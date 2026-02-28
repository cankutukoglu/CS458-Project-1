from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Location(BaseModel):
    x: float
    y: float


class Size(BaseModel):
    width: float
    height: float


class HistoricalMetadata(BaseModel):
    tag: str | None = None
    parent_tag: str
    text: str | None = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    location: Location
    size: Size | None = None
    color: str
    background_color: str | None = None
    neighbor_signature: list[str] = Field(default_factory=list)
    last_verified_at: str | None = None


class EnvironmentConfig(BaseModel):
    base_url: str
    api_base_url: str
    browser_matrix: list[str] = Field(default_factory=lambda: ["chrome"])
    default_timeout_seconds: int = 10
    headless: bool = False

    @field_validator("browser_matrix")
    @classmethod
    def validate_browsers(cls, value: list[str]) -> list[str]:
        allowed = {"chrome", "firefox"}
        normalized = [item.lower() for item in value]
        invalid = [item for item in normalized if item not in allowed]
        if invalid:
            raise ValueError(f"Unsupported browsers: {', '.join(invalid)}")
        return normalized


class CredentialSet(BaseModel):
    email: str
    phone: str
    password: str
    google_username: str = ""
    google_password: str = ""
    facebook_username: str = ""
    facebook_password: str = ""


class ElementDefinition(BaseModel):
    key: str
    intended_role: str
    selector_type: str
    selector: str
    fallback_selectors: list[str] = Field(default_factory=list)
    historical_metadata: HistoricalMetadata

    @field_validator("selector_type")
    @classmethod
    def validate_selector_type(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"css", "xpath"}:
            raise ValueError("selector_type must be 'css' or 'xpath'")
        return normalized


class TestSuiteConfig(BaseModel):
    environment: EnvironmentConfig
    credentials: CredentialSet
    elements: list[ElementDefinition]
    scenarios: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def get_element(self, key: str) -> ElementDefinition:
        for element in self.elements:
            if element.key == key:
                return element
        raise KeyError(f"Unknown element key: {key}")
