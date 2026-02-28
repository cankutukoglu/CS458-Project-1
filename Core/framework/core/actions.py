from __future__ import annotations

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
)


class SafeActions:
    """High-level browser actions routed through the healing pipeline."""

    def __init__(self, driver, finder, healer) -> None:
        self.driver = driver
        self.finder = finder
        self.healer = healer

    def click(self, element_key: str) -> None:
        element = self.finder.find(element_key)
        try:
            element.click()
            return
        except ElementClickInterceptedException as exc:
            dismiss_selector = self.healer.recover(self.driver, element_key, exc, mode="obstacle_repair")
            self.finder.find_by_selector(dismiss_selector).click()
            self.finder.find(element_key).click()
        except (ElementNotInteractableException, StaleElementReferenceException):
            self.finder.find(element_key).click()

    def type(self, element_key: str, value: str, clear_first: bool = True) -> None:
        element = self.finder.find(element_key)
        try:
            if clear_first:
                element.clear()
            element.send_keys(value)
        except (ElementNotInteractableException, StaleElementReferenceException):
            element = self.finder.find(element_key)
            if clear_first:
                element.clear()
            element.send_keys(value)
