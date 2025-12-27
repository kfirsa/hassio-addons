ARG BUILD_FROM
FROM $BUILD_FROM

# Add env
ENV LANG=C.UTF-8
# Set CUPS environment variables for data persistence
ENV CUPS_DATADIR=/data/cups
ENV CUPS_CACHEDIR=/data/cups/cache
ENV CUPS_LOGDIR=/data/cups/logs
ENV CUPS_STATEDIR=/data/cups/state
ENV CUPS_SERVERROOT=/data/cups/config

# Setup base
RUN \
    echo "http://dl-cdn.alpinelinux.org/alpine/v$(cat /etc/alpine-release | cut -d'.' -f1,2)/main" > /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v$(cat /etc/alpine-release | cut -d'.' -f1,2)/community" >> /etc/apk/repositories && \
    apk update && \
    apk add --no-cache \
        cups \
        cups-filters \
        ghostscript \
        libjpeg-turbo \
        net-snmp \
        epson-inkjet-printer-escpr \
        usbutils \
        libusb \
        curl \
        gcc \
        make \
        g++ \
        musl-dev \
        cups-dev \
        cups-filters-dev

# Build ZJ-58 thermal printer driver
# Original driver by Aleksey N. Vinogradov (2014)
# Based on: https://github.com/klirichek/zj-58
# Copy driver source files
COPY drivers/zj-58/ /tmp/zj-58/
WORKDIR /tmp/zj-58
# Fix musl libc compatibility: add portable signal handler type definition
# This is done at build time without modifying the original source files
RUN sed -i '/#include <signal.h>/a\\n// Portable signal handler type for musl libc compatibility\ntypedef void (*__sighandler_t)(int);' rastertozj.c && \
    make && \
    cp rastertozj /usr/lib/cups/filter/ && \
    chmod 755 /usr/lib/cups/filter/rastertozj && \
    mkdir -p /usr/share/cups/model/zjiang && \
    cp ZJ-58.ppd /usr/share/cups/model/zjiang/ && \
    make clean && \
    rm -rf /tmp/zj-58

# Preinstall popular printer PPD files
# These are commonly used printers that users frequently need
RUN mkdir -p /usr/share/cups/model/openprinting && \
    echo "Preinstalling popular printer PPD files..." && \
    # HP LaserJet 1020 (very popular)
    curl -f -L -s -o /usr/share/cups/model/openprinting/hp-laserjet_1020.ppd \
        "https://www.openprinting.org/download/PPD/HP/hp-laserjet_1020.ppd" || true && \
    # HP LaserJet P1005
    curl -f -L -s -o /usr/share/cups/model/openprinting/hp-laserjet_p1005.ppd \
        "https://www.openprinting.org/download/PPD/HP/hp-laserjet_p1005.ppd" || true && \
    # Brother QL-800 (thermal label printer)
    curl -f -L -s -o /usr/share/cups/model/openprinting/brother-ql800.ppd \
        "https://www.openprinting.org/download/PPD/Brother/brother-ql800.ppd" || true && \
    # Brother HL-2270DW
    curl -f -L -s -o /usr/share/cups/model/openprinting/brother-hl2270dw.ppd \
        "https://www.openprinting.org/download/PPD/Brother/brother-hl2270dw.ppd" || true && \
    # Canon PIXMA MP250
    curl -f -L -s -o /usr/share/cups/model/openprinting/canon-pixma_mp250.ppd \
        "https://www.openprinting.org/download/PPD/Canon/canon-pixma_mp250.ppd" || true && \
    # Epson Stylus Photo R2000
    curl -f -L -s -o /usr/share/cups/model/openprinting/epson-stylus_photo_r2000.ppd \
        "https://www.openprinting.org/download/PPD/Epson/epson-stylus_photo_r2000.ppd" || true && \
    echo "Popular PPD files preinstalled (some may have failed if URLs changed)"

# Remove build dependencies to minimize image size
RUN apk del gcc make g++ musl-dev cups-dev cups-filters-dev

# Copy data
COPY rootfs /

# Expose CUPS web interface port
EXPOSE 631

HEALTHCHECK \
    CMD lpstat -r || exit 1