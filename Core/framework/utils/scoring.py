from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable

from framework.config.schema import ElementDefinition
from framework.core.metadata import CandidateElement


def score_candidates(
    element_definition: ElementDefinition,
    candidates: Iterable[CandidateElement],
) -> list[CandidateElement]:
    scored: list[CandidateElement] = []
    metadata = element_definition.historical_metadata
    for candidate in candidates:
        score = 0.0
        if metadata.tag and candidate.tag == metadata.tag:
            score += 20
        score += 20 * _similarity(metadata.text or "", candidate.text)
        score += 20 * _attribute_similarity(metadata.attributes, candidate.attributes)
        if candidate.parent_tag == metadata.parent_tag:
            score += 10
        score += 10 * _class_overlap(
            metadata.attributes.get("class", ""),
            candidate.attributes.get("class", ""),
        )
        score += 10 * _location_similarity(metadata.location.model_dump(), candidate.rect)
        score += 5 * _color_similarity(metadata.color, candidate.styles.get("color", ""))
        score += 5 * _neighbor_similarity(metadata.neighbor_signature, candidate)
        candidate.heuristic_score = round(score, 4)
        scored.append(candidate)
    scored.sort(key=lambda item: item.heuristic_score, reverse=True)
    return scored


def _similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left.lower(), b=right.lower()).ratio()


def _attribute_similarity(expected: dict[str, str], actual: dict[str, str]) -> float:
    keys = ("name", "type", "placeholder", "role", "aria-label")
    scores = [_similarity(expected.get(key, ""), actual.get(key, "")) for key in keys]
    return sum(scores) / len(scores)


def _class_overlap(expected: str, actual: str) -> float:
    left = {item for item in expected.split() if item}
    right = {item for item in actual.split() if item}
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union)


def _location_similarity(expected: dict[str, float], actual: dict[str, float]) -> float:
    if not expected or not actual:
        return 0.0
    delta_x = abs(expected.get("x", 0.0) - actual.get("x", 0.0))
    delta_y = abs(expected.get("y", 0.0) - actual.get("y", 0.0))
    total_delta = delta_x + delta_y
    return max(0.0, 1.0 - min(total_delta / 1000.0, 1.0))


def _color_similarity(expected: str, actual: str) -> float:
    return 1.0 if expected and actual and expected.strip() == actual.strip() else 0.0


def _neighbor_similarity(neighbors: list[str], candidate: CandidateElement) -> float:
    if not neighbors:
        return 0.0
    local_tokens = [candidate.parent_tag, candidate.tag]
    overlap = set(neighbors) & set(local_tokens)
    return len(overlap) / max(len(set(neighbors)), 1)
