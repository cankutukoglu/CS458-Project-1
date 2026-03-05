"""Tests for Google and GitHub social sign-in buttons.

Covers:
- Selector healing when button IDs/classes are mutated
- Full OAuth handshake flow (skipped when credentials are absent)
"""
from __future__ import annotations

import time

import pytest
from selenium.webdriver.common.by import By

from tests.helpers import (
    _is_back_at_app,
    capture_auth_token,
    complete_social_provider_login,
    managed_runtime,
    open_login_page,
    require_reachable_base_url,
    require_scenario_enabled,
    require_social_credentials,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_url_change(driver, original_url: str, timeout: float = 10) -> str:
    """Block until the browser navigates away from *original_url* or times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if driver.current_url != original_url:
            return driver.current_url
        time.sleep(0.2)
    return driver.current_url


# ---------------------------------------------------------------------------
# Selector healing tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_google_sign_in_button_selector_healing(suite_config):
    """Framework must locate the Google button via fallback when its ID is mutated."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        # Break the primary selector (#googleLogin)
        runtime.driver.execute_script(
            "const btn = document.getElementById('googleLogin');"
            "if (btn) btn.id = 'googleLoginMutated';"
        )
        original_url = runtime.driver.current_url
        # The fallback selector `button.btn-google` should still locate the button.
        runtime.actions.click("google_login_button")
        new_url = _wait_for_url_change(runtime.driver, original_url)
        assert new_url != original_url, (
            "Expected redirect to occur after clicking Google button via fallback selector"
        )


@pytest.mark.integration
def test_github_sign_in_button_selector_healing(suite_config):
    """Framework must locate the GitHub button via fallback when its ID is mutated."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        # Break the primary selector (#githubLogin)
        runtime.driver.execute_script(
            "const btn = document.getElementById('githubLogin');"
            "if (btn) btn.id = 'githubLoginMutated';"
        )
        original_url = runtime.driver.current_url
        # The fallback selector `button.btn-github` should still locate the button.
        runtime.actions.click("github_login_button")
        new_url = _wait_for_url_change(runtime.driver, original_url)
        assert new_url != original_url, (
            "Expected redirect to occur after clicking GitHub button via fallback selector"
        )

@pytest.mark.integration
def test_google_sign_in_full_oauth_handshake(suite_config):
    """Complete the Google OAuth flow end-to-end using test credentials.

    Skipped automatically when GOOGLE_TEST_USERNAME / GOOGLE_TEST_PASSWORD are
    not set in the environment or config.
    """
    require_reachable_base_url(suite_config)
    require_scenario_enabled(suite_config, "social_auth_handshake")
    username, password = require_social_credentials(suite_config, "google")

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        original_url = runtime.driver.current_url

        runtime.actions.click("google_login_button")
        _wait_for_url_change(runtime.driver, original_url)

        # Navigate through Google sign-in pages until redirected back
        complete_social_provider_login(runtime, "google", username, password, timeout=60)

        # Wait for the page to settle (success message renders asynchronously)
        time.sleep(3)

        current_url = runtime.driver.current_url
        success_visible = runtime.driver.execute_script(
            "const el = document.getElementById('successMessage');"
            "return el && getComputedStyle(el).display !== 'none' ? el.textContent : '';"
        )
        error_visible = runtime.driver.execute_script(
            "const el = document.getElementById('errorMessage');"
            "return el && getComputedStyle(el).display !== 'none' ? el.textContent : '';"
        )
        success_text = (success_visible or "").lower()
        assert _is_back_at_app(current_url), (
            f"Browser never returned to the app after Google OAuth.\n"
            f"  URL: {current_url}"
        )
        assert "login successful" in success_text or "login_success=true" in current_url, (
            f"Google OAuth did not result in a successful login.\n"
            f"  URL: {current_url}\n"
            f"  successMessage: {success_visible!r}\n"
            f"  errorMessage: {error_visible!r}"
        )


@pytest.mark.integration
def test_github_sign_in_full_oauth_handshake(suite_config):
    """Complete the GitHub OAuth flow end-to-end using test credentials.

    Skipped automatically when GITHUB_TEST_USERNAME / GITHUB_TEST_PASSWORD are
    not set in the environment or config, or when GitHub OAuth env vars
    (GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET) are absent from the server.
    """
    require_reachable_base_url(suite_config)
    require_scenario_enabled(suite_config, "social_auth_handshake")
    username, password = require_social_credentials(suite_config, "github")

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        original_url = runtime.driver.current_url

        runtime.actions.click("github_login_button")
        new_url = _wait_for_url_change(runtime.driver, original_url)

        # If GitHub OAuth is not configured server-side the URL will contain ?error=
        if "error=" in new_url.lower():
            pytest.skip("GitHub OAuth is not configured on the server — skipping full handshake")

        # Navigate through GitHub sign-in pages until redirected back
        complete_social_provider_login(runtime, "github", username, password, timeout=60)

        # Wait for the page to settle (success message renders asynchronously)
        time.sleep(3)

        current_url = runtime.driver.current_url
        success_visible = runtime.driver.execute_script(
            "const el = document.getElementById('successMessage');"
            "return el && getComputedStyle(el).display !== 'none' ? el.textContent : '';"
        )
        error_visible = runtime.driver.execute_script(
            "const el = document.getElementById('errorMessage');"
            "return el && getComputedStyle(el).display !== 'none' ? el.textContent : '';"
        )
        success_text = (success_visible or "").lower()
        assert _is_back_at_app(current_url), (
            f"Browser never returned to the app after GitHub OAuth.\n"
            f"  URL: {current_url}"
        )
        assert "login successful" in success_text or "login_success=true" in current_url, (
            f"GitHub OAuth did not result in a successful login.\n"
            f"  URL: {current_url}\n"
            f"  successMessage: {success_visible!r}\n"
            f"  errorMessage: {error_visible!r}"
        )
