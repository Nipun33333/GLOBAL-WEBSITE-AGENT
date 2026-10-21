from datetime import date
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


class SearchArea(BaseModel):
    # Explicit names avoid assigning nearby towns to the requested city.
    city: str
    country: str = Field(pattern=r"^[A-Z]{2}$")
    bbox: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_bbox(self):
        west, south, east, north = self.bbox
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("Invalid non-antimeridian bbox")
        return self


class DiscoveryConfig(BaseModel):
    source_priority: list[Literal["overture", "osm_extract", "overpass"]] = ["overture", "osm_extract"]
    release: str = Field("2026-09-23.1", pattern=r"^(latest|[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+)$")
    release_reference: str = "https://docs.overturemaps.org/getting-data/"
    overture_enabled: bool = True
    cache_hours: int = Field(168, ge=0, le=720)
    max_requests: int = Field(160, ge=1, le=2000)
    max_download_bytes: int = Field(64_000_000, ge=1024, le=1_000_000_000)
    max_disk_bytes: int = Field(128_000_000, ge=1024)
    max_memory_mb: int = Field(512, ge=128, le=4096)
    max_seconds: int = Field(300, ge=1, le=1200)
    max_queries: int = Field(8, ge=1, le=64)
    max_candidates: int = Field(120, ge=1, le=1000)
    max_files_per_query: int = Field(8, ge=1, le=100)
    max_cities: int = Field(2, ge=1, le=10)
    max_radius_km: float = Field(25, gt=0, le=100)
    radius_steps_km: list[float] = [3, 8, 15]
    max_attempts: int = Field(3, ge=1, le=5)
    retry_base_seconds: float = Field(1, ge=0, le=30)
    cooldown_seconds: int = Field(3600, ge=60)
    empty_retry_hours: int = Field(24, ge=1)
    max_retry_cycles: int = Field(7, ge=1, le=30)
    taxonomy_path: str = "config/discovery-taxonomy.yml"
    osm_extracts: list[dict] = Field(default_factory=list)
    osm_license_review_reference: str = ""
    osm_database_obligations_accepted: bool = False
    overpass_endpoint: str = ""
    overpass_private_or_contracted: bool = False
    overpass_commercial_use_authorized: bool = False
    overpass_agreement_reference: str = ""

    @model_validator(mode="after")
    def bounded_radii(self):
        if any(r <= 0 or r > self.max_radius_km for r in self.radius_steps_km):
            raise ValueError("Radius steps must fit maximum radius")
        if len(self.radius_steps_km) > 4 or len(self.source_priority) != len(set(self.source_priority)):
            raise ValueError("Too many radii or repeated sources")
        return self


class Location(BaseModel):
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str
    timezone: str
    language: str
    subdivision: str | None = None
    bbox: list[float] | None = None
    nearby_areas: list[SearchArea] = Field(default_factory=list)

    @model_validator(mode="after")
    def timezone_exists(self):
        ZoneInfo(self.timezone)
        if self.bbox is not None:
            SearchArea(city=self.city, country=self.country, bbox=self.bbox)
        return self


class ModelAuthorization(BaseModel):
    tier: Literal["free", "paid"]
    review_reference: str = Field(min_length=1, max_length=200)
    expires_on: date


class ModelCapability(BaseModel):
    structured_output: bool = True
    input_tokens: int = Field(1_048_576, ge=1)
    output_tokens: int = Field(65_536, ge=1)
    active: bool = True
    review_reference: str = Field(min_length=1)
    review_expires_on: date


class GeminiPolicy(BaseModel):
    automatic_fallback: bool = True
    prefer_free_tier: bool = True
    allow_paid_fallback: bool = False
    max_model_attempts: int = Field(3, ge=1, le=5)
    retries_per_model: int = Field(2, ge=0, le=2)
    cooldown_seconds: int = Field(900, ge=60, le=86400)
    max_output_tokens: int = Field(8192, ge=256, le=8192)
    fallback_models: list[str] = Field(
        default_factory=lambda: [
            "gemini-3.6-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ],
        max_length=7,
    )
    capabilities: dict[str, ModelCapability] = Field(
        default_factory=lambda: {
            name: ModelCapability(
                review_reference="https://ai.google.dev/gemini-api/docs/models/" + name,
                review_expires_on=date(2027, 1, 19),
            )
            for name in [
                "gemini-3.8-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
            ]
        }
    )
    usage_authorizations: dict[str, ModelAuthorization] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exact_models(self):
        import re

        names = [*self.fallback_models, *self.capabilities, *self.usage_authorizations]
        if any(not re.fullmatch(r"gemini-[a-z0-9]+(?:[.-][a-z0-9]+)*", name) for name in names):
            raise ValueError("Use exact Gemini model IDs, never wildcards")
        if len(self.capabilities) > 20 or len(set(self.fallback_models)) != len(self.fallback_models):
            raise ValueError("Bounded unique model catalog required")
        return self


class Config(BaseModel):
    limits: Limits = Field(default_factory=Limits)
    locations: list[Location]
    niches: list[str]
    search_template: str = "{niche} {city} {country} official website"
    schedule_timezone: str = "UTC"
    schedule_hour: int = Field(3, ge=0, le=23)
    schedule_hours: list[int] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_schedule_hours(self):
        if self.schedule_hours != sorted(set(self.schedule_hours)):
            raise ValueError("Schedule hours must be sorted and distinct")
        if any(hour < 0 or hour > 23 for hour in self.schedule_hours):
            raise ValueError("Schedule hours must be between 0 and 23")
        return self
    research_hours: list[int] = [8, 20]
    discovery_provider: Literal["open_data", "brave", "licensed_json"] = "open_data"
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    provider_agreement_reference: str = ""
    storage_and_outreach_use_authorized: bool = False
    discovery_endpoint: str = ""
    gemini: GeminiPolicy = Field(default_factory=GeminiPolicy)
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
    enable_generation: bool = False
    enable_deployment: bool = False
    enable_drafts: bool = False
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
