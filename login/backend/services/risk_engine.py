import logging
from datetime import datetime, timezone, timedelta

from config import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CHALLENGED,
    ACCOUNT_LOCKED,
    ACCOUNT_SUSPENDED,
    RISK_HIGH,
    RISK_CRITICAL,
    VELOCITY_WINDOW_SECONDS,
    VELOCITY_MAX_ATTEMPTS,
    SCORE_PER_FAILED_ATTEMPT,
)
from extensions import db
from models.login_log import LoginLog

log = logging.getLogger(__name__)


class RiskEngine:
    def __init__(self, account_service):
        self._account_service = account_service

    def compute_score(self, user, email, ip_address, user_agent):
        score = 0
        factors = []

        if user and user.failed_attempts > 0:
            attempt_score = min(user.failed_attempts * SCORE_PER_FAILED_ATTEMPT, RISK_CRITICAL)
            score += attempt_score
            factors.append(
                f"FAILED_ATTEMPTS: {user.failed_attempts} consecutive failed attempt(s) (+{attempt_score})"
            )

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
            LoginLog.timestamp >= window_start,
        ).count()
        if recent_attempts >= VELOCITY_MAX_ATTEMPTS:
            score += 30
            factors.append(
                f"VELOCITY: {recent_attempts} attempts in last {VELOCITY_WINDOW_SECONDS}s "
                f"(threshold: {VELOCITY_MAX_ATTEMPTS})"
            )
        elif recent_attempts >= VELOCITY_MAX_ATTEMPTS // 2:
            score += 10
            factors.append(
                f"VELOCITY_WARN: {recent_attempts} attempts in last {VELOCITY_WINDOW_SECONDS}s"
            )

        if user:
            last_successful = (
                LoginLog.query.filter_by(user_id=user.id, success=True)
                .order_by(LoginLog.timestamp.desc())
                .first()
            )
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

    def apply_action(self, user, risk_score, fraud_result):
        if not user:
            return "denied"

        recommendation = fraud_result.get("recommendation", "") if fraud_result else ""

        if risk_score >= RISK_CRITICAL or recommendation == "lock_account":
            new_status = self._account_service.lock_or_suspend_user(user)
            db.session.commit()
            return new_status
        
        if risk_score >= RISK_HIGH or recommendation == "challenge_user":
            if user.account_status == ACCOUNT_ACTIVE:
                user.account_status = ACCOUNT_CHALLENGED
                db.session.commit()
            return "challenged"

        return "allowed"
