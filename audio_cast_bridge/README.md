# Audio Cast Bridge

Experimental Home Assistant add-on that bridges **YouTube Music / Cast audio** to
**LinkPlay** and **DLNA** speakers that do not have native Google Cast.

See [`CHANGELOG.md`](CHANGELOG.md) for release notes (shown by Home Assistant on update).

## Features

- Pick eligible speakers in Ingress; changing selection **restarts and applies** immediately (default max **2** bridges)
- Supports **WiiM**, **LinkPlay**, and **DLNA DMR** media players
- Skips devices that already have **native Google Cast**
- Cast target name: `{friendly_name} (Audio Cast Bridge)` — advertised on the LAN via **Vibecast**
- HA `media_player.play_media` + **ffmpeg** HTTP re-stream for stable LAN URLs
- Ingress UI for device selection, sizing, and health

## Installation

1. Add this repository in **Settings → Add-ons → Add-on Store → Repositories**:
   `https://github.com/kfirsa/hassio-addons`
2. Install **Audio Cast Bridge**
3. Start the add-on (requires **host network**)
4. Open **Web UI** / Ingress
5. Select eligible devices (up to 2 by default); the add-on restarts and applies automatically
6. On first start the add-on downloads a **hash-pinned Cast auth bundle** into private add-on data (not stored in git)

After update, look for log lines like:

```text
Advertising Cast speaker: 'Kitchen Balcony (Audio Cast Bridge)' → media_player.…
```

Phones may take ~30s for mDNS before the name appears in the Cast picker.

## Configuration (Supervisor options)

| Option | Description | Default |
|--------|-------------|---------|
| `max_bridges` | Hard ceiling on selected devices | `2` |
| `max_concurrent_streams` | Max simultaneous ffmpeg relays / casts | `2` |
| `stream_port` | LAN HTTP port for speaker streams | `18080` |
| `dial_base_port` | Reserved (legacy) | `3100` |
| `log_level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |
| `certificate_path` | Optional absolute path to a local BYO auth bundle | empty |
| `stream_host` | Host/IP used in speaker stream URLs (blank = auto LAN IP) | empty |

Device selection is stored under add-on `/data` (not in Supervisor options).

### RAM estimate (configure time)

```text
suggested_ram_mb = 128 + (N_selected × 12) + (max_concurrent_streams × 48)
```

The Ingress UI shows this and a recommended host free-RAM band.

## Cast V2 (Vibecast)

The image ships the **Vibecast** binary from
[cast-audio-receiver-lab](https://github.com/Allcrafter1/cast-audio-receiver-lab)
(`ghcr.io/allcrafter1/cast-audio-receiver:0.6.0-dev29`). Each selected HA entity
registers as a separate audio Cast receiver over the loopback player bridge.

Cast authentication uses a separately released experimental bundle (downloaded
once). Google can revoke or change sender acceptance at any time. Treat this
add-on as experimental.

## Architecture

```text
YouTube Music / Cast sender
        │  Cast V2 (Vibecast + mDNS)
        ▼
Audio Cast Bridge manager
        ├── player-protocol adapters (one per speaker)
        ├── ffmpeg HTTP re-stream (:stream_port)
        └── Home Assistant API → LinkPlay / DLNA media_player
```

## Notes

- **Host network** is required for Cast/mDNS and for speakers to fetch streams
- Google Home speaker groups and Spotify Cast are out of scope
- New LinkPlay/DLNA devices do not auto-join; change selection (auto-restarts)
- Auth bundle provenance: [cast-audio-receiver-bundles](https://github.com/Allcrafter1/cast-audio-receiver-bundles)
