import csv, os, re, sqlite3
from affiliate import get_match, get_networks, build_destination, log_click
from datetime import datetime
from flask import Flask, render_template, abort, Response, request, url_for, redirect

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get('DATABASE_PATH', os.path.join(BASE,'data','uscouponhub.db'))
CSV_FILE=os.environ.get('STORES_CSV', os.path.join(BASE,'data','Stores_Final.csv'))
app=Flask(__name__)
@app.route("/")
def home():
    return render_template("home.html")
STATES={'california':'California','texas':'Texas','florida':'Florida','new-york':'New York','illinois':'Illinois','pennsylvania':'Pennsylvania','ohio':'Ohio','georgia':'Georgia','north-carolina':'North Carolina','michigan':'Michigan'}
CITIES={'new-york':'New York, NY','los-angeles':'Los Angeles, CA','chicago':'Chicago, IL','houston':'Houston, TX','phoenix':'Phoenix, AZ','philadelphia':'Philadelphia, PA','san-antonio':'San Antonio, TX','san-diego':'San Diego, CA','dallas':'Dallas, TX','san-jose':'San Jose, CA'}
CATEGORIES=['fashion','electronics','beauty','home-garden','travel','food-drink','software','baby-kids']
RESERVED={'states','cities','categories','seasonal','search','sitemap.xml','robots.txt','static','favicon.ico'}

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    return c

def clean_slug(value):
    value=(value or '').strip().lower()
    value=re.sub(r'[^a-z0-9]+','-',value).strip('-')
    return value

def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c=conn()
    c.execute('''CREATE TABLE IF NOT EXISTS stores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        category TEXT DEFAULT 'Shopping',
        description TEXT,
        active INTEGER DEFAULT 1
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_stores_slug ON stores(slug)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_stores_name ON stores(name COLLATE NOCASE)')
    c.execute('''CREATE TABLE IF NOT EXISTS affiliate_networks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, priority INTEGER DEFAULT 100, active INTEGER DEFAULT 0, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS affiliate_merchants (id INTEGER PRIMARY KEY AUTOINCREMENT, network_id INTEGER NOT NULL, merchant_name TEXT NOT NULL, merchant_domain TEXT, merchant_external_id TEXT, status TEXT DEFAULT 'pending', UNIQUE(network_id, merchant_external_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS store_affiliate_matches (id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL, network_id INTEGER NOT NULL, merchant_id INTEGER, affiliate_url TEXT, status TEXT DEFAULT 'pending', match_method TEXT DEFAULT 'manual', confidence REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS affiliate_clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER, match_id INTEGER, network_id INTEGER, clicked_at TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_match_store ON store_affiliate_matches(store_id, status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_click_store ON affiliate_clicks(store_id)')
    for priority, slug, name in [(1,'sovrn','Sovrn Commerce'),(2,'awin','Awin'),(3,'cj','CJ Affiliate'),(4,'impact','Impact'),(5,'rakuten','Rakuten Advertising'),(6,'ebay','eBay Partner Network')]:
        c.execute('INSERT OR IGNORE INTO affiliate_networks(name,slug,priority,active,created_at) VALUES (?,?,?,?,?)',(name,slug,priority,0,datetime.utcnow().isoformat()))
    count=c.execute('SELECT COUNT(*) FROM stores').fetchone()[0]
    if count==0 and os.path.exists(CSV_FILE):
        batch=[]; seen=set()
        with open(CSV_FILE,newline='',encoding='utf-8-sig',errors='ignore') as f:
            for row in csv.reader(f):
                if len(row)<2: continue
                name=row[0].strip(); slug=clean_slug(row[1])
                if not name or not slug or name.lower() in {'store name','name'} or slug in RESERVED: continue
                if slug in seen: continue
                seen.add(slug); batch.append((name,slug))
                if len(batch)>=5000:
                    c.executemany('INSERT OR IGNORE INTO stores(name,slug) VALUES (?,?)',batch); c.commit(); batch=[]
        if batch: c.executemany('INSERT OR IGNORE INTO stores(name,slug) VALUES (?,?)',batch)
    c.commit(); c.close()

@app.context_processor
def globals_ctx():
    return {'current_year':datetime.now().year,'site_name':'US Coupon Hub','states':STATES,'cities':CITIES,'categories':CATEGORIES,'format_number':lambda n:f'{n:,}'}

@app.route('/')
def home():
    c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT 12').fetchall(); total=c.execute('SELECT COUNT(*) FROM stores WHERE active=1').fetchone()[0]; c.close()
    return render_template('home.html',stores=stores,total=total)

@app.route('/search/')
def search_page():
    q=request.args.get('q','').strip(); page=max(1,int(request.args.get('page',1))); per_page=50; offset=(page-1)*per_page
    c=conn()
    if q:
        pattern=f'%{q}%'; total=c.execute('SELECT COUNT(*) FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?)',(pattern,pattern)).fetchone()[0]
        results=c.execute('SELECT * FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?) ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?',(pattern,pattern,per_page,offset)).fetchall()
    else:
        total=c.execute('SELECT COUNT(*) FROM stores WHERE active=1').fetchone()[0]
        results=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?',(per_page,offset)).fetchall()
    c.close(); return render_template('search.html',q=q,results=results,page=page,total=total,per_page=per_page)

@app.route('/<slug>')
def store_page(slug):
    if slug in RESERVED: abort(404)
    c=conn(); store=c.execute('SELECT * FROM stores WHERE slug=? AND active=1',(slug,)).fetchone()
    if not store: c.close(); abort(404)
    first=(store['name'] or '')[:1]
    related=c.execute('SELECT * FROM stores WHERE active=1 AND slug<>? AND name LIKE ? COLLATE NOCASE ORDER BY name LIMIT 6',(slug,f'{first}%')).fetchall()
    if len(related)<6:
        extra=c.execute('SELECT * FROM stores WHERE active=1 AND slug<>? ORDER BY name COLLATE NOCASE LIMIT ?',(slug,6-len(related))).fetchall(); related=list(related)+list(extra)
    match=get_match(c, store['id']); c.close(); return render_template('store.html',store=store,related=related,affiliate_match=match)

@app.route('/go/<slug>/')
def affiliate_go(slug):
    if slug in RESERVED: abort(404)
    c=conn(); store=c.execute('SELECT * FROM stores WHERE slug=? AND active=1',(slug,)).fetchone()
    if not store: c.close(); abort(404)
    match=get_match(c,store['id']); destination=build_destination(match)
    if not destination:
        c.close(); return redirect(url_for('store_page',slug=slug))
    log_click(c,store['id'],match['id'],match['network_id']); c.close()
    return redirect(destination, code=302)

@app.route('/affiliate-disclosure/')
def affiliate_disclosure():
    return render_template('affiliate_disclosure.html')

@app.route('/affiliate-status/')
def affiliate_status():
    c=conn(); networks=get_networks(c); c.close()
    return render_template('affiliate_status.html',networks=networks)

@app.route('/states/<state_slug>/')
def state_page(state_slug):
    if state_slug not in STATES: abort(404)
    c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT 18').fetchall(); c.close(); return render_template('state.html',state=STATES[state_slug],stores=stores)

@app.route('/cities/<city_slug>/')
def city_page(city_slug):
    if city_slug not in CITIES: abort(404)
    c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT 12').fetchall(); c.close(); return render_template('city.html',city=CITIES[city_slug],stores=stores)

@app.route('/categories/<category_slug>/')
def category_page(category_slug):
    if category_slug not in CATEGORIES: abort(404)
    category=category_slug.replace('-',' ').title(); c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT 24').fetchall(); c.close(); return render_template('category.html',category=category,stores=stores)

@app.route('/seasonal/<event_slug>/')
def seasonal_page(event_slug): return render_template('seasonal.html',event=event_slug.replace('-',' ').title())

@app.route('/sitemap.xml')
def sitemap_index():
    c=conn(); total=c.execute('SELECT COUNT(*) FROM stores WHERE active=1').fetchone()[0]; c.close(); parts=(total+49999)//50000; base='https://uscouponhub.com'
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<sitemap><loc>{base}/sitemap-stores-{i}.xml</loc></sitemap>' for i in range(1,parts+1))+f'<sitemap><loc>{base}/sitemap-static.xml</loc></sitemap></sitemapindex>',mimetype='application/xml')

@app.route('/sitemap-static.xml')
def sitemap_static():
    base='https://uscouponhub.com'; urls=[f'{base}/']+[f'{base}/states/{s}/' for s in STATES]+[f'{base}/cities/{x}/' for x in CITIES]+[f'{base}/categories/{x}/' for x in CATEGORIES]
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{u}</loc></url>' for u in urls)+'</urlset>',mimetype='application/xml')

@app.route('/sitemap-stores-<int:part>.xml')
def sitemap_stores(part):
    per=50000; offset=(part-1)*per; c=conn(); rows=c.execute('SELECT slug FROM stores WHERE active=1 ORDER BY id LIMIT ? OFFSET ?',(per,offset)).fetchall(); c.close(); base='https://uscouponhub.com'
    if not rows: abort(404)
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{base}/{r["slug"]}</loc></url>' for r in rows)+'</urlset>',mimetype='application/xml')

@app.route('/robots.txt')
def robots(): return Response('User-agent: *\nAllow: /\nSitemap: https://uscouponhub.com/sitemap.xml\n',mimetype='text/plain')

init_db()
if __name__=='__main__': app.run(debug=True)
