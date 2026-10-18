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
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    bytes_sent: int = 0
    last_error: str = ""


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

    def is_running(self, entity_id: str) -> bool:
        sess = self._sessions.get(entity_id)
        return bool(sess and sess.process and sess.process.returncode is None)

    async def start(self, entity_id: str, source_url: str) -> str:
        async with self._lock:
            existing = self._sessions.get(entity_id)
            if existing and existing.process and existing.process.returncode is None:
                await self._stop_locked(entity_id)
            session = StreamSession(entity_id=entity_id, source_url=source_url)
            self._sessions[entity_id] = session
            # No -re: network sources should be pulled and remuxed as data arrives.
            # Protocol whitelist + UA help with signed HTTPS / HLS from Cast providers.
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-protocol_whitelist",
                "file,http,https,tcp,tls,crypto,httpproxy",
                "-user_agent",
                "AudioCastBridge/1.1",
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
            asyncio.create_task(self._drain_stderr(session), name=f"acb-ffmpeg-err-{entity_id}")
            return self.public_url(entity_id)

    async def wait_ready(self, entity_id: str, timeout: float = 12.0) -> bool:
        sess = self._sessions.get(entity_id)
        if not sess:
            return False
        try:
            await asyncio.wait_for(sess.ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            LOGGER.warning(
                "ffmpeg relay for %s produced no audio within %.1fs (stderr=%r)",
                entity_id,
                timeout,
                (sess.last_error or "")[-300:],
            )
            return False

    async def _drain_stderr(self, session: StreamSession) -> None:
        proc = session.process
        if not proc or not proc.stderr:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if not text:
                    continue
                session.last_error = (session.last_error + "\n" + text)[-2000:]
                LOGGER.warning("[ffmpeg %s] %s", session.entity_id, text)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("stderr drain ended for %s: %s", session.entity_id, exc)

    async def _pump(self, session: StreamSession) -> None:
        assert session.process and session.process.stdout
        try:
            while True:
                chunk = await session.process.stdout.read(4096)
                if not chunk:
                    break
                session.bytes_sent += len(chunk)
                if not session.ready.is_set():
                    session.ready.set()
                    LOGGER.info(
                        "ffmpeg relay ready for %s (first %s bytes)",
                        session.entity_id,
                        len(chunk),
                    )
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
            code = session.process.returncode if session.process else None
            if code not in (None, 0) and not session.ready.is_set():
                LOGGER.error(
                    "ffmpeg relay failed for %s before any audio (exit=%s)",
                    session.entity_id,
                    code,
                )
            for queue in list(session.listeners):
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            session.listeners.clear()
            LOGGER.info(
                "Relay ended for %s (bytes=%s ready=%s)",
                session.entity_id,
                session.bytes_sent,
                session.ready.is_set(),
            )

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
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
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
                    "source_url": sess.source_url[:120] + ("…" if len(sess.source_url) > 120 else ""),
                    "listeners": len(sess.listeners),
                    "running": sess.process is not None and sess.process.returncode is None,
                    "ready": sess.ready.is_set(),
                    "bytes_sent": sess.bytes_sent,
                    "public_url": self.public_url(eid),
                    "last_error": (sess.last_error or "")[-200:],
                }
            )
        return out
