"""Disposable SQLite-only regression tests for sqlite_hot_backup."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_hot_backup import backup_database


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / "live.db"
        self.destination = self.root / "private"
        self.destination.mkdir()

    def seed(self, stores=2):
        with sqlite3.connect(self.original) as db:
            db.execute("CREATE TABLE stores (id INTEGER PRIMARY KEY, name TEXT, slug TEXT)")
            db.execute("CREATE TABLE offers (id INTEGER PRIMARY KEY, store_id INTEGER)")
            db.execute("CREATE TABLE store_affiliate_matches (id INTEGER PRIMARY KEY, store_id INTEGER)")
            db.execute("CREATE TABLE affiliate_networks (id INTEGER PRIMARY KEY, name TEXT)")
            for idx in range(stores):
                db.execute("INSERT INTO stores(name, slug) VALUES(?, ?)", (f"Sample {idx}", f"sample-{idx}"))
            db.execute("INSERT INTO offers(store_id) VALUES (1)")

    def test_snapshot_preserves_source_and_counts(self):
        self.seed()
        before = hashlib.sha256(self.original.read_bytes()).hexdigest()
        result = backup_database(self.original, self.destination)
        after = hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.assertEqual(before, after, "Backup must not write to source SQLite file")
        backup = Path(result["backup"])
        manifest = Path(result["manifest"])
        self.assertTrue(backup.is_file())
        self.assertTrue(manifest.is_file())
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM stores").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM offers").fetchone()[0], 1)
        info = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(info["sha256"], hashlib.sha256(backup.read_bytes()).hexdigest())
        self.assertEqual(info["backup_counts"]["stores"], 2)
        self.assertEqual(info["backup_counts"]["offers"], 1)

    def test_refuses_empty_database(self):
        self.seed(stores=0)
        with self.assertRaises(RuntimeError):
            backup_database(self.original, self.destination)
        self.assertFalse(list(self.destination.glob("uscouponhub-*.db")))

    def test_refuses_corrupt_database(self):
        self.original.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            backup_database(self.original, self.destination)
        self.assertFalse(list(self.destination.glob("uscouponhub-*.db")))

    def test_nonexistent_source_never_created(self):
        with self.assertRaises(FileNotFoundError):
            backup_database(self.root / "missing.db", self.destination)
        self.assertFalse((self.root / "missing.db").exists())

    def test_separate_immutable_backups(self):
        self.seed()
        first = backup_database(self.original, self.destination)
        second = backup_database(self.original, self.destination)
        self.assertNotEqual(first["backup"], second["backup"])
        self.assertTrue(Path(first["backup"]).exists())
        self.assertTrue(Path(second["backup"]).exists())


if __name__ == "__main__":
    unittest.main()
