import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'maintenance'


class MaintenanceScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='backup-security-tests-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        binaries = self.root / 'bin'
        binaries.mkdir()
        self.backups = self.root / 'backups'
        self.restore_log = self.root / 'restore.log'
        self.ssh_log = self.root / 'ssh.log'
        key = self.root / 'passphrase'
        key.write_text('test passphrase only')
        mocks = {
            'pg_dump': '''#!/bin/sh
set -eu
for arg in "$@"; do case "$arg" in --file=*) output=${arg#--file=} ;; esac; done
printf PGDMP > "$output"
[ "${FAIL_DUMP:-0}" = 0 ]
''',
            'pg_restore': '''#!/bin/sh
set -eu
if [ "$1" = --list ]; then [ "$(cat "$2")" = PGDMP ]; exit; fi
printf '%s\\n' "$@" > "$RESTORE_LOG"
''',
            'gpg': '''#!/bin/sh
set -eu
mode=encrypt
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) shift; output=$1 ;;
        --passphrase-file) shift; [ -s "$1" ] ;;
        --decrypt) mode=decrypt ;;
    esac
    input=$1
    shift
done
if [ "$mode" = encrypt ]; then printf 'ENCRYPTED:' > "$output"; cat "$input" >> "$output";
else sed 's/^ENCRYPTED://' "$input" > "$output"; fi
''',
            'scp': '''#!/bin/sh
printf '%s\\n' "$@" > "$SSH_LOG"
''',
        }
        for name, content in mocks.items():
            binary = binaries / name
            binary.write_text(content)
            binary.chmod(0o700)
        self.env = dict(os.environ, PATH=f'{binaries}:' + os.environ['PATH'],
            BACKUP_DIR=str(self.backups), POSTGRES_DB='testdb', POSTGRES_USER='testuser',
            POSTGRES_PASSWORD='testpassword', RESTORE_LOG=str(self.restore_log), SSH_LOG=str(self.ssh_log))
        # Do not inherit a developer's remote destination or encryption settings.
        for name in ['BACKUP_REMOTE_DEST', 'BACKUP_PASSPHRASE_FILE', 'BACKUP_ENCRYPTION_REQUIRED']:
            self.env.pop(name, None)
        self.key = key

    def run_script(self, name, *args, success=True, **extra):
        result = subprocess.run(['sh', str(SCRIPTS / name), *args], env=dict(self.env, **extra), capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_shell_syntax(self):
        for script in SCRIPTS.glob('*.sh'):
            subprocess.run(['sh', '-n', str(script)], check=True)

    def test_backup_and_atomic_restore(self):
        self.run_script('backup.sh')
        backup, = self.backups.glob('*.dump')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.run_script('list-backups.sh').stdout.strip(), backup.name)
        self.run_script('restore.sh', backup.name)
        arguments = self.restore_log.read_text().splitlines()
        for required in ['--clean', '--single-transaction', '--exit-on-error', '--dbname=testdb']:
            self.assertIn(required, arguments)

    def test_failed_dump_leaves_no_archive(self):
        self.run_script('backup.sh', success=False, FAIL_DUMP='1')
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_required_encryption_fails_without_key(self):
        self.run_script('backup.sh', success=False, BACKUP_ENCRYPTION_REQUIRED='true')
        self.assertFalse(self.backups.exists())

    def test_encrypted_backup_restore_and_cleanup(self):
        self.run_script('backup.sh', BACKUP_PASSPHRASE_FILE=str(self.key), BACKUP_ENCRYPTION_REQUIRED='true')
        backup, = self.backups.iterdir()
        self.assertTrue(backup.name.endswith('.dump.gpg'))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertTrue(backup.read_text().startswith('ENCRYPTED:'))
        self.run_script('restore.sh', backup.name, BACKUP_PASSPHRASE_FILE=str(self.key))
        self.assertTrue(self.restore_log.exists())
        self.assertEqual(list(self.backups.iterdir()), [backup])

    def test_invalid_paths_and_archives_never_restore(self):
        self.backups.mkdir()
        invalid = self.backups / 'invalid.dump'
        invalid.write_text('not an archive')
        for name in ['../escape.dump', 'missing.dump', invalid.name]:
            self.run_script('restore.sh', name, success=False)
        self.assertFalse(self.restore_log.exists())

    def test_offsite_requires_encryption_and_verified_host(self):
        self.backups.mkdir()
        archive = self.backups / 'backup.dump.gpg'
        archive.write_text('encrypted mock')
        options = dict(BACKUP_REMOTE_DEST='backup@example.com:/backups',
            BACKUP_SSH_KEY_FILE=str(self.key), BACKUP_KNOWN_HOSTS_FILE=str(self.key))
        self.run_script('backup-offsite.sh', 'plain.dump', success=False, **options)
        self.run_script('backup-offsite.sh', archive.name, **options)
        arguments = self.ssh_log.read_text().splitlines()
        self.assertIn('StrictHostKeyChecking=yes', arguments)
        self.assertIn('BatchMode=yes', arguments)


if __name__ == '__main__':
    unittest.main()
