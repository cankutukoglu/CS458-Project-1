from __future__ import annotations

from framework.core.exceptions import SelectorValidationError


def infer_selector_type(selector: str) -> str:
    stripped = selector.strip()
    if stripped.startswith("/") or stripped.startswith("("):
        return "xpath"
    return "css"


def parse_selector_response(response: str) -> tuple[str, str]:
    selector = response.strip()
    if not selector:
        raise SelectorValidationError("LLM returned an empty selector")
    if "\n" in selector or "\r" in selector:
        raise SelectorValidationError("LLM returned a multiline selector")
    if "```" in selector:
        raise SelectorValidationError("LLM returned markdown instead of a selector")
    return selector, infer_selector_type(selector)
