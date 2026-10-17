"""Home Assistant Supervisor API client for entity discovery and media control."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

import aiohttp

LOGGER = logging.getLogger("acb.ha")

ELIGIBLE_DOMAINS = frozenset({"linkplay", "dlna_dmr"})
CAST_DOMAIN = "cast"


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("ACB_HA_URL")
            or "http://supervisor/core"
        ).rstrip("/")
        self.token = token or os.environ.get("SUPERVISOR_TOKEN") or ""
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "HomeAssistantClient":
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._owns_session = True
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._session is None:
            raise RuntimeError("HomeAssistantClient session is not started")
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        async with self._session.request(
            method, url, headers=self._headers(), **kwargs
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"HA API {method} {path} -> {resp.status}: {text[:300]}")
            if not text:
                return None
            try:
                return await resp.json(content_type=None)
            except Exception:
                return text

    async def get_states(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/states")
        return data if isinstance(data, list) else []

    async def get_config_entries(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/config/config_entries/entry")
        return data if isinstance(data, list) else []

    async def call_service(
        self, domain: str, service: str, data: dict[str, Any] | None = None
    ) -> Any:
        return await self._request(
            "POST",
            f"/api/services/{domain}/{service}",
            json=data or {},
        )

    async def play_media(
        self, entity_id: str, media_url: str, media_type: str = "music"
    ) -> None:
        await self.call_service(
            "media_player",
            "play_media",
            {
                "entity_id": entity_id,
                "media_content_id": media_url,
                "media_content_type": media_type,
            },
        )

    async def media_pause(self, entity_id: str) -> None:
        await self.call_service("media_player", "media_pause", {"entity_id": entity_id})

    async def media_play(self, entity_id: str) -> None:
        await self.call_service("media_player", "media_play", {"entity_id": entity_id})

    async def media_stop(self, entity_id: str) -> None:
        await self.call_service("media_player", "media_stop", {"entity_id": entity_id})

    async def volume_set(self, entity_id: str, volume: float) -> None:
        await self.call_service(
            "media_player",
            "volume_set",
            {"entity_id": entity_id, "volume_level": max(0.0, min(1.0, volume))},
        )

    async def volume_mute(self, entity_id: str, mute: bool) -> None:
        await self.call_service(
            "media_player",
            "volume_mute",
            {"entity_id": entity_id, "is_volume_muted": mute},
        )


def _entry_domain_map(entries: list[dict[str, Any]]) -> dict[str, str]:
    """Map config_entry_id -> integration domain."""
    out: dict[str, str] = {}
    for entry in entries:
        entry_id = entry.get("entry_id") or entry.get("entryId")
        domain = entry.get("domain")
        if entry_id and domain:
            out[str(entry_id)] = str(domain)
    return out


def _ip_from_attributes(attrs: dict[str, Any]) -> str | None:
    for key in ("ip_address", "host", "hostname", "ip"):
        val = attrs.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return None


def classify_media_players(
    states: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Split media_player entities into eligible vs skipped (native Cast)."""
    domain_by_entry = _entry_domain_map(entries)
    cast_ips: set[str] = set()
    cast_entity_ids: set[str] = set()
    players: list[dict[str, Any]] = []

    for state in states:
        entity_id = str(state.get("entity_id") or "")
        if not entity_id.startswith("media_player."):
            continue
        attrs = state.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        entry_id = attrs.get("config_entry_id") or attrs.get("entry_id")
        domain = domain_by_entry.get(str(entry_id), "") if entry_id else ""
        # Fallback: platform attribute sometimes present
        if not domain and isinstance(attrs.get("platform"), str):
            domain = attrs["platform"]
        ip = _ip_from_attributes(attrs)
        item = {
            "entity_id": entity_id,
            "friendly_name": attrs.get("friendly_name") or entity_id,
            "state": state.get("state"),
            "domain": domain or "unknown",
            "ip_address": ip,
            "cast_name": f"{attrs.get('friendly_name') or entity_id} (Audio Cast Bridge)",
        }
        players.append(item)
        if domain == CAST_DOMAIN:
            cast_entity_ids.add(entity_id)
            if ip:
                cast_ips.add(ip)

    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in players:
        domain = item["domain"]
        if domain == CAST_DOMAIN:
            skipped.append({**item, "skip_reason": "native_google_cast"})
            continue
        if domain not in ELIGIBLE_DOMAINS:
            continue
        ip = item.get("ip_address")
        if ip and ip in cast_ips:
            skipped.append({**item, "skip_reason": "same_ip_has_cast"})
            continue
        eligible.append(item)

    return {
        "eligible": sorted(eligible, key=lambda x: str(x["friendly_name"]).lower()),
        "skipped": sorted(skipped, key=lambda x: str(x["friendly_name"]).lower()),
        "cast_entity_ids": sorted(cast_entity_ids),
    }
