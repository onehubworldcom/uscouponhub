import csv, os, re, sqlite3, hashlib, base64, json, time
from urllib import request as urlrequest, parse as urlparse, error as urlerror
from affiliate import get_match, get_networks, build_destination, log_click
from datetime import datetime
from flask import Flask, render_template, abort, Response, request, url_for, redirect

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get('DATABASE_PATH', os.path.join(BASE,'data','uscouponhub.db'))
CSV_FILE=os.environ.get('STORES_CSV', os.path.join(BASE,'data','Stores_Final.csv'))
app=Flask(__name__)
@app.template_filter('format_number')
def format_number(value):
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return value
STATES={'california':'California','texas':'Texas','florida':'Florida','new-york':'New York','illinois':'Illinois','pennsylvania':'Pennsylvania','ohio':'Ohio','georgia':'Georgia','north-carolina':'North Carolina','michigan':'Michigan'}
CITIES={'new-york':'New York, NY','los-angeles':'Los Angeles, CA','chicago':'Chicago, IL','houston':'Houston, TX','phoenix':'Phoenix, AZ','philadelphia':'Philadelphia, PA','san-antonio':'San Antonio, TX','san-diego':'San Diego, CA','dallas':'Dallas, TX','san-jose':'San Jose, CA'}
CATEGORIES=['shopping','fashion','electronics','beauty','home-garden','travel','food-drink','software','baby-kids']
RESERVED={'states','cities','categories','seasonal','search','sitemap.xml','robots.txt','static','favicon.ico'}


CATEGORY_CONFIG={
    'shopping': {'label':'Shopping','aliases':['shopping','deals','stores'], 'query':'shopping deals', 'subcategories':['Department Stores','Deals','Gift Cards']},
    'fashion': {'label':'Fashion','aliases':['fashion','clothes','clothing','apparel','shoes'], 'query':'fashion clothing shoes', 'subcategories':['Women’s Fashion','Men’s Fashion','Shoes','Accessories']},
    'electronics': {'label':'Electronics','aliases':['electronics','tech','technology','gadgets'], 'query':'electronics', 'subcategories':['Phones & Tablets','Laptops & Computers','TV & Home Theater','Gaming','Cameras']},
    'beauty': {'label':'Beauty','aliases':['beauty','makeup','skincare','skin care','cosmetics'], 'query':'beauty skincare makeup', 'subcategories':['Makeup','Skin Care','Hair Care','Fragrance']},
    'home-garden': {'label':'Home & Garden','aliases':['home','garden','furniture','home decor'], 'query':'home garden', 'subcategories':['Furniture','Home Decor','Kitchen','Garden']},
    'travel': {'label':'Travel','aliases':['travel','hotel','hotels','flights'], 'query':'travel accessories', 'subcategories':['Hotels','Flights','Luggage','Travel Accessories']},
    'food-drink': {'label':'Food & Drink','aliases':['food','drink','groceries','grocery'], 'query':'food kitchen', 'subcategories':['Groceries','Restaurants','Coffee & Tea','Kitchen']},
    'software': {'label':'Software','aliases':['software','apps','app','digital'], 'query':'software', 'subcategories':['Security','Productivity','Creative','Business']},
    'baby-kids': {'label':'Baby & Kids','aliases':['baby','kids','children','toys'], 'query':'baby kids', 'subcategories':['Baby Gear','Kids Clothing','Toys','School']},
}

# Smart eBay search mapping. Generic directory labels can produce unrelated
# marketplace results, so translate them into product-focused searches.
SMART_EBAY_SEARCH = {
    'shopping': ['popular shopping products', 'electronics home fashion'],
    'deals': ['clearance deals new products', 'sale items free shipping'],
    'department stores': ['department store clothing home goods', 'brand name retail clothing home'],
    'department store': ['department store clothing home goods', 'brand name retail clothing home'],
    'gift cards': ['gift cards digital codes', 'apple amazon visa gift cards'],
    'gift card': ['gift cards digital codes', 'apple amazon visa gift cards'],
    'fashion': ['new clothing shoes accessories', 'fashion apparel deals'],
    'electronics': ['consumer electronics phones laptops', 'electronics accessories new'],
    'beauty': ['beauty skincare makeup new', 'makeup fragrance skincare'],
    'home & garden': ['home kitchen garden products', 'home decor furniture deals'],
    'travel': ['travel luggage accessories', 'travel bags organizers'],
    'food & drink': ['kitchen food storage coffee', 'kitchen cookware accessories'],
    'software': ['software digital license', 'computer software license'],
    'baby & kids': ['baby gear kids toys', 'baby clothing toys'],
}

def smart_ebay_queries(query, category=''):
    normalized = normalize_search_query(query)
    cat = normalize_search_query(category)
    candidates = []
    if normalized in SMART_EBAY_SEARCH:
        candidates.extend(SMART_EBAY_SEARCH[normalized])
    else:
        if normalized:
            candidates.append((query or '').strip())
        simplified = re.sub(r'^[0-9][0-9.\-\s]*', '', query or '').strip()
        if simplified and normalize_search_query(simplified) != normalized:
            candidates.append(simplified)
        if cat in SMART_EBAY_SEARCH:
            candidates.extend(SMART_EBAY_SEARCH[cat])
        else:
            category_slug = category_from_query(cat) if cat else None
            if category_slug:
                candidates.append(CATEGORY_CONFIG[category_slug].get('query', category_slug.replace('-', ' ')))
    seen=set(); ordered=[]
    for candidate in candidates:
        candidate=(candidate or '').strip(); key=normalize_search_query(candidate)
        if candidate and key not in seen:
            seen.add(key); ordered.append(candidate)
    return ordered[:4]


def category_from_query(value):
    normalized=normalize_search_query(value) if 'normalize_search_query' in globals() else (value or '').strip().lower()
    for slug, cfg in CATEGORY_CONFIG.items():
        if normalized == slug or normalized in cfg['aliases']:
            return slug
    return None

# eBay Browse API integration
# Credentials stay in Render environment variables and are never sent to the browser.
_EBAY_TOKEN = None
_EBAY_TOKEN_EXPIRES_AT = 0
_EBAY_LAST_ERROR = None

def ebay_api_base():
    env = os.environ.get('EBAY_ENV', 'production').strip().lower()
    return 'https://api.sandbox.ebay.com' if env == 'sandbox' else 'https://api.ebay.com'

def ebay_get_application_token():
    global _EBAY_TOKEN, _EBAY_TOKEN_EXPIRES_AT, _EBAY_LAST_ERROR
    now = time.time()
    _EBAY_LAST_ERROR = None

    if _EBAY_TOKEN and now < (_EBAY_TOKEN_EXPIRES_AT - 60):
        return _EBAY_TOKEN

    client_id = os.environ.get('EBAY_CLIENT_ID', '').strip()
    client_secret = os.environ.get('EBAY_CLIENT_SECRET', '').strip()
    if not client_id or not client_secret:
        _EBAY_LAST_ERROR = 'Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET.'
        return None

    basic = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8')).decode('ascii')
    body = urlparse.urlencode({
        'grant_type': 'client_credentials',
        'scope': 'https://api.ebay.com/oauth/api_scope'
    }).encode('utf-8')

    req = urlrequest.Request(
        ebay_api_base() + '/identity/v1/oauth2/token',
        data=body,
        headers={
            'Authorization': 'Basic ' + basic,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        },
        method='POST'
    )

    try:
        with urlrequest.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urlerror.HTTPError as exc:
        try:
            raw = exc.read().decode('utf-8', errors='replace')[:500]
            data = json.loads(raw)
            message = data.get('error_description') or data.get('message') or data.get('error')
        except Exception:
            message = None
        _EBAY_LAST_ERROR = f'OAuth HTTP {exc.code}' + (f': {message}' if message else '')
        return None
    except urlerror.URLError as exc:
        _EBAY_LAST_ERROR = f'OAuth connection error: {exc.reason}'
        return None
    except TimeoutError:
        _EBAY_LAST_ERROR = 'OAuth request timed out.'
        return None
    except ValueError:
        _EBAY_LAST_ERROR = 'OAuth returned an invalid response.'
        return None

    token = payload.get('access_token')
    if not token:
        _EBAY_LAST_ERROR = 'OAuth response did not contain an access token.'
        return None

    _EBAY_TOKEN = token
    _EBAY_TOKEN_EXPIRES_AT = now + max(60, int(payload.get('expires_in', 7200)))
    return _EBAY_TOKEN

def ebay_search_items(query, limit=12):
    token = ebay_get_application_token()
    if not token:
        return None, _EBAY_LAST_ERROR or 'eBay OAuth is not available yet.'

    params = urlparse.urlencode({
        'q': query,
        'limit': max(1, min(int(limit), 50))
    })
    req = urlrequest.Request(
        ebay_api_base() + '/buy/browse/v1/item_summary/search?' + params,
        headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/json',
            'X-EBAY-C-MARKETPLACE-ID': os.environ.get('EBAY_MARKETPLACE_ID', 'EBAY_US')
        }
    )
    try:
        with urlrequest.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urlerror.HTTPError as exc:
        return None, f'eBay search is temporarily unavailable (HTTP {exc.code}).'
    except (urlerror.URLError, ValueError, TimeoutError):
        return None, 'eBay search is temporarily unavailable.'

    items = []
    for item in payload.get('itemSummaries', []):
        price = item.get('price') or {}
        image = (item.get('image') or {}).get('imageUrl', '')
        shipping = item.get('shippingOptions') or []
        shipping_cost = ''
        if shipping and shipping[0].get('shippingCost'):
            sc = shipping[0]['shippingCost']
            if sc.get('value') not in (None, ''):
                shipping_cost = f"{sc.get('currency', '')} {sc.get('value', '')}".strip()
        items.append({
            'title': item.get('title', 'eBay item'),
            'price': f"{price.get('currency', '')} {price.get('value', '')}".strip(),
            'image': image,
            'url': item.get('itemWebUrl', ''),
            'condition': item.get('condition', ''),
            'shipping': shipping_cost
        })
    return items, None

def ebay_items_match_query(items, query):
    # Only enforce relevance for specific store/brand searches. Generic labels
    # intentionally use mapped product searches and should not be filtered here.
    generic={'store','stores','shop','shopping','deal','deals','boutique','online'}
    words=[w for w in re.findall(r'[a-z0-9]+', normalize_search_query(query)) if len(w)>=3 and w not in generic and not w.isdigit()]
    if not words:
        return True
    sample=' '.join((item.get('title') or '').lower() for item in (items or [])[:6])
    return any(word in sample for word in words)

def ebay_search_smart(query, category='', limit=12):
    queries=smart_ebay_queries(query, category)
    if not queries:
        return [], None, ''
    last_error=None
    original_normalized=normalize_search_query(query)
    for index, candidate in enumerate(queries):
        items, error=ebay_search_items(candidate, limit=limit)
        if items:
            # If an exact store search returns clearly unrelated items, continue
            # to the alternate query/category instead of showing bad matches.
            if index == 0 and original_normalized not in SMART_EBAY_SEARCH and not ebay_items_match_query(items, candidate) and len(queries) > 1:
                continue
            return items, None, candidate
        if error:
            last_error=error
    return [], last_error, queries[0]


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
    # Privacy-friendly search analytics: no IPs, cookies, or account identifiers.
    c.execute('''CREATE TABLE IF NOT EXISTS search_events (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, normalized_query TEXT NOT NULL, route_type TEXT NOT NULL, matched_slug TEXT, results_count INTEGER DEFAULT 0, created_at TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        code TEXT,
        offer_type TEXT DEFAULT 'code',
        badge TEXT DEFAULT 'OFFER',
        verified INTEGER DEFAULT 0,
        expires_at TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_offers_store ON offers(store_id, active)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_match_store ON store_affiliate_matches(store_id, status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_click_store ON affiliate_clicks(store_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_search_events_query ON search_events(normalized_query, created_at)')
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

def normalize_search_query(value):
    value=(value or '').strip().lower()
    value=re.sub(r'\s+',' ',value)
    return value[:180]

def classify_search(c, q):
    """Choose the best internal destination without sending users off-site."""
    normalized=normalize_search_query(q)
    if not normalized:
        return 'directory', None, 0
    q_slug=clean_slug(normalized)
    exact=c.execute('SELECT * FROM stores WHERE active=1 AND (slug=? OR lower(name)=?) LIMIT 1',(q_slug,normalized)).fetchone()
    if exact:
        return 'store', exact['slug'], 1
    category_slug=category_from_query(normalized)
    if category_slug:
        return 'category', category_slug, 1
    pattern=f'%{normalized}%'
    count=c.execute('SELECT COUNT(*) FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?)',(pattern,pattern)).fetchone()[0]
    if count==1:
        one=c.execute('SELECT slug FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?) LIMIT 1',(pattern,pattern)).fetchone()
        if one:
            return 'store', one['slug'], count
    return ('directory' if count else 'ebay'), None, count

def log_search(c, q, route_type, matched_slug=None, results_count=0):
    if not q:
        return
    c.execute('INSERT INTO search_events(query,normalized_query,route_type,matched_slug,results_count,created_at) VALUES (?,?,?,?,?,?)',(q[:180],normalize_search_query(q),route_type,matched_slug,results_count,datetime.utcnow().isoformat()))
    c.commit()

@app.route('/search/')
def search_page():
    q=request.args.get('q','').strip()
    page=max(1,int(request.args.get('page',1)))
    per_page=50; offset=(page-1)*per_page
    c=conn(); route_type,target,classified_count=classify_search(c,q)
    if q and route_type=='store' and target:
        log_search(c,q,'store',target,classified_count); c.close()
        return redirect(url_for('store_page',slug=target))
    if q and route_type=='category' and target:
        log_search(c,q,'category',target,classified_count); c.close()
        return redirect(url_for('category_page',category_slug=target))
    if q and route_type=='ebay':
        log_search(c,q,'ebay',None,0); c.close()
        return redirect(url_for('ebay_search_page',q=q))
    if q:
        pattern=f'%{q}%'
        total=c.execute('SELECT COUNT(*) FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?)',(pattern,pattern)).fetchone()[0]
        results=c.execute('SELECT * FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?) ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?',(pattern,pattern,per_page,offset)).fetchall()
        log_search(c,q,'directory',None,total)
    else:
        total=c.execute('SELECT COUNT(*) FROM stores WHERE active=1').fetchone()[0]
        results=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?',(per_page,offset)).fetchall()
    c.close()
    return render_template('search.html',q=q,results=results,page=page,total=total,per_page=per_page)

@app.route('/search-insights/')
def search_insights():
    days=max(1,min(365,int(request.args.get('days',30))))
    c=conn(); since=f'-{days} days'
    summary=c.execute("SELECT COUNT(*) AS searches, COUNT(DISTINCT normalized_query) AS unique_queries FROM search_events WHERE created_at >= datetime(\'now\', ?)",(since,)).fetchone()
    top=c.execute("SELECT normalized_query, COUNT(*) AS volume, SUM(CASE WHEN route_type=\'store\' THEN 1 ELSE 0 END) AS store_matches, SUM(CASE WHEN route_type=\'category\' THEN 1 ELSE 0 END) AS category_matches, SUM(CASE WHEN route_type=\'ebay\' THEN 1 ELSE 0 END) AS ebay_fallbacks FROM search_events WHERE created_at >= datetime(\'now\', ?) AND normalized_query<>\'\' GROUP BY normalized_query ORDER BY volume DESC, normalized_query LIMIT 100",(since,)).fetchall()
    c.close()
    return render_template('search_insights.html',days=days,summary=summary,top=top)

@app.route('/<slug>')
def store_page(slug):
    if slug in RESERVED: abort(404)
    c=conn(); store=c.execute('SELECT * FROM stores WHERE slug=? AND active=1',(slug,)).fetchone()
    if not store: c.close(); abort(404)
    first=(store['name'] or '')[:1]
    related=c.execute('SELECT * FROM stores WHERE active=1 AND slug<>? AND name LIKE ? COLLATE NOCASE ORDER BY name LIMIT 6',(slug,f'{first}%')).fetchall()
    if len(related)<6:
        extra=c.execute('SELECT * FROM stores WHERE active=1 AND slug<>? ORDER BY name COLLATE NOCASE LIMIT ?',(slug,6-len(related))).fetchall(); related=list(related)+list(extra)
    offers=c.execute('SELECT * FROM offers WHERE store_id=? AND active=1 ORDER BY verified DESC, id DESC',(store['id'],)).fetchall()
    match=get_match(c, store['id']); c.close(); return render_template('store.html',store=store,related=related,offers=offers,affiliate_match=match)

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


@app.route('/ebay/search/')
def ebay_search_page():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    items = []
    error = None
    matched_query = ''
    if q:
        items, error, matched_query = ebay_search_smart(q, category=category)
        items = items or []
    return render_template('ebay_search.html', q=q, items=items, error=error, matched_query=matched_query, category=category)

@app.route('/ebay/debug/')
def ebay_debug():
    # Safe diagnostic endpoint: never returns credential values.
    client_id = os.environ.get('EBAY_CLIENT_ID', '').strip()
    client_secret = os.environ.get('EBAY_CLIENT_SECRET', '').strip()
    ebay_env = os.environ.get('EBAY_ENV', 'production').strip().lower()
    marketplace = os.environ.get('EBAY_MARKETPLACE_ID', 'EBAY_US').strip()

    token = ebay_get_application_token()

    return {
        'client_id_present': bool(client_id),
        'client_secret_present': bool(client_secret),
        'ebay_env': ebay_env,
        'marketplace_id': marketplace,
        'oauth_token_obtained': bool(token),
        'oauth_error': _EBAY_LAST_ERROR
    }


@app.route('/ebay/account-deletion', methods=['GET', 'POST'])
@app.route('/ebay/account-deletion/', methods=['GET', 'POST'])
def ebay_account_deletion():
    # eBay Marketplace Account Deletion notification endpoint.
    # eBay sends a GET request containing challenge_code when it validates
    # this URL. The response must contain the SHA-256 challengeResponse.
    endpoint = os.environ.get(
        'EBAY_ACCOUNT_DELETION_ENDPOINT',
        'https://uscouponhub.onrender.com/ebay/account-deletion'
    ).strip().rstrip('/')

    verification_token = os.environ.get('EBAY_VERIFICATION_TOKEN', '').strip()

    # eBay uses challenge_code. Also accept challengeCode for safe compatibility
    # with manual tests or alternate clients.
    challenge_code = (
        request.args.get('challenge_code')
        or request.args.get('challengeCode')
        or ''
    ).strip()

    if challenge_code:
        if not verification_token or not endpoint:
            return {
                'error': 'Missing eBay verification configuration.'
            }, 500

        challenge_response = hashlib.sha256(
            (challenge_code + verification_token + endpoint).encode('utf-8')
        ).hexdigest()
        return {'challengeResponse': challenge_response}, 200

    # A normal GET without a challenge is useful for health checks. It must not
    # expose secrets or configuration values.
    if request.method == 'GET':
        return {
            'status': 'eBay account deletion endpoint is ready',
            'challenge_required': True
        }, 200

    # Acknowledge actual account-deletion notifications immediately.
    # This app does not currently store eBay user records.
    return '', 204

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
    cfg=CATEGORY_CONFIG.get(category_slug, {'label':category_slug.replace('-',' ').title(),'query':category_slug.replace('-',' '),'subcategories':[]})
    category=cfg['label']
    c=conn()
    # Prefer stores explicitly assigned to this category. If the imported directory
    # has not been categorized yet, use a transparent name/keyword match rather
    # than showing an unrelated alphabetical list.
    stores=c.execute('SELECT * FROM stores WHERE active=1 AND lower(category)=? ORDER BY name COLLATE NOCASE LIMIT 24',(category.lower(),)).fetchall()
    if not stores:
        words=[w for w in re.split(r'[^a-z0-9]+', cfg['query'].lower()) if len(w)>2]
        aliases=cfg.get('aliases', [])
        terms=list(dict.fromkeys(words+aliases))[:8]
        clauses=' OR '.join(['lower(name) LIKE ?' for _ in terms])
        params=[f'%{term.lower()}%' for term in terms]
        if clauses:
            stores=c.execute(f'SELECT * FROM stores WHERE active=1 AND ({clauses}) ORDER BY name COLLATE NOCASE LIMIT 24',params).fetchall()
    c.close()
    ebay_items, ebay_error, ebay_query=ebay_search_smart(category, category=category, limit=9)
    return render_template('category.html',category=category,category_slug=category_slug,stores=stores,subcategories=cfg.get('subcategories',[]),ebay_items=ebay_items or [],ebay_error=ebay_error,ebay_query=ebay_query)

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
