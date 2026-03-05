import json
import logging
from datetime import datetime, timezone, timedelta

from flask import jsonify

from config import (
    ACCOUNT_ACTIVE,
    ACCOUNT_LOCKED,
    ACCOUNT_SUSPENDED,
    LOCK_DURATION_SECONDS,
)
from extensions import db
from models.login_log import LoginLog

log = logging.getLogger(__name__)


class AccountService:
    def create_login_log(
        self,
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

    def maybe_unlock_account(self, user) -> bool:
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

    def lock_or_suspend_user(self, user) -> str:
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
        log.info(
            "Account locked until %s (lock #%d): %s",
            user.locked_until.isoformat(),
            user.lock_count,
            user.email,
        )
        return ACCOUNT_LOCKED

    def deny_login_for_status(self, user, email, ip_address, user_agent, account_status, error_message):
        risk_factor = (
            "SUSPENDED_ACCOUNT" if account_status == ACCOUNT_SUSPENDED else "LOCKED_ACCOUNT"
        )
        self.create_login_log(
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
