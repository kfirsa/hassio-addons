# Changelog

All notable changes to the Audio Cast Bridge Home Assistant add-on are documented in this file.

## 1.1.8

- Fix stream relay crash: restore missing `_fanout` so audio actually reaches speakers after connect

## 1.1.7

- Fix Cast session abort: out-of-band volume must not report IDLE before/during load (phones tear down the bridge); serialize websocket sends

## 1.1.6

- Fix Cast volume control: apply volume immediately (not blocked behind load), echo level to the phone, avoid spurious unmute spam on LinkPlay

## 1.1.5

- Fix cast stopping after a few seconds: apply backpressure to slow speakers instead of dropping the HTTP listener when the queue fills

## 1.1.4

- If no speaker fetches the `.local` stream URL within 10s, retry `play_media` with the LAN IP and log a clear `stream_host` hint

## 1.1.3

- Default stream URL host is `{hostname}.local`; set `stream_host` to a LAN IP if speakers cannot resolve mDNS

## 1.1.2

- Fix stream dying before speakers connect: ffmpeg no longer drains the whole track with zero HTTP listeners
- Prefer LAN IP for stream URLs (speakers often cannot resolve hostname `homeassistant`)
- Optional Supervisor option `stream_host` to override the stream URL host

## 1.1.1

- Keep Cast session alive while HA is still buffering (do not report IDLE right after connect)
- Wait for ffmpeg to produce audio before calling `play_media`
- Harden ffmpeg relay (HTTPS/HLS whitelist, user-agent, stderr logging)

## 1.1.0

- Ship Vibecast Cast frontend (from cast-audio-receiver-lab `0.6.0-dev29`) so selected speakers advertise on the LAN
- First-start hash-pinned auth bundle download into `/data/private`
- Per-speaker player-protocol bridge → HA `play_media` / controls
- Switch image base to Debian bookworm (glibc) so Vibecast runs
- Ingress banner shows advertisement status

## 1.0.7

- Log each Cast target by name on start (e.g. `Kitchen Balcony (Audio Cast Bridge)`)
- Warn clearly when the Cast V2 frontend binary is missing so LAN advertisement is inactive

## 1.0.6

- Apply speaker selection immediately: changing checkboxes restarts the add-on (no Save step)
- Default `max_bridges` / concurrent streams = **2**

## 1.0.5

- Fix template fallback parsing: HA returns Python list repr (`['a','b']`), not JSON
- Keep entity-registry WebSocket as primary discovery

## 1.0.4

- Discover speakers via entity-registry WebSocket (fixes empty lists when templates return nothing)
- Treat official **wiim** integration as eligible (WiiM/LinkPlay-family), alongside linkplay and dlna_dmr
- Show all media_player platform counts in the UI for debugging

## 1.0.3

- Fix eligible device discovery: resolve LinkPlay/DLNA/Cast via `integration_entities()` (state attributes do not expose platform)

## 1.0.2

- Fix Docker build: install `py3-aiohttp` via apk instead of pip (Python 3.14 has no aiohttp wheel without a compiler)

## 1.0.1

- Add store `icon.png` / `logo.png` using Material `music_cast` glyph
- Show logo in Ingress header
- Remove redundant versioning docs/UI (version lives in `config.yaml` + this changelog)

## 1.0.0

- Initial Audio Cast Bridge add-on (experimental)
- Configure-then-restart flow: list eligible LinkPlay/DLNA entities, skip native Cast, select bridges
- Configure-time RAM estimate: `128 + (N × 12) + (max_concurrent_streams × 48)` MB
- Persist pending/committed bridge config under `/data`
- Home Assistant API client for discovery and `media_player` playback control
- HTTP stream relay (ffmpeg) for stable LAN URLs to speakers
- Ingress UI for device selection, sizing, restart banner, and health
- Cast V2 frontend integration hooks (binary pin / player-bridge); advertise `{friendly_name} (Audio Cast Bridge)`
- Document Cast authentication fragility and host-network requirements
