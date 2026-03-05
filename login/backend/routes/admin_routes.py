import json
import logging

from flask import Blueprint, request, jsonify

from config import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CHALLENGED,
    ACCOUNT_LOCKED,
    ACCOUNT_SUSPENDED,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
    RISK_CRITICAL,
    SCORE_PER_FAILED_ATTEMPT,
    VELOCITY_WINDOW_SECONDS,
    VELOCITY_MAX_ATTEMPTS,
)
from extensions import db
from models.user import User
from models.login_log import LoginLog

log = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/login-logs", methods=["GET"])
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
            "id": entry.id,
            "user_id": entry.user_id,
            "email": entry.email_attempted,
            "ip_address": entry.ip_address,
            "user_agent": entry.user_agent,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "success": entry.success,
            "risk_score": entry.risk_score,
            "risk_factors": json.loads(entry.risk_factors) if entry.risk_factors else [],
            "fraud_analysis": json.loads(entry.fraud_analysis) if entry.fraud_analysis else None,
            "action_taken": entry.action_taken,
        }
        for entry in logs
    ]), 200


@admin_bp.route("/api/admin/user-status", methods=["POST"])
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


@admin_bp.route("/api/risk-config", methods=["GET"])
def risk_config():
    return jsonify({
        "thresholds": {
            "low": RISK_LOW,
            "medium": RISK_MEDIUM,
            "high": RISK_HIGH,
            "critical": RISK_CRITICAL,
        },
        "score_per_failed_attempt": SCORE_PER_FAILED_ATTEMPT,
        "velocity_window_seconds": VELOCITY_WINDOW_SECONDS,
        "velocity_max_attempts": VELOCITY_MAX_ATTEMPTS,
        "account_states": [ACCOUNT_ACTIVE, ACCOUNT_CHALLENGED, ACCOUNT_LOCKED, ACCOUNT_SUSPENDED],
    }), 200
