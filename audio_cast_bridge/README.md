# Audio Cast Bridge

Experimental Home Assistant add-on that bridges **YouTube Music / Cast audio** to
**LinkPlay** and **DLNA** speakers that do not have native Google Cast.

See [`CHANGELOG.md`](CHANGELOG.md) for release notes (shown by Home Assistant on update).

## Features

- **Configure → restart → apply**: pick eligible HA media players, review RAM estimate, save, restart add-on
- Skips devices that already have **native Google Cast**
- Cast target name: `{friendly_name} (Audio Cast Bridge)`
- HA `media_player.play_media` + **ffmpeg** HTTP re-stream for stable LAN URLs
- Ingress UI for device selection, sizing, and health
- Cast V2 frontend hooks (optional binary at `/usr/local/bin/cast-frontend`)

## Installation

1. Add this repository in **Settings → Add-ons → Add-on Store → Repositories**:
   `https://github.com/kfirsa/hassio-addons`
2. Install **Audio Cast Bridge**
3. Start the add-on (requires **host network**)
4. Open **Web UI** / Ingress
5. Select eligible devices, set max concurrent streams, review RAM estimate → **Save**
6. **Restart the add-on** to provision bridges

## Configuration (Supervisor options)

| Option | Description | Default |
|--------|-------------|---------|
| `max_bridges` | Hard ceiling on selected devices | `5` |
| `max_concurrent_streams` | Max simultaneous ffmpeg relays / casts | `2` |
| `stream_port` | LAN HTTP port for speaker streams | `18080` |
| `dial_base_port` | Reserved for Cast frontend port allocation | `3100` |
| `log_level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |

Device selection is stored under add-on `/data` (not in Supervisor options) so the
list can stay dynamic.

### RAM estimate (configure time)

```text
suggested_ram_mb = 128 + (N_selected × 12) + (max_concurrent_streams × 48)
```

The Ingress UI shows this and a recommended host free-RAM band.

## Cast V2 frontend

Full LAN Cast advertisement needs a **Vibecast / Cast Audio Receiver Lab–compatible**
binary installed as `CAST_FRONTEND_BIN` (default `/usr/local/bin/cast-frontend`).

Without that binary the add-on still provides:

- Eligible device discovery and configure-then-restart flow
- Stream relay and HA `play_media` control
- Health APIs

Cast authentication used by experimental receivers can be **revoked or broken** by
Google at any time. Treat this add-on as experimental.

## Architecture

```text
YouTube Music / Cast sender
        │  Cast V2 (when frontend binary present)
        ▼
Audio Cast Bridge manager
        ├── ffmpeg HTTP re-stream (:stream_port)
        └── Home Assistant API → LinkPlay / DLNA media_player
```

## Notes

- **Host network** is required for Cast/mDNS and for speakers to fetch streams
- Google Home speaker groups and Spotify Cast are out of scope
- New LinkPlay/DLNA devices do not auto-join; reconfigure and restart
