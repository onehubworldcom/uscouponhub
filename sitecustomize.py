"""Disable the retired eBay integration without changing normal Flask routing."""
import importlib.abc
import importlib.machinery
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

            # Category/store pages must no longer call the retired eBay API.
            module.ebay_search_smart = lambda *args, **kwargs: ([], None, "")

            app = getattr(module, "app", None)
            if app is not None:
                @app.before_request
                def _retire_ebay_routes():
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
