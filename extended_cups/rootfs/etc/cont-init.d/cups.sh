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

# Check if debug mode is enabled
DEBUG_MODE="${DEBUG:-false}"
if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
    set -x  # Enable debug output
    log_info "DEBUG MODE ENABLED - Verbose logging activated"
fi

# Create CUPS data directories for persistence
# /data is the standard persistent storage volume in Home Assistant addons
# addon_config:rw maps to /config in container and /addon_configs/{REPO}_{slug} on host
log_info "Creating CUPS data directories in persistent storage..."
if mkdir -p /data/cups/cache /data/cups/logs /data/cups/state /data/cups/config /data/cups/ppds; then
    log_info "CUPS data directories created successfully in /data/cups"
    
    # Also create directories in /config for addon_config mapping (user-accessible)
    # This makes files visible in /addon_configs/{REPO}_extended_cups on the host
    # Note: We create actual directories (not symlinks) because symlinks may not
    # work properly across the addon_config mount boundary
    if mkdir -p /config/cups/config /config/cups/ppds; then
        log_info "Created directories in /config for addon_config mapping"
        log_info "Files in /config will be visible at /addon_configs/{REPO}_extended_cups/ on host"
    else
        log_warn "Failed to create directories in /config"
    fi
    
    # Verify directories exist and show their locations
    log_info "Persistent storage locations:"
    log_info "  - /data/cups/config (primary persistent storage)"
    log_info "  - /config/cups/config (accessible via /addon_configs/{REPO}_extended_cups/cups/config on host)"
    log_info "  - /data/cups/ppds (PPD files storage)"
    log_info "  - /config/cups/ppds (accessible via /addon_configs/{REPO}_extended_cups/cups/ppds on host)"
    
    # Create marker files to ensure directories are visible
    echo "# CUPS Persistent Storage" > /data/cups/.persistent_storage_marker
    echo "# This directory contains CUPS configuration and data" >> /data/cups/.persistent_storage_marker
    echo "# Created: $(date)" >> /data/cups/.persistent_storage_marker
    
    # Also create marker in /config for addon_config visibility
    if [ -d /config ]; then
        mkdir -p /config
        echo "# CUPS Configuration (accessible via /addon_configs)" > /config/.addon_config_marker 2>/dev/null || true
        echo "# Created: $(date)" >> /config/.addon_config_marker 2>/dev/null || true
        log_info "Created marker file in /config for addon_config visibility"
    fi
    
    # Verify we can write to the persistent location
    if touch /data/cups/.write_test 2>/dev/null && rm -f /data/cups/.write_test 2>/dev/null; then
        log_info "Verified write access to persistent storage"
    else
        log_warn "Warning: May not have write access to persistent storage"
    fi
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

# Make /etc/cups a symlink to persistent location
# This ensures ALL CUPS writes go directly to persistent storage
log_info "Setting up CUPS configuration directory..."
if [ -d /etc/cups ] && [ ! -L /etc/cups ]; then
    # If /etc/cups exists as a directory, move any existing files to persistent location
    log_info "Migrating existing /etc/cups files to persistent location..."
    if [ -f /etc/cups/printers.conf ]; then
        cp /etc/cups/printers.conf /data/cups/config/printers.conf 2>/dev/null || true
        log_info "Migrated printers.conf to persistent location"
    fi
    if [ -f /etc/cups/cupsd.conf ]; then
        # Only copy if our persistent one doesn't exist
        if [ ! -f /data/cups/config/cupsd.conf ]; then
            cp /etc/cups/cupsd.conf /data/cups/config/cupsd.conf 2>/dev/null || true
        fi
    fi
    # Remove the directory
    rm -rf /etc/cups
    log_info "Removed /etc/cups directory for symlink creation"
fi

# Create symlink from /etc/cups to persistent location
# This ensures CUPS writes directly to persistent storage
if [ ! -L /etc/cups ]; then
    ln -sf /data/cups/config /etc/cups
    log_info "Created /etc/cups symlink to persistent location"
else
    # Verify the symlink points to the correct location
    current_link=$(readlink /etc/cups)
    if [ "$current_link" != "/data/cups/config" ]; then
        log_warn "Existing /etc/cups symlink points to $current_link, recreating..."
        rm -f /etc/cups
        ln -sf /data/cups/config /etc/cups
        log_info "Recreated /etc/cups symlink to persistent location"
    else
        log_info "/etc/cups symlink already points to persistent location"
    fi
fi

# Verify the symlink works
if [ -L /etc/cups ] && [ -d /etc/cups ]; then
    log_info "CUPS configuration directory symlink verified"
else
    log_error "Failed to create /etc/cups symlink"
    exit 1
fi

# Basic CUPS configuration without admin authentication
# Note: We don't set ServerRoot here - CUPS will use default /etc/cups
# Since /etc/cups is a symlink to /data/cups/config, all writes persist automatically
log_info "Generating CUPS configuration file..."
cat > /data/cups/config/cupsd.conf << EOL
# Note: ServerRoot defaults to /etc/cups
# Since /etc/cups is symlinked to /data/cups/config (persistent storage),
# all CUPS configuration files will automatically persist across restarts

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

if [ -f /data/cups/config/cupsd.conf ]; then
    log_info "CUPS configuration file created successfully at /data/cups/config/cupsd.conf"
    # Create symlink in /config so it's visible in addon_config directory
    if [ -f /config/cups/config/cupsd.conf ] && [ ! -L /config/cups/config/cupsd.conf ]; then
        rm -f /config/cups/config/cupsd.conf
    fi
    if ln -sf /data/cups/config/cupsd.conf /config/cups/config/cupsd.conf 2>/dev/null; then
        log_info "Created symlink: /config/cups/config/cupsd.conf -> /data/cups/config/cupsd.conf"
    else
        log_warn "Failed to create symlink for cupsd.conf (files may not be visible in addon_config)"
    fi
else
    log_error "Failed to create CUPS configuration file"
    exit 1
fi

# Initialize printers.conf in persistent location if it doesn't exist
# This ensures printer configurations persist across restarts and upgrades
log_info "Initializing printers configuration file in persistent storage..."
if [ ! -f /data/cups/config/printers.conf ]; then
    if touch /data/cups/config/printers.conf && chown root:lp /data/cups/config/printers.conf && chmod 640 /data/cups/config/printers.conf; then
        log_info "Created new printers.conf in persistent location: /data/cups/config/printers.conf"
    else
        log_error "Failed to create printers.conf in persistent location"
        exit 1
    fi
else
    log_info "Existing printers.conf found in persistent location"
    # Show file size to verify it has content
    file_size=$(stat -c%s /data/cups/config/printers.conf 2>/dev/null || echo "0")
    if [ "$file_size" -gt 0 ]; then
        log_info "Printers configuration file contains data ($file_size bytes)"
    else
        log_info "Printers configuration file is empty (no printers configured yet)"
    fi
fi

# Create symlink from /config to /data for printers.conf
# Remove existing file if it's not a symlink
if [ -f /config/cups/config/printers.conf ] && [ ! -L /config/cups/config/printers.conf ]; then
    rm -f /config/cups/config/printers.conf
    log_info "Removed existing printers.conf file (will create symlink instead)"
fi
# Create symlink
if ln -sf /data/cups/config/printers.conf /config/cups/config/printers.conf 2>/dev/null; then
    log_info "Created symlink: /config/cups/config/printers.conf -> /data/cups/config/printers.conf"
    log_info "  (Host path: /config/addon_configs/{REPO}_extended_cups/cups/config/printers.conf)"
else
    log_warn "Failed to create symlink for printers.conf"
fi

# Create a README file in /config/cups/config to help users understand the directory structure
# This file will be visible in /addon_configs/{REPO}_extended_cups/cups/config/ on the host
log_info "Creating README file in /config/cups/config for user reference..."
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
    log_info "README.txt created successfully in /config/cups/config"
else
    log_warn "Failed to create README.txt in /config/cups/config"
fi

# List files in /data/cups/config to verify they exist
log_info "Files in /data/cups/config:"
ls -la /data/cups/config/ 2>/dev/null | while read -r line; do
    log_info "  $line"
done || log_warn "Could not list files in /data/cups/config"

# List files in /config/cups/config to verify symlink works
log_info "Files in /config/cups/config (via symlink):"
ls -la /config/cups/config/ 2>/dev/null | while read -r line; do
    log_info "  $line"
done || log_warn "Could not list files in /config/cups/config"

# Verify /etc/cups symlink is working correctly
# Since /etc/cups is now a symlink to /data/cups/config, all CUPS writes go to persistent storage
if [ -L /etc/cups ] && [ -d /etc/cups ]; then
    link_target=$(readlink /etc/cups)
    if [ "$link_target" = "/data/cups/config" ]; then
        log_info "/etc/cups symlink verified - all CUPS writes will persist"
        # Verify printers.conf is accessible through the symlink
        if [ -f /etc/cups/printers.conf ] && [ -r /etc/cups/printers.conf ]; then
            log_info "Printers configuration accessible through /etc/cups symlink"
        fi
    else
        log_error "/etc/cups symlink points to wrong location: $link_target"
        exit 1
    fi
else
    log_error "/etc/cups symlink not properly created"
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
# PPDs are stored in persistent location and only downloaded if missing or URL changed
PPD_URLS_ENV="${PPD_URLS:-[]}"
if [ "$PPD_URLS_ENV" != "[]" ] && [ -n "$PPD_URLS_ENV" ]; then
    log_info "PPD URLs configured, checking for downloads/updates..."
    
    # Create persistent directory for downloaded PPDs
    if mkdir -p /data/cups/ppds; then
        log_info "Persistent PPD directory ready"
    else
        log_error "Failed to create persistent PPD directory"
    fi
    
    # Create symlink from CUPS model directory to persistent location
    # First, migrate any preinstalled PPDs from Docker image to persistent location
    if [ -d /usr/share/cups/model/openprinting ] && [ ! -L /usr/share/cups/model/openprinting ]; then
        if [ "$(ls -A /usr/share/cups/model/openprinting 2>/dev/null)" ]; then
            log_info "Migrating preinstalled PPDs from image to persistent location..."
            for ppd_file in /usr/share/cups/model/openprinting/*.ppd; do
                if [ -f "$ppd_file" ]; then
                    ppd_name=$(basename "$ppd_file")
                    if [ ! -f "/data/cups/ppds/$ppd_name" ]; then
                        cp "$ppd_file" "/data/cups/ppds/$ppd_name"
                        log_info "Migrated preinstalled PPD: $ppd_name"
                    fi
                fi
            done
        fi
        rm -rf /usr/share/cups/model/openprinting
    fi
    
    if [ ! -L /usr/share/cups/model/openprinting ]; then
        ln -sf /data/cups/ppds /usr/share/cups/model/openprinting
        log_info "Created symlink from /usr/share/cups/model/openprinting to persistent location"
    fi
    
    download_count=0
    skip_count=0
    error_count=0
    update_count=0
    
    # Create metadata file to track downloads
    metadata_file="/data/cups/ppds/.ppd_metadata"
    touch "$metadata_file"
    
    # Parse PPD URLs from JSON array format
    # Extract URLs from JSON array: ["url1", "url2"] -> url1, url2
    if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
        log_info "DEBUG: PPD_URLS_ENV = $PPD_URLS_ENV"
        log_info "DEBUG: Extracting URLs from JSON array..."
    fi
    
    # Store URLs in a temporary file to avoid subshell issues with counters
    url_list_file="/tmp/ppd_urls_$$"
    echo "$PPD_URLS_ENV" | grep -oE 'https?://[^"]+' > "$url_list_file" || true
    
    if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
        log_info "DEBUG: Found $(wc -l < "$url_list_file" | tr -d ' ') URL(s) to process"
    fi
    
    while read -r url; do
        if [ -n "$url" ]; then
            filename=$(basename "$url" | sed 's/[?&].*//')
            # Ensure filename ends with .ppd
            if [ "${filename##*.}" != "ppd" ]; then
                filename="${filename}.ppd"
            fi
            persistent_file="/data/cups/ppds/$filename"
            temp_file="/tmp/${filename}.$$"
            
            if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
                log_info "DEBUG: Processing PPD: $filename"
                log_info "DEBUG:   URL: $url"
                log_info "DEBUG:   Persistent file: $persistent_file"
                log_info "DEBUG:   Temp file: $temp_file"
            fi
            
            # Check if file already exists and URL matches
            existing_url=$(grep "^${filename}:" "$metadata_file" 2>/dev/null | cut -d':' -f2-)
            
            if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
                log_info "DEBUG:   Existing URL in metadata: ${existing_url:-none}"
                log_info "DEBUG:   File exists: $([ -f "$persistent_file" ] && echo 'yes' || echo 'no')"
            fi
            
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
                if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
                    log_info "DEBUG: Downloaded $temp_size bytes to temp file"
                    log_info "DEBUG: First 3 lines of downloaded file:"
                    head -n 3 "$temp_file" | while read -r line; do
                        log_info "DEBUG:   $line"
                    done
                fi
                
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
                        log_info "  - Stored in: $persistent_file"
                        log_info "  - Accessible via symlink at: /config/cups/ppds/$filename"
                        download_count=$((download_count + 1))
                    else
                        log_error "Failed to move validated PPD file: $filename"
                        rm -f "$temp_file"
                        error_count=$((error_count + 1))
                    fi
                else
                    rm -f "$temp_file"
                    log_error "Rejected invalid PPD file from $url - file does not appear to be a valid PPD file"
                    if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
                        log_info "DEBUG: File header (first 5 lines):"
                        head -n 5 "$temp_file" 2>/dev/null | while read -r line; do
                            log_info "DEBUG:   $line"
                        done
                    fi
                    error_count=$((error_count + 1))
                fi
            else
                curl_exit_code=$?
                log_error "Failed to download PPD from $url (curl exit code: $curl_exit_code)"
                if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
                    log_info "DEBUG: Attempting verbose curl to diagnose issue..."
                    curl -v -L "$url" -o /dev/null 2>&1 | head -n 20 | while read -r line; do
                        log_info "DEBUG:   $line"
                    done
                fi
                error_count=$((error_count + 1))
            fi
        fi
    done < "$url_list_file"
    rm -f "$url_list_file"
    
    log_info "PPD download process completed: $download_count downloaded, $update_count updated, $skip_count skipped, $error_count errors"
else
    log_info "No additional PPD URLs configured, checking for preinstalled PPDs..."
    # Migrate preinstalled PPDs even if no URLs are configured
    if [ -d /usr/share/cups/model/openprinting ] && [ ! -L /usr/share/cups/model/openprinting ]; then
        if [ "$(ls -A /usr/share/cups/model/openprinting 2>/dev/null)" ]; then
            log_info "Migrating preinstalled PPDs from image to persistent location..."
            mkdir -p /data/cups/ppds
            for ppd_file in /usr/share/cups/model/openprinting/*.ppd; do
                if [ -f "$ppd_file" ]; then
                    ppd_name=$(basename "$ppd_file")
                    if [ ! -f "/data/cups/ppds/$ppd_name" ]; then
                        cp "$ppd_file" "/data/cups/ppds/$ppd_name"
                        log_info "Migrated preinstalled PPD: $ppd_name"
                    fi
                fi
            done
        fi
        rm -rf /usr/share/cups/model/openprinting
    fi
    # Create symlink for preinstalled PPDs
    if [ ! -L /usr/share/cups/model/openprinting ]; then
        mkdir -p /data/cups/ppds
        ln -sf /data/cups/ppds /usr/share/cups/model/openprinting
    fi
fi

# Create symlink from /config/cups/ppds to /data/cups/ppds for visibility
# This ensures all PPDs are visible in addon_config via symlink
log_info "Creating symlink for PPD directory visibility..."
if [ -d /data/cups/ppds ]; then
    # Remove existing directory if it's not a symlink
    if [ -d /config/cups/ppds ] && [ ! -L /config/cups/ppds ]; then
        rm -rf /config/cups/ppds
        log_info "Removed existing /config/cups/ppds directory (will create symlink instead)"
    fi
    
    # Create symlink
    if [ ! -L /config/cups/ppds ]; then
        if ln -sf /data/cups/ppds /config/cups/ppds 2>/dev/null; then
            log_info "Created symlink: /config/cups/ppds -> /data/cups/ppds"
        else
            log_warn "Failed to create symlink for PPD directory"
        fi
    else
        log_info "PPD directory symlink already exists: /config/cups/ppds -> /data/cups/ppds"
    fi
    
    # Count and list PPD files
    ppd_count=$(find /data/cups/ppds -maxdepth 1 -name "*.ppd" -type f 2>/dev/null | wc -l | tr -d ' ')
    log_info "Found $ppd_count PPD file(s) in /data/cups/ppds (accessible via /config/cups/ppds symlink)"
    
    if [ "$ppd_count" -gt 0 ]; then
        log_info "PPD files available:"
        for ppd in /data/cups/ppds/*.ppd; do
            if [ -f "$ppd" ]; then
                ppd_name=$(basename "$ppd")
                if [ "$ppd_name" != ".ppd_metadata" ]; then
                    size=$(stat -c%s "$ppd" 2>/dev/null || echo "0")
                    log_info "  ✓ $ppd_name (${size} bytes)"
                fi
            fi
        done
    fi
    
    # Verify symlink works
    if [ -L /config/cups/ppds ] && [ -d /config/cups/ppds ]; then
        log_info "PPD directory symlink verified - files accessible at /addon_configs/{REPO}_extended_cups/cups/ppds/"
    else
        log_warn "PPD directory symlink may not be working correctly"
    fi
else
    log_warn "/data/cups/ppds directory does not exist"
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
    # Verify /etc/cups symlink is correct (CUPS will use default /etc/cups location)
    if [ -L /etc/cups ] && [ "$(readlink /etc/cups)" = "/data/cups/config" ]; then
        log_info "CUPS will write to /etc/cups (mapped to persistent /data/cups/config)"
    else
        log_error "/etc/cups symlink is not correctly configured"
        exit 1
    fi
else
    log_error "CUPS daemon not found at /usr/sbin/cupsd"
    exit 1
fi

# Final PPD verification summary
log_info "=== PPD Download and Storage Summary ==="
if [ -d /data/cups/ppds ]; then
    total_ppds=$(find /data/cups/ppds -maxdepth 1 -name "*.ppd" -type f 2>/dev/null | wc -l | tr -d ' ')
    log_info "Total PPD files in persistent storage (/data/cups/ppds): $total_ppds"
    
    if [ -d /config/cups/ppds ]; then
        config_ppds=$(find /config/cups/ppds -maxdepth 1 -name "*.ppd" -type f 2>/dev/null | wc -l | tr -d ' ')
        log_info "Total PPD files in addon_config (/config/cups/ppds): $config_ppds"
        log_info "PPD files accessible at: /addon_configs/{REPO}_extended_cups/cups/ppds/"
        
        if [ "$total_ppds" -gt 0 ]; then
            log_info "PPD files available:"
            for ppd in /data/cups/ppds/*.ppd; do
                if [ -f "$ppd" ]; then
                    ppd_name=$(basename "$ppd")
                    if [ "$ppd_name" != ".ppd_metadata" ]; then
                        size=$(stat -c%s "$ppd" 2>/dev/null || echo "0")
                        if [ -f "/config/cups/ppds/$ppd_name" ]; then
                            log_info "  ✓ $ppd_name (${size} bytes) - available in both locations"
                        else
                            log_warn "  ⚠ $ppd_name (${size} bytes) - missing in /config"
                        fi
                    fi
                fi
            done
        fi
    else
        log_warn "/config/cups/ppds directory does not exist"
    fi
else
    log_warn "/data/cups/ppds directory does not exist"
fi
log_info "========================================="

# Copy logs to /config for visibility if debug mode
if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
    log_info "DEBUG: Creating logs directory in /config for visibility..."
    mkdir -p /config/logs
    # Create a symlink or copy mechanism for logs
    if [ -d /data/cups/logs ]; then
        log_info "DEBUG: CUPS logs available in /data/cups/logs"
        log_info "DEBUG: To view logs, check addon logs in Home Assistant UI"
    fi
fi

log_info "Initialization complete!"
log_info "Automatic printer discovery enabled:"
log_info "  - USB printers: Auto-detected via USB backend"
log_info "  - Network printers: Auto-discovered via mDNS/Bonjour (Avahi)"
log_info "  - Printer configurations: Persisted in /data/cups/config (visible via /config/cups/config)"
log_info "  - PPD files: Persisted in /data/cups/ppds (visible via /config/cups/ppds)"
log_info "  - Configuration files: Linked via symlinks (always up-to-date automatically)"
if [ "$DEBUG_MODE" = "true" ] || [ "$DEBUG_MODE" = "1" ]; then
    log_info "  - Debug mode: ENABLED - Check logs for detailed information"
fi
log_info "Services starting:"
log_info "  - CUPS daemon (port 631)"
log_info "  - Configuration files linked via symlinks (always up-to-date automatically)"
