"""Create a verified SQLite backup without changing the source database.

Usage:
    python scripts/sqlite_hot_backup.py --db /path/to/uscouponhub.db --dest /secure/existing/directory

IMPORTANT: Copy the resulting .db and .json files off the Render instance immediately.
Running this utility is not a substitute for having access to the *existing* live
instance. Never redeploy a Free Render service merely to make this script available.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


REQUIRED_TABLES = {"stores", "offers", "store_affiliate_matches", "affiliate_networks"}


def readonly_connection(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)


def database_summary(db):
    result = db.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError("SQLite quick_check failed: " + str(result))
    found = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    missing = REQUIRED_TABLES - found
    if missing:
        raise RuntimeError("Missing expected tables: " + ", ".join(sorted(missing)))
    counts = {}
    for table in sorted(REQUIRED_TABLES):
        counts[table] = db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
    if counts["stores"] < 1:
        raise RuntimeError("Refusing an empty store database")
    return counts


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(source_path, destination_directory):
    source = Path(source_path).expanduser().resolve(strict=True)
    output = Path(destination_directory).expanduser().resolve(strict=True)
    if not source.is_file() or not output.is_dir():
        raise ValueError("Source must be a database file and destination an existing directory")
    if not os.access(output, os.W_OK):
        raise PermissionError("Backup destination is not writable")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = output / ("uscouponhub-" + stamp + ".db")
    manifest = target.with_suffix(".json")

    fd, temporary_name = tempfile.mkstemp(prefix=".uscouponhub-snapshot-", suffix=".db", dir=output)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with closing(readonly_connection(source)) as live:
            source_counts = database_summary(live)
            live.execute("PRAGMA query_only=ON")
            with closing(sqlite3.connect(str(temporary), timeout=30)) as snapshot:
                live.backup(snapshot, pages=1000, sleep=0.1)
                snapshot.commit()
        with closing(readonly_connection(temporary)) as check:
            backup_counts = database_summary(check)
        if backup_counts != source_counts:
            # Records may change while the source is live. Refuse ambiguous snapshots.
            raise RuntimeError("Database row counts changed during backup; retry after writes settle")
        data = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "backup_name": target.name,
            "source_counts": source_counts,
            "backup_counts": backup_counts,
            "sqlite_quick_check": "ok",
            "backup_size_bytes": temporary.stat().st_size,
            "sha256": sha256_file(temporary),
            "warning": "Store a copy OFF the Render instance; never commit the SQLite file to GitHub.",
        }
        # Atomic create-if-absent; never overwrite an existing backup.
        os.link(temporary, target)
        with manifest.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        return {"backup": str(target), "manifest": str(manifest), **data}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to the currently populated SQLite database")
    parser.add_argument("--dest", required=True, help="An existing private directory with sufficient space")
    args = parser.parse_args()
    print(json.dumps(backup_database(args.db, args.dest), indent=2))


if __name__ == "__main__":
    main()
