"""Regression checks using disposable fixtures; never opens production data."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent

with tempfile.TemporaryDirectory() as directory:
    os.environ['DATABASE_PATH'] = str(Path(directory) / 'seo-fixture.db')
    os.environ['STORES_CSV'] = str(ROOT / 'data/test_stores.csv')
    os.environ['CURATED_STORE_INDEXING_ENABLED'] = '1'
    import sitecustomize  # exercise the Gunicorn runtime wrapper
    import app as site

    client = site.app.test_client()
    c = site.conn()
    description = 'Merchant-specific information, delivery terms and shopping guidance. ' * 4
    records = [
        ('Quality "Store" & More', 'quality-store', description),
        ('Thin Store', 'thin-store', None),
        ('Expired Store', 'expired-store', None),
        ('Current Store', 'current-store', None),
        ('Today Store', 'today-store', None),
        ('Invalid Date Store', 'invalid-date-store', None),
        ('Retired Offer Store', 'retired-offer-store', None),
        ('Bad URL', 'bad&slug', description),
        ('Reserved', 'stores', description),
    ]
    c.executemany('INSERT INTO stores(name,slug,description) VALUES (?,?,?)', records)
    for slug, expiry, kind in [('expired-store','2000-01-01','code'),
                               ('current-store','2999-01-01','code'),
                               ('today-store',c.execute("SELECT date('now')").fetchone()[0],'code'),
                               ('invalid-date-store','not-a-date','code'),
                               ('retired-offer-store',None,'ebay')]:
        sid = c.execute('SELECT id FROM stores WHERE slug=?', (slug,)).fetchone()[0]
        c.execute('INSERT INTO offers(store_id,title,verified,active,expires_at,offer_type) VALUES (?,?,1,1,?,?)',
                  (sid, 'TEST '+slug, expiry, kind))
    c.commit()
    before = list(map(tuple,c.execute('SELECT * FROM stores ORDER BY id')))
    c.close()

    ns = {'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = {el.text for el in ET.fromstring(client.get('/sitemap-stores-1.xml').data).findall('.//s:loc',ns)}
    assert urls == {'https://uscouponhub.com/'+s for s in ('quality-store','current-store','today-store')}, urls
    for slug in ['quality-store','thin-store','expired-store','current-store','today-store','invalid-date-store','retired-offer-store']:
        page = client.get('/'+slug)
        assert page.status_code == 200
        indexable = 'https://uscouponhub.com/'+slug in urls
        robots = 'index,follow' if indexable else 'noindex,follow'
        assert f'name="robots" content="{robots}"'.encode() in page.data
    for slug in ['expired-store','invalid-date-store','retired-offer-store']:
        assert ('TEST '+slug).encode() not in client.get('/'+slug).data
    assert b'TEST current-store' in client.get('/current-store').data

    page = client.get('/quality-store')
    assert description.encode() in page.data
    assert b'<link rel="canonical" href="https://uscouponhub.com/quality-store">' in page.data
    for script in re.findall(br'<script type="application/ld\+json">(.*?)</script>',page.data,re.S):
        schema = json.loads(script)
        if schema['@type'] == 'WebPage':
            assert schema['name'].startswith('Quality "Store" & More')
    links = re.findall(br'class="related-store-card" href="([^"]+)"',page.data)
    assert len(links) == len(set(links))
    assert all(not link.endswith(b'/') and client.get(link.decode()).status_code==200 for link in links)
    redirect = client.get('/quality-store/')
    assert redirect.status_code==301 and redirect.headers['Location']=='/quality-store'
    assert client.get('/unknown-missing-store/').status_code==404

    for path in ['/stores/?page=99999999999999999999999999999999',
                 '/stores/?page=0','/stores/?page=abc','/stores/?page=1']:
        assert client.get(path).status_code==301, path
        assert client.get(path,follow_redirects=True).status_code==200, path
    assert client.get('/stores/?page=2').status_code==200
    assert b'aria-label="Store page 3"' in client.get('/stores/').data
    for part in ['0','99999999999999999999999999999999','99']:
        page=client.get('/sitemap-stores-'+part+'.xml')
        assert page.status_code==404
        assert page.headers['Cache-Control']=='no-store'
    # Both modes preserve rows and reject malformed sitemap URL segments.
    site.CURATED_STORE_INDEXING_ENABLED=False
    default_map=client.get('/sitemap-stores-1.xml')
    ET.fromstring(default_map.data)
    assert b'thin-store' in default_map.data
    assert b'bad&amp;slug' not in default_map.data and b'bad&slug' not in default_map.data
    assert b'<loc>https://uscouponhub.com/stores</loc>' not in default_map.data
    with site.conn() as c:
        assert before == list(map(tuple,c.execute('SELECT * FROM stores ORDER BY id')))

    # A WAL source verifies that the online backup captures committed WAL data.
    from scripts.backup_sqlite_verified import backup
    source=Path(directory)/'wal-source.db'
    with sqlite3.connect(source) as live:
        live.execute('PRAGMA journal_mode=WAL')
        live.execute('CREATE TABLE stores(id INTEGER PRIMARY KEY, name TEXT)')
        live.execute('INSERT INTO stores VALUES (1,?)', ('Preserve me',))
        live.commit()
        destination=Path(directory)/'verified.db'
        report=backup(source,destination)
        assert report['backup_verified'] and report['tables']['stores']['rows']==1
        assert report['sha256']==hashlib.sha256(destination.read_bytes()).hexdigest()
        with sqlite3.connect(destination) as restored:
            assert restored.execute('SELECT name FROM stores').fetchone()[0]=='Preserve me'
        for target in [source,destination]:
            try:
                backup(source,target)
                raise AssertionError('Existing file was not rejected')
            except FileExistsError:
                pass
        assert live.execute('SELECT name FROM stores').fetchone()[0]=='Preserve me'
    missing=Path(directory)/'missing.db'
    try:
        backup(missing,Path(directory)/'must-not-exist.db')
        raise AssertionError('Missing source was accepted')
    except FileNotFoundError:
        assert not missing.exists()

print('SEO_QUALITY_CHECK=PASS: canonical links, pagination 500, expiry, shared eligibility, data preservation, WAL backup')
