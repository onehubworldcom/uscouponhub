"""Read-only SEO inventory for USCouponHub.

Usage: python scripts/seo_readonly_audit.py /path/to/uscouponhub.db
Never run against production if a safe copied backup is available.
"""
import argparse
import json
import sqlite3
from pathlib import Path

INDEXABLE_WHERE = """s.active=1 AND (length(trim(coalesce(s.description,''))) >= 160
 OR EXISTS (SELECT 1 FROM offers o WHERE o.store_id=s.id AND o.active=1 AND o.verified=1)
 OR EXISTS (SELECT 1 FROM store_affiliate_matches m JOIN affiliate_networks n
 ON n.id=m.network_id WHERE m.store_id=s.id AND m.status='approved'
 AND n.active=1 AND (m.affiliate_url LIKE 'http://%' OR m.affiliate_url LIKE 'https://%')))"""


def audit(database):
    uri = Path(database).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Database quick_check failed')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted({'stores', 'offers', 'store_affiliate_matches', 'affiliate_networks'} - tables)
        if missing:
            raise RuntimeError('Missing tables: ' + ', '.join(missing))
        one = lambda sql: db.execute(sql).fetchone()[0]
        total = one('SELECT COUNT(*) FROM stores')
        active = one('SELECT COUNT(*) FROM stores WHERE active=1')
        eligible = one(f'SELECT COUNT(*) FROM stores s WHERE {INDEXABLE_WHERE}')
        with_description = one("SELECT COUNT(*) FROM stores WHERE active=1 AND length(trim(coalesce(description,''))) >= 160")
        verified = one('SELECT COUNT(DISTINCT s.id) FROM stores s JOIN offers o ON o.store_id=s.id WHERE s.active=1 AND o.active=1 AND o.verified=1')
        invalid_slugs = one("SELECT COUNT(*) FROM stores WHERE active=1 AND (slug IS NULL OR slug='' OR slug<>lower(slug) OR slug LIKE '% %')")
        suspect_names = one("SELECT COUNT(*) FROM stores WHERE active=1 AND (trim(name)='' OR name GLOB '[0-9][0-9]-[A-Za-z][A-Za-z][A-Za-z]*')")
        return {'quick_check': 'ok', 'stores_total': total, 'stores_active': active,
                'stores_curated_sitemap_eligible': eligible,
                'active_stores_not_eligible': active-eligible,
                'active_stores_with_description_160': with_description,
                'active_stores_with_verified_offer': verified,
                'active_stores_invalid_slug_simple_check': invalid_slugs,
                'active_stores_suspicious_name_simple_check': suspect_names,
                'current_50k_store_sitemaps': (active+49999)//50000,
                'curated_50k_store_sitemaps': (eligible+49999)//50000,
                'note': 'Eligibility matches current sitemap SQL, not guaranteed Google indexing.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='Path to a backed-up SQLite database')
    args = parser.parse_args()
    print(json.dumps(audit(args.database), indent=2))


if __name__ == '__main__':
    main()
