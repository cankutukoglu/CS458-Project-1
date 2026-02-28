from __future__ import annotations

INSTALL_MONITOR_SCRIPT = r"""
if (!window.__heal_events__) {
  window.__heal_events__ = [];
}

if (!window.__heal_observer_installed__) {
  const pushEvent = (mutation, rootLabel) => {
    window.__heal_events__.push({
      type: mutation.type,
      targetTag: mutation.target && mutation.target.tagName ? mutation.target.tagName.toLowerCase() : "",
      addedCount: mutation.addedNodes ? mutation.addedNodes.length : 0,
      removedCount: mutation.removedNodes ? mutation.removedNodes.length : 0,
      attributeName: mutation.attributeName || "",
      root: rootLabel,
      timestamp: Date.now(),
    });
    if (window.__heal_events__.length > 200) {
      window.__heal_events__ = window.__heal_events__.slice(-200);
    }
  };

  const observeRoot = (root, label) => {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        pushEvent(mutation, label);
        if (mutation.type === "childList") {
          for (const node of mutation.addedNodes) {
            if (node instanceof Element && node.shadowRoot) {
              observeRoot(node.shadowRoot, node.tagName.toLowerCase());
            }
          }
        }
      }
    });
    observer.observe(root, {
      attributes: true,
      childList: true,
      subtree: true,
    });
  };

  observeRoot(document, "document");
  for (const node of document.querySelectorAll("*")) {
    if (node.shadowRoot) {
      observeRoot(node.shadowRoot, node.tagName.toLowerCase());
    }
  }
  window.__heal_observer_installed__ = true;
}
"""

FLUSH_EVENTS_SCRIPT = """
const events = window.__heal_events__ || [];
window.__heal_events__ = [];
return events;
"""


class DomMonitor:
    """Installs and reads the browser-side mutation buffer."""

    def install(self, driver) -> None:
        driver.execute_script(INSTALL_MONITOR_SCRIPT)

    def flush_events(self, driver) -> list[dict]:
        return driver.execute_script(FLUSH_EVENTS_SCRIPT) or []
