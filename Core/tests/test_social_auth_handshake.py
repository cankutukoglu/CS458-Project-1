from __future__ import annotations

import pytest

from tests.helpers import (
    capture_auth_token,
    complete_social_provider_login,
    managed_runtime,
    open_login_page,
    require_reachable_base_url,
    require_scenario_enabled,
    require_social_credentials,
)


@pytest.mark.integration
@pytest.mark.oauth
def test_social_auth_handshake(suite_config):
    require_reachable_base_url(suite_config)
    require_scenario_enabled(suite_config, "social_auth_handshake")
    username, password = require_social_credentials(suite_config, "google")

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        runtime.actions.click("google_login_button")
        complete_social_provider_login(runtime, "google", username, password)
        token_data = capture_auth_token(runtime)
        assert any(value for value in token_data.values()), "No social-auth token or redirect artifact was captured"
