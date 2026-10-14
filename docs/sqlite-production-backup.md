# USCouponHub: protect production SQLite before changing Render

Status (2026-10-14): The `uscouponhub` service is on Render's **Free** plan. No persistent disk is shown in the service configuration. Its repository SQLite files are placeholders and do **not** contain a verified production backup.

## Immediate safety rule

**Do not merge PR #16, trigger a deploy, change the service plan, add a disk, restart, or spin down the service with the expectation that its current local SQLite data will survive.** Render documents that Free web services lose filesystem changes when they restart, deploy, or spin down. Free web services do not provide SSH or dashboard Shell. Attaching a disk itself triggers a deploy.

A store count matching `Stores_Final.csv` does not demonstrate safety: `init_db()` can repopulate stores when SQLite is empty, but previously saved descriptions, offers and affiliate information may be absent.

## First: check whether an independent backup exists

1. Search the owner's private backups outside Render (local PC, private cloud storage, historical exports) for a **nonempty populated** `uscouponhub.db`. Do not confuse it with the GitHub zero-byte placeholder.
2. Check whether `DATABASE_PATH` points to an independently persisted database location. Avoid exposing private env values or secrets publicly.
3. If no backup exists, ask **Render support** whether there is a safe way to export the SQLite file from the **currently running Free service instance without restarting/redeploying/changing its plan**. Explain that the database could contain unique offers, descriptions and approved affiliate records. Do not assume support can recover it.
4. If there is no supported non-disruptive retrieval option, explicitly decide whether the existing state can be reconstructed from the CSV and other private records before making any hosting changes.

## Safe backup procedure once the CURRENT populated database is accessible

**Only perform this on a filesystem copy or in a shell that connects to the current instance without replacing it.** This repo's backup script is not on the current deployed Free instance; do not redeploy merely to install it.

Once the script is available in a safe environment:

```bash
mkdir -p /secure/private-backups
python scripts/sqlite_hot_backup.py --db /absolute/path/to/uscouponhub.db --dest /secure/private-backups
```

The script:
- Opens the source SQLite database read-only.
- Uses SQLite's consistent online `backup()` mechanism.
- Refuses missing, corrupt, empty, or improperly structured databases.
- Checks the backup's SQLite integrity and compares source/backup counts.
- Creates a unique snapshot without overwriting an existing backup.
- Writes a `.json` manifest with counts, timestamp and SHA-256.

**Copy both files off the running Render instance immediately** to private offline storage, and verify the recorded SHA-256 and a fresh `PRAGMA quick_check` on the downloaded snapshot. Treat affiliate data as sensitive and never publish the snapshot in GitHub or as a website download.

## After the backup is independently verified

1. Run `python scripts/seo_readonly_audit.py /path/to/backup.db --duplicate-csv /path/to/review.csv`.
2. Compare live/backup store totals and offers, approved affiliate data, descriptions and duplicate names.
3. Design storage that persists across restarts: a paid Render service with a correctly mounted persistent disk, or a managed database migration with tested import/restore. **A paid plan without a persistent disk is not sufficient for SQLite durability.**
4. Test restore, permissions, startup path (`DATABASE_PATH`) and app behavior in staging first.
5. Only then release PR #16, verify affected routes, store counts, offers, sitemap and Google Search Console.

## Why this procedure is separate from PR #16

PR #16 contains the SEO behavior changes and remains draft. This backup utility has **no runtime changes to the web application** and is safe to review independently. Creating a tool in GitHub is not the same as recovering the current Render database.

References: https://render.com/docs/free , https://render.com/docs/disks , https://render.com/docs/ssh
