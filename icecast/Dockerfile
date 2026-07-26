ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8

RUN \
    apk add --no-cache \
        icecast \
        nginx

COPY rootfs /

RUN chmod a+x /etc/cont-init.d/* /etc/services.d/*/* 2>/dev/null || true

EXPOSE 8000 8099
