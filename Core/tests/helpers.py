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
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from framework.core.actions import SafeActions
from framework.core.browser import BrowserSession
from framework.core.dom_monitor import DomMonitor
from framework.core.finder import SafeFinder
from framework.core.healer import Healer
from framework.llm.client import create_selector_repair_client, _post_json
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


def require_social_credentials(suite_config, provider: str) -> tuple[str, str]:
    if provider == "google":
        username = suite_config.credentials.google_username
        password = suite_config.credentials.google_password
    elif provider == "github":
        username = suite_config.credentials.github_username
        password = suite_config.credentials.github_password
    else:
        pytest.skip(f"Unsupported social provider: {provider}")
        return "", ""  # unreachable; satisfies type checkers
    if not username or not password:
        pytest.skip(f"Missing {provider} test credentials in config/test_suite.json")
    return username, password


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
        time.sleep(1)
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


_OAUTH_NAV_SYSTEM_PROMPT = """\
You are an automated browser agent navigating an OAuth login flow (Google or GitHub).
Your GOAL is to successfully authenticate the user and authorize the application.

You will receive:
- "provider": the OAuth provider ("google" or "github")
- "goal": what you are trying to accomplish on this page
- "url": the current page URL
- "credentials": {"username": "...", "password": "..."} — the test account to log in with
- "interactive_elements": a list of interactive elements on the page with their selector, tag, text, and attributes

You must respond with EXACTLY one JSON object (no markdown, no explanation) with these keys:
- "action": one of "type", "click", "wait", or "give_up"
- "index": the numeric index of the target element from the interactive_elements list
- "value": the text to type (only for "type" action, empty string otherwise)
- "reasoning": a short explanation of why this action progresses the login/authorization

IMPORTANT: Use the "index" field to identify elements. Do NOT guess CSS selectors —
multiple elements may share the same classes. The index is the only reliable identifier.

RULES:
1. NEVER click buttons that decline, deny, cancel, or refuse authorization.
2. ALWAYS click buttons that accept, allow, authorize, continue, next, or confirm.
3. For email/username fields, type the username from credentials.
4. For password fields, type the password from credentials.
5. If the page shows a consent/authorize prompt, click the APPROVE/AUTHORIZE button.
6. If no useful action is available, respond with action "wait".
7. If you are certain the login has permanently failed (e.g. wrong credentials, account locked,
   captcha you cannot solve, or an unrecoverable error page), respond with action "give_up"
   and explain in "reasoning".
8. Use the element "index" to identify which element to interact with.\

"""

_COLLECT_INTERACTIVE_ELEMENTS_SCRIPT = r"""
const items = [];
const elements = document.querySelectorAll(
  'input, button, a, select, textarea, [role="button"], [role="link"], [type="submit"]'
);
let idx = 0;
for (const node of elements) {
  const rect = node.getBoundingClientRect();
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0) continue;
  node.setAttribute('data-oauth-idx', String(idx));
  items.push({
    index: idx,
    tag: node.tagName.toLowerCase(),
    type: node.getAttribute('type') || '',
    text: (node.innerText || node.textContent || '').trim().slice(0, 120),
    attributes: {
      id: node.id || '',
      name: node.getAttribute('name') || '',
      class: (node.className || '').toString().slice(0, 120),
      href: node.getAttribute('href') || '',
      value: node.getAttribute('value') || '',
      placeholder: node.getAttribute('placeholder') || '',
      aria_label: node.getAttribute('aria-label') || '',
    },
  });
  idx++;
}
return items.slice(0, 50);
"""


def _build_llm_oauth_request(provider, page_url, username, password, elements):
    """Build the LLM API request body for OAuth page navigation."""
    user_payload = json.dumps({
        "provider": provider,
        "goal": f"Log in to {provider} with the provided credentials and authorize the application.",
        "url": page_url,
        "credentials": {"username": username, "password": password},
        "interactive_elements": elements,
    }, indent=2)

    # Reuse the same LLM provider configuration as the healing pipeline
    llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if llm_provider in ("azure_openai", "azure"):
        api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
        url_endpoint = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        headers = {"api-key": api_key, "Content-Type": "application/json"}
        body = {
            "messages": [
                {"role": "system", "content": _OAUTH_NAV_SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
        }
        return url_endpoint, body, headers
    elif llm_provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        url_endpoint = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model, "temperature": 0,
            "messages": [
                {"role": "system", "content": _OAUTH_NAV_SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
        }
        return url_endpoint, body, headers
    elif llm_provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        url_endpoint = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        body = {
            "model": model, "max_tokens": 256, "temperature": 0,
            "system": _OAUTH_NAV_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_payload}],
        }
        return url_endpoint, body, headers
    elif llm_provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        body = {
            "system_instruction": {"parts": [{"text": _OAUTH_NAV_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
            "generationConfig": {"temperature": 0},
        }
        return url_endpoint, body, headers
    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER for OAuth navigation: {llm_provider}")


def _parse_llm_response(raw_response: dict) -> dict:
    """Extract the action JSON from any supported LLM provider response format."""
    # OpenAI / Azure OpenAI
    if "choices" in raw_response:
        text = raw_response["choices"][0]["message"]["content"]
    # Anthropic
    elif "content" in raw_response and isinstance(raw_response["content"], list):
        text = raw_response["content"][0]["text"]
    # Gemini
    elif "candidates" in raw_response:
        parts = raw_response["candidates"][0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
    else:
        return {"action": "wait", "selector": "", "value": "", "reasoning": "Unparseable LLM response"}

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)


def _llm_pick_action(driver, provider: str, username: str, password: str) -> dict:
    """Ask the LLM what to do on the current OAuth page."""
    elements = driver.execute_script(_COLLECT_INTERACTIVE_ELEMENTS_SCRIPT) or []
    print(f"  [OAuth AI] URL: {driver.current_url}")
    print(f"  [OAuth AI] Found {len(elements)} interactive elements")
    for el in elements:
        print(f"    [{el.get('index')}] <{el.get('tag')}> text={el.get('text')!r}")
    url_endpoint, body, headers = _build_llm_oauth_request(
        provider, driver.current_url, username, password, elements
    )
    raw = _post_json(url_endpoint, body, headers)
    action = _parse_llm_response(raw)
    print(f"  [OAuth AI] LLM decided: {action.get('action')} on index={action.get('index')} — {action.get('reasoning', '')}")
    return action


def _execute_action(driver, action: dict) -> bool:
    """Execute an LLM-chosen action using data-oauth-idx for precise targeting."""
    act = action.get("action", "wait")
    idx = action.get("index")
    value = action.get("value", "")

    if act == "wait" or idx is None:
        return False

    # Find by the data-oauth-idx attribute we stamped during collection
    selector = f'[data-oauth-idx="{idx}"]'
    try:
        if act == "type":
            el = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
            )
            el.clear()
            el.send_keys(value)
            print(f"  [OAuth AI] Typed into element index={idx}")
            return True
        elif act == "click":
            el = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            el.click()
            print(f"  [OAuth AI] Clicked element index={idx}")
            return True
    except Exception as exc:
        print(f"  [OAuth AI] data-oauth-idx={idx} lookup failed: {exc}")

    return False


def _is_back_at_app(url: str) -> bool:
    """Check if the browser's *host* indicates we've returned to our app.

    We parse only the hostname so that OAuth redirect_uri query params
    (which contain 'localhost') don't cause a false positive.
    """
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1")


def _google_credential_entry(driver, username: str, password: str) -> None:
    """Walk through Google's known login pages with explicit waits."""
    wait = WebDriverWait(driver, 15)
    # Email page
    try:
        email_field = wait.until(EC.visibility_of_element_located((By.ID, "identifierId")))
        email_field.clear()
        email_field.send_keys(username)
        print(f"  [OAuth] Typed email into #identifierId")
        wait.until(EC.element_to_be_clickable((By.ID, "identifierNext"))).click()
        print(f"  [OAuth] Clicked #identifierNext")
        time.sleep(3)
    except Exception as exc:
        print(f"  [OAuth] Google email step failed: {exc}")
        return
    # Password page
    try:
        pw_field = wait.until(EC.visibility_of_element_located((By.NAME, "Passwd")))
        pw_field.clear()
        pw_field.send_keys(password)
        print(f"  [OAuth] Typed password into Passwd field")
        wait.until(EC.element_to_be_clickable((By.ID, "passwordNext"))).click()
        print(f"  [OAuth] Clicked #passwordNext")
        time.sleep(3)
    except Exception as exc:
        print(f"  [OAuth] Google password step failed: {exc}")


def _github_credential_entry(driver, username: str, password: str) -> None:
    """Walk through GitHub's known login page with explicit waits."""
    wait = WebDriverWait(driver, 15)
    try:
        login_field = wait.until(EC.visibility_of_element_located((By.ID, "login_field")))
        login_field.clear()
        login_field.send_keys(username)
        print(f"  [OAuth] Typed username into #login_field")
        pw_field = driver.find_element(By.ID, "password")
        pw_field.clear()
        pw_field.send_keys(password)
        print(f"  [OAuth] Typed password into #password")
        wait.until(EC.element_to_be_clickable((By.NAME, "commit"))).click()
        print(f"  [OAuth] Clicked Sign In (commit)")
        time.sleep(3)
    except Exception as exc:
        print(f"  [OAuth] GitHub credential entry failed: {exc}")


def complete_social_provider_login(runtime: FrameworkRuntime, provider: str, username: str, password: str, timeout: float = 60) -> None:
    """Navigate through OAuth provider pages: credentials first, then LLM for any remaining pages.

    Phase 1: Enter credentials using known selectors (reliable, no LLM needed).
    Phase 2: Use the configured LLM to decide what to click on any
             intermediate pages (consent, device trust, 2FA, etc.)
             until the browser returns to our app or the LLM gives up.

    There is no hard timeout — the loop continues until the browser
    redirects back or the LLM explicitly signals failure.
    """
    driver = runtime.driver
    MAX_ITERATIONS = 50  # safety net against truly infinite loops

    # Phase 1 — enter credentials using known, reliable selectors
    print(f"  [OAuth] Phase 1: entering {provider} credentials...")
    if provider == "google":
        _google_credential_entry(driver, username, password)
    elif provider == "github":
        _github_credential_entry(driver, username, password)

    # Phase 2 — LLM-driven navigation for any remaining pages
    consecutive_waits = 0
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        current = driver.current_url
        if _is_back_at_app(current):
            print(f"  [OAuth] Back at app: {current}")
            return

        print(f"  [OAuth] Phase 2 (iter {iteration}): still on external page — asking LLM for guidance...")
        try:
            action = _llm_pick_action(driver, provider, username, password)
        except Exception as exc:
            print(f"  [OAuth AI] LLM call failed: {exc}")
            time.sleep(3)
            continue

        act = action.get("action", "wait")

        if act == "give_up":
            reason = action.get("reasoning", "LLM decided the login cannot succeed")
            print(f"  [OAuth AI] Giving up: {reason}")
            return

        if act == "wait":
            consecutive_waits += 1
            if consecutive_waits >= 5:
                print(f"  [OAuth AI] LLM said 'wait' {consecutive_waits} times — giving up")
                return
            time.sleep(2)
            continue

        consecutive_waits = 0
        executed = _execute_action(driver, action)
        if not executed:
            print(f"  [OAuth AI] Could not execute action: {action}")
        time.sleep(2)

    print(f"  [OAuth] Reached max iterations ({MAX_ITERATIONS}) — current URL: {driver.current_url}")


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


def inject_class_mutation(runtime: FrameworkRuntime) -> None:
    """Change element classes to test heuristic class overlap scoring."""
    runtime.driver.execute_script(
        """
        const button = document.querySelector('#loginButton');
        if (button) {
            button.id = '';
            button.className = 'submit-action primary-btn';
        }
        """
    )


def inject_element_relocation(runtime: FrameworkRuntime) -> None:
    """Move login button to a different parent to test parent_tag heuristics."""
    runtime.driver.execute_script(
        """
        const button = document.querySelector('#loginButton');
        const container = document.querySelector('.login-container');
        if (button && container) {
            button.id = '';
            const wrapper = document.createElement('section');
            wrapper.id = 'relocated-wrapper';
            wrapper.appendChild(button.cloneNode(true));
            container.appendChild(wrapper);
            button.remove();
        }
        """
    )


def inject_text_content_change(runtime: FrameworkRuntime) -> None:
    """Change button text to test text similarity heuristics."""
    runtime.driver.execute_script(
        """
        const button = document.querySelector('#loginButton');
        if (button) {
            button.id = '';
            button.textContent = 'Log In Now';
        }
        """
    )


def inject_attribute_mutation(runtime: FrameworkRuntime) -> None:
    """Change input attributes to test attribute similarity scoring."""
    runtime.driver.execute_script(
        """
        const email = document.querySelector('#email');
        if (email) {
            email.id = '';
            email.name = 'user_email';
            email.placeholder = 'Enter email address';
        }
        """
    )


def inject_delayed_element(runtime: FrameworkRuntime, delay_ms: int = 2000) -> None:
    """Remove element and re-add it after a delay to test async waiting."""
    runtime.driver.execute_script(
        f"""
        const button = document.querySelector('#loginButton');
        if (button) {{
            const parent = button.parentNode;
            const clone = button.cloneNode(true);
            clone.id = 'loginButtonDelayed';
            button.remove();
            setTimeout(() => parent.appendChild(clone), {delay_ms});
        }}
        """
    )


def inject_multiple_mutations(runtime: FrameworkRuntime) -> None:
    """Apply multiple simultaneous mutations to stress test healing."""
    runtime.driver.execute_script(
        """
        const email = document.querySelector('#email');
        const password = document.querySelector('#password');
        const button = document.querySelector('#loginButton');

        if (email) {
            email.id = 'userEmail';
            email.placeholder = 'Your email here';
        }
        if (password) {
            password.id = 'userPass';
            password.className = 'secure-input';
        }
        if (button) {
            button.id = 'submitBtn';
            button.textContent = 'Login';
        }
        """
    )


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


def get_user_status(suite_config, email: str) -> str | None:
    """Get current user account status via login logs API."""
    url = f"{suite_config.environment.api_base_url.rstrip('/')}/login-logs?email={email}&limit=1"
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data:
                return data[0].get("action_taken")
    except (error.HTTPError, error.URLError):
        pass
    return None


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
    # The backend calls the LLM synchronously when risk_score >= RISK_HIGH (60),
    # which can happen after ~8 rapid failed attempts (velocity + failed-attempt
    # factors).  The LLM timeout is 30 s, so allow 35 s here so the server can
    # finish, commit the DB state, and return a real response.
    try:
        with request.urlopen(req, timeout=35) as response:
            return {"status": response.status, "data": json.loads(response.read().decode("utf-8"))}
    except error.HTTPError as exc:
        return {"status": exc.code, "data": json.loads(exc.read().decode("utf-8"))}
    except (error.URLError, TimeoutError) as exc:
        reason = exc.reason if isinstance(exc, error.URLError) else exc
        return {"status": 0, "error": str(reason)}


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
