#!/usr/bin/with-contenv bash

# Create CUPS data directories for persistence
mkdir -p /data/cups/cache
mkdir -p /data/cups/logs
mkdir -p /data/cups/state
mkdir -p /data/cups/config

# Set proper permissions
chown -R root:lp /data/cups
chmod -R 775 /data/cups

# Create CUPS configuration directory if it doesn't exist
mkdir -p /etc/cups

# Basic CUPS configuration without admin authentication
cat > /data/cups/config/cupsd.conf << EOL
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

# Default settings
DefaultAuthType None
JobSheets none,none
PreserveJobHistory No
EOL

# Create a symlink from the default config location to our persistent location
ln -sf /data/cups/config/cupsd.conf /etc/cups/cupsd.conf
ln -sf /data/cups/config/printers.conf /etc/cups/printers.conf

# Note: ZJ-58 thermal printer driver (rastertozj filter and PPD) is installed
# during image build in /usr/lib/cups/filter/ and /usr/share/cups/model/zjiang/

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
    echo "Downloading additional PPD files..."
    # Create directory for downloaded PPDs
    mkdir -p /usr/share/cups/model/openprinting
    
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
            echo "Downloading PPD: $filename from $url"
            
            # Download to temporary file first
            if curl -f -L -s -o "$temp_file" "$url"; then
                # Validate that it's a valid PPD file
                if validate_ppd "$temp_file"; then
                    mv "$temp_file" "/usr/share/cups/model/openprinting/$filename"
                    echo "Successfully downloaded and validated: $filename"
                else
                    rm -f "$temp_file"
                    echo "ERROR: Rejected invalid PPD file from $url - file does not appear to be a valid PPD file"
                fi
            else
                echo "ERROR: Failed to download PPD from $url"
            fi
        fi
    done
fi

# Ensure USB devices are accessible
# Create USB device directory if it doesn't exist
mkdir -p /dev/bus/usb

# Start CUPS service
/usr/sbin/cupsd -f