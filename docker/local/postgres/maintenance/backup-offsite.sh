#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"
[ "$#" -eq 1 ] || { printf 'Usage: backup-offsite.sh <filename.dump.gpg>\n' >&2; exit 1; }
case "$1" in
    */*|.*|*[!a-zA-Z0-9_.-]*|"") exit 1 ;;
    *.dump.gpg) ;;
    *) printf 'Off-host copies require an encrypted .dump.gpg backup.\n' >&2; exit 1 ;;
esac
: "${BACKUP_REMOTE_DEST:?Set an SSH destination such as backup@host:/backups}"
: "${BACKUP_SSH_KEY_FILE:?Set the path to the mounted SSH private key}"
: "${BACKUP_KNOWN_HOSTS_FILE:?Set the path to verified SSH known_hosts}"
case "$BACKUP_REMOTE_DEST" in -*|*[!a-zA-Z0-9_@:/.-]*) exit 1 ;; esac
case "$BACKUP_REMOTE_DEST" in *@*:* ) ;; *) exit 1 ;; esac
[ -f "$BACKUP_DIR/$1" ] && [ ! -L "$BACKUP_DIR/$1" ]
scp -i "$BACKUP_SSH_KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=yes \
    -o "UserKnownHostsFile=$BACKUP_KNOWN_HOSTS_FILE" \
    "$BACKUP_DIR/$1" "$BACKUP_REMOTE_DEST/"
