from __future__ import annotations

import pytest

from tests.helpers import (
    managed_runtime,
    open_login_page,
    require_reachable_base_url,
)


@pytest.mark.integration
def test_mutation_observer_captures_changes(suite_config):
    """Test that DOM monitor captures mutation events."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)

        runtime.driver.execute_script(
            "document.getElementById('loginButton').setAttribute('data-test', 'mutated');"
        )

        events = runtime.dom_monitor.flush_events(runtime.driver)
        assert len(events) > 0, "Mutation observer should capture attribute changes"

        attr_changes = [e for e in events if e.get("type") == "attributes"]
        assert len(attr_changes) > 0, "Should have captured attribute mutation"


@pytest.mark.integration
def test_mutation_observer_captures_child_additions(suite_config):
    """Test that DOM monitor captures child node additions."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        runtime.dom_monitor.flush_events(runtime.driver)

        runtime.driver.execute_script(
            """
            const div = document.createElement('div');
            div.id = 'injected-element';
            document.body.appendChild(div);
            """
        )

        events = runtime.dom_monitor.flush_events(runtime.driver)
        child_additions = [e for e in events if e.get("addedCount", 0) > 0]
        assert len(child_additions) > 0, "Should have captured child node addition"


@pytest.mark.integration
def test_mutation_observer_tracks_element_removal(suite_config):
    """Test that DOM monitor captures element removals."""
    require_reachable_base_url(suite_config)

    with managed_runtime(suite_config, "chrome") as runtime:
        open_login_page(runtime, suite_config)
        runtime.dom_monitor.flush_events(runtime.driver)

        runtime.driver.execute_script(
            """
            const btn = document.getElementById('googleLogin');
            if (btn) btn.remove();
            """
        )

        events = runtime.dom_monitor.flush_events(runtime.driver)
        removals = [e for e in events if e.get("removedCount", 0) > 0]
        assert len(removals) > 0, "Should have captured element removal"
