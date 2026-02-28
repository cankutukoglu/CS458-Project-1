from __future__ import annotations

import json
from pathlib import Path

from framework.core.metadata import HealAttempt


class HealingAuditLogger:
    """Persists healing attempts and latest selector overrides."""

    def __init__(self, root: str | Path = "artifacts") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.healed_elements_path = self.root / "healed_elements.jsonl"
        self.selector_overrides_path = self.root / "selector_overrides.json"

    def write(self, attempt: HealAttempt) -> None:
        payload = {
            "element_key": attempt.element_key,
            "old_selector": attempt.old_selector,
            "failure_type": attempt.failure_type,
            "top_candidates": attempt.top_candidates,
            "llm_provider": attempt.llm_provider,
            "new_selector": attempt.new_selector,
            "success": attempt.success,
            "artifact_paths": attempt.artifact_paths,
        }
        with self.healed_elements_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

        if attempt.success and attempt.new_selector:
            overrides = self.read_overrides()
            overrides[attempt.element_key] = attempt.new_selector
            self.selector_overrides_path.write_text(
                json.dumps(overrides, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    def read_overrides(self) -> dict[str, str]:
        if not self.selector_overrides_path.exists():
            return {}
        return json.loads(self.selector_overrides_path.read_text(encoding="utf-8"))
