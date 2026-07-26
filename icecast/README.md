# Icecast

[Icecast](https://icecast.org/) streaming media server for Home Assistant. Stream audio (Ogg Vorbis, Opus, MP3, WebM, and more) on your home network, with the admin UI available through Home Assistant Ingress.

## Features

- Icecast server with required, configurable source, relay, and admin passwords
- **Ingress** panel for the Icecast status and admin web UI inside Home Assistant
- Host port **8000** for source clients and listeners (not via Ingress)
- Optional hostname: auto-discovered from the Home Assistant host, or set manually
- Persistent logs under add-on data storage

## Installation

1. Add this repository to Home Assistant:
   - **Settings** → **Add-ons** → **Add-on Store** → **Repositories**
   - Add: `https://github.com/kfirsa/hassio-addons`
2. Install **Icecast** from the add-on store
3. Set the required passwords (`source_password`, `relay_password`, `admin_password`)
4. Optionally set `hostname` (see [Hostname](#hostname) below); leave empty to auto-discover
5. Start the add-on
6. Open the UI via **Open Web UI** / Ingress (sidebar: **Icecast**)

## Access

| Use | How |
|-----|-----|
| Status / admin UI | Home Assistant Ingress (sidebar or **Open Web UI**) |
| Source clients (butt, Liquidsoap, ffmpeg, …) | `http://<home-assistant-host>:8000` |
| Listeners / players | `http://<home-assistant-host>:8000/<mount>` |

Use your Home Assistant IP, or a DNS / mDNS name that resolves to that host (for example `homeassistant.local` or a custom name like `stream.local`).

All three passwords are **required** — the add-on will not start until they are set. Choose strong values before exposing port 8000 on an untrusted network.

Admin pages under `/admin/` still use Icecast HTTP Basic Auth (`admin` + your `admin_password`) even when opened through Ingress.

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `source_password` | Password for source clients (**required**) | — |
| `relay_password` | Password for relays (**required**) | — |
| `admin_password` | Password for admin user `admin` (**required**) | — |
| `hostname` | Advertised hostname for playlists / directory listings (optional) | Auto-discover, else `homeassistant.local` |
| `location` | Location string shown on the status page | `Home` |
| `admin` | Contact shown on the status page | `admin@example.com` |
| `max_clients` | Maximum concurrent listeners | `100` |
| `max_sources` | Maximum concurrent sources | `10` |
| `source_timeout` | Seconds without data before Icecast drops a source. Use a high value for intermittent streams (e.g. SDRTrunk) | `86400` (24h) |

### Hostname

Icecast’s `hostname` is **not** a DNS setting and does not create names like `stream.local`. It is the name Icecast puts into generated playlists and related metadata.

Resolution order:

1. If you set `hostname` in the add-on options, that value is used
2. Otherwise the add-on asks Supervisor for the Home Assistant **host** hostname
3. If discovery fails, it falls back to `homeassistant.local`

Examples:

- Leave `hostname` empty → use the platform hostname when available
- `hostname: "homeassistant.local"` → force that name in playlists
- `hostname: "stream.local"` → advertise `stream.local` (you must make that name resolve to your HA host yourself)

### Example

```yaml
source_password: "your-source-password"
relay_password: "your-relay-password"
admin_password: "your-admin-password"
# hostname: "stream.local"   # optional; leave unset to auto-discover
location: "Home"
admin: "you@example.com"
max_clients: 100
max_sources: 10
source_timeout: 86400
```

Intermittent sources (scanner / SDR audio that is silent for long periods) need a high `source_timeout`. The previous default of 10 seconds caused Icecast to disconnect idle sources with `Disconnecting source … due to socket timeout`.

## Source client example (ffmpeg)

```bash
ffmpeg -re -i music.mp3 -c:a libmp3lame -b:a 128k -f mp3 \
  -content_type audio/mpeg \
  icecast://source:YOUR_SOURCE_PASSWORD@HOMEASSISTANT_HOST:8000/live
```

Listeners can then open:

```text
http://HOMEASSISTANT_HOST:8000/live
```

Replace `HOMEASSISTANT_HOST` with the host IP or the same name you use for listening (for example `homeassistant.local`).

## Notes

- This add-on runs the Icecast **server only**. Source encoding (ffmpeg, IceS, butt, etc.) runs elsewhere and connects to port 8000.
- Ingress is for the web UI only. Do not rely on Ingress for live stream playback; use port **8000**.
- TLS is not terminated inside the add-on; use your reverse proxy or Home Assistant networking as needed.
- Icecast version comes from the Alpine package on the Home Assistant base image (commonly 2.4.x / 2.5.x).
- Release notes for each version are in [`CHANGELOG.md`](CHANGELOG.md) (shown in Home Assistant when an update is available).
