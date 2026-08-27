# USCouponHub V5 — Large Store Database

## Included
- Imports `data/Stores_Final.csv` automatically on first run.
- Handles headerless or header-based 2-column CSV data.
- Deduplicates by SEO slug during import.
- SQLite indexes for fast store lookup/search.
- Search pagination (50 results per page).
- Scalable sitemap index split into 50,000-URL store sitemaps.

## Run locally
```bash
pip install -r requirements.txt
python app.py
```

The first run imports the store CSV into `data/uscouponhub.db`. Do not delete the database after deployment unless you intend to re-import.

## Production recommendation
For initial testing SQLite is fine. For a public site with high traffic, migrate the same schema to managed PostgreSQL and set credentials through environment variables. Keep API keys and affiliate credentials out of source code.


## V6 Multi-Affiliate Architecture
- Affiliate networks are stored in the database and are disabled by default.
- Store matches require approved status and an explicit affiliate URL.
- `/go/<store-slug>/` logs a click and redirects only to an approved destination.
- Never put API keys in source code; use environment variables.
- Do not activate a network until the account/site is approved and its terms allow the intended implementation.


## eBay Browse API
- Added `/ebay/search/` for live eBay item searches.
- Set `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` as environment variables in Render.
- Default production marketplace is `EBAY_US`.
- The client secret stays server-side and is never exposed to visitors.
- eBay item search displays listings, not guaranteed coupon codes.


## eBay Marketplace Account Deletion setup

For the Production eBay keyset, configure these Render environment variables:

- `EBAY_VERIFICATION_TOKEN` - a private token you choose.
- `EBAY_ACCOUNT_DELETION_ENDPOINT` - the exact public HTTPS URL entered in eBay Developer Portal, for example `https://uscouponhub.onrender.com/ebay/account-deletion`.

In eBay Developer Portal > Alerts & Notifications > Marketplace Account Deletion, enter the same endpoint URL and the same verification token. The app responds to eBay's GET challenge with the required SHA-256 `challengeResponse` and accepts POST deletion notifications with HTTP 204.
