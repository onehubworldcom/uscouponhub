"""Shared, read-only predicates for store HTML, sitemaps and SEO audits."""

RESERVED_SLUGS = {
    'states', 'cities', 'categories', 'seasonal', 'guides', 'blog', 'search',
    'stores', 'about', 'privacy', 'terms', 'disclaimer', 'contact',
    'affiliate-disclosure', 'affiliate-status', 'sitemap.xml', 'robots.txt',
    'static', 'favicon.ico',
}

# Slugs are URL path segments. Suspicious names are reported for human review,
# never deleted or automatically mapped to another merchant.
STORE_VALID_WHERE = """s.active=1
 AND length(trim(coalesce(s.name,'')))>0
 AND coalesce(s.slug,'')<>''
 AND s.slug NOT GLOB '*[^a-z0-9-]*'
 AND s.slug NOT LIKE '-%' AND s.slug NOT LIKE '%-'
 AND s.slug NOT LIKE '%--%'
 AND s.slug NOT IN ({})""".format(','.join("'" + v + "'" for v in sorted(RESERVED_SLUGS)))

# Date-only expiry values remain valid through that UTC calendar day.
# Malformed dates and retired marketplace offers cannot qualify a store.
CURRENT_OFFER_WHERE = """o.active=1
 AND lower(coalesce(o.offer_type,''))<>'ebay'
 AND (trim(coalesce(o.expires_at,''))=''
 OR (trim(o.expires_at) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'
 AND julianday(CASE WHEN length(trim(o.expires_at))=10
     THEN date(trim(o.expires_at), '+1 day') ELSE trim(o.expires_at) END)>julianday('now')))"""

STORE_INDEXABLE_WHERE = STORE_VALID_WHERE + """ AND (
 length(trim(coalesce(s.description,'')))>=160
 OR EXISTS (SELECT 1 FROM offers o WHERE o.store_id=s.id AND o.verified=1 AND """ + CURRENT_OFFER_WHERE + """)
 OR EXISTS (SELECT 1 FROM store_affiliate_matches m
     JOIN affiliate_networks n ON n.id=m.network_id
     WHERE m.store_id=s.id AND m.status='approved' AND n.active=1
     AND (trim(m.affiliate_url) GLOB 'http://?*' OR trim(m.affiliate_url) GLOB 'https://?*')))
"""


def store_sitemap_where(curated=False):
    return STORE_INDEXABLE_WHERE if curated else STORE_VALID_WHERE
