# The `matchups` layer

This is page three of the `fantasy_analyzer` reference (see
[`docs/league.md`](league.md) for page one, the `league/` layer, and
[`docs/analytics.md`](analytics.md) for page two, the `analytics/` layer
that consumes this page's main output). It covers
[`src/fantasy_analyzer/matchups/`](../src/fantasy_analyzer/matchups/) only.

Conventions on this page (matching `docs/league.md` and `docs/analytics.md`):

- Source links point at a specific line in the current `main` (commit
  `b3115d6` at time of writing). **Line numbers drift as the code
  changes** -- if a link looks wrong, search the module for the symbol name
  rather than trusting the anchor.
- Sleeper IDs (`roster_id`, `matchup_id`, etc.) are always the join key;
  owner/team display names are labels only, resolved for convenience and
  never guaranteed unique.
- "Verified" below means run against real data with `.venv/bin/python`.
  Everything on this page was run **offline**: a small, hand-built raw
  weekly-matchup payload in the exact shape Sleeper's matchup endpoint
  returns (for the pipeline steps), and this repository's own
  `tests/fixtures/sleeper/winners_bracket.json` /
  `losers_bracket.json` fixtures (for the playoff-bracket section). No
  live-Sleeper run was done for this page.

## What this layer is for

`matchups/` turns Sleeper's raw, per-week, per-roster matchup entries into
the canonical, analysis-ready tables AGENTS.md's "Canonical Matchup
Dataset" describes: one row per matchup with both rosters, their points,
and a derived winner/loser/tie/margin -- plus a reconciliation check against
Sleeper's own cumulative standings, and separately, a normalized view of the
postseason bracket and final placements. Every function here performs
**no network I/O** except the two explicit fetching wrappers
(`load_season_matchups`, `load_playoff_brackets`); everything else takes
already-fetched data and returns a normalized result deterministically, so
it is unit-testable offline and safe to call repeatedly.

The pipeline has four stages, run in this order, each stage's output the
next stage's input:

```text
load_season_matchups   (fetch, per week)
        |
        v
pair_season_matchups   (group each week's flat roster entries into
        |               head-to-head pairs by matchup_id)
        v
derive_season_outcomes (compute winner/loser/tie/margin per pair)
        |
        v
build_season_matchup_df (resolve owner labels, assemble the one
                          canonical season_matchup_df DataFrame)
```

`season_matchup_df` is the frame `fantasy_analyzer.analytics` (see
[`docs/analytics.md`](analytics.md)) is built on. Two further, independent
consumers of this pipeline's outputs are documented at the end of this page:
`reconciliation.py` (a trust check between the matchup-derived record and
Sleeper's own cumulative standings) and `playoffs.py` (a separate raw-input
normalization for the postseason bracket, not part of the four-stage
pipeline above).

## Quick start: raw Sleeper matchups to a season matchup frame

This example is fully offline: it hand-builds three weeks of raw
per-roster matchup entries in the exact shape
`SleeperClient.get_matchups(league_id, week)` returns, for a 3-roster league
with one bye per week and a playoff bracket starting week 3, and runs them
through the whole pipeline.

```python
import pandas as pd

from fantasy_analyzer.league.season import SeasonBoundaries
from fantasy_analyzer.matchups.loader import collect_season_matchups
from fantasy_analyzer.matchups.pairing import pair_season_matchups
from fantasy_analyzer.matchups.outcomes import derive_season_outcomes
from fantasy_analyzer.matchups.season_matchups import build_season_matchup_df

# In practice, build this with derive_season_boundaries(snapshot.league,
# total_weeks) -- see docs/league.md. Here: 2 regular-season weeks, 1
# playoff week, so is_playoff is exercised without a long example.
boundaries = SeasonBoundaries(
    regular_season_weeks=[1, 2], playoff_weeks=[3], playoff_week_start=3, total_weeks=3
)

# One raw Sleeper matchups response per week -- exactly what
# client.get_matchups(league_id, week) returns: a flat list of one dict per
# roster, `matchup_id` shared by the two rosters that played each other
# (None for a bye).
raw_weekly_matchups = {
    1: [
        {"roster_id": 1, "matchup_id": 1, "points": 120.0},
        {"roster_id": 2, "matchup_id": 1, "points": 100.0},
        {"roster_id": 3, "matchup_id": None, "points": 90.0},   # bye
    ],
    2: [
        {"roster_id": 2, "matchup_id": 1, "points": 110.0},
        {"roster_id": 3, "matchup_id": 1, "points": 95.0},
        {"roster_id": 1, "matchup_id": None, "points": 85.0},   # bye
    ],
    3: [
        {"roster_id": 1, "matchup_id": 1, "points": 115.0},
        {"roster_id": 3, "matchup_id": 1, "points": 105.0},
        {"roster_id": 2, "matchup_id": None, "points": 80.0},   # bye
    ],
}

# Step 1: fetch/collect, tagged with season + is_playoff per week.
weeks = collect_season_matchups(raw_weekly_matchups, boundaries, season="2025")

# Step 2: group each week's flat entries into head-to-head pairs.
pairings = pair_season_matchups(weeks)

# Step 3: derive winner/loser/tie/margin for each pair.
outcomes = derive_season_outcomes(pairings)

# Step 4: resolve owner labels and assemble the canonical frame.
teams_df = pd.DataFrame([
    {"roster_id": 1, "owner_id": "u1", "display_name": "Alec", "team_name": "Alec"},
    {"roster_id": 2, "owner_id": "u2", "display_name": "Mike", "team_name": "Mike"},
    {"roster_id": 3, "owner_id": "u3", "display_name": "Joe",  "team_name": "Joe"},
])
season_matchup_df = build_season_matchup_df(outcomes, teams_df)
print(season_matchup_df)
```

**Verified offline** with `.venv/bin/python`. Real output:

```text
  season  week  is_playoff  matchup_id  roster_1_id  roster_2_id owner_1 owner_2  points_1  points_2  winner  loser  is_tie  margin  point_differential
0   2025     1       False         1.0            1          2.0    Alec    Mike     120.0     100.0     1.0    2.0   False    20.0                20.0
1   2025     1       False         NaN            3          NaN     Joe     NaN      90.0       NaN     NaN    NaN   False     NaN                 NaN
2   2025     2       False         NaN            1          NaN    Alec     NaN      85.0       NaN     NaN    NaN   False     NaN                 NaN
3   2025     2       False         1.0            2          3.0    Mike     Joe     110.0      95.0     2.0    3.0   False    15.0                15.0
4   2025     3        True         1.0            1          3.0    Alec     Joe     115.0     105.0     1.0    3.0   False    10.0                10.0
5   2025     3        True         NaN            2          NaN    Mike     NaN      80.0       NaN     NaN    NaN   False     NaN                 NaN
```

Note `matchup_id`/`roster_2_id`/`winner`/`loser` show as `NaN` rather than
`None` in this printed frame -- pandas upcasts an integer column to
`float64` as soon as any row in it is missing, which happens whenever a
single `season_matchup_df` mixes real matchups with bye rows. This is a
display/dtype detail, not a semantic difference: test for "missing" with
`pd.isna(...)`, not `... is None`, anywhere on this page (the same rule
`reconciliation.py`'s own implementation calls out explicitly -- see
below).

**Getting the raw weekly payloads for a real league** is what
`load_season_matchups` (below) does for you, in one call per week, via a
`SleeperClient`; this quick start uses `collect_season_matchups` directly
so it can run without network access. `notebooks/league_walkthrough.ipynb`
runs the live-`SleeperClient` equivalent of this whole pipeline against a
real league before handing the result to `fantasy_analyzer.analytics` (see
[`docs/analytics.md`](analytics.md)).

## Reference

### `fantasy_analyzer.matchups` (package exports)

[`__init__.py`](../src/fantasy_analyzer/matchups/__init__.py) re-exports the
public surface of every module on this page. Import from the package
directly (`from fantasy_analyzer.matchups import ...`) rather than reaching
into submodules -- the `__all__` list is the contract:

`WeekMatchups`, `collect_season_matchups`, `load_season_matchups`,
`MatchupPairing`, `pair_week_matchups`, `pair_season_matchups`,
`MatchupOutcome`, `derive_matchup_outcome`, `derive_season_outcomes`,
`SEASON_MATCHUP_COLUMNS`, `build_season_matchup_df`, `DERIVED_TOTALS_COLUMNS`,
`RECONCILIATION_COLUMNS`, `WIN_LOSS_TIE_TOLERANCE`, `POINTS_TOLERANCE`,
`derive_roster_totals`, `reconcile_matchups_to_standings`,
`FINAL_PLACEMENT_COLUMNS`, `LOSERS_BRACKET`, `PLAYOFF_BRACKET_COLUMNS`,
`WINNERS_BRACKET`, `build_bracket_df`, `build_final_placements`,
`build_playoff_brackets`, `load_playoff_brackets`.

---

### 1. Loading a season of raw matchups (FFA-030)

**Answers:** "get me every week's raw Sleeper matchup data for this league,
tagged with whether it's a playoff week" -- the pipeline's fetch step.

Module:
[`matchups/loader.py`](../src/fantasy_analyzer/matchups/loader.py) --
[module docstring](../src/fantasy_analyzer/matchups/loader.py#L1).

**[`WeekMatchups`](../src/fantasy_analyzer/matchups/loader.py#L23)** --
frozen dataclass, one week of raw matchups tagged with season-phase
metadata. Fields: `season` (`Optional[str]`), `week` (`int`), `is_playoff`
(`bool`, per the league's `SeasonBoundaries` -- see
[`docs/league.md`](league.md)), `matchups` (`list[dict]`, the raw Sleeper
matchup entries for the week, exactly as `SleeperClient.get_matchups`
returns them; empty if Sleeper returned no data for that week).

**[`collect_season_matchups(raw_weekly_matchups: Mapping[int, Optional[list[dict]]], boundaries: SeasonBoundaries, season: Optional[str] = None) -> list[WeekMatchups]`](../src/fantasy_analyzer/matchups/loader.py#L43)**

The pure composition core -- no network access. Takes matchup lists you've
already fetched, keyed by week number, plus a `SeasonBoundaries` (from
[`derive_season_boundaries`](../src/fantasy_analyzer/league/season.py#L46),
documented on page one). Returns one `WeekMatchups` per week in
`boundaries` (regular season weeks then playoff weeks, ascending), each
tagged `is_playoff` via
[`is_playoff_week`](../src/fantasy_analyzer/league/season.py#L99). A week
missing from `raw_weekly_matchups`, or whose value is `None` (Sleeper
returns `null` for some unplayed weeks), is retained with an **empty**
`matchups` list rather than dropped, so every relevant week is explicitly
visible downstream.

**[`load_season_matchups(client: SleeperClient, league_id: str, boundaries: SeasonBoundaries, season: Optional[str] = None) -> list[WeekMatchups]`](../src/fantasy_analyzer/matchups/loader.py#L84)**

Thin fetching wrapper around `collect_season_matchups`: calls
`client.get_matchups(league_id, week)` once per week in `boundaries` and
hands the result to `collect_season_matchups`. Prefer
`collect_season_matchups` directly for tests or when the raw data is
already in hand (as in the quick start above).

---

### 2. Pairing opponents by `matchup_id` (FFA-031)

**Answers:** "who played whom this week" -- turning Sleeper's flat,
one-row-per-roster weekly list into head-to-head pairs.

Module:
[`matchups/pairing.py`](../src/fantasy_analyzer/matchups/pairing.py) --
[module docstring](../src/fantasy_analyzer/matchups/pairing.py#L1). This
step is pairing only: it does **not** derive a winner/loser/margin (that's
`outcomes.py`, next) and does not resolve `roster_id` to an owner label
(that's `season_matchups.py`, at the end of the pipeline).

**[`MatchupPairing`](../src/fantasy_analyzer/matchups/pairing.py#L48)** --
frozen dataclass. Fields: `season`, `week`, `is_playoff` (carried through
from the source `WeekMatchups`); `matchup_id` (`Optional[int]`, `None` for
a bye); `roster_1_id` (the *lower* of the two paired roster ids, or the
sole roster id for a bye/incomplete case -- pairs are ordered by ascending
`roster_id`, not raw Sleeper entry order, so pairing output is
deterministic); `roster_2_id` (`Optional[int]`, `None` if there was no
second roster entry); `points_1`/`points_2` (raw reported points,
unvalidated; `points_2` is `None` when there's no `roster_2_id`).

**[`pair_week_matchups(week: WeekMatchups) -> list[MatchupPairing]`](../src/fantasy_analyzer/matchups/pairing.py#L100)**

Groups one week's flat `matchups` entries by shared `matchup_id`. Returns
one `MatchupPairing` per distinct `matchup_id` (two roster entries) plus
one per bye entry, sorted by ascending `roster_1_id`.

- **Bye**: Sleeper represents a roster with no opponent (`matchup_id:
  null`) with an unpaired `MatchupPairing` of its own. Multiple byes in the
  same week are never paired *with each other* -- a `None` `matchup_id`
  never means "these rosters share a matchup."
- **Incomplete data**: a non-`null` `matchup_id` shared by only *one*
  roster entry (a partially-loaded week) is likewise an unpaired
  `MatchupPairing`, preserving the real `matchup_id` rather than discarding
  it.
- **Data-integrity anomaly**: a non-`null` `matchup_id` shared by **more
  than two** roster entries has no correct interpretation -- raises
  `ValueError` rather than guessing a pairing that would silently corrupt
  every downstream metric.

**[`pair_season_matchups(weeks: list[WeekMatchups]) -> list[MatchupPairing]`](../src/fantasy_analyzer/matchups/pairing.py#L147)**

Thin wrapper applying `pair_week_matchups` to every week in turn, preserving
week order. This is the function used in the quick start above.

---

### 3. Deriving winner/loser/tie/margin (FFA-032)

**Answers:** "who won this matchup, and by how much" -- the first point in
the pipeline where a pair of scores becomes a result.

Module:
[`matchups/outcomes.py`](../src/fantasy_analyzer/matchups/outcomes.py) --
[module docstring](../src/fantasy_analyzer/matchups/outcomes.py#L1). Owner
resolution is still out of scope here; `winner_roster_id`/`loser_roster_id`
are raw Sleeper roster ids, per AGENTS.md's immutable-IDs-over-labels rule.

**[`MatchupOutcome`](../src/fantasy_analyzer/matchups/outcomes.py#L63)** --
frozen dataclass. Carries every `MatchupPairing` field unchanged, plus:
`winner_roster_id`/`loser_roster_id` (`Optional[int]`, both `None` if tied
or incomplete), `is_tie` (`bool`, `True` only when both scores are present
*and* equal -- `False`, not `True`, for an incomplete matchup: a missing
opponent is not a tie), `margin` (`abs(points_1 - points_2)`, non-negative,
`0.0` for a tie, `None` if incomplete), `point_differential`
(`points_1 - points_2`, signed from `roster_1_id`'s perspective, `None` if
incomplete).

**[`derive_matchup_outcome(pairing: MatchupPairing) -> MatchupOutcome`](../src/fantasy_analyzer/matchups/outcomes.py#L109)**

For a **complete** matchup (`roster_2_id` present, both `points` present):
computes `point_differential`, `margin = abs(point_differential)`, and
`is_tie`/`winner_roster_id`/`loser_roster_id` from the sign of the
differential. For an **incomplete** matchup (`roster_2_id` is `None`, i.e.
a bye/partial pairing, *or* either side's `points` is missing) this module
makes **no guess**: every outcome field is `None`/`False` rather than
treating a missing opponent or a missing score as a win, a loss, or a 0-0
tie.

**[`derive_season_outcomes(pairings: list[MatchupPairing]) -> list[MatchupOutcome]`](../src/fantasy_analyzer/matchups/outcomes.py#L175)**

Thin wrapper applying `derive_matchup_outcome` to every pairing, preserving
order. Used in the quick start above.

**Regular season vs. playoffs:** this module makes no distinction --
`is_playoff` is carried through unchanged and winner/loser/tie/margin are
derived identically regardless of season phase. Phase-specific analysis
(e.g. playoffs-only head-to-head) is entirely downstream, in
`fantasy_analyzer.analytics` (see [`docs/analytics.md`](analytics.md)).

---

### 4. Building the canonical season matchup frame (FFA-033)

**Answers:** "give me the one table every downstream analysis reads" -- the
pipeline's final assembly step, and the first point where `roster_id` is
resolved to a display label.

Module:
[`matchups/season_matchups.py`](../src/fantasy_analyzer/matchups/season_matchups.py)
-- [module docstring](../src/fantasy_analyzer/matchups/season_matchups.py#L1).

**[`build_season_matchup_df(outcomes: list[MatchupOutcome], teams_df: pd.DataFrame) -> pd.DataFrame`](../src/fantasy_analyzer/matchups/season_matchups.py#L73)**

- `outcomes`: per-matchup outcomes, as produced by `derive_season_outcomes`.
- `teams_df`: `LeagueSnapshot.teams_df`-shaped (see
  [`docs/league.md`](league.md)), needs at least `["roster_id",
  "display_name"]`, used only to resolve `owner_1`/`owner_2`.
- Returns `SEASON_MATCHUP_COLUMNS` (defined at
  [`season_matchups.py#L54`](../src/fantasy_analyzer/matchups/season_matchups.py#L54)),
  one row per input outcome, in the same order as `outcomes`. Empty
  `outcomes` returns an empty, correctly-columned frame. A `roster_id`
  absent from `teams_df` (or an empty `teams_df`) resolves to
  `owner_1`/`owner_2 = None` rather than raising.

#### The canonical `season_matchup_df` schema

This is the frame `fantasy_analyzer.analytics` (see
[`docs/analytics.md`](analytics.md)) takes as its main input everywhere.

| Column | Meaning |
|---|---|
| `season` | Season label (e.g. `"2025"`), or `None` if unset. |
| `week` | Week number (`int`). |
| `is_playoff` | Whether this week falls in the playoffs, per the league's `SeasonBoundaries`. |
| `matchup_id` | Raw Sleeper `matchup_id`, or `None` for a bye. |
| `roster_1_id` / `roster_2_id` | The two paired rosters. `roster_2_id` is `None` on a bye row (roster 1 played, but had no opponent that week). |
| `owner_1` / `owner_2` | Display-name labels resolved from `teams_df["display_name"]` by `roster_id`, or `None` if unmapped. Human-readable exception to the "IDs, not labels" rule -- `winner`/`loser` below stay roster ids. |
| `points_1` / `points_2` | Raw reported points, or `None`/`NaN` for an unloaded week. **A missing score is never treated as `0.0`** anywhere in this package. |
| `winner` / `loser` | The roster ids that won/lost (`MatchupOutcome.winner_roster_id`/`loser_roster_id`, carried through as-is -- not owner labels), or both `None` if tied or if either score is missing (an "incomplete" matchup is never guessed at). |
| `is_tie` | `True` only if both scores are present and equal; `False` for an incomplete matchup. |
| `margin` | `abs(points_1 - points_2)`, non-negative, `0.0` for a tie, `None` if incomplete. |
| `point_differential` | `points_1 - points_2`, signed from `roster_1_id`'s perspective, `None` if incomplete. |

`is_tie` and `point_differential` are retained even though AGENTS.md's
originally-sketched schema doesn't list them: dropping them would make a
tie (`winner`/`loser` both `None`, `points_1 == points_2`) indistinguishable
from an incomplete matchup (`winner`/`loser` both `None`, points missing) --
a distinction downstream metrics need (see `docs/analytics.md`'s tie-vs-
incomplete handling throughout). A bye row therefore has a real `points_1`
but `roster_2_id`/`winner`/`loser`/`margin`/`point_differential` all `None`.

**Regular season vs. playoffs:** `is_playoff` is carried through from
`MatchupOutcome` unchanged; this module makes no phase-specific distinction
of its own. Callers filter on `is_playoff` for phase-specific analysis.

---

### 5. Reconciling matchups to standings (FFA-034)

**Answers:** "do I trust this matchup-derived data" -- a check between two
independently-derived views of the same season: the matchup-level frame
built by steps 1-4 above, and Sleeper's own season-cumulative roster
counters (`LeagueSnapshot.rosters_df`, consumed via
`build_standings` -- see [`docs/analytics.md`](analytics.md)).

Module:
[`matchups/reconciliation.py`](../src/fantasy_analyzer/matchups/reconciliation.py)
-- [module docstring](../src/fantasy_analyzer/matchups/reconciliation.py#L1).

**[`derive_roster_totals(season_matchup_df: pd.DataFrame) -> pd.DataFrame`](../src/fantasy_analyzer/matchups/reconciliation.py#L198)**

Sums every row of `season_matchup_df` -- regular season and playoff alike,
**no** `is_playoff` filter is applied internally, because Sleeper's own
cumulative counters mix both phases too, so reconciling against them
requires summing every week -- attributing points and win/loss/tie credit
to both `roster_1_id` and `roster_2_id`. Returns `DERIVED_TOTALS_COLUMNS`
(defined at
[`reconciliation.py#L139`](../src/fantasy_analyzer/matchups/reconciliation.py#L139)):

| Column | Meaning |
|---|---|
| `roster_id` | Identity. Only rosters appearing in at least one `season_matchup_df` row get a row here. |
| `wins` / `losses` | Incremented for the `winner`/`loser` roster on each decided row. |
| `ties` | Incremented for both rosters on each `is_tie` row. |
| `points_for` | Sum of that roster's own points across every row it appears in (a missing points value contributes nothing, never `0`). |
| `points_against` | Sum of the *opponent's* points in the same rows -- **not credited on a bye row**, since there is no opponent to be scored against. |

A bye row contributes only to that roster's `points_for` -- an explicit,
documented assumption (not verified against a live bye week in this
codebase's fixtures) that Sleeper's own cumulative `fpts` counts a bye
week's score while `fpts_against` does not charge anything for it. A
roster with zero matchup rows is simply absent from the output.

**[`reconcile_matchups_to_standings(season_matchup_df: pd.DataFrame, standings_df: pd.DataFrame, *, win_loss_tie_tolerance: float = WIN_LOSS_TIE_TOLERANCE, points_tolerance: float = POINTS_TOLERANCE) -> pd.DataFrame`](../src/fantasy_analyzer/matchups/reconciliation.py#L288)**

Compares `derive_roster_totals`'s output against a `build_standings`-shaped
`standings_df` (not raw `rosters_df` -- the two already share column names,
so the comparison needs no field-renaming translation layer, and any bug
in `build_standings`'s pass-through surfaces here too, which is intended).
Tolerances (module constants, also overridable per-call):
[`WIN_LOSS_TIE_TOLERANCE = 0`](../src/fantasy_analyzer/matchups/reconciliation.py#L177)
(wins/losses/ties are exact integer counts -- any difference is real), and
[`POINTS_TOLERANCE = 1e-6`](../src/fantasy_analyzer/matchups/reconciliation.py#L182)
(absorbs floating-point summation-order noise between this module's
row-by-row accumulation and Sleeper's own cumulative total, without masking
a genuine discrepancy, which would be orders of magnitude larger).

Returns `RECONCILIATION_COLUMNS` (defined at
[`reconciliation.py#L150`](../src/fantasy_analyzer/matchups/reconciliation.py#L150)):
for each of `wins`, `losses`, `ties`, `points_for`, `points_against`, a
`derived_<x>` / `sleeper_<x>` / `<x>_diff` (`derived - sleeper`, `None` if
either side is unknown) / `<x>_match` (boolean) column set, plus an overall
`reconciled` boolean (`True` only if every metric matches). One row per
roster appearing in **either** input, sorted by ascending `roster_id`.

- A roster with **no matchup rows** (absent from `derive_roster_totals`)
  gets its derived side defaulted to `0`/`0.0` -- a roster in zero matchups
  has, by definition, zero recorded games and points, not an *unknown*
  value, so a non-zero Sleeper record for it correctly reports a mismatch.
- A roster **missing from `standings_df`** (or vice versa) keeps that
  side's values as `NaN` (a genuinely unknown comparison value), and every
  `*_match` flag for it is `False` -- an unknown comparison can never be
  "within tolerance".
- Both inputs empty: returns an empty, correctly-columned frame.

```python
import pandas as pd
from fantasy_analyzer.analytics import build_standings
from fantasy_analyzer.matchups.reconciliation import (
    derive_roster_totals, reconcile_matchups_to_standings,
)

# season_matchup_df, teams_df from the quick-start pipeline above
derived = derive_roster_totals(season_matchup_df)
print(derived)

# Sleeper's own cumulative rosters_df -- matches the derived totals for
# rosters 1 and 2, but roster 3's Sleeper fpts is off by 5.0 (simulating a
# real discrepancy, e.g. a scoring correction applied after this pipeline's
# matchup data was fetched).
rosters_df = pd.DataFrame([
    {"roster_id": 1, "owner_id": "u1", "wins": 2, "losses": 0, "ties": 0, "fpts": 320.0, "fpts_against": 205.0},
    {"roster_id": 2, "owner_id": "u2", "wins": 1, "losses": 1, "ties": 0, "fpts": 290.0, "fpts_against": 215.0},
    {"roster_id": 3, "owner_id": "u3", "wins": 0, "losses": 2, "ties": 0, "fpts": 295.0, "fpts_against": 225.0},
])
standings_df = build_standings(rosters_df, teams_df)

recon = reconcile_matchups_to_standings(season_matchup_df, standings_df)
print(recon[["roster_id", "derived_wins", "sleeper_wins", "wins_match",
             "derived_points_for", "sleeper_points_for", "points_for_diff",
             "points_for_match", "reconciled"]])
```

**Verified offline** -- real output for `derive_roster_totals`:

```text
   roster_id  wins  losses  ties  points_for  points_against
0          1     2       0     0       320.0           205.0
1          2     1       1     0       290.0           215.0
2          3     0       2     0       290.0           225.0
```

and for the reconciliation:

```text
   roster_id  derived_wins  sleeper_wins  wins_match  derived_points_for  sleeper_points_for  points_for_diff  points_for_match  reconciled
0          1             2             2        True               320.0               320.0              0.0              True        True
1          2             1             1        True               290.0               290.0              0.0              True        True
2          3             0             0        True               290.0               295.0             -5.0             False       False
```

Roster 3's manufactured 5-point Sleeper/derived mismatch is caught exactly
as intended: `points_for_match = False` and `reconciled = False` only for
that roster, while rosters 1 and 2 -- whose fabricated `rosters_df` values
were built to agree with the pipeline's own derived totals -- fully
reconcile.

---

### Playoff brackets and final placements (FFA-055)

**Answers:** "what does the postseason bracket look like, and who finished
where" -- a separate normalization, not part of the four-stage regular
pipeline above (it consumes raw bracket payloads, not `season_matchup_df`).
Referenced by `LeagueAnalytics.playoff_brackets()`/`.final_placements()` in
[`docs/analytics.md`](analytics.md).

Module:
[`matchups/playoffs.py`](../src/fantasy_analyzer/matchups/playoffs.py) --
[module docstring](../src/fantasy_analyzer/matchups/playoffs.py#L1). Sleeper
exposes the postseason as two independent flat lists of bracket matches --
the winners (championship) bracket and the losers (consolation) bracket,
via `SleeperClient.get_winners_bracket`/`get_losers_bracket` -- each entry
shaped like `{"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4}`, optionally
with `"t1_from"`/`"t2_from"` (how an unfilled slot will be populated) and
`"p"` (a placement award).

**[`build_bracket_df(raw_bracket: Optional[list[dict]], bracket: str) -> pd.DataFrame`](../src/fantasy_analyzer/matchups/playoffs.py#L207)**

Normalizes **one** raw bracket payload. `bracket` is an opaque label --
[`WINNERS_BRACKET = "winners"`](../src/fantasy_analyzer/matchups/playoffs.py#L138)
or
[`LOSERS_BRACKET = "losers"`](../src/fantasy_analyzer/matchups/playoffs.py#L141)
-- retained verbatim in the output's `bracket` column. Raw-field mapping:
`r`->`round`, `m`->`match_id` (unique **only within one bracket** -- a
combined frame must key on `(bracket, match_id)`), `t1`/`t2`->
`roster_1_id`/`roster_2_id` (`None` for an unfilled slot), `t1_from`/
`t2_from`->`roster_1_from`/`roster_2_from` (rendered as a readable string,
e.g. `{"w": 1}` -> `"winner_of_match_1"`; **not** resolved into concrete
roster ids by walking earlier rounds -- once an earlier match is played,
Sleeper itself backfills `t1`/`t2`, so re-deriving it here would add
nothing), `w`/`l`->`winner_roster_id`/`loser_roster_id` (`None` for an
unplayed match), and `p`->**both** `winner_placement` (`p`) and
`loser_placement` (`p + 1`) -- Sleeper's convention is that a
placement-awarding match's winner takes place `p` and its loser takes place
`p + 1`; this module surfaces both explicitly rather than making every
reader know that convention. **Most matches award no placement at all**
(`p` absent, both fields `None`) -- only certain matches (typically
semifinals/finals and their consolation counterparts) do.

**[`build_playoff_brackets(winners_raw: Optional[list[dict]], losers_raw: Optional[list[dict]] = None) -> pd.DataFrame`](../src/fantasy_analyzer/matchups/playoffs.py#L270)**

Normalizes **both** brackets into one combined frame: winners bracket rows
first, then losers bracket rows, each block sorted by ascending `round`
then `match_id`. Returns `PLAYOFF_BRACKET_COLUMNS` (defined at
[`playoffs.py#L145`](../src/fantasy_analyzer/matchups/playoffs.py#L145)):
`bracket`, `round`, `match_id`, `roster_1_id`, `roster_2_id`,
`roster_1_from`, `roster_2_from`, `winner_roster_id`, `loser_roster_id`,
`winner_placement`, `loser_placement` (nullable columns held as
`dtype=object` so a missing value is a real `None`, not `NaN`). Either or
both of `winners_raw`/`losers_raw` may be `None`/empty (no consolation
bracket, or playoffs not yet started); returns an empty, correctly-columned
frame if both are.

**[`build_final_placements(bracket_df: pd.DataFrame, teams_df: pd.DataFrame) -> pd.DataFrame`](../src/fantasy_analyzer/matchups/playoffs.py#L306)**

Every match with a `winner_placement` **and** a decided
`winner_roster_id`/`loser_roster_id` awards two places (winner ->
`winner_placement`, loser -> `loser_placement`). Returns
`FINAL_PLACEMENT_COLUMNS` (defined at
[`playoffs.py#L174`](../src/fantasy_analyzer/matchups/playoffs.py#L174)):
`roster_id`, `owner` (resolved from `teams_df["display_name"]`, `None` if
unmapped), `placement`, `bracket`, `match_id` (the last two tracing the
placement back to the match that awarded it). One row per roster with a
**determined** placement, sorted by ascending `placement` then
`roster_id`.

**A roster whose place is never explicitly awarded by a `p`-bearing match
is simply absent -- no placement is ever inferred**, from seed, standings,
or anything else. This is normal, not a data error: many real leagues
bracket out only the games their format cares about, leaving some
placements (e.g. 7th vs. 8th, if no such game exists) undetermined. Raises
`ValueError` only if the bracket is **self-contradictory** -- two different
placement-awarding matches crediting the *same* roster with two *different*
placements; the *same* placement value awarded to two *different* rosters
is deliberately **not** rejected (Sleeper's consolation-bracket `p`
numbering is only observed to be league-absolute in this codebase's own
fixtures, not proven universal, so rejecting it could raise on perfectly
ordinary data from a league that numbers it differently).

**[`load_playoff_brackets(client: SleeperClient, league_id: str) -> pd.DataFrame`](../src/fantasy_analyzer/matchups/playoffs.py#L406)**

Thin fetching wrapper: calls `client.get_winners_bracket`/
`get_losers_bracket` once each and passes the results to
`build_playoff_brackets`. Prefer `build_playoff_brackets` directly for
tests or already-fetched data.

**Rounds are not mapped to weeks.** A bracket match's raw payload carries
no week number, only a round (`r`); this module does not attempt to derive
one (it depends on the league's playoff format, byes, and multi-week
finals), and deliberately does not touch `SeasonBoundaries`. Every row here
is postseason by construction, so there is no regular-season/playoff
filtering decision for this module to make.

```python
import json
import pandas as pd
from fantasy_analyzer.matchups.playoffs import build_playoff_brackets, build_final_placements

# This repository's own fixtures: an 8-team league, winners bracket fully
# played (rounds 1-2), losers bracket only partially awarding placements --
# see the printed output below for what that means for rosters 6 and 8.
winners_raw = json.load(open("tests/fixtures/sleeper/winners_bracket.json"))
losers_raw = json.load(open("tests/fixtures/sleeper/losers_bracket.json"))

bracket_df = build_playoff_brackets(winners_raw, losers_raw)
print(bracket_df)

teams_df = pd.DataFrame(
    [{"roster_id": r, "owner_id": f"u{r}", "display_name": f"Team{r}", "team_name": f"Team{r}"}
     for r in range(1, 9)]
)
print(build_final_placements(bracket_df, teams_df))
```

**Verified offline** (against this repository's real fixture files) --
real output for `build_playoff_brackets`:

```text
   bracket  round  match_id roster_1_id roster_2_id      roster_1_from      roster_2_from winner_roster_id loser_roster_id winner_placement loser_placement
0  winners      1         1           1           4               None               None                1               4             None            None
1  winners      1         2           2           3               None               None                2               3             None            None
2  winners      2         3           1           2  winner_of_match_1  winner_of_match_2                1               2                1               2
3  winners      2         4           4           3   loser_of_match_1   loser_of_match_2                3               4                3               4
4   losers      1         1           5           8               None               None                5               8             None            None
5   losers      1         2           6           7               None               None                7               6             None            None
6   losers      2         3           5           7  winner_of_match_1  winner_of_match_2                7               5                5               6
```

and for `build_final_placements`:

```text
   roster_id  owner  placement  bracket  match_id
0          1  Team1          1  winners         3
1          2  Team2          2  winners         3
2          3  Team3          3  winners         4
3          4  Team4          4  winners         4
4          7  Team7          5   losers         3
5          5  Team5          6   losers         3
```

Rosters **6 and 8** -- the two round-1 losers in the losers bracket -- get
**no row**: the fixture's losers bracket only has one placement-awarding
match (`p: 5`, awarding 5th/6th to rosters 7 and 5), so nothing in the
bracket data determines who finished 7th vs. 8th between 6 and 8. This is
the exact "undetermined placement" case the module docstring describes, not
a bug in this example.
