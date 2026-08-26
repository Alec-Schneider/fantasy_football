# The `analytics` layer

This is page two of the `fantasy_analyzer` reference (see
[`docs/league.md`](league.md) for page one, the `league/` layer, and
[`docs/matchups.md`](matchups.md) for page three, the `matchups/` layer that
produces this layer's main input). It covers
[`src/fantasy_analyzer/analytics/`](../src/fantasy_analyzer/analytics/) only.

Conventions on this page (matching `docs/league.md`):

- Source links point at a specific line in the current `main` (commit
  `b3115d6` at time of writing). **Line numbers drift as the code
  changes** -- if a link looks wrong, search the module for the symbol name
  rather than trusting the anchor.
- Sleeper IDs (`roster_id`, etc.) are always the join key; owner/team display
  names are labels only, resolved for convenience and never guaranteed
  unique.
- "Verified" below means run against real data with `.venv/bin/python`.
  Everything in this page was run against a small, hand-built,
  offline `season_matchup_df`/`teams_df`/`rosters_df` -- the exact shapes
  `tests/analytics/` builds by hand, not live Sleeper data -- so nothing
  here depends on network access. No live-Sleeper run was done for this
  page; see "Gaps" in the report for what that means for you.

## What this layer is for

`analytics/` turns normalized league and matchup data into the numbers a
manager actually wants to read: standings, who scored the most in a given
week, all-play records, expected wins and schedule luck, week-to-week
consistency, strength of schedule, a documented power ranking, and
manager-vs-manager head-to-head/rivalry history. It performs **no network
I/O** and computes deterministically from already-built inputs, so every
function here is unit-testable offline and safe to call repeatedly.

## What this layer consumes

Two shapes feed almost everything in this package:

- **`teams_df`** -- `LeagueSnapshot.teams_df` (see
  [`docs/league.md`](league.md)): `["roster_id", "owner_id", "display_name",
  "team_name"]`, one row per roster. Used everywhere only to resolve an
  `owner`/`display_name` label; a `roster_id` missing from `teams_df`
  resolves to `owner = None` rather than raising, consistently across every
  module on this page.
- **`season_matchup_df`** -- the output of
  [`build_season_matchup_df`](../src/fantasy_analyzer/matchups/season_matchups.py#L73)
  (`fantasy_analyzer.matchups.season_matchups`), the canonical one-row-per-matchup
  table produced by the `fantasy_analyzer.matchups` pipeline (raw Sleeper
  weekly matchups -> paired opponents -> derived winner/loser/margin ->
  this frame). It carries, per matchup, the two rosters and their points,
  the resolved `owner_1`/`owner_2` display labels, and the derived
  `winner`/`loser`/`is_tie`/`margin`/`point_differential` outcome fields --
  with a bye row (one roster, no opponent) represented by `roster_2_id` and
  every outcome field `None`, and a missing score never treated as `0.0`
  anywhere in this package. **Full column-by-column schema:**
  [`docs/matchups.md`'s "The canonical `season_matchup_df` schema"](matchups.md#the-canonical-season_matchup_df-schema).
  That page also covers how to build one from a live league
  (`fantasy_analyzer.matchups`: `load_season_matchups` ->
  `pair_season_matchups` -> `derive_season_outcomes` ->
  `build_season_matchup_df`).

- **`rosters_df`** -- `LeagueSnapshot.rosters_df` (see
  [`docs/league.md`](league.md)): Sleeper's own season-cumulative
  `["roster_id", "wins", "losses", "ties", "fpts", "fpts_against"]`. Only
  `standings.py`/`summary.py` use this; everything else on this page is
  derived from `season_matchup_df` instead, because Sleeper's cumulative
  roster counters cannot be split by week or by season phase (see
  `standings.py`'s module docstring).

## Quick start: from a season of matchups to every Epic 6 metric

This is the highest-level entry point:
[`build_league_analytics`](../src/fantasy_analyzer/analytics/league_analytics.py#L317)
composes weekly scoring ranks, all-play standings, schedule luck,
consistency, strength of schedule, and power rankings into one object. This
example is fully offline -- it hand-builds a tiny 3-roster,
3-week `season_matchup_df` (one bye per week) instead of fetching one from
Sleeper, the same fixture shape `tests/analytics/test_league_analytics.py`
uses -- so you can paste and run it as-is:

```python
import pandas as pd
from fantasy_analyzer.analytics import build_league_analytics
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def game(roster_1_id, roster_2_id, points_1, points_2, week, matchup_id=1):
    """Build one SEASON_MATCHUP_COLUMNS row (outcome fields derived by hand,
    the way build_season_matchup_df's upstream pipeline would)."""
    winner = loser = margin = point_differential = None
    is_tie = False
    if roster_2_id is not None and points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
        if points_1 > points_2:
            winner, loser = roster_1_id, roster_2_id
        elif points_1 < points_2:
            winner, loser = roster_2_id, roster_1_id
        else:
            is_tie = True
    return {
        "season": "2025", "week": week, "is_playoff": False, "matchup_id": matchup_id,
        "roster_1_id": roster_1_id, "roster_2_id": roster_2_id,
        "owner_1": None, "owner_2": None,
        "points_1": points_1, "points_2": points_2,
        "winner": winner, "loser": loser, "is_tie": is_tie,
        "margin": margin, "point_differential": point_differential,
    }


rows = [
    game(1, 2, 120.0, 100.0, week=1),
    game(3, None, 90.0, None, week=1, matchup_id=None),   # roster 3 on a bye
    game(2, 3, 110.0, 95.0, week=2),
    game(1, None, 85.0, None, week=2, matchup_id=None),
    game(1, 3, 115.0, 105.0, week=3),
    game(2, None, 80.0, None, week=3, matchup_id=None),
]
season_matchup_df = pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)

teams_df = pd.DataFrame([
    {"roster_id": 1, "owner_id": "u1", "display_name": "Alec", "team_name": "Alec"},
    {"roster_id": 2, "owner_id": "u2", "display_name": "Mike", "team_name": "Mike"},
    {"roster_id": 3, "owner_id": "u3", "display_name": "Joe",  "team_name": "Joe"},
])

# In practice season_matchup_df comes from your own league's matchup pipeline
# (fantasy_analyzer.matchups: load_season_matchups -> pair_season_matchups ->
# derive_season_outcomes -> build_season_matchup_df) and teams_df comes from
# snapshot.teams_df on a LeagueSnapshot built with your own league_id -- see
# docs/league.md for how to get a LeagueSnapshot.
analytics = build_league_analytics(season_matchup_df, teams_df)

print(analytics.all_play())
print(analytics.schedule_luck())
print(analytics.power_rankings())
```

**Verified offline** with `.venv/bin/python`. Real output for `analytics.all_play()`:

```text
   roster_id owner  weeks_played  all_play_wins  all_play_losses  all_play_ties  all_play_games  all_play_win_pct  all_play_rank
0          1  Alec             3              4                2              0               6          0.666667              1
1          2  Mike             3              3                3              0               6          0.500000              2
2          3   Joe             3              2                4              0               6          0.333333              3
```

and for `analytics.power_rankings()`:

```text
   roster_id owner  games_played  win_pct  all_play_win_pct  mean_points  win_pct_z  all_play_win_pct_z  mean_points_z  power_score  power_rank
0          1  Alec             2      1.0          0.666667   106.666667   1.224745            1.224745       1.414214     1.262639           1
1          2  Mike             2      0.5          0.500000    96.666667   0.000000            0.000000      -0.707107    -0.141421           2
2          3   Joe             2      0.0          0.333333    96.666667  -1.224745           -1.224745      -0.707107    -1.121217           3
```

`analytics.schedule_luck()`'s real output is shown in that section below.
Column meanings for every one of these are defined section-by-section in the
Reference below -- this quick start is only here to show the call shape.

**Getting a real `season_matchup_df` against your own league** is a
multi-step pipeline (`fantasy_analyzer.matchups`:
`load_season_matchups` -> `pair_season_matchups` -> `derive_season_outcomes`
-> `build_season_matchup_df`), each step itself loadable independently and
documented in full on [`docs/matchups.md`](matchups.md).
`notebooks/league_walkthrough.ipynb` runs the whole thing against live
Sleeper data end to end, immediately followed by the same
`build_league_analytics` call shown above.

## Reference

### `fantasy_analyzer.analytics` (package exports)

[`__init__.py`](../src/fantasy_analyzer/analytics/__init__.py) re-exports the
public surface of every module on this page. Import from the package
directly (`from fantasy_analyzer.analytics import ...`) rather than reaching
into submodules -- the `__all__` list is the contract:

`build_standings`, `build_scoring_summary`, `build_league_summary`,
`LeagueSummary`, `LeagueSummaryView`, `build_head_to_head_records`,
`build_head_to_head_matrix`, `format_head_to_head_matrix`, `HeadToHeadCell`,
`build_rivalry_records`, `RivalryGame`, `build_matchup_history`,
`MatchupHistory`, `HeadToHeadHistory`, `HeadToHeadByPhase`,
`HeadToHeadPhaseRecord`, `build_weekly_scoring_ranks`,
`build_all_play_standings`, `build_schedule_luck`,
`build_consistency_metrics`, `build_strength_of_schedule`,
`build_power_rankings`, `build_league_analytics`, `LeagueAnalytics`, plus the
column-order constants and tuning constants named per module below.

Every ranked column in this package uses the same tie convention unless
stated otherwise: **standard competition ("1224") ranking** -- tied values
share a rank, and the next distinct rank skips the number of tied rows (two
teams tied for 1st both get rank `1`, and the next team gets `3`, not `2`).

---

### League summary -- standings and scoring rate (FFA-020/021/023)

**Answers:** "where does my team stand", "who's actually scoring the most
points per game (not just winning)".

Module:
[`analytics/standings.py`](../src/fantasy_analyzer/analytics/standings.py) --
metric definitions and edge cases live in its module docstring
([lines 1-93](../src/fantasy_analyzer/analytics/standings.py#L1)).
Composed into the ergonomic entry point by
[`analytics/summary.py`](../src/fantasy_analyzer/analytics/summary.py).

**[`build_standings(rosters_df: pd.DataFrame, teams_df: pd.DataFrame) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/standings.py#L140)**

- `rosters_df`: `LeagueSnapshot.rosters_df`-shaped, needs at least
  `["roster_id", "wins", "losses", "ties", "fpts", "fpts_against"]`.
- `teams_df`: `LeagueSnapshot.teams_df`-shaped, needs at least
  `["roster_id", "owner_id", "display_name", "team_name"]`.
- Returns `STANDINGS_COLUMNS` (defined at
  [line 100](../src/fantasy_analyzer/analytics/standings.py#L100)), one row
  per roster, sorted by descending `win_pct` then descending `points_for`:

  | Column | Meaning |
  |---|---|
  | `roster_id`, `owner_id`, `display_name`, `team_name` | Identity/labels from `teams_df`. |
  | `wins`, `losses`, `ties` | Passed through unchanged from Sleeper's cumulative roster counters. |
  | `win_pct` | `(wins + 0.5*ties) / (wins+losses+ties)`; `0.0` (not `NaN`) at zero games played. |
  | `points_for`, `points_against` | Passed through from `rosters_df["fpts"]`/`["fpts_against"]`. |
  | `point_diff` | `points_for - points_against`. |
  | `rank` | 1-indexed standard competition rank on (`win_pct` desc, `points_for` desc tiebreak). |

  Empty input (either frame) returns an empty, correctly-columned frame.

**[`build_scoring_summary(rosters_df, teams_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/standings.py#L222)**

  Returns `SCORING_SUMMARY_COLUMNS` (defined at
  [line 116](../src/fantasy_analyzer/analytics/standings.py#L116)):
  `roster_id`, `owner_id`, `display_name`, `team_name`, `points_per_game`
  (`points_for / games_played`, `0.0` at zero games), `points_against_per_game`,
  `scoring_rank` (1-indexed rank on cumulative `points_for`, **not**
  `points_per_game`), `avg_margin` (`point_diff / games_played`).

  **Not implemented, by design:** `high_score`/`low_score` (a team's single
  best/worst week). Sleeper's roster-level counters only expose
  season-cumulative totals, not a per-week history, so there is no way to
  derive a single game's high/low from this module's inputs; the module
  docstring calls this out explicitly rather than approximating it.

**Regular season vs. playoffs:** neither function makes any distinction.
Sleeper's cumulative `wins`/`losses`/`fpts` counters mix both phases
indistinguishably at the roster-settings level -- there is no way to split
them without matchup-level data (see `head_to_head.py` and friends below,
which use `season_matchup_df` instead and so can be pre-filtered).

**Composition layer:**
[`LeagueSummary`](../src/fantasy_analyzer/analytics/summary.py#L63) /
[`build_league_summary(snapshot: LeagueSnapshot, total_weeks: int) -> LeagueSummary`](../src/fantasy_analyzer/analytics/summary.py#L144)
wrap the two functions above over a `LeagueSnapshot`, adding
`season_boundaries` (via
[`derive_season_boundaries`](../src/fantasy_analyzer/league/season.py#L46),
documented on [page one](league.md)). `LeagueSummary.standings()` and
`.scoring_summary()` are thin per-call passthroughs;
`.league_summary()` returns a
[`LeagueSummaryView`](../src/fantasy_analyzer/analytics/summary.py#L32)
dataclass bundling league metadata, both DataFrames, and the season
boundaries in one call. This defines no new metrics of its own.

```python
from fantasy_analyzer.analytics import build_standings, build_scoring_summary
import pandas as pd

rosters_df = pd.DataFrame([
    {"roster_id": 1, "owner_id": "u1", "wins": 2, "losses": 0, "ties": 0, "fpts": 320.0, "fpts_against": 290.0},
    {"roster_id": 2, "owner_id": "u2", "wins": 1, "losses": 1, "ties": 0, "fpts": 290.0, "fpts_against": 305.0},
    {"roster_id": 3, "owner_id": "u3", "wins": 0, "losses": 2, "ties": 0, "fpts": 290.0, "fpts_against": 315.0},
])
teams_df = pd.DataFrame([
    {"roster_id": 1, "owner_id": "u1", "display_name": "Alec", "team_name": "Alec"},
    {"roster_id": 2, "owner_id": "u2", "display_name": "Mike", "team_name": "Mike"},
    {"roster_id": 3, "owner_id": "u3", "display_name": "Joe",  "team_name": "Joe"},
])
build_standings(rosters_df, teams_df)
```

**Verified offline** -- real output:

```text
   roster_id owner_id display_name team_name  wins  losses  ties  win_pct  points_for  points_against  point_diff  rank
0          1       u1         Alec      Alec     2       0     0      1.0       320.0           290.0        30.0     1
1          2       u2         Mike      Mike     1       1     0      0.5       290.0           305.0       -15.0     2
2          3       u3          Joe       Joe     0       2     0      0.0       290.0           315.0       -25.0     3
```

Note roster 2 and roster 3 both have 290.0 points_for but different
`win_pct`, so they are *not* tied here -- `build_scoring_summary` on the same
input, by contrast, ranks `scoring_rank` on `points_for` alone and does show
2 and 3 tied at rank 2 (verified in the same run):

```text
   roster_id owner_id display_name team_name  points_per_game  points_against_per_game  scoring_rank  avg_margin
0          1       u1         Alec      Alec            160.0                    145.0             1        15.0
1          2       u2         Mike      Mike            145.0                    152.5             2        -7.5
2          3       u3          Joe       Joe            145.0                    157.5             2       -12.5
```

---

### Head-to-head, the matrix, and rivalries (Epic 5: FFA-040/041/042/043/044)

**Answers:** "what's my record against this specific manager", "show me the
whole league's head-to-head grid", "which of my rivalries has the closest
games / biggest blowouts".

**[`build_head_to_head_records(season_matchup_df, teams_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/head_to_head.py#L166)**
([module docstring](../src/fantasy_analyzer/analytics/head_to_head.py#L1))

Emits **two rows per meeting** -- one from each roster's perspective -- so
`(roster_id=A, opponent_roster_id=B)` and `(roster_id=B,
opponent_roster_id=A)` are mirror images, not one combined row. Returns
`HEAD_TO_HEAD_COLUMNS` ([line 135](../src/fantasy_analyzer/analytics/head_to_head.py#L135)):

| Column | Meaning |
|---|---|
| `roster_id`, `opponent_roster_id` | The ordered pair. |
| `owner`, `opponent_owner` | Display labels, `None` if unmapped. |
| `meetings` | Times this pair played (bye rows excluded; a missing-points row still counts as a meeting). |
| `wins`, `losses`, `ties` | From `roster_id`'s perspective. An unresolved outcome (missing points) contributes to none of the three. |
| `total_points`, `total_opponent_points` | Summed over meetings (missing points contribute `0`, not counted as a game total change). |
| `avg_points`, `avg_opponent_points` | `total_points / meetings`. Never a division by zero -- a pair with zero meetings gets no row at all. |

**Metric definitions:** all counts are direct sums over qualifying rows; no
formula beyond arithmetic averages. **Ties:** counted in `ties`, contribute
`0` wins/losses to either side. **Regular season vs. playoffs:** combined,
no `is_playoff` filter applied internally -- pre-filter `season_matchup_df`
before calling for a phase-scoped table (see `MatchupHistory` below for a
built-in split).

**[`build_head_to_head_matrix(head_to_head_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/head_to_head_matrix.py#L257)**
and
**[`format_head_to_head_matrix(head_to_head_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/head_to_head_matrix.py#L329)**
([module docstring](../src/fantasy_analyzer/analytics/head_to_head_matrix.py#L1))

Pure reshaping, no new metrics: pivot `build_head_to_head_records`'s output
into a roster-by-roster grid. The raw form
(`build_head_to_head_matrix`) is `roster_id`-indexed on both axes with cells
as [`HeadToHeadCell`](../src/fantasy_analyzer/analytics/head_to_head_matrix.py#L182)
(`meetings`, `wins`, `losses`, `ties`); the diagonal is `None` (self-meetings
are meaningless) and a never-met pair is a zeroed cell
(`meetings=0`), not `None` -- so `cell.meetings == 0` is a safe check that
never needs a `None` guard. `format_head_to_head_matrix` renders the same
grid with owner-name axes and `"W-L"` (or `"W-L-T"` if there are ties) string
cells, `"—"` (`HEAD_TO_HEAD_MATRIX_DIAGONAL`) on the diagonal, and `""`
(`HEAD_TO_HEAD_MATRIX_NO_MEETING`) for a never-met pair. The display form is
lossy (not parseable back to counts) and its axis labels can collide on
duplicate display names -- use the raw matrix for anything programmatic.

**[`build_rivalry_records(season_matchup_df, teams_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/rivalries.py#L282)**
([module docstring](../src/fantasy_analyzer/analytics/rivalries.py#L1))

Extends the same directional-pair shape with per-game extrema. Returns
`RIVALRY_COLUMNS` ([line 197](../src/fantasy_analyzer/analytics/rivalries.py#L197)):
`roster_id`, `opponent_roster_id`, `owner`, `opponent_owner`, `meetings`,
`scored_meetings` (meetings with both scores present -- the honest
denominator for the stats below, `<= meetings`), `avg_margin` (mean
*absolute* margin over scored meetings, `NaN` if none), and four
[`RivalryGame`](../src/fantasy_analyzer/analytics/rivalries.py#L213) columns
-- `closest_game` (smallest margin), `largest_win` (largest margin among
`roster_id`'s wins, `None` if it never won), `largest_loss` (same for
losses), `highest_scoring_matchup` (largest `points + opponent_points`).
Each of the four is resolved independently, so a rivalry that's all ties
still gets `closest_game`/`highest_scoring_matchup` but `None` for both win
and loss extrema. `margin` is always non-negative -- direction lives in
*which* column a game appears under, not in the sign.

```python
from fantasy_analyzer.analytics import (
    build_head_to_head_records, format_head_to_head_matrix, build_rivalry_records,
)
# season_matchup_df/teams_df from the quick-start example above
h2h = build_head_to_head_records(season_matchup_df, teams_df)
format_head_to_head_matrix(h2h)
```

**Verified offline** -- real output:

```text
opponent_owner Alec Mike  Joe
owner                        
Alec              —  1-0  1-0
Mike            0-1    —  1-0
Joe             0-1  0-1    —
```

**Composition layer:**
[`MatchupHistory`](../src/fantasy_analyzer/analytics/matchup_history.py#L362) /
[`build_matchup_history(season_matchup_df, teams_df) -> MatchupHistory`](../src/fantasy_analyzer/analytics/matchup_history.py#L558)
wraps all three of the above plus a phase-split view. Both
`head_to_head_df` and `rivalry_df` (and, for FFA-044, `regular_season_head_to_head_df`
/ `playoff_head_to_head_df`) are computed **once** at construction. Key
methods:

- **`.head_to_head(team_a: int, team_b: int) -> Optional[HeadToHeadHistory]`**
  -- looks up an ordered pair by `roster_id` (never by owner name -- names
  aren't unique or immutable) and returns a flattened
  [`HeadToHeadHistory`](../src/fantasy_analyzer/analytics/matchup_history.py#L176)
  combining the head-to-head record and rivalry stats. Returns `None` if the
  pair never met (including `team_a == team_b`) -- a normal result, not an
  error.
- **`.head_to_head_by_phase(team_a, team_b) -> Optional[HeadToHeadByPhase]`**
  (FFA-044) -- same lookup, but split into
  [`HeadToHeadByPhase`](../src/fantasy_analyzer/analytics/matchup_history.py#L291)`.regular_season`
  / `.playoffs`, each an optional
  [`HeadToHeadPhaseRecord`](../src/fantasy_analyzer/analytics/matchup_history.py#L239)
  (no rivalry stats at this level). Either field is `None` if the pair never
  met in that phase; the whole thing is `None` only if they never met in
  either phase.
- **`.head_to_head_matrix()`** / **`.formatted_head_to_head_matrix()`** --
  thin passthroughs to the matrix functions above, over the cached
  `head_to_head_df`.

```python
from fantasy_analyzer.analytics import build_matchup_history
history = build_matchup_history(season_matchup_df, teams_df)
history.head_to_head(1, 3)
```

**Verified offline** -- real output:

```text
HeadToHeadHistory(roster_id=1, opponent_roster_id=3, owner='Alec', opponent_owner='Joe', meetings=1, wins=1, losses=0, ties=0, total_points=115.0, total_opponent_points=105.0, avg_points=115.0, avg_opponent_points=105.0, scored_meetings=1, avg_margin=10.0, closest_game=RivalryGame(season='2025', week=3, is_playoff=False, matchup_id=1, roster_id=1, opponent_roster_id=3, points=115.0, opponent_points=105.0, margin=10.0, combined_points=220.0), largest_win=RivalryGame(...), largest_loss=None, highest_scoring_matchup=RivalryGame(...))
```

`largest_loss=None` here because roster 1 has never lost to roster 3 in this
toy data.

---

### Weekly scoring ranks (FFA-050) -- the shared foundation

**Answers:** "who scored the most this week" (a scoring question, entirely
independent of who won the actual matchup).

**[`build_weekly_scoring_ranks(season_matchup_df, teams_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/weekly_scores.py#L212)**
([module docstring](../src/fantasy_analyzer/analytics/weekly_scores.py#L1))

Reshapes the wide (one row per matchup) `season_matchup_df` into the long
(one row per roster-week) form that `all_play.py` and `consistency.py`
consume. Returns `WEEKLY_SCORING_RANK_COLUMNS`
([line 165](../src/fantasy_analyzer/analytics/weekly_scores.py#L165)):
`season`, `week`, `is_playoff`, `roster_id`, `owner`, `points`,
`weekly_rank` (1-indexed, `1` = that week's top score, standard competition
ranking within each `(season, week)`).

- **Bye rows are included** -- a bye is a real score with no opponent, and
  it still competes for that week's rank.
- **Missing scores are excluded entirely**, never treated as `0.0` -- such
  a roster-week produces no row (not a null rank).
- Raises `ValueError` if the same `(season, week, roster_id)` appears more
  than once -- a data-integrity anomaly, not a normal input.
- Makes **no** regular-season/playoff distinction; `is_playoff` is carried
  through as an informational column only.

This function is rarely called directly by an end user -- it's the shared
input `build_all_play_standings` and `build_consistency_metrics` both take,
and it's what `LeagueAnalytics` caches once at construction (see below).

---

### All-play standings (FFA-051)

**Answers:** "was my record earned, or did I get lucky/unlucky with the
schedule" (half of the answer -- the "how good was I really" half).

**[`build_all_play_standings(weekly_scoring_ranks_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/all_play.py#L265)**
([module docstring](../src/fantasy_analyzer/analytics/all_play.py#L1))

**Metric:** for every week, compares each roster's score against every
*other* scored roster's that week (win if higher, loss if lower, tie if
equal), summed over the season. Returns `ALL_PLAY_STANDINGS_COLUMNS`
([line 201](../src/fantasy_analyzer/analytics/all_play.py#L201)):

| Column | Meaning |
|---|---|
| `roster_id`, `owner` | Identity. |
| `weeks_played` | Weeks with a defined score. |
| `all_play_wins`/`losses`/`ties` | Summed pairwise results across the season. |
| `all_play_games` | `wins+losses+ties`; grows roughly as `weeks_played * (field_size - 1)`, so it is **not** the same denominator as `weeks_played` and differs roster-to-roster if some weeks have missing scores. |
| `all_play_win_pct` | `(wins + 0.5*ties) / all_play_games`; `0.0` at zero games. **Compare rosters on this rate, not on raw `all_play_wins`.** |
| `all_play_rank` | 1-indexed standard competition rank on `all_play_win_pct` alone (no secondary tiebreak). |

**Tie handling:** a tie is credited to both sides (never as a win to one,
loss to the other); ties use exact float equality (Sleeper reports to two
decimals, so this is reliable in practice). **Regular season vs.
playoffs:** combined; pre-filter `weekly_scoring_ranks_df` on `is_playoff`
before calling for a phase-scoped view. **Rows are input-driven:** a roster
with no scored week anywhere gets no row (an all-play rate over zero
observations is undefined, not `0.0`).

---

### Expected wins and schedule luck (FFA-052)

**Answers:** "did my record match how well I actually scored, or is my
schedule to blame/thank" (the other half of the "was I lucky" question, and
the sharpest single number for it).

**[`build_schedule_luck(season_matchup_df, teams_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/schedule_luck.py#L293)**
([module docstring](../src/fantasy_analyzer/analytics/schedule_luck.py#L1))

Builds **both halves of the comparison from the same input frame**
specifically so they can never silently cover different sets of games (the
module docstring documents a real bug this design prevents: comparing a
14-week actual record against an 18-week all-play rate). Returns
`SCHEDULE_LUCK_COLUMNS` ([line 255](../src/fantasy_analyzer/analytics/schedule_luck.py#L255)):

| Column | Meaning |
|---|---|
| `roster_id`, `owner` | Identity. |
| `games_played` | Decided games (`wins+losses+ties` from actual matchups) -- **not** the same as all-play's `weeks_played`; a bye week counts toward all-play scoring strength but not toward a decision. |
| `wins`, `losses`, `ties`, `win_pct` | The roster's real record over `games_played`. |
| `all_play_games`, `all_play_win_pct`, `all_play_rank` | Carried through from `build_all_play_standings`. |
| `expected_wins` | `all_play_win_pct * games_played`. |
| `expected_losses` | `games_played - expected_wins` (so the two always sum exactly to `games_played`, including in floating point). |
| `schedule_luck` | `(wins + 0.5*ties) - expected_wins`. **Positive = lucky** (record beat scoring strength); **negative = unlucky**. |
| `schedule_luck_rank` | 1-indexed, **rank 1 = luckiest roster**, not the best team. |

**Metric definition (formula), from `AGENTS.md`'s own worked example** (a
roster 8-6 with `all_play_win_pct = 10/14`):
```
expected_wins   = 10.0
expected_losses = 4.0
schedule_luck   = 8 - 10.0 = -2.0
```
reproduced exactly by
[`tests/analytics/test_schedule_luck.py::test_agents_md_worked_example`](../tests/analytics/test_schedule_luck.py#L198).
**Tie handling:** the actual side uses `wins + 0.5*ties` (half credit),
matching the half-credit already baked into `all_play_win_pct`, so a tied
game is never reported as bad luck purely for being a tie. **Regular season
vs. playoffs:** combined; filter `season_matchup_df` to
`is_playoff == False` *before* calling for the conventional view -- a
playoff bracket is seeded, not scheduled, so "luck" means something
different there. **A bye-only roster gets no row** (it has all-play scoring
strength but zero decisions to be lucky or unlucky about).

```python
from fantasy_analyzer.analytics import build_schedule_luck
build_schedule_luck(season_matchup_df, teams_df)  # from the quick-start data
```

**Verified offline** -- real output:

```text
   roster_id owner  games_played  wins  losses  ties  win_pct  all_play_games  all_play_win_pct  all_play_rank  expected_wins  expected_losses  schedule_luck  schedule_luck_rank
0          1  Alec             2     2       0     0      1.0               6          0.666667              1       1.333333         0.666667       0.666667                   1
1          2  Mike             2     1       1     0      0.5               6          0.500000              2       1.000000         1.000000       0.000000                   2
2          3   Joe             2     0       2     0      0.0               6          0.333333              3       0.666667         1.333333      -0.666667                   3
```

Roster 1 went 2-0 while its all-play rate said it "deserved" 1.33 wins --
`+0.67` luck. This is a 2-game sample, purely illustrative of the shape;
see the interpretation note in the report about small-sample reads.

---

### Consistency metrics (FFA-053)

**Answers:** "is this team a steady week-in-week-out scorer, or a
boom-or-bust roster" -- independent of how good the team actually is.

**[`build_consistency_metrics(weekly_scoring_ranks_df, boom_bust_threshold=1.0) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/consistency.py#L449)**
([module docstring](../src/fantasy_analyzer/analytics/consistency.py#L1))

Every metric here is **within-roster** -- nothing compares one roster
against another (that's what all-play and `weekly_rank` are for). A roster
that scores 70 every single week is "maximally consistent" by these columns
and also the worst team in the league; `mean_points` is included precisely
so consistency is never read without its level. Returns
`CONSISTENCY_METRICS_COLUMNS`
([line 342](../src/fantasy_analyzer/analytics/consistency.py#L342)):

| Column | Meaning |
|---|---|
| `roster_id`, `owner`, `weeks_played` | Identity and sample size (the denominator behind every column below). |
| `mean_points`, `median_points` | Center of the weekly-score distribution. |
| `stdev_points` | **Population** standard deviation (`ddof=0`, via `statistics.pstdev` -- deliberately *not* pandas'/`statistics.stdev`'s sample default). `NaN` if `weeks_played < 2`. |
| `cv` | Coefficient of variation, `stdev_points / mean_points` (a scale-free volatility measure). `NaN` if `stdev_points` is undefined or `mean_points <= 0`. |
| `scoring_floor`, `scoring_ceiling` | Single worst/best week (not an estimated quantile). |
| `boom_weeks`, `boom_pct` | Weeks scoring `> mean + k*stdev` (default `k = 1.0`, `BOOM_BUST_THRESHOLD_STDEVS`, a chosen convention). `NaN` if `weeks_played < 3`. |
| `bust_weeks`, `bust_pct` | Weeks scoring `< mean - k*stdev`. Same `NaN` rule. |

**Why boom/bust needs `weeks_played >= 3`:** at exactly 2 weeks, the
classification is **provably independent of the actual scores** -- for any
two values `a < b`, `b` sits exactly one population standard deviation
above the mean, so at `k=1.0` it always counts (or the arithmetic randomly
tips it either way on floating-point noise). The module docstring reports
this was empirically ~30% noise-driven over 20,000 random two-week pairs.
Playoff-only slices (2-3 weeks) hit this routinely -- `boom_pct`/`bust_pct`
will mostly be `NaN` there, by design, not a bug.

**Reading the resolution honestly:** validated against a live 2025
twelve-team, 14-week regular season, `boom_weeks` ranged only 1-3 and
`bust_weeks` only 1-4 across all twelve rosters (eight of twelve tied at
exactly 2 busts) -- a one-boom difference between two teams is noise at
this sample size. `stdev_points`/`cv` separated the same field far more
usefully (`cv` ranged 0.131-0.251). **Use `stdev_points`/`cv` for ordering
teams by volatility; treat boom/bust as a coarse shape descriptor.**

**No rank column, deliberately:** consistency has no single "better"
direction (low `stdev_points` protects a lead for a strong team but is bad
for a weak one that needs variance to win), so this frame is not ranked --
sort on the specific column you mean.

```python
from fantasy_analyzer.analytics import build_consistency_metrics, build_weekly_scoring_ranks
weekly = build_weekly_scoring_ranks(season_matchup_df, teams_df)
build_consistency_metrics(weekly)
```

**Verified offline** -- real output:

```text
   roster_id owner  weeks_played  mean_points  median_points  stdev_points        cv  scoring_floor  scoring_ceiling  boom_weeks  boom_pct  bust_weeks  bust_pct
0          1  Alec             3   106.666667          115.0     15.456031  0.144900           85.0            120.0         0.0  0.000000         1.0  0.333333
1          2  Mike             3    96.666667          100.0     12.472191  0.129023           80.0            110.0         1.0  0.333333         1.0  0.333333
2          3   Joe             3    96.666667           95.0      6.236096  0.064511           90.0            105.0         1.0  0.333333         1.0  0.333333
```

---

### Strength of schedule (FFA-054)

**Answers:** "how tough were the opponents I actually faced" -- the
companion to schedule luck (luck is *whether* your record diverged from
your scoring; this is *one concrete reason* it might have).

**[`build_strength_of_schedule(season_matchup_df, teams_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/strength_of_schedule.py#L334)**
([module docstring](../src/fantasy_analyzer/analytics/strength_of_schedule.py#L1))

Reports **two** measures of opponent quality side by side, rather than
picking one:

| Column | Meaning |
|---|---|
| `roster_id`, `owner` | Identity. |
| `opponent_weeks` | Weeks with a real, resolvable opponent -- the sample size for both averages below. |
| `unresolved_opponent_weeks` | Weeks with a real opponent whose own strength couldn't be computed (that opponent had zero decided games itself); normally `0`. |
| `avg_opponent_win_pct` | Mean of each faced opponent's **actual** season `win_pct` -- the traditional "opponents' combined win percentage" reading. |
| `sos_rank` | 1-indexed rank on `avg_opponent_win_pct`, **rank 1 = toughest schedule** (this is the "worse for you" direction, unlike most rank columns in this package). |
| `avg_opponent_all_play_win_pct` | Mean of each faced opponent's schedule-independent `all_play_win_pct` -- not itself contaminated by whether that opponent's own record was lucky. |
| `all_play_sos_rank` | Same rank-1-is-toughest convention, computed independently on the all-play column. |

**Why report both:** a roster whose `avg_opponent_win_pct` is high but
whose `avg_opponent_all_play_win_pct` is middling faced opponents who were
themselves *lucky* -- their records looked tough on paper, but they weren't
actually scoring like strong teams. Reading only one column would miss this.

**A structural artifact worth knowing:** because no roster ever plays
itself, the league's best team almost mechanically has the league's
weakest schedule (everyone else has to play it; it never has to play
itself), and the worst team the toughest. This is not evidence of unfair
scheduling.

**Bye weeks vs. unresolvable opponents:** a bye contributes to neither
`opponent_weeks` nor `unresolved_opponent_weeks` (there's no opponent at
all); an opponent whose own record is entirely undecided contributes to
`unresolved_opponent_weeks` but not the averages. **Regular season vs.
playoffs:** combined, no internal filter -- filter `season_matchup_df` on
`is_playoff` before calling, same rule as `schedule_luck`.

```python
from fantasy_analyzer.analytics import build_strength_of_schedule
build_strength_of_schedule(season_matchup_df, teams_df)
```

**Verified offline** -- real output:

```text
   roster_id owner  opponent_weeks  unresolved_opponent_weeks  avg_opponent_win_pct  sos_rank  avg_opponent_all_play_win_pct  all_play_sos_rank
0          3   Joe               2                          0                  0.75         1                       0.583333                   1
1          2  Mike               2                          0                  0.50         2                       0.500000                   2
2          1  Alec               2                          0                  0.25         3                       0.416667                   3
```

Roster 3 (Joe) faced the toughest schedule by both measures (`sos_rank = 1`)
-- consistent with it also being the weakest team in `power_rankings()`
above, per the "worst team gets the toughest schedule" artifact noted above.

---

### Power rankings (FFA-056)

**Answers:** "who is actually the strongest team right now" -- a single,
documented composite, explicitly not a projection.

**[`build_power_rankings(season_matchup_df, teams_df) -> pd.DataFrame`](../src/fantasy_analyzer/analytics/power_rankings.py#L337)**
([module docstring](../src/fantasy_analyzer/analytics/power_rankings.py#L1))

**Formula** (module constants
[`WIN_PCT_WEIGHT = 0.3`](../src/fantasy_analyzer/analytics/power_rankings.py#L310),
[`ALL_PLAY_WIN_PCT_WEIGHT = 0.5`](../src/fantasy_analyzer/analytics/power_rankings.py#L314),
[`MEAN_POINTS_WEIGHT = 0.2`](../src/fantasy_analyzer/analytics/power_rankings.py#L318)):

```
power_score = 0.3 * z(win_pct) + 0.5 * z(all_play_win_pct) + 0.2 * z(mean_points)
```

where each `z(...)` is a **population** z-score (`(x - mean) / pstdev`)
computed **within the set of rosters this call produces a row for** (not
against any external/historical baseline). If a feature has zero variance
across the row set, its z-score is `0.0` for everyone (not `NaN`/a
division error) and the other feature(s) alone decide the ordering.

Returns `POWER_RANKING_COLUMNS`
([line 294](../src/fantasy_analyzer/analytics/power_rankings.py#L294)):
`roster_id`, `owner`, `games_played`, `win_pct`, `all_play_win_pct`,
`mean_points` (raw feature values, from `build_schedule_luck` and
`build_consistency_metrics` on the same `season_matchup_df`), `win_pct_z`,
`all_play_win_pct_z`, `mean_points_z` (their z-scores), `power_score`, and
`power_rank` (1-indexed, **rank 1 = strongest team**, standard competition
ranking, no secondary tiebreak).

**Why these three features and not others** (stated plainly so you don't
read more into the score than it claims):

- **`schedule_luck` is deliberately excluded** -- it's an exact linear
  function of `win_pct` and `all_play_win_pct` already in the composite, so
  adding it would double-count the same contrast under a new name.
- **Consistency/volatility (`stdev_points`, `cv`, boom/bust) is deliberately
  excluded** -- volatility has no single sign of "good": it protects a lead
  for a strong team and is exactly what a weak team needs to steal an
  upset. There is no principled weight for it without silently assuming
  which kind of team a roster is.
- **FFA-055's final playoff placement is deliberately excluded** -- feeding
  a playoff outcome into a "how strong is this team" score would be
  circular (the outcome is downstream of exactly the strength being
  measured), and placement data is frequently and non-uniformly missing for
  rosters that missed the playoffs.

**What this is not:** not a projection (no future schedule, injuries, or
player data feeds it); not validated as predictive (no backtest is
attempted); not a replacement for the individual columns -- they're kept on
the row precisely so you can see *why* two teams landed where they did.

**Regular season vs. playoffs:** combined, no internal filter. Because the
function just uses whatever weeks are in the input, passing weeks `<= N`
naturally gives you a rolling "power ranking as of week N" -- there's no
separate parameter for it.

```python
from fantasy_analyzer.analytics import build_power_rankings
build_power_rankings(season_matchup_df, teams_df)
```

Real, verified output for this call is shown in the Quick Start section
above.

---

### `LeagueAnalytics` -- the Epic 6 composition service (FFA-057)

**[`LeagueAnalytics`](../src/fantasy_analyzer/analytics/league_analytics.py#L173)**
/
**[`build_league_analytics(season_matchup_df, teams_df, winners_bracket_raw=None, losers_bracket_raw=None) -> LeagueAnalytics`](../src/fantasy_analyzer/analytics/league_analytics.py#L317)**
([module docstring](../src/fantasy_analyzer/analytics/league_analytics.py#L1))

The one-stop entry point used in the Quick Start above. Wraps every builder
on this page from `weekly_scores.py` down through `power_rankings.py`, plus
`fantasy_analyzer.matchups.playoffs`'s `build_playoff_brackets`/
`build_final_placements` -- see
[`docs/matchups.md`'s "Playoff brackets and final placements"](matchups.md#playoff-brackets-and-final-placements-ffa-055)
for their column-by-column schemas, since they are not otherwise covered on
this page. No new metrics of its own. `weekly_scoring_ranks_df` is cached
once at construction (shared by `.all_play()` and `.consistency()`); every
other method (`.schedule_luck()`, `.strength_of_schedule()`,
`.power_rankings()`) deliberately re-derives its own weekly-scoring-ranks
internally rather than reusing the cache, because each of those functions'
own "both halves must come from one frame" invariant would otherwise be at
risk. `winners_bracket_raw`/`losers_bracket_raw` are optional (`None`
before/without a playoff bracket) and accepted as the *raw* Sleeper bracket
payloads (`client.get_winners_bracket(league_id)` /
`get_losers_bracket(league_id)`), not `season_matchup_df`-shaped data.

Methods: `.all_play()`, `.schedule_luck()`,
`.consistency(boom_bust_threshold=BOOM_BUST_THRESHOLD_STDEVS)`,
`.strength_of_schedule()`, `.power_rankings()`, `.playoff_brackets()`,
`.final_placements()` -- each a thin passthrough to the function of the
same name documented above (playoff methods return empty frames if no
bracket data was supplied).

**Regular season vs. playoffs, one more time:** none of the above filters
internally. If you want a regular-season-only `LeagueAnalytics`, build it
from `season_matchup_df[season_matchup_df["is_playoff"] == False]` -- there
is deliberately no per-method boolean parameter, to avoid quietly
reinventing that same "construct a new instance from a pre-filtered frame"
pattern one flag at a time.
