ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
# Pinned Cast Audio Receiver Lab image — source of the Vibecast binary (glibc).
ARG CAST_LAB_IMAGE=ghcr.io/allcrafter1/cast-audio-receiver:0.6.0-dev29

FROM ${CAST_LAB_IMAGE} AS cast-lab

FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    ADDON_VERSION=1.1.8 \
    PYTHONUNBUFFERED=1 \
    CAST_FRONTEND_BIN=/usr/local/bin/vibecast \
    ACB_APP_DIR=/opt/audio_cast_bridge \
    ACB_VIBECAST_CONFIG_TEMPLATE=/usr/share/audio_cast_bridge/vibecast-audio.toml

# Debian packages — Alpine/musl cannot run the Lab Vibecast binary.
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-aiohttp \
        python3-websockets \
        ffmpeg \
        yt-dlp \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=cast-lab /usr/local/bin/vibecast /usr/local/bin/vibecast
RUN chmod 0755 /usr/local/bin/vibecast

COPY app/ ${ACB_APP_DIR}/
COPY config/vibecast-audio.toml ${ACB_VIBECAST_CONFIG_TEMPLATE}
COPY config/bundle-release.json ${ACB_APP_DIR}/bundle-release.json
COPY rootfs /

RUN chmod a+x /etc/cont-init.d/* /etc/services.d/*/* 2>/dev/null || true

LABEL \
    io.hass.name="Audio Cast Bridge" \
    io.hass.description="Cast V2 bridge for LinkPlay/DLNA via Home Assistant" \
    io.hass.version="${ADDON_VERSION}" \
    io.hass.type="addon" \
    io.hass.arch="aarch64|amd64"

EXPOSE 8099 18080 8008 8009 8010
