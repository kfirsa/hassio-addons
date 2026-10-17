"""Bridge configuration on /data (applied on add-on start)."""

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
CONFIG_PATH = DATA_DIR / "bridge_config.json"
# Legacy paths from configure-then-restart flow
_LEGACY_PENDING = DATA_DIR / "bridge_config.pending.json"
_LEGACY_COMMITTED = DATA_DIR / "bridge_config.committed.json"
PLAYER_IDS_PATH = DATA_DIR / "cast_player_ids.json"

ADDON_VERSION = os.environ.get("ADDON_VERSION", "1.0.0")
DEFAULT_MAX_BRIDGES = 2
DEFAULT_MAX_STREAMS = 2


def _default_config() -> dict[str, Any]:
    streams = int(os.environ.get("ACB_MAX_CONCURRENT_STREAMS", str(DEFAULT_MAX_STREAMS)))
    return {
        "addon_version": ADDON_VERSION,
        "selected_entities": [],
        "max_concurrent_streams": streams,
        "max_bridges": int(os.environ.get("ACB_MAX_BRIDGES", str(DEFAULT_MAX_BRIDGES))),
        "stream_port": int(os.environ.get("ACB_STREAM_PORT", "18080")),
        "suggested_ram_mb": suggested_ram_mb(0, streams),
        "recommended_host_free_mb": recommended_host_free_mb(
            suggested_ram_mb(0, streams)
        ),
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
    streams = int(out.get("max_concurrent_streams") or DEFAULT_MAX_STREAMS)
    suggested = suggested_ram_mb(len(selected), streams)
    out["selected_entities"] = selected
    out["max_concurrent_streams"] = streams
    out["max_bridges"] = int(out.get("max_bridges") or DEFAULT_MAX_BRIDGES)
    out["suggested_ram_mb"] = suggested
    out["recommended_host_free_mb"] = recommended_host_free_mb(suggested)
    out["addon_version"] = ADDON_VERSION
    out.pop("needs_restart", None)
    return out


def load_config() -> dict[str, Any]:
    """Load active config; migrate legacy pending/committed files once."""
    data = _read_json(CONFIG_PATH)
    if data:
        return enrich(data)
    pending = _read_json(_LEGACY_PENDING)
    committed = _read_json(_LEGACY_COMMITTED)
    legacy = pending or committed
    if legacy:
        migrated = enrich(legacy)
        _atomic_write(CONFIG_PATH, migrated)
        LOGGER.info("Migrated legacy bridge config to %s", CONFIG_PATH)
        return migrated
    return enrich(_default_config())


def status() -> dict[str, Any]:
    cfg = load_config()
    return {
        "addon_version": ADDON_VERSION,
        "config": cfg,
        "path": str(CONFIG_PATH),
    }


def save_config(
    selected_entities: list[str],
    max_concurrent_streams: int | None = None,
    max_bridges: int | None = None,
    stream_port: int | None = None,
) -> dict[str, Any]:
    current = load_config()
    max_bridges_val = int(
        max_bridges
        if max_bridges is not None
        else current.get("max_bridges")
        or os.environ.get("ACB_MAX_BRIDGES", str(DEFAULT_MAX_BRIDGES))
    )
    streams = int(
        max_concurrent_streams
        if max_concurrent_streams is not None
        else current.get("max_concurrent_streams")
        or DEFAULT_MAX_STREAMS
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
        }
    )
    _atomic_write(CONFIG_PATH, payload)
    LOGGER.info(
        "Saved bridge config: %s entities, streams=%s, suggested_ram_mb=%s",
        len(unique),
        streams,
        payload["suggested_ram_mb"],
    )
    return payload


def load_player_ids() -> dict[str, str]:
    data = _read_json(PLAYER_IDS_PATH) or {}
    return {str(k): str(v) for k, v in data.items() if isinstance(k, str)}


def save_player_ids(mapping: dict[str, str]) -> None:
    _atomic_write(PLAYER_IDS_PATH, mapping)
