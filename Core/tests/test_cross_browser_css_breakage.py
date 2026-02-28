from __future__ import annotations

import pytest

from tests.helpers import (
    css_breakage_applied,
    inject_css_breakage,
    login_with_password,
    managed_runtime,
    open_login_page,
    require_llm_credentials,
    require_reachable_base_url,
)


@pytest.mark.integration
@pytest.mark.parametrize("browser_name", ["chrome", "firefox"])
def test_cross_browser_css_breakage(suite_config, browser_name):
    require_reachable_base_url(suite_config)
    require_llm_credentials()

    with managed_runtime(suite_config, browser_name) as runtime:
        open_login_page(runtime, suite_config)
        inject_css_breakage(runtime)
        assert css_breakage_applied(runtime)
        login_with_password(runtime, suite_config)
        assert runtime.driver.current_url
