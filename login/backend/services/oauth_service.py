import logging
import os
from datetime import datetime, timezone

from flask import redirect, session
from werkzeug.security import generate_password_hash

from config import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CHALLENGED,
    ACCOUNT_LOCKED,
    ACCOUNT_SUSPENDED,
    RISK_HIGH,
)
from extensions import db
from models.user import User

log = logging.getLogger(__name__)


class OAuthService:
    def __init__(self, account_service, risk_engine, fraud_analysis_service):
        self._account_service = account_service
        self._risk_engine = risk_engine
        self._fraud_analysis = fraud_analysis_service

    def find_or_create_user(self, email, provider, provider_id=None):
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

    def finalize_login(self, user, email, ip_address, user_agent, action_taken):
        self._account_service.create_login_log(
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

    def finalize_with_risk(self, user, email, ip_address, user_agent, provider):
        if user.account_status == ACCOUNT_SUSPENDED:
            self._account_service.create_login_log(
                user=user, email=email, ip_address=ip_address, user_agent=user_agent,
                success=False, risk_score=100, risk_factors=["SUSPENDED_ACCOUNT"],
                action_taken="denied",
            )
            db.session.commit()
            log.warning("OAuth login denied — suspended account: %s", email)
            return redirect("/index.html?error=Account+suspended.+Please+contact+support.")

        if user.account_status == ACCOUNT_LOCKED:
            if not self._account_service.maybe_unlock_account(user):
                risk_score, risk_factors = self._risk_engine.compute_score(
                    user, email, ip_address, user_agent
                )
                remaining_secs = 0
                if user.locked_until:
                    lu = user.locked_until
                    if lu.tzinfo is None:
                        lu = lu.replace(tzinfo=timezone.utc)
                    remaining_secs = max(
                        0, int((lu - datetime.now(timezone.utc)).total_seconds())
                    )
                self._account_service.create_login_log(
                    user=user, email=email, ip_address=ip_address, user_agent=user_agent,
                    success=False, risk_score=risk_score, risk_factors=risk_factors,
                    action_taken="denied",
                )
                db.session.commit()
                log.warning(
                    "OAuth login denied — account still locked (%ds remaining): %s",
                    remaining_secs,
                    email,
                )
                return redirect(
                    f"/index.html?error=Account+locked.+Auto-unlocks+in+{remaining_secs}+second(s)."
                )

        risk_score, risk_factors = self._risk_engine.compute_score(
            user, email, ip_address, user_agent
        )

        fraud_analysis = (
            self._fraud_analysis.analyze(email, ip_address, user_agent, risk_score, risk_factors)
            if risk_score >= RISK_HIGH
            else None
        )

        action = self._risk_engine.apply_action(user, risk_score, fraud_analysis)

        if action in (ACCOUNT_LOCKED, ACCOUNT_SUSPENDED):
            self._account_service.create_login_log(
                user=user, email=email, ip_address=ip_address, user_agent=user_agent,
                success=False, risk_score=risk_score, risk_factors=risk_factors,
                fraud_analysis=fraud_analysis, action_taken=action,
            )
            db.session.commit()
            log.warning(
                "OAuth login denied via risk action '%s' (score=%d): %s",
                action,
                risk_score,
                email,
            )
            if action == ACCOUNT_SUSPENDED:
                return redirect(
                    "/index.html?error=Account+suspended+due+to+suspicious+activity."
                )
            return redirect("/index.html?error=Account+locked+due+to+suspicious+activity.")

        if user.account_status == ACCOUNT_CHALLENGED:
            user.account_status = ACCOUNT_ACTIVE
            user.failed_attempts = 0
            log.info(
                "Account reset CHALLENGED → ACTIVE via OAuth (%s): %s", provider, email
            )

        self._account_service.create_login_log(
            user=user, email=email, ip_address=ip_address, user_agent=user_agent,
            success=True, risk_score=risk_score, risk_factors=risk_factors,
            fraud_analysis=fraud_analysis, action_taken=f"oauth_{provider}",
        )
        db.session.commit()
        session["user_id"] = user.id
        session["email"] = email
        log.info(
            "OAuth login granted (provider=%s, score=%d): %s", provider, risk_score, email
        )
        return redirect("/index.html?login_success=true")
