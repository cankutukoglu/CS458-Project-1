import os
import logging

from flask import Flask
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from extensions import db, oauth
from models.user import User
from models.login_log import LoginLog
from services.recaptcha_service import ReCaptchaService
from services.fraud_analysis_service import FraudAnalysisService
from services.account_service import AccountService
from services.risk_engine import RiskEngine
from services.oauth_service import OAuthService
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp

logging.basicConfig(level=logging.INFO)


def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    CORS(app)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///ares.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    oauth.init_app(app)

    oauth.register(
        name="google",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    oauth.register(
        name="github",
        client_id=os.environ.get("GITHUB_CLIENT_ID"),
        client_secret=os.environ.get("GITHUB_CLIENT_SECRET"),
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "read:user user:email"},
    )


    recaptcha_svc = ReCaptchaService()
    fraud_svc = FraudAnalysisService()
    account_svc = AccountService()
    risk_eng = RiskEngine(account_svc)
    oauth_svc = OAuthService(account_svc, risk_eng, fraud_svc)

    app.recaptcha_service = recaptcha_svc
    app.fraud_analysis_service = fraud_svc
    app.account_service = account_svc
    app.risk_engine = risk_eng
    app.oauth_service = oauth_svc

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    return app


app = create_app()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5001, debug=True)
