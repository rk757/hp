"""
Per-race field statistics for the athlete profile page.

Courses differ between venues: Trakai's OD is not Veisiejai's OD. So raw times
from different races of the "same" distance aren't directly comparable. To
show whether an athlete is really improving, the dashboard can compare each
split to the median of that race's field: same stage, same distance, same
gender, finishers only. That median is computed here from the full archive,
because docs/data.json only carries the club's own rows.

attach_field_stats() returns *copies* of the club rows with a "_field" dict
added, so the big raw archive stays unchanged:

    "_field": {"n": 87, "total": 8123.4, "swim": 1702.0, "bike": 3650.0,
               "run": 2501.0, "trans": 160.0}

The values are median seconds. A discipline is left out when fewer than
MIN_FIELD finishers have it.
"""

import re
from collections import defaultdict
from statistics import median

MIN_FIELD = 5
SPLITS = {"total": ("TOTAL",), "swim": ("SWIM",), "bike": ("BIKE",), "run": ("RUN",), "trans": ("T1", "T2")}


def time_to_seconds(t):
    """'02:14:00.7' / '0:43:04' / '27:01' -> seconds (float), else None."""
    if not isinstance(t, str) or not re.match(r"^\s*\d+(:\d+(\.\d+)?){1,2}\s*$", t):
        return None
    parts = [float(p) for p in t.strip().split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs if secs > 0 else None


def split_seconds(row, disc):
    vals = [time_to_seconds(row.get(col)) for col in SPLITS[disc]]
    return None if any(v is None for v in vals) else sum(vals)


def _group_key(r):
    return (r.get("_stage_id"), (r.get("_distance") or "").lower(), (r.get("GENDER") or "").strip().upper())


def attach_field_stats(club_rows, all_records):
    finishers = defaultdict(list)
    for r in all_records:
        if str(r.get("POS", "")).strip().isdigit() and r.get("FIRST NAME"):
            finishers[_group_key(r)].append(r)

    cache = {}

    def stats_for(key):
        if key not in cache:
            rows = finishers.get(key, [])
            out = {"n": len(rows)}
            for disc in SPLITS:
                vals = [v for v in (split_seconds(r, disc) for r in rows) if v]
                if len(vals) >= MIN_FIELD:
                    out[disc] = round(median(vals), 1)
            cache[key] = out if len(out) > 1 else None
        return cache[key]

    result = []
    for r in club_rows:
        r = dict(r)
        stats = stats_for(_group_key(r)) if r.get("FIRST NAME") else None
        if stats:
            r["_field"] = stats
        else:
            r.pop("_field", None)
        result.append(r)
    return result
