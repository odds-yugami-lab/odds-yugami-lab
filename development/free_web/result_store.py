"""Free public result ingestion prototype; does not predict or publish."""
import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
import urllib.request

def text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value))).strip()

def parse_result(page, race_id):
    if not re.fullmatch(r"\d{10}", race_id):
        raise ValueError("Invalid race ID")
    tables = [t for t in re.findall(r"<table\b[^>]*>(.*?)</table>", page, re.S)
              if "着順" in t and "調教師" in t]
    if len(tables) != 1:
        raise ValueError("Result table missing or ambiguous")
    body = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", tables[0], re.S)
    if not body:
        raise ValueError("Result body missing")
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body.group(1), re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) != 9:
            raise ValueError("Unexpected column count")
        ids = {}
        for kind, value in re.findall(r'/keiba/directory/(horse|jockey|trainer)/(\d+)/', tr):
            ids[kind] = value
        if set(ids) != {"horse", "jockey", "trainer"}:
            raise ValueError("Identity missing")
        number = text(cells[2])
        if not number.isdigit() or not 1 <= int(number) <= 18:
            raise ValueError("Invalid horse number")
        row = {"race_id": race_id, "horse_id": ids["horse"],
               "jockey_id": ids["jockey"], "trainer_id": ids["trainer"],
               "horse_number": int(number), "finish_text": text(cells[0]),
               "frame": text(cells[1]), "horse_detail": text(cells[3]),
               "time_margin": text(cells[4]), "passing_last3f": text(cells[5]),
               "jockey_weight": text(cells[6]), "popularity_odds": text(cells[7])}
        rows.append(row)
    if not rows or len({r["horse_id"] for r in rows}) != len(rows) or len({r["horse_number"] for r in rows}) != len(rows):
        raise ValueError("Empty or duplicate results")
    return rows

def save_result(con, page, race_id, source_url, retrieved_at):
    rows = parse_result(page, race_id)  # validate before mutation
    stamp = dt.datetime.fromisoformat(retrieved_at)
    if stamp.tzinfo is None:
        raise ValueError("Timezone required")
    retrieved_at = stamp.astimezone(dt.timezone.utc).isoformat()
    digest = hashlib.sha256(page.encode("utf-8")).hexdigest()
    con.executescript('''
    CREATE TABLE IF NOT EXISTS fetches (
      race_id TEXT, page_sha256 TEXT, source_url TEXT, retrieved_at TEXT,
      PRIMARY KEY(race_id,page_sha256));
    CREATE TABLE IF NOT EXISTS results (
      race_id TEXT,horse_id TEXT,horse_number INTEGER,payload TEXT,
      source_url TEXT,first_seen_at TEXT,last_seen_at TEXT,page_sha256 TEXT,
      PRIMARY KEY(race_id,horse_id),UNIQUE(race_id,horse_number));
    CREATE TABLE IF NOT EXISTS revisions (
      race_id TEXT,horse_id TEXT,payload_sha256 TEXT,payload TEXT,observed_at TEXT,
      PRIMARY KEY(race_id,horse_id,payload_sha256));
    ''')
    with con:
        prior = con.execute("SELECT horse_id,horse_number FROM results WHERE race_id=?", (race_id,)).fetchall()
        if prior and set(prior) != {(r["horse_id"],r["horse_number"]) for r in rows}:
            raise ValueError("Participant set changed; manual review required")
        con.execute("INSERT OR IGNORE INTO fetches VALUES (?,?,?,?)", (race_id,digest,source_url,retrieved_at))
        for r in rows:
            payload = json.dumps(r, ensure_ascii=False, sort_keys=True)
            ph = hashlib.sha256(payload.encode()).hexdigest()
            con.execute("INSERT OR IGNORE INTO revisions VALUES (?,?,?,?,?)", (race_id,r["horse_id"],ph,payload,retrieved_at))
            con.execute('''INSERT INTO results VALUES (?,?,?,?,?,?,?,?)
              ON CONFLICT(race_id,horse_id) DO UPDATE SET
              payload=excluded.payload,source_url=excluded.source_url,
              last_seen_at=excluded.last_seen_at,page_sha256=excluded.page_sha256
              WHERE excluded.last_seen_at >= results.last_seen_at''',
              (race_id,r["horse_id"],r["horse_number"],payload,source_url,retrieved_at,retrieved_at,digest))
    return len(rows)

def fetch_and_save(con, race_id):
    url = "https://sports.yahoo.co.jp/keiba/race/result/" + race_id
    with urllib.request.urlopen(url, timeout=30) as response:
        page = response.read().decode("utf-8")
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    return save_result(con, page, race_id, url, stamp)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("race_id")
    p.add_argument("--db", default="free_results.sqlite")
    args = p.parse_args()
    with sqlite3.connect(args.db) as con:
        print("Stored result rows:", fetch_and_save(con, args.race_id))
