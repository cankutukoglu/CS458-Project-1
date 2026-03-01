from __future__ import annotations

import json
from typing import Any

from framework.core.metadata import CandidateElement

COLLECT_CANDIDATES_SCRIPT = r"""
const includeNode = (node) => {
  if (!(node instanceof Element)) return false;
  const tag = node.tagName.toLowerCase();
  if (["input", "button", "a", "select", "textarea"].includes(tag)) return true;
  if (node.hasAttribute("role")) return true;
  if (node.hasAttribute("data-testid")) return true;
  if (typeof node.onclick === "function") return true;
  return false;
};

const bestSelector = (node) => {
  if (node.id) return `#${CSS.escape(node.id)}`;
  if (node.getAttribute("data-testid")) return `[data-testid="${node.getAttribute("data-testid")}"]`;
  if (node.getAttribute("name")) return `${node.tagName.toLowerCase()}[name="${node.getAttribute("name")}"]`;
  if (node.classList.length) return `${node.tagName.toLowerCase()}.${Array.from(node.classList).slice(0, 3).map((name) => CSS.escape(name)).join(".")}`;
  return node.tagName.toLowerCase();
};

const roots = [document];
const shadowHosts = Array.from(document.querySelectorAll("*")).filter((node) => node.shadowRoot);
for (const host of shadowHosts) roots.push(host.shadowRoot);

const items = [];
for (const root of roots) {
  const elements = root.querySelectorAll("*");
  for (const node of elements) {
    if (!includeNode(node)) continue;
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    items.push({
      selector_hint: bestSelector(node),
      tag: node.tagName.toLowerCase(),
      text: (node.innerText || node.textContent || "").trim().slice(0, 200),
      attributes: Array.from(node.attributes).reduce((acc, attr) => {
        acc[attr.name] = attr.value;
        return acc;
      }, {}),
      parent_tag: node.parentElement ? node.parentElement.tagName.toLowerCase() : "",
      rect: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      },
      styles: {
        color: style.color,
        backgroundColor: style.backgroundColor,
        display: style.display,
        visibility: style.visibility,
        zIndex: style.zIndex,
      },
    });
  }
}
return items.slice(0, 80);
"""


def extract_candidate_elements(driver) -> list[CandidateElement]:
    raw_candidates = driver.execute_script(COLLECT_CANDIDATES_SCRIPT) or []
    candidates: list[CandidateElement] = []
    for item in raw_candidates:
        candidates.append(
            CandidateElement(
                selector_hint=item.get("selector_hint", ""),
                tag=item.get("tag", ""),
                text=item.get("text", ""),
                attributes=item.get("attributes", {}),
                parent_tag=item.get("parent_tag", ""),
                rect=item.get("rect", {}),
                styles=item.get("styles", {}),
            )
        )
    return candidates


def build_dom_snippet(page_source: str, candidates: list[CandidateElement], max_chars: int = 12000) -> str:
    summary = {
        "candidate_hints": [candidate.selector_hint for candidate in candidates],
        "candidate_tags": [candidate.tag for candidate in candidates],
        "page_source_excerpt": page_source[: max_chars // 2],
    }
    return json.dumps(summary, indent=2)
