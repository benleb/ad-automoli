FROM python:3.8-alpine

# API Port
EXPOSE 5050

# Mountpoints for configuration & certificates
VOLUME /conf
VOLUME /certs

# Copy appdaemon into image
WORKDIR /usr/src/app

# Install additional packages
RUN apk add --no-cache curl tzdata gcc libffi-dev openssl-dev musl-dev

# Install appdaemon
RUN pip install --no-cache-dir --upgrade appdaemon

# bootstrap appdaemon
RUN mkdir -p conf/apps/
# add patched default configuration
COPY demo/automoli.apps.yaml conf/apps/apps.yaml.example
COPY demo/automoli.appdaemon.yaml conf/appdaemon.yaml.example

# add AutoMoLi
COPY apps/automoli conf/apps/automoli

# patch appdaemon startup script with new env vars & show config on startup
RUN sed -i '44i\\n# AutoMoLi: env variable configuration\nif [ -n "$AUTOMOLI_ROOM" ]; then sed -i \"s/kitchen/$(echo $AUTOMOLI_ROOM | sed "s/[^[:print:]]//g")/\" $CONF/apps/apps.yaml; fi' /usr/src/app/dockerStart.sh && \
    sed -i '47i# AutoMoLi: show config on st

# Start script
RUN chmod +x /usr/src/app/dockerStart.sh
ENTRYPOINT ["./dockerStart.sh"]
