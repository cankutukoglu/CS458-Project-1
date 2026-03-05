import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, redirect, session, url_for, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from config import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CHALLENGED,
    ACCOUNT_LOCKED,
    ACCOUNT_SUSPENDED,
    RISK_HIGH,
    RISK_CRITICAL,
    SCORE_PER_FAILED_ATTEMPT,
    LOCK_DURATION_SECONDS,
)
from extensions import db, oauth
from models.user import User

log = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


def get_client_ip():
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )


def _failed_login_response(user, action, risk_score, risk_factors, fraud_analysis, recaptcha_error=None):
    """Build the HTTP response for any failed login path."""
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
    response = {**base, "error": recaptcha_error or "Invalid credentials"}
    if recaptcha_error:
        response["code"] = "recaptcha_failed"
        response["challenge_required"] = True
        response["account_status"] = ACCOUNT_CHALLENGED
    elif user and user.account_status == ACCOUNT_CHALLENGED:
        response["account_status"] = ACCOUNT_CHALLENGED
        response["challenge_required"] = bool(current_app.recaptcha_service.is_enabled())

    if user and user.failed_attempts > 0:
        current_score = min(user.failed_attempts * SCORE_PER_FAILED_ATTEMPT, RISK_CRITICAL)
        if current_score >= RISK_HIGH:
            pts_to_lock = max(0, RISK_CRITICAL - current_score)
            attempts_to_lock = max(0, -(-pts_to_lock // SCORE_PER_FAILED_ATTEMPT))
            response.setdefault("account_status", user.account_status)
            response["warning"] = (
                f"Risk score is {current_score}/100. "
                f"Account will be locked in ~{attempts_to_lock} more failed attempt(s)."
            )

    return jsonify(response), 401


@auth_bp.route("/api/health")
def health():
    return {"status": "ok"}, 200


@auth_bp.route("/api/recaptcha-config", methods=["GET"])
def recaptcha_config():
    svc = current_app.recaptcha_service
    return jsonify({
        "enabled": svc.is_enabled(),
        "site_key": svc.site_key if svc.is_enabled() else "",
        "mode": "challenged_login_only",
    }), 200


@auth_bp.route("/api/register", methods=["POST"])
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


@auth_bp.route("/api/login", methods=["POST"])
def login():
    recaptcha_svc = current_app.recaptcha_service
    account_svc = current_app.account_service
    risk_eng = current_app.risk_engine
    fraud_svc = current_app.fraud_analysis_service

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
        email = user.email if user else phone

    if user and user.account_status == ACCOUNT_SUSPENDED:
        return account_svc.deny_login_for_status(
            user, email, ip_address, user_agent,
            ACCOUNT_SUSPENDED, "Account is suspended. Please contact support.",
        )

    if user and user.account_status == ACCOUNT_LOCKED:
        if account_svc.maybe_unlock_account(user):
            log.info("Temporary lock expired — continuing login for %s", email)
        else:
            remaining_secs = 0
            if user.locked_until:
                lu = user.locked_until
                if lu.tzinfo is None:
                    lu = lu.replace(tzinfo=timezone.utc)
                remaining_secs = max(0, int((lu - datetime.now(timezone.utc)).total_seconds()))
            risk_score, risk_factors = risk_eng.compute_score(user, email, ip_address, user_agent)
            account_svc.create_login_log(
                user=user, email=email, ip_address=ip_address, user_agent=user_agent,
                success=False, risk_score=risk_score, risk_factors=risk_factors,
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
                "risk_score": risk_score,
                "risk_factors": risk_factors,
            }), 403

    if user and user.account_status == ACCOUNT_CHALLENGED and recaptcha_svc.is_enabled():
        recaptcha_token = (data.get("recaptcha_token") or "").strip()
        recaptcha_ok, recaptcha_error = recaptcha_svc.verify_token(recaptcha_token, ip_address)
        if not recaptcha_ok:
            user.failed_attempts += 1
            risk_score, risk_factors = risk_eng.compute_score(user, email, ip_address, user_agent)
            risk_factors = list(risk_factors) + [
                "RECAPTCHA_FAILED: Required challenge not completed or invalid"
            ]
            fraud_analysis = (
                fraud_svc.analyze(email, ip_address, user_agent, risk_score, risk_factors)
                if risk_score >= RISK_HIGH
                else None
            )
            action = risk_eng.apply_action(user, risk_score, fraud_analysis)
            account_svc.create_login_log(
                user=user, email=email, ip_address=ip_address, user_agent=user_agent,
                success=False, risk_score=risk_score, risk_factors=risk_factors,
                fraud_analysis=fraud_analysis, action_taken=action,
            )
            db.session.commit()
            return _failed_login_response(
                user, action, risk_score, risk_factors, fraud_analysis,
                recaptcha_error=recaptcha_error,
            )

    if not user or not check_password_hash(user.password_hash, password):
        if user:
            user.failed_attempts += 1
        risk_score, risk_factors = risk_eng.compute_score(user, email, ip_address, user_agent)
        fraud_analysis = (
            fraud_svc.analyze(email, ip_address, user_agent, risk_score, risk_factors)
            if risk_score >= RISK_HIGH
            and user
            and user.account_status == ACCOUNT_CHALLENGED
            and recaptcha_svc.is_enabled()
            else None
        )
        action = risk_eng.apply_action(user, risk_score, fraud_analysis) if user else "denied"
        account_svc.create_login_log(
            user=user, email=email, ip_address=ip_address, user_agent=user_agent,
            success=False, risk_score=risk_score, risk_factors=risk_factors,
            fraud_analysis=fraud_analysis, action_taken=action,
        )
        db.session.commit()
        return _failed_login_response(user, action, risk_score, risk_factors, fraud_analysis)

    risk_score, risk_factors = risk_eng.compute_score(user, email, ip_address, user_agent)
    fraud_analysis = None
    action = "allowed"

    user.failed_attempts = 0
    user.lock_count = 0
    user.locked_until = None
    if user.account_status == ACCOUNT_CHALLENGED:
        user.account_status = ACCOUNT_ACTIVE

    account_svc.create_login_log(
        user=user, email=email, ip_address=ip_address, user_agent=user_agent,
        success=True, risk_score=risk_score, risk_factors=risk_factors,
        fraud_analysis=fraud_analysis, action_taken=action,
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


@auth_bp.route("/api/me")
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


@auth_bp.route("/api/login/google")
def login_google():
    redirect_uri = url_for("auth.auth_google", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/api/login/google/callback")
def auth_google():
    ip_address = get_client_ip()
    user_agent = request.headers.get("User-Agent", "")

    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get("userinfo")
        if not user_info:
            resp = oauth.google.get("userinfo")
            user_info = resp.json()
    except Exception as e:
        log.error("Google OAuth callback failed: %s", e)
        return redirect("/index.html?error=Google+login+failed")

    email = user_info.get("email")
    if not email:
        return redirect("/index.html?error=No+email+provided+from+Google")

    email = email.strip().lower()
    oauth_svc = current_app.oauth_service
    user = oauth_svc.find_or_create_user(email, "google", user_info.get("sub"))
    return oauth_svc.finalize_with_risk(user, email, ip_address, user_agent, "google")


@auth_bp.route("/api/login/github")
def login_github():
    if not os.environ.get("GITHUB_CLIENT_ID") or not os.environ.get("GITHUB_CLIENT_SECRET"):
        return redirect("/index.html?error=GitHub+OAuth+is+not+configured")
    redirect_uri = url_for("auth.auth_github", _external=True)
    return oauth.github.authorize_redirect(redirect_uri)


@auth_bp.route("/api/login/github/callback")
def auth_github():
    ip_address = get_client_ip()
    user_agent = request.headers.get("User-Agent", "")

    try:
        token = oauth.github.authorize_access_token()
        user_info_resp = oauth.github.get("user", token=token)
        user_info = user_info_resp.json() if user_info_resp else {}
    except Exception as e:
        log.error("GitHub OAuth callback failed: %s", e)
        return redirect("/index.html?error=GitHub+login+failed")

    email = user_info.get("email")
    if not email:
        try:
            emails_resp = oauth.github.get("user/emails", token=token)
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
    oauth_svc = current_app.oauth_service
    user = oauth_svc.find_or_create_user(email, "github", str(user_info.get("id", "")))
    return oauth_svc.finalize_with_risk(user, email, ip_address, user_agent, "github")
