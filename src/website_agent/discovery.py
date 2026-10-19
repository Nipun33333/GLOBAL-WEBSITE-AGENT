from typing import Protocol

import httpx
from pydantic import BaseModel, Field, HttpUrl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from website_agent.security import Blocked


class Business(BaseModel):
    provider_id: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=300)
    url: HttpUrl


class DiscoveryProvider(Protocol):
    def discover(self, location, niche, limit: int) -> list[Business]: ...


class TransientAPIError(RuntimeError):
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, TransientAPIError)),
    reraise=True,
)
def api_get(client, url, **kwargs):
    response = client.get(url, **kwargs)
    if response.status_code == 429:
        raise Blocked("Provider rate limit exhausted; paused until a later run")
    if response.status_code >= 500:
        raise TransientAPIError("Provider temporary failure")
    response.raise_for_status()
    return response


class SearchProvider:
    def __init__(self, settings, config, client=None):
        self.settings, self.config = settings, config
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)

    def discover(self, location, niche, limit):
        if (
            not self.config.storage_and_outreach_use_authorized
            or not self.config.provider_agreement_reference
        ):
            raise Blocked("Discovery requires documented provider storage AND outreach-use rights")
        self.settings.require("discovery_api_key")
        query = self.config.search_template.format(niche=niche, city=location.city, country=location.country)
        results = []
        if self.config.discovery_provider == "licensed_json":
            if not self.config.discovery_endpoint.startswith("https://"):
                raise Blocked("Licensed provider requires HTTPS endpoint")
            response = api_get(
                self.client,
                self.config.discovery_endpoint,
                headers={"Authorization": f"Bearer {self.settings.discovery_api_key}"},
                params={"q": query, "country": location.country, "city": location.city, "limit": limit},
            )
            return [Business.model_validate(b) for b in response.json()["businesses"][:limit]]
        # Brave maximum count is 20, offset is bounded; search results are NOT verified business facts.
        for offset in range(min(10, (limit + 19) // 20)):
            response = api_get(
                self.client,
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": self.settings.discovery_api_key},
                params={
                    "q": query,
                    "country": location.country,
                    "count": min(20, limit - len(results)),
                    "offset": offset,
                },
            )
            batch = response.json().get("web", {}).get("results", [])
            for item in batch:
                results.append(Business(provider_id=item["url"], name=item["title"][:300], url=item["url"]))
            if not batch or len(results) >= limit:
                break
        return results[:limit]
