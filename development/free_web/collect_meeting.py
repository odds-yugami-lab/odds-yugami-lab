"""Collect every listed race for explicit meeting IDs, then export JSON.

Not scheduled. No model, prior-performance update, or GitHub writer.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import urllib.request
from result_store import save_result

def download_result(race_id):
    url = "https://sports.yahoo.co.jp/keiba/race/result/" + race_id
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            page = response.read().decode("utf-8")
        return race_id, page, url, dt.datetime.now(dt.timezone.utc).isoformat(), None
    except Exception as e:
        return race_id, None, url, None, str(e)

def list_races(meeting_id):
    if not re.fullmatch(r"\d{8}", meeting_id):
        raise ValueError("Invalid meeting ID")
    url = "https://sports.yahoo.co.jp/keiba/race/list/" + meeting_id
    with urllib.request.urlopen(url, timeout=30) as r:
        page = r.read().decode("utf-8")
    ids = sorted(set(re.findall(r'/keiba/race/(?:index|result|denma)/(\d{10})', page)))
    ids = [i for i in ids if i.startswith(meeting_id)]
    if not ids:
        raise ValueError("No races discovered")
    return ids

def collect(con, meeting_ids, export_path):
    expected = []
    failures = []
    counts = {}
    for meeting in meeting_ids:
        try:
            ids = list_races(meeting)
        except Exception as e:
            failures.append({"meeting": meeting, "error": str(e)})
            continue
        expected.extend(ids)
        # Downloads only are parallel; all SQLite mutations remain sequential.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for race, page, url, stamp, error in pool.map(download_result, ids):
                try:
                    if error:
                        raise ValueError(error)
                    counts[race] = save_result(con, page, race, url, stamp)
                    print(race, counts[race], flush=True)
                except Exception as e:
                    failures.append({"race": race, "error": str(e)})
                    print(race, "FAILED", str(e), flush=True)
    result = {"purpose": "post_race_ingestion", "is_pre_race_prediction": False,
              "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "meetings": meeting_ids, "expected_races": expected,
              "successful_races": counts, "failures": failures, "races": []}
    for race in sorted(counts):
        records = con.execute("SELECT payload,source_url,last_seen_at,page_sha256 FROM results WHERE race_id=? ORDER BY horse_number", (race,)).fetchall()
        result["races"].append({"race_id": race, "source_url": records[0][1],
                               "retrieved_at": records[0][2], "page_sha256": records[0][3],
                               "rows": [json.loads(r[0]) for r in records]})
    result["complete"] = not failures and len(counts) == len(set(expected))
    Path(export_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("meetings", nargs="+")
    p.add_argument("--db", default="free_results.sqlite")
    p.add_argument("--output", default="results.json")
    args = p.parse_args()
    with sqlite3.connect(args.db) as con:
        result = collect(con, args.meetings, args.output)
    print("Complete:", result["complete"], "Rows:", sum(result["successful_races"].values()))
    raise SystemExit(0 if result["complete"] else 1)
