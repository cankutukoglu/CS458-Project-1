from datetime import datetime, timezone

from extensions import db
from config import ACCOUNT_ACTIVE


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
