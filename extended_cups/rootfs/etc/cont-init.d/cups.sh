#!/usr/bin/with-contenv bash

# Logging functions with timestamps and levels
log_info() {
    echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

log_debug() {
    if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
        echo "[DEBUG] $(date '+%Y-%m-%d %H:%M:%S') $*"
    fi
}

log_warn() {
    echo "[WARN] $(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}

log_error() {
    echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}

log_info "Starting Extended CUPS Print Server initialization..."

# Current addon version (from config.yaml)
# NOTE: Update this version number when bumping version in config.yaml
CURRENT_VERSION="1.5.5"
VERSION_FILE="/config/.addon_version"

# Check if debug mode is enabled
DEBUG_MODE="${DEBUG:-false}"
if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
    set -x  # Enable debug output
    log_info "DEBUG MODE ENABLED - Verbose logging activated"
fi

# Function to send Home Assistant notification via Supervisor API
send_ha_notification() {
    local title="$1"
    local message="$2"
    local version="$3"
    
    log_info "Addon updated: $title"
    log_info "  Version: $version"
    log_info "  Message: $message"
    
    # Try to send notification via Supervisor API
    # The Supervisor API socket is available at /run/supervisor/supervisor.sock
    if [ -S /run/supervisor/supervisor.sock ] && command -v curl >/dev/null 2>&1; then
        # Use Supervisor API to trigger an event that Home Assistant can listen to
        # Supervisor API endpoint: POST /supervisor/api/events
        local event_payload=$(cat <<EOF
{
    "type": "addon_update",
    "data": {
        "addon": "extended_cups",
        "version": "$version",
        "title": "$title",
        "message": "$message",
        "timestamp": "$(date -Iseconds)"
    }
}
EOF
)
        # Send event via Supervisor API
        if curl -s --unix-socket /run/supervisor/supervisor.sock \
            -X POST \
            -H "Content-Type: application/json" \
            -d "$event_payload" \
            http://supervisor/api/events >/dev/null 2>&1; then
            log_info "Update notification sent to Home Assistant via Supervisor API"
        else
            log_debug "Failed to send notification via Supervisor API (this is OK if API is not available)"
        fi
    fi
    
    # Also store notification in a file that can be monitored by Home Assistant
    # This provides a fallback method for monitoring updates
    mkdir -p /config
    local notification_file="/config/.addon_notifications"
    local notification_entry="$(date -Iseconds)|$title|$message|$version"
    echo "$notification_entry" >> "$notification_file" 2>/dev/null || true
    log_debug "Update notification stored in $notification_file"
}

# Check for addon update
if [ -f "$VERSION_FILE" ]; then
    PREVIOUS_VERSION=$(cat "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")
    if [ -n "$PREVIOUS_VERSION" ] && [ "$PREVIOUS_VERSION" != "$CURRENT_VERSION" ]; then
        log_info "========================================="
        log_info "Addon Update Detected!"
        log_info "  Previous version: $PREVIOUS_VERSION"
        log_info "  Current version: $CURRENT_VERSION"
        log_info "========================================="
        
        send_ha_notification \
            "Extended CUPS Addon Updated" \
            "The Extended CUPS Print Server addon has been updated from version $PREVIOUS_VERSION to $CURRENT_VERSION. Please check the changelog for new features and improvements." \
            "$CURRENT_VERSION"
    else
        log_debug "Addon version unchanged: $CURRENT_VERSION"
    fi
else
    log_debug "First run detected, version: $CURRENT_VERSION"
    # First run - don't send notification
fi

# Save current version
echo "$CURRENT_VERSION" > "$VERSION_FILE" 2>/dev/null || true

# Function to send Home Assistant notification via Supervisor API
send_ha_notification() {
    local title="$1"
    local message="$2"
    
    # Try to send notification via Supervisor API
    # The Supervisor API socket is available at /run/supervisor
    if [ -S /run/supervisor/supervisor.sock ]; then
        # Use Supervisor API to trigger an event that Home Assistant can listen to
        # We'll use curl to send a POST request to the Supervisor API
        local event_data=$(cat <<EOF
{
    "type": "addon_update",
    "data": {
        "addon": "extended_cups",
        "version": "$CURRENT_VERSION",
        "title": "$title",
        "message": "$message"
    }
}
EOF
)
        # Try to send via Supervisor API (if available)
        if command -v curl >/dev/null 2>&1; then
            # Use the Supervisor API endpoint
            # Note: This requires proper authentication, which may not be available
            # Alternative: Write to a file that can be monitored
            log_debug "Attempting to send HA notification: $title - $message"
            
            # Store notification in a file that can be read by Home Assistant
            mkdir -p /config
            echo "$(date -Iseconds)|$title|$message" >> /config/.addon_notifications 2>/dev/null || true
        fi
    fi
    
    # Also log the update
    log_info "$title: $message"
}

# Check for addon update
if [ -f "$VERSION_FILE" ]; then
    PREVIOUS_VERSION=$(cat "$VERSION_FILE" 2>/dev/null || echo "")
    if [ -n "$PREVIOUS_VERSION" ] && [ "$PREVIOUS_VERSION" != "$CURRENT_VERSION" ]; then
        log_info "Addon updated from version $PREVIOUS_VERSION to $CURRENT_VERSION"
        send_ha_notification "Extended CUPS Addon Updated" \
            "The Extended CUPS Print Server addon has been updated from version $PREVIOUS_VERSION to $CURRENT_VERSION. Please check the changelog for new features and improvements."
    else
        log_debug "Addon version unchanged: $CURRENT_VERSION"
    fi
else
    log_debug "First run detected, version: $CURRENT_VERSION"
    # First run - don't send notification
fi

# Save current version
echo "$CURRENT_VERSION" > "$VERSION_FILE" 2>/dev/null || true

# Create CUPS data directories
# Original files will be in /config (addon_config, visible on host)
# /data will contain symlinks pointing to /config
log_info "Creating CUPS data directories..."
# Create /data directories for logs, cache, state (these stay in /data)
if mkdir -p /data/cups/cache /data/cups/logs /data/cups/state; then
    log_info "CUPS data directories created in /data/cups (cache, logs, state)"
else
    log_error "Failed to create CUPS data directories in /data"
    exit 1
fi

# Create /config directories for configuration files (visible on host via addon_config)
# These will contain the original files
if mkdir -p /config/cups/config /config/cups/ppds; then
    log_info "Created directories in /config for addon_config mapping"
    log_info "Files in /config will be visible at /addon_configs/{REPO}_extended_cups/ on host"
else
    log_error "Failed to create directories in /config"
    exit 1
fi

# Migrate any existing files from /data/cups/config to /config/cups/config
if [ -d /data/cups/config ] && [ "$(ls -A /data/cups/config 2>/dev/null)" ]; then
    log_debug "Migrating existing files from /data/cups/config to /config/cups/config..."
    for file in /data/cups/config/*; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            if [ ! -f "/config/cups/config/$filename" ]; then
                cp "$file" "/config/cups/config/$filename" 2>/dev/null && \
                log_debug "Migrated $filename to /config/cups/config"
            fi
        fi
    done
fi

# Migrate any existing PPD files from /data/cups/ppds to /config/cups/ppds
if [ -d /data/cups/ppds ] && [ "$(ls -A /data/cups/ppds 2>/dev/null)" ]; then
    log_debug "Migrating existing PPD files from /data/cups/ppds to /config/cups/ppds..."
    for file in /data/cups/ppds/*.ppd; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            if [ "$filename" != ".ppd_metadata" ] && [ ! -f "/config/cups/ppds/$filename" ]; then
                cp "$file" "/config/cups/ppds/$filename" 2>/dev/null && \
                log_debug "Migrated PPD $filename to /config/cups/ppds"
            fi
        fi
    done
    # Also migrate metadata file if it exists
    if [ -f /data/cups/ppds/.ppd_metadata ]; then
        cp /data/cups/ppds/.ppd_metadata /config/cups/ppds/.ppd_metadata 2>/dev/null || true
    fi
fi
    
    # Verify directories exist and show their locations (debug only)
    log_debug "Persistent storage locations:"
    log_debug "  - /data/cups/config (symlink to /config/cups/config)"
    log_debug "  - /config/cups/config (accessible via /addon_configs/{REPO}_extended_cups/cups/config on host)"
    log_debug "  - /data/cups/ppds (symlink to /config/cups/ppds)"
    log_debug "  - /config/cups/ppds (accessible via /addon_configs/{REPO}_extended_cups/cups/ppds on host)"
    
    # Create marker files to ensure directories are visible
    echo "# CUPS Persistent Storage" > /data/cups/.persistent_storage_marker
    echo "# This directory contains CUPS configuration and data" >> /data/cups/.persistent_storage_marker
    echo "# Created: $(date)" >> /data/cups/.persistent_storage_marker
    
    # Also create marker in /config for addon_config visibility
    if [ -d /config ]; then
        mkdir -p /config
        echo "# CUPS Configuration (accessible via /addon_configs)" > /config/.addon_config_marker 2>/dev/null || true
        echo "# Created: $(date)" >> /config/.addon_config_marker 2>/dev/null || true
        log_debug "Created marker file in /config for addon_config visibility"
    fi
    
    # Verify we can write to the persistent location
    if touch /data/cups/.write_test 2>/dev/null && rm -f /data/cups/.write_test 2>/dev/null; then
        log_debug "Verified write access to persistent storage"
    else
        log_warn "Warning: May not have write access to persistent storage"
    fi
else
    log_error "Failed to create CUPS data directories"
    exit 1
fi

# Set proper permissions
log_debug "Setting permissions for CUPS data directories..."
if chown -R root:lp /data/cups && chmod -R 775 /data/cups; then
    log_debug "Permissions set successfully"
else
    log_warn "Some permission operations may have failed"
fi

# Make /etc/cups a symlink to /config/cups/config
# Original files are in /config (visible on host), /etc/cups points to them
log_info "Setting up CUPS configuration directory..."
if [ -d /etc/cups ] && [ ! -L /etc/cups ]; then
    # If /etc/cups exists as a directory, migrate files to /config
    log_debug "Migrating existing /etc/cups files to /config/cups/config..."
    if [ -f /etc/cups/printers.conf ]; then
        cp /etc/cups/printers.conf /config/cups/config/printers.conf 2>/dev/null || true
        log_debug "Migrated printers.conf to /config/cups/config"
    fi
    if [ -f /etc/cups/cupsd.conf ]; then
        if [ ! -f /config/cups/config/cupsd.conf ]; then
            cp /etc/cups/cupsd.conf /config/cups/config/cupsd.conf 2>/dev/null || true
            log_debug "Migrated cupsd.conf to /config/cups/config"
        fi
    fi
    # Remove the directory
    rm -rf /etc/cups
    log_debug "Removed /etc/cups directory for symlink creation"
fi

# Create symlink from /etc/cups to /config/cups/config
# This ensures CUPS writes directly to /config (visible on host)
if [ ! -L /etc/cups ]; then
    ln -sf /config/cups/config /etc/cups
    log_debug "Created /etc/cups symlink to /config/cups/config (original files in addon_config)"
else
    # Verify the symlink points to the correct location
    current_link=$(readlink /etc/cups)
    if [ "$current_link" != "/config/cups/config" ]; then
        log_warn "Existing /etc/cups symlink points to $current_link, recreating..."
        rm -f /etc/cups
        ln -sf /config/cups/config /etc/cups
        log_debug "Recreated /etc/cups symlink to /config/cups/config"
    else
        log_debug "/etc/cups symlink already points to /config/cups/config"
    fi
fi

# Also create /data/cups/config as a symlink to /config/cups/config for consistency
# This allows any scripts expecting /data/cups/config to still work
if [ -d /data/cups/config ] && [ ! -L /data/cups/config ]; then
    # If it's a directory, remove it first
    rm -rf /data/cups/config
fi
if [ ! -L /data/cups/config ]; then
    ln -sf /config/cups/config /data/cups/config
    log_debug "Created /data/cups/config symlink to /config/cups/config"
fi

# Verify the symlink works
if [ -L /etc/cups ] && [ -d /etc/cups ]; then
    log_debug "CUPS configuration directory symlink verified: /etc/cups -> /config/cups/config"
else
    log_error "Failed to create /etc/cups symlink"
    exit 1
fi

# Basic CUPS configuration without admin authentication
# Note: We don't set ServerRoot here - CUPS will use default /etc/cups
# Since /etc/cups is a symlink to /config/cups/config, all writes go to addon_config (visible on host)
log_info "Generating CUPS configuration file..."
cat > /config/cups/config/cupsd.conf << EOL
# Note: ServerRoot defaults to /etc/cups
# Since /etc/cups is symlinked to /config/cups/config (addon_config),
# all CUPS configuration files will be visible on host and persist across restarts

# Listen on all interfaces and port
# Note: With host_network: true, CUPS listens directly on the host network
Listen *:631
Port 631

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

if [ -f /config/cups/config/cupsd.conf ]; then
    log_debug "CUPS configuration file created successfully at /config/cups/config/cupsd.conf"
    log_debug "  (Original file in addon_config, visible on host)"
else
    log_error "Failed to create CUPS configuration file"
    exit 1
fi

# Initialize printers.conf in /config if it doesn't exist
# Original file is in /config (visible on host via addon_config)
log_info "Initializing printers configuration file..."
if [ ! -f /config/cups/config/printers.conf ]; then
    if touch /config/cups/config/printers.conf && chown root:lp /config/cups/config/printers.conf && chmod 640 /config/cups/config/printers.conf; then
        log_info "Created new printers.conf in /config/cups/config (original file in addon_config)"
        log_info "  (Host path: /config/addon_configs/{REPO}_extended_cups/cups/config/printers.conf)"
    else
        log_error "Failed to create printers.conf in /config/cups/config"
        exit 1
    fi
else
    log_debug "Existing printers.conf found in /config/cups/config"
    # Show file size to verify it has content
    file_size=$(stat -c%s /config/cups/config/printers.conf 2>/dev/null || echo "0")
    if [ "$file_size" -gt 0 ]; then
        log_debug "Printers configuration file contains data ($file_size bytes)"
    else
        log_debug "Printers configuration file is empty (no printers configured yet)"
    fi
fi

# Create a README file in /config/cups/config to help users understand the directory structure
# This file will be visible in /addon_configs/{REPO}_extended_cups/cups/config/ on the host
log_debug "Creating README file in /config/cups/config for user reference..."
cat > /config/cups/config/README.txt << 'READMEEOF'
CUPS Configuration Directory
============================

This directory contains CUPS configuration files that persist across addon restarts and upgrades.

Files in this directory:
- cupsd.conf: Main CUPS daemon configuration
- printers.conf: Printer definitions (created automatically when printers are added)
- Other CUPS configuration files as needed

Location:
- Container path: /data/cups/config (primary storage, CUPS writes here)
- Host path: /config/addon_configs/{REPO}_extended_cups/cups/config
- Accessible via: /config/cups/config (copied from /data for visibility)

Note: Files are stored in /data/cups/config (primary) and copied to /config/cups/config
for user accessibility via the addon_config mapping. CUPS writes to /data, files are
synced to /config for visibility.

To add printers:
1. Access the CUPS web interface at http://<your-ip>:631
2. Go to Administration > Add Printer
3. Select your printer and configure it
4. The printer configuration will be saved to printers.conf in this directory
READMEEOF
if [ -f /config/cups/config/README.txt ]; then
    log_debug "README.txt created successfully in /config/cups/config"
else
    log_warn "Failed to create README.txt in /config/cups/config"
fi

# List files in /data/cups/config to verify they exist (debug only)
log_debug "Files in /data/cups/config:"
ls -la /data/cups/config/ 2>/dev/null | while read -r line; do
    log_debug "  $line"
done || log_warn "Could not list files in /data/cups/config"

# List files in /config/cups/config to verify symlink works (debug only)
log_debug "Files in /config/cups/config (via symlink):"
ls -la /config/cups/config/ 2>/dev/null | while read -r line; do
    log_debug "  $line"
done || log_warn "Could not list files in /config/cups/config"

# Verify /etc/cups symlink is working correctly
# Since /etc/cups is now a symlink to /config/cups/config, all CUPS writes go to addon_config (visible on host)
if [ -L /etc/cups ] && [ -d /etc/cups ]; then
    link_target=$(readlink /etc/cups)
    if [ "$link_target" = "/config/cups/config" ]; then
        log_debug "/etc/cups symlink verified - all CUPS writes go to /config/cups/config (visible on host)"
        # Verify printers.conf is accessible through the symlink
        if [ -f /etc/cups/printers.conf ] && [ -r /etc/cups/printers.conf ]; then
            log_debug "Printers configuration accessible through /etc/cups symlink"
        fi
    else
        log_error "/etc/cups symlink points to wrong location: $link_target (expected /config/cups/config)"
        exit 1
    fi
else
    log_error "/etc/cups symlink not properly created"
    exit 1
fi

# Verify ZJ-58 driver installation
log_debug "Verifying ZJ-58 thermal printer driver installation..."
if [ -f /usr/lib/cups/filter/rastertozj ] && [ -f /usr/share/cups/model/zjiang/ZJ-58.ppd ]; then
    log_debug "ZJ-58 driver found: filter and PPD installed"
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
# PPDs are stored in persistent location and only downloaded if missing or URL changed
PPD_URLS_ENV="${PPD_URLS:-[]}"
if [ "$PPD_URLS_ENV" != "[]" ] && [ -n "$PPD_URLS_ENV" ]; then
    log_info "PPD URLs configured, checking for downloads/updates..."
    
    # Original PPD files are in /config/cups/ppds (visible on host)
    # Create symlink from /data/cups/ppds to /config/cups/ppds
    if [ -d /data/cups/ppds ] && [ ! -L /data/cups/ppds ]; then
        # If /data/cups/ppds is a directory, remove it (files already migrated earlier)
        rm -rf /data/cups/ppds
    fi
    if [ ! -L /data/cups/ppds ]; then
        ln -sf /config/cups/ppds /data/cups/ppds
        log_debug "Created /data/cups/ppds symlink to /config/cups/ppds"
    fi
    
    # Create symlink from CUPS model directory to /config/cups/ppds
    # First, migrate any preinstalled PPDs from Docker image to /config
    if [ -d /usr/share/cups/model/openprinting ] && [ ! -L /usr/share/cups/model/openprinting ]; then
        if [ "$(ls -A /usr/share/cups/model/openprinting 2>/dev/null)" ]; then
            log_debug "Migrating preinstalled PPDs from image to /config/cups/ppds..."
            for ppd_file in /usr/share/cups/model/openprinting/*.ppd; do
                if [ -f "$ppd_file" ]; then
                    ppd_name=$(basename "$ppd_file")
                    if [ ! -f "/config/cups/ppds/$ppd_name" ]; then
                        cp "$ppd_file" "/config/cups/ppds/$ppd_name"
                        log_debug "Migrated preinstalled PPD: $ppd_name to /config/cups/ppds"
                    fi
                fi
            done
        fi
        rm -rf /usr/share/cups/model/openprinting
    fi
    
    if [ ! -L /usr/share/cups/model/openprinting ]; then
        ln -sf /config/cups/ppds /usr/share/cups/model/openprinting
        log_debug "Created symlink from /usr/share/cups/model/openprinting to /config/cups/ppds"
    fi
    
    download_count=0
    skip_count=0
    error_count=0
    update_count=0
    
    # Create metadata file to track downloads (in /config, original location)
    metadata_file="/config/cups/ppds/.ppd_metadata"
    touch "$metadata_file"
    
    # Parse PPD URLs from JSON array format
    # Extract URLs from JSON array: ["url1", "url2"] -> url1, url2
    log_debug "PPD_URLS_ENV = $PPD_URLS_ENV"
    log_debug "Extracting URLs from JSON array..."
    
    # Store URLs in a temporary file to avoid subshell issues with counters
    url_list_file="/tmp/ppd_urls_$$"
    echo "$PPD_URLS_ENV" | grep -oE 'https?://[^"]+' > "$url_list_file" || true
    
    log_debug "Found $(wc -l < "$url_list_file" | tr -d ' ') URL(s) to process"
    
    while read -r url; do
        if [ -n "$url" ]; then
            filename=$(basename "$url" | sed 's/[?&].*//')
            # Ensure filename ends with .ppd
            if [ "${filename##*.}" != "ppd" ]; then
                filename="${filename}.ppd"
            fi
            persistent_file="/config/cups/ppds/$filename"
            temp_file="/tmp/${filename}.$$"
            
            log_debug "Processing PPD: $filename"
            log_debug "  URL: $url"
            log_debug "  Persistent file: $persistent_file"
            log_debug "  Temp file: $temp_file"
            
            # Check if file already exists and URL matches
            existing_url=$(grep "^${filename}:" "$metadata_file" 2>/dev/null | cut -d':' -f2-)
            
            log_debug "  Existing URL in metadata: ${existing_url:-none}"
            log_debug "  File exists: $([ -f "$persistent_file" ] && echo 'yes' || echo 'no')"
            
            if [ -f "$persistent_file" ] && [ "$existing_url" = "$url" ]; then
                # File exists and URL matches - validate it's still good
                if validate_ppd "$persistent_file"; then
                    file_size=$(stat -c%s "$persistent_file" 2>/dev/null || echo "0")
                    log_info "PPD already exists and is valid: $filename (${file_size} bytes, skipping download)"
                    skip_count=$((skip_count + 1))
                    continue
                else
                    log_warn "Existing PPD file is invalid, re-downloading: $filename"
                fi
            elif [ -f "$persistent_file" ] && [ -n "$existing_url" ] && [ "$existing_url" != "$url" ]; then
                log_info "URL changed for $filename, updating..."
                update_count=$((update_count + 1))
            fi
            
            log_info "Downloading PPD: $filename from $url"
            
            # Download to temporary file first
            if curl -f -L -s -o "$temp_file" "$url"; then
                temp_size=$(stat -c%s "$temp_file" 2>/dev/null || echo "0")
                log_debug "Downloaded $temp_size bytes to temp file"
                log_debug "First 3 lines of downloaded file:"
                head -n 3 "$temp_file" | while read -r line; do
                    log_debug "  $line"
                done
                
                # Validate that it's a valid PPD file
                if validate_ppd "$temp_file"; then
                    if mv "$temp_file" "$persistent_file"; then
                        chmod 644 "$persistent_file"
                        final_size=$(stat -c%s "$persistent_file" 2>/dev/null || echo "0")
                        
                        # Update metadata file
                        grep -v "^${filename}:" "$metadata_file" > "${metadata_file}.tmp" 2>/dev/null || true
                        echo "${filename}:${url}:$(date +%s)" >> "${metadata_file}.tmp"
                        mv "${metadata_file}.tmp" "$metadata_file"
                        
                        log_info "Successfully downloaded and validated: $filename (${final_size} bytes)"
                        log_debug "  - Stored in: $persistent_file (original file in addon_config)"
                        log_debug "  - Host path: /addon_configs/{REPO}_extended_cups/cups/ppds/$filename"
                        download_count=$((download_count + 1))
                    else
                        log_error "Failed to move validated PPD file: $filename"
                        rm -f "$temp_file"
                        error_count=$((error_count + 1))
                    fi
                else
                    rm -f "$temp_file"
                    log_error "Rejected invalid PPD file from $url - file does not appear to be a valid PPD file"
                    log_debug "File header (first 5 lines):"
                    head -n 5 "$temp_file" 2>/dev/null | while read -r line; do
                        log_debug "  $line"
                    done
                    error_count=$((error_count + 1))
                fi
            else
                curl_exit_code=$?
                log_error "Failed to download PPD from $url (curl exit code: $curl_exit_code)"
                log_debug "Attempting verbose curl to diagnose issue..."
                curl -v -L "$url" -o /dev/null 2>&1 | head -n 20 | while read -r line; do
                    log_debug "  $line"
                done
                error_count=$((error_count + 1))
            fi
        fi
    done < "$url_list_file"
    rm -f "$url_list_file"
    
    log_info "PPD download process completed: $download_count downloaded, $update_count updated, $skip_count skipped, $error_count errors"
else
    log_debug "No additional PPD URLs configured, checking for preinstalled PPDs..."
    # Migrate preinstalled PPDs even if no URLs are configured
    if [ -d /usr/share/cups/model/openprinting ] && [ ! -L /usr/share/cups/model/openprinting ]; then
        if [ "$(ls -A /usr/share/cups/model/openprinting 2>/dev/null)" ]; then
            log_debug "Migrating preinstalled PPDs from image to /config/cups/ppds..."
            for ppd_file in /usr/share/cups/model/openprinting/*.ppd; do
                if [ -f "$ppd_file" ]; then
                    ppd_name=$(basename "$ppd_file")
                    if [ ! -f "/config/cups/ppds/$ppd_name" ]; then
                        cp "$ppd_file" "/config/cups/ppds/$ppd_name"
                        log_debug "Migrated preinstalled PPD: $ppd_name to /config/cups/ppds"
                    fi
                fi
            done
        fi
        rm -rf /usr/share/cups/model/openprinting
    fi
    # Create symlink for preinstalled PPDs
    if [ ! -L /usr/share/cups/model/openprinting ]; then
        ln -sf /config/cups/ppds /usr/share/cups/model/openprinting
        log_debug "Created symlink from /usr/share/cups/model/openprinting to /config/cups/ppds"
    fi
    
    # Also create /data/cups/ppds symlink to /config/cups/ppds
    if [ -d /data/cups/ppds ] && [ ! -L /data/cups/ppds ]; then
        rm -rf /data/cups/ppds
    fi
    if [ ! -L /data/cups/ppds ]; then
        ln -sf /config/cups/ppds /data/cups/ppds
        log_debug "Created /data/cups/ppds symlink to /config/cups/ppds"
    fi
fi

# Verify PPD directory setup
log_debug "Verifying PPD directory setup..."
if [ -d /config/cups/ppds ]; then
    # Count and list PPD files (original files in /config)
    ppd_count=$(find /config/cups/ppds -maxdepth 1 -name "*.ppd" -type f 2>/dev/null | wc -l | tr -d ' ')
    log_info "Found $ppd_count PPD file(s) in /config/cups/ppds"
    
    if [ "$ppd_count" -gt 0 ]; then
        log_debug "PPD files available:"
        for ppd in /config/cups/ppds/*.ppd; do
            if [ -f "$ppd" ]; then
                ppd_name=$(basename "$ppd")
                if [ "$ppd_name" != ".ppd_metadata" ]; then
                    size=$(stat -c%s "$ppd" 2>/dev/null || echo "0")
                    log_debug "  ✓ $ppd_name (${size} bytes)"
                fi
            fi
        done
    fi
    
    # Verify symlinks work
    if [ -L /data/cups/ppds ] && [ -d /data/cups/ppds ]; then
        log_debug "PPD directory symlink verified: /data/cups/ppds -> $(readlink /data/cups/ppds)"
    fi
    if [ -L /usr/share/cups/model/openprinting ] && [ -d /usr/share/cups/model/openprinting ]; then
        log_debug "CUPS model directory symlink verified: /usr/share/cups/model/openprinting -> $(readlink /usr/share/cups/model/openprinting)"
    fi
    log_debug "PPD files accessible on host at: /addon_configs/{REPO}_extended_cups/cups/ppds/"
else
    log_warn "/config/cups/ppds directory does not exist"
fi

# Ensure USB devices are accessible
log_debug "Setting up USB device access..."
if mkdir -p /dev/bus/usb; then
    log_debug "USB device directory ready"
    # Check if USB devices are accessible
    if [ -d /dev/bus/usb ] && [ -r /dev/bus/usb ]; then
        log_debug "USB backend should be functional"
    else
        log_warn "USB device directory may not be accessible - USB printers may not be detected"
    fi
else
    log_error "Failed to create USB device directory"
fi

# Start Avahi daemon for mDNS/Bonjour printer discovery
log_debug "Setting up Avahi daemon for automatic printer discovery..."
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
        log_debug "Created Avahi daemon configuration"
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
    log_info "CUPS daemon found, ready to start service"
    # Verify /etc/cups symlink is correct (CUPS will use default /etc/cups location)
    if [ -L /etc/cups ] && [ "$(readlink /etc/cups)" = "/config/cups/config" ]; then
        log_debug "CUPS will write to /etc/cups (mapped to /config/cups/config, visible on host via addon_config)"
    else
        log_error "/etc/cups symlink is not correctly configured (expected -> /config/cups/config)"
        exit 1
    fi
else
    log_error "CUPS daemon not found at /usr/sbin/cupsd"
    exit 1
fi

# Final PPD verification summary (debug only)
log_debug "=== PPD Download and Storage Summary ==="
if [ -d /config/cups/ppds ]; then
    total_ppds=$(find /config/cups/ppds -maxdepth 1 -name "*.ppd" -type f 2>/dev/null | wc -l | tr -d ' ')
    log_debug "Total PPD files in /config/cups/ppds (original files in addon_config): $total_ppds"
    log_debug "PPD files accessible on host at: /addon_configs/{REPO}_extended_cups/cups/ppds/"
    
    if [ "$total_ppds" -gt 0 ]; then
        log_debug "PPD files available:"
        for ppd in /config/cups/ppds/*.ppd; do
            if [ -f "$ppd" ]; then
                ppd_name=$(basename "$ppd")
                if [ "$ppd_name" != ".ppd_metadata" ]; then
                    size=$(stat -c%s "$ppd" 2>/dev/null || echo "0")
                    log_debug "  ✓ $ppd_name (${size} bytes)"
                fi
            fi
        done
    fi
    
    # Verify symlinks
    if [ -L /data/cups/ppds ]; then
        log_debug "Symlink verified: /data/cups/ppds -> $(readlink /data/cups/ppds)"
    fi
    if [ -L /usr/share/cups/model/openprinting ]; then
        log_debug "Symlink verified: /usr/share/cups/model/openprinting -> $(readlink /usr/share/cups/model/openprinting)"
    fi
else
    log_warn "/config/cups/ppds directory does not exist"
fi
log_debug "========================================="

# Copy logs to /config for visibility if debug mode
if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
    log_debug "Creating logs directory in /config for visibility..."
    mkdir -p /config/logs
    # Create a symlink or copy mechanism for logs
    if [ -d /data/cups/logs ]; then
        log_debug "CUPS logs available in /data/cups/logs"
        log_debug "To view logs, check addon logs in Home Assistant UI"
    fi
fi

log_info "Initialization complete!"
log_info "Automatic printer discovery enabled:"
log_info "  - USB printers: Auto-detected via USB backend"
log_info "  - Network printers: Auto-discovered via mDNS/Bonjour (Avahi)"
log_info "  - Printer configurations: Persisted in /data/cups/config (visible via /config/cups/config)"
log_info "  - PPD files: Original files in /config/cups/ppds (visible on host via addon_config)"
log_info "  - Configuration files: Linked via symlinks (always up-to-date automatically)"
if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
    log_info "  - Debug mode: ENABLED - Check logs for detailed information"
fi
log_info "Services starting:"
log_info "  - CUPS daemon (port 631)"
log_info "  - Configuration files linked via symlinks (always up-to-date automatically)"
