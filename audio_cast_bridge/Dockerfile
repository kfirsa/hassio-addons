ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    ADDON_VERSION=1.0.0 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CAST_FRONTEND_BIN=/usr/local/bin/cast-frontend \
    ACB_APP_DIR=/opt/audio_cast_bridge

# Runtime tools: Python manager, ffmpeg relay, optional yt-dlp extract path
RUN \
    apk add --no-cache \
        python3 \
        py3-pip \
        ffmpeg \
        yt-dlp \
    && python3 -m pip install --break-system-packages --no-cache-dir \
        aiohttp==3.11.18 \
        yarl==1.20.0

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
