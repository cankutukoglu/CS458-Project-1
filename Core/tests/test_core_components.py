from __future__ import annotations

import json

from framework.llm.client import GeminiSelectorRepairClient, create_selector_repair_client
from framework.config.loader import ConfigLoader
from framework.llm.parser import infer_selector_type, parse_selector_response
from framework.utils.scoring import score_candidates


def test_config_loader_validates_json(tmp_path):
    config_path = tmp_path / "suite.json"
    config_path.write_text(
        json.dumps(
            {
                "environment": {
                    "base_url": "http://localhost:8000",
                    "api_base_url": "http://localhost:8000",
                    "browser_matrix": ["chrome"],
                    "default_timeout_seconds": 5,
                    "headless": True
                },
                "credentials": {
                    "email": "a@example.com",
                    "phone": "+10000000000",
                    "password": "secret"
                },
                "elements": [
                    {
                        "key": "login_button",
                        "intended_role": "button",
                        "selector_type": "css",
                        "selector": "#login",
                        "fallback_selectors": [],
                        "historical_metadata": {
                            "parent_tag": "form",
                            "location": {"x": 1, "y": 2},
                            "color": "rgb(0, 0, 0)"
                        }
                    }
                ],
                "scenarios": {}
            }
        ),
        encoding="utf-8",
    )
    config = ConfigLoader.load(config_path)
    assert config.environment.browser_matrix == ["chrome"]
    assert config.get_element("login_button").selector == "#login"


def test_selector_parser_accepts_css_and_xpath():
    css_selector, css_type = parse_selector_response("#login-button")
    xpath_selector, xpath_type = parse_selector_response("//button[@type='submit']")
    assert css_selector == "#login-button"
    assert css_type == "css"
    assert xpath_selector == "//button[@type='submit']"
    assert xpath_type == "xpath"
    assert infer_selector_type("(//button)[1]") == "xpath"


def test_scoring_prefers_closer_match(suite_config):
    element_definition = suite_config.get_element("login_button")
    candidates = [
        type(
            "Candidate",
            (),
            {
                "selector_hint": "#wrong",
                "tag": "div",
                "text": "Ignore",
                "attributes": {"class": "foo"},
                "parent_tag": "section",
                "rect": {"x": 1, "y": 1},
                "styles": {"color": "rgb(0, 0, 0)"},
                "heuristic_score": 0.0,
            },
        )(),
        type(
            "Candidate",
            (),
            {
                "selector_hint": "#login-button",
                "tag": "button",
                "text": "Login",
                "attributes": {"type": "submit", "class": "btn btn-primary"},
                "parent_tag": "form",
                "rect": {"x": 320, "y": 410},
                "styles": {"color": "rgb(255, 255, 255)"},
                "heuristic_score": 0.0,
            },
        )(),
    ]
    scored = score_candidates(element_definition, candidates)
    assert scored[0].selector_hint == "#login-button"


def test_selector_client_factory_supports_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = create_selector_repair_client()
    assert isinstance(client, GeminiSelectorRepairClient)
    assert client.provider_name == "gemini"
