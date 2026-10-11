import os
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "seo-full-dataset.db")
    os.environ["STORES_CSV"] = os.path.join(ROOT, "data", "Stores_Final.csv")

    import sitecustomize  # noqa: F401
    import app as site

    db = site.conn()
    total_before = db.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    indexable = db.execute(
        f"SELECT COUNT(*) FROM stores s WHERE {site.STORE_INDEXABLE_WHERE}"
    ).fetchone()[0]
    db.close()

    assert total_before >= 280000, f"Unexpectedly small store import: {total_before}"

    client = site.app.test_client()
    home = client.get("/")
    assert home.status_code == 200

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert b"sitemap-static.xml" in sitemap.data

    expected_parts = (indexable + 49999) // 50000
    for part in range(1, expected_parts + 1):
        assert f"sitemap-stores-{part}.xml".encode() in sitemap.data
    assert f"sitemap-stores-{expected_parts + 1}.xml".encode() not in sitemap.data

    db = site.conn()
    total_after = db.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    db.close()
    assert total_after == total_before, "Full dataset check changed the store row count."

print("SEO_FULL_DATASET_CHECK=PASS")
print(f"TOTAL_STORES={total_before}")
print(f"INDEXABLE_STORES={indexable}")
print(f"STORE_SITEMAP_PARTS={expected_parts}")
