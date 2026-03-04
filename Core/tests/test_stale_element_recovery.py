from __future__ import annotations

import pytest
from selenium.common.exceptions import StaleElementReferenceException

from tests.helpers import (
    managed_runtime,
    open_login_page,
    require_reachable_base_url,
)


@pytest.mark.integration
def test_stale_element_retry_on_type(suite_config):
    """Test that typing recovers from stale element by re-finding."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)

        # Get reference to element
        runtime.actions.type("login_email_input", "test@")

        # Replace the element to make old reference stale
        runtime.driver.execute_script(
            """
            const old = document.getElementById('email');
            const parent = old.parentNode;
            const newInput = old.cloneNode(true);
            old.remove();
            parent.appendChild(newInput);
            """
        )

        # This should recover by re-finding the element
        runtime.actions.type("login_email_input", "example.com")

        value = runtime.driver.execute_script(
            "return document.getElementById('email').value;"
        )
        assert "example.com" in value


@pytest.mark.integration
def test_stale_element_retry_on_click(suite_config):
    """Test that clicking recovers from stale element by re-finding."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)

        # Find element first
        element = runtime.finder.find("login_button")

        # Replace it to make reference stale
        runtime.driver.execute_script(
            """
            const old = document.getElementById('loginButton');
            const parent = old.parentNode;
            const newBtn = old.cloneNode(true);
            old.remove();
            parent.appendChild(newBtn);
            """
        )

        # Direct click on stale element should fail
        with pytest.raises(StaleElementReferenceException):
            element.click()

        # But SafeActions.click should handle it
        runtime.actions.type("login_email_input", "test@example.com")
        runtime.actions.type("login_phone_input", "+1234567890")
        runtime.actions.type("login_password_input", "password")
        # This should work - SafeActions handles stale refs
        runtime.actions.click("login_button")
