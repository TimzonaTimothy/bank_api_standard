# Database backup and restore

Rebuild the PostgreSQL image once to install the shell scripts:

```sh
docker compose -f local.yml up -d --build postgres
make backup
make backups
```

Backups use PostgreSQL's custom archive format. Files are created with private
permissions in `/backups`, backed by the `banker_local_db_backups` named volume.
Failed dumps are removed; only completed backups appear in the list. Credentials
come from the container's existing `POSTGRES_*` environment variables.

To restore, stop database writers first and choose a filename from `make backups`:

```sh
docker compose -f local.yml stop api celeryworker celerybeat
make restore BACKUP=backup_20261105T120000Z_ABC123.dump
docker compose -f local.yml start api celeryworker celerybeat
```

Restore replaces objects present in the archive in the existing `POSTGRES_DB`.
It validates the archive first and uses one transaction, rolling back on errors.
Objects absent from the archive are not removed. The restored objects belong to
`POSTGRES_USER`; cluster roles and original ownership/privileges are not restored.
Use backups from a trusted source and compatible PostgreSQL versions.

The scripts can also be run directly:

```sh
docker compose -f local.yml exec -T postgres /usr/local/bin/maintenance/backup.sh
docker compose -f local.yml exec -T postgres /usr/local/bin/maintenance/list-backups.sh
docker compose -f local.yml exec -T postgres /usr/local/bin/maintenance/restore.sh BACKUP_FILENAME.dump
```

Copy a backup outside Docker for an independent copy:

```sh
docker compose -f local.yml cp postgres:/backups/BACKUP_FILENAME.dump /path/to/backup.dump
```

The backup volume survives container rebuilds and `docker compose down`, but
`docker compose down -v` removes it. These commands create on-demand backups;
they do not schedule backups or delete older archives.
