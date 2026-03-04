from __future__ import annotations

import pytest

from tests.helpers import (
    api_login,
    ensure_test_user,
    require_reachable_base_url,
    reset_user_state,
)


@pytest.mark.integration
def test_failed_attempts_increase_risk_score(suite_config):
    """Test that consecutive failed attempts increase the risk score."""
    require_reachable_base_url(suite_config)
    ensure_test_user(suite_config)
    email = suite_config.credentials.email
    reset_user_state(suite_config, email)

    scores = []
    for _ in range(6):
        result = api_login(suite_config, email, "wrong-password")
        scores.append(result["data"].get("risk_score", 0))

    assert scores[-1] > scores[0], "Risk score should increase with failed attempts"

    reset_user_state(suite_config, email)


@pytest.mark.integration
def test_risk_factors_reported_in_response(suite_config):
    """Test that risk factors are included in login response."""
    require_reachable_base_url(suite_config)
    ensure_test_user(suite_config)
    email = suite_config.credentials.email
    reset_user_state(suite_config, email)

    for _ in range(5):
        result = api_login(suite_config, email, "wrong-password")

    risk_factors = result["data"].get("risk_factors", [])
    assert len(risk_factors) > 0, "Risk factors should be reported after failed attempts"
    assert any("failed" in f.lower() for f in risk_factors)

    reset_user_state(suite_config, email)


@pytest.mark.integration
def test_successful_login_returns_risk_score(suite_config):
    """Test that even successful logins include risk score data."""
    require_reachable_base_url(suite_config)
    ensure_test_user(suite_config)
    email = suite_config.credentials.email
    password = suite_config.credentials.password
    reset_user_state(suite_config, email)

    result = api_login(suite_config, email, password)
    assert result["status"] == 200
    assert "risk_score" in result["data"]

    reset_user_state(suite_config, email)
