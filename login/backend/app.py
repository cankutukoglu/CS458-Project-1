import os
from datetime import datetime, timezone

from flask import Flask, request, jsonify, redirect, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth

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
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    client_kwargs={'scope': 'openid email profile'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
)

facebook = oauth.register(
    name='facebook',
    client_id=os.environ.get("FACEBOOK_CLIENT_ID"),
    client_secret=os.environ.get("FACEBOOK_CLIENT_SECRET"),
    access_token_url='https://graph.facebook.com/v12.0/oauth/access_token',
    access_token_params=None,
    authorize_url='https://www.facebook.com/v12.0/dialog/oauth',
    authorize_params=None,
    api_base_url='https://graph.facebook.com/v12.0/',
    client_kwargs={'scope': 'email public_profile'}
)

# ── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(20), default="Active")
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return {"status": "ok"}, 200


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""

    # Validation
    if not email:
        return jsonify({"error": "Email is required"}), 400
    if not phone:
        return jsonify({"error": "Phone is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    # Check for duplicate email
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists"}), 409

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
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    return jsonify({
        "message": "Login successful",
        "user": {
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
        },
    }), 200

@app.route("/api/login/google")
def login_google():
    redirect_uri = url_for("auth_google", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/api/login/google/callback")
def auth_google():
    try:
        token = google.authorize_access_token()
        user_info = google.parse_id_token(token, nonce=None)
        if not user_info:
            resp = google.get("userinfo")
            user_info = resp.json()
    except Exception as e:
        return redirect("/index.html?error=Google+login+failed")
    
    email = user_info.get("email")
    if not email:
        return redirect("/index.html?error=No+email+provided+from+Google")
    
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            phone="oauth-dummy-phone",
            password_hash="oauth",
        )
        db.session.add(user)
        db.session.commit()
    
    return redirect(f"/index.html?login_success=true&email={email}")

@app.route("/api/login/facebook")
def login_facebook():
    redirect_uri = url_for("auth_facebook", _external=True)
    return facebook.authorize_redirect(redirect_uri)

@app.route("/api/login/facebook/callback")
def auth_facebook():
    try:
        token = facebook.authorize_access_token()
        resp = facebook.get("me?fields=id,name,email")
        user_info = resp.json()
    except Exception as e:
        return redirect("/index.html?error=Facebook+login+failed")
    
    email = user_info.get("email")
    if not email:
        # Fallback if no email is provided (Facebook allows sign-up with phone only sometimes)
        email = f"{user_info.get('id')}@facebook.invalid"
    
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            phone="oauth-dummy-phone",
            password_hash="oauth",
        )
        db.session.add(user)
        db.session.commit()
    
    return redirect(f"/index.html?login_success=true&email={email}")


# ── Start ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)
