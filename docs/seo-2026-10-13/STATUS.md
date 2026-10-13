# USCouponHub SEO continuation — 13 October 2026

Continues draft PR #9 at `db03b8432ae6a97f5431ac41fc2ad601e238f581`.
Production Render deployment was `39a2f0fe4f4dd514dfe2fab98451fe25b295c158`.
This branch has NOT been deployed. No production database, service setting,
store record or Search Console validation state was changed.

## Verified public checks

| Check | Observed result |
| --- | --- |
| Main sitemap | HTTP 200; seven children |
| Store sitemaps 1–5 | HTTP 200; valid XML; 50,000 URLs each |
| Store sitemap 6 | HTTP 200; valid XML; 38,414 URLs |
| Static sitemap | HTTP 200; valid XML; 64 URLs |
| Nine exported 5xx URLs | All currently HTTP 200 |
| Eight exported crawled/not-indexed URLs | All currently HTTP 200, index/follow, self-canonical |
| robots.txt during this check | HTTP 200; permits public pages; advertises main sitemap |
| `/2020ave-coupon-code/` | HTTP 404; slashless URL is HTTP 200 |
| Very large `/stores/?page=...` | Reproduced HTTP 500 with a 32-digit page number |

The live XML contains 288,478 URLs: 288,414 stores and 64 static pages.
This is not an indexed-page count. The nine exported 5xx examples were last
crawled in September; their current successful HTTP responses do not prove
Google has recrawled them. Raw results are in `live-checks.csv` and
`live-page-sample.json` beside this document.

The sampled store pages showed generic merchant text and automatic deal
cards. Three Daniel Wellington URL variants all returned 200 with their own
canonical URLs; investigate consolidation after checking the production data.

## Source-data audit — NOT production database verification

The unmodified PR #9 audit was run on a disposable database reconstructed
using the repository's own CSV importer. `quick_check=ok` and 288,414 stores
were preserved. No store in this reconstruction has a description, verified
offer or approved affiliate match, so its curated-eligible count is zero.

The supplementary read-only audit found:

- 24,014 normalized-name review groups covering 51,020 records.
- Five date-like names: `17-Jun`, `10-May`, `26-May`, `30-Oct`, `17-Oct`.
- Zero malformed active slugs under the proposed URL checks.

Name matching is a review signal, not proof of identical merchant identity.
No records were merged/deleted or renamed; no merchant canonical mapping was
guessed. Counts and examples are in `source-quality-audit.json`.

## Changes prepared

- Bound pagination before SQLite OFFSET, and redirect invalid or clamped
  page parameters to the corresponding directory URL.
- Link directly to slashless store URLs and redirect valid old slash URLs.
- Render stored merchant descriptions with HTML escaping.
- Add store-directory breadcrumbs and numbered directory links; remove the
  “related stores” search link that returned to the same merchant.
- Use the same eligibility SQL for sitemap inclusion and store robots tags.
- Reject malformed/reserved sitemap URL segments without editing records.
- Ignore expired, malformed-expiry and retired marketplace offers when
  displaying current offers or qualifying stores in curated mode.
- Serialize store structured-data strings safely as JSON.
- Add read-only quality review and verified SQLite snapshot tools.

`CURATED_STORE_INDEXING_ENABLED` remains OFF by default. Do not enable it on
production until its real inventory and content-enrichment plan have been
reviewed: the repository reconstruction would otherwise remove every store
from the sitemap. Description length and affiliate approval alone do not
establish useful, original content or guarantee indexing.

## Validation

All checks passed locally using disposable databases:

```text
SEO_RECOVERY_CHECK=PASS
STORES_PRESERVED=100
SEO_QUALITY_CHECK=PASS
SEO_FULL_DATASET_CHECK=PASS
TOTAL_STORES=288414
STORE_SITEMAP_PARTS=6
```

The new checks cover the reproduced pagination error, canonical/slash links,
unknown-store 404s, expired offers, sitemap/robots agreement, unchanged store
rows, and a SQLite WAL backup with an integrity check and matching contents.
Backup checks also verify refusal to overwrite the source or an existing
destination and refusal to create a missing source database. CI runs these
checks on pull requests to main.

## Production backup and deployment gates

The connected Render service `uscouponhub` in the confirmed My Workspace is
on the Free compute plan, with auto-deploy enabled for `main`. Render's API
reported the service live and not suspended. No recent matching error logs
were returned by the initial error-log query; this is not evidence that no
errors occur.

Render Free has no SSH/dashboard shell, one-off jobs or persistent disks.
Its local files, including SQLite, are ephemeral. The app has no existing
database-export route, and the Render connector cannot read its SQLite file.
The repository's two tracked `.db` files are zero-byte placeholders, not
production backups. Therefore, a verified live database backup has NOT yet
been obtained. Do not trigger a deploy, restart, plan change or merge to main
as a way to gain access: any restart may lose current local data.

The next gate is a supported export of the *currently running* SQLite file,
for example a host-assisted snapshot arranged with Render. No support
message has been sent. If the file is made accessible without restarting,
the prepared tool can create and verify a new snapshot:

```bash
python scripts/backup_sqlite_verified.py /absolute/path/to/existing-production.db /existing/secure-backup-dir/new-snapshot.sqlite
python scripts/seo_readonly_audit.py /existing/secure-backup-dir/new-snapshot.sqlite
python scripts/seo_quality_audit.py /existing/secure-backup-dir/new-snapshot.sqlite --source-label 'Verified production snapshot'
```

Replace the example paths with observed paths; do not create a new database
at the source path. Keep the snapshot and its `.verified.json` manifest
off-host, compare counts/content, and confirm durable storage and recovery
before deploying. The backup contains the whole database and belongs in a
private backup location, never in this GitHub repository.

After those gates: rerun all tests against a *copy*, deploy the reviewed
commit, verify all seven current sitemap URLs (or the deliberately revised
set), inspect representative canonicals and robots tags, and check the
exported error URLs. Only then validate eligible fixes in Search Console.

## Search Console access

The Cloud Browser had no signed-in Search Console session. Google sign-in
returned a 502 connection-refused error. Automatic approval review rejected
a retry because the authentication failure required stopping. No live GSC
counts, sitemap submission, URL inspection or “Validate fix” action was
completed. The user-supplied GSC figures and saved exports remain the latest
available GSC evidence, not newly observed dashboard values.

## Primary references

- [Render Free service limitations](https://render.com/docs/free): ephemeral
  SQLite, no shell/disks, idle spin-down and automatic disallow-all robots.txt
  while asleep. These are crawl reliability risks, not a proven explanation
  for the historical nine errors.
- [Render shell compatibility](https://render.com/docs/ssh).
- [Google sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).
- [Google canonical guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls).
