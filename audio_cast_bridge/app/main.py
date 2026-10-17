#!/usr/bin/env python3
"""Audio Cast Bridge manager: configure UI, HA bridge, stream relay, Cast hooks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from aiohttp import web

from cast_runtime import CastRouteManager
from config_store import (
    ADDON_VERSION,
    commit_pending_on_start,
    load_player_ids,
    save_pending,
    save_player_ids,
    status as config_status,
)
from ha_client import HomeAssistantClient, classify_media_players
from stream_relay import StreamRelayHub

LOG_LEVEL = os.environ.get("ACB_LOG_LEVEL", os.environ.get("LOG_LEVEL", "INFO")).upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("acb")

WEB_ROOT = Path(__file__).resolve().parent / "web"
INGRESS_PORT = int(os.environ.get("ACB_INGRESS_PORT", "8099"))
STREAM_PORT = int(os.environ.get("ACB_STREAM_PORT", "18080"))
HOST_HINT = os.environ.get("ACB_HOST_HINT", "homeassistant.local")


class AppState:
    def __init__(self) -> None:
        self.committed = commit_pending_on_start()
        self.ha: HomeAssistantClient | None = None
        self.relay = StreamRelayHub(
            host_hint=HOST_HINT,
            stream_port=int(self.committed.get("stream_port") or STREAM_PORT),
        )
        self.cast = CastRouteManager(
            on_load=self.handle_cast_load,
            on_stop=self.handle_cast_stop,
        )
        self.cast.set_player_ids(load_player_ids())
        self.entity_meta: dict[str, dict[str, Any]] = {}
        self.max_concurrent = int(self.committed.get("max_concurrent_streams") or 2)
        self._poll_task: asyncio.Task[None] | None = None

    async def handle_cast_load(self, entity_id: str, source_url: str) -> bool:
        if self.relay.active_count() >= self.max_concurrent and entity_id not in {
            s["entity_id"] for s in self.relay.snapshot() if s["running"]
        }:
            LOGGER.warning("Rejecting cast: max_concurrent_streams=%s", self.max_concurrent)
            return False
        if not self.ha:
            return False
        public = await self.relay.start(entity_id, source_url)
        await self.ha.play_media(entity_id, public)
        route = self.cast.runtime.routes.get(entity_id)
        if route:
            route.casting = True
        return True

    async def handle_cast_stop(self, entity_id: str) -> None:
        await self.relay.stop(entity_id)
        if self.ha:
            try:
                await self.ha.media_stop(entity_id)
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("media_stop failed for %s: %s", entity_id, exc)
        route = self.cast.runtime.routes.get(entity_id)
        if route:
            route.casting = False

    async def refresh_entities(self) -> dict[str, Any]:
        assert self.ha
        states = await self.ha.get_states()
        try:
            platforms = await self.ha.platforms_for_media_players()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("platform discovery failed: %s", exc)
            platforms = {}
        classified = classify_media_players(states, platforms)
        self.entity_meta = {
            item["entity_id"]: item
            for item in classified["eligible"] + classified["skipped"]
        }
        # Update availability for committed routes
        for entity_id, route in self.cast.runtime.routes.items():
            meta = self.entity_meta.get(entity_id)
            if not meta:
                self.cast.update_availability(entity_id, False)
                continue
            available = meta.get("state") not in {"unavailable", "unknown"}
            # Re-check skip: if device gained native Cast, mark unavailable for bridging
            if meta.get("skip_reason"):
                available = False
            self.cast.update_availability(entity_id, bool(available))
        return classified

    async def provision_committed(self) -> None:
        selected = list(self.committed.get("selected_entities") or [])
        await self.refresh_entities()
        self.cast.provision(selected, self.entity_meta)
        save_player_ids(self.cast.player_ids())
        await self.cast.start_frontend()

    async def poll_loop(self) -> None:
        while True:
            try:
                await self.refresh_entities()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Entity poll failed: %s", exc)
            await asyncio.sleep(int(os.environ.get("ACB_POLL_INTERVAL", "15")))


STATE = AppState()


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


async def api_health(_: web.Request) -> web.Response:
    return _json(
        {
            "ok": True,
            "addon_version": ADDON_VERSION,
            "cast": STATE.cast.snapshot(),
            "streams": STATE.relay.snapshot(),
            "config": config_status(),
        }
    )


async def api_devices(_: web.Request) -> web.Response:
    try:
        classified = await STATE.refresh_entities()
    except Exception as exc:  # noqa: BLE001
        return _json({"error": str(exc)}, status=502)
    cfg = config_status()
    pending = cfg.get("pending") or cfg.get("committed") or {}
    selected = set(pending.get("selected_entities") or [])
    for item in classified["eligible"]:
        item["selected"] = item["entity_id"] in selected
    return _json(
        {
            "eligible": classified["eligible"],
            "skipped": classified["skipped"],
            "diagnostics": classified.get("diagnostics") or {},
            "config": cfg,
            "sizing_formula": "128 + (N × 12) + (max_concurrent_streams × 48)",
        }
    )


async def api_config_get(_: web.Request) -> web.Response:
    return _json(config_status())


async def api_config_save(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json({"error": "invalid JSON"}, status=400)
    selected = body.get("selected_entities") or []
    if not isinstance(selected, list):
        return _json({"error": "selected_entities must be a list"}, status=400)
    try:
        pending = save_pending(
            selected_entities=[str(x) for x in selected],
            max_concurrent_streams=body.get("max_concurrent_streams"),
            max_bridges=body.get("max_bridges"),
            stream_port=body.get("stream_port"),
        )
    except ValueError as exc:
        return _json({"error": str(exc)}, status=400)
    return _json(
        {
            "ok": True,
            "needs_restart": True,
            "pending": pending,
            "message": "Configuration saved. Restart the add-on to apply bridges.",
        }
    )


async def api_play_test(request: web.Request) -> web.Response:
    """Dev helper: play a direct URL via relay to a committed entity."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _json({"error": "invalid JSON"}, status=400)
    entity_id = str(body.get("entity_id") or "")
    source_url = str(body.get("source_url") or "")
    if not entity_id or not source_url:
        return _json({"error": "entity_id and source_url required"}, status=400)
    if entity_id not in STATE.cast.runtime.routes:
        return _json({"error": "entity not in committed routes"}, status=400)
    ok = await STATE.handle_cast_load(entity_id, source_url)
    return _json({"ok": ok, "streams": STATE.relay.snapshot()})


async def stream_handler(request: web.Request) -> web.StreamResponse:
    slug = request.match_info["slug"]
    queue = STATE.relay.subscribe(slug)
    if queue is None:
        raise web.HTTPNotFound(text="stream not active")
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "audio/mpeg",
            "Cache-Control": "no-cache",
            "Connection": "close",
        },
    )
    await resp.prepare(request)
    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            await resp.write(chunk)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        sess_list = STATE.relay._sessions  # noqa: SLF001
        for sess in sess_list.values():
            sess.listeners.discard(queue)
    return resp


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_ROOT / "index.html")


async def on_startup(app: web.Application) -> None:
    STATE.ha = HomeAssistantClient()
    await STATE.ha.__aenter__()
    LOGGER.info(
        "Audio Cast Bridge v%s starting (stream_port=%s ingress=%s)",
        ADDON_VERSION,
        STATE.relay.stream_port,
        INGRESS_PORT,
    )
    try:
        await STATE.provision_committed()
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Initial provision failed: %s", exc)
    STATE._poll_task = asyncio.create_task(STATE.poll_loop(), name="acb-poll")


async def on_cleanup(app: web.Application) -> None:
    if STATE._poll_task:
        STATE._poll_task.cancel()
        try:
            await STATE._poll_task
        except asyncio.CancelledError:
            pass
    await STATE.relay.stop_all()
    await STATE.cast.stop_frontend()
    if STATE.ha:
        await STATE.ha.__aexit__(None, None, None)


def build_apps() -> tuple[web.Application, web.Application]:
    ui = web.Application()
    ui.router.add_get("/", index)
    ui.router.add_static("/static/", WEB_ROOT, show_index=False)
    ui.router.add_get("/api/health", api_health)
    ui.router.add_get("/api/devices", api_devices)
    ui.router.add_get("/api/config", api_config_get)
    ui.router.add_post("/api/config", api_config_save)
    ui.router.add_post("/api/play_test", api_play_test)
    ui.on_startup.append(on_startup)
    ui.on_cleanup.append(on_cleanup)

    streams = web.Application()
    streams.router.add_get("/stream/{slug}", stream_handler)
    return ui, streams


async def amain() -> None:
    ui, streams = build_apps()
    runner_ui = web.AppRunner(ui)
    runner_st = web.AppRunner(streams)
    await runner_ui.setup()
    await runner_st.setup()
    site_ui = web.TCPSite(runner_ui, "0.0.0.0", INGRESS_PORT)
    site_st = web.TCPSite(runner_st, "0.0.0.0", STATE.relay.stream_port)
    await site_ui.start()
    await site_st.start()
    LOGGER.info("Ingress UI on :%s ; streams on :%s", INGRESS_PORT, STATE.relay.stream_port)

    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass
    await stop.wait()
    await runner_ui.cleanup()
    await runner_st.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
