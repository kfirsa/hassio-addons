#!/usr/bin/with-contenv bash

# Logging functions with timestamps and levels
log_info() {
    echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

log_warn() {
    echo "[WARN] $(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}

log_error() {
    echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}

log_info "Starting Extended CUPS Print Server initialization..."

# Create CUPS data directories for persistence
log_info "Creating CUPS data directories..."
if mkdir -p /data/cups/cache /data/cups/logs /data/cups/state /data/cups/config; then
    log_info "CUPS data directories created successfully"
else
    log_error "Failed to create CUPS data directories"
    exit 1
fi

# Set proper permissions
log_info "Setting permissions for CUPS data directories..."
if chown -R root:lp /data/cups && chmod -R 775 /data/cups; then
    log_info "Permissions set successfully"
else
    log_warn "Some permission operations may have failed"
fi

# Create CUPS configuration directory if it doesn't exist
log_info "Creating CUPS configuration directory..."
mkdir -p /etc/cups

# Basic CUPS configuration without admin authentication
log_info "Generating CUPS configuration file..."
cat > /data/cups/config/cupsd.conf << EOL
# Server root directory - ensures all config files are in persistent location
# This MUST be an absolute path to ensure CUPS writes to persistent storage
ServerRoot /data/cups/config

# State directory for printer configurations
StateDir /data/cups/state

# Listen on all interfaces
Listen 0.0.0.0:631

# Allow access from local network
<Location />
  Order allow,deny
  Allow localhost
  Allow 10.0.0.0/8
  Allow 172.16.0.0/12
  Allow 192.168.0.0/16
</Location>

# Admin access (no authentication)
<Location /admin>
  Order allow,deny
  Allow localhost
  Allow 10.0.0.0/8
  Allow 172.16.0.0/12
  Allow 192.168.0.0/16
</Location>

# Job management permissions
<Location /jobs>
  Order allow,deny
  Allow localhost
  Allow 10.0.0.0/8
  Allow 172.16.0.0/12
  Allow 192.168.0.0/16
</Location>

<Limit Send-Document Send-URI Hold-Job Release-Job Restart-Job Purge-Jobs Set-Job-Attributes Create-Job-Subscription Renew-Subscription Cancel-Subscription Get-Notifications Reprocess-Job Cancel-Current-Job Suspend-Current-Job Resume-Job Cancel-My-Jobs Close-Job CUPS-Move-Job CUPS-Get-Document>
  Order allow,deny
  Allow localhost
  Allow 10.0.0.0/8
  Allow 172.16.0.0/12
  Allow 192.168.0.0/16
</Limit>

# Enable web interface
WebInterface Yes

# USB backend configuration
# Enable USB printer detection
LoadModule usb

# Automatic printer discovery (Bonjour/mDNS)
# Enable browsing for network printers
Browsing On
BrowseLocalProtocols dnssd
BrowseRemoteProtocols dnssd
BrowseAllow all
BrowseAddress @LOCAL
# Poll remote printers periodically for discovery
BrowsePoll all

# Default settings
DefaultAuthType None
JobSheets none,none
PreserveJobHistory No
EOL

if [ -f /data/cups/config/cupsd.conf ]; then
    log_info "CUPS configuration file created successfully"
else
    log_error "Failed to create CUPS configuration file"
    exit 1
fi

# Initialize printers.conf in persistent location if it doesn't exist
# This ensures printer configurations persist across restarts and upgrades
log_info "Initializing printers configuration file..."
if [ ! -f /data/cups/config/printers.conf ]; then
    touch /data/cups/config/printers.conf
    chown root:lp /data/cups/config/printers.conf
    chmod 640 /data/cups/config/printers.conf
    log_info "Created new printers.conf in persistent location"
else
    log_info "Existing printers.conf found in persistent location"
fi

# Ensure /etc/cups directory exists but remove any non-persistent printers.conf
log_info "Preparing /etc/cups directory..."
mkdir -p /etc/cups

# If printers.conf exists in /etc/cups (non-persistent), copy it to persistent location
if [ -f /etc/cups/printers.conf ] && [ ! -L /etc/cups/printers.conf ]; then
    log_info "Found existing printers.conf in /etc/cups, copying to persistent location..."
    cp /etc/cups/printers.conf /data/cups/config/printers.conf
    chown root:lp /data/cups/config/printers.conf
    chmod 640 /data/cups/config/printers.conf
    rm -f /etc/cups/printers.conf
    log_info "Migrated printers.conf to persistent location"
fi

# Remove any existing printers.conf in /etc/cups (even if symlink) to ensure clean state
rm -f /etc/cups/printers.conf

# Create symlinks - MUST be done after removing any existing files
log_info "Creating configuration symlinks..."
if ln -sf /data/cups/config/cupsd.conf /etc/cups/cupsd.conf && \
   ln -sf /data/cups/config/printers.conf /etc/cups/printers.conf; then
    log_info "Configuration symlinks created successfully"
else
    log_error "Failed to create configuration symlinks"
    exit 1
fi

# Verify symlinks are correct
if [ -L /etc/cups/printers.conf ] && [ "$(readlink /etc/cups/printers.conf)" = "/data/cups/config/printers.conf" ]; then
    log_info "Printers configuration symlink verified correctly"
else
    log_error "Printers configuration symlink is incorrect"
    exit 1
fi

# Verify printers.conf is accessible in persistent location
if [ -f /data/cups/config/printers.conf ] && [ -r /data/cups/config/printers.conf ]; then
    log_info "Printers configuration file is ready and accessible in persistent location"
    # Show file size to verify it has content
    file_size=$(stat -c%s /data/cups/config/printers.conf 2>/dev/null || echo "0")
    if [ "$file_size" -gt 0 ]; then
        log_info "Printers configuration file contains data ($file_size bytes)"
    else
        log_info "Printers configuration file is empty (no printers configured yet)"
    fi
else
    log_error "Printers configuration file is not accessible"
    exit 1
fi

# Verify ZJ-58 driver installation
log_info "Verifying ZJ-58 thermal printer driver installation..."
if [ -f /usr/lib/cups/filter/rastertozj ] && [ -f /usr/share/cups/model/zjiang/ZJ-58.ppd ]; then
    log_info "ZJ-58 driver found: filter and PPD installed"
else
    log_warn "ZJ-58 driver files not found - thermal printer support may be limited"
fi

# Function to validate PPD file
validate_ppd() {
    local file="$1"
    # Check if file exists and is readable
    if [ ! -f "$file" ] || [ ! -r "$file" ]; then
        return 1
    fi
    # Check if file starts with PPD header (PPD files start with *PPD-Adobe or similar)
    if head -n 1 "$file" | grep -qE '^\*PPD-Adobe|^\*FormatVersion|^\*%PDF'; then
        return 0
    fi
    return 1
}

# Download additional PPD files from OpenPrinting if configured
# Home Assistant passes list options as JSON arrays in environment variables
PPD_URLS_ENV="${PPD_URLS:-[]}"
if [ "$PPD_URLS_ENV" != "[]" ] && [ -n "$PPD_URLS_ENV" ]; then
    log_info "PPD URLs configured, starting download process..."
    # Create directory for downloaded PPDs
    if mkdir -p /usr/share/cups/model/openprinting; then
        log_info "OpenPrinting PPD directory ready"
    else
        log_error "Failed to create OpenPrinting PPD directory"
    fi
    
    download_count=0
    error_count=0
    
    # Parse PPD URLs from JSON array format
    # Extract URLs from JSON array: ["url1", "url2"] -> url1, url2
    echo "$PPD_URLS_ENV" | grep -oE 'https?://[^"]+' | while read -r url; do
        if [ -n "$url" ]; then
            filename=$(basename "$url" | sed 's/[?&].*//')
            # Ensure filename ends with .ppd
            if [ "${filename##*.}" != "ppd" ]; then
                filename="${filename}.ppd"
            fi
            temp_file="/tmp/${filename}"
            log_info "Downloading PPD: $filename from $url"
            
            # Download to temporary file first
            if curl -f -L -s -o "$temp_file" "$url"; then
                # Validate that it's a valid PPD file
                if validate_ppd "$temp_file"; then
                    if mv "$temp_file" "/usr/share/cups/model/openprinting/$filename"; then
                        log_info "Successfully downloaded and validated: $filename"
                        download_count=$((download_count + 1))
                    else
                        log_error "Failed to move validated PPD file: $filename"
                        rm -f "$temp_file"
                        error_count=$((error_count + 1))
                    fi
                else
                    rm -f "$temp_file"
                    log_error "Rejected invalid PPD file from $url - file does not appear to be a valid PPD file"
                    error_count=$((error_count + 1))
                fi
            else
                log_error "Failed to download PPD from $url"
                error_count=$((error_count + 1))
            fi
        fi
    done
    
    log_info "PPD download process completed"
else
    log_info "No additional PPD URLs configured, skipping download"
fi

# Ensure USB devices are accessible
log_info "Setting up USB device access..."
if mkdir -p /dev/bus/usb; then
    log_info "USB device directory ready"
    # Check if USB devices are accessible
    if [ -d /dev/bus/usb ] && [ -r /dev/bus/usb ]; then
        log_info "USB backend should be functional"
    else
        log_warn "USB device directory may not be accessible - USB printers may not be detected"
    fi
else
    log_error "Failed to create USB device directory"
fi

# Start Avahi daemon for mDNS/Bonjour printer discovery
log_info "Setting up Avahi daemon for automatic printer discovery..."
if [ -x /usr/sbin/avahi-daemon ]; then
    # Create Avahi configuration directory
    mkdir -p /etc/avahi
    # Create minimal Avahi configuration if it doesn't exist
    if [ ! -f /etc/avahi/avahi-daemon.conf ]; then
        cat > /etc/avahi/avahi-daemon.conf << AVAHI_EOF
[server]
host-name=cups
use-ipv4=yes
use-ipv6=no
enable-dbus=no

[wide-area]
enable-wide-area=yes

[publish]
publish-hinfo=no
publish-workstation=no
publish-domain=yes

[reflector]
enable-reflector=no
AVAHI_EOF
        log_info "Created Avahi daemon configuration"
    fi
    
    # Start Avahi daemon in background
    if /usr/sbin/avahi-daemon -D; then
        log_info "Avahi daemon started successfully for network printer discovery"
        # Give Avahi a moment to initialize
        sleep 1
    else
        log_warn "Avahi daemon may have failed to start (this is OK if already running)"
    fi
else
    log_warn "Avahi daemon not found - automatic network printer discovery may be limited"
fi

# Verify CUPS binary exists
if [ -x /usr/sbin/cupsd ]; then
    log_info "CUPS daemon found, starting service..."
else
    log_error "CUPS daemon not found at /usr/sbin/cupsd"
    exit 1
fi

log_info "Initialization complete, starting CUPS service..."
log_info "Automatic printer discovery enabled:"
log_info "  - USB printers: Auto-detected via USB backend"
log_info "  - Network printers: Auto-discovered via mDNS/Bonjour (Avahi)"
log_info "  - Printer configurations: Persisted in /data/cups/config"
# Start CUPS service
/usr/sbin/cupsd -f
