"""Pending / committed bridge configuration on /data."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from sizing import recommended_host_free_mb, suggested_ram_mb

LOGGER = logging.getLogger("acb.config")

DATA_DIR = Path(os.environ.get("ACB_DATA_DIR", "/data"))
PENDING_PATH = DATA_DIR / "bridge_config.pending.json"
COMMITTED_PATH = DATA_DIR / "bridge_config.committed.json"
PLAYER_IDS_PATH = DATA_DIR / "cast_player_ids.json"

ADDON_VERSION = os.environ.get("ADDON_VERSION", "1.0.0")


def _default_config() -> dict[str, Any]:
    return {
        "addon_version": ADDON_VERSION,
        "selected_entities": [],
        "max_concurrent_streams": int(os.environ.get("ACB_MAX_CONCURRENT_STREAMS", "2")),
        "max_bridges": int(os.environ.get("ACB_MAX_BRIDGES", "5")),
        "stream_port": int(os.environ.get("ACB_STREAM_PORT", "18080")),
        "suggested_ram_mb": suggested_ram_mb(0, 2),
        "recommended_host_free_mb": recommended_host_free_mb(suggested_ram_mb(0, 2)),
        "needs_restart": False,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed to read %s: %s", path, exc)
    return None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(DATA_DIR), prefix=".cfg-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def enrich(config: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(config)
    selected = list(out.get("selected_entities") or [])
    streams = int(out.get("max_concurrent_streams") or 2)
    suggested = suggested_ram_mb(len(selected), streams)
    out["selected_entities"] = selected
    out["max_concurrent_streams"] = streams
    out["suggested_ram_mb"] = suggested
    out["recommended_host_free_mb"] = recommended_host_free_mb(suggested)
    out["addon_version"] = ADDON_VERSION
    return out


def load_pending() -> dict[str, Any] | None:
    data = _read_json(PENDING_PATH)
    return enrich(data) if data else None


def load_committed() -> dict[str, Any]:
    data = _read_json(COMMITTED_PATH)
    if not data:
        return enrich(_default_config())
    return enrich(data)


def status() -> dict[str, Any]:
    pending = load_pending()
    committed = load_committed()
    needs_restart = bool(pending and pending.get("needs_restart"))
    if pending and not needs_restart:
        # Pending without flag still means unapplied if different from committed
        needs_restart = pending.get("selected_entities") != committed.get(
            "selected_entities"
        ) or pending.get("max_concurrent_streams") != committed.get(
            "max_concurrent_streams"
        )
    return {
        "addon_version": ADDON_VERSION,
        "needs_restart": needs_restart,
        "pending": pending,
        "committed": committed,
        "paths": {
            "pending": str(PENDING_PATH),
            "committed": str(COMMITTED_PATH),
        },
    }


def save_pending(
    selected_entities: list[str],
    max_concurrent_streams: int | None = None,
    max_bridges: int | None = None,
    stream_port: int | None = None,
) -> dict[str, Any]:
    current = load_pending() or load_committed()
    max_bridges_val = int(
        max_bridges
        if max_bridges is not None
        else current.get("max_bridges")
        or os.environ.get("ACB_MAX_BRIDGES", "5")
    )
    streams = int(
        max_concurrent_streams
        if max_concurrent_streams is not None
        else current.get("max_concurrent_streams")
        or 2
    )
    unique: list[str] = []
    seen: set[str] = set()
    for entity_id in selected_entities:
        eid = str(entity_id).strip()
        if not eid or eid in seen:
            continue
        seen.add(eid)
        unique.append(eid)
    if len(unique) > max_bridges_val:
        raise ValueError(
            f"Selected {len(unique)} devices exceeds max_bridges={max_bridges_val}"
        )

    payload = enrich(
        {
            "addon_version": ADDON_VERSION,
            "selected_entities": unique,
            "max_concurrent_streams": streams,
            "max_bridges": max_bridges_val,
            "stream_port": int(
                stream_port
                if stream_port is not None
                else current.get("stream_port")
                or os.environ.get("ACB_STREAM_PORT", "18080")
            ),
            "needs_restart": True,
        }
    )
    _atomic_write(PENDING_PATH, payload)
    LOGGER.info(
        "Saved pending bridge config: %s entities, suggested_ram_mb=%s (restart required)",
        len(unique),
        payload["suggested_ram_mb"],
    )
    return payload


def commit_pending_on_start() -> dict[str, Any]:
    """Apply pending config at process start; return committed config."""
    pending = load_pending()
    if pending and pending.get("needs_restart"):
        committed = enrich({**pending, "needs_restart": False})
        _atomic_write(COMMITTED_PATH, committed)
        # Clear restart flag on pending so UI reflects applied state
        _atomic_write(PENDING_PATH, committed)
        LOGGER.info(
            "Committed bridge config on start: %s entities, suggested_ram_mb=%s",
            len(committed.get("selected_entities") or []),
            committed.get("suggested_ram_mb"),
        )
        return committed
    return load_committed()


def load_player_ids() -> dict[str, str]:
    data = _read_json(PLAYER_IDS_PATH) or {}
    return {str(k): str(v) for k, v in data.items() if isinstance(k, str)}


def save_player_ids(mapping: dict[str, str]) -> None:
    _atomic_write(PLAYER_IDS_PATH, mapping)
