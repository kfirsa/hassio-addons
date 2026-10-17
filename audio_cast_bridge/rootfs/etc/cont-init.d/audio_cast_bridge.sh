#!/usr/bin/with-contenv bashio
# ==============================================================================
# Audio Cast Bridge initialization
# ==============================================================================
set -e

bashio::log.info "Initializing Audio Cast Bridge v${ADDON_VERSION:-1.0.0}..."

mkdir -p /data/log
chmod 750 /data/log

MAX_BRIDGES=$(bashio::config 'max_bridges')
MAX_STREAMS=$(bashio::config 'max_concurrent_streams')
STREAM_PORT=$(bashio::config 'stream_port')
LOG_LEVEL=$(bashio::config 'log_level')

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
export ADDON_VERSION='${ADDON_VERSION:-1.0.0}'
export CAST_FRONTEND_BIN='${CAST_FRONTEND_BIN:-/usr/local/bin/cast-frontend}'
EOF

bashio::log.info "Host hint for streams: ${HOST_HINT}"
bashio::log.info "max_bridges=${MAX_BRIDGES} max_concurrent_streams=${MAX_STREAMS} stream_port=${STREAM_PORT}"
bashio::log.info "Initialization complete"
