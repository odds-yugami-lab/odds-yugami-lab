"""Convert public results using verified entry metadata; append labeled history.

This is a bridge only. It cannot generate future entry metadata or certify
that all intervening race days are present. Never use it as freshness proof.
"""
import datetime as dt
import os
from pathlib import Path
import re

COLUMNS = ["race_code", "ketto_toroku_bango", "race_date", "keibajo_code",
           "track_code", "distance_m", "jockey_code", "trainer_code", "sire_code",
           "body_weight_kg", "body_weight_change_kg",
           "is_cancelled_or_excluded", "target_finish_position", "target_win", "target_top3"]

def normalize(results, entries):
    """entries keyed by (web race_id, horse_id); supplied, verified metadata."""
    output = []
    seen = set()
    for result in results:
        key = (result["race_id"], result["horse_id"])
        if key in seen:
            raise ValueError("Duplicate result key")
        seen.add(key)
        entry = entries.get(key)
        if entry is None:
            raise ValueError("Verified entry metadata missing: " + str(key))
        for name, actual in [("ketto_toroku_bango",result["horse_id"]),
                             ("jockey_code",result["jockey_id"]),
                             ("trainer_code",result["trainer_id"])]:
            if entry[name] != actual:
                raise ValueError("Entry identity mismatch: " + name)
        date = dt.date.fromisoformat(str(entry["race_date"]))
        expected_race = date.strftime("%Y%m%d") + result["race_id"][2:]
        if entry["race_code"] != expected_race or int(entry["umaban"]) != result["horse_number"]:
            raise ValueError("Race or horse-number mismatch")
        status = result["finish_text"]
        cancelled = status in {"取消", "除外"}
        if not re.fullmatch(r"\d+", status) and status not in {"取消", "除外", "中止", "失格"}:
            raise ValueError("Unknown result status: " + status)
        finish = int(status) if status.isdigit() else None
        if finish is not None and not 1 <= finish <= 18:
            raise ValueError("Invalid finish position")
        if bool(entry["is_cancelled_or_excluded"]) != cancelled:
            raise ValueError("Cancellation differs; refresh entry metadata")
        row = {name: entry[name] for name in COLUMNS if name not in {"target_finish_position","target_win","target_top3"}}
        row.update(race_date=date, target_finish_position=finish,
                   target_win=finish==1, target_top3=finish is not None and finish<=3)
        weight=re.search(r'/(\d+)\(([+-]?\d+)\)',result['horse_detail'])
        row['body_weight_kg']=int(weight.group(1)) if weight else None
        row['body_weight_change_kg']=int(weight.group(2)) if weight else None
        output.append(row)
    return output

def append_history(con, source_path, rows, output_path):
    columns = ",".join(COLUMNS)
    con.execute(f"CREATE OR REPLACE TEMP TABLE bridge_base AS SELECT {columns} FROM read_parquet(?)", [str(source_path)])
    con.execute("CREATE OR REPLACE TEMP TABLE bridge_new AS SELECT * FROM bridge_base LIMIT 0")
    con.executemany("INSERT INTO bridge_new VALUES (" + ",".join("?" for _ in COLUMNS) + ")", [[r[k] for k in COLUMNS] for r in rows])
    if con.execute('''SELECT count(*) FROM bridge_new n JOIN bridge_base b
        ON n.race_code=b.race_code AND n.ketto_toroku_bango=b.ketto_toroku_bango
        WHERE to_json(n) != to_json(b)''').fetchone()[0]:
        raise ValueError("Conflicting historical record; review required")
    con.execute('''CREATE OR REPLACE TEMP TABLE bridge_merged AS SELECT * FROM bridge_base
        UNION ALL SELECT n.* FROM bridge_new n WHERE NOT EXISTS
        (SELECT 1 FROM bridge_base b WHERE b.race_code=n.race_code
         AND b.ketto_toroku_bango=n.ketto_toroku_bango)''')
    output = Path(output_path)
    if output.resolve() == Path(source_path).resolve():
        raise ValueError("Source history must remain unchanged")
    temporary = output.with_suffix(output.suffix + ".tmp")
    con.execute("COPY bridge_merged TO ? (FORMAT PARQUET)", [str(temporary)])
    os.replace(temporary, output)
    return con.execute("SELECT count(*) FROM bridge_merged").fetchone()[0]
