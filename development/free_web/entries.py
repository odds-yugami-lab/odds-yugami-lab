"""Parse public registration/entry pages, preserving unpublished fields.

Partial registration rows are NOT prediction-ready. This parser covers the
listed flat-course labels only; unsupported course labels stay unresolved.
"""
import datetime as dt
import re
from result_store import text

TRACKS = {"芝・直線":"10", "芝・左":"11", "芝・左・外":"12",
          "芝・右":"17", "芝・右・外":"18", "ダート・左":"23", "ダート・右":"24"}
SEX = {"牡":"1", "牝":"2", "せん":"3"}

def attach_known_sires(con, rows, history_paths, known_through):
    """Use stable pedigree IDs already observed; never guess or use future rows."""
    date = dt.date.fromisoformat(known_through)
    known = {}
    for path in history_paths:
        pairs = con.execute('''SELECT DISTINCT ketto_toroku_bango,sire_code
            FROM read_parquet(?) WHERE race_date<=? AND sire_code IS NOT NULL''', [str(path),date]).fetchall()
        for horse,sire in pairs:
            known.setdefault(horse,set()).add(sire)
    output=[]
    for row in rows:
        row=dict(row)
        ids=known.get(row['ketto_toroku_bango'],set())
        if len(ids)>1:
            raise ValueError("Conflicting existing pedigree IDs")
        row['sire_code']=next(iter(ids)) if ids else None
        if row['sire_code'] is not None:
            row['unpublished_or_unresolved']=[k for k in row['unpublished_or_unresolved'] if k!='sire_code']
        output.append(row)
    return output

def identity(cell, kind):
    matches = re.findall(r'/keiba/directory/' + kind + r'/(\d+)/', cell)
    if len(set(matches)) != 1:
        raise ValueError("Missing or ambiguous " + kind + " identity")
    return matches[0]

def parse(page, race_id, stage):
    if stage not in {"registration", "entries"} or not re.fullmatch(r"\d{10}",race_id):
        raise ValueError("Invalid race ID or stage")
    plain = text(page)
    date = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', plain)
    if not date:
        raise ValueError("Race date missing")
    date = dt.date(*map(int,date.groups()))
    start = re.search(r'(\d{1,2}:\d{2}|-)\s*発走', plain)
    status = re.search(r'class="hr-predictRaceInfo__text"[^>]*>([^<]+?)(\d+)m</span>',page)
    if not status:
        raise ValueError("Course metadata missing")
    course = status.group(1).strip()
    grade = re.search(r'hr-label--g([123])',page)
    common = {"race_id":race_id,"race_code":date.strftime('%Y%m%d')+race_id[2:],
              "race_date":date.isoformat(),"start_time":start.group(1) if start and start.group(1)!='-' else None,
              "keibajo_code":race_id[2:4],"track_code":TRACKS.get(course),
              "course_label":course,"distance_m":int(status.group(2)),
              "grade_code":{"1":"A","2":"B","3":"C"}.get(grade.group(1)) if grade else None,
              "stage":stage}
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S)
            if ('父馬名' in t and '調教師' in t) or 'horsePedigree' in t]
    if len(tables)!=1:
        raise ValueError("Entry table missing or ambiguous")
    body=re.search(r'<tbody\b[^>]*>(.*?)</tbody>',tables[0],re.S)
    if not body:
        raise ValueError("Entry body missing")
    rows=[]
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body.group(1),re.S):
        cells=re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S)
        expected=5 if stage=='registration' else 8
        if len(cells)!=expected:
            raise ValueError("Unexpected entry column count")
        horse_cell=cells[0] if stage=='registration' else cells[2]
        trainer_cell=cells[2] if stage=='registration' else cells[4]
        sexage=re.search(r'(牡|牝|せん)(\d+)/',text(horse_cell))
        if not sexage:
            raise ValueError("Sex/age missing")
        if stage=='registration':
            weight=text(cells[1]);sire=text(cells[3]);jockey=None;frame=None;number=None;bw=None;change=None
        else:
            weights=re.findall(r'<p\b[^>]*>(.*?)</p>',cells[3],re.S)
            weight=text(weights[-1]) if weights else ''
            sire_match=re.search(r'父：(.*?)(?:</p>)',cells[5],re.S)
            sire=text(sire_match.group(1)) if sire_match else None
            jockey=identity(cells[3],'jockey')
            frame=text(cells[0]);number=text(cells[1])
            frame=frame if frame.isdigit() and 1<=int(frame)<=8 else None
            number=number.zfill(2) if number.isdigit() and 1<=int(number)<=18 else None
            body=re.fullmatch(r'(\d+)\(([+-]?\d+)\)',text(cells[6]))
            bw=int(body.group(1)) if body else None;change=int(body.group(2)) if body else None
        rows.append(dict(common,ketto_toroku_bango=identity(horse_cell,'horse'),
                         trainer_code=identity(trainer_cell,'trainer'),jockey_code=jockey,
                         sire_name=sire,sire_code=None,sex_code=SEX[sexage.group(1)],age=int(sexage.group(2)),
                         carried_weight_kg=float(weight) if re.fullmatch(r'\d+(?:\.\d+)?',weight) else None,
                         wakuban=frame,umaban=number,body_weight_kg=bw,body_weight_change_kg=change))
    if not rows or len({r['ketto_toroku_bango'] for r in rows})!=len(rows):
        raise ValueError("Empty or duplicate runners")
    for row in rows:
        row['field_size']=len(rows) if stage=='entries' else None
        required=['start_time','track_code','jockey_code','sire_code','carried_weight_kg','wakuban','umaban','body_weight_kg','body_weight_change_kg','field_size']
        row['unpublished_or_unresolved']=[k for k in required if row[k] is None]
        row['prediction_ready']=False  # Other features, odds and model still required.
    return rows
