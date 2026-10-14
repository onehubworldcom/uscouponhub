import os
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "seo-recovery-test.db")
    os.environ["STORES_CSV"] = os.path.join(ROOT, "data", "test_stores.csv")
    os.environ["CURATED_STORE_INDEXING_ENABLED"] = "1"

    # Import explicitly so the production runtime patch is exercised by CI.
    import sitecustomize  # noqa: F401
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
    assert client.get("/categories/shopping/").status_code == 200

    # Thin stores remain available to visitors but are not indexable.
    r = client.get(f"/{slug}")
    assert r.status_code == 200
    assert b'name="robots" content="noindex,follow"' in r.data
    # Empty stores should not claim automatically generated comparison cards
    # are genuine coupon offers. The independent Amazon link remains.
    assert b"0 offers listed" in r.data
    assert b"AUTO DEAL" not in r.data
    assert b"Search Amazon" in r.data

    # Canonical related links must be slashless and existing active stores.
    import re
    related_section = re.search(rb'<section class="content related-stores-section">(.*?)</section>', r.data, flags=re.S)
    assert related_section, "Expected related-store links"
    related_slugs = re.findall(rb'class="related-store-card" href="/([^"/]+)"', related_section.group(1))
    assert 1 <= len(related_slugs) <= 6, related_slugs
    assert len(related_slugs) == len(set(related_slugs)), "Duplicate related links"
    assert slug.encode() not in related_slugs, "Related stores include current page"
    for related_slug in related_slugs:
        assert client.get("/" + related_slug.decode()).status_code == 200

    # Store path with slash is redirected only for real active stores.
    slash_response = client.get(f"/{slug}/", follow_redirects=False)
    assert slash_response.status_code == 301
    assert slash_response.headers["Location"].endswith("/" + slug)
    assert client.get("/definitely-not-a-store-20261014/", follow_redirects=False).status_code == 404

    # A huge page parameter used to raise OverflowError when bound as
    # a SQLite OFFSET before clamping to the directory page count.
    huge_page = client.get("/stores/?page=99999999999999999999999999999999")
    assert huge_page.status_code == 200
    assert b"Page " in huge_page.data

    static_map = client.get("/sitemap-static.xml")
    assert static_map.status_code == 200
    assert b"/seasonal/halloween/" in static_map.data
    assert b"/seasonal/black-friday/" in static_map.data
    assert b"/seasonal/cyber-monday/" in static_map.data

    index_map = client.get("/sitemap.xml")
    assert index_map.status_code == 200
    assert b"sitemap-static.xml" in index_map.data
    assert b"sitemap-stores-1.xml" not in index_map.data

    # An unverified database offer must NOT make a thin page indexable.
    db = site.conn()
    db.execute(
        "INSERT INTO offers(store_id,title,verified,active,created_at) VALUES (?,?,?,?,?)",
        (store_id, "Unverified test offer", 0, 1, "2026-10-11T00:00:00"),
    )
    db.commit()
    db.close()

    r = client.get(f"/{slug}")
    assert b'name="robots" content="noindex,follow"' in r.data
    assert b"sitemap-stores-1.xml" not in client.get("/sitemap.xml").data

    # Verified content should promote the page into the indexable set.
    db = site.conn()
    db.execute("UPDATE offers SET verified=1 WHERE store_id=?", (store_id,))
    db.commit()
    db.close()

    r = client.get(f"/{slug}")
    assert b'name="robots" content="index,follow"' in r.data
    index_map = client.get("/sitemap.xml")
    assert b"sitemap-stores-1.xml" in index_map.data
    store_map = client.get("/sitemap-stores-1.xml")
    assert store_map.status_code == 200
    assert f"https://uscouponhub.com/{slug}".encode() in store_map.data

    # Unique substantial merchant content is also enough to qualify.
    db = site.conn()
    db.execute("DELETE FROM offers WHERE store_id=?", (store_id,))
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
    assert b"sitemap-stores-1.xml" in client.get("/sitemap.xml").data
    # Existing merchant descriptions must be visible in both body and metadata.
    assert b"Independent merchant information and shopping guidance." in r.data
    assert b'content="Independent merchant information' in r.data

print("SEO_RECOVERY_CHECK=PASS")
print(f"STORES_PRESERVED={initial_count}")
