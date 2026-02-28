from __future__ import annotations

from pathlib import Path

import pytest

from framework.config.loader import ConfigLoader


@pytest.fixture()
def suite_config():
    config_path = Path(__file__).resolve().parents[1] / "config" / "test_suite.json"
    return ConfigLoader.load(config_path)
