"""Create a verified SQLite snapshot without changing or replacing the source.

Run only where the existing production file is accessible. A repository CSV
reconstruction is NOT a production backup. Copy the resulting database and
manifest off the service before any restart or deployment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone


def inventory(db):
    schema = list(db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    result = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        # These application tables all have rowid. An unexpected schema stops
        # verification rather than making an unverified preservation claim.
        digest = hashlib.sha256()
        count = 0
        for row in db.execute(f'SELECT * FROM {quoted} ORDER BY rowid'):
            digest.update(repr(tuple(row)).encode('utf-8') + b'\n')
            count += 1
        result[table] = {'rows': count, 'sha256_rows': digest.hexdigest()}
    return {'schema': schema, 'tables': result}


def backup(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    manifest = Path(str(destination) + '.verified.json')
    if destination.resolve() == source or destination.exists() or manifest.exists():
        raise FileExistsError('Refusing to replace the source or an existing backup/manifest')
    if not destination.parent.is_dir():
        raise ValueError('Choose an existing backup directory outside the application tree')
    started = time.monotonic()
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        src.execute('PRAGMA query_only=ON')
        src.execute('BEGIN')
        if list(src.execute('PRAGMA quick_check')) != [('ok',)]:
            raise RuntimeError('Source quick_check failed')
        before = inventory(src)
        if before['tables'].get('stores', {}).get('rows', 0) == 0:
            raise RuntimeError('Source has no store records; refusing to call it a verified backup')
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)

        def progress(status, remaining, total):
            if time.monotonic() - started > 120:
                raise TimeoutError('Backup time limit reached; no verified manifest was written')

        dst = sqlite3.connect(destination)
        try:
            src.backup(dst, pages=256, progress=progress, sleep=0.05)
            if list(dst.execute('PRAGMA integrity_check')) != [('ok',)]:
                raise RuntimeError('Backup integrity_check failed')
            after = inventory(dst)
            if before != after:
                raise RuntimeError('Backup table contents/schema differ from the source snapshot')
        finally:
            dst.close()
    with destination.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    report = {
        'backup_verified': True,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': str(source), 'backup': str(destination),
        'source_open_mode': 'ro', 'source_quick_check': 'ok',
        'backup_integrity_check': 'ok', 'sha256': digest,
        'size_bytes': destination.stat().st_size,
        'tables': after['tables'],
        'warning': 'Keep this database and manifest off-host before restart/deploy. '
                   'This script cannot certify that a supplied file is the live production database.',
    }
    fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Existing SQLite database; opened in read-only mode')
    parser.add_argument('destination', help='New backup filename in an existing secure directory')
    args = parser.parse_args()
    print(json.dumps(backup(args.source, args.destination), indent=2))
