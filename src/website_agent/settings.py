from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Limits(BaseModel):
    discovered: int = Field(30, ge=1, le=200)
    inspected: int = Field(10, ge=1, le=100)
    qualified: int = Field(5, ge=1, le=100)
    previews_daily: int = Field(2, ge=0)
    outreach_daily: int = Field(2, ge=0)
    followups_daily: int = Field(2, ge=0)
    max_followups: int = Field(2, ge=0, le=2)
    threshold: int = Field(55, ge=0, le=100)
    ai_requests_daily: int = Field(30, ge=0)
    ai_budget_usd: float = Field(1.0, ge=0)
    database_max_mb: int = Field(400, ge=1)


class Location(BaseModel):
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str
    timezone: str
    language: str
    subdivision: str | None = None

    @model_validator(mode="after")
    def timezone_exists(self):
        ZoneInfo(self.timezone)
        return self


class Config(BaseModel):
    limits: Limits = Field(default_factory=Limits)
    locations: list[Location]
    niches: list[str]
    search_template: str = "{niche} {city} {country} official website"
    schedule_timezone: str = "UTC"
    schedule_hour: int = Field(3, ge=0, le=23)
    research_hours: list[int] = [8, 20]
    discovery_provider: Literal["brave", "licensed_json"] = "brave"
    provider_agreement_reference: str = ""
    storage_and_outreach_use_authorized: bool = False
    discovery_endpoint: str = ""
    model_prices: dict[str, dict[str, float]] = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_advanced_model: str = "gemini-4-argon"
    gemini_fallback_models: str = ""
    discovery_api_key: str = ""
    netlify_auth_token: str = ""
    netlify_site_id: str = ""
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    sender_name: str = ""
    sender_email: str = ""
    reply_to: str = ""
    sender_postal_address: str = ""
    owner_email: str = ""
    enable_sending: bool = False
    enable_routine_replies: bool = False
    config_path: str = "config/settings.yml"
    policy_path: str = "config/country-policies.yml"
    research_user_agent: str = "GlobalWebsiteConceptBot/1.0"

    def config(self) -> Config:
        return Config.model_validate(yaml.safe_load(Path(self.config_path).read_text(encoding="utf-8")))

    def require(self, *names):
        missing = [n.upper() for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError("Missing configuration: " + ", ".join(missing))
