from __future__ import annotations

import pytest

from tests.helpers import managed_runtime, repeat_failed_login, require_reachable_base_url


@pytest.mark.integration
def test_rate_limiting(suite_config):
    require_reachable_base_url(suite_config)
    settings = suite_config.scenarios.get("rate_limiting", {})
    attempts = int(settings.get("invalid_attempts", 10))
    expected_indicators = [item.lower() for item in settings.get("expected_indicators", [])]

    with managed_runtime(suite_config, "chrome") as runtime:
        observations = repeat_failed_login(runtime, suite_config, attempts)
        combined_text = " ".join(item["page_source_excerpt"] for item in observations).lower()
        combined_urls = " ".join(item["url"] for item in observations).lower()
        assert any(
            indicator in combined_text or indicator in combined_urls
            for indicator in expected_indicators
        ), "Rate limiting indicators were not observed in the UI flow"
