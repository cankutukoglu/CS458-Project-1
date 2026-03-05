from __future__ import annotations

import pytest

from tests.helpers import (
    api_login,
    ensure_test_user,
    require_reachable_base_url,
    reset_user_state,
)


@pytest.mark.integration
def test_account_transitions_to_challenged(suite_config):
    """Test that 5 failed logins transition account to challenged state."""
    require_reachable_base_url(suite_config)
    ensure_test_user(suite_config)
    email = suite_config.credentials.email
    reset_user_state(suite_config, email)

    for i in range(5):
        result = api_login(suite_config, email, "wrong-password")
        assert result["status"] == 401

    assert result["data"].get("account_status") == "challenged"
    assert "warning" in result["data"]

    reset_user_state(suite_config, email)


@pytest.mark.integration
def test_locked_account_denies_login(suite_config):
    """Test that locked accounts cannot login even with correct password."""
    require_reachable_base_url(suite_config)
    ensure_test_user(suite_config)
    email = suite_config.credentials.email
    password = suite_config.credentials.password
    reset_user_state(suite_config, email)

    for _ in range(10):
        api_login(suite_config, email, "wrong-password")

    result = api_login(suite_config, email, password)
    assert result["status"] == 403
    assert "locked" in result["data"].get("error", "").lower()

    reset_user_state(suite_config, email)


@pytest.mark.integration
def test_successful_login_resets_failed_attempts(suite_config):
    """Test that successful login resets failed attempt counter."""
    require_reachable_base_url(suite_config)
    ensure_test_user(suite_config)
    email = suite_config.credentials.email
    password = suite_config.credentials.password
    reset_user_state(suite_config, email)

    for _ in range(3):
        api_login(suite_config, email, "wrong-password")

    result = api_login(suite_config, email, password)
    assert result["status"] == 200

    for _ in range(3):
        api_login(suite_config, email, "wrong-password")

    result = api_login(suite_config, email, password)
    assert result["status"] == 200

    reset_user_state(suite_config, email)
