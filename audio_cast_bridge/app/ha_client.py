"""Home Assistant Supervisor API client for entity discovery and media control."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urljoin

import aiohttp

LOGGER = logging.getLogger("acb.ha")

# Integrations that can receive a LAN HTTP stream via media_player.play_media
ELIGIBLE_DOMAINS = frozenset({
    "linkplay",
    "wiim",       # official WiiM / LinkPlay-family core integration
    "dlna_dmr",
})
CAST_DOMAIN = "cast"
TRACKED_DOMAINS = frozenset({*ELIGIBLE_DOMAINS, CAST_DOMAIN})


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

    def _ws_url(self) -> str:
        base = self.base_url
        if base.startswith("https://"):
            return "wss://" + base[len("https://") :] + "/api/websocket"
        if base.startswith("http://"):
            return "ws://" + base[len("http://") :] + "/api/websocket"
        return "ws://" + base + "/api/websocket"

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

    async def entity_registry_list(self) -> list[dict[str, Any]]:
        """Fetch entity registry via WebSocket (includes integration platform)."""
        if self._session is None:
            raise RuntimeError("HomeAssistantClient session is not started")
        ws_url = self._ws_url()
        LOGGER.debug("Connecting to HA websocket %s", ws_url)
        async with self._session.ws_connect(ws_url, heartbeat=30) as ws:
            msg = await ws.receive_json()
            if msg.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected WS hello: {msg!r}")
            await ws.send_json({"type": "auth", "access_token": self.token})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                raise RuntimeError(f"HA websocket auth failed: {auth!r}")
            await ws.send_json({"id": 1, "type": "config/entity_registry/list"})
            while True:
                resp = await ws.receive_json()
                if resp.get("id") != 1:
                    continue
                if not resp.get("success"):
                    raise RuntimeError(f"entity_registry/list failed: {resp!r}")
                result = resp.get("result")
                if isinstance(result, list):
                    return result
                raise RuntimeError(f"Unexpected entity_registry result type: {type(result)}")

    async def platforms_for_media_players(self) -> dict[str, str]:
        """Map media_player entity_id -> integration platform (e.g. wiim, dlna_dmr)."""
        mapping: dict[str, str] = {}
        entries = await self.entity_registry_list()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entity_id = str(entry.get("entity_id") or "")
            if not entity_id.startswith("media_player."):
                continue
            # Entity registry: domain = component (media_player), platform = integration
            platform = entry.get("platform") or entry.get("pl")
            if isinstance(platform, str) and platform:
                mapping[entity_id] = platform
        counts: dict[str, int] = {}
        for platform in mapping.values():
            counts[platform] = counts.get(platform, 0) + 1
        LOGGER.info(
            "Entity registry: %s media_player platforms: %s",
            len(mapping),
            dict(sorted(counts.items())),
        )
        return mapping

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


def _ip_from_attributes(attrs: dict[str, Any]) -> str | None:
    for key in ("ip_address", "host", "hostname", "ip"):
        val = attrs.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return None


def classify_media_players(
    states: list[dict[str, Any]],
    platform_by_entity: dict[str, str],
) -> dict[str, Any]:
    """Split media_player entities into eligible vs skipped (native Cast)."""
    cast_ips: set[str] = set()
    cast_entity_ids: set[str] = set()
    players: list[dict[str, Any]] = []
    media_player_total = 0
    platform_counts: dict[str, int] = {}

    for state in states:
        entity_id = str(state.get("entity_id") or "")
        if not entity_id.startswith("media_player."):
            continue
        media_player_total += 1
        attrs = state.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        domain = platform_by_entity.get(entity_id, "unknown")
        platform_counts[domain] = platform_counts.get(domain, 0) + 1
        ip = _ip_from_attributes(attrs)
        item = {
            "entity_id": entity_id,
            "friendly_name": attrs.get("friendly_name") or entity_id,
            "state": state.get("state"),
            "domain": domain,
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
        "diagnostics": {
            "media_player_total": media_player_total,
            "eligible_domains": sorted(ELIGIBLE_DOMAINS),
            "tracked_platforms": {
                domain: platform_counts.get(domain, 0) for domain in sorted(TRACKED_DOMAINS)
            },
            "all_platforms": dict(sorted(platform_counts.items())),
            "platform_mapped": len(platform_by_entity),
        },
    }
