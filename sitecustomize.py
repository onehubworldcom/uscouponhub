"""Retire the old marketplace integration and keep store pages Amazon-only."""
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
            from flask import Response, request

            # Category/store pages must not call the retired marketplace API.
            module.ebay_search_smart = lambda *args, **kwargs: ([], None, "")

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
            # Never prevent the application from starting because of this cleanup.
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
