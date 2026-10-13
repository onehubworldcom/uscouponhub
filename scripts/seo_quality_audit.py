"""Read-only duplicate, invalid URL and thin-content review; never edits stores.

Prefer a verified production backup. Label source CSV reconstructions explicitly.
Matching names are REVIEW candidates, not proof two merchants are duplicates.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seo_eligibility import STORE_VALID_WHERE, STORE_INDEXABLE_WHERE
from seo_readonly_audit import audit as original_audit


def audit(database, source_label):
    result = {'source_label': source_label, 'pr9_baseline': original_audit(database)}
    names, descriptions = defaultdict(list), defaultdict(list)
    suspicious = []
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        def scalar(sql):
            return db.execute(sql).fetchone()[0]
        result['eligible_under_proposed_curated_rules'] = scalar(
            f'SELECT count(*) FROM stores s WHERE {STORE_INDEXABLE_WHERE}')
        invalid = list(db.execute(
            f'SELECT id,name,slug FROM stores s WHERE s.active=1 AND NOT ({STORE_VALID_WHERE})'))
        result['invalid_active_store_count'] = len(invalid)
        result['invalid_active_store_examples'] = invalid[:20]
        for sid, name, slug, description in db.execute(
                'SELECT id,name,slug,description FROM stores WHERE active=1 ORDER BY id'):
            key = re.sub(r'[^a-z0-9]+', '', (name or '').casefold())
            if key:
                names[key].append((sid, name, slug))
            if description and description.strip():
                key = ' '.join(description.casefold().split())
                descriptions[key].append((sid, name, slug))
            if re.fullmatch(r'\d{1,2}[-/](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:[-/]\d{2,4})?', (name or '').strip(), re.I):
                suspicious.append((sid, name, slug))
        duplicate_names = [group for group in names.values() if len(group)>1]
        duplicate_descriptions = [group for group in descriptions.values() if len(group)>1]
        result.update({
            'normalized_name_review_groups': len(duplicate_names),
            'stores_in_normalized_name_review_groups': sum(map(len, duplicate_names)),
            'normalized_name_review_examples': [g[:10] for g in duplicate_names[:20]],
            'repeated_description_groups': len(duplicate_descriptions),
            'stores_with_repeated_description': sum(map(len, duplicate_descriptions)),
            'date_like_name_review_count': len(suspicious),
            'date_like_name_review_examples': suspicious[:20],
            'eligibility_is_quality_review_candidate_only': True,
            'notes': ['No records deleted, renamed, redirected or modified.',
                      'Description length and affiliate approval do not prove content quality.',
                      'Review merchant identity and repeated descriptions before any canonical consolidation.'],
        })
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    parser.add_argument('--source-label', required=True,
                        help='For example: verified production backup, or source CSV reconstruction')
    args = parser.parse_args()
    print(json.dumps(audit(args.database, args.source_label), indent=2))
