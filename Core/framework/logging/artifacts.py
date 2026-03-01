from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path


class ArtifactManager:
    """Creates and manages framework artifact files."""

    def __init__(self, root: str | Path = "artifacts") -> None:
        self.root = Path(root)
        self.dom_root = self.root / "dom_snapshots"
        self.screenshot_root = self.root / "screenshots"
        self.run_log_root = self.root / "run_logs"
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.dom_root.mkdir(parents=True, exist_ok=True)
        self.screenshot_root.mkdir(parents=True, exist_ok=True)
        self.run_log_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def timestamp() -> str:
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    def write_dom_snapshot(self, element_key: str, page_source: str, timestamp: str | None = None) -> Path:
        stamp = timestamp or self.timestamp()
        path = self.dom_root / f"{stamp}_{element_key}.html"
        path.write_text(page_source, encoding="utf-8")
        return path

    def screenshot_path(self, element_key: str, timestamp: str | None = None) -> Path:
        stamp = timestamp or self.timestamp()
        return self.screenshot_root / f"{stamp}_{element_key}.png"

    def write_run_log(self, message: str, timestamp: str | None = None) -> Path:
        stamp = timestamp or self.timestamp()
        path = self.run_log_root / f"{stamp}.log"
        path.write_text(message, encoding="utf-8")
        return path

    def reset(self) -> Path:
        self._ensure_structure()
        for child in self.root.iterdir():
            if child.is_file() and child.name != ".gitkeep":
                child.unlink()
        for directory in (self.dom_root, self.screenshot_root, self.run_log_root):
            self._clear_directory(directory)
        return self.root

    @staticmethod
    def _clear_directory(directory: Path) -> None:
        for child in directory.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.is_file() and child.name != ".gitkeep":
                child.unlink()
