import os
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "seo-recovery-test.db")
    os.environ["STORES_CSV"] = os.path.join(ROOT, "data", "test_stores.csv")

    import app as site

    client = site.app.test_client()
    db = site.conn()
    initial_count = db.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    first_store = db.execute("SELECT id, slug FROM stores ORDER BY id LIMIT 1").fetchone()
    assert first_store is not None, "Test CSV did not import a store."
    store_id, slug = first_store["id"], first_store["slug"]
    db.close()

    r = client.get("/stores", follow_redirects=False)
    assert r.status_code == 301 and r.headers["Location"].endswith("/stores/")

    r = client.get("/blog", follow_redirects=False)
    assert r.status_code == 301 and r.headers["Location"].endswith("/blog/")

    r = client.get("/blog/how-to-plan-weekly-shopping-budget", follow_redirects=False)
    assert r.status_code == 301 and r.headers["Location"].endswith("/blog/how-to-plan-weekly-shopping-budget/")

    assert client.get("/seasonal/not-a-real-event/").status_code == 404
    assert client.get("/seasonal/black-friday/").status_code == 200

    r = client.get(f"/{slug}")
    assert r.status_code == 200
    assert b'name="robots" content="noindex,follow"' in r.data

    static_map = client.get("/sitemap-static.xml")
    assert static_map.status_code == 200
    assert b"/seasonal/halloween/" in static_map.data
    assert b"/seasonal/black-friday/" in static_map.data
    assert b"/seasonal/cyber-monday/" in static_map.data

    index_map = client.get("/sitemap.xml")
    assert index_map.status_code == 200
    assert b"sitemap-static.xml" in index_map.data
    assert b"sitemap-stores-1.xml" not in index_map.data

    db = site.conn()
    db.execute(
        "UPDATE stores SET description=? WHERE id=?",
        ("Independent merchant information and shopping guidance. " * 5, store_id),
    )
    db.commit()
    final_count = db.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    db.close()

    assert final_count == initial_count, "SEO changes must not delete store rows."

    r = client.get(f"/{slug}")
    assert b'name="robots" content="index,follow"' in r.data

    index_map = client.get("/sitemap.xml")
    assert b"sitemap-stores-1.xml" in index_map.data

    store_map = client.get("/sitemap-stores-1.xml")
    assert store_map.status_code == 200
    assert f"https://uscouponhub.com/{slug}".encode() in store_map.data

print("SEO_RECOVERY_CHECK=PASS")
print(f"STORES_PRESERVED={initial_count}")
