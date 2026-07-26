# Icecast

[Icecast](https://icecast.org/) streaming media server for Home Assistant. Stream audio (Ogg Vorbis, Opus, MP3, WebM, and more) on your home network, with the admin UI available through Home Assistant Ingress.

## Features

- Icecast server with configurable source, relay, and admin passwords
- **Ingress** panel for the Icecast status and admin web UI inside Home Assistant
- Host port **8000** for source clients and listeners (not via Ingress)
- Persistent logs under add-on data storage

## Installation

1. Add this repository to Home Assistant:
   - **Settings** → **Add-ons** → **Add-on Store** → **Repositories**
   - Add: `https://github.com/kfirsa/hassio-addons`
2. Install **Icecast** from the add-on store
3. Set the required passwords in the configuration (`source_password`, `relay_password`, `admin_password`)
4. Start the add-on
5. Open the UI via **Open Web UI** / Ingress (sidebar: Icecast)

## Access

| Use | How |
|-----|-----|
| Status / admin UI | Home Assistant Ingress (sidebar or Open Web UI) |
| Source clients (butt, Liquidsoap, ffmpeg, …) | `http://<home-assistant-ip>:8000` |
| Listeners / players | `http://<home-assistant-ip>:8000/<mount>` |

All three passwords are **required** — the add-on will not start until they are set. Choose strong values before exposing port 8000 on an untrusted network.

Admin pages still use Icecast HTTP Basic Auth (`admin` + your `admin_password`) even when opened through Ingress.

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `source_password` | Password for source clients (**required**) | — |
| `relay_password` | Password for relays (**required**) | — |
| `admin_password` | Password for admin user `admin` (**required**) | — |
| `hostname` | Hostname used in playlists / directory listings | `local` |
| `location` | Location string shown on the status page | `Home` |
| `admin` | Contact shown on the status page | `admin@example.com` |
| `max_clients` | Maximum concurrent listeners | `100` |
| `max_sources` | Maximum concurrent sources | `10` |

### Example

```yaml
source_password: "your-source-password"
relay_password: "your-relay-password"
admin_password: "your-admin-password"
hostname: "homeassistant.local"
location: "Home"
admin: "you@example.com"
max_clients: 100
max_sources: 10
```

## Source client example (ffmpeg)

```bash
ffmpeg -re -i music.mp3 -c:a libmp3lame -b:a 128k -f mp3 \
  -content_type audio/mpeg \
  icecast://source:YOUR_SOURCE_PASSWORD@HOMEASSISTANT_IP:8000/live
```

Listeners can then open:

```text
http://HOMEASSISTANT_IP:8000/live
```

## Notes

- This add-on runs the Icecast **server only**. Source encoding (ffmpeg, IceS, butt, etc.) runs elsewhere and connects to port 8000.
- TLS is not terminated inside the add-on; use your reverse proxy or Home Assistant networking as needed.
- Icecast version comes from the Alpine package on the Home Assistant base image (commonly 2.4.x).
