#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

if [ "$#" -ne 0 ]; then
    printf 'Usage: list-backups.sh\n' >&2
    exit 1
fi
for backup_file in "$BACKUP_DIR"/*.dump "$BACKUP_DIR"/*.dump.gpg; do
    [ -f "$backup_file" ] || continue
    basename "$backup_file"
done
