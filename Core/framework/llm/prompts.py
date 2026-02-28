from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You repair Selenium selectors. Return exactly one valid selector string and nothing else.
Rules:
1. Use only elements present in the provided DOM snippet.
2. Do not invent tags, attributes, text, or hierarchy.
3. Prefer a CSS selector when it uniquely identifies the intended element.
4. If a CSS selector cannot safely identify the element, return a valid XPath.
5. Output must be a single line with no explanation, no quotes, no markdown, and no code fence.
6. If the target action is dismissing an overlay, return the selector for the dismiss/close control only."""


def build_user_prompt(payload: dict[str, Any]) -> str:
    """Formats a deterministic user payload for the model."""

    return json.dumps(payload, indent=2, sort_keys=True)
