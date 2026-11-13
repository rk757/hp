"""Tests for age-group enrichment. Run: python -m pytest scraper/"""
import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from age_groups import (AG, AG_ORIG, GP, GP_ORIG, _recompute_group_pos, _restore,
                        enrich_age_groups, normalize_name, render_report_markdown)

RAW = Path(__file__).resolve().parent.parent / "data" / "all_results_raw.json"

META = {
    1: {"name": "A TRIATLONAS - LTT 1", "date": "2026-05-31"},
    2: {"name": "B TRIATLONAS - LTT 2", "date": "2026-06-28"},
    3: {"name": "C TRIATLONAS - LTT 3", "date": "2026-07-19"},
    9: {"name": "D TRIATLONAS - LTT 1", "date": "2025-06-01"},
    5: {"name": "VILNIAUS TRIATLONAS TRI - FUN", "date": "2026-07-16"},
}


def row(stage, first, last, ag="__absent__", gender="V", dist="od", pos="1", gpos="9", club="-", **kw):
    r = {"FIRST NAME": first, "LAST NAME": last, "GENDER": gender, "POS": pos,
         "GENDER POS": gpos, "CLUB": club, "_stage_id": stage, "_distance": dist, **kw}
    if ag != "__absent__":
        r[AG] = ag
    return r


def test_normalize_name_strips_diacritics_and_space():
    assert normalize_name("  Januškevičius ") == normalize_name("JANUSKEVICIUS")
    assert normalize_name("Ona  Marija") == "ona marija"


def test_generic_group_filled_from_same_year_and_original_kept():
    recs = [row(1, "Jonas", "Jonaitis", "V30"), row(2, "Jonas", "JONAITIS", "EM")]
    enrich_age_groups(recs, META)
    assert recs[1][AG] == "V30"
    assert recs[1][AG_ORIG] == "EM"
    assert recs[1]["_age_group_confidence"] == "high"
    assert recs[1]["_age_group_sources"] == [1]
    assert AG_ORIG not in recs[0]  # source rows untouched


def test_missing_column_filled_and_restored_as_absent():
    recs = [row(1, "Jonas", "Jonaitis", "V30"), row(2, "Jonas", "Jonaitis")]
    pristine = copy.deepcopy(recs)
    enrich_age_groups(recs, META)
    assert recs[1][AG] == "V30" and recs[1][AG_ORIG] is None
    for r in recs:
        _restore(r)
    assert recs == pristine


def test_other_year_is_never_used():
    recs = [row(9, "Jonas", "Jonaitis", "V30"), row(2, "Jonas", "Jonaitis", "EM"),
            row(1, "Kitas", "Dalyvis", "V40")]  # makes "od" eligible in 2026
    enrich_age_groups(recs, META)
    assert recs[1][AG] is None
    assert recs[1]["_age_group_confidence"] == "unmatched"


def test_non_ltt_stage_neither_source_nor_target():
    recs = [row(5, "Jonas", "Jonaitis", "V30"), row(2, "Jonas", "Jonaitis", "EM"),
            row(1, "Ona", "Onaite", "V40"), row(5, "Ona", "Onaite", "EM")]
    enrich_age_groups(recs, META)
    assert recs[1]["_age_group_confidence"] == "unmatched"
    assert recs[3][AG] == "EM" and AG_ORIG not in recs[3]


def test_gender_guard_rejects_other_gender_namesake():
    recs = [row(1, "Vilija", "Petraitė", "M30", gender="M"), row(2, "Vilija", "Petraitė", "EM", gender="V")]
    enrich_age_groups(recs, META)
    assert recs[1][AG] is None


def test_gender_letter_scheme_learned_per_year():
    # 2022-style: men are "M", women "W", while GENDER stays V/M
    meta = {1: {"name": "X - LTT 1", "date": "2022-05-01"}, 2: {"name": "Y - LTT 2", "date": "2022-06-11"}}
    recs = [row(1, "Petras", "P", "M30", gender="V"), row(1, "Ona", "O", "W25", gender="M"),
            row(2, "Petras", "P", "-", gender="V"), row(2, "Ona", "O", None, gender="M")]
    enrich_age_groups(recs, meta)
    assert recs[2][AG] == "M30" and recs[3][AG] == "W25"


def test_majority_wins_with_medium_confidence():
    recs = [row(1, "A", "B", "V40"), row(3, "A", "B", "V40", dist="sd"), row(3, "A", "B", "V30"),
            row(2, "A", "B", "EM")]
    enrich_age_groups(recs, META)
    assert (recs[3][AG], recs[3]["_age_group_confidence"]) == ("V40", "medium")


def test_tie_broken_by_club_else_conflict():
    recs = [row(1, "A", "B", "V30", club="Klubas"), row(3, "A", "B", "V35", club="Kitas"),
            row(2, "A", "B", "EM", club="KLUBAS")]
    enrich_age_groups(recs, META)
    assert (recs[2][AG], recs[2]["_age_group_confidence"]) == ("V30", "medium")

    recs = [row(1, "A", "B", "V30"), row(3, "A", "B", "V35"), row(2, "A", "B", "EM")]
    enrich_age_groups(recs, META)
    assert (recs[2][AG], recs[2]["_age_group_confidence"]) == (None, "conflict")


def test_ineligible_distances_untouched():
    recs = [row(1, "A", "B", "V30"), row(2, "A", "B", "TRI-FUN-40V", dist="trifun"),
            row(2, "A", "B", "IM", dist="ssd")]
    enrich_age_groups(recs, META)
    assert AG_ORIG not in recs[1] and AG_ORIG not in recs[2]


def test_group_pos_recomputed_only_when_whole_distance_generic():
    src = [row(1, n, "X", "V30") for n in "abcde"]
    stage2 = [row(2, n, "X", "EM", pos=str(i + 1), gpos=str(i + 1), **{GP: str(i + 1)})
              for i, n in enumerate("abcde")]
    stage2.append(row(2, "zz", "X", "EM", pos="DNF", gpos="DNF", **{GP: "DNF"}))
    enrich_age_groups(src + stage2, META)
    assert [r[GP] for r in stage2] == ["*", "*", "*", "1", "2", None]
    assert [r[GP_ORIG] for r in stage2] == ["1", "2", "3", "4", "5", "DNF"]
    assert all(r["_group_pos_estimated"] for r in stage2)

    # Partially generic distance: official GROUP POS of other rows is kept
    src = [row(1, "a", "X", "V30")]
    stage3 = [row(3, "a", "X", "-", pos="5", **{GP: "-"}), row(3, "b", "X", "V30", pos="6", **{GP: "2"})]
    enrich_age_groups(src + stage3, META)
    assert stage3[0][AG] == "V30" and stage3[0][GP] == "-"
    assert stage3[1][GP] == "2" and GP_ORIG not in stage3[1]


def test_idempotent_and_report_renders():
    recs = [row(1, "Jonas", "Jonaitis", "V30"), row(2, "Jonas", "Jonaitis", "EM", **{GP: "1"})]
    rep1 = enrich_age_groups(recs, META)
    snap = copy.deepcopy(recs)
    rep2 = enrich_age_groups(recs, META)
    assert recs == snap and rep1 == rep2
    md = render_report_markdown(rep1, club_name="-")
    assert "Jonas Jonaitis" in md and "V30" in md


# --- Regression checks against the real archive (skipped if it is not present) ---

def _raw():
    if not RAW.exists():
        pytest.skip("raw archive not present")
    recs = json.loads(RAW.read_text(encoding="utf-8"))
    for r in recs:
        _restore(r)
    return recs


def test_group_pos_rule_matches_organiser_on_2026_stages():
    recs = _raw()
    mismatches = total = 0
    for sid in (134, 135, 138, 139, 140, 141):
        for d in ("od", "sd"):
            rows = [copy.deepcopy(r) for r in recs if r["_stage_id"] == sid and r["_distance"] == d]
            official = [r.get(GP) for r in rows]
            _recompute_group_pos(rows)
            for o, r in zip(official, rows):
                if not str(r.get("POS", "")).isdigit():
                    continue
                total += 1
                same = (o in ("*", "-") and r[GP] == "*") or str(o) == str(r[GP])
                mismatches += not same
    assert total > 1000 and mismatches <= 5


def test_backtest_hidden_stage_accuracy():
    """Hide the age groups of LTT 4 (stage 138, 2026), infer them, compare to the truth."""
    recs = _raw()
    meta = {134: {"name": "LTT 1", "date": "2026-05-31"}, 135: {"name": "LTT 2", "date": "2026-06-14"},
            138: {"name": "LTT 4", "date": "2026-07-19"}, 139: {"name": "LTT 5", "date": "2026-08-16"},
            140: {"name": "LTT 6", "date": "2026-08-23"}, 141: {"name": "LTT 7", "date": "2026-09-05"}}
    recs = [r for r in recs if r["_stage_id"] in meta]
    truth = {}
    for i, r in enumerate(recs):
        if r["_stage_id"] == 138 and r["_distance"] in ("od", "sd"):
            truth[i] = r.get(AG)
            r[AG] = "EM"
    enrich_age_groups(recs, meta)
    outcome = Counter()
    for i, true_ag in truth.items():
        got = recs[i][AG]
        outcome["none" if got is None else ("ok" if got == true_ag else "wrong")] += 1
    inferred = outcome["ok"] + outcome["wrong"]
    print("backtest stage 138:", dict(outcome))
    assert inferred / len(truth) > 0.5
    assert outcome["ok"] / inferred > 0.97


# --- field_stats ---

def test_field_stats_medians_per_stage_distance_gender():
    from field_stats import attach_field_stats, time_to_seconds
    assert time_to_seconds("02:14:00.7") == pytest.approx(8040.7)
    assert time_to_seconds("0:43:04") == 2584 and time_to_seconds("DNF") is None
    field = [{"FIRST NAME": f"a{i}", "GENDER": "V", "POS": str(i + 1), "_stage_id": 1, "_distance": "od",
              "TOTAL": f"02:0{i}:00", "SWIM": "00:30:00", "BIKE": "01:00:00", "RUN": "00:40:00",
              "T1": "00:01:00", "T2": "00:01:00", "CLUB": "X"} for i in range(5)]
    dnf = dict(field[0], POS="DNF", TOTAL="00:01:00", **{"FIRST NAME": "dnf"})
    women = dict(field[0], GENDER="M", **{"FIRST NAME": "w"})
    club = dict(field[2], CLUB="HighPeaks Lietuva")
    out = attach_field_stats([club, women], field + [dnf, women])
    assert out[0]["_field"] == {"n": 5, "total": 7320.0, "swim": 1800.0, "bike": 3600.0,
                                "run": 2400.0, "trans": 120.0}
    assert "_field" not in out[1]  # only 1 woman finisher < MIN_FIELD
    assert "_field" not in club  # input rows not mutated
