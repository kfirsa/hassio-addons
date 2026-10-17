# Changelog

All notable changes to the Audio Cast Bridge Home Assistant add-on are documented in this file.

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
