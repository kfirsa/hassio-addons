# Extended CUPS Print Server

A comprehensive CUPS (Common UNIX Printing System) add-on for Home Assistant with support for network printing, USB printers, Gutenprint universal drivers, and built-in thermal printer drivers.

## Features

- **Network Printing**: Support for IPP, LPD, and other network printing protocols
- **USB Printer Support**: Full USB device access for connected printers
- **Gutenprint Drivers**: Universal printer drivers supporting 1000+ printer models (HP, Epson, Brother, Canon, and more)
- **Thermal Printer Support**: Built-in drivers for popular thermal printers
- **PPD File Management**: Download and validate PPD files from OpenPrinting.org
- **Web Interface**: Access CUPS web interface at `http://<your-ha-ip>:631`

## Supported Thermal Printers

### Built-in Support

- **Zjiang ZJ-58**: Full driver support with custom CUPS filter
  - 58mm thermal paper widths
  - Multiple paper length options (74mm, 210mm, 297mm, continuous)
  - Cash drawer control support

### Gutenprint Support

The add-on includes Gutenprint universal drivers, which provide support for many thermal printers including:

- **Brother QL Series** (QL-600, QL-700, QL-800, QL-1100): Label printers
- **Epson TM Series** (TM-M30III, TM-T20III, TM-T88): Receipt printers (may require additional PPD files)
- **Star Micronics TSP Series**: Receipt printers
- **Generic ESC/POS Printers**: Many 58mm/80mm thermal printers

### Popular Home Thermal Printers

The following popular thermal printers are well-supported:

- **Epson TM-M30III**: Compact receipt printer with Wi-Fi/Bluetooth
- **Epson TM-T20III**: Economical receipt printer with USB/Ethernet
- **Star Micronics TSP143**: Versatile receipt printer with USB/Bluetooth
- **HPRT HM-A200U**: Portable thermal printer with Bluetooth
- **Brother QL Series**: Label printers for home organization

**Note**: Some Epson TM series printers may require downloading drivers from Epson's official website. Gutenprint provides basic support, but for full functionality, you may need to add manufacturer-specific PPD files.

## Installation

1. Add this repository to Home Assistant:
   - Go to **Supervisor** → **Add-on Store** → **Repositories**
   - Add: `https://github.com/kfirsa/hassio-addons`
2. Install **Extended CUPS Print Server** from the add-on store
3. Configure the add-on (see Configuration below)
4. Start the add-on

## Configuration

### Basic Options

- `admin_username`: CUPS web interface username (default: "admin")
- `admin_password`: CUPS web interface password (default: "admin")
- `ppd_urls`: List of PPD file URLs to download from OpenPrinting.org

### Example Configuration

```yaml
admin_username: "admin"
admin_password: "your-secure-password"
ppd_urls:
  - "https://www.openprinting.org/download/PPD/HP/hp-laserjet_1020.ppd"
  - "https://www.openprinting.org/download/PPD/Brother/brother-ql800.ppd"
  - "https://www.openprinting.org/download/PPD/Epson/epson-tm-t20iii.ppd"
```

### Adding PPD Files

1. Find your printer's PPD file on [OpenPrinting.org](https://www.openprinting.org/download/PPD/)
2. Copy the direct download URL
3. Add it to the `ppd_urls` list in the add-on configuration
4. Save and restart the add-on

The add-on will automatically:
- Download the PPD file
- Validate it (ensuring it's a valid PPD file)
- Install it to `/usr/share/cups/model/openprinting/`
- Log any errors or failures

## Usage

### Accessing CUPS Web Interface

1. Open your browser and navigate to: `http://<your-ha-ip>:631`
2. Log in with your configured `admin_username` and `admin_password`
3. Go to **Administration** → **Add Printer**
4. Select your printer (USB or network)
5. Choose the appropriate driver:
   - For ZJ-58: Select **ZJ-58** or **Zijiang ZJ-58**
   - For other printers: Use Gutenprint drivers or PPD files you've added

### Adding a Thermal Printer

1. Connect your thermal printer via USB to your Home Assistant host
2. Ensure the add-on has USB access enabled (`usb: true` in config)
3. Start the add-on
4. Access CUPS web interface at `http://<your-ha-ip>:631`
5. Go to **Administration** → **Add Printer**
6. Select your USB printer
7. Choose the driver:
   - **ZJ-58 printers**: Select "ZJ-58" or "Zijiang ZJ-58"
   - **Brother QL printers**: Select appropriate Gutenprint driver or PPD
   - **Epson TM printers**: Select Gutenprint driver or add Epson PPD file
   - **Other thermal printers**: Try Gutenprint drivers first

## Troubleshooting

### Printer Not Detected

- **USB Printers**: Ensure the printer is connected and powered on before starting the add-on
- **USB Access**: Verify `usb: true` is set in the add-on configuration
- **Restart**: Try restarting the add-on after connecting a USB printer
- **Check Logs**: Review the add-on logs for detailed error messages

### PPD File Download Failed

- **Invalid URL**: Verify the PPD URL is correct and accessible
- **Network Issues**: Check your Home Assistant's internet connection
- **Validation Failed**: The PPD file may be corrupted or invalid - check the logs
- **Manual Download**: You can manually download PPD files and add them later

### Thermal Printer Not Working

- **Driver Selection**: Ensure you've selected the correct driver in CUPS
- **Gutenprint**: Try selecting a Gutenprint driver if available
- **PPD Files**: For Epson TM series, you may need to download drivers from Epson's website
- **ZJ-58**: Verify you're using the ZJ-58 driver for Zjiang printers

### Can't Access Web Interface

- **Add-on Running**: Ensure the add-on is started
- **Port 631**: Verify port 631 isn't blocked by your firewall
- **Network Access**: Check that your network allows access to the Home Assistant device

## Supported Printer Types

- Network printers (IPP, LPD, etc.)
- USB printers (all types)
- Thermal printers (receipt and label printers)
- Inkjet printers (via Gutenprint)
- Laser printers (via Gutenprint or PPD files)
- Photo printers (via Gutenprint)

## Architecture Support

This add-on supports all Home Assistant architectures:
- `armhf`
- `armv7`
- `aarch64`
- `amd64`
- `i386`

## Credits

- **CUPS**: [Common UNIX Printing System](https://www.cups.org/)
- **Gutenprint**: Universal printer drivers
- **ZJ-58 Driver**: Original driver by Aleksey N. Vinogradov (2014), based on [zj-58](https://github.com/klirichek/zj-58)
- **Home Assistant**: [Home Assistant](https://www.home-assistant.io/)

## License

MIT License - See LICENSE file for details

