#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

if [ "$#" -ne 1 ]; then
    printf 'Usage: restore.sh <backup-filename.dump>\n' >&2
    exit 1
fi
case "$1" in
    */*|.*|*[!a-zA-Z0-9_.-]*|"")
        printf 'Provide a backup filename from list-backups.sh, without a directory.\n' >&2
        exit 1
        ;;
    *.dump|*.dump.gpg) ;;
    *) printf 'Backup filename must end in .dump\n' >&2; exit 1 ;;
esac
backup_file="$BACKUP_DIR/$1"
if [ ! -f "$backup_file" ] || [ -L "$backup_file" ]; then
    printf 'Backup not found or not a regular archive: %s\n' "$1" >&2
    exit 1
fi
configure_database
temporary_file=""
trap '[ -z "$temporary_file" ] || rm -f "$temporary_file"' EXIT
trap 'exit 1' HUP INT TERM
case "$backup_file" in
    *.gpg)
        : "${BACKUP_PASSPHRASE_FILE:?Set the backup passphrase file to decrypt this archive}"
        temporary_file=$(mktemp)
        gpg --batch --yes --pinentry-mode loopback --passphrase-file "$BACKUP_PASSPHRASE_FILE" \
            --decrypt --output "$temporary_file" "$backup_file"
        backup_file=$temporary_file
        ;;
esac
# Validate the archive before connecting to the target database.
pg_restore --list "$backup_file" >/dev/null
printf 'Restoring %s into database %s\n' "$1" "$POSTGRES_DB"
pg_restore --clean --if-exists --single-transaction --exit-on-error \
    --no-owner --no-privileges --dbname="$POSTGRES_DB" "$backup_file"
printf 'Database restore completed.\n'
