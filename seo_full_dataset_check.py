import os
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "seo-full-dataset.db")
    os.environ["STORES_CSV"] = os.path.join(ROOT, "data", "Stores_Final.csv")
    os.environ.pop("CURATED_STORE_INDEXING_ENABLED", None)

    import sitecustomize  # noqa: F401
    import app as site

    assert site.CURATED_STORE_INDEXING_ENABLED is False

    db = site.conn()
    total_before = db.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    db.close()

    assert total_before >= 280000, f"Unexpectedly small store import: {total_before}"

    client = site.app.test_client()

    assert client.get("/categories/shopping/").status_code == 200
    assert client.get("/favicon.ico").status_code == 200

    assert client.get("/stores", follow_redirects=False).status_code == 301
    stores_page = client.get("/stores/")
    assert stores_page.status_code == 200
    assert stores_page.headers.get("X-Robots-Tag") is None
    assert b'name="robots" content="index,follow"' in stores_page.data

    search_page = client.get("/search/?q=definitely-no-such-store")
    assert search_page.status_code == 200
    assert search_page.headers.get("X-Robots-Tag") == "noindex, follow"
    assert b'name="robots" content="noindex,follow"' in search_page.data

    assert client.get("/ebay/search/").status_code == 410
    assert client.get("/ebay/debug/").status_code == 410
    assert client.get("/ebay/account-deletion").status_code == 200
    assert client.post("/ebay/account-deletion").status_code == 204

    assert client.get("/blog", follow_redirects=False).status_code == 301
    assert client.get("/blog/").status_code == 200
    assert client.get("/guides/").status_code == 200
    assert client.get("/guides/check-sale-price-real-deal/").status_code == 200
    assert client.get("/guides/free-shipping-vs-coupon-discount/").status_code == 200
    assert client.get("/guides/online-return-policy-checklist/").status_code == 200
    assert client.get("/guides/safe-online-shopping-checklist/").status_code == 200
    assert client.get("/guides/holiday-shipping-deadlines-guide/").status_code == 200
    assert client.get("/blog/why-20-percent-coupon-can-cost-more-than-free-shipping/").status_code == 200
    assert client.get("/blog/coupon-code-not-working-things-to-check/").status_code == 200
    assert client.get("/blog/percentage-off-vs-dollar-off/").status_code == 200
    assert client.get("/blog/return-shipping-can-change-deal/").status_code == 200
    assert client.get("/blog/simple-price-tracking-before-major-sales/").status_code == 200
    assert client.get("/seasonal/not-a-real-event/").status_code == 404

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert b"sitemap-static.xml" in sitemap.data

    expected_parts = (total_before + 49999) // 50000
    assert expected_parts == 6, f"Expected six store sitemap parts, got {expected_parts}"
    for part in range(1, expected_parts + 1):
        assert f"sitemap-stores-{part}.xml".encode() in sitemap.data
    assert f"sitemap-stores-{expected_parts + 1}.xml".encode() not in sitemap.data

    # Default rollout must preserve indexability until curated mode is
    # deliberately enabled after production enrichment is confirmed.
    db = site.conn()
    sample = db.execute("SELECT slug FROM stores ORDER BY id LIMIT 1").fetchone()
    total_after = db.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    db.close()

    assert total_after == total_before, "Full dataset check changed the store row count."

    store_page = client.get(f"/{sample['slug']}")
    assert store_page.status_code == 200
    assert b'name="robots" content="index,follow"' in store_page.data
    assert b"ebay" not in store_page.data.lower()
    assert b"amazon" in store_page.data.lower()

print("SEO_FULL_DATASET_CHECK=PASS")
print(f"TOTAL_STORES={total_before}")
print("CURATED_STORE_INDEXING_ENABLED=0")
print(f"STORE_SITEMAP_PARTS={expected_parts}")
