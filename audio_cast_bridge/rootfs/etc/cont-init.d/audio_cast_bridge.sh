#!/usr/bin/with-contenv bashio
# ==============================================================================
# Audio Cast Bridge initialization
# ==============================================================================
set -e

bashio::log.info "Initializing Audio Cast Bridge v${ADDON_VERSION:-1.1.0}..."

mkdir -p /data/log /data/private /data/frontend
chmod 750 /data/log
chmod 700 /data/private /data/frontend

MAX_BRIDGES=$(bashio::config 'max_bridges')
MAX_STREAMS=$(bashio::config 'max_concurrent_streams')
STREAM_PORT=$(bashio::config 'stream_port')
LOG_LEVEL=$(bashio::config 'log_level')
CERT_PATH=$(bashio::config 'certificate_path')

HOST_HINT=""
if bashio::supervisor.ping; then
    HOST_HINT=$(bashio::host.hostname 2>/dev/null || true)
fi
if [[ -z "${HOST_HINT}" ]]; then
    HOST_HINT="homeassistant.local"
fi

cat > /data/acb.env <<EOF
export ACB_MAX_BRIDGES='${MAX_BRIDGES}'
export ACB_MAX_CONCURRENT_STREAMS='${MAX_STREAMS}'
export ACB_STREAM_PORT='${STREAM_PORT}'
export ACB_LOG_LEVEL='${LOG_LEVEL}'
export ACB_HOST_HINT='${HOST_HINT}'
export ACB_DATA_DIR='/data'
export ACB_INGRESS_PORT='8099'
export ADDON_VERSION='${ADDON_VERSION:-1.1.0}'
export CAST_FRONTEND_BIN='${CAST_FRONTEND_BIN:-/usr/local/bin/vibecast}'
export ACB_VIBECAST_CONFIG_TEMPLATE='${ACB_VIBECAST_CONFIG_TEMPLATE:-/usr/share/audio_cast_bridge/vibecast-audio.toml}'
EOF

if [[ -n "${CERT_PATH}" ]]; then
    echo "export ACB_CERTS_PATH='${CERT_PATH}'" >> /data/acb.env
fi

bashio::log.info "Host hint for streams: ${HOST_HINT}"
bashio::log.info "max_bridges=${MAX_BRIDGES} max_concurrent_streams=${MAX_STREAMS} stream_port=${STREAM_PORT}"
bashio::log.info "Cast frontend: ${CAST_FRONTEND_BIN:-/usr/local/bin/vibecast}"
bashio::log.info "Initialization complete"
