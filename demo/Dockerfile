FROM python:3.8-alpine

ARG APPDAEMON_VERSION=dev

# api / admin ui
EXPOSE 5050

# appdaemon mounts
VOLUME /conf
VOLUME /certs

WORKDIR /usr/src/app

# install additional packages
RUN apk add --no-cache curl tzdata

# install appdaemon
RUN apk add --virtual build git gcc libffi-dev openssl-dev musl-dev && \
    git clone https://github.com/AppDaemon/appdaemon.git /usr/src/app && cd /usr/src/app && git checkout ${APPDAEMON_VERSION} && \
    pip install --no-cache-dir . && \
    apk del build

# bootstrap appdaemon
RUN mkdir -p conf/apps/
# add patched default configuration
COPY demo/automoli.apps.yaml conf/apps/apps.yaml.example
COPY demo/automoli.appdaemon.yaml conf/appdaemon.yaml.example

# add AutoMoLi
COPY apps/automoli conf/apps/automoli

# patch appdaemon startup script with new env vars & show config on startup
RUN sed -i '44i\\n# AutoMoLi: env variable configuration\nif [ -n "$AUTOMOLI_ROOM" ]; then sed -i \"s/kitchen/$(echo $AUTOMOLI_ROOM | sed "s/[^[:print:]]//g")/\" $CONF/apps/apps.yaml; fi' /usr/src/app/dockerStart.sh && \
    sed -i '47i# AutoMoLi: show config on startup\necho -e "\\n\\n\\033[1mAutoMoLil\\033[0m configuration in \\033[1m$CONF/apps/apps.yaml\\033[0m:\\n" && cat $CONF/apps/apps.yaml && echo -e "\\n\\n"' /usr/src/app/dockerStart.sh

# Start script
RUN chmod +x /usr/src/app/dockerStart.sh
ENTRYPOINT ["./dockerStart.sh"]
