from __future__ import annotations

import json
from pathlib import Path

from framework.config.schema import TestSuiteConfig


class ConfigLoader:
    """Loads and validates the JSON test suite configuration."""

    @staticmethod
    def load(path: str | Path) -> TestSuiteConfig:
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return TestSuiteConfig.model_validate(payload)
