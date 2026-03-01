from __future__ import annotations

import pytest

from tests.helpers import (
    assert_authenticated_state,
    healing_log_contains,
    inject_dynamic_id_change,
    login_with_password,
    managed_runtime,
    open_login_page,
    require_llm_credentials,
    require_reachable_base_url,
)


@pytest.mark.integration
def test_dynamic_id_recovery(suite_config):
    require_reachable_base_url(suite_config)
    require_llm_credentials()
    suite_config.get_element("login_button").fallback_selectors = []

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        inject_dynamic_id_change(runtime)
        login_with_password(runtime, suite_config)
        assert healing_log_contains("login_button")
        assert_authenticated_state(runtime, suite_config.environment.base_url)
