"""Cast V2 frontend (Vibecast) supervision and per-speaker player bridges."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from auth_bundle import certs_path, certs_present, ensure_auth_bundle
from vibecast_bridge import VibecastPlayerBridge

LOGGER = logging.getLogger("acb.cast")

CAST_NAME_SUFFIX = " (Audio Cast Bridge)"
DEFAULT_BRIDGE_URL = "ws://127.0.0.1:8010/player"


@dataclass
class CastRoute:
    entity_id: str
    friendly_name: str
    cast_name: str
    player_id: str
    available: bool = True
    casting: bool = False
    advertised: bool = False


@dataclass
class CastRuntime:
    frontend_bin: Path
    routes: dict[str, CastRoute] = field(default_factory=dict)
    process: asyncio.subprocess.Process | None = None
    frontend_available: bool = False
    auth_bundle_present: bool = False
    bridge_ready: bool = False

    def __post_init__(self) -> None:
        self.frontend_available = self.frontend_bin.is_file() and os.access(
            self.frontend_bin, os.X_OK
        )
        self.auth_bundle_present = certs_present()


def stable_player_id(entity_id: str, existing: dict[str, str]) -> str:
    if entity_id in existing:
        return existing[entity_id]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"audio-cast-bridge:{entity_id}"))


class CastRouteManager:
    """Holds routes; starts Vibecast; one player-bridge task per selected speaker."""

    def __init__(
        self,
        frontend_bin: str | None = None,
        on_load: Callable[[str, str], Awaitable[bool]] | None = None,
        on_stop: Callable[[str], Awaitable[None]] | None = None,
        on_control: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None,
        status_provider: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        bin_path = Path(
            frontend_bin
            or os.environ.get("CAST_FRONTEND_BIN", "/usr/local/bin/vibecast")
        )
        self.runtime = CastRuntime(frontend_bin=bin_path)
        self.on_load = on_load
        self.on_stop = on_stop
        self.on_control = on_control
        self.status_provider = status_provider
        self._player_ids: dict[str, str] = {}
        self._bridges: dict[str, VibecastPlayerBridge] = {}
        self._log_task: asyncio.Task[None] | None = None
        self.bridge_url = os.environ.get("ACB_PLAYER_BRIDGE_URL", DEFAULT_BRIDGE_URL)
        self.data_dir = Path(os.environ.get("ACB_DATA_DIR", "/data"))
        self.frontend_dir = self.data_dir / "frontend"

    def set_player_ids(self, mapping: dict[str, str]) -> None:
        self._player_ids = dict(mapping)

    def player_ids(self) -> dict[str, str]:
        return dict(self._player_ids)

    def bind_stream_generation(self, entity_id: str, generation: int) -> None:
        bridge = self._bridges.get(entity_id)
        if bridge:
            bridge.bind_stream_generation(generation)

    async def notify_stream_finished(self, entity_id: str, generation: int) -> None:
        bridge = self._bridges.get(entity_id)
        if bridge:
            await bridge.notify_stream_finished(generation)

    def provision(
        self,
        selected_entities: list[str],
        entity_meta: dict[str, dict[str, Any]],
    ) -> list[CastRoute]:
        """Replace route table from committed selection (call on start)."""
        if not selected_entities:
            LOGGER.warning(
                "No speakers selected — no Cast targets will be created. "
                "Pick devices in the Ingress UI (selection restarts the add-on)."
            )
            self.runtime.routes = {}
            return []

        new_routes: dict[str, CastRoute] = {}
        for entity_id in selected_entities:
            meta = entity_meta.get(entity_id) or {}
            friendly = str(meta.get("friendly_name") or entity_id)
            cast_name = f"{friendly}{CAST_NAME_SUFFIX}"
            player_id = stable_player_id(entity_id, self._player_ids)
            self._player_ids[entity_id] = player_id
            state = str(meta.get("state") or "unknown")
            available = state not in {"unavailable", "unknown"}
            new_routes[entity_id] = CastRoute(
                entity_id=entity_id,
                friendly_name=friendly,
                cast_name=cast_name,
                player_id=player_id,
                available=available,
            )
            LOGGER.info(
                "Cast target created: %r -> %s (player_id=%s available=%s state=%s)",
                cast_name,
                entity_id,
                player_id,
                available,
                state,
            )
        self.runtime.routes = new_routes
        LOGGER.info(
            "Provisioned %s Cast target(s) (frontend_bin=%s binary_present=%s)",
            len(new_routes),
            self.runtime.frontend_bin,
            self.runtime.frontend_available,
        )
        return list(new_routes.values())

    def update_availability(self, entity_id: str, available: bool) -> None:
        route = self.runtime.routes.get(entity_id)
        if not route:
            return
        if route.available == available:
            return
        route.available = available
        LOGGER.info(
            "Route %s availability -> %s (cast_name=%s)",
            entity_id,
            available,
            route.cast_name,
        )
        bridge = self._bridges.get(entity_id)
        if not available and bridge:
            asyncio.create_task(self._withdraw_bridge(entity_id), name=f"acb-withdraw-{entity_id}")
        elif available and entity_id not in self._bridges and self.runtime.bridge_ready:
            asyncio.create_task(self._spawn_bridge(route), name=f"acb-spawn-{entity_id}")

    async def _withdraw_bridge(self, entity_id: str) -> None:
        bridge = self._bridges.pop(entity_id, None)
        if bridge:
            await bridge.stop()
            route = self.runtime.routes.get(entity_id)
            if route:
                route.advertised = False
            LOGGER.info("Withdrew Cast advertisement for %s", entity_id)

    def snapshot(self) -> dict[str, Any]:
        for entity_id, bridge in self._bridges.items():
            route = self.runtime.routes.get(entity_id)
            if route:
                route.advertised = bridge.advertised
        return {
            "frontend_bin": str(self.runtime.frontend_bin),
            "frontend_available": self.runtime.frontend_available,
            "frontend_running": self.runtime.process is not None
            and self.runtime.process.returncode is None,
            "auth_bundle_present": certs_present(),
            "bridge_ready": self.runtime.bridge_ready,
            "bridge_url": self.bridge_url,
            "routes": [
                {
                    "entity_id": r.entity_id,
                    "friendly_name": r.friendly_name,
                    "cast_name": r.cast_name,
                    "player_id": r.player_id,
                    "available": r.available,
                    "casting": r.casting,
                    "advertised": r.advertised
                    or (
                        self._bridges.get(r.entity_id).advertised
                        if r.entity_id in self._bridges
                        else False
                    ),
                }
                for r in self.runtime.routes.values()
            ],
        }

    def _prepare_frontend_dir(self) -> Path:
        self.frontend_dir.mkdir(parents=True, exist_ok=True)
        template = Path(
            os.environ.get(
                "ACB_VIBECAST_CONFIG_TEMPLATE",
                "/usr/share/audio_cast_bridge/vibecast-audio.toml",
            )
        )
        dest = self.frontend_dir / "config.toml"
        if not dest.is_file() and template.is_file():
            shutil.copyfile(template, dest)
        elif not dest.is_file():
            dest.write_text(
                '[device]\nmodel = "Audio Speaker"\nlocale = "en-US"\ncountry_code = "US"\n',
                encoding="utf-8",
            )
        return self.frontend_dir

    async def start_frontend(self) -> None:
        if not self.runtime.frontend_available:
            LOGGER.warning(
                "Cast V2 frontend binary not found at %s — LAN Cast advertisement disabled",
                self.runtime.frontend_bin,
            )
            return

        try:
            ensure_auth_bundle()
            self.runtime.auth_bundle_present = True
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Cast auth bundle unavailable (%s) — LAN Cast advertisement disabled",
                type(exc).__name__,
            )
            self.runtime.auth_bundle_present = False
            return

        data_dir = self._prepare_frontend_dir()
        if self.runtime.process and self.runtime.process.returncode is None:
            await self._ensure_bridges()
            return

        certs = certs_path()
        cmd = [
            str(self.runtime.frontend_bin),
            "--certs",
            str(certs),
            "--data-dir",
            str(data_dir),
            "--model",
            "Audio Speaker",
            "--bind-host",
            "0.0.0.0",
        ]
        LOGGER.info("Starting Vibecast Cast frontend: %s", " ".join(cmd))
        self.runtime.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._log_task = asyncio.create_task(self._log_frontend(), name="acb-cast-frontend-log")

        if not await self._wait_for_bridge(timeout=45.0):
            LOGGER.error(
                "Vibecast player bridge at %s did not become ready — speakers will not advertise",
                self.bridge_url,
            )
            return

        self.runtime.bridge_ready = True
        await self._ensure_bridges()

    async def _wait_for_bridge(self, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.runtime.process and self.runtime.process.returncode is not None:
                LOGGER.error("Vibecast exited early with code %s", self.runtime.process.returncode)
                return False
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", 8010),
                    timeout=1.0,
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
                del reader
                LOGGER.info("Vibecast player bridge port 8010 is accepting connections")
                return True
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(0.5)
        return False

    async def _ensure_bridges(self) -> None:
        if not self.on_load or not self.on_stop:
            LOGGER.error("Cast load/stop handlers not configured")
            return
        wanted = {
            entity_id: route
            for entity_id, route in self.runtime.routes.items()
            if route.available
        }
        for entity_id in list(self._bridges):
            if entity_id not in wanted:
                await self._withdraw_bridge(entity_id)
        for entity_id, route in wanted.items():
            if entity_id not in self._bridges:
                await self._spawn_bridge(route)

    async def _spawn_bridge(self, route: CastRoute) -> None:
        if route.entity_id in self._bridges:
            return
        assert self.on_load and self.on_stop
        bridge = VibecastPlayerBridge(
            bridge_url=self.bridge_url,
            player_id=route.player_id,
            cast_name=route.cast_name,
            entity_id=route.entity_id,
            on_load=self.on_load,
            on_stop=self.on_stop,
            on_control=self.on_control,
            status_provider=self.status_provider,
        )
        self._bridges[route.entity_id] = bridge
        bridge.start()
        route.advertised = True

    async def _log_frontend(self) -> None:
        proc = self.runtime.process
        if not proc or not proc.stdout:
            return
        async for line in proc.stdout:
            LOGGER.info("[vibecast] %s", line.decode(errors="replace").rstrip())
        code = await proc.wait()
        self.runtime.bridge_ready = False
        LOGGER.warning("Vibecast exited with code %s", code)

    async def stop_frontend(self) -> None:
        for entity_id in list(self._bridges):
            await self._withdraw_bridge(entity_id)
        proc = self.runtime.process
        if not proc or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=8)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        self.runtime.bridge_ready = False
        if self._log_task:
            self._log_task.cancel()
            try:
                await self._log_task
            except asyncio.CancelledError:
                pass
            self._log_task = None
