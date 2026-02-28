from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib import error, request

import pytest
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from framework.core.actions import SafeActions
from framework.core.browser import BrowserSession
from framework.core.dom_monitor import DomMonitor
from framework.core.finder import SafeFinder
from framework.core.healer import Healer
from framework.llm.client import create_selector_repair_client
from framework.logging.artifacts import ArtifactManager
from framework.logging.audit import HealingAuditLogger


@dataclass(slots=True)
class FrameworkRuntime:
    driver: object
    browser_session: BrowserSession
    dom_monitor: DomMonitor
    artifact_manager: ArtifactManager
    audit_logger: HealingAuditLogger
    healer: Healer
    finder: SafeFinder
    actions: SafeActions


class LazySelectorRepairClient:
    """Defers provider client construction until a heal is actually needed."""

    def __init__(self) -> None:
        self.provider_name = os.getenv("LLM_PROVIDER", "openai").lower()
        self._client = None

    def repair_selector(self, payload):
        if self._client is None:
            self._client = create_selector_repair_client()
            self.provider_name = self._client.provider_name
        return self._client.repair_selector(payload)


def require_reachable_base_url(suite_config) -> None:
    try:
        with request.urlopen(suite_config.environment.base_url, timeout=2):
            return
    except (error.URLError, TimeoutError) as exc:
        pytest.skip(f"Target app is not reachable at {suite_config.environment.base_url}: {exc}")


def require_llm_credentials() -> None:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for self-healing tests")
    if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is required for self-healing tests")
    if provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is required for self-healing tests")


def require_social_credentials(suite_config, provider: str) -> tuple[str, str]:
    if provider == "google":
        username = suite_config.credentials.google_username
        password = suite_config.credentials.google_password
    else:
        username = suite_config.credentials.facebook_username
        password = suite_config.credentials.facebook_password
    if not username or not password:
        pytest.skip(f"Missing {provider} test credentials in config/test_suite.json")
    return username, password


@contextmanager
def managed_runtime(suite_config, browser_name: str) -> Iterator[FrameworkRuntime]:
    browser_session = BrowserSession(suite_config.environment)
    try:
        driver = browser_session.start(browser_name)
    except WebDriverException as exc:
        pytest.skip(f"WebDriver could not start for {browser_name}: {exc}")
    dom_monitor = DomMonitor()
    dom_monitor.install(driver)
    artifact_manager = ArtifactManager()
    audit_logger = HealingAuditLogger()
    llm_client = LazySelectorRepairClient()
    healer = Healer(suite_config, llm_client, dom_monitor, artifact_manager, audit_logger)
    finder = SafeFinder(driver, suite_config, dom_monitor, healer, audit_logger)
    actions = SafeActions(driver, finder, healer)
    runtime = FrameworkRuntime(
        driver=driver,
        browser_session=browser_session,
        dom_monitor=dom_monitor,
        artifact_manager=artifact_manager,
        audit_logger=audit_logger,
        healer=healer,
        finder=finder,
        actions=actions,
    )
    try:
        yield runtime
    finally:
        driver.quit()


def open_login_page(runtime: FrameworkRuntime, suite_config) -> None:
    runtime.driver.get(suite_config.environment.base_url)
    runtime.dom_monitor.install(runtime.driver)


def login_with_password(runtime: FrameworkRuntime, suite_config, password: str | None = None) -> None:
    runtime.actions.type("login_email_input", suite_config.credentials.email)
    runtime.actions.type("login_password_input", password or suite_config.credentials.password)
    runtime.actions.click("login_button")


def inject_dynamic_id_change(runtime: FrameworkRuntime) -> None:
    runtime.driver.execute_script(
        """
        const button = document.querySelector('#login-button');
        if (button) {
          button.id = 'login-button-mutated';
        }
        """
    )


def inject_popup_overlay(runtime: FrameworkRuntime) -> None:
    runtime.driver.execute_script(
        """
        const target = document.querySelector('#google-login') || document.querySelector("button[data-provider='google']");
        if (!target) return;
        if (document.getElementById('__codex_blocker__')) return;
        const rect = target.getBoundingClientRect();
        const overlay = document.createElement('div');
        overlay.id = '__codex_blocker__';
        overlay.style.position = 'fixed';
        overlay.style.left = `${rect.left}px`;
        overlay.style.top = `${rect.top}px`;
        overlay.style.width = `${Math.max(rect.width, 240)}px`;
        overlay.style.height = `${Math.max(rect.height, 120)}px`;
        overlay.style.background = 'rgba(0, 0, 0, 0.85)';
        overlay.style.zIndex = '2147483647';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.id = '__codex_blocker_close__';
        closeButton.textContent = 'Close Popup';
        closeButton.style.padding = '12px 16px';
        closeButton.addEventListener('click', () => overlay.remove());
        overlay.appendChild(closeButton);
        document.body.appendChild(overlay);
        """
    )


def popup_overlay_present(runtime: FrameworkRuntime) -> bool:
    return bool(
        runtime.driver.execute_script(
            "return Boolean(document.getElementById('__codex_blocker__'));"
        )
    )


def inject_css_breakage(runtime: FrameworkRuntime) -> None:
    runtime.driver.execute_script(
        """
        if (document.getElementById('__codex_css_breakage__')) return;
        const style = document.createElement('style');
        style.id = '__codex_css_breakage__';
        style.textContent = `
          * { transition: none !important; }
          form { transform: translateX(120px) !important; }
          label { opacity: 0 !important; }
          button { letter-spacing: 0.2em !important; }
        `;
        document.head.appendChild(style);
        document.body.dataset.codexCssBreakage = 'true';
        """
    )


def css_breakage_applied(runtime: FrameworkRuntime) -> bool:
    return bool(
        runtime.driver.execute_script(
            "return document.body.dataset.codexCssBreakage === 'true';"
        )
    )


def capture_auth_token(runtime: FrameworkRuntime) -> dict[str, str]:
    token_data = runtime.driver.execute_script(
        """
        return {
          url: window.location.href,
          hash: window.location.hash,
          query: window.location.search,
          localStorageToken: window.localStorage.getItem('token') || '',
          sessionStorageToken: window.sessionStorage.getItem('token') || ''
        };
        """
    )
    for cookie in runtime.driver.get_cookies():
        if "token" in cookie["name"].lower():
            token_data["cookieToken"] = cookie["value"]
            break
    return token_data


def complete_social_provider_login(runtime: FrameworkRuntime, provider: str, username: str, password: str) -> None:
    if provider == "google":
        _send_keys_if_present(runtime, By.ID, "identifierId", username)
        _click_if_present(runtime, By.ID, "identifierNext")
        _send_keys_if_present(runtime, By.NAME, "Passwd", password)
        _click_if_present(runtime, By.ID, "passwordNext")
    else:
        _send_keys_if_present(runtime, By.ID, "email", username)
        _send_keys_if_present(runtime, By.ID, "pass", password)
        _click_if_present(runtime, By.NAME, "login")


def repeat_failed_login(runtime: FrameworkRuntime, suite_config, attempts: int) -> list[dict[str, str]]:
    observations: list[dict[str, str]] = []
    for _ in range(attempts):
        runtime.driver.get(suite_config.environment.base_url)
        runtime.dom_monitor.install(runtime.driver)
        runtime.actions.type("login_email_input", suite_config.credentials.email)
        runtime.actions.type("login_password_input", "definitely-wrong-password")
        runtime.actions.click("login_button")
        observations.append(
            {
                "url": runtime.driver.current_url,
                "page_source_excerpt": runtime.driver.page_source[:1000],
            }
        )
    return observations


def assert_authenticated_state(runtime: FrameworkRuntime, base_url: str) -> None:
    token_data = capture_auth_token(runtime)
    page_source = runtime.driver.page_source.lower()
    indicators = (
        runtime.driver.current_url != base_url,
        any(value for value in token_data.values() if value and value != base_url),
        "logout" in page_source,
        "dashboard" in page_source,
        "welcome" in page_source,
    )
    assert any(indicators), "Could not confirm authenticated state from URL, token, or page content"


def healing_log_contains(element_key: str, root: str | Path = "artifacts") -> bool:
    path = Path(root) / "healed_elements.jsonl"
    if not path.exists():
        return False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("element_key") == element_key and payload.get("success"):
                return True
    return False


def _send_keys_if_present(runtime: FrameworkRuntime, by: str, selector: str, value: str) -> None:
    elements = runtime.driver.find_elements(by, selector)
    if elements:
        elements[0].clear()
        elements[0].send_keys(value)


def _click_if_present(runtime: FrameworkRuntime, by: str, selector: str) -> None:
    elements = runtime.driver.find_elements(by, selector)
    if elements:
        elements[0].click()
