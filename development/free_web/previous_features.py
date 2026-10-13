"""Previous-race features from labeled history and separately verified styles."""
import datetime as dt

def calculate(con,history_path,runners,race_date,styles):
    cutoff=dt.date.fromisoformat(race_date)
    con.execute('''CREATE OR REPLACE TEMP TABLE previous_history AS
      SELECT * FROM read_parquet(?) WHERE race_date<?''',[str(history_path),cutoff])
    q=con.execute('''SELECT ketto_toroku_bango,race_date,target_finish_position,
      distance_m,keibajo_code,track_code,body_weight_kg,body_weight_change_kg
      FROM previous_history WHERE NOT is_cancelled_or_excluded
      AND race_code IN (SELECT race_code FROM previous_history GROUP BY race_code
                       HAVING count(target_finish_position)>0)
      QUALIFY row_number() OVER(PARTITION BY ketto_toroku_bango
                                ORDER BY race_date DESC,race_code DESC)=1''')
    latest={r[0]:r[1:] for r in q.fetchall()}
    output=[]
    for runner in runners:
        row=dict(runner);previous=latest.get(row['ketto_toroku_bango'])
        if previous:
            date,finish,distance,course,track,weight,change=previous
            elapsed=(cutoff-date).days
            values=[elapsed,finish,styles.get((row['ketto_toroku_bango'],date.isoformat())),
                    distance,course,track,weight,change,elapsed]
            row['previous_race_date']=date.isoformat()
        else:
            values=[None]*9;row['previous_race_date']=None
        fields=['days_since_last_race','previous_finish_position','previous_running_style_code',
                'previous_distance_m','previous_keibajo_code','previous_track_code',
                'previous_body_weight_kg','previous_body_weight_change_kg','days_since_previous_race']
        row.update(zip(fields,values));output.append(row)
    return output
