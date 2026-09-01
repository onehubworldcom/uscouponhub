"""Keep retired marketplace code from affecting live store/category pages and SEO."""
import importlib.abc
import importlib.machinery
import re
import sys


class _AppLoader(importlib.abc.Loader):
    def __init__(self, loader):
        self.loader = loader

    def create_module(self, spec):
        create = getattr(self.loader, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module):
        self.loader.exec_module(module)
        try:
            from flask import Response, request, render_template, abort

            # Retire the old marketplace completely.
            module.ebay_search_smart = lambda *args, **kwargs: ([], None, "")

            # Never expose legacy eBay offers on store pages.
            original_automatic_offers = getattr(module, "automatic_store_offers", None)
            if original_automatic_offers:
                def _amazon_only_offers(store, existing_offers):
                    offers = [o for o in list(existing_offers or [])
                              if str(o.get("source", "")).lower() != "ebay"
                              and str(o.get("offer_type", "")).lower() != "ebay"]
                    result = original_automatic_offers(store, offers)
                    return [o for o in list(result or [])
                            if str(o.get("source", "")).lower() != "ebay"
                            and str(o.get("offer_type", "")).lower() != "ebay"]
                module.automatic_store_offers = _amazon_only_offers

            # Search must never fall back to the retired marketplace.
            original_classify_search = getattr(module, "classify_search", None)
            if original_classify_search:
                def _safe_classify_search(c, q):
                    result = original_classify_search(c, q)
                    if isinstance(result, tuple) and result and result[0] == "ebay":
                        return "directory", None, result[2] if len(result) > 2 else 0
                    return result
                module.classify_search = _safe_classify_search

            app = getattr(module, "app", None)
            if app is not None:
                @app.before_request
                def _retire_old_marketplace_routes():
                    if request.path.lower().startswith("/ebay"):
                        return Response(
                            "The requested page has been permanently removed.",
                            status=410,
                            headers={
                                "X-Robots-Tag": "noindex, nofollow, noarchive",
                                "Cache-Control": "public, max-age=3600",
                            },
                            content_type="text/plain; charset=utf-8",
                        )

                # Replace the category handler so category pages never depend
                # on the retired marketplace API.
                for rule in list(app.url_map.iter_rules()):
                    if rule.rule == "/categories/<category_slug>/":
                        endpoint = rule.endpoint
                        if endpoint in app.view_functions:
                            def _safe_category_page(category_slug):
                                categories = getattr(module, "CATEGORIES", [])
                                if category_slug not in categories:
                                    return abort(404)
                                config = getattr(module, "CATEGORY_CONFIG", {}).get(
                                    category_slug,
                                    {"label": category_slug.replace("-", " ").title(),
                                     "query": category_slug.replace("-", " "),
                                     "subcategories": []},
                                )
                                category = config["label"]
                                c = module.conn()
                                stores = c.execute(
                                    "SELECT * FROM stores WHERE active=1 AND lower(category)=? ORDER BY name COLLATE NOCASE LIMIT 24",
                                    (category.lower(),),
                                ).fetchall()
                                if not stores:
                                    words = [w for w in re.split(r"[^a-z0-9]+", config["query"].lower()) if len(w) > 2]
                                    terms = list(dict.fromkeys(words + config.get("aliases", [])))[:8]
                                    if terms:
                                        clauses = " OR ".join(["lower(name) LIKE ?" for _ in terms])
                                        params = [f"%{term.lower()}%" for term in terms]
                                        stores = c.execute(
                                            f"SELECT * FROM stores WHERE active=1 AND ({clauses}) ORDER BY name COLLATE NOCASE LIMIT 24",
                                            params,
                                        ).fetchall()
                                c.close()
                                return render_template(
                                    "category.html", category=category,
                                    category_slug=category_slug, stores=stores,
                                    subcategories=config.get("subcategories", []),
                                    ebay_items=[], ebay_error=None, ebay_query="",
                                )
                            app.view_functions[endpoint] = _safe_category_page
                        break

                # Keep only useful store URLs in XML sitemaps. The CSV contains
                # a very large number of store records, but thin/unverified
                # store pages should not all be submitted to Google.
                def _curated_sitemap_index():
                    c = module.conn()
                    count = c.execute("""SELECT COUNT(*) FROM stores s
                        WHERE s.active=1 AND (
                          EXISTS (SELECT 1 FROM offers o WHERE o.store_id=s.id AND o.active=1)
                          OR EXISTS (SELECT 1 FROM store_affiliate_matches m WHERE m.store_id=s.id AND m.status IN ('active','approved','matched'))
                        )""").fetchone()[0]
                    c.close()
                    parts = (count + 49999) // 50000
                    base = "https://uscouponhub.com"
                    entries = ''.join(f'<sitemap><loc>{base}/sitemap-stores-{i}.xml</loc></sitemap>' for i in range(1, parts + 1))
                    entries += f'<sitemap><loc>{base}/sitemap-static.xml</loc></sitemap>'
                    return Response('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + '</sitemapindex>', mimetype='application/xml')

                def _curated_sitemap_stores(part):
                    if part < 1:
                        return abort(404)
                    per = 50000
                    offset = (part - 1) * per
                    c = module.conn()
                    rows = c.execute("""SELECT s.slug FROM stores s
                        WHERE s.active=1 AND (
                          EXISTS (SELECT 1 FROM offers o WHERE o.store_id=s.id AND o.active=1)
                          OR EXISTS (SELECT 1 FROM store_affiliate_matches m WHERE m.store_id=s.id AND m.status IN ('active','approved','matched'))
                        )
                        ORDER BY s.id LIMIT ? OFFSET ?""", (per, offset)).fetchall()
                    c.close()
                    if not rows:
                        return abort(404)
                    base = "https://uscouponhub.com"
                    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    xml += ''.join(f'<url><loc>{base}/{r["slug"]}</loc></url>' for r in rows)
                    xml += '</urlset>'
                    return Response(xml, mimetype='application/xml')

                if "sitemap_index" in app.view_functions:
                    app.view_functions["sitemap_index"] = _curated_sitemap_index
                if "sitemap_stores" in app.view_functions:
                    app.view_functions["sitemap_stores"] = _curated_sitemap_stores

                # Search pages are site functionality, not landing pages. Keep
                # them crawlable only as needed for users, but tell search
                # engines not to index query/pagination variants.
                @app.after_request
                def _noindex_search_variants(response):
                    if request.path.rstrip("/") in ("/search", "/stores"):
                        response.headers["X-Robots-Tag"] = "noindex, follow"
                    return response

                # Safety net for any legacy store HTML still present in a
                # deployment: convert marketplace wording and links to Amazon.
                original_store_page = app.view_functions.get("store_page")
                if original_store_page:
                    def _amazonize_store_page(*args, **kwargs):
                        response = original_store_page(*args, **kwargs)
                        body = response.get_data(as_text=True) if hasattr(response, "get_data") else str(response)
                        if re.search(r"ebay", body, re.IGNORECASE):
                            slug = request.path.strip("/").split("/")[0]
                            amazon_url = "/amazon/search/" + slug + "/"
                            body = re.sub(r"https?://(?:www\.)?ebay\.[^\"'<> ]+", amazon_url, body, flags=re.IGNORECASE)
                            body = re.sub(r"/ebay(?:/search)?(?:/[^\"'<> ]*)?", amazon_url, body, flags=re.IGNORECASE)
                            body = re.sub(r"Check live eBay listings for [^<]+", "Compare Shopping prices on Amazon", body, flags=re.IGNORECASE)
                            body = re.sub(r"Search current eBay listings and compare available items, prices and shipping\.?", "Search current products and offers on Amazon.", body, flags=re.IGNORECASE)
                            body = re.sub(r"Find [^<]+ Deals on eBay", "More Shopping Deals on Amazon", body, flags=re.IGNORECASE)
                            body = re.sub(r"Search [^<]+ on eBay", "Search on Amazon", body, flags=re.IGNORECASE)
                            body = re.sub(r"eBay", "Amazon", body)
                            body = re.sub(r"EBAY", "AMAZON", body)
                            body = re.sub(r"ebay", "Amazon", body, flags=re.IGNORECASE)
                            if hasattr(response, "set_data"):
                                response.set_data(body)
                                response.headers["Content-Type"] = "text/html; charset=utf-8"
                                return response
                            return body
                        return response
                    app.view_functions["store_page"] = _amazonize_store_page
        except Exception:
            # Never prevent the application from starting because of cleanup.
            pass


class _AppFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "app":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _AppLoader(spec.loader)
        return spec


sys.meta_path.insert(0, _AppFinder())
