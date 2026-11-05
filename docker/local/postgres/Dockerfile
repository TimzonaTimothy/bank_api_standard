FROM docker.io/postgres:16-bullseye

COPY ./docker/local/postgres/maintenance /usr/local/bin/maintenance
RUN chmod +x /usr/local/bin/maintenance/*.sh && \
    mkdir -p /backups && chmod 700 /backups
