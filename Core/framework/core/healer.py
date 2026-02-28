from __future__ import annotations

from typing import Any

from selenium.common.exceptions import InvalidSelectorException
from selenium.webdriver.common.by import By

from framework.config.schema import TestSuiteConfig
from framework.core.exceptions import HealingError, SelectorValidationError
from framework.core.metadata import HealAttempt
from framework.llm.parser import parse_selector_response
from framework.logging.artifacts import ArtifactManager
from framework.logging.audit import HealingAuditLogger
from framework.utils.dom_extract import build_dom_snippet, extract_candidate_elements
from framework.utils.scoring import score_candidates


class Healer:
    """Coordinates DOM capture, candidate ranking, and LLM selector repair."""

    def __init__(
        self,
        suite_config: TestSuiteConfig,
        llm_client,
        dom_monitor,
        artifact_manager: ArtifactManager,
        audit_logger: HealingAuditLogger,
    ) -> None:
        self.suite_config = suite_config
        self.llm_client = llm_client
        self.dom_monitor = dom_monitor
        self.artifact_manager = artifact_manager
        self.audit_logger = audit_logger

    def recover(self, driver, element_key: str, failure: Exception, mode: str = "target_repair") -> str:
        element_definition = self.suite_config.get_element(element_key)
        timestamp = self.artifact_manager.timestamp()
        mutation_events = self.dom_monitor.flush_events(driver)
        page_source = driver.page_source
        screenshot_path = self.artifact_manager.screenshot_path(element_key, timestamp)
        driver.save_screenshot(str(screenshot_path))
        dom_path = self.artifact_manager.write_dom_snapshot(element_key, page_source, timestamp)
        candidates = score_candidates(element_definition, extract_candidate_elements(driver))
        top_candidates = candidates[:5]
        payload = self._build_payload(
            element_definition=element_definition,
            failure=failure,
            mode=mode,
            page_source=page_source,
            mutation_events=mutation_events,
            top_candidates=top_candidates,
        )

        selector = ""
        success = False
        try:
            selector = self.llm_client.repair_selector(payload)
            selector, selector_type = parse_selector_response(selector)
            self._validate_selector(driver, selector, selector_type)
            success = True
            return selector
        except Exception as exc:  # noqa: BLE001 - audit logging needs the concrete failure.
            if isinstance(exc, (SelectorValidationError, HealingError)):
                raise
            raise HealingError(str(exc)) from exc
        finally:
            attempt = HealAttempt(
                element_key=element_key,
                old_selector=element_definition.selector,
                failure_type=type(failure).__name__,
                top_candidates=[self._candidate_payload(item) for item in top_candidates],
                llm_provider=getattr(self.llm_client, "provider_name", "unknown"),
                new_selector=selector,
                success=success,
                artifact_paths={
                    "dom_snapshot": str(dom_path),
                    "screenshot": str(screenshot_path),
                },
            )
            self.audit_logger.write(attempt)

    def _build_payload(
        self,
        *,
        element_definition,
        failure: Exception,
        mode: str,
        page_source: str,
        mutation_events: list[dict[str, Any]],
        top_candidates,
    ) -> dict[str, Any]:
        return {
            "mode": mode,
            "failed_element_key": element_definition.key,
            "old_selector": element_definition.selector,
            "failure_type": type(failure).__name__,
            "expected_role": element_definition.intended_role,
            "historical_metadata": element_definition.historical_metadata.model_dump(),
            "top_ranked_candidates": [self._candidate_payload(item) for item in top_candidates],
            "dom_snippet": build_dom_snippet(page_source, list(top_candidates)),
            "mutation_events": mutation_events[-20:],
        }

    @staticmethod
    def _candidate_payload(candidate) -> dict[str, Any]:
        return {
            "selector_hint": candidate.selector_hint,
            "tag": candidate.tag,
            "text": candidate.text,
            "attributes": candidate.attributes,
            "parent_tag": candidate.parent_tag,
            "rect": candidate.rect,
            "styles": candidate.styles,
            "heuristic_score": candidate.heuristic_score,
        }

    @staticmethod
    def _validate_selector(driver, selector: str, selector_type: str) -> None:
        by = By.XPATH if selector_type == "xpath" else By.CSS_SELECTOR
        try:
            matches = driver.find_elements(by, selector)
        except InvalidSelectorException as exc:
            raise SelectorValidationError("LLM returned an invalid selector") from exc
        if not matches:
            raise SelectorValidationError("LLM selector did not match any element")
