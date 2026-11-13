# Plan: Add TSK Darna Race Scraping

## Context

tskdarna.lt (Triatlono ir sveikatingumo klubas Darna, Panevezys) runs on the **exact same CARE platform** as triatlonotaure.lt and irontrakai.lt — identical JSON API endpoints, identical response format (`{result: [{id, row, titles, stageId, distance}], page, total, total_pages}`). The existing `record_to_dict()` logic works unchanged.

HighPeaks Lietuva members already participate in TSK Darna events — confirmed in scrape data (e.g. Paulius Andriekus, Arvydas Daunys, Egle Ragaisyte, Martynas Mickus in duathlons; Kristijonas Vysniauskas in 2025 duathlon).

## Site inventory

TSK Darna has 3 seasons (2024, 2025, 2026) with stage IDs 1-12. These **collide** with both triatlonotaure.lt and irontrakai.lt stage IDs. The system already offsets Iron Trakai by +10000.

### All stages

| Stage ID | Name | Date | Type | Has Results |
|----------|------|------|------|-------------|
| 1 | Panevezio Maratonas 2024 | 2024-11-09 | Running | No |
| 4 | Senvage 2025 | 2025-04-05 | Running (external reg) | No |
| 2 | B. Abramaicio triatlono taure 2025 | 2025-04-13 | Pool triathlon | **Yes** |
| 5 | Duatlonas 2025 | 2025-04-13 | Duathlon | **Yes** |
| 6 | Vidutinio nuotolio cempionatas 2025 | 2025-08-02 | 70.3 triathlon | **Yes** |
| 7 | Panevezio Maratonas 2025 | 2025-11-08 | Running | No |
| 10 | B. Abramaicio triatlono taure 2026 | 2026-05-17 | Pool triathlon | **Yes** |
| 12 | Duatlonas 2026 | 2026-05-17 | Duathlon | **Yes** |
| 9 | Vidutinio nuotolio cempionatas 2026 | 2026-08-01 | 70.3 triathlon | **Yes** |
| 8 | Panevezio Maratonas 2026 | 2026-11-07 | Running | No (upcoming) |

### Stages with results (6 total, ~250 result rows)

**Pool triathlon** (B. Abramaicio triatlono taure) — indoor short-course triathlon:
- Stage 2 (2025): distances `I dist`, `II dist`, `III dist`, `IV dist` (100m+3km+0.5km up to 750m+20km+5km)
- Stage 10 (2026): distances `1`, `2`, `3`, `4` (same events, different codes)
- Titles: FIRST NAME, LAST NAME, BIRTH DATE, POS, GENDER POS, GROUP POS, BIB, AGE GROUP, GENDER, CITY, CLUB, MORE, **SWIM, T1, BIKE, T2, RUN, TOTAL**

**70.3 triathlon** (Vidutinio nuotolio cempionatas) — half-Ironman distance:
- Stage 6 (2025): distances `vid` (individual, 100 results), `est` (relay)
- Stage 9 (2026): distances `vid` (individual, 122 results), `est` (relay)
- Titles: ...SWIM POS, **SWIM**, T1, BIKE POS, **BIKE**, T2, RUN POS, **RUN**, TOTAL
- Note: extra `SWIM POS`, `BIKE POS`, `RUN POS` columns vs pool triathlon

**Duathlon** (run-bike-run, NOT swim-bike-run):
- Stage 5 (2025): distances `D1` (individual, 6 results), `Esta` (relay)
- Stage 12 (2026): distances `duatlonas` (individual, 8 results), `est` (relay)
- Titles: same as pool triathlon (SWIM, T1, BIKE, T2, RUN, TOTAL)
- **Quirk**: the CARE platform labels the first run segment as "SWIM" even for duathlons. Column names match triathlon structure despite being a different sport. The existing `_is_triathlon_result` filter (checks for "SWIM" in titles) will include duathlons, which is desirable since HighPeaks members participate.

**Running events** (marathons) — `has_results: false`, nothing to fetch.

## Approach: Add to existing SITES[] config

Since the multi-site loop with stage ID offsetting is already implemented, this is a minimal change — just add a third entry to `SITES[]`.

### Stage ID offset: +20000

Iron Trakai uses +10000, TSK Darna uses +20000. Stage 2 becomes 20002, stage 9 becomes 20009, etc. No collisions possible.

### Distance normalization

TSK Darna used different distance codes for the same event across years:

```python
DARNA_DISTANCE_CANONICAL = {
    "I dist": "1",       # 2025 pool triathlon I -> 2026 canonical
    "II dist": "2",      # 2025 pool triathlon II -> 2026 canonical
    "III dist": "3",     # 2025 pool triathlon III -> 2026 canonical
    "IV dist": "4",      # 2025 pool triathlon IV -> 2026 canonical
    "D1": "duatlonas",   # 2025 duathlon individual -> 2026 canonical
    "Esta": "est",       # 2025 duathlon relay -> 2026 canonical
}
```

The 70.3 codes (`vid`, `est`) are already consistent across years.

### Distance code collision note

TSK Darna uses `est` for both 70.3 relay and duathlon relay. Since these are on different stages, `_group_key = (_stage_id, _distance, gender)` doesn't collide. In `distance_names.json`, the last-written display label for `est` will win — acceptable since context comes from the stage name.

### No cross-site distance normalization

TSK Darna distances are distinct physical events — no mapping to LTT or Iron Trakai distances:
- Pool triathlon: 100m-750m swim + 3-20km bike + 0.5-5km run (tiny vs LTT sprint/olympic)
- 70.3: same physical distance as Iron Trakai 70-3, but different organizer/venue. Could theoretically map `vid` -> `70-3` and `est` -> `70-3est` to merge with Iron Trakai for athlete tracking. **Decision needed: keep separate or merge?** Keeping separate is safer — the events are at different venues (Panevezys Senvage vs Trakai) with different courses.

### Triathlon filter behavior

The existing `_is_triathlon_result` (checks for "SWIM" + "RUN" in titles) will:
- **Include**: pool triathlon, 70.3 triathlon, duathlon (all have SWIM+RUN in titles)
- **Exclude**: running events (only TOTAL, but these have `has_results: false` anyway)

No filter changes needed.

### No club standings

TSK Darna has no `global_results_stage: true` entries — no club standings aggregate. Set `has_club_standings: False`.

## Changes: `scraper/scrape.py` only

### 1. Add distance map and SITES entry (~3 lines config)

```python
DARNA_DISTANCE_CANONICAL = {
    "I dist": "1",
    "II dist": "2",
    "III dist": "3",
    "IV dist": "4",
    "D1": "duatlonas",
    "Esta": "est",
}
```

Add to `SITES[]`:

```python
{
    "key": "darna",
    "label": "tskdarna.lt",
    "base_url": "https://www.tskdarna.lt",
    "stage_id_offset": 20_000,
    "has_club_standings": False,
    "distance_map": DARNA_DISTANCE_CANONICAL,
},
```

### 2. No other changes needed

The multi-site loop, triathlon filter, distance normalization, and offset logic are already in place from the Iron Trakai implementation.

## Files touched

| File | Change |
|------|--------|
| `scraper/scrape.py` | Add `DARNA_DISTANCE_CANONICAL` dict and one SITES entry |
| All other files | None |

## Expected scrape output

- ~6 completed stages, 1-2 upcoming stages (Panevezio Maratonas 2026, possibly 2025 if still listed)
- ~250 new result rows across pool triathlon, 70.3, and duathlon
- Stage names like `"20002": "B. ABRAMAIČIO TRIATLONO TAURĖ 2025 (2025-04-13)"`
- Distance names for codes: `1`, `2`, `3`, `4`, `vid`, `est`, `duatlonas`
- HighPeaks Lietuva members visible in duathlon results

## Verification

1. Run existing tests: `python -m pytest scraper/` — must pass unchanged
2. Run scraper: `python scraper/scrape.py --club "HighPeaks Lietuva"`
3. Check `data/all_results_raw.json` contains records with `_source: "darna"` and `_stage_id` >= 20000
4. Check `docs/stage_names.json` has entries like `"20002": "B. ABRAMAIČIO TRIATLONO TAURĖ 2025 ..."`
5. Check `docs/distance_names.json` includes TSK Darna distance codes
6. Verify pool triathlon (stages 20002, 20010), 70.3 (20006, 20009), and duathlon (20005, 20012) all appear
7. Verify HighPeaks members in duathlon results appear in filtered `docs/data.json`
8. Running events (Panevezio Maratonas) do NOT appear in results (no `has_results`)

## Open questions

1. **Merge 70.3 distances with Iron Trakai?** TSK Darna `vid`/`est` are the same physical distance as Iron Trakai `70-3`/`70-3est`. Merging would enable athlete progress tracking across venues. Keeping separate is safer but fragments the data. Recommendation: keep separate for now, revisit if athlete tracking across venues is requested.

2. **Duathlon labeling**: The CARE platform labels duathlon first-run as "SWIM". This is misleading but harmless for data processing. If a frontend display ever shows split names, it would show "SWIM: 23:19" for what's actually a 6km run. No action needed unless the frontend gets discipline-aware labels.
