"""Run latest numerical/entry preparation integration from private fixtures.

The scheduled caller performs GitHub API writes and passes actual receipts
back to finish(). Tests never create an actual pre-race prediction.
"""
import datetime as dt
import json
from pathlib import Path
from integration_rehearsal import run as historical_run
from entry_link_resolver import resolve as resolve_link
from publication import confirm
from official_results import fetch_for_race
from settlement import settle

def prepare(model_dir,history_path,bundle_dir):
    bundle=Path(bundle_dir)
    manifest=json.loads((bundle/'manifest.json').read_text())
    if manifest.get('historical_test_only') is not True:raise ValueError('Test fixture required')
    evidence=json.loads((bundle/'fixtures/swan_previous_evidence.json').read_text())
    request,report=historical_run(model_dir,history_path,bundle/'fixtures/pedigree_lookup.parquet',
        (bundle/'fixtures/swan_official_entry.html').read_text(),
        (bundle/'fixtures/swan_free_entry.html').read_text(),previous_overrides=evidence)
    if not report['previous_features_all_horses_publicly_sourced'] or report['previous_record_seed_fallback_count']:
        raise ValueError('Rehearsal used stored previous feature fallback')
    request['path']='development/free_web/publication_tests/scheduled_preflight_20261013/'+report['race_code']+'.json'
    report['record_type']='scheduled_latest_pipeline_preflight'
    report['future_preparation']=json.loads((bundle/'upcoming/preparation_report.json').read_text())
    report['official_entry_links']=[resolve_link(code) for code in manifest['future_races']]
    report['prepared_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    return request,report

def finish(request,report,commit_sha,committed_content,commit_recorded_at):
    receipt,chat,draft=confirm(request,commit_sha,committed_content,commit_recorded_at)
    if draft is not None:raise ValueError('X draft should not be emitted for a test')
    record=json.loads(committed_content)
    result=fetch_for_race(record['race_code'])
    settled=settle(record,result,test_only=True)
    return dict(report,github_saved=True,chat_generated=True,settlement_checked=True,
                receipt=receipt,investment_yen=settled['investment_yen'],payout_yen=settled['payout_yen'],
                current_live_pipeline_verified=False,
                remaining_live_checks=['current_cancelled_entry_row','in_sale_complete_odds','deadline_delivery'])
