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
    listener_event: asyncio.Event = field(default_factory=asyncio.Event)
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
        return self.url_for_host(entity_id, self.host_hint)

    def url_for_host(self, entity_id: str, host: str) -> str:
        slug = entity_id.replace(".", "_")
        return f"http://{host}:{self.stream_port}/stream/{slug}"

    def slug(self, entity_id: str) -> str:
        return entity_id.replace(".", "_")

    def is_running(self, entity_id: str) -> bool:
        sess = self._sessions.get(entity_id)
        return bool(sess and sess.process and sess.process.returncode is None)

    def listener_count(self, entity_id: str) -> int:
        sess = self._sessions.get(entity_id)
        return len(sess.listeners) if sess else 0

    async def wait_listener(self, entity_id: str, timeout: float = 12.0) -> bool:
        """Wait until at least one HTTP client is subscribed to this stream."""
        sess = self._sessions.get(entity_id)
        if not sess:
            return False
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if sess.listeners:
                return True
            if sess.process is None or sess.process.returncode is not None:
                return False
            sess.listener_event.clear()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(sess.listener_event.wait(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
        return bool(sess.listeners)

    async def start(self, entity_id: str, source_url: str) -> str:
        async with self._lock:
            existing = self._sessions.get(entity_id)
            if existing and existing.process and existing.process.returncode is None:
                await self._stop_locked(entity_id)
            session = StreamSession(entity_id=entity_id, source_url=source_url)
            self._sessions[entity_id] = session
            # Protocol whitelist + UA help with signed HTTPS / HLS from Cast providers.
            # Do NOT use -re: backpressure from the pump (wait for listeners) paces output.
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

    async def _wait_for_listeners(self, session: StreamSession) -> bool:
        """Block until an HTTP listener joins, or ffmpeg dies."""
        while not session.listeners:
            proc = session.process
            if proc is None or proc.returncode is not None:
                return False
            session.listener_event.clear()
            try:
                await asyncio.wait_for(session.listener_event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
        return True

    async def _fanout(self, session: StreamSession, chunk: bytes) -> None:
        """Deliver chunk to every listener; await slow queues instead of dropping."""
        dead: list[asyncio.Queue[bytes | None]] = []
        for queue in list(session.listeners):
            try:
                await queue.put(chunk)
            except Exception:  # noqa: BLE001
                dead.append(queue)
        for queue in dead:
            session.listeners.discard(queue)

    async def _pump(self, session: StreamSession) -> None:
        assert session.process and session.process.stdout
        prebuffer = b""
        try:
            # Confirm ffmpeg can produce audio, then STOP reading until a speaker
            # connects. Previously we drained the whole track with zero listeners
            # and the relay ended before LinkPlay fetched the URL.
            first = await session.process.stdout.read(4096)
            if not first:
                LOGGER.error(
                    "ffmpeg relay for %s exited before producing audio (stderr=%r)",
                    session.entity_id,
                    (session.last_error or "")[-300:],
                )
                return
            prebuffer = first
            session.bytes_sent += len(first)
            session.ready.set()
            LOGGER.info(
                "ffmpeg relay ready for %s (prebuffer=%s bytes); waiting for HTTP listener",
                session.entity_id,
                len(first),
            )

            while True:
                if not await self._wait_for_listeners(session):
                    LOGGER.info(
                        "ffmpeg relay for %s ending — no listeners and process stopped",
                        session.entity_id,
                    )
                    break

                if prebuffer:
                    chunk = prebuffer
                    prebuffer = b""
                    LOGGER.info(
                        "HTTP listener connected for %s — starting audio fan-out",
                        session.entity_id,
                    )
                else:
                    chunk = await session.process.stdout.read(4096)
                    if not chunk:
                        break
                    session.bytes_sent += len(chunk)

                # Backpressure: wait for slow speakers instead of dropping them.
                # put_nowait+discard caused "plays a few seconds then stops".
                await self._fanout(session, chunk)
                if not session.listeners and not prebuffer:
                    LOGGER.info(
                        "All listeners gone for %s — pausing ffmpeg read (bytes=%s)",
                        session.entity_id,
                        session.bytes_sent,
                    )
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
                "Relay ended for %s (bytes=%s ready=%s listeners=%s)",
                session.entity_id,
                session.bytes_sent,
                session.ready.is_set(),
                len(session.listeners),
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
        session.listener_event.set()
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
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=512)
        session.listeners.add(queue)
        session.listener_event.set()
        LOGGER.info(
            "Stream subscribe for %s (listeners=%s)",
            session.entity_id,
            len(session.listeners),
        )
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
                    "source_url": sess.source_url[:120]
                    + ("…" if len(sess.source_url) > 120 else ""),
                    "listeners": len(sess.listeners),
                    "running": sess.process is not None and sess.process.returncode is None,
                    "ready": sess.ready.is_set(),
                    "bytes_sent": sess.bytes_sent,
                    "public_url": self.public_url(eid),
                    "last_error": (sess.last_error or "")[-200:],
                }
            )
        return out
