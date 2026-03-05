from __future__ import annotations

import pytest

from tests.helpers import (
    assert_authenticated_state,
    login_with_password,
    managed_runtime,
    open_login_page,
    require_reachable_base_url,
)


@pytest.mark.integration
def test_fallback_selector_used_when_primary_fails(suite_config):
    """Test that fallback selectors are tried before LLM healing.

    This verifies the two-tier approach: fallbacks first, LLM second.
    No LLM credentials needed - fallbacks should handle it.
    """
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)

        # Break the primary selector but leave fallback intact
        runtime.driver.execute_script(
            "document.getElementById('loginButton').id = 'brokenId';"
        )

        # Fallback selector `button.btn-login` should still work
        login_with_password(runtime, suite_config)
        assert_authenticated_state(runtime, suite_config.environment.base_url)


@pytest.mark.integration
def test_xpath_fallback_works(suite_config):
    """Test that XPath fallback selectors are evaluated correctly."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)

        # Break both ID and class selectors
        runtime.driver.execute_script(
            """
            const btn = document.getElementById('loginButton');
            btn.id = 'broken';
            btn.className = 'broken-class';
            """
        )

        # XPath fallback `//button[contains(normalize-space(.), 'Sign In')]` should work
        login_with_password(runtime, suite_config)
        assert_authenticated_state(runtime, suite_config.environment.base_url)
