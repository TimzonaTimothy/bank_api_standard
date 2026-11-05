#!/bin/sh

set -eu
umask 077

BACKUP_DIR=${BACKUP_DIR:-/backups}

configure_database() {
    : "${POSTGRES_DB:?POSTGRES_DB must be set}"
    : "${POSTGRES_USER:?POSTGRES_USER must be set}"
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
    PGHOST=${POSTGRES_HOST:-/var/run/postgresql}
    PGPORT=${POSTGRES_PORT:-5432}
    PGUSER=$POSTGRES_USER
    PGPASSWORD=$POSTGRES_PASSWORD
    export PGHOST PGPORT PGUSER PGPASSWORD
}
