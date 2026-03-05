from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import (
    managed_runtime,
    open_login_page,
    require_llm_credentials,
    require_reachable_base_url,
)


@pytest.mark.integration
def test_healed_selector_persisted_to_overrides(suite_config):
    """Test that successfully healed selectors are saved to overrides file.

    This verifies the audit logging writes selector_overrides.json
    so future runs can skip re-healing the same element.
    """
    require_reachable_base_url(suite_config)
    require_llm_credentials()
    suite_config.get_element("login_button").fallback_selectors = []

    overrides_path = Path("artifacts/selector_overrides.json")
    if overrides_path.exists():
        initial_overrides = json.loads(overrides_path.read_text())
    else:
        initial_overrides = {}

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)

        # Break the selector to force healing
        runtime.driver.execute_script(
            "document.getElementById('loginButton').id = 'healedButton';"
        )

        # This triggers healing
        runtime.finder.find("login_button")

    # Verify override was persisted
    assert overrides_path.exists(), "selector_overrides.json should be created"
    overrides = json.loads(overrides_path.read_text())
    assert "login_button" in overrides, "Healed selector should be saved"
    assert overrides["login_button"] != "#loginButton", "Override should be different from original"


@pytest.mark.integration
def test_healing_attempt_logged_to_audit(suite_config):
    """Test that healing attempts are logged to healed_elements.json."""
    require_reachable_base_url(suite_config)
    require_llm_credentials()
    suite_config.get_element("login_button").fallback_selectors = []

    audit_path = Path("artifacts/healed_elements.json")

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)

        runtime.driver.execute_script(
            "document.getElementById('loginButton').id = 'auditTestButton';"
        )

        runtime.finder.find("login_button")

    assert audit_path.exists(), "healed_elements.json should be created"
    attempts = json.loads(audit_path.read_text())

    recent = [a for a in attempts if a.get("element_key") == "login_button"]
    assert len(recent) > 0, "Healing attempt should be logged"
    assert recent[-1].get("success") is True, "Healing should have succeeded"
    assert "artifact_paths" in recent[-1], "Artifacts should be recorded"
