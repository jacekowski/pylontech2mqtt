# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt

# Copy root filesystem
COPY rootfs /

RUN chmod +x /usr/bin/run.sh


