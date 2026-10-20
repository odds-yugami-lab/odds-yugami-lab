"""Check intervening JRA race days; never assume Monday-Friday are non-race days."""
import datetime as dt
import json
from source_bundle import download


def check(complete_through, required_through, month_pages):
    covered = dt.date.fromisoformat(complete_through)
    needed = dt.date.fromisoformat(required_through)
    if covered >= needed:
        return complete_through
    dates = set()
    cursor = covered + dt.timedelta(days=1)
    while cursor <= needed:
        key = cursor.strftime('%Y%m')
        if key not in month_pages:
            raise ValueError('Official calendar coverage missing: ' + key)
        page = month_pages[key]
        if not isinstance(page, list) or len(page) != 1 or int(page[0]['month']) != cursor.month:
            raise ValueError('Unsupported official calendar month')
        data = page[0]['data']
        if not isinstance(data, list) or not data:
            raise ValueError('Empty official calendar is not proof of no racing')
        days = set()
        for row in data:
            day = dt.date(cursor.year, cursor.month, int(row['date']))
            if day in days: raise ValueError('Ambiguous calendar date')
            days.add(day)
            for info in row['info']:
                if not isinstance(info['race'], list): raise ValueError('Unsupported calendar races')
                if info['race']: dates.add(day)
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    missing = sorted(d.isoformat() for d in dates if covered < d <= needed)
    if missing:
        raise ValueError('History missing completed JRA race days: ' + ','.join(missing))
    return required_through


def effective_coverage(complete_through, required_through):
    covered = dt.date.fromisoformat(complete_through)
    needed = dt.date.fromisoformat(required_through)
    pages, evidence = {}, []
    cursor = covered + dt.timedelta(days=1)
    while cursor <= needed:
        key = cursor.strftime('%Y%m')
        url = 'https://www.jra.go.jp/keiba/common/calendar/json/' + key + '.json'
        page, stamp, sha = download(url)
        pages[key] = json.loads(page)
        evidence.append({'source_url':url,'retrieved_at':stamp,'page_sha256':sha})
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return check(complete_through, required_through, pages), evidence
