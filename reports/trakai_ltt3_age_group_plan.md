# Trakų triatlonas LTT 3 (2026): age-group gap analysis and plan to infer the missing groups

_Analysis date: 2026-11-13. Data source: `data/all_results_raw.json` (31,844 rows) at commit `9c48feb`._

## 1. Project context (what the code does)

- `scraper/scrape.py` runs nightly through GitHub Actions (`.github/workflows/scrape.yml`). It walks every season, pulls every distance for every completed stage, and flattens each API row into a dict using that stage's own column titles (`record_to_dict`). It writes:
  - `data/all_results_raw.json`: every athlete, every club.
  - `docs/data.json`: HighPeaks Lietuva rows only. The dashboard reads this file.
- `docs/index.html` uses `AGE GROUP` in two places: the age-group filter dropdowns (`populateAgeGroupFilter`, lines 652–662) and age-group podiums (`isAgPodiumRow` → `GROUP POS` top 3, line 443). Age-group podiums also count toward the "Podiums" leaderboard (lines 1056–1057).
- The scraper does not normalise anything. Each stage's columns and values are stored exactly as the organiser published them. Every nightly run overwrites both JSON files, so **a hand edit to the data would be lost the next night**. Any fix has to run as a step inside the pipeline.

## 2. The problem: stage 136, "TRAKŲ TRIATLONAS - LTT 3 (2026-06-28)"

### 2.1 Age-group values per distance, Trakai compared with the other 2026 LTT stages

| Distance | Other 2026 LTT stages (134, 135, 138–141) | Trakai LTT 3 (136) |
|---|---|---|
| `od` (300 rows) | 5-year bands: `V20 V25 … V60`, `M20 M25 … M55` | Only `EM` (266), `EF` (32) and `-` (2). These are Elite/Open men and women, so there is **no age information**. |
| `sd` (148 rows) | 5-year bands as for `od` | **No `AGE GROUP` or `GROUP POS` columns at all**. The organiser published a different table layout. |
| `ssd` (74 rows, super sprint) | not held at other stages | Youth/junior categories `IM IW JM JW DM DW` plus `-` (47). Out of scope: these are kids, and no other stage has a comparable adult group. |
| `od-est` / `sd-est` / `ssd-est` | relay, no age groups | relay, no age groups |

The same layout appears at Trakai in earlier years: stages 106 (2023), 112 (2024) and 124 (2025) have **no `AGE GROUP` at all**. The Trakai event is apparently run as an open or championship format every year, so this gap will come back each season.

### 2.2 Other findings

- **`BIRTH DATE` cannot be used.** Every 2026 row holds the placeholder `2000-12-12`; across all seasons there are 15,199 placeholder rows and 16,645 nulls. We cannot compute an age group from birth year, so the only way to infer one is to **match the person** to another stage.
- **`GROUP POS` at Trakai `od` currently equals `GENDER POS`**, because everyone is ranked inside `EM`/`EF`. On the dashboard this means:
  - Trakai age-group podiums are wrong: only the overall gender top 3 show as AG podiums.
  - The age-group filter shows `EM`/`EF` as if they were age groups.
  - Trakai `sd` rows have no age group, so they never pass an age-group filter.
- **The organiser's `GROUP POS` rule.** I reverse-engineered it from the 2026 stages and it reproduces 1,245 of 1,247 `od`/`sd` finishers. The two misses are rows that are themselves missing an age group. The rule:
  - The gender top 3 (`GENDER POS` 1–3) get **no** age-group place. They are marked `*` or `-`.
  - Every other finisher is ranked by `POS` within (distance, `AGE GROUP`).
  - `DNF` and `DSQ` rows have no place.
- **Age-group schemes changed between seasons.**
  - 2025 used `V20`, then **`V25` as a wide 25–39 band** (431 rows), then 5-year bands from `V40`/`M40` upward.
  - 2026 uses 5-year bands throughout: `V20 V25 V30 V35 V40 …`.
  - An athlete's 2026 group is therefore either their 2025 group or the next band up. For 2025 groups of V40 and above, the observed shift was 0 in about 85% of cases and +5 in about 15%. A 2025 `V25`/`M25` can become any of 25/30/35/40.
- **The gender letter is consistent.** The `V` (vyrai, men) or `M` (moterys, women) prefix of the age group always matched the `GENDER` column, with 0 mismatches. This is a useful consistency check.
- **Within 2026 the same name almost always carries the same group.** Only 3 of 593 matched people are inconsistent:
  - Mantas Kukėnys: V40 at three stages and V30 at stage 141. Most likely a data-entry error; a majority vote picks V40.
  - Elvis Januškevičius: V30 (stage 138, `sd`) and V35 (stage 140). Spelled with and without diacritics. The true group is ambiguous.
  - Antanas Norkevičius: V55 and V45, both at stage 134, under different clubs. These are **probably two different people** with the same name.
- **Names vary in spelling.** The same person sometimes appears with and without Lithuanian diacritics (e.g. `JANUŠKEVIČIUS` / `JANUSKEVICIUS`), so names must be matched after normalisation. The dashboard already does this in `normalizeNameKey`. 61 names appear under more than one club in 2026, so the club is a poor matching key: people leave it blank (`-`) or change clubs.

### 2.3 How much can be inferred

These figures cover Trakai `od` + `sd` finishers with a name: 448 rows.

| Match source | od | sd | Total | Confidence |
|---|---|---|---|---|
| Same name in another 2026 LTT stage, consistent group | 147 | 80 | **227 (50.7%)** | High |
| Same name in 2026, conflicting groups | 3 | 1 | 4 | Medium (majority vote) or flag for review |
| Only in 2025 stages | 15 | 6 | 21 (4.7%) | Low to medium (band changed, see 2.2) |
| No match anywhere | 135 | 61 | 196 (43.8%) | Cannot infer |

Almost all of the unmatched athletes are one-off participants (foreign athletes, Trakai-only locals).

**HighPeaks Lietuva at Trakai (23 adult `od`/`sd` rows):** 22 match a 2026 stage with a single consistent group, for example Ramūnas Keliuotis V50, Gabija Juknytė M25 and Darius Puknys V50. Only **Ignas Zarevičius** has no match. Timas Jablonskis (`ssd`, youth) is out of scope. For the club's own dashboard, coverage is therefore about 96%.

## 3. Plan

### Step 1: Add a post-processing module, `scraper/age_groups.py`

The scraper calls this module after it collects `all_records` and **before** it writes the raw and filtered files, so that both outputs contain the enriched rows. It must be a pure function, `enrich_age_groups(records) -> records`, so it can be unit-tested on fixture data without network access.

### Step 2: Detect which stage/distance pairs need inference

Do this from the data, not from a hard-coded stage ID, because Trakai does the same thing every year.

- A (stage, distance) pair is a **target** when it is an individual adult distance (`od`, `sd`) and either:
  - none of its rows has an `AGE GROUP` column, or
  - none of its rows has an age group matching `^[VM]\d{2}$` (e.g. only `EM`/`EF`).
- Keep a small override list, e.g. `{136: ["od", "sd"]}`, so the target set is explicit and can be reviewed. Log every target the scraper detects.
- Never touch relay distances (`*-est`, `*est`), kids' distances (`vaikai*`, `splash`), `trifun` (it has its own `TRI-FUN-13M…` scheme) or `ssd` (youth groups).

### Step 3: Build the person → age-group index

- **Key:** `(normalise(FIRST NAME), normalise(LAST NAME))`. To normalise: apply NFKD, strip combining marks, lowercase, collapse whitespace. This is the same logic as `normalizeNameKey` in `index.html`.
- **Source rows:** rows from other stages **in the same season**, any of the `od`/`sd` distances, whose `AGE GROUP` matches `^[VM]\d{2}$`. Determine the season from the stage date year.
- **Gender guard:** the first letter of the candidate group must equal the target row's `GENDER` (`V`/`M`). This rules out some same-name collisions.

### Step 4: Resolve the group, in priority order

1. **Same season, exactly one distinct group.** Use it. `confidence = "high"`.
2. **Same season, several groups.** If one group holds a strict majority of the person's stage appearances, use it with `confidence = "medium"`. Otherwise leave the group empty and set `confidence = "conflict"`.
   - Optional tie-breaker: prefer the candidate from a row whose club matches the target row's club. Example: Norkevičius at Trakai races for a club that matches one of his two namesakes.
3. **Previous season only.** Apply it only when the 2025 group is unambiguous under the 2026 scheme.
   - If the previous group is V40/M40 or above, or V20/M20, carry it forward with `confidence = "low"`. The group is correct in about 85% of cases; otherwise the true group is one band up.
   - If the previous group was the 2025 wide band `V25`/`M25`, **do not guess**. Leave it empty.
4. **No match.** Leave `AGE GROUP` empty. Do not invent anything.

### Step 5: Write the result without destroying the source data

For each target row:

- `AGE GROUP_ORIGINAL`: what the organiser published (`EM`, `EF`, `-`, or missing). Keep it for auditing.
- `AGE GROUP`: the inferred group, or `null`. The dashboard keeps working without any change, and `EM`/`EF` no longer show up in the age-group filter.
- `_age_group_inferred: true`, `_age_group_confidence: high|medium|low|conflict|none` and `_age_group_source: [stage_ids]`.

### Step 6: Recompute `GROUP POS` for the target stage and distance

Apply the organiser's rule, which reproduces 1,245 of 1,247 rows on the 2026 data:

```
finishers = rows with numeric POS, sorted by int(POS)
for r in finishers:
    if GENDER POS in {1,2,3}:   GROUP POS = "*"        # gender podium, no AG place
    elif AGE GROUP is empty:    GROUP POS = None
    else:                       GROUP POS = running count within AGE GROUP
DNF / DSQ rows:                 GROUP POS = None
```

- Keep the original value as `GROUP POS_ORIGINAL`.
- **Caveat:** these places are relative to the *inferred* field. About 44% of athletes stay unassigned, so a computed place of 3 might really have been 4 or 5 if every athlete's group were known. Two options:
  - (a) Mark the place as estimated (`_group_pos_estimated: true`) and show it with a "~" or an asterisk in the UI. **Recommended.**
  - (b) Only compute places for age groups in which every finisher could be classified.

### Step 7: Dashboard changes (`docs/index.html`, small)

- In the results table, show inferred age groups and places with a marker and a tooltip, e.g. "inferred from LTT 1/2/4", based on `_age_group_inferred` and `_group_pos_estimated`.
- Decide whether estimated AG podiums count toward the "Podiums" leaderboard and the "Age group podium finishes" stat (`isAgPodiumRow`). Suggestion: count them, but give the stat tile a footnote, or put a toggle on it.
- `populateAgeGroupFilter` needs no change once `EM`/`EF` have moved to `AGE GROUP_ORIGINAL`.

### Step 8: Tests and verification

- **Unit tests** (pytest, fixture rows):
  - name normalisation, including diacritics and extra whitespace
  - each rule in Step 4, including the conflict case, the gender guard and refusing to map from the 2025 `V25` band
  - Step 6 reproduces the original `GROUP POS` on stages 134, 135 and 138–141, as a regression test of the rule
- **Back-test the inference.** Pick a stage that does have groups, e.g. 138. Hide its groups, run the inference from the other 2026 stages, and measure accuracy and coverage. Expected: very high accuracy given only 3/593 inconsistencies, with about 50–60% coverage.
- **Report on each run.** The scraper should print the coverage per target: high / medium / low / conflict / none counts, plus HighPeaks rows that stayed unmatched. Today that would be Ignas Zarevičius.

### Step 9 (optional): Manual overrides for the gaps that remain

Add `data/age_group_overrides.json` with entries like `{"<stage_id>": {"<first|last>": "V30"}}`. These win over inference. Club members can fill in the few HighPeaks athletes who never raced another LTT stage, such as Ignas Zarevičius. Use `confidence = "manual"`.

## 4. Risks and open questions

- **Same-name collisions.** Example: Antanas Norkevičius, who looks like two people. The gender guard and the club tie-breaker reduce the risk but cannot remove it. A low rate is acceptable at about 1 in 600.
- **Age-group definition.** Groups appear to be assigned by birth year, i.e. by age on 31 December of the season. A person's group is therefore constant within a season, which is the assumption the whole plan rests on. The 2026 data supports it: 590 of 593 people had consistent groups.
- **Official status.** The inferred placings are unofficial. The organiser chose not to rank Trakai by age group. Label them as estimates in the UI.
- **Ordering inside the season.** Trakai matches can come from stages held *after* it (LTT 4–7). That is fine for a finished season. If the inference runs mid-season, coverage improves as later stages publish, and the nightly re-scrape picks this up automatically because enrichment runs on every scrape.
- **Earlier Trakai editions** (2023–2025; stages 106, 112, 124) have no `AGE GROUP` either. The same mechanism applies to them, but those seasons used different schemes, such as the 2025 wide V25 band. It works if the index is built per season. Enable it per season once the 2026 back-test looks good.

## 5. Effort estimate

| Item | Effort |
|---|---|
| `age_groups.py` (detect, index, resolve, recompute `GROUP POS`) + hook in `scrape.py` | ~0.5 day |
| Unit tests + back-test script | ~0.5 day |
| Dashboard markers/tooltips + podium counting decision | ~2–3 h |
| Overrides file (optional) | ~1 h |
