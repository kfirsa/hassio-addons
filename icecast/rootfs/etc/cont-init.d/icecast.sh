#!/usr/bin/with-contenv bashio
# ==============================================================================
# Generate Icecast and nginx Ingress configuration
# ==============================================================================
set -e

bashio::log.info "Initializing Icecast add-on..."

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
xml_escape() {
    local s="${1}"
    s="${s//&/&amp;}"
    s="${s//</&lt;}"
    s="${s//>/&gt;}"
    s="${s//\"/&quot;}"
    s="${s//\'/&apos;}"
    printf '%s' "${s}"
}

# ---------------------------------------------------------------------------
# Read options (passwords are mandatory)
# ---------------------------------------------------------------------------
SOURCE_PASSWORD=$(bashio::config 'source_password')
RELAY_PASSWORD=$(bashio::config 'relay_password')
ADMIN_PASSWORD=$(bashio::config 'admin_password')

if ! bashio::config.has_value 'source_password' || [[ -z "${SOURCE_PASSWORD}" ]]; then
    bashio::exit.nok "Option 'source_password' is required. Set it in the add-on configuration."
fi
if ! bashio::config.has_value 'relay_password' || [[ -z "${RELAY_PASSWORD}" ]]; then
    bashio::exit.nok "Option 'relay_password' is required. Set it in the add-on configuration."
fi
if ! bashio::config.has_value 'admin_password' || [[ -z "${ADMIN_PASSWORD}" ]]; then
    bashio::exit.nok "Option 'admin_password' is required. Set it in the add-on configuration."
fi

HOSTNAME=""
if bashio::config.has_value 'hostname'; then
    HOSTNAME=$(bashio::config 'hostname')
fi

if [[ -z "${HOSTNAME}" ]]; then
    DISCOVERED=""
    if bashio::supervisor.ping; then
        DISCOVERED=$(bashio::host.hostname 2>/dev/null || true)
    fi
    if [[ -n "${DISCOVERED}" ]]; then
        HOSTNAME="${DISCOVERED}"
        bashio::log.info "Discovered host hostname: ${HOSTNAME}"
    else
        HOSTNAME="homeassistant.local"
        bashio::log.info "Host hostname unavailable; using default: ${HOSTNAME}"
    fi
else
    bashio::log.info "Using configured hostname: ${HOSTNAME}"
fi

LOCATION=$(bashio::config 'location')
ADMIN=$(bashio::config 'admin')
MAX_CLIENTS=$(bashio::config 'max_clients')
MAX_SOURCES=$(bashio::config 'max_sources')
SOURCE_TIMEOUT=$(bashio::config 'source_timeout')

# Keep intermittent sources (e.g. SDRTrunk) connected during long silence
if ! bashio::config.has_value 'source_timeout' || [[ -z "${SOURCE_TIMEOUT}" ]] || [[ "${SOURCE_TIMEOUT}" -lt 1 ]]; then
    SOURCE_TIMEOUT=86400
fi

SOURCE_PASSWORD_XML=$(xml_escape "${SOURCE_PASSWORD}")
RELAY_PASSWORD_XML=$(xml_escape "${RELAY_PASSWORD}")
ADMIN_PASSWORD_XML=$(xml_escape "${ADMIN_PASSWORD}")
HOSTNAME_XML=$(xml_escape "${HOSTNAME}")
LOCATION_XML=$(xml_escape "${LOCATION}")
ADMIN_XML=$(xml_escape "${ADMIN}")

# ---------------------------------------------------------------------------
# Directories and web roots
# ---------------------------------------------------------------------------
mkdir -p /data/log /data/nginx /run/nginx

# Alpine packages typically ship web assets under /usr/share/icecast
WEBROOT="/usr/share/icecast/web"
ADMINROOT="/usr/share/icecast/admin"

if [[ ! -d "${WEBROOT}" ]]; then
    # Fallback for alternate packaging layouts
    if [[ -d /usr/share/icecast2/web ]]; then
        WEBROOT="/usr/share/icecast2/web"
        ADMINROOT="/usr/share/icecast2/admin"
        BASEDIR="/usr/share/icecast2"
    else
        bashio::exit.nok "Icecast webroot not found under /usr/share/icecast"
    fi
else
    BASEDIR="/usr/share/icecast"
fi

# Ensure icecast can write logs and PRNG seed; config must not be world-readable
mkdir -p /data/log
chown -R icecast:icecast /data/log 2>/dev/null || true
chmod 750 /data/log
touch /data/log/icecast.pid /data/log/access.log /data/log/error.log /data/log/icecast.prng-seed
chown icecast:icecast /data/log/icecast.pid /data/log/access.log /data/log/error.log /data/log/icecast.prng-seed
chmod 640 /data/log/access.log /data/log/error.log /data/log/icecast.prng-seed
chmod 644 /data/log/icecast.pid

# ---------------------------------------------------------------------------
# icecast.xml
# ---------------------------------------------------------------------------
bashio::log.info "Writing /data/icecast.xml"

cat > /data/icecast.xml <<EOF
<icecast>
    <location>${LOCATION_XML}</location>
    <admin>${ADMIN_XML}</admin>
    <hostname>${HOSTNAME_XML}</hostname>

    <limits>
        <clients>${MAX_CLIENTS}</clients>
        <sources>${MAX_SOURCES}</sources>
        <queue-size>524288</queue-size>
        <client-timeout>30</client-timeout>
        <header-timeout>15</header-timeout>
        <source-timeout>${SOURCE_TIMEOUT}</source-timeout>
        <burst-size>65535</burst-size>
    </limits>

    <authentication>
        <source-password>${SOURCE_PASSWORD_XML}</source-password>
        <relay-password>${RELAY_PASSWORD_XML}</relay-password>
        <admin-user>admin</admin-user>
        <admin-password>${ADMIN_PASSWORD_XML}</admin-password>
    </authentication>

    <listen-socket>
        <port>8000</port>
        <bind-address>0.0.0.0</bind-address>
    </listen-socket>

    <http-headers>
        <header name="Access-Control-Allow-Origin" value="*" />
    </http-headers>

    <fileserve>1</fileserve>

    <paths>
        <basedir>${BASEDIR}</basedir>
        <logdir>/data/log</logdir>
        <webroot>${WEBROOT}</webroot>
        <adminroot>${ADMINROOT}</adminroot>
        <pidfile>/data/log/icecast.pid</pidfile>
        <alias source="/" destination="/status.xsl"/>
    </paths>

    <logging>
        <accesslog>access.log</accesslog>
        <errorlog>error.log</errorlog>
        <loglevel>3</loglevel>
        <logsize>10000</logsize>
    </logging>

    <security>
        <chroot>0</chroot>
        <changeowner>
            <user>icecast</user>
            <group>icecast</group>
        </changeowner>
    </security>

    <prng-seed type="read-write" size="1024">/data/log/icecast.prng-seed</prng-seed>
    <prng-seed type="profile">linux</prng-seed>
</icecast>
EOF

chmod 640 /data/icecast.xml
chown root:icecast /data/icecast.xml 2>/dev/null || chown root:root /data/icecast.xml

# ---------------------------------------------------------------------------
# nginx Ingress front-end (port 8099)
# Rewrites absolute root paths so Icecast UI works under HA Ingress.
# ---------------------------------------------------------------------------
bashio::log.info "Writing nginx Ingress configuration"

mkdir -p /tmp/nginx/client_body /tmp/nginx/proxy /tmp/nginx/fastcgi /tmp/nginx/uwsgi /tmp/nginx/scgi

# Start with optional dynamic sub_filter module (Alpine)
: > /data/nginx/ingress.conf
if [[ -f /usr/lib/nginx/modules/ngx_http_sub_module.so ]]; then
    echo 'load_module /usr/lib/nginx/modules/ngx_http_sub_module.so;' >> /data/nginx/ingress.conf
elif [[ -f /etc/nginx/modules/ngx_http_sub_module.so ]]; then
    echo 'load_module /etc/nginx/modules/ngx_http_sub_module.so;' >> /data/nginx/ingress.conf
fi

cat >> /data/nginx/ingress.conf <<'EOF'
worker_processes 1;
error_log /data/log/nginx-error.log warn;
pid /tmp/nginx.pid;

events {
    worker_connections 128;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    access_log    /data/log/nginx-access.log;
    sendfile      on;
    keepalive_timeout 65;
    # Disable compression so sub_filter can rewrite HTML/XSL bodies
    gzip off;

    client_body_temp_path /tmp/nginx/client_body;
    proxy_temp_path       /tmp/nginx/proxy;
    fastcgi_temp_path     /tmp/nginx/fastcgi;
    uwsgi_temp_path       /tmp/nginx/uwsgi;
    scgi_temp_path        /tmp/nginx/scgi;

    map $http_x_ingress_path $ingress_path {
        default $http_x_ingress_path;
        ""      "";
    }

    server {
        listen 8099 default_server;
        server_name _;

        allow 172.30.32.2;
        deny all;

        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Accept-Encoding "";

            # text/html is implied by sub_filter; listing it causes a duplicate MIME warning
            sub_filter_types text/css text/xml application/xml application/xhtml+xml;
            sub_filter_once off;
            sub_filter 'href="/' 'href="$ingress_path/';
            sub_filter "href='/" "href='$ingress_path/";
            sub_filter 'src="/' 'src="$ingress_path/';
            sub_filter "src='/" "src='$ingress_path/";
            sub_filter 'url(/' 'url($ingress_path/';
            sub_filter 'action="/' 'action="$ingress_path/';
            sub_filter 'content="/' 'content="$ingress_path/';
        }
    }
}
EOF

bashio::log.info "Icecast initialization complete"
