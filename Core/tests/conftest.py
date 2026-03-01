from __future__ import annotations

from pathlib import Path

import pytest

from framework.config.loader import ConfigLoader
from framework.logging.artifacts import ArtifactManager


@pytest.fixture(scope="session", autouse=True)
def reset_artifacts_for_test_run():
    artifacts_root = Path(__file__).resolve().parents[1] / "artifacts"
    manager = ArtifactManager(artifacts_root)
    manager.reset()
    return manager


@pytest.fixture()
def suite_config():
    config_path = Path(__file__).resolve().parents[1] / "config" / "test_suite.json"
    return ConfigLoader.load(config_path)
