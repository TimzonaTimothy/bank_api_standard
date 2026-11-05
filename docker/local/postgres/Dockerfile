FROM docker.io/postgres:16-bullseye

RUN apt-get update && apt-get install --no-install-recommends -y gnupg openssh-client && rm -rf /var/lib/apt/lists/*

COPY ./docker/local/postgres/maintenance /usr/local/bin/maintenance
RUN chmod +x /usr/local/bin/maintenance/*.sh && \
    mkdir -p /backups && chmod 700 /backups
