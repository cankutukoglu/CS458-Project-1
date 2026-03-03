from __future__ import annotations

import json
import os
import re
from pathlib import Path

from framework.config.schema import TestSuiteConfig


def _load_dotenv(start_path: Path) -> None:
    """Walk up from start_path looking for a .env file and load missing keys into os.environ."""
    for directory in [start_path, *start_path.parents]:
        env_file = directory / ".env"
        if env_file.is_file():
            with env_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Strip optional surrounding quotes
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = value
            return


def _expand_env_vars(obj):
    """Recursively expand ${VAR} placeholders in all string values."""
    if isinstance(obj, str):
        return re.sub(r'\$\{([^}]+)\}', lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


class ConfigLoader:
    """Loads and validates the JSON test suite configuration."""

    @staticmethod
    def load(path: str | Path) -> TestSuiteConfig:
        config_path = Path(path).resolve()
        _load_dotenv(config_path.parent)
        with config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload = _expand_env_vars(payload)
        return TestSuiteConfig.model_validate(payload)
