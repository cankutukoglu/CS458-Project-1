from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DomSnapshot:
    url: str
    page_source: str
    mutation_events: list[dict[str, Any]]
    screenshot_path: Path
    timestamp: str


@dataclass(slots=True)
class CandidateElement:
    selector_hint: str
    tag: str
    text: str
    attributes: dict[str, str]
    parent_tag: str
    rect: dict[str, float]
    styles: dict[str, str]
    heuristic_score: float = 0.0


@dataclass(slots=True)
class HealAttempt:
    element_key: str
    old_selector: str
    failure_type: str
    top_candidates: list[dict[str, Any]]
    llm_provider: str
    new_selector: str
    success: bool
    artifact_paths: dict[str, str] = field(default_factory=dict)
