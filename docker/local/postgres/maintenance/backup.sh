#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

if [ "$#" -ne 0 ]; then
    printf 'Usage: backup.sh\n' >&2
    exit 1
fi
configure_database
mkdir -p "$BACKUP_DIR"
temporary_file=$(mktemp "$BACKUP_DIR/.backup_$(date -u +%Y%m%dT%H%M%SZ)_XXXXXX")
trap 'rm -f "$temporary_file"' EXIT
trap 'exit 1' HUP INT TERM

pg_dump --format=custom --no-owner --no-privileges \
    --dbname="$POSTGRES_DB" --file="$temporary_file"
backup_file="$BACKUP_DIR/$(basename "$temporary_file" | cut -c 2-).dump"
mv "$temporary_file" "$backup_file"
printf 'Backup created: %s\n' "$backup_file"
