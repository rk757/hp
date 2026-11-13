"""
Age-group enrichment for LTT (Lietuvos triatlono taurė) stages.

Some LTT stages publish no usable age groups. Trakai, for example, uses only
"EM"/"EF" (open men/women) on the Olympic distance and has no AGE GROUP
column at all on the sprint. Birth dates can't be used to compute a group,
because every row carries the placeholder "2000-12-12". So for each row whose
AGE GROUP is missing or too generic, we look the athlete up by name in the
*other LTT stages of the same year* and copy their group from there.

Rules
-----
* A "specific" age group matches ^[VMW]\\d{2}$ (letter = gender, digits = age
  band). Anything else (None, "", "-", "EM", "EF", missing column) is
  "generic". The letter scheme differs by year: most seasons use V/M (vyrai =
  men, moterys = women), but 2022 used M/W. So "M" means women in one year and
  men in another. The GENDER column is always V/M, so the mapping from GENDER
  to group letter is learned per year from rows that have both.
* Only distances where at least one LTT stage that year has specific groups are
  eligible. This keeps out trifun (TRI-FUN-13M...), kids (AM/BV...), splash,
  relays and youth super sprint.
* Matching key: first + last name, lowercased, diacritics stripped, whitespace
  collapsed. Gender guard: the candidate group's letter must be the letter
  that year's scheme uses for the row's GENDER.
* Resolution:
    - one distinct candidate group                 -> confidence "high"
    - several, one has a strict majority of votes  -> "medium"
    - tie, but exactly one tied group was seen with
      the same club as this row                    -> "medium"
    - otherwise                                    -> "conflict" (left empty)
    - no candidates                                -> "unmatched" (left empty)
* Original values are kept in "AGE GROUP ORIGINAL" / "GROUP POS ORIGINAL".
* GROUP POS is recomputed only for stage+distance pairs that had *no* specific
  groups at all (i.e. the organiser did not rank by age group). Partially-filled
  distances keep the official GROUP POS. The recompute uses the organiser's own
  rule, verified on the 2026 stages: gender top 3 get "*" (no AG place), and
  everyone else is ranked by POS within their age group. Those places are
  estimates, because unmatched athletes are missing from the ranking.

enrich_age_groups() is idempotent: rows already enriched by a previous run are
restored to their originals first. That makes it safe to run on an
already-enriched raw archive.
"""

import re
import unicodedata
from collections import Counter, defaultdict

SPECIFIC_AG = re.compile(r"^[VMW]\d{2}$")
LTT_STAGE = re.compile(r"\bLTT\s*\d", re.IGNORECASE)
GENDER_PODIUM = {"1", "2", "3"}

AG = "AGE GROUP"
AG_ORIG = "AGE GROUP ORIGINAL"
GP = "GROUP POS"
GP_ORIG = "GROUP POS ORIGINAL"
MARK = "_age_group_inferred"  # True on every row this module touched
ABSENT = "_age_group_absent_columns"  # columns that did not exist before enrichment


def normalize_name(s):
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def norm_club(s):
    s = normalize_name(s)
    return "" if s in ("", "-") else s


def person_key(row):
    first, last = normalize_name(row.get("FIRST NAME")), normalize_name(row.get("LAST NAME"))
    return (first, last) if first and last else None


def is_specific(ag):
    return isinstance(ag, str) and bool(SPECIFIC_AG.match(ag.strip()))


def _restore(row):
    """Undo a previous enrichment so the function is idempotent."""
    if not row.pop(MARK, False):
        return
    absent = set(row.get(ABSENT) or [])
    for cur, orig in ((AG, AG_ORIG), (GP, GP_ORIG)):
        if orig in row:
            val = row.pop(orig)
            if cur in absent:
                row.pop(cur, None)
            else:
                row[cur] = val
    for k in [k for k in row if k.startswith("_age_group_") or k == "_group_pos_estimated"]:
        row.pop(k)


def _stash(row, cur, orig):
    """Remember the organiser's value (and whether the column existed) before overwriting."""
    if orig in row:
        return
    row[orig] = row.get(cur)
    if cur not in row:
        row.setdefault(ABSENT, []).append(cur)


def _resolve(candidates, row_club):
    """candidates: list of (age_group, club_norm, stage_id). Returns (group|None, confidence)."""
    if not candidates:
        return None, "unmatched"
    votes = Counter(ag for ag, _, _ in candidates)
    if len(votes) == 1:
        return next(iter(votes)), "high"
    (top, n1), (_, n2) = votes.most_common(2)
    if n1 > n2:
        return top, "medium"
    tied = [ag for ag, n in votes.items() if n == n1]
    if row_club:
        same_club = {ag for ag, club, _ in candidates if ag in tied and club == row_club}
        if len(same_club) == 1:
            return same_club.pop(), "medium"
    return None, "conflict"


def _recompute_group_pos(rows):
    """Organiser's rule: gender top 3 -> '*', others ranked by POS within AGE GROUP."""
    finishers = sorted((r for r in rows if str(r.get("POS", "")).isdigit()), key=lambda r: int(r["POS"]))
    counters = Counter()
    for r in rows:
        _stash(r, GP, GP_ORIG)
        r[GP] = None
        r["_group_pos_estimated"] = True
        r[MARK] = True
    for r in finishers:
        if str(r.get("GENDER POS", "")) in GENDER_PODIUM:
            r[GP] = "*"
        elif is_specific(r.get(AG)):
            counters[r[AG]] += 1
            r[GP] = str(counters[r[AG]])


def enrich_age_groups(records, stage_meta):
    """
    records:    list of flat result dicts (record_to_dict output); modified in place.
    stage_meta: {stage_id: {"name": str, "date": "YYYY-MM-DD..."}}
    Returns a report dict describing every adjustment.
    """
    for r in records:
        _restore(r)

    ltt = {}  # stage_id -> year
    for sid, info in stage_meta.items():
        if LTT_STAGE.search(info.get("name") or "") and (info.get("date") or "")[:4].isdigit():
            ltt[int(sid)] = info["date"][:4]

    by_year = defaultdict(list)
    for r in records:
        sid = r.get("_stage_id")
        if sid in ltt and person_key(r):
            by_year[ltt[sid]].append(r)

    def label(sid):
        info = stage_meta.get(sid) or stage_meta.get(str(sid)) or {}
        return f"{info.get('name')} ({(info.get('date') or '')[:10]})"

    report = {"ltt_stages": {str(s): label(s) for s in sorted(ltt)}, "years": {}}

    for year, rows in sorted(by_year.items()):
        dist = lambda r: (r.get("_distance") or "").lower()
        eligible = {dist(r) for r in rows if is_specific(r.get(AG))}

        # person -> [(age_group, club, stage_id)]: one vote per stage+distance appearance
        index = defaultdict(list)
        for r in rows:
            if dist(r) in eligible and is_specific(r.get(AG)):
                index[person_key(r)].append((r[AG].strip(), norm_club(r.get("CLUB")), r["_stage_id"]))

        # GENDER (V/M) -> age-group letter used this year (V/M, or M/W in 2022)
        pairs = defaultdict(Counter)
        for r in rows:
            if is_specific(r.get(AG)) and r.get("GENDER"):
                pairs[r["GENDER"].strip().upper()][r[AG].strip()[0]] += 1
        letter_for = {g: c.most_common(1)[0][0] for g, c in pairs.items()}

        targets = [r for r in rows if dist(r) in eligible and not is_specific(r.get(AG))]
        groups = defaultdict(list)
        for r in targets:
            groups[(r["_stage_id"], dist(r))].append(r)

        year_report = []
        for (sid, d), trows in sorted(groups.items()):
            all_rows = [r for r in rows if r["_stage_id"] == sid and dist(r) == d]
            fully_generic = not any(is_specific(r.get(AG)) for r in all_rows)
            outcome = Counter()
            changes = []
            for r in trows:
                gender = (r.get("GENDER") or "").strip().upper()
                letter = letter_for.get(gender)
                # Unknown mapping for this gender: at least reject letters owned by another gender
                foreign = {l for g, l in letter_for.items() if g != gender} if gender else set()
                cands = [c for c in index.get(person_key(r), [])
                         if c[2] != sid and (c[0][0] == letter if letter else c[0][0] not in foreign)]
                new, conf = _resolve(cands, norm_club(r.get("CLUB")))
                outcome[conf] += 1
                orig = r.get(AG)
                _stash(r, AG, AG_ORIG)
                r[AG] = new
                r[MARK] = True
                r["_age_group_confidence"] = conf
                r["_age_group_sources"] = sorted({c[2] for c in cands})
                changes.append({
                    "name": f"{r.get('FIRST NAME', '')} {r.get('LAST NAME', '')}".strip(),
                    "club": r.get("CLUB"),
                    "gender": r.get("GENDER"),
                    "pos": r.get("POS"),
                    "original": orig,
                    "inferred": new,
                    "confidence": conf,
                    "candidates": dict(Counter(c[0] for c in cands)),
                    "sources": r["_age_group_sources"],
                })
            if fully_generic:
                for r in all_rows:
                    _stash(r, AG, AG_ORIG)
                _recompute_group_pos(all_rows)
                for c, r in zip(changes, trows):
                    c["group_pos_original"] = r.get(GP_ORIG)
                    c["group_pos"] = r.get(GP)
            year_report.append({
                "stage_id": sid,
                "stage": label(sid),
                "distance": d,
                "rows_total": len(all_rows),
                "rows_targeted": len(trows),
                "group_pos_recomputed": fully_generic,
                "outcome": dict(outcome),
                "changes": changes,
            })
        report["years"][year] = {"eligible_distances": sorted(eligible), "stages": year_report}
    return report


def report_totals(report):
    t = Counter()
    for y in report["years"].values():
        for s in y["stages"]:
            t["targeted"] += s["rows_targeted"]
            t.update(s["outcome"])
    return dict(t)


def render_report_markdown(report, club_name=None, scrape_summary=None):
    club_n = normalize_name(club_name) if club_name else None
    out = ["# Scrape report", ""]
    if scrape_summary:
        for k, v in scrape_summary.items():
            out.append(f"- **{k}**: {v}")
        out.append("")
    t = report_totals(report)
    out += ["## Age-group enrichment (LTT stages, same-year lookup)", "",
            f"Rows with missing/generic age group: **{t.get('targeted', 0)}** — "
            f"high: {t.get('high', 0)}, medium: {t.get('medium', 0)}, "
            f"conflict: {t.get('conflict', 0)}, unmatched: {t.get('unmatched', 0)}", "",
            "Original values are kept in `AGE GROUP ORIGINAL` / `GROUP POS ORIGINAL`. "
            "`GROUP POS` is recomputed (estimate) only where the organiser published no age groups "
            "for the whole distance.", ""]
    for year, y in sorted(report["years"].items(), reverse=True):
        if not y["stages"]:
            continue
        out += [f"### {year}", "",
                "| Stage | Distance | Targeted / total | high | medium | conflict | unmatched | GROUP POS recomputed |",
                "|---|---|---|---|---|---|---|---|"]
        for s in y["stages"]:
            o = s["outcome"]
            out.append(f"| {s['stage']} | {s['distance']} | {s['rows_targeted']} / {s['rows_total']} | "
                       f"{o.get('high', 0)} | {o.get('medium', 0)} | {o.get('conflict', 0)} | "
                       f"{o.get('unmatched', 0)} | {'yes' if s['group_pos_recomputed'] else 'no'} |")
        out.append("")
        for s in y["stages"]:
            out += [f"#### {s['stage']} — {s['distance']}", "",
                    "| Pos | Name | Club | Original | Inferred | Confidence | Candidates | GROUP POS (orig → new) |",
                    "|---|---|---|---|---|---|---|---|"]
            for c in sorted(s["changes"], key=lambda c: (c["inferred"] is None, int(c["pos"]) if str(c["pos"]).isdigit() else 10**6)):
                club = c["club"] or ""
                if club_n and normalize_name(club) == club_n:
                    club = f"**{club}**"
                cands = ", ".join(f"{k}×{v}" for k, v in sorted(c["candidates"].items())) or "—"
                gp = f"{c.get('group_pos_original')} → {c.get('group_pos')}" if "group_pos" in c else "unchanged"
                out.append(f"| {c['pos']} | {c['name']} | {club} | {c['original'] if c['original'] is not None else '∅'} | "
                           f"{c['inferred'] or '—'} | {c['confidence']} | {cands} | {gp} |")
            out.append("")
    return "\n".join(out)
