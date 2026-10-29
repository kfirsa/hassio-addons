"""Vibecast player-protocol v2 client — one Cast speaker → one HA media_player."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import platform
from typing import Any, Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed

LOGGER = logging.getLogger("acb.bridge")

LoadHandler = Callable[[str, str], Awaitable[bool]]
StopHandler = Callable[[str], Awaitable[None]]
ControlHandler = Callable[[str, str, dict[str, Any]], Awaitable[None]]
StatusProvider = Callable[[str], Awaitable[dict[str, Any]]]


def _finite_number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("numeric value must not be boolean")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid numeric value") from None
    if not math.isfinite(result):
        raise ValueError("numeric value must be finite")
    return result


def _valid_media_id(value: object) -> bool:
    return value is None or (type(value) is int and -(1 << 63) <= value < (1 << 63))


class VibecastPlayerBridge:
    """Register one named output with Vibecast and forward load/control to HA."""

    def __init__(
        self,
        *,
        bridge_url: str,
        player_id: str,
        cast_name: str,
        entity_id: str,
        on_load: LoadHandler,
        on_stop: StopHandler,
        on_control: ControlHandler | None = None,
        status_provider: StatusProvider | None = None,
    ) -> None:
        self.bridge_url = bridge_url
        self.player_id = player_id
        self.cast_name = cast_name
        self.entity_id = entity_id
        self.on_load = on_load
        self.on_stop = on_stop
        self.on_control = on_control
        self.status_provider = status_provider
        self.session_id: str | None = None
        self._websocket: Any = None
        self._media_session_id: int | None = None
        self._media_session_owner: str | None = None
        self._preparing_load = False
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.advertised = False
        # Local Cast player state — do NOT mirror HA idle while a session is active,
        # or the phone tears down the session immediately after connect.
        self._player_state = "IDLE"
        self._volume: float | None = None
        self._muted: bool | None = None

    def registration(self) -> dict[str, object]:
        return {
            "type": "register",
            "player": {
                "protocolVersion": 2,
                "playerId": self.player_id,
                "name": self.cast_name,
                "capabilities": {
                    "localAudioCache": False,
                    "platform": f"Linux {platform.machine()}",
                    "drm": [],
                    "videoCodecs": ["h264", "vp9", "av1"],
                    "audioCodecs": ["opus", "aac"],
                    "maxResolution": {"width": 1920, "height": 1080},
                    "hdrFormats": [],
                    "frameRates": [24, 25, 30, 50, 60],
                    "subtitleFormats": [],
                    "hdcpLevel": None,
                    "controlRequests": [
                        "play",
                        "pause",
                        "stop",
                        "seek",
                        "volume",
                        "next",
                        "previous",
                    ],
                },
            },
        }

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"acb-bridge-{self.entity_id}")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.advertised = False
        try:
            await self.on_stop(self.entity_id)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("on_stop during bridge stop: %s", exc)

    async def _run(self) -> None:
        LOGGER.info(
            "Advertising Cast speaker: %r → %s (player_id=%s)",
            self.cast_name,
            self.entity_id,
            self.player_id,
        )
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.bridge_url,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                ) as websocket:
                    self._websocket = websocket
                    await websocket.send(
                        json.dumps(self.registration(), separators=(",", ":"))
                    )
                    self.advertised = True
                    LOGGER.info(
                        "Connected to Vibecast player bridge for %r", self.cast_name
                    )
                    await self._serve(websocket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.advertised = False
                LOGGER.warning(
                    "Vibecast bridge for %r interrupted (%s); retrying",
                    self.cast_name,
                    type(exc).__name__,
                )
                try:
                    await self.on_stop(self.entity_id)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(2)
            finally:
                self._websocket = None
                self.session_id = None
                self.advertised = False

    async def _serve(self, websocket: Any) -> None:
        commands: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)

        async def receive() -> None:
            async for raw in websocket:
                if self._stop.is_set():
                    return
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("player command must be an object")
                # Volume must not wait behind a long load/listener wait.
                if message.get("type") == "volume":
                    asyncio.create_task(
                        self._handle_message(message),
                        name=f"acb-vol-{self.entity_id}",
                    )
                    continue
                try:
                    commands.put_nowait(message)
                except asyncio.QueueFull:
                    raise ValueError("player command queue saturated") from None

        async def execute() -> None:
            while not self._stop.is_set():
                message = await commands.get()
                await self._handle_message(message)

        async def periodic() -> None:
            while not self._stop.is_set():
                await asyncio.sleep(1)
                if self.session_id is not None:
                    await self._send_backend_state(self.session_id)

        tasks = [
            asyncio.create_task(receive()),
            asyncio.create_task(execute()),
            asyncio.create_task(periodic()),
        ]
        stopper = asyncio.create_task(self._stop.wait())
        tasks.append(stopper)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is stopper:
                    continue
                exc = task.exception()
                if exc:
                    raise exc
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        command = message.get("type")
        if command in {"settingsSnapshot", "settingsUpdateResult"}:
            return
        session_id = message.get("sessionId")
        if not isinstance(session_id, str):
            return
        media_id = None
        if command == "load" and isinstance(message.get("media"), dict):
            media_id = message["media"].get("mediaSessionId")
        elif session_id == self._media_session_owner:
            media_id = self._media_session_id
        if not _valid_media_id(media_id):
            media_id = None

        try:
            LOGGER.info(
                "player command=%s session=%s entity=%s",
                command,
                session_id,
                self.entity_id,
            )
            if command == "load":
                await self._load(session_id, message.get("media"))
                return
            if command == "volume":
                level = max(0.0, min(1.0, _finite_number(message.get("level", 1.0))))
                muted = bool(message.get("muted", False))
                self._volume = level
                self._muted = muted
                if self.on_control:
                    await self.on_control(
                        self.entity_id,
                        "volume",
                        {"level": level, "muted": muted},
                    )
                # Echo applied volume immediately so the phone slider does not snap back.
                await self._send_state(
                    session_id,
                    self._player_state if self.session_id == session_id else "IDLE",
                    volume=level,
                    muted=muted,
                )
                return
            if session_id != self.session_id:
                return
            if command == "play" and self.on_control:
                await self.on_control(self.entity_id, "play", {})
                self._player_state = "PLAYING"
            elif command == "pause" and self.on_control:
                await self.on_control(self.entity_id, "pause", {})
                self._player_state = "PAUSED"
            elif command == "seek" and self.on_control:
                await self.on_control(
                    self.entity_id,
                    "seek",
                    {"position": _finite_number(message.get("position", 0.0))},
                )
            elif command == "stop":
                await self.on_stop(self.entity_id)
                self.session_id = None
                self._player_state = "IDLE"
            await self._send_backend_state(session_id)
        except (OSError, TypeError, ValueError, RuntimeError, ConnectionClosed) as exc:
            LOGGER.error(
                "player command %s failed for %s: %s",
                command,
                self.entity_id,
                type(exc).__name__,
            )
            payload: dict[str, object] = {
                "type": "error",
                "sessionId": session_id,
                "code": "PLAYBACK_COMMAND_FAILED",
                "message": "Output command failed",
            }
            if media_id is not None:
                payload["mediaSessionId"] = media_id
            await self._send(payload)

    async def _load(self, session_id: str, media: Any) -> None:
        self._preparing_load = True
        try:
            if not isinstance(media, dict):
                raise ValueError("load command has no media object")
            mid = media.get("mediaSessionId")
            if not _valid_media_id(mid):
                raise ValueError("invalid media session identity")
            self._media_session_id = mid if isinstance(mid, int) else None
            self._media_session_owner = session_id
            streams = media.get("streams")
            if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
                raise ValueError("load command has no playable stream")
            url = streams[0].get("url")
            if not isinstance(url, str) or not url:
                raise ValueError("stream has no URL")
            start_time = max(0.0, _finite_number(media.get("startTime", 0.0)))
            self.session_id = session_id
            await self._send_state(session_id, "BUFFERING", current_time=start_time)
            LOGGER.info(
                "load session=%s entity=%s title=%r",
                session_id,
                self.entity_id,
                media.get("title"),
            )
            ok = await self.on_load(self.entity_id, url)
            if not ok:
                raise RuntimeError("HA load rejected")
            self._player_state = "PLAYING"
        except Exception:
            self.session_id = None
            self._player_state = "IDLE"
            try:
                await self.on_stop(self.entity_id)
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            self._preparing_load = False
        await self._send_state(session_id, "PLAYING", current_time=start_time)

    async def _send_backend_state(self, session_id: str) -> None:
        if self._preparing_load:
            return
        current_time = 0.0
        volume = None
        muted = None
        idle_reason = None
        ha_state = ""
        if self.status_provider:
            try:
                snap = await self.status_provider(self.entity_id)
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("status_provider failed: %s", exc)
                snap = {}
            ha_state = str(snap.get("state") or "")
            attrs = snap.get("attributes") or {}
            if isinstance(attrs, dict):
                pos = attrs.get("media_position")
                if isinstance(pos, (int, float)):
                    current_time = float(pos)
                vol = attrs.get("volume_level")
                if isinstance(vol, (int, float)):
                    volume = float(vol)
                if "is_volume_muted" in attrs:
                    muted = bool(attrs.get("is_volume_muted"))
            # Prefer last Cast-applied volume until HA state catches up.
            if self._volume is not None:
                volume = self._volume
            if self._muted is not None:
                muted = self._muted

        # While a Cast session is active, never report IDLE just because HA has
        # not flipped to "playing" yet — that aborts the phone session.
        if self.session_id == session_id:
            if ha_state == "playing":
                state = "PLAYING"
                self._player_state = "PLAYING"
            elif ha_state == "paused" or self._player_state == "PAUSED":
                state = "PAUSED"
                self._player_state = "PAUSED"
            elif ha_state in {"buffering"}:
                state = "BUFFERING"
            else:
                state = self._player_state if self._player_state != "IDLE" else "PLAYING"
        else:
            state = "IDLE"
            idle_reason = "FINISHED" if self._player_state != "IDLE" else None
            self._player_state = "IDLE"

        await self._send_state(
            session_id,
            state,
            current_time=current_time,
            idle_reason=idle_reason,
            volume=volume,
            muted=muted,
        )

    async def _send_state(
        self,
        session_id: str,
        state: str,
        current_time: float = 0.0,
        idle_reason: str | None = None,
        volume: float | None = None,
        muted: bool | None = None,
    ) -> None:
        message: dict[str, object] = {
            "type": "state",
            "sessionId": session_id,
            "playerState": state,
            "currentTime": max(0.0, current_time),
        }
        if self._media_session_owner == session_id and self._media_session_id is not None:
            message["mediaSessionId"] = self._media_session_id
        if idle_reason:
            message["idleReason"] = idle_reason
        if volume is not None:
            message["volume"] = volume
        if muted is not None:
            message["muted"] = muted
        await self._send(message)

    async def _send(self, message: dict[str, object]) -> None:
        if self._websocket is not None:
            await self._websocket.send(json.dumps(message, separators=(",", ":")))
