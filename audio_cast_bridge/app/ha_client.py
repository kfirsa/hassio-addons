"""Home Assistant Supervisor API client for entity discovery and media control."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urljoin

import aiohttp

LOGGER = logging.getLogger("acb.ha")

ELIGIBLE_DOMAINS = frozenset({"linkplay", "dlna_dmr"})
CAST_DOMAIN = "cast"
# Domains we care about for bridging / skip logic
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

    async def render_template(self, template: str) -> str:
        """Render a Jinja template via the HA REST API."""
        data = await self._request("POST", "/api/template", json={"template": template})
        if isinstance(data, str):
            return data
        return str(data)

    async def integration_entity_ids(self, domain: str) -> list[str]:
        """Entity IDs belonging to an integration (via integration_entities())."""
        # tojson keeps quoting predictable for json.loads
        template = (
            "{{ integration_entities('"
            + domain.replace("'", "")
            + "') | list | tojson }}"
        )
        raw = (await self.render_template(template)).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("Could not parse integration_entities(%s): %r", domain, raw[:200])
            return []
        if not isinstance(parsed, list):
            return []
        return [str(x) for x in parsed if isinstance(x, str)]

    async def platforms_for_media_players(self) -> dict[str, str]:
        """Map media_player entity_id -> integration platform/domain.

        State attributes do not expose config_entry_id/platform. Use
        integration_entities() for known domains (reliable with homeassistant_api).
        """
        mapping: dict[str, str] = {}
        for domain in sorted(TRACKED_DOMAINS):
            try:
                entity_ids = await self.integration_entity_ids(domain)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("integration_entities(%s) failed: %s", domain, exc)
                continue
            for entity_id in entity_ids:
                if entity_id.startswith("media_player."):
                    mapping[entity_id] = domain
            LOGGER.info(
                "Discovered %s media_player(s) for integration %s",
                sum(1 for e in entity_ids if e.startswith("media_player.")),
                domain,
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

    for state in states:
        entity_id = str(state.get("entity_id") or "")
        if not entity_id.startswith("media_player."):
            continue
        media_player_total += 1
        attrs = state.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        domain = platform_by_entity.get(entity_id, "")
        # Soft fallbacks (rarely present on state)
        if not domain:
            entry_hint = attrs.get("config_entry_id") or attrs.get("entry_id")
            if isinstance(attrs.get("platform"), str):
                domain = attrs["platform"]
            elif entry_hint:
                domain = "unknown"
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
        "diagnostics": {
            "media_player_total": media_player_total,
            "tracked_platforms": {
                domain: sum(1 for d in platform_by_entity.values() if d == domain)
                for domain in sorted(TRACKED_DOMAINS)
            },
            "platform_mapped": len(platform_by_entity),
        },
    }
