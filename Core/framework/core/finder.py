from __future__ import annotations

from time import monotonic, sleep

from selenium.common.exceptions import (
    InvalidSelectorException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By

from framework.config.schema import TestSuiteConfig
from framework.llm.parser import infer_selector_type


class SafeFinder:
    """Centralized element lookup with automatic healing."""

    def __init__(
        self,
        driver,
        suite_config: TestSuiteConfig,
        dom_monitor,
        healer,
        audit_logger,
    ) -> None:
        self.driver = driver
        self.suite_config = suite_config
        self.dom_monitor = dom_monitor
        self.healer = healer
        self.audit_logger = audit_logger
        self.selector_overrides = audit_logger.read_overrides()

    def find(self, element_key: str, timeout: int | None = None):
        self.dom_monitor.install(self.driver)
        self.dom_monitor.flush_events(self.driver)
        duration = timeout or self.suite_config.environment.default_timeout_seconds
        selectors = self._selector_specs(element_key)
        try:
            return self._wait_for_first_match(selectors, duration)
        except (NoSuchElementException, TimeoutException, StaleElementReferenceException) as exc:
            healed_selector = self.healer.recover(self.driver, element_key, exc, mode="target_repair")
            self.selector_overrides[element_key] = healed_selector
            return self.find_by_selector(healed_selector, timeout=duration)

    def find_by_selector(self, selector: str, timeout: int | None = None):
        selector_type = infer_selector_type(selector)
        by = self._by(selector_type)
        duration = timeout or self.suite_config.environment.default_timeout_seconds
        return self._wait_for_first_match([(by, selector)], duration)

    def _selector_specs(self, element_key: str) -> list[tuple[str, str]]:
        element_definition = self.suite_config.get_element(element_key)
        selectors: list[tuple[str, str]] = []
        override = self.selector_overrides.get(element_key)
        if override:
            selectors.append((self._by(infer_selector_type(override)), override))
        selectors.append((self._by(element_definition.selector_type), element_definition.selector))
        for fallback in element_definition.fallback_selectors:
            selectors.append((self._by(infer_selector_type(fallback)), fallback))
        return selectors

    def _wait_for_first_match(self, selectors: list[tuple[str, str]], timeout: int):
        deadline = monotonic() + timeout
        last_error: Exception | None = None
        while monotonic() < deadline:
            for by, selector in selectors:
                try:
                    matches = self.driver.find_elements(by, selector)
                except InvalidSelectorException as exc:
                    last_error = exc
                    continue
                if matches:
                    return matches[0]
            sleep(0.2)
        if last_error:
            if isinstance(last_error, InvalidSelectorException):
                raise NoSuchElementException(str(last_error)) from last_error
            raise last_error
        raise TimeoutException("Timed out waiting for element")

    @staticmethod
    def _by(selector_type: str) -> str:
        return By.XPATH if selector_type == "xpath" else By.CSS_SELECTOR
