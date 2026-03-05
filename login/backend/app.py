import os
import json
import logging
from datetime import datetime, timezone, timedelta
from urllib import request as url_request, error as url_error, parse as url_parse

from flask import Flask, request, jsonify, redirect, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# LLM Provider Configuration - Azure OpenAI takes priority
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "").strip()
RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY", "").strip()
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

_llm_provider = None
_gemini_client = None

if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT:
    _llm_provider = "azure_openai"
    log.info("Azure OpenAI configured – LLM fraud analysis enabled (deployment: %s)", AZURE_OPENAI_DEPLOYMENT)
elif GEMINI_API_KEY:
    try:
        from google import genai
        from google.genai import types as genai_types
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        _llm_provider = "gemini"
        log.info("Gemini API configured – LLM fraud analysis enabled (model: %s)", GEMINI_MODEL)
    except ImportError:
        log.warning("google-genai package not installed – falling back to simulated fraud analysis")
else:
    log.warning("No LLM API keys set – falling back to simulated fraud analysis")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
CORS(app)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///ares.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

github = oauth.register(
    name='github',
    client_id=os.environ.get("GITHUB_CLIENT_ID"),
    client_secret=os.environ.get("GITHUB_CLIENT_SECRET"),
    access_token_url='https://github.com/login/oauth/access_token',
    authorize_url='https://github.com/login/oauth/authorize',
    api_base_url='https://api.github.com/',
    client_kwargs={'scope': 'read:user user:email'},
)

ACCOUNT_ACTIVE = "active"
ACCOUNT_CHALLENGED = "challenged"
ACCOUNT_LOCKED = "locked"
ACCOUNT_SUSPENDED = "suspended"

RISK_LOW = 20
RISK_MEDIUM = 40
RISK_HIGH = 60
RISK_CRITICAL = 90

FAILED_ATTEMPTS_LOCK = 10
FAILED_ATTEMPTS_CHALLENGE = 5
VELOCITY_WINDOW_SECONDS = 300
VELOCITY_MAX_ATTEMPTS = 8
LOCK_DURATION_SECONDS = 15  # First offence: temporary 2-minute lock; second offence: permanent suspension



class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(30), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    account_status = db.Column(db.String(20), default=ACCOUNT_ACTIVE, nullable=False)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    locked_until = db.Column(db.DateTime, nullable=True)
    lock_count = db.Column(db.Integer, default=0, nullable=False)

    login_logs = db.relationship("LoginLog", backref="user", lazy="dynamic")


class LoginLog(db.Model):
    __tablename__ = "login_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    email_attempted = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(512), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    success = db.Column(db.Boolean, nullable=False)
    risk_score = db.Column(db.Integer, default=0)
    risk_factors = db.Column(db.Text, default="[]")
    fraud_analysis = db.Column(db.Text, nullable=True)
    action_taken = db.Column(db.String(30), default="allowed")



def get_client_ip():
    return request.headers.get("X-Real-IP") or \
           request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or \
           request.remote_addr or "unknown"


def create_login_log(
    *,
    user,
    email,
    ip_address,
    user_agent,
    success,
    risk_score=0,
    risk_factors=None,
    fraud_analysis=None,
    action_taken="allowed",
):
    login_log = LoginLog(
        user_id=user.id if user else None,
        email_attempted=email,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        risk_score=risk_score,
        risk_factors=json.dumps(risk_factors or []),
        fraud_analysis=json.dumps(fraud_analysis) if fraud_analysis else None,
        action_taken=action_taken,
    )
    db.session.add(login_log)
    return login_log


def is_recaptcha_enabled():
    return bool(RECAPTCHA_SITE_KEY and RECAPTCHA_SECRET_KEY)


def verify_recaptcha_token(token, remote_ip):
    if not is_recaptcha_enabled():
        return True, None

    if not token:
        return False, "Please complete the reCAPTCHA challenge."

    payload = {
        "secret": RECAPTCHA_SECRET_KEY,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    encoded_payload = url_parse.urlencode(payload).encode("utf-8")
    verify_request = url_request.Request(
        RECAPTCHA_VERIFY_URL,
        data=encoded_payload,
        method="POST",
    )

    try:
        with url_request.urlopen(verify_request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (url_error.URLError, TimeoutError, ValueError) as exc:
        log.warning("reCAPTCHA verification failed due to upstream/network issue: %s", exc)
        return False, "Could not verify reCAPTCHA. Please try again."

    if not result.get("success", False):
        log.info("reCAPTCHA validation rejected token with errors: %s", result.get("error-codes", []))
        return False, "reCAPTCHA challenge failed. Please try again."

    return True, None


def deny_login_for_status(user, email, ip_address, user_agent, account_status, error_message):
    risk_factor = "SUSPENDED_ACCOUNT" if account_status == ACCOUNT_SUSPENDED else "LOCKED_ACCOUNT"
    create_login_log(
        user=user,
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        success=False,
        risk_score=100,
        risk_factors=[risk_factor],
        action_taken="denied",
    )
    db.session.commit()
    return jsonify({
        "error": error_message,
        "account_status": account_status,
    }), 403


def maybe_unlock_account(user) -> bool:
    """Auto-unlock a temporarily locked account if the lock duration has expired.

    Returns True if the account was unlocked so the caller can continue the
    login flow normally; False if the lock is still active.
    """
    if user.account_status != ACCOUNT_LOCKED or not user.locked_until:
        return False
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= locked_until:
        user.account_status = ACCOUNT_ACTIVE
        user.failed_attempts = 0
        user.locked_until = None
        db.session.commit()
        log.info("Account auto-unlocked after lock expiry: %s", user.email)
        return True
    return False


def lock_or_suspend_user(user) -> str:
    """Lock the account temporarily on first offence; suspend permanently on second.

    First lock  → account_status = ACCOUNT_LOCKED, locked_until = now + LOCK_DURATION_SECONDS,
                  lock_count incremented to 1.
    Second lock → account_status = ACCOUNT_SUSPENDED, locked_until cleared (permanent).

    Returns the new account_status string ("locked" or "suspended").
    """
    if user.lock_count >= 1:
        user.account_status = ACCOUNT_SUSPENDED
        user.locked_until = None
        log.info("Account suspended after second lockout: %s", user.email)
        return ACCOUNT_SUSPENDED
    user.account_status = ACCOUNT_LOCKED
    user.locked_until = datetime.now(timezone.utc) + timedelta(seconds=LOCK_DURATION_SECONDS)
    user.lock_count += 1
    log.info("Account locked until %s (lock #%d): %s",
             user.locked_until.isoformat(), user.lock_count, user.email)
    return ACCOUNT_LOCKED


def find_or_create_oauth_user(email, provider, provider_id=None):
    email = (email or "").strip().lower()
    user = User.query.filter_by(email=email).first()
    if user:
        return user

    # Keep the synthetic phone unique for each OAuth-created account.
    synthetic_suffix = (provider_id or os.urandom(4).hex()).replace(" ", "")[:12]
    synthetic_phone = f"oauth-{provider}-{synthetic_suffix}"
    user = User(
        email=email,
        phone=synthetic_phone,
        password_hash=generate_password_hash(os.urandom(32).hex()),
    )
    db.session.add(user)
    db.session.commit()
    return user


def finalize_oauth_login(user, email, ip_address, user_agent, action_taken):
    create_login_log(
        user=user,
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        success=True,
        action_taken=action_taken,
    )
    db.session.commit()
    session["user_id"] = user.id
    session["email"] = email


def simulate_fraud_analysis(prompt_context):
    recommendation = "allow_with_monitoring"
    verdict = "LOW_RISK"

    if prompt_context["risk_score"] >= RISK_CRITICAL:
        verdict = "HIGH_RISK"
        recommendation = "lock_account"
    elif prompt_context["risk_score"] >= RISK_HIGH:
        verdict = "MEDIUM_RISK"
        recommendation = "challenge_user"

    reasoning = (
        f"Rule-based fallback evaluated risk score {prompt_context['risk_score']}/100 "
        f"with factors: {', '.join(prompt_context['risk_factors']) or 'none'}."
    )

    return {
        "verdict": verdict,
        "reasoning": reasoning,
        "recommendation": recommendation,
        "prompt_context": prompt_context,
        "model": "rule-based-fallback",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


def compute_risk_score(user, email, ip_address, user_agent):
    score = 0
    factors = []

    if user:
        if user.failed_attempts >= FAILED_ATTEMPTS_LOCK:
            score += 90  # Alone reaches RISK_CRITICAL → LLM will recommend lock_account
            factors.append(f"CRITICAL: {user.failed_attempts} consecutive failed attempts (>= {FAILED_ATTEMPTS_LOCK})")
        elif user.failed_attempts >= FAILED_ATTEMPTS_CHALLENGE:
            score += 60  # Alone reaches RISK_HIGH → LLM will recommend challenge_user
            factors.append(f"HIGH: {user.failed_attempts} consecutive failed attempts (>= {FAILED_ATTEMPTS_CHALLENGE})")
        elif user.failed_attempts >= 3:
            score += 15
            factors.append(f"MEDIUM: {user.failed_attempts} consecutive failed attempts")

    if user:
        known_ip = LoginLog.query.filter_by(
            user_id=user.id, ip_address=ip_address, success=True
        ).first()
        if not known_ip:
            has_any_login = LoginLog.query.filter_by(
                user_id=user.id, success=True
            ).first()
            if has_any_login:
                score += 25
                factors.append(f"NEW_IP: Login from unrecognized IP {ip_address}")

    window_start = datetime.now(timezone.utc) - timedelta(seconds=VELOCITY_WINDOW_SECONDS)
    recent_attempts = LoginLog.query.filter(
        LoginLog.email_attempted == email,
        LoginLog.timestamp >= window_start
    ).count()
    if recent_attempts >= VELOCITY_MAX_ATTEMPTS:
        score += 30
        factors.append(f"VELOCITY: {recent_attempts} attempts in last {VELOCITY_WINDOW_SECONDS}s (threshold: {VELOCITY_MAX_ATTEMPTS})")
    elif recent_attempts >= VELOCITY_MAX_ATTEMPTS // 2:
        score += 10
        factors.append(f"VELOCITY_WARN: {recent_attempts} attempts in last {VELOCITY_WINDOW_SECONDS}s")

    if user:
        last_successful = LoginLog.query.filter_by(
            user_id=user.id, success=True
        ).order_by(LoginLog.timestamp.desc()).first()
        if last_successful and last_successful.user_agent and user_agent:
            if last_successful.user_agent != user_agent:
                score += 10
                factors.append("UA_CHANGE: User-agent differs from last successful login")

    if user and user.account_status == ACCOUNT_LOCKED:
        score += 20
        factors.append("LOCKED_ACCOUNT: Attempt on a locked account")
    elif user and user.account_status == ACCOUNT_SUSPENDED:
        score += 40
        factors.append("SUSPENDED_ACCOUNT: Attempt on a suspended account")

    return min(score, 100), factors



FRAUD_SYSTEM_PROMPT = """You are a fraud detection analyst for the ARES authentication system.
Analyze the login attempt context provided and return your assessment as a JSON object with exactly these keys:

- "verdict": one of "HIGH_RISK", "MEDIUM_RISK", or "LOW_RISK"
- "reasoning": a 2-3 sentence explanation of your analysis
- "recommendation": one of "lock_account", "challenge_user", or "allow_with_monitoring"

Rules:
- If there are 10+ consecutive failed attempts or signs of brute-force, verdict must be HIGH_RISK with recommendation lock_account.
- If there is high login velocity (many attempts in short time), verdict should be at least MEDIUM_RISK with recommendation challenge_user.
- A new IP alone with no other factors is LOW_RISK with recommendation allow_with_monitoring.
- Combine multiple factors: new IP + failed attempts + velocity = higher risk.

Return ONLY the JSON object, no markdown fences, no extra text."""


def _call_azure_openai(prompt_context: dict) -> str:
    """Call Azure OpenAI API for fraud analysis. Returns raw text content."""
    url = f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
    body = {
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": FRAUD_SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this login attempt:\n{json.dumps(prompt_context, indent=2)}"},
        ],
    }
    encoded = json.dumps(body).encode("utf-8")
    req = url_request.Request(
        url,
        data=encoded,
        headers={
            "api-key": AZURE_OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with url_request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    content: str = data["choices"][0]["message"]["content"]
    return content


def llm_fraud_analysis(email, ip_address, user_agent, risk_score, risk_factors):
    """
    Call LLM API for fraud analysis.
    Supports Azure OpenAI and Gemini. Falls back to rule-based simulation if no API configured.
    """
    prompt_context = {
        "email": email,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "risk_score": risk_score,
        "risk_factors": risk_factors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if _llm_provider == "azure_openai":
        try:
            raw_text = _call_azure_openai(prompt_context)
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                raw_text = raw_text.rsplit("```", 1)[0].strip()

            result = json.loads(raw_text)

            for key in ("verdict", "reasoning", "recommendation"):
                if key not in result:
                    raise ValueError(f"Missing key '{key}' in Azure OpenAI response")

            result["prompt_context"] = prompt_context
            result["model"] = AZURE_OPENAI_DEPLOYMENT
            result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
            log.info("Azure OpenAI fraud analysis: verdict=%s recommendation=%s",
                     result["verdict"], result["recommendation"])
            return result

        except Exception as e:
            log.error("Azure OpenAI API call failed, falling back to simulation: %s", e)

    elif _llm_provider == "gemini" and _gemini_client:
        try:
            response = _gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"Analyze this login attempt:\n{json.dumps(prompt_context, indent=2)}",
                config=genai_types.GenerateContentConfig(
                    system_instruction=FRAUD_SYSTEM_PROMPT,
                    temperature=0.2,
                ),
            )

            raw_text = response.text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                raw_text = raw_text.rsplit("```", 1)[0].strip()

            result = json.loads(raw_text)

            for key in ("verdict", "reasoning", "recommendation"):
                if key not in result:
                    raise ValueError(f"Missing key '{key}' in Gemini response")

            result["prompt_context"] = prompt_context
            result["model"] = GEMINI_MODEL
            result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
            log.info("Gemini fraud analysis: verdict=%s recommendation=%s",
                     result["verdict"], result["recommendation"])
            return result

        except Exception as e:
            log.error("Gemini API call failed, falling back to simulation: %s", e)

    return simulate_fraud_analysis(prompt_context)


def apply_risk_action(user, risk_score, fraud_result):
    if not user:
        return "denied"

    recommendation = fraud_result.get("recommendation", "") if fraud_result else ""

    # Critical: lock the account (or suspend on second offence)
    if risk_score >= RISK_CRITICAL or recommendation == "lock_account":
        new_status = lock_or_suspend_user(user)
        db.session.commit()
        return new_status  # ACCOUNT_LOCKED or ACCOUNT_SUSPENDED

    # High risk: challenge the user
    if risk_score >= RISK_HIGH or recommendation == "challenge_user":
        if user.account_status == ACCOUNT_ACTIVE:
            user.account_status = ACCOUNT_CHALLENGED
            db.session.commit()
        return "challenged"

    return "allowed"


@app.route("/api/health")
def health():
    return {"status": "ok"}, 200


@app.route("/api/recaptcha-config", methods=["GET"])
def recaptcha_config():
    return jsonify({
        "enabled": is_recaptcha_enabled(),
        "site_key": RECAPTCHA_SITE_KEY if is_recaptcha_enabled() else "",
        "mode": "challenged_login_only",
    }), 200


def _failed_login_response(user, action, risk_score, risk_factors, fraud_analysis, recaptcha_error=None):
    """Build the HTTP response for any failed login path.

    action is the string returned by apply_risk_action():
      ACCOUNT_LOCKED / ACCOUNT_SUSPENDED → 403
      "challenged" / "denied"            → 401
    recaptcha_error is set only when the failure was a reCAPTCHA rejection.
    """
    base = {
        "risk_score": risk_score,
        **({"risk_factors": risk_factors} if risk_factors else {}),
        **({"fraud_analysis": fraud_analysis} if fraud_analysis else {}),
    }

    if action == ACCOUNT_SUSPENDED:
        return jsonify({
            **base,
            "error": "Account suspended due to repeated suspicious activity. Please contact support.",
            "account_status": ACCOUNT_SUSPENDED,
        }), 403

    if action == ACCOUNT_LOCKED:
        return jsonify({
            **base,
            "error": (
                f"Account locked due to suspicious activity. "
                f"It will auto-unlock in {LOCK_DURATION_SECONDS // 60} minute(s)."
            ),
            "account_status": ACCOUNT_LOCKED,
            "locked_until": user.locked_until.isoformat() if user and user.locked_until else None,
        }), 403

    # "challenged" or "denied" — 401
    response = {
        **base,
        "error": recaptcha_error or "Invalid credentials",
    }
    if recaptcha_error:
        response["code"] = "recaptcha_failed"
        response["challenge_required"] = True
        response["account_status"] = ACCOUNT_CHALLENGED
    elif user and user.account_status == ACCOUNT_CHALLENGED:
        response["account_status"] = ACCOUNT_CHALLENGED
        response["challenge_required"] = bool(is_recaptcha_enabled())

    if user and user.failed_attempts >= FAILED_ATTEMPTS_CHALLENGE:
        remaining = max(0, FAILED_ATTEMPTS_LOCK - user.failed_attempts)
        response.setdefault("account_status", user.account_status)
        response["warning"] = f"Account will be locked after {remaining} more failed attempts"

    return jsonify(response), 401


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""

    if not email:
        return jsonify({"error": "Email is required"}), 400
    if not phone:
        return jsonify({"error": "Phone is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists"}), 409

    if User.query.filter_by(phone=phone).first():
        return jsonify({"error": "An account with this phone number already exists"}), 409

    user = User(
        email=email,
        phone=phone,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "Account created successfully", "email": user.email}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""

    if not email and not phone:
        return jsonify({"error": "Email or phone is required"}), 400
    if not password:
        return jsonify({"error": "Password is required"}), 400

    ip_address = get_client_ip()
    user_agent = request.headers.get("User-Agent", "")

    if email:
        user = User.query.filter_by(email=email).first()
    else:
        user = User.query.filter_by(phone=phone).first()
        # Use the user's email for logging if found, otherwise use the phone as identifier
        email = user.email if user else phone

    if user and user.account_status == ACCOUNT_SUSPENDED:
        return deny_login_for_status(
            user,
            email,
            ip_address,
            user_agent,
            ACCOUNT_SUSPENDED,
            "Account is suspended. Please contact support.",
        )

    if user and user.account_status == ACCOUNT_LOCKED:
        if maybe_unlock_account(user):
            log.info("Temporary lock expired — continuing login for %s", email)
        else:
            # Lock still active; calculate remaining seconds for the response
            remaining_secs = 0
            if user.locked_until:
                lu = user.locked_until
                if lu.tzinfo is None:
                    lu = lu.replace(tzinfo=timezone.utc)
                remaining_secs = max(0, int((lu - datetime.now(timezone.utc)).total_seconds()))
            create_login_log(
                user=user,
                email=email,
                ip_address=ip_address,
                user_agent=user_agent,
                success=False,
                risk_score=100,
                risk_factors=["LOCKED_ACCOUNT"],
                action_taken="denied",
            )
            db.session.commit()
            return jsonify({
                "error": (
                    f"Account is locked due to suspicious activity. "
                    f"It will auto-unlock in {remaining_secs} second(s). "
                    f"Contact support if you need immediate access."
                ),
                "account_status": ACCOUNT_LOCKED,
                "locked_until": user.locked_until.isoformat() if user.locked_until else None,
                "risk_score": 100,
                "risk_factors": ["LOCKED_ACCOUNT"],
            }), 403

    # ------------------------------------------------------------------ #
    #  Step 1 — reCAPTCHA gate (challenged accounts + recaptcha enabled) #
    # ------------------------------------------------------------------ #
    if user and user.account_status == ACCOUNT_CHALLENGED and is_recaptcha_enabled():
        recaptcha_token = (data.get("recaptcha_token") or "").strip()
        recaptcha_ok, recaptcha_error = verify_recaptcha_token(recaptcha_token, ip_address)
        if not recaptcha_ok:
            user.failed_attempts += 1
            risk_score, risk_factors = compute_risk_score(user, email, ip_address, user_agent)
            risk_factors = list(risk_factors) + [
                "RECAPTCHA_FAILED: Required challenge not completed or invalid"
            ]
            fraud_analysis = (
                llm_fraud_analysis(email, ip_address, user_agent, risk_score, risk_factors)
                if risk_score >= RISK_HIGH else None
            )
            action = apply_risk_action(user, risk_score, fraud_analysis)
            create_login_log(
                user=user, email=email, ip_address=ip_address, user_agent=user_agent,
                success=False, risk_score=risk_score, risk_factors=risk_factors,
                fraud_analysis=fraud_analysis, action_taken=action,
            )
            db.session.commit()
            return _failed_login_response(
                user, action, risk_score, risk_factors, fraud_analysis,
                recaptcha_error=recaptcha_error,
            )

    # ------------------------------------------------------------------ #
    #  Step 2 — Password check                                            #
    #  Increment failed_attempts FIRST so compute_risk_score sees the     #
    #  up-to-date count (as the PDF requires: "10th failed attempt"       #
    #  must be reflected in the risk score that triggers the LLM).        #
    # ------------------------------------------------------------------ #
    if not user or not check_password_hash(user.password_hash, password):
        if user:
            user.failed_attempts += 1
        risk_score, risk_factors = compute_risk_score(user, email, ip_address, user_agent)
        # LLM only fires after reCAPTCHA has been generated (shown) at least once.
        # That requires two conditions:
        #   1. reCAPTCHA is enabled — so it was actually presented to the user.
        #   2. account is CHALLENGED — meaning a prior high-risk attempt already
        #      triggered the CAPTCHA challenge flow.
        # Without both, we know reCAPTCHA was never generated, so the LLM stays silent.
        fraud_analysis = (
            llm_fraud_analysis(email, ip_address, user_agent, risk_score, risk_factors)
            if risk_score >= RISK_HIGH
            and user
            and user.account_status == ACCOUNT_CHALLENGED
            and is_recaptcha_enabled()
            else None
        )
        action = apply_risk_action(user, risk_score, fraud_analysis) if user else "denied"
        create_login_log(
            user=user, email=email, ip_address=ip_address, user_agent=user_agent,
            success=False, risk_score=risk_score, risk_factors=risk_factors,
            fraud_analysis=fraud_analysis, action_taken=action,
        )
        db.session.commit()
        return _failed_login_response(user, action, risk_score, risk_factors, fraud_analysis)

    # Compute risk score for the success log (reflects state before reset,
    # e.g. a user with 3 prior failures still shows MEDIUM risk on success).
    risk_score, risk_factors = compute_risk_score(user, email, ip_address, user_agent)
    fraud_analysis = None
    action = "allowed"

    user.failed_attempts = 0
    user.lock_count = 0
    user.locked_until = None
    if user.account_status == ACCOUNT_CHALLENGED:
        user.account_status = ACCOUNT_ACTIVE

    create_login_log(
        user=user,
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        success=True,
        risk_score=risk_score,
        risk_factors=risk_factors,
        fraud_analysis=fraud_analysis,
        action_taken=action,
    )
    db.session.commit()

    response = {
        "message": "Login successful",
        "user": {
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "account_status": user.account_status,
        },
        "risk_score": risk_score,
    }
    if risk_factors:
        response["risk_factors"] = risk_factors
    if fraud_analysis:
        response["fraud_analysis"] = fraud_analysis

    return jsonify(response), 200



@app.route("/api/login-logs", methods=["GET"])
def get_login_logs():
    """View login logs with optional filters."""
    email = request.args.get("email", "").strip().lower()
    limit = min(int(request.args.get("limit", 50)), 200)

    query = LoginLog.query.order_by(LoginLog.timestamp.desc())
    if email:
        query = query.filter_by(email_attempted=email)

    logs = query.limit(limit).all()

    return jsonify([
        {
            "id": log.id,
            "user_id": log.user_id,
            "email": log.email_attempted,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "success": log.success,
            "risk_score": log.risk_score,
            "risk_factors": json.loads(log.risk_factors) if log.risk_factors else [],
            "fraud_analysis": json.loads(log.fraud_analysis) if log.fraud_analysis else None,
            "action_taken": log.action_taken,
        }
        for log in logs
    ]), 200



@app.route("/api/admin/user-status", methods=["POST"])
def update_user_status():
    """Admin endpoint to change user account state."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = (data.get("email") or "").strip().lower()
    new_status = data.get("status", "").strip().lower()

    valid_statuses = [ACCOUNT_ACTIVE, ACCOUNT_CHALLENGED, ACCOUNT_LOCKED, ACCOUNT_SUSPENDED]
    if new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status. Must be one of: {valid_statuses}"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    old_status = user.account_status
    user.account_status = new_status
    if new_status == ACCOUNT_ACTIVE:
        user.failed_attempts = 0
        user.lock_count = 0
        user.locked_until = None
    db.session.commit()

    return jsonify({
        "message": f"Account status changed from '{old_status}' to '{new_status}'",
        "email": user.email,
        "account_status": user.account_status,
    }), 200



@app.route("/api/risk-config", methods=["GET"])
def risk_config():
    return jsonify({
        "thresholds": {
            "low": RISK_LOW,
            "medium": RISK_MEDIUM,
            "high": RISK_HIGH,
            "critical": RISK_CRITICAL,
        },
        "failed_attempts_to_challenge": FAILED_ATTEMPTS_CHALLENGE,
        "failed_attempts_to_lock": FAILED_ATTEMPTS_LOCK,
        "velocity_window_seconds": VELOCITY_WINDOW_SECONDS,
        "velocity_max_attempts": VELOCITY_MAX_ATTEMPTS,
        "account_states": [ACCOUNT_ACTIVE, ACCOUNT_CHALLENGED, ACCOUNT_LOCKED, ACCOUNT_SUSPENDED],
    }), 200

@app.route("/api/login/google")
def login_google():
    redirect_uri = url_for("auth_google", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/api/login/google/callback")
def auth_google():
    ip_address = get_client_ip()
    user_agent = request.headers.get("User-Agent", "")

    try:
        token = google.authorize_access_token()
        user_info = token.get("userinfo")
        if not user_info:
            resp = google.get("userinfo")
            user_info = resp.json()
    except Exception as e:
        log.error("Google OAuth callback failed: %s", e)
        return redirect("/index.html?error=Google+login+failed")

    email = user_info.get("email")
    if not email:
        return redirect("/index.html?error=No+email+provided+from+Google")

    email = email.strip().lower()
    user = find_or_create_oauth_user(email, "google", user_info.get("sub"))
    finalize_oauth_login(user, email, ip_address, user_agent, "oauth_google")

    return redirect("/index.html?login_success=true")


@app.route("/api/login/github")
def login_github():
    if not os.environ.get("GITHUB_CLIENT_ID") or not os.environ.get("GITHUB_CLIENT_SECRET"):
        return redirect("/index.html?error=GitHub+OAuth+is+not+configured")
    redirect_uri = url_for("auth_github", _external=True)
    return github.authorize_redirect(redirect_uri)


@app.route("/api/login/github/callback")
def auth_github():
    ip_address = get_client_ip()
    user_agent = request.headers.get("User-Agent", "")

    try:
        token = github.authorize_access_token()
        user_info_resp = github.get("user", token=token)
        user_info = user_info_resp.json() if user_info_resp else {}
    except Exception as e:
        log.error("GitHub OAuth callback failed: %s", e)
        return redirect("/index.html?error=GitHub+login+failed")

    email = user_info.get("email")
    if not email:
        try:
            emails_resp = github.get("user/emails", token=token)
            emails = emails_resp.json() if emails_resp else []
            primary_verified = next(
                (item for item in emails if item.get("primary") and item.get("verified")),
                None,
            )
            any_verified = next((item for item in emails if item.get("verified")), None)
            chosen = primary_verified or any_verified
            email = chosen.get("email") if chosen else None
        except Exception as e:
            log.error("GitHub email lookup failed: %s", e)
            email = None

    if not email:
        return redirect("/index.html?error=No+public+or+verified+email+from+GitHub")

    email = email.strip().lower()
    user = find_or_create_oauth_user(email, "github", str(user_info.get("id", "")))
    finalize_oauth_login(user, email, ip_address, user_agent, "oauth_github")
    return redirect("/index.html?login_success=true")


@app.route("/api/me")
def me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        "id": user.id,
        "email": user.email,
        "account_status": user.account_status,
    }), 200


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5001, debug=True)
