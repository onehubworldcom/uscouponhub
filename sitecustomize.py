"""Retire the former eBay integration before Flask registers application routes."""
try:
    from flask import Flask

    _original_add_url_rule = Flask.add_url_rule

    def _retired_ebay(*args, **kwargs):
        return (
            "The requested page has been permanently removed.",
            410,
            {
                "Content-Type": "text/plain; charset=utf-8",
                "X-Robots-Tag": "noindex, nofollow, noarchive",
                "Cache-Control": "public, max-age=3600",
            },
        )

    def _add_url_rule_without_ebay(self, rule, endpoint=None, view_func=None, **options):
        if str(rule).lower().startswith("/ebay"):
            view_func = _retired_ebay
        return _original_add_url_rule(self, rule, endpoint, view_func, **options)

    Flask.add_url_rule = _add_url_rule_without_ebay
except Exception:
    # Never prevent the application from starting if Flask changes its API.
    pass
