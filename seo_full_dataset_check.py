import os
import re
import tempfile
from html import unescape

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

    for collection_name, collection in [("guide", site.SHOPPING_GUIDES), ("blog", site.BLOG_POSTS)]:
        for slug, item in collection.items():
            content_meta = site.content_meta_description(item["description"])
            assert 150 <= len(content_meta) <= 160, f"{collection_name} {slug} meta length={len(content_meta)}: {content_meta}"
            assert content_meta.startswith(item["description"]), f"{collection_name} {slug} meta lost its unique description"

    for store_name in ["3M", "Walmart", "Daniel Wellington", "Very Very Long Store Name With Many Words And Extra Text"]:
        store_meta = site.store_meta_description(store_name)
        assert 150 <= len(store_meta) <= 160, f"Store meta length={len(store_meta)} for {store_name}: {store_meta}"
        for keyword in ["Coupon Codes", "Promo Codes", "Discounts", "Sale Offers", "Black Friday Deals", "Up to 90% OFF", "Store"]:
            assert keyword in store_meta, f"Missing {keyword} in Store meta: {store_meta}"

    def meta_description(response):
        match = re.search(br'<meta name="description" content="([^"]*)">', response.data)
        assert match, "Missing meta description"
        return unescape(match.group(1).decode("utf-8"))

    def assert_meta_length(response, label):
        description = meta_description(response)
        assert 150 <= len(description) <= 160, f"{label} meta description length={len(description)}: {description}"
        return description

    home_page = client.get("/")
    assert home_page.status_code == 200
    assert_meta_length(home_page, "home")
    assert b'Find Coupon Codes, Promo Codes, Discounts, Sale Offers, Black Friday Deals and Up to 90% OFF savings where available from popular US Stores at US Coupon Hub.' in home_page.data
    assert b'"@type":"Organization"' in home_page.data
    assert b'"@type":"WebSite"' in home_page.data
    assert b'https://www.instagram.com/uscouponhub/' in home_page.data
    assert b'aria-label="Visit US Coupon Hub on Instagram"' in home_page.data
    assert b"Stores in directory" in home_page.data

    assert client.get("/categories/shopping/").status_code == 200
    assert_meta_length(client.get("/guides/"), "guides")
    assert_meta_length(client.get("/blog/"), "blog")
    assert_meta_length(client.get("/categories/beauty/"), "category-beauty")
    assert_meta_length(client.get("/categories/home-garden/"), "category-home-garden")
    assert_meta_length(client.get("/states/ohio/"), "state-ohio")
    assert_meta_length(client.get("/states/north-carolina/"), "state-north-carolina")
    assert_meta_length(client.get("/cities/dallas/"), "city-dallas")
    assert_meta_length(client.get("/cities/philadelphia/"), "city-philadelphia")
    assert_meta_length(client.get("/seasonal/halloween/"), "seasonal-halloween")
    assert_meta_length(client.get("/seasonal/black-friday/"), "seasonal-black-friday")
    assert_meta_length(client.get("/about/"), "about")
    assert_meta_length(client.get("/contact/"), "contact")
    assert_meta_length(client.get("/privacy/"), "privacy")
    assert_meta_length(client.get("/terms/"), "terms")
    assert_meta_length(client.get("/disclaimer/"), "disclaimer")
    assert_meta_length(client.get("/affiliate-disclosure/"), "affiliate-disclosure")

    assert client.get("/favicon.ico").status_code == 200

    assert client.get("/stores", follow_redirects=False).status_code == 301
    stores_page = client.get("/stores/")
    assert stores_page.status_code == 200
    assert stores_page.headers.get("X-Robots-Tag") is None
    assert_meta_length(stores_page, "stores-directory")
    assert b'name="robots" content="index,follow"' in stores_page.data
    page_two = client.get("/stores/?page=2")
    assert page_two.status_code == 200
    assert b"Page 2 | US Coupon Hub" in page_two.data
    assert b'<link rel="canonical" href="https://uscouponhub.com/stores/?page=2">' in page_two.data

    stores_query = client.get("/stores/?q=definitely-no-such-store")
    assert stores_query.status_code == 200
    assert b'name="robots" content="noindex,follow"' in stores_query.data


    search_page = client.get("/search/?q=definitely-no-such-store")
    assert search_page.status_code == 200
    assert search_page.headers.get("X-Robots-Tag") == "noindex, follow"
    assert_meta_length(search_page, "search")
    assert b'name="robots" content="noindex,follow"' in search_page.data

    assert client.get("/ebay/search/").status_code == 410
    assert client.get("/ebay/debug/").status_code == 410
    assert client.get("/ebay/account-deletion").status_code == 200
    assert client.post("/ebay/account-deletion").status_code == 204

    legacy_blog = client.get("/blog/how-to-check-promo-code/", follow_redirects=False)
    assert legacy_blog.status_code == 301
    assert legacy_blog.headers["Location"].endswith("/guides/find-legit-promo-codes/")

    assert client.get("/blog", follow_redirects=False).status_code == 301
    assert client.get("/blog/").status_code == 200
    assert client.get("/guides/").status_code == 200
    assert client.get("/guides/check-sale-price-real-deal/").status_code == 200
    guide_detail = client.get("/guides/check-sale-price-real-deal/")
    assert b'"@type":"Article"' in guide_detail.data
    assert b'"@type":"BreadcrumbList"' in guide_detail.data
    assert client.get("/guides/free-shipping-vs-coupon-discount/").status_code == 200
    assert client.get("/guides/online-return-policy-checklist/").status_code == 200
    assert client.get("/guides/safe-online-shopping-checklist/").status_code == 200
    assert client.get("/guides/holiday-shipping-deadlines-guide/").status_code == 200
    assert client.get("/blog/why-20-percent-coupon-can-cost-more-than-free-shipping/").status_code == 200
    assert client.get("/blog/coupon-code-not-working-things-to-check/").status_code == 200
    blog_detail = client.get("/blog/coupon-code-not-working-things-to-check/")
    assert b'"@type":"BlogPosting"' in blog_detail.data
    assert b'"@type":"BreadcrumbList"' in blog_detail.data
    assert client.get("/blog/percentage-off-vs-dollar-off/").status_code == 200
    assert client.get("/blog/return-shipping-can-change-deal/").status_code == 200
    assert client.get("/blog/simple-price-tracking-before-major-sales/").status_code == 200
    assert client.get("/seasonal/not-a-real-event/").status_code == 404

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert b"sitemap-static.xml" in sitemap.data
    assert "max-age=3600" in sitemap.headers.get("Cache-Control", "")

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
    assert_meta_length(store_page, "store-page")
    assert b'name="robots" content="index,follow"' in store_page.data
    assert b"Promo Codes" in store_page.data
    assert b"Coupon Codes" in store_page.data
    assert b"Discounts" in store_page.data
    assert b"Sale Offers" in store_page.data
    assert b"Black Friday Deals" in store_page.data
    assert b"Up to 90% OFF where available" in store_page.data
    assert b"ebay" not in store_page.data.lower()
    assert b"amazon" in store_page.data.lower()

print("SEO_FULL_DATASET_CHECK=PASS")
print(f"TOTAL_STORES={total_before}")
print("CURATED_STORE_INDEXING_ENABLED=0")
print(f"STORE_SITEMAP_PARTS={expected_parts}")
