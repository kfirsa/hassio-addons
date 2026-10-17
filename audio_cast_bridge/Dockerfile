ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    ADDON_VERSION=1.0.7 \
    PYTHONUNBUFFERED=1 \
    CAST_FRONTEND_BIN=/usr/local/bin/cast-frontend \
    ACB_APP_DIR=/opt/audio_cast_bridge

# Use Alpine packages only — pip wheels for aiohttp fail on Python 3.14 without a C toolchain.
RUN \
    apk add --no-cache \
        python3 \
        py3-aiohttp \
        ffmpeg \
        yt-dlp

COPY app/ ${ACB_APP_DIR}/
COPY rootfs /

RUN chmod a+x /etc/cont-init.d/* /etc/services.d/*/* 2>/dev/null || true

# Cast V2 frontend binary is optional at build time. Place a Vibecast/Lab-compatible
# binary at CAST_FRONTEND_BIN (image build ARG or volume) to enable LAN advertisement.
# Without it the add-on still runs configure UI, HA discovery, and stream relay.
LABEL \
    io.hass.name="Audio Cast Bridge" \
    io.hass.description="Cast V2 bridge for LinkPlay/DLNA via Home Assistant" \
    io.hass.version="${ADDON_VERSION}" \
    io.hass.type="addon" \
    io.hass.arch="aarch64|amd64"

EXPOSE 8099 18080
