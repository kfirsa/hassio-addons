# Changelog

All notable changes to the Icecast Home Assistant add-on are documented in this file.

## 1.0.5

- Add `CHANGELOG.md` so Home Assistant shows release notes on update
- Document versioning / changelog expectations for maintainers

## 1.0.4

- Remove obsolete Icecast 2.5 tag `burst-on-connect` (use `burst-size` only)
- Configure PRNG seeds (`linux` profile + persistent seed file)
- Tighten permissions on `icecast.xml` and log files (no world-readable config)
- Pre-create `icecast.pid` under `/data/log`
- Fix nginx Ingress warning about duplicate `text/html` in `sub_filter_types`

## 1.0.3

- Add configurable `source_timeout` (default `86400` seconds)
- Prevent intermittent sources (e.g. SDRTrunk) from being dropped after 10s of silence

## 1.0.2

- Auto-discover hostname from Supervisor when `hostname` is unset
- Fall back to `homeassistant.local` if discovery fails
- Enable `hassio_api` for host hostname lookup

## 1.0.1

- Set default `BUILD_FROM` to `ghcr.io/home-assistant/base:latest` (Supervisor no longer injects it)
- Make `source_password`, `relay_password`, and `admin_password` required (no insecure defaults)

## 1.0.0

- Initial Icecast add-on with Ingress admin UI and stream port 8000
