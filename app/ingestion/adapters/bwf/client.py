from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class BWFResponse:
    endpoint_key: str
    url: str
    status_code: int
    payload: dict[str, Any]


class BWFClient:
    """Thin client for routes observed in BWF's production Match Centre bundle.

    The adapter does not infer endpoints, scrape HTML, or expose arbitrary URLs.
    """

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self.settings.bwf_live_base_url.rstrip("/"),
            timeout=self.settings.bwf_request_timeout_seconds,
            headers={"User-Agent": self.settings.bwf_user_agent, "Accept": "application/json"},
            follow_redirects=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(self, endpoint_key: str, path: str, params: dict[str, Any] | None = None) -> BWFResponse:
        response = self._client.get(path, params=params or {})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "results" not in payload:
            raise ValueError(f"BWF response contract failed for {endpoint_key}: missing results")
        return BWFResponse(endpoint_key=endpoint_key, url=str(response.url), status_code=response.status_code, payload=payload)

    def list_current_tournaments(self) -> BWFResponse:
        return self._get("vue-current-live", "/api/match-center/vue-current-live")

    def get_tournament_detail(self, tournament_id: int | str) -> BWFResponse:
        return self._get("vue-tournament-detail", "/api/match-center/vue-tournament-detail", {"tmtId": tournament_id})

    def list_live_matches(self, tournament_id: int | str) -> BWFResponse:
        return self._get("vue-live-matches", "/api/match-center/vue-live-matches", {"tmtId": tournament_id, "tmtType": 0})

    def get_live_match(self, tournament_id: int | str, match_id: int | str) -> BWFResponse:
        return self._get("vue-live-single", "/api/match-center/vue-live-single", {"tmtId": tournament_id, "matchId": match_id})
