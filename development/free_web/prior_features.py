"""Reproduce 30 prior-performance features from labeled historical Parquet.

Requires duckdb. Does not import new web results, predict, or publish.
The supplied history must contain one reliable record per race/horse.
Duplicate keys are rejected rather than silently merged.
"""
import datetime as dt

GROUPS = [
    ("horse", ["ketto_toroku_bango"]),
    ("horse_distance", ["ketto_toroku_bango", "distance_m"]),
    ("horse_course_track", ["ketto_toroku_bango", "keibajo_code", "track_code"]),
    ("jockey", ["jockey_code"]),
    ("trainer", ["trainer_code"]),
    ("sire", ["sire_code"]),
]

def calculate(con, history_path, runners, race_date):
    """Return independent feature dicts; race-day results are always excluded."""
    cutoff = dt.date.fromisoformat(race_date)
    con.execute("CREATE OR REPLACE TEMP TABLE prior_history AS SELECT * FROM read_parquet(?) WHERE race_date < ?", [str(history_path), cutoff])
    con.execute('''CREATE OR REPLACE TEMP VIEW prior_eligible AS
        SELECT * FROM prior_history WHERE NOT is_cancelled_or_excluded
        AND race_code IN (SELECT race_code FROM prior_history GROUP BY race_code
                          HAVING count(target_finish_position)>0)''')
    duplicate = con.execute('''SELECT race_code,ketto_toroku_bango FROM prior_eligible
        GROUP BY race_code,ketto_toroku_bango HAVING count(*)>1 LIMIT 1''').fetchone()
    if duplicate:
        raise ValueError("Duplicate eligible historical race/horse keys: " + str(duplicate))
    result = [dict(r) for r in runners]
    for prefix, keys in GROUPS:
        fields = ",".join(keys)
        records = con.execute(f'''SELECT {fields},count(*),
            count(*) FILTER(WHERE target_win),count(*) FILTER(WHERE target_top3)
            FROM prior_eligible GROUP BY {fields}''').fetchall()
        counts = {tuple(r[:len(keys)]):r[len(keys):] for r in records}
        for runner in result:
            identity = tuple(runner[k] for k in keys)
            n,w,t = counts.get(identity,(0,0,0)) if all(v is not None for v in identity) else (0,0,0)
            for suffix,value in zip(["starts","wins","top3","win_rate","top3_rate"],
                                    [n,w,t,w/n if n else None,t/n if n else None]):
                runner[prefix + "_prior_" + suffix] = value
    return result
