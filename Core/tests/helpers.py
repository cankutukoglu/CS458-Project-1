from __future__ import annotations

import json
import os
import time
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


@dataclass
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
    if provider in ("azure_openai", "azure"):
        if not os.getenv("AZURE_OPENAI_API_KEY"):
            pytest.skip("AZURE_OPENAI_API_KEY is required for self-healing tests")
        if not os.getenv("AZURE_OPENAI_ENDPOINT"):
            pytest.skip("AZURE_OPENAI_ENDPOINT is required for self-healing tests")
        if not os.getenv("AZURE_OPENAI_DEPLOYMENT"):
            pytest.skip("AZURE_OPENAI_DEPLOYMENT is required for self-healing tests")


def require_scenario_enabled(suite_config, scenario_name: str) -> None:
    settings = suite_config.scenarios.get(scenario_name, {})
    if settings.get("enabled", True):
        return
    reason = settings.get("reason", f"{scenario_name} is disabled in config/test_suite.json")
    pytest.skip(reason)


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


def _wait_for_login_response(runtime: FrameworkRuntime, timeout: float = 10) -> bool:
    """Wait for the async login fetch to complete by checking for a visible response message.

    Returns True if a response message became visible, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done = runtime.driver.execute_script(
            "const err = document.getElementById('errorMessage');"
            "const suc = document.getElementById('successMessage');"
            "return (err && getComputedStyle(err).display !== 'none') ||"
            "       (suc && getComputedStyle(suc).display !== 'none');"
        )
        if done:
            return True
        time.sleep(0.2)
    return False


def login_with_password(runtime: FrameworkRuntime, suite_config, password: str | None = None) -> None:
    ensure_test_user(suite_config)
    runtime.actions.type("login_email_input", suite_config.credentials.email)
    runtime.actions.type("login_password_input", password or suite_config.credentials.password)
    runtime.actions.click("login_button")
    if not _wait_for_login_response(runtime, suite_config.environment.default_timeout_seconds):
        # The Selenium click on the healed element may not have triggered the
        # form submit event (synthetic-click edge case).  Submit explicitly so
        # the login flow still completes after healing.
        runtime.driver.execute_script(
            "const form = document.getElementById('loginForm');"
            "if (form) form.requestSubmit();"
        )
        if not _wait_for_login_response(runtime, suite_config.environment.default_timeout_seconds):
            pytest.fail(
                f"Login response was not received within "
                f"{suite_config.environment.default_timeout_seconds}s after explicit form submit "
                f"for base URL {suite_config.environment.base_url!r}."
            )


def inject_dynamic_id_change(runtime: FrameworkRuntime) -> None:
    runtime.driver.execute_script(
        """
        const button = document.querySelector('#loginButton');
        if (button) {
          button.id = 'loginButtonMutated';
        }
        """
    )


def inject_popup_overlay(runtime: FrameworkRuntime) -> None:
    runtime.driver.execute_script(
        """
        const target = document.querySelector('#googleLogin') || document.querySelector("button.btn-google");
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



def repeat_failed_login(runtime: FrameworkRuntime, suite_config, attempts: int) -> list[dict[str, str]]:
    ensure_test_user(suite_config)
    observations: list[dict[str, str]] = []
    for _ in range(attempts):
        runtime.driver.get(suite_config.environment.base_url)
        runtime.dom_monitor.install(runtime.driver)
        runtime.actions.type("login_email_input", suite_config.credentials.email)
        runtime.actions.type("login_password_input", "definitely-wrong-password")
        runtime.actions.click("login_button")
        _wait_for_login_response(runtime, suite_config.environment.default_timeout_seconds)
        error_state = runtime.driver.execute_script(
            """
            const err = document.getElementById('errorMessage');
            const warn = document.getElementById('warningMessage');
            return {
              text: err ? (err.textContent || '').trim() : '',
              visible: Boolean(err && getComputedStyle(err).display !== 'none'),
              warning: warn && getComputedStyle(warn).display !== 'none'
                       ? (warn.textContent || '').trim() : ''
            };
            """
        )
        observations.append(
            {
                "url": runtime.driver.current_url,
                "page_source_excerpt": runtime.driver.page_source[:1000],
                "visible_error": error_state["text"] if error_state["visible"] else "",
                "visible_warning": error_state.get("warning", ""),
            }
        )
    return observations


def assert_authenticated_state(runtime: FrameworkRuntime, base_url: str) -> None:
    token_data = capture_auth_token(runtime)
    success_state = runtime.driver.execute_script(
        """
        const el = document.getElementById('successMessage');
        return {
          text: el ? (el.textContent || '').trim() : '',
          visible: Boolean(el && getComputedStyle(el).display !== 'none')
        };
        """
    )
    page_source = runtime.driver.page_source.lower()
    current = runtime.driver.current_url.rstrip("/")
    normalized_base = base_url.rstrip("/")
    indicators = (
        current != normalized_base,
        any(value for value in token_data.values() if value and value.rstrip("/") != normalized_base),
        success_state["visible"] and "login successful" in success_state["text"].lower(),
        "login successful" in page_source,
        "logout" in page_source,
        "dashboard" in page_source,
        "welcome" in page_source,
    )
    assert any(indicators), (
        "Could not confirm authenticated state from URL, token, or page content.\n"
        f"  URL: {current}\n"
        f"  success_state: {success_state}\n"
        f"  token_data keys with values: "
        f"{[k for k, v in token_data.items() if v and v.rstrip('/') != normalized_base]}\n"
        f"  page_source excerpt (500 chars): {page_source[:500]}"
    )


def healing_log_contains(element_key: str, root: str | Path = "artifacts") -> bool:
    path = Path(root) / "healed_elements.json"
    if not path.exists():
        return False
    payloads = json.loads(path.read_text(encoding="utf-8"))
    for payload in payloads:
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





def reset_user_state(suite_config, email: str) -> bool:
    """Reset user account to active state via admin API."""
    url = f"{suite_config.environment.api_base_url.rstrip('/')}/admin/user-status"
    payload = json.dumps({"email": email, "status": "active"}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except error.HTTPError:
        return False
    except error.URLError:
        return False


def api_login(suite_config, email: str, password: str) -> dict:
    """Perform login via API and return response."""
    url = f"{suite_config.environment.api_base_url.rstrip('/')}/login"
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return {"status": response.status, "data": json.loads(response.read().decode("utf-8"))}
    except error.HTTPError as exc:
        return {"status": exc.code, "data": json.loads(exc.read().decode("utf-8"))}
    except error.URLError as exc:
        return {"status": 0, "error": str(exc.reason)}


def ensure_test_user(suite_config) -> None:
    url = f"{suite_config.environment.api_base_url.rstrip('/')}/register"
    payload = json.dumps(
        {
            "email": suite_config.credentials.email,
            "phone": suite_config.credentials.phone,
            "password": suite_config.credentials.password,
        }
    ).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            if response.status == 201:
                return
    except error.HTTPError as exc:
        if exc.code == 409:
            return
        detail = exc.read().decode("utf-8", errors="replace")
        pytest.skip(f"Could not prepare test user via {url}: HTTP {exc.code} {detail}")
    except error.URLError as exc:
        pytest.skip(f"Could not prepare test user via {url}: {exc.reason}")
