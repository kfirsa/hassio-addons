"""ffmpeg-based HTTP re-stream so LinkPlay/DLNA get a stable LAN URL."""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger("acb.stream")


@dataclass
class StreamSession:
    entity_id: str
    source_url: str
    process: asyncio.subprocess.Process | None = None
    listeners: set[asyncio.Queue[bytes | None]] = field(default_factory=set)
    started: bool = False


class StreamRelayHub:
    """One ffmpeg process per entity; fan-out MP3 to HTTP listeners."""

    def __init__(self, host_hint: str = "homeassistant.local", stream_port: int = 18080) -> None:
        self.host_hint = host_hint
        self.stream_port = stream_port
        self._sessions: dict[str, StreamSession] = {}
        self._lock = asyncio.Lock()

    def public_url(self, entity_id: str) -> str:
        slug = entity_id.replace(".", "_")
        return f"http://{self.host_hint}:{self.stream_port}/stream/{slug}"

    def slug(self, entity_id: str) -> str:
        return entity_id.replace(".", "_")

    async def start(self, entity_id: str, source_url: str) -> str:
        async with self._lock:
            existing = self._sessions.get(entity_id)
            if existing and existing.process and existing.process.returncode is None:
                await self._stop_locked(entity_id)
            session = StreamSession(entity_id=entity_id, source_url=source_url)
            self._sessions[entity_id] = session
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-re",
                "-i",
                source_url,
                "-vn",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-f",
                "mp3",
                "pipe:1",
            ]
            LOGGER.info("Starting ffmpeg relay for %s", entity_id)
            session.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            session.started = True
            asyncio.create_task(self._pump(session), name=f"acb-pump-{entity_id}")
            return self.public_url(entity_id)

    async def _pump(self, session: StreamSession) -> None:
        assert session.process and session.process.stdout
        try:
            while True:
                chunk = await session.process.stdout.read(4096)
                if not chunk:
                    break
                dead: list[asyncio.Queue[bytes | None]] = []
                for queue in list(session.listeners):
                    try:
                        queue.put_nowait(chunk)
                    except asyncio.QueueFull:
                        dead.append(queue)
                for queue in dead:
                    session.listeners.discard(queue)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Relay pump error for %s: %s", session.entity_id, exc)
        finally:
            for queue in list(session.listeners):
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            session.listeners.clear()
            LOGGER.info("Relay ended for %s", session.entity_id)

    async def stop(self, entity_id: str) -> None:
        async with self._lock:
            await self._stop_locked(entity_id)

    async def _stop_locked(self, entity_id: str) -> None:
        session = self._sessions.pop(entity_id, None)
        if not session or not session.process:
            return
        proc = session.process
        if proc.returncode is None:
            try:
                proc.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass
        for queue in list(session.listeners):
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        session.listeners.clear()

    async def stop_all(self) -> None:
        async with self._lock:
            for entity_id in list(self._sessions):
                await self._stop_locked(entity_id)

    def subscribe(self, slug_or_id: str) -> asyncio.Queue[bytes | None] | None:
        session = self._sessions.get(slug_or_id)
        if not session:
            for eid, sess in self._sessions.items():
                if self.slug(eid) == slug_or_id:
                    session = sess
                    break
        if not session:
            return None
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
        session.listeners.add(queue)
        return queue

    def active_count(self) -> int:
        return sum(
            1
            for s in self._sessions.values()
            if s.process is not None and s.process.returncode is None
        )

    def snapshot(self) -> list[dict[str, Any]]:
        out = []
        for eid, sess in self._sessions.items():
            out.append(
                {
                    "entity_id": eid,
                    "source_url": sess.source_url,
                    "listeners": len(sess.listeners),
                    "running": sess.process is not None and sess.process.returncode is None,
                    "public_url": self.public_url(eid),
                }
            )
        return out
