#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

if [ "$#" -ne 0 ]; then
    printf 'Usage: backup.sh\n' >&2
    exit 1
fi
configure_database
if [ "${BACKUP_ENCRYPTION_REQUIRED:-false}" = true ] && [ -z "${BACKUP_PASSPHRASE_FILE:-}" ]; then
    printf 'BACKUP_PASSPHRASE_FILE is required for encrypted backups.\n' >&2
    exit 1
fi
mkdir -p "$BACKUP_DIR"
temporary_file=$(mktemp "$BACKUP_DIR/.backup_$(date -u +%Y%m%dT%H%M%SZ)_XXXXXX")
encrypted_file=""
trap 'rm -f "$temporary_file"; [ -z "$encrypted_file" ] || rm -f "$encrypted_file"' EXIT
trap 'exit 1' HUP INT TERM

pg_dump --format=custom --no-owner --no-privileges \
    --dbname="$POSTGRES_DB" --file="$temporary_file"
backup_file="$BACKUP_DIR/$(basename "$temporary_file" | cut -c 2-).dump"
if [ -n "${BACKUP_PASSPHRASE_FILE:-}" ]; then
    [ -s "$BACKUP_PASSPHRASE_FILE" ] || { printf 'Missing backup passphrase file\n' >&2; exit 1; }
    encrypted_file=$(mktemp "$BACKUP_DIR/.encrypted_XXXXXX")
    gpg --batch --yes --pinentry-mode loopback --passphrase-file "$BACKUP_PASSPHRASE_FILE" \
        --symmetric --cipher-algo AES256 --compress-algo none --output "$encrypted_file" "$temporary_file"
    backup_file="$backup_file.gpg"
    mv "$encrypted_file" "$backup_file"
else
    mv "$temporary_file" "$backup_file"
fi
printf 'Backup created: %s\n' "$backup_file"
if [ -n "${BACKUP_REMOTE_DEST:-}" ]; then
    "$SCRIPT_DIR/backup-offsite.sh" "$(basename "$backup_file")"
fi
