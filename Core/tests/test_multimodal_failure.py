from __future__ import annotations

import pytest

from tests.helpers import (
    healing_log_contains,
    inject_popup_overlay,
    managed_runtime,
    open_login_page,
    popup_overlay_present,
    require_llm_credentials,
    require_reachable_base_url,
)


@pytest.mark.integration
def test_multimodal_failure(suite_config):
    require_reachable_base_url(suite_config)
    require_llm_credentials()

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        inject_popup_overlay(runtime)
        assert popup_overlay_present(runtime)
        runtime.actions.click("google_login_button")
        assert healing_log_contains("google_login_button")
        assert not popup_overlay_present(runtime) or runtime.driver.current_url != suite_config.environment.base_url
