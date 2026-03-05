from datetime import datetime, timezone

from extensions import db


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
