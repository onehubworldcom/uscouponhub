import os, sqlite3, urllib.parse
from datetime import datetime
NETWORKS = ['sovrn','awin','cj','impact','rakuten','ebay']

def get_networks(c):
    return c.execute('SELECT * FROM affiliate_networks WHERE active=1 ORDER BY priority ASC, name ASC').fetchall()

def get_match(c, store_id):
    return c.execute('''SELECT m.*, n.name AS network_name, n.slug AS network_slug
                        FROM store_affiliate_matches m JOIN affiliate_networks n ON n.id=m.network_id
                        WHERE m.store_id=? AND m.status='approved' AND n.active=1
                        ORDER BY n.priority ASC LIMIT 1''',(store_id,)).fetchone()

def build_destination(match):
    if not match: return None
    url=(match['affiliate_url'] or '').strip()
    return url if url.startswith(('http://','https://')) else None

def log_click(c, store_id, match_id, network_id):
    c.execute('INSERT INTO affiliate_clicks(store_id,match_id,network_id,clicked_at) VALUES (?,?,?,?)',
              (store_id,match_id,network_id,datetime.utcnow().isoformat()))
    c.commit()
