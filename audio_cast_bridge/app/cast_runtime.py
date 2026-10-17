"""Cast V2 frontend supervision and route provisioning hooks.

The real Cast advertisement requires a Vibecast/Lab-compatible binary at
CAST_FRONTEND_BIN. Without it the manager still provisions routes in software
state and serves configure/HA/stream paths; LAN Cast discovery stays inactive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

LOGGER = logging.getLogger("acb.cast")

CAST_NAME_SUFFIX = " (Audio Cast Bridge)"


@dataclass
class CastRoute:
    entity_id: str
    friendly_name: str
    cast_name: str
    player_id: str
    available: bool = True
    casting: bool = False


@dataclass
class CastRuntime:
    frontend_bin: Path
    routes: dict[str, CastRoute] = field(default_factory=dict)
    process: asyncio.subprocess.Process | None = None
    frontend_available: bool = False

    def __post_init__(self) -> None:
        self.frontend_available = self.frontend_bin.is_file() and os.access(
            self.frontend_bin, os.X_OK
        )


def stable_player_id(entity_id: str, existing: dict[str, str]) -> str:
    if entity_id in existing:
        return existing[entity_id]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"audio-cast-bridge:{entity_id}"))


class CastRouteManager:
    """Holds committed routes; starts optional Cast frontend process."""

    def __init__(
        self,
        frontend_bin: str | None = None,
        on_load: Callable[[str, str], Awaitable[bool]] | None = None,
        on_stop: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        bin_path = Path(
            frontend_bin or os.environ.get("CAST_FRONTEND_BIN", "/usr/local/bin/cast-frontend")
        )
        self.runtime = CastRuntime(frontend_bin=bin_path)
        self.on_load = on_load
        self.on_stop = on_stop
        self._player_ids: dict[str, str] = {}

    def set_player_ids(self, mapping: dict[str, str]) -> None:
        self._player_ids = dict(mapping)

    def player_ids(self) -> dict[str, str]:
        return dict(self._player_ids)

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

    def snapshot(self) -> dict[str, Any]:
        return {
            "frontend_bin": str(self.runtime.frontend_bin),
            "frontend_available": self.runtime.frontend_available,
            "frontend_running": self.runtime.process is not None
            and self.runtime.process.returncode is None,
            "routes": [
                {
                    "entity_id": r.entity_id,
                    "friendly_name": r.friendly_name,
                    "cast_name": r.cast_name,
                    "player_id": r.player_id,
                    "available": r.available,
                    "casting": r.casting,
                }
                for r in self.runtime.routes.values()
            ],
        }

    async def start_frontend(self) -> None:
        if not self.runtime.frontend_available:
            names = [r.cast_name for r in self.runtime.routes.values()]
            LOGGER.warning(
                "Cast V2 frontend binary not found at %s — "
                "%s Cast target(s) are registered in the manager but NOT advertised on the LAN "
                "(YouTube Music will not see them until the frontend binary is installed). "
                "Targets: %s",
                self.runtime.frontend_bin,
                len(names),
                names or "(none)",
            )
            return
        if self.runtime.process and self.runtime.process.returncode is None:
            return
        # Frontend-specific flags depend on the pinned Vibecast/Lab build.
        # Keep argv minimal; extend via CAST_FRONTEND_ARGS.
        extra = os.environ.get("CAST_FRONTEND_ARGS", "").strip().split()
        cmd = [str(self.runtime.frontend_bin), *extra]
        LOGGER.info("Starting Cast V2 frontend: %s", " ".join(cmd))
        self.runtime.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        asyncio.create_task(self._log_frontend(), name="acb-cast-frontend-log")

    async def _log_frontend(self) -> None:
        proc = self.runtime.process
        if not proc or not proc.stdout:
            return
        async for line in proc.stdout:
            LOGGER.info("[cast-frontend] %s", line.decode(errors="replace").rstrip())
        code = await proc.wait()
        LOGGER.warning("Cast frontend exited with code %s", code)

    async def stop_frontend(self) -> None:
        proc = self.runtime.process
        if not proc or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=8)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
