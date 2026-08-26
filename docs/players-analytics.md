# The `players` layer, part 2: analytics (Epic 7)

This is page five of the `fantasy_analyzer` reference (see
[`docs/league.md`](league.md), [`docs/matchups.md`](matchups.md),
[`docs/analytics.md`](analytics.md), and
[`docs/players-data.md`](players-data.md) for the earlier four). It covers
the second half of
[`src/fantasy_analyzer/players/`](../src/fantasy_analyzer/players/) -- the
metrics built on top of the player-week fact table
[`docs/players-data.md`](players-data.md) documents:
[`performance.py`](../src/fantasy_analyzer/players/performance.py),
[`position_strength.py`](../src/fantasy_analyzer/players/position_strength.py),
[`lineup_efficiency.py`](../src/fantasy_analyzer/players/lineup_efficiency.py),
[`player_value.py`](../src/fantasy_analyzer/players/player_value.py),
[`matchup_contribution.py`](../src/fantasy_analyzer/players/matchup_contribution.py),
[`lineup_tendencies.py`](../src/fantasy_analyzer/players/lineup_tendencies.py),
[`player_rankings.py`](../src/fantasy_analyzer/players/player_rankings.py),
and the top-level composition,
[`player_analytics.py`](../src/fantasy_analyzer/players/player_analytics.py).

Conventions on this page (matching the earlier four):

- Source links point at a specific line in the current `main` (commit
  `6629f59` at time of writing). **Line numbers drift as the code
  changes** -- if a link looks wrong, search the module for the symbol name
  rather than trusting the anchor.
- Sleeper IDs (`sleeper_player_id`, `roster_id`) are always the join keys.
- "Verified" below means run with `.venv/bin/python`, **entirely offline**,
  against small, hand-built `player_week_df`/`season_matchup_df` fixtures --
  no live nflverse or Sleeper call. Several examples reproduce the exact
  hand-checked toy numbers each module's own docstring states (roster
  construction, FLEX usage) so the doc and the source specification agree
  independently of my own arithmetic.

## What this layer is for

Every module here reads
[`player_week_df`](players-data.md#the-canonical-player-week-schema) (FFA-064's
fact table, documented in full on [`docs/players-data.md`](players-data.md))
and answers a progressively more specific question about it:

```text
player_week_df  (one row per rostered player, per week)
        |
        +--> performance.py            (FFA-065) how good/consistent is
        |                                          this player, alone?
        |
        +--> position_strength.py      (FFA-066) how much did a team get
        |                                          from a position group?
        |
        +--> lineup_efficiency.py      (FFA-067) how well did a manager
        |                                          set their lineup?
        |
        +--> player_value.py           (FFA-068) how much is a player worth
        |        (needs performance.py's output)   vs. a replacement pickup?
        |
        +--> matchup_contribution.py   (FFA-069) which players drove a
        |        (also needs season_matchup_df)     specific win/loss?
        |
        +--> lineup_tendencies.py      (FFA-070) what are a manager's
        |        (also needs lineup_efficiency.py)  roster/start-sit habits?
        |
        +--> player_rankings.py        (FFA-073) one league-wide value
        |        (needs performance.py, and             ranking across every
        |         player_value.py internally)           position at once
        |
        +--> player_analytics.py       (FFA-071) one composed entry point
                 (needs performance.py + player_value.py                  
                  + position_strength.py + lineup_efficiency.py
                  + player_rankings.py)
```

Every function on this page performs **no network access** and operates
entirely on already-built DataFrames. Every module reuses
`analytics/consistency.py`'s formulas (population standard deviation, a
self-referential mean +/- k*stdev boom/bust threshold, the same minimum
sample-size guards) wherever the underlying statistical question is
identical, and documents explicitly, module by module, the one or two
places where the player/team/roster grain genuinely demands a different
answer than the team-season grain `analytics/consistency.py` (see
[`docs/analytics.md`](analytics.md)) uses.

**`player_week_df` has no `is_playoff` column at all**, unlike
`season_matchup_df` -- it is built directly from NFL week numbers and a
league's rostered players, with no notion of any one league's playoff
schedule. Every function on this page is therefore **phase-agnostic**: none
makes a regular-season-vs-playoff distinction internally, and a caller
wanting a phase-specific view must pre-filter `player_week_df` on `week`
against the calling league's `playoff_week_start` (see
[`docs/league.md`](league.md)'s `SeasonBoundaries`) *before* calling anything
on this page. This is stated once here because it is true of every builder
below without exception; each module's own docstring restates it, but this
page does not repeat the caveat section by section.

## Quick start: `PlayerAnalytics`, the Epic 7 entry point

[`build_player_analytics`](../src/fantasy_analyzer/players/player_analytics.py#L604)
is the highest-level entry point -- the Epic 7 analog of
[`LeagueAnalytics`](analytics.md#leagueanalytics----the-epic-6-composition-service-ffa-057)
and [`MatchupHistory`](analytics.md). It wires `performance.py`,
`position_strength.py`, `lineup_efficiency.py`, `player_value.py`,
`lineup_tendencies.py`, and `matchup_contribution.py` together over one
`player_week_df` (plus, for the last of those, one `season_matchup_df`).
This example is fully offline: a tiny hand-built `player_week_df` for two
teams, two positions, a few weeks.

```python
import pandas as pd
from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS
from fantasy_analyzer.players.player_analytics import build_player_analytics

# Each row needs a real (possibly missing) provider stat column --
# performance.py (and everything built on it) only counts a week as
# "played" if at least one raw stat column is non-null; fantasy_points
# alone does not qualify (see docs/players-data.md's fact-table schema).
rows = [
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "started": True, "bench": False,
     "passing_yards": 300, "rushing_yards": None, "fantasy_points": 20.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "started": True, "bench": False,
     "passing_yards": 250, "rushing_yards": None, "fantasy_points": 16.0},
    {"season": 2025, "week": 3, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "started": True, "bench": False,
     "passing_yards": 350, "rushing_yards": None, "fantasy_points": 32.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "2000",
     "position": "RB", "started": True, "bench": False,
     "passing_yards": None, "rushing_yards": 50, "fantasy_points": 10.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "2000",
     "position": "RB", "started": True, "bench": False,
     "passing_yards": None, "rushing_yards": 100, "fantasy_points": 20.0},
    {"season": 2025, "week": 3, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "2000",
     "position": "RB", "started": True, "bench": False,
     "passing_yards": None, "rushing_yards": 75, "fantasy_points": 15.0},
    {"season": 2025, "week": 1, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "1002",
     "player_name": "QB Two", "position": "QB", "started": True, "bench": False,
     "passing_yards": 200, "rushing_yards": None, "fantasy_points": 12.0},
    {"season": 2025, "week": 2, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "1002",
     "player_name": "QB Two", "position": "QB", "started": True, "bench": False,
     "passing_yards": 220, "rushing_yards": None, "fantasy_points": 14.0},
    {"season": 2025, "week": 1, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "2002",
     "position": "RB", "started": True, "bench": False,
     "passing_yards": None, "rushing_yards": 25, "fantasy_points": 5.0},
    {"season": 2025, "week": 2, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "2002",
     "position": "RB", "started": True, "bench": False,
     "passing_yards": None, "rushing_yards": 25, "fantasy_points": 5.0},
]
player_week_df = pd.DataFrame(
    rows, columns=PLAYER_WEEK_COLUMNS + ["passing_yards", "rushing_yards", "fantasy_points"]
)

# roster_positions/num_teams describe the league's rules, e.g.
# LeagueSnapshot.roster_positions / LeagueSettings.total_rosters.
analytics = build_player_analytics(
    player_week_df, roster_positions=["QB", "RB", "BN", "BN"], num_teams=2
)

print(analytics.player_season_df[[
    "season", "sleeper_player_id", "player_name", "position", "games_played", "points_per_game"
]])
print(analytics.player_value_df[[
    "sleeper_player_id", "player_name", "position", "points_per_game",
    "replacement_ppg", "points_above_replacement", "value_rank",
]])
print(analytics.roster_efficiency_df[[
    "season", "roster_id", "fantasy_team", "weeks_played",
    "total_actual_points", "total_optimal_points", "efficiency_pct",
]])
```

**Verified offline** with `.venv/bin/python`. Real output:

```text
   season sleeper_player_id player_name position  games_played  points_per_game
0    2025              1000  Josh Allen       QB             3        22.666667
1    2025              1002      QB Two       QB             2        13.000000
2    2025              2000         NaN       RB             3        15.000000
3    2025              2002         NaN       RB             2         5.000000
  sleeper_player_id player_name position  points_per_game  replacement_ppg  points_above_replacement  value_rank
0              2000        None       RB        15.000000              5.0                      30.0           1
1              1000  Josh Allen       QB        22.666667             13.0                      29.0           2
2              1002      QB Two       QB        13.000000             13.0                       0.0           3
3              2002        None       RB         5.000000              5.0                       0.0           3
   season  roster_id fantasy_team  weeks_played  total_actual_points  total_optimal_points  efficiency_pct
0    2025          1         Alec             3                113.0                 113.0             1.0
1    2025          2         Mike             2                 36.0                  36.0             1.0
```

Hand-checked: Josh Allen's `points_per_game = (20+16+32)/3 = 22.667`; the RB
`replacement_ppg` (a 1-RB-starter, 2-team league, so cutoff = `2*1 = 2`, i.e.
the 2nd-best RB) is `5.0` (roster `2002`'s rate); `2000`'s
`points_above_replacement = 45 - 5.0*3 = 30.0`. The two `NaN`/`None`
`player_name` values are real: this hand-built input never supplied a name
for those two rows, and neither builder invents one -- see
[`docs/players-data.md`](players-data.md)'s "Identity enrichment order" for
where a real pipeline would resolve it instead.

**[`PlayerAnalytics`](../src/fantasy_analyzer/players/player_analytics.py#L309)**
-- frozen dataclass over `player_week_df` + `roster_positions` + `num_teams`
(`Optional[int]`, since `LeagueSettings.total_rosters` is optional) + two
boom/bust threshold fields
(`player_boom_bust_threshold`, `position_boom_bust_threshold`, each
defaulting to its own module's constant) + an optional
[`season_matchup_df`](../src/fantasy_analyzer/players/player_analytics.py#L365).
Frames are **attributes**, not
methods (`analytics.player_value_df`, not `analytics.player_value_df()`) --
the shape AGENTS.md's ticket text specifies for this service, unlike
`LeagueAnalytics`'s methods. `player_season_df` is computed **once** at
construction (the same eager-caching pattern `LeagueAnalytics` uses for
`weekly_scoring_ranks_df`); every other attribute is a **lazy, per-access**
recompute -- reading `analytics.position_summary_df` twice does the work
twice. Fifteen attributes total, one per output of every module it
composes:

| Attribute | Source | Grain |
|---|---|---|
| `player_weekly_df` | `player_week_df`, unchanged | `(season, week, roster_id, sleeper_player_id)` |
| `player_season_df` | `performance.py`, FFA-065 (eager) | `(season, sleeper_player_id)` |
| `position_summary_df` | `position_strength.py`, FFA-066 | `(season, fantasy_team, position)` |
| `roster_efficiency_df` | `lineup_efficiency.py`, FFA-067 | `(season, roster_id)` |
| `lineup_efficiency_df` | `lineup_efficiency.py`, FFA-067 | `(season, week, roster_id)` |
| `player_value_df` | `player_value.py`, FFA-068 (from `player_season_df`) | `(season, sleeper_player_id)` |
| `position_scarcity_df` | `player_value.py`, FFA-068 (from `player_season_df`) | `(season, position)` |
| `player_ranking_df` | `player_rankings.py`, FFA-073 (from `player_season_df`) | `(season, sleeper_player_id)` |
| `roster_construction_df` | `lineup_tendencies.py`, FFA-070 | `(season, fantasy_team, position)` |
| `bench_allocation_df` | `lineup_tendencies.py`, FFA-070 | `(season, fantasy_team, position)` |
| `flex_usage_df` | `lineup_tendencies.py`, FFA-070 | `(season, fantasy_team, position)` |
| `start_sit_tendency_df` | `lineup_tendencies.py`, FFA-070 | `(season, roster_id)` |
| `positional_preference_df` | `lineup_tendencies.py`, FFA-070 | `(season, fantasy_team, position)` |
| `player_contribution_df` | `matchup_contribution.py`, FFA-069 (**needs `season_matchup_df`**) | `(season, week, roster_id, sleeper_player_id)` |
| `positional_advantage_df` | `matchup_contribution.py`, FFA-069 (**needs `season_matchup_df`**) | `(season, week, roster_id, position)` |

**`season_matchup_df` is optional, and the two FFA-069 frames raise without
it.** It is declared **last** (after the two threshold fields) so that every
existing positional call keeps working, and defaults to `None` so the twelve
frames that never read it stay constructible from a fact table alone. Reading
`player_contribution_df` or `positional_advantage_df` on an instance built
without it raises `ValueError` naming the missing input -- deliberately not
an empty frame, since an empty frame is exactly what those builders return
when no roster-week qualifies, and a forgotten argument would then look like
a real "no contributions" answer. An **empty** `season_matchup_df` is a valid
input and does not raise. `matchup_contribution.py`'s third function,
`reconcile_matchup_points`, has no accessor here on purpose: it is a
data-quality check on two independently-computed scores, not an analytics
frame -- call it directly (covered below).

**One league-season at a time**: like every module it
composes, an instance is expected to cover one league's players for one
season (never pooled) and, per "What this layer is for" above, one season
phase (pre-filter `player_week_df` -- and `season_matchup_df`, on the same
week boundary -- before constructing).

```python
# Continuing the example above. FFA-070's five tendency frames need nothing
# beyond the fact table already passed to the constructor.
print(analytics.roster_construction_df[[
    "season", "fantasy_team", "position", "distinct_players", "roster_share",
]])

# FFA-069's two frames need season_matchup_df, which this instance lacks.
try:
    analytics.player_contribution_df
except ValueError as error:
    print(error)
```

**Verified offline** with `.venv/bin/python`. Real output:

```text
   season fantasy_team position  distinct_players  roster_share
0    2025         Alec       QB                 1           0.5
1    2025         Alec       RB                 1           0.5
2    2025         Mike       QB                 1           0.5
3    2025         Mike       RB                 1           0.5
player_contribution_df requires season_matchup_df, which was not provided; pass season_matchup_df to PlayerAnalytics (or build_player_analytics) to use the FFA-069 matchup contribution frames
```

Hand-checked: each team carried exactly one QB and one RB for the same number
of weeks, so every `roster_share` is `0.5`.

[`PlayerAnalytics`](../src/fantasy_analyzer/players/player_analytics.py#L309)
/
[`build_player_analytics(player_week_df, roster_positions, num_teams, player_boom_bust_threshold=..., position_boom_bust_threshold=..., season_matchup_df=None, ranking_weights=..., rate_shrinkage_games=...) -> PlayerAnalytics`](../src/fantasy_analyzer/players/player_analytics.py#L653)
([module docstring](../src/fantasy_analyzer/players/player_analytics.py#L1)).

## Reference

### Player performance (FFA-065)

**Answers:** "how good and how consistent is this player, on his own merits
-- independent of whether his own fantasy manager started him."

Module:
[`players/performance.py`](../src/fantasy_analyzer/players/performance.py)
([module docstring](../src/fantasy_analyzer/players/performance.py#L1)). The
player-level analog of
[`analytics/consistency.py`](analytics.md) (team-season shape), reusing that
module's formulas wherever the question is identical.

**Metric definitions**, one row per `(season, sleeper_player_id)` with at
least one qualifying game:

| Column | Formula / definition |
|---|---|
| `games_played` | `n`, count of qualifying games (see below). |
| `total_points` | `sum(fantasy_points)` over qualifying games. |
| `points_per_game` | Arithmetic mean (AGENTS.md's own term for this quantity; the identical formula `consistency.py` calls `mean_points`). |
| `median_points` | Standard median (mean of the two middle values for even `n`). |
| `stdev_points` | **Population** standard deviation (`ddof=0`). `NaN` if `n < MIN_GAMES_FOR_DISPERSION` (2). |
| `cv` | `stdev_points / points_per_game`. `NaN` if `stdev_points` undefined or `points_per_game <= 0`. |
| `scoring_floor` / `scoring_ceiling` | `min`/`max` of qualifying-game scores. |
| `boom_games` / `bust_games` | Count of games `> mean + k*stdev` / `< mean - k*stdev`, `k = boom_bust_threshold` (default [`BOOM_BUST_THRESHOLD_STDEVS = 1.0`](../src/fantasy_analyzer/players/performance.py#L392)). |
| `boom_pct` / `bust_pct` | `boom_games / n` / `bust_games / n`. `NaN` if `n < MIN_GAMES_FOR_BOOM_BUST` (3). |

**What counts as a "game played" -- the central design decision, and the one
place this diverges from `consistency.py`:** a week counts as a game played
**only if the player has at least one non-null raw provider stat value**
that week -- being merely rostered is not enough. `player_week_df`'s row
universe is *rostered* players (bye weeks, inactives, and provider
no-data-weeks all still get a row with every stat `NaN` and
`fantasy_points = 0.0` by construction -- see
[`docs/players-data.md`](players-data.md)); treating every rostered
player-week as a "game" the way `consistency.py` treats every roster-week
as one would dilute `points_per_game` with artificial zero-point weeks that
describe a fantasy manager's roster decisions, not the player's football.
The rule is checked against the raw stat columns, never `fantasy_points`
itself (which is `0.0` both when a player produced nothing fantasy-relevant
*and* when he didn't play at all -- an ambiguity the raw stat columns don't
have). Concretely: this module identifies "raw stat columns" as every
`player_week_df` column that is neither one of `PLAYER_WEEK_COLUMNS` nor
`fantasy_points` -- if a `player_week_df` has **zero** such columns, no week
can ever qualify and the whole function returns an empty (but
correctly-shaped) frame, not an error.

**Started and benched games both count.** Unlike the "game played" question
above, this module does not filter on `started`/`bench` at all: it answers
"how good was this player, period" (the foundation
`position_strength.py`/`player_value.py`/`matchup_contribution.py` need),
not "how did this player perform in games his manager actually used him" (a
manager-relative question closer to `lineup_tendencies.py`).

**Grouping key: `(season, sleeper_player_id)` -- seasons are never
pooled.** A player's role/health/offense can change completely year to
year, so a multi-season input produces separate rows per season.
`player_name`/`position`/`nfl_team` are resolved independently per player
as the **most frequent non-null value across every row for that player that
season** (majority vote, ties broken toward whichever value appeared first)
-- a different rule from `player_week.py`'s own per-row "last non-null wins"
fallback, since this is resolving one label from *many rows that may
disagree* (e.g. a mid-season trade), not one row's missing field.

**A player who never has a qualifying game gets no row** -- following
`consistency.py`'s "zero games -> no row" precedent, not `player_week.py`'s
"still gets a row" precedent: this module is a distribution summary (a
distribution over zero observations is undefined), while `player_week.py`
is a roster/lineup-context log (a rostered-but-inactive player is itself the
fact worth recording).

**Regular season vs. playoffs**: phase-agnostic (see "What this layer is
for" above) -- `player_week_df` has no `is_playoff` column at all.

**[`build_player_performance_metrics(player_week_df, boom_bust_threshold=BOOM_BUST_THRESHOLD_STDEVS) -> pd.DataFrame`](../src/fantasy_analyzer/players/performance.py#L518)**
returns [`PLAYER_PERFORMANCE_COLUMNS`](../src/fantasy_analyzer/players/performance.py#L369),
sorted by ascending `season` then `sleeper_player_id` (no rank column --
"no single 'better' direction," identical to `consistency.py`'s reasoning).
Raises `ValueError` for a negative `boom_bust_threshold`.

```python
import pandas as pd
from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS
from fantasy_analyzer.players.performance import build_player_performance_metrics

# Josh Allen: 4 qualifying games with real spread. A second RB: 2 qualifying
# games (at the dispersion minimum, below the boom/bust minimum) plus one
# bye week the provider has no data for at all (not a qualifying game).
rows = [
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "nfl_team": "BUF", "started": True, "bench": False,
     "passing_yards": 300, "rushing_yards": None, "fantasy_points": 20.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "nfl_team": "BUF", "started": True, "bench": False,
     "passing_yards": 250, "rushing_yards": None, "fantasy_points": 16.0},
    {"season": 2025, "week": 3, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "nfl_team": "BUF", "started": True, "bench": False,
     "passing_yards": 100, "rushing_yards": None, "fantasy_points": 4.0},
    {"season": 2025, "week": 4, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "nfl_team": "BUF", "started": True, "bench": False,
     "passing_yards": 350, "rushing_yards": None, "fantasy_points": 32.0},
    {"season": 2025, "week": 5, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "nfl_team": "BUF", "started": False, "bench": True,
     "passing_yards": None, "rushing_yards": None, "fantasy_points": 0.0},
    {"season": 2025, "week": 1, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "1002",
     "player_name": "Test RB", "position": "RB", "nfl_team": "KC", "started": True, "bench": False,
     "passing_yards": None, "rushing_yards": 80, "fantasy_points": 8.0},
    {"season": 2025, "week": 2, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "1002",
     "player_name": "Test RB", "position": "RB", "nfl_team": "KC", "started": True, "bench": False,
     "passing_yards": None, "rushing_yards": 120, "fantasy_points": 12.0},
]
player_week_df = pd.DataFrame(rows, columns=PLAYER_WEEK_COLUMNS + ["passing_yards", "rushing_yards", "fantasy_points"])
result = build_player_performance_metrics(player_week_df)
print(result[["season", "sleeper_player_id", "player_name", "position", "games_played",
              "total_points", "points_per_game", "median_points", "stdev_points", "cv",
              "scoring_floor", "scoring_ceiling", "boom_games", "boom_pct", "bust_games", "bust_pct"]])
```

**Verified offline** -- real output:

```text
   season sleeper_player_id player_name position  games_played  total_points  points_per_game  median_points  stdev_points        cv  scoring_floor  \
0    2025              1000  Josh Allen       QB             4          72.0             18.0           18.0          10.0  0.555556            4.0   
1    2025              1002     Test RB       RB             2          20.0             10.0           10.0           2.0  0.200000            8.0   

   scoring_ceiling  boom_games  boom_pct  bust_games  bust_pct  
0             32.0         1.0      0.25         1.0      0.25  
1             12.0         NaN       NaN         NaN       NaN  
```

Hand-checked: Josh Allen's scores are 20, 16, 4, 32 -> mean `18.0`;
population variance `= (4+4+196+196)/4 = 100`, so `stdev = 10.0`, matching
the printed value exactly; boom threshold `18+10=28` (only `32` exceeds ->
`boom_games=1`), bust threshold `18-10=8` (only `4` is below ->
`bust_games=1`). The week-5 bye row (no raw stat data at all) correctly
does not appear as a 5th game. Test RB's 2 games leave `boom`/`bust`
undefined (`n < 3`), by design.

---

### Team-position strength (FFA-066)

**Answers:** "how much scoring did this fantasy team actually get from a
position group, and how does that rank against the rest of the league at
the same position."

Module:
[`players/position_strength.py`](../src/fantasy_analyzer/players/position_strength.py)
([module docstring](../src/fantasy_analyzer/players/position_strength.py#L1)).

**Grouping key: `(season, fantasy_team, position)`.** `fantasy_team` is
read directly from `player_week_df`'s own resolved column (no separate
`teams_df` parameter, matching `weekly_scores.py`/`consistency.py`'s
precedent). `position` is read from each row's **own** value that week, not
`performance.py`'s per-player-season majority vote -- a mid-season position
reclassification should attribute each week's points to whichever position
applied that week.

**Production/consistency use STARTED weeks only; depth uses ALL rostered
weeks -- the module's central design decision, and where it diverges from
`performance.py`'s "both count" choice.** `performance.py` describes a
player's own on-field production, independent of any manager's decisions;
this module describes a **team's realized position strength** -- what a
manager actually extracted, given the lineup decisions actually made. A
bench tight end who quietly puts up 15 points a week the manager never
started contributed nothing to the team's realized strength, however good a
player he was.

| Column | Formula / definition |
|---|---|
| `weeks_played` | Count of weeks with `>= 1` started player at the position (a "weekly position score" sums every started row sharing that week -- more than one player can be started at a position in the same week, e.g. two starting RBs). |
| `total_points`, `points_per_game`, `median_points`, `stdev_points`, `cv`, `scoring_floor`, `scoring_ceiling`, `boom_weeks`/`boom_pct`, `bust_weeks`/`bust_pct` | Identical formulas to `performance.py`'s player-grain columns, computed over the started-weeks-only weekly series. Default `k = 1.0` ([`BOOM_BUST_THRESHOLD_STDEVS`](../src/fantasy_analyzer/players/position_strength.py#L400)); `NaN` guards at `MIN_WEEKS_FOR_DISPERSION=2`/`MIN_WEEKS_FOR_BOOM_BUST=3`. |
| `positional_rank` | Standard competition rank on descending `total_points`, **within `(season, position)`** -- computed only among teams with a row for that position (rank 1 = the league's best producer at that position that season). |
| `share_of_team_points` | `total_points / team_total_points`, where the denominator sums `total_points` across **every** position row this function emits for that `(season, fantasy_team)` -- including K/DEF, not just the four skill positions, so shares are a genuine (~1.0-summing) partition. `NaN` when the team total is `<= 0`. Can exceed `[0, 1]` if a position (typically DEF) scores negative. |
| `positional_depth` | Count of **distinct** `sleeper_player_id`s rostered at the position that season with **at least one qualifying game** (`performance.py`'s exact rule) -- both started and benched qualifying weeks count. Only reported for a team-position that started at least once (a bench-only position gets no row at all, and therefore no depth value -- a documented limitation). |

**A `(season, fantasy_team, position)` with zero started weeks gets no row
at all** -- the identical "distribution over zero observations is
undefined" precedent every sibling module uses.

**[`build_position_strength_metrics(player_week_df, boom_bust_threshold=BOOM_BUST_THRESHOLD_STDEVS) -> pd.DataFrame`](../src/fantasy_analyzer/players/position_strength.py#L521)**
returns [`POSITION_STRENGTH_COLUMNS`](../src/fantasy_analyzer/players/position_strength.py#L376).

```python
import pandas as pd
from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS
from fantasy_analyzer.players.position_strength import build_position_strength_metrics

# Alec starts one RB every week (10, 20, 15) and benches a handcuff RB who
# never starts but has real stats (counts toward depth, not production).
# Mike starts a weaker RB for 2 weeks only (5, 5).
rows = [
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "2000",
     "position": "RB", "started": True, "bench": False, "rushing_yards": 50, "fantasy_points": 10.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "2000",
     "position": "RB", "started": True, "bench": False, "rushing_yards": 100, "fantasy_points": 20.0},
    {"season": 2025, "week": 3, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "2000",
     "position": "RB", "started": True, "bench": False, "rushing_yards": 75, "fantasy_points": 15.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "2001",
     "position": "RB", "started": False, "bench": True, "rushing_yards": 20, "fantasy_points": 4.0},
    {"season": 2025, "week": 1, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "2002",
     "position": "RB", "started": True, "bench": False, "rushing_yards": 25, "fantasy_points": 5.0},
    {"season": 2025, "week": 2, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "2002",
     "position": "RB", "started": True, "bench": False, "rushing_yards": 25, "fantasy_points": 5.0},
]
player_week_df = pd.DataFrame(rows, columns=PLAYER_WEEK_COLUMNS + ["rushing_yards", "fantasy_points"])
result = build_position_strength_metrics(player_week_df)
print(result[["season", "fantasy_team", "position", "weeks_played", "total_points", "points_per_game",
              "positional_rank", "share_of_team_points", "positional_depth"]])
```

**Verified offline** -- real output:

```text
   season fantasy_team position  weeks_played  total_points  points_per_game  positional_rank  share_of_team_points  positional_depth
0    2025         Alec       RB             3          45.0             15.0                1                   1.0                 2
1    2025         Mike       RB             2          10.0              5.0                2                   1.0                 1
```

Hand-checked: Alec's RB `total_points = 10+20+15 = 45`, ranked 1st over
Mike's `10`; `positional_depth = 2` (the started RB plus the benched
handcuff, who has a qualifying game); `share_of_team_points = 1.0` because
RB is the only position row emitted for Alec in this small example (the
denominator is the same 45).

---

### Lineup and roster efficiency (FFA-067)

**Answers:** "how much did the manager actually score this week vs. the
best legal lineup they could have set, and how often were their start/sit
decisions wrong."

Module:
[`players/lineup_efficiency.py`](../src/fantasy_analyzer/players/lineup_efficiency.py)
([module docstring](../src/fantasy_analyzer/players/lineup_efficiency.py#L1)).
This is the one module on this page that also needs the league's
`roster_positions` slot list, not `player_week_df` alone.

**Weekly metrics**, one row per `(season, week, roster_id)`:

| Column | Formula / definition |
|---|---|
| `actual_points` | Sum of `fantasy_points` over `started == True` rows. |
| `optimal_points` | Sum over the **exact, deterministic optimal lineup** under `roster_positions` (see below). |
| `bench_points` | Sum over benched rows -- **informational only**: includes points that could not legally have started (e.g. a 2nd QB in a 1-QB league). |
| `points_left_on_bench` | `optimal_points - actual_points`. Always `>= 0`. |
| `efficiency_pct` | `actual_points / optimal_points`. `NaN` when `optimal_points <= 0`. |
| `is_suboptimal` | `optimal_points > actual_points`. |
| `suboptimal_starts` | Count of actually-started players not in the optimal lineup ("wrong starts"). |
| `suboptimal_sits` | Count of benched players who are in the optimal lineup ("wrong sits"). |

**The optimal-lineup problem.** Assign at most one player per slot (each
player used at most once) to maximize total points, respecting
[`START_SLOT_ELIGIBILITY`](../src/fantasy_analyzer/players/lineup_efficiency.py#L306):
`QB`/`RB`/`WR`/`TE`/`K`/`DEF` (single position), `FLEX` (`RB`/`WR`/`TE`),
`SUPER_FLEX` (`QB`/`RB`/`WR`/`TE`), `REC_FLEX` (`WR`/`TE`),
`WRRB_FLEX` (`WR`/`RB`). Any other slot label (`BN`, `IR`, unrecognized) is a
bench slot. Solved **exactly**, not heuristically: since each player has
exactly one position, the problem separates into (1) a small dynamic
program over feasible per-position starter counts (at most a few hundred
states for a standard league) and (2) picking each position's top-`c_p`
scorers by prefix sum. **Ties are broken toward the manager's actual
lineup** at both levels (equal-scoring candidates prefer already-started
players; equal-value count vectors prefer the one closer to the actual
lineup) so a genuine tie is never counted as a mistake.

**Season roster-efficiency summary**, one row per `(season, roster_id)`:
`weeks_played`, `total_actual_points`/`total_optimal_points`/
`total_bench_points`/`total_points_left_on_bench` (season sums),
`efficiency_pct` (**aggregate**, `total_actual / total_optimal` -- not the
mean of weekly percentages), `suboptimal_weeks`/`suboptimal_week_pct`
(frequency of weeks with any suboptimal decision), `total_suboptimal_starts`/
`total_suboptimal_sits` (season sums of the weekly counts).

**Negative scorers** (typically a DEF that cost points): the optimizer may
correctly leave a slot **empty** rather than start a negative scorer, so
`efficiency_pct` can be `NaN` even with real activity, and a manager who
did start the negative scorer is flagged suboptimal with it counted as a
wrong start.

**[`build_lineup_efficiency_metrics(player_week_df, roster_positions) -> pd.DataFrame`](../src/fantasy_analyzer/players/lineup_efficiency.py#L466)**
returns [`LINEUP_EFFICIENCY_COLUMNS`](../src/fantasy_analyzer/players/lineup_efficiency.py#L268).
**[`build_roster_efficiency_metrics(player_week_df, roster_positions) -> pd.DataFrame`](../src/fantasy_analyzer/players/lineup_efficiency.py#L583)**
(built from the weekly function, not a separate computation) returns
[`ROSTER_EFFICIENCY_COLUMNS`](../src/fantasy_analyzer/players/lineup_efficiency.py#L287).

```python
import pandas as pd
from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS
from fantasy_analyzer.players.lineup_efficiency import (
    build_lineup_efficiency_metrics, build_roster_efficiency_metrics,
)

roster_positions = ["QB", "RB", "FLEX", "BN"]

# Week 1: manager starts QB(20)+RB(10), benches a WR who scored 25 -- the WR
# is FLEX-eligible and the empty FLEX slot should have started him.
# Week 2: same shape, smaller gap (bench WR scores only 5).
rows = [
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "3000",
     "position": "QB", "started": True, "bench": False, "fantasy_points": 20.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "3001",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 10.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "3002",
     "position": "WR", "started": False, "bench": True, "fantasy_points": 25.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "3000",
     "position": "QB", "started": True, "bench": False, "fantasy_points": 18.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "3001",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 22.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "3002",
     "position": "WR", "started": False, "bench": True, "fantasy_points": 5.0},
]
player_week_df = pd.DataFrame(rows, columns=PLAYER_WEEK_COLUMNS + ["fantasy_points"])

weekly = build_lineup_efficiency_metrics(player_week_df, roster_positions)
print(weekly[["season", "week", "roster_id", "actual_points", "optimal_points", "bench_points",
              "points_left_on_bench", "efficiency_pct", "is_suboptimal",
              "suboptimal_starts", "suboptimal_sits"]])

season_summary = build_roster_efficiency_metrics(player_week_df, roster_positions)
print(season_summary[["season", "roster_id", "weeks_played", "total_actual_points",
                       "total_optimal_points", "efficiency_pct", "suboptimal_weeks",
                       "suboptimal_week_pct", "total_suboptimal_starts", "total_suboptimal_sits"]])
```

**Verified offline** -- real output:

```text
   season  week  roster_id  actual_points  optimal_points  bench_points  points_left_on_bench  efficiency_pct  is_suboptimal  suboptimal_starts  \
0    2025     1          1           30.0            55.0          25.0                  25.0        0.545455           True                  0   
1    2025     2          1           40.0            45.0           5.0                   5.0        0.888889           True                  0   

   suboptimal_sits  
0                1  
1                1  

   season  roster_id  weeks_played  total_actual_points  total_optimal_points  efficiency_pct  suboptimal_weeks  suboptimal_week_pct  total_suboptimal_starts  \
0    2025          1             2                 70.0                 100.0             0.7                 2                  1.0                        0   

   total_suboptimal_sits  
0                      2
```

Hand-checked, week 1: `roster_positions` has one `RB` slot and one `FLEX`
slot (accepting `RB`/`WR`/`TE`) -- the optimal lineup is `QB(20) + RB(10) +
FLEX->WR(25) = 55`; the manager's actual `30` leaves `25` on the bench
(`efficiency_pct = 30/55 = 0.5455`), with zero wrong starts and one wrong
sit (the bench WR who should have filled FLEX). Season aggregate:
`efficiency_pct = 70/100 = 0.7` (aggregate, not the mean of `0.5455` and
`0.8889`).

---

### Replacement-level player value and positional scarcity (FFA-068)

**Answers:** "how much is this player actually worth, relative to his
position and relative to a free replacement-level pickup" -- the first
module on this page that is explicitly **league-relative**.

Module:
[`players/player_value.py`](../src/fantasy_analyzer/players/player_value.py)
([module docstring](../src/fantasy_analyzer/players/player_value.py#L1)).
Consumes `performance.py`'s output directly (`games_played`/
`points_per_game`/`total_points` are read, never recomputed) plus a
league's `roster_positions` and `num_teams`.

**Replacement-level methodology**, per `(season, position)`:

1. **Count starting slots**: each slot in `roster_positions` maps to the
   positions it accepts (`START_SLOT_ELIGIBILITY`, the same table
   `lineup_efficiency.py` uses, extended for this module with Sleeper's
   real IDP labels -- `DL`/`LB`/`DB`/`IDP_FLEX`/`DT`/`DE`/`CB`/`S`). A `FLEX`
   slot counts as one starter at **every** eligible position (RB, WR, *and*
   TE) -- a deliberate choice: it's a pure statement about the league's
   rules, not an assumption about how managers actually use the slot, and
   it keeps the baseline monotone.
2. **Starter cutoff** = `num_teams * slots(position)`.
3. **Replacement player** = the position's players ranked by descending
   `points_per_game` (ties broken by ascending `sleeper_player_id`), at
   rank `min(cutoff, field_size)` -- **clamped to the worst rostered
   player** when the league doesn't roster `cutoff` players at the
   position. This is a documented heuristic, not a bound: `player_week_df`'s
   row universe is rostered players only (see
   [`docs/players-data.md`](players-data.md)), so a genuinely better
   unrostered/waiver player is invisible to this module -- see the
   "Rostered-only caveat" in the module docstring.
4. **`replacement_ppg`** = that player's `points_per_game`, denormalized
   onto every player at the position that season.

**Player-value columns**, one row per `(season, sleeper_player_id)`:

| Column | Formula |
|---|---|
| `position_players` | Field size at the position. |
| `position_mean_ppg` / `position_mean_total` | Position averages of `points_per_game` / `total_points`. |
| `ppg_above_position_average` | `points_per_game - position_mean_ppg`. |
| `total_above_position_average` | `total_points - position_mean_total`. |
| `replacement_ppg` | As above. |
| `ppg_above_replacement` | `points_per_game - replacement_ppg` (rate VORP). |
| `points_above_replacement` | `total_points - replacement_ppg * games_played` (season VORP -- the ticket's headline "points above replacement"). |
| `value_rank` | Standard competition rank on descending `points_above_replacement`, **across every position in the season** (rank 1 = the most valuable player in the league that season, whatever his position). Ties compared after rounding to 6 decimal places (not exact float equality, unlike most other rank columns in this codebase -- deliberately coarser, to avoid splitting a mathematically-equal VORP on floating-point noise). |

**Position-scarcity columns** (`build_position_scarcity_metrics`), one row
per `(season, position)`: `players` (field size), `position_starters`
(`num_teams * slots(position)`, unclamped), `replacement_rank` (the actual
clamped rank used), `best_ppg`, `replacement_ppg`,
`ppg_gap_to_replacement` (`best_ppg - replacement_ppg`), and
`scarcity_ratio` = `ppg_gap_to_replacement / replacement_ppg` -- the gap
expressed relative to the baseline, so a QB position (high scoring level)
and a TE position (low scoring level) with the *same absolute* gap are
correctly read as differently scarce. `NaN` when `replacement_ppg <= 0`.

**Both frames are total** (never raise for a degenerate league
configuration): `cutoff < 1` (`num_teams <= 0`/`None`, or no starting slots
at the position) falls back to the same worst-rostered-player baseline.
Both **do** raise `ValueError` for a `performance_df` missing a required
column, or containing duplicate `(season, sleeper_player_id)` rows -- silent
corruption of the position means/replacement level is judged worse than a
loud failure.

**[`build_player_value_metrics(performance_df, roster_positions, num_teams) -> pd.DataFrame`](../src/fantasy_analyzer/players/player_value.py#L706)**
returns [`PLAYER_VALUE_COLUMNS`](../src/fantasy_analyzer/players/player_value.py#L340).
**[`build_position_scarcity_metrics(performance_df, roster_positions, num_teams) -> pd.DataFrame`](../src/fantasy_analyzer/players/player_value.py#L817)**
returns [`POSITION_SCARCITY_COLUMNS`](../src/fantasy_analyzer/players/player_value.py#L362).

```python
import pandas as pd
from fantasy_analyzer.players.performance import PLAYER_PERFORMANCE_COLUMNS
from fantasy_analyzer.players.player_value import (
    build_player_value_metrics, build_position_scarcity_metrics,
)

# 4 RBs in a 2-team, 1-RB-starter league (no FLEX) -- starter cutoff = 2.
rows = [
    {"season": 2025, "sleeper_player_id": "1", "player_name": "RB Elite", "position": "RB",
     "nfl_team": "BUF", "games_played": 4, "total_points": 80.0, "points_per_game": 20.0},
    {"season": 2025, "sleeper_player_id": "2", "player_name": "RB Good", "position": "RB",
     "nfl_team": "KC", "games_played": 4, "total_points": 60.0, "points_per_game": 15.0},
    {"season": 2025, "sleeper_player_id": "3", "player_name": "RB Bench1", "position": "RB",
     "nfl_team": "SEA", "games_played": 4, "total_points": 32.0, "points_per_game": 8.0},
    {"season": 2025, "sleeper_player_id": "4", "player_name": "RB Bench2", "position": "RB",
     "nfl_team": "DAL", "games_played": 4, "total_points": 16.0, "points_per_game": 4.0},
]
performance_df = pd.DataFrame(rows, columns=PLAYER_PERFORMANCE_COLUMNS)
roster_positions = ["QB", "RB", "BN", "BN"]  # 1 RB starter slot, no FLEX
num_teams = 2

value = build_player_value_metrics(performance_df, roster_positions, num_teams)
print(value[["sleeper_player_id", "player_name", "points_per_game", "position_mean_ppg",
             "ppg_above_position_average", "replacement_ppg", "ppg_above_replacement",
             "points_above_replacement", "value_rank"]])

scarcity = build_position_scarcity_metrics(performance_df, roster_positions, num_teams)
print(scarcity[["season", "position", "players", "position_starters", "replacement_rank",
                "best_ppg", "replacement_ppg", "ppg_gap_to_replacement", "scarcity_ratio"]])
```

**Verified offline** -- real output:

```text
  sleeper_player_id player_name  points_per_game  position_mean_ppg  ppg_above_position_average  replacement_ppg  ppg_above_replacement  \
0                 1    RB Elite             20.0              11.75                        8.25             15.0                    5.0   
1                 2     RB Good             15.0              11.75                        3.25             15.0                    0.0   
2                 3   RB Bench1              8.0              11.75                       -3.75             15.0                   -7.0   
3                 4   RB Bench2              4.0              11.75                       -7.75             15.0                  -11.0   

   points_above_replacement  value_rank  
0                      20.0           1  
1                       0.0           2  
2                     -28.0           3  
3                     -44.0           4  

   season position  players  position_starters  replacement_rank  best_ppg  replacement_ppg  ppg_gap_to_replacement  scarcity_ratio
0    2025       RB        4                  2                 2      20.0             15.0                     5.0        0.333333
```

Hand-checked: mean `ppg = (20+15+8+4)/4 = 11.75`; cutoff `= 2*1 = 2`, so the
2nd-best RB (`RB Good`, `15.0`) is replacement; `RB Elite`'s
`points_above_replacement = 80 - 15.0*4 = 20.0`; `scarcity_ratio =
(20-15)/15 = 0.3333`.

---

### Matchup player contribution (FFA-069)

**Answers:** "which players actually drove this specific matchup's win or
loss, and how did each position compare to the opponent's."

Module:
[`players/matchup_contribution.py`](../src/fantasy_analyzer/players/matchup_contribution.py)
([module docstring](../src/fantasy_analyzer/players/matchup_contribution.py#L1)).
The one module on this page that joins **two** canonical frames --
`season_matchup_df` ([`docs/matchups.md`](matchups.md)) and `player_week_df`
([`docs/players-data.md`](players-data.md)) -- on `(season, week,
roster_id)`.

**Row universe: started players in paired (non-bye) matchups only.** Bye
rows are excluded entirely (no opponent to compare against, mirroring
`analytics/head_to_head.py`); only `started == True` rows are read (a
benched player's points never entered the recorded score and could not have
driven the outcome -- `lineup_efficiency.py`'s `bench_points` is
"informational only" for the identical reason). An **incomplete** matchup
(a real opponent, but a missing score) is *not* excluded like a bye: it
still gets rows, with `result = None` and `margin`/`share_of_team_points`
`NaN` wherever the missing score would be needed.

**`team_points`/`opponent_points`/`margin`/`result` come from
`season_matchup_df`, never recomputed from `player_week_df`.** These are
two independently-derived scores (Sleeper's own recorded total vs. this
codebase's scoring engine re-applied to provider stats) and are *expected*,
not guaranteed, to agree -- see `reconcile_matchup_points` below for the
documented check. `margin` here is **signed from the reporting roster's own
perspective** (`team_points - opponent_points`), deliberately different from
`season_matchup_df.margin`'s unsigned magnitude.

**Player contribution** (`build_matchup_player_contributions`), one row per
started player per roster-week:

| Column | Formula |
|---|---|
| `fantasy_points` | The player's own score -- and, by linearity of `margin = sum(own) - sum(opponent)`, **exactly** his contribution to his roster's margin. No separate "contribution" column duplicates this. |
| `share_of_team_points` | `fantasy_points / team_points`. `NaN` if `team_points` is `NaN` or `<= 0`. Not guaranteed to sum to `1.0` across a roster-week's players when the two source frames disagree (see reconciliation). |
| `contribution_rank` | Standard competition rank, descending `fantasy_points` (`NaN` treated as `0.0`), **within `(season, week, roster_id)`** -- rank 1 is that roster's best starter that week. Filter to `contribution_rank == 1` and read `result` to answer "who drove this win/loss." |

**Positional matchup advantage** (`build_positional_matchup_advantage`), one
row per `(season, week, roster_id, position)`: `own_points`/
`opponent_points` (summed started `fantasy_points` at that position for
each side that week, `0.0` if a side started nobody there),
`own_starters`/`opponent_starters` (headcounts), and
`positional_advantage = own_points - opponent_points`. **Row set is the
union of positions started by either side** (a team that started nobody at
TE still gets a TE row if its opponent did) -- a deliberate divergence from
`position_strength.py`'s "no row for a never-started position," because
this is a head-to-head comparison where "my opponent played a position I
didn't" is exactly the signal worth surfacing. Summing
`positional_advantage` across a roster-week's position rows reproduces that
week's signed `margin` exactly (both partition the identical
`sum(own started) - sum(opponent started)`).

**Reconciliation** (`reconcile_matchup_points`): compares
`season_matchup_df`'s recorded score against the sum of
`player_week_df`'s started `fantasy_points` for the same roster-week, per
`(season, week, roster_id)`, flagging any mismatch beyond
[`MATCHUP_POINTS_TOLERANCE = 1e-6`](../src/fantasy_analyzer/players/matchup_contribution.py#L407).
Unlike `matchups/reconciliation.py`'s comparison (two views of the *same*
Sleeper counters, expected to match up to floating-point noise), this
compares two **independently-computed** scores and a real mismatch is a
genuine, expected possibility -- an unsupported scoring key, a provider
with no stats for a started player that week, or a roster-week
`player_week_df` was never built for at all (`started_points = NaN` in that
last case, not `0.0`).

The first two functions are also available as
[`PlayerAnalytics.player_contribution_df`](../src/fantasy_analyzer/players/player_analytics.py#L544)
and
[`PlayerAnalytics.positional_advantage_df`](../src/fantasy_analyzer/players/player_analytics.py#L566),
on an instance constructed with a `season_matchup_df`; `reconcile_matchup_points`
is call-it-directly only (see the quick start above).

**[`build_matchup_player_contributions(season_matchup_df, player_week_df) -> pd.DataFrame`](../src/fantasy_analyzer/players/matchup_contribution.py#L570)**
returns [`PLAYER_CONTRIBUTION_COLUMNS`](../src/fantasy_analyzer/players/matchup_contribution.py#L346).
**[`build_positional_matchup_advantage(season_matchup_df, player_week_df) -> pd.DataFrame`](../src/fantasy_analyzer/players/matchup_contribution.py#L694)**
returns [`POSITIONAL_ADVANTAGE_COLUMNS`](../src/fantasy_analyzer/players/matchup_contribution.py#L369).
**[`reconcile_matchup_points(season_matchup_df, player_week_df, *, points_tolerance=MATCHUP_POINTS_TOLERANCE) -> pd.DataFrame`](../src/fantasy_analyzer/players/matchup_contribution.py#L809)**
returns [`RECONCILE_COLUMNS`](../src/fantasy_analyzer/players/matchup_contribution.py#L388).
**Phase-agnostic** like every other module here, except `is_playoff` **is**
carried through onto every output row (copied from `season_matchup_df`,
since that frame already has the column) -- filter `season_matchup_df` (and
`player_week_df` on the same week boundary) before calling for a
phase-specific view.

```python
import pandas as pd
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS
from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS
from fantasy_analyzer.players.matchup_contribution import (
    build_matchup_player_contributions, build_positional_matchup_advantage,
    reconcile_matchup_points,
)

# Week 1: roster 1 (Alec, 30 pts) beat roster 2 (Mike, 22 pts).
season_matchup_df = pd.DataFrame([{
    "season": "2025", "week": 1, "is_playoff": False, "matchup_id": 1,
    "roster_1_id": 1, "roster_2_id": 2, "owner_1": "Alec", "owner_2": "Mike",
    "points_1": 30.0, "points_2": 22.0,
    "winner": 1, "loser": 2, "is_tie": False, "margin": 8.0, "point_differential": 8.0,
}], columns=SEASON_MATCHUP_COLUMNS)

rows = [
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1000",
     "player_name": "Josh Allen", "position": "QB", "started": True, "fantasy_points": 20.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alec", "sleeper_player_id": "1001",
     "player_name": "RB One", "position": "RB", "started": True, "fantasy_points": 10.0},
    {"season": 2025, "week": 1, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "1002",
     "player_name": "QB Two", "position": "QB", "started": True, "fantasy_points": 12.0},
    {"season": 2025, "week": 1, "roster_id": 2, "fantasy_team": "Mike", "sleeper_player_id": "1003",
     "player_name": "RB Two", "position": "RB", "started": True, "fantasy_points": 10.0},
]
player_week_df = pd.DataFrame(rows, columns=PLAYER_WEEK_COLUMNS + ["fantasy_points"])

contributions = build_matchup_player_contributions(season_matchup_df, player_week_df)
print(contributions[["roster_id", "fantasy_team", "opponent_fantasy_team", "sleeper_player_id",
                      "player_name", "position", "fantasy_points", "team_points", "opponent_points",
                      "share_of_team_points", "margin", "result", "contribution_rank"]])

advantage = build_positional_matchup_advantage(season_matchup_df, player_week_df)
print(advantage[["roster_id", "fantasy_team", "position", "own_points", "own_starters",
                  "opponent_points", "opponent_starters", "positional_advantage"]])

recon = reconcile_matchup_points(season_matchup_df, player_week_df)
print(recon)
```

**Verified offline** -- real output:

```text
   roster_id fantasy_team opponent_fantasy_team sleeper_player_id player_name position  fantasy_points  team_points  opponent_points  share_of_team_points  \
0          1         Alec                  Mike              1000  Josh Allen       QB            20.0         30.0             22.0              0.666667   
1          1         Alec                  Mike              1001      RB One       RB            10.0         30.0             22.0              0.333333   
2          2         Mike                  Alec              1002      QB Two       QB            12.0         22.0             30.0              0.545455   
3          2         Mike                  Alec              1003      RB Two       RB            10.0         22.0             30.0              0.454545   

   margin result  contribution_rank  
0     8.0    win                  1  
1     8.0    win                  2  
2    -8.0   loss                  1  
3    -8.0   loss                  2  

   roster_id fantasy_team position  own_points  own_starters  opponent_points  opponent_starters  positional_advantage
0          1         Alec       QB        20.0             1               12.0                  1                    8.0
1          1         Alec       RB        10.0             1               10.0                  1                    0.0
2          2         Mike       QB        12.0             1               20.0                  1                   -8.0
3          2         Mike       RB        10.0             1               10.0                  1                    0.0

   season  week  roster_id fantasy_team  matchup_points  started_points  points_diff  points_match
0    2025     1          1         Alec            30.0            30.0          0.0          True
1    2025     1          2         Mike            22.0            22.0          0.0          True
```

Hand-checked: Josh Allen's `20.0` is exactly `20/30` of Alec's `30`-point
week; the `QB` positional advantage (`20 - 12 = 8.0`) plus the `RB`
advantage (`10 - 10 = 0.0`) sums to the matchup's `8.0` margin exactly, and
both rosters' recorded scores reconcile exactly against their started
players' point sums.

---

### Manager lineup tendencies (FFA-070)

**Answers:** "what does this manager's roster-construction and start/sit
*habits* look like across a season" -- not how much a team scored
(`position_strength.py`) or how efficient a lineup was
(`lineup_efficiency.py`), but which positions were stockpiled, which were
benched, which soaked up FLEX slots, and how the manager's actual lineup
compares in aggregate to the efficiency-optimal one.

Module:
[`players/lineup_tendencies.py`](../src/fantasy_analyzer/players/lineup_tendencies.py)
([module docstring](../src/fantasy_analyzer/players/lineup_tendencies.py#L1)).
Five functions, all grouped by `(season, fantasy_team, position)` except
the fourth (which wraps `lineup_efficiency.py`'s own `(season, roster_id)`
grain). All five are also available as
[`PlayerAnalytics`](../src/fantasy_analyzer/players/player_analytics.py#L309)
attributes -- `roster_construction_df`, `bench_allocation_df`,
`flex_usage_df`, `start_sit_tendency_df`, `positional_preference_df` -- which
need no constructor argument beyond the ones that service already takes:

1. **[`build_roster_construction_metrics(player_week_df) -> pd.DataFrame`](../src/fantasy_analyzer/players/lineup_tendencies.py#L550)**
   -- [`ROSTER_CONSTRUCTION_COLUMNS`](../src/fantasy_analyzer/players/lineup_tendencies.py#L412):
   `distinct_players` (rostered, started or benched, no qualifying-game
   filter -- a stash who never played still represents a real
   roster-construction decision), `rostered_player_weeks` (volume
   counterpart), `roster_share` (share of the team-season's total rostered
   player-weeks across every position).
2. **[`build_bench_allocation_metrics(player_week_df) -> pd.DataFrame`](../src/fantasy_analyzer/players/lineup_tendencies.py#L617)**
   -- [`BENCH_ALLOCATION_COLUMNS`](../src/fantasy_analyzer/players/lineup_tendencies.py#L422):
   `bench_weeks`, `bench_share`. A position never benched gets no row (the
   same "zero observations, no row" precedent).
3. **[`build_flex_usage_metrics(player_week_df, roster_positions) -> pd.DataFrame`](../src/fantasy_analyzer/players/lineup_tendencies.py#L702)**
   -- [`FLEX_USAGE_COLUMNS`](../src/fantasy_analyzer/players/lineup_tendencies.py#L431):
   which position most often filled a FLEX-*type* slot in the manager's
   **actual** lineup (not the optimal one). Computed in closed form, per
   roster-week: `flex_starts(position) = max(0, started_count(position) -
   fixed_slot_count(position))`, summed across the season -- since every
   non-FLEX slot is dedicated to exactly one position, any player started
   beyond a position's fixed slot count must have used FLEX capacity.
   `flex_start_share` and `flex_usage_rank` (standard competition rank,
   descending, within one team-season) follow. Returns empty if
   `roster_positions` has no FLEX-type slot at all.
4. **[`build_start_sit_tendency_metrics(player_week_df, roster_positions) -> pd.DataFrame`](../src/fantasy_analyzer/players/lineup_tendencies.py#L829)**
   -- [`START_SIT_TENDENCY_COLUMNS`](../src/fantasy_analyzer/players/lineup_tendencies.py#L442):
   defines **no new arithmetic** -- `build_roster_efficiency_metrics`'s
   season table unchanged, plus two derived rates,
   `suboptimal_starts_per_week = total_suboptimal_starts / weeks_played` and
   `suboptimal_sits_per_week = total_suboptimal_sits / weeks_played`. Grouped
   by `(season, roster_id)`, not `fantasy_team` -- inherited unchanged from
   the wrapped function.
5. **[`build_positional_preference_metrics(player_week_df) -> pd.DataFrame`](../src/fantasy_analyzer/players/lineup_tendencies.py#L868)**
   -- [`POSITIONAL_PREFERENCE_COLUMNS`](../src/fantasy_analyzer/players/lineup_tendencies.py#L461):
   a **rollup**, not an independent metric -- combines
   `build_roster_construction_metrics` and `build_bench_allocation_metrics`'s
   signals with one more (`started_weeks`/`start_share`) into one row per
   position the team ever rostered, started, or benched that season, so all
   three angles are visible together without an outer-join.

**Waiver-player utilization is deliberately out of scope.** AGENTS.md lists
it as a sixth tendency, but it requires a rostered player's **acquisition
method** (draft/waiver/trade), which exists nowhere in any normalized
dataset in this codebase today -- `SleeperClient.get_transactions` exists
but nothing normalizes its output, and building that dataset (reconciling
`adds`/`drops` across transaction types, plus draft results, plus a caching
strategy) is a Data/Software-Engineer-sized ticket in its own right, not a
Data Scientist composition on top of already-normalized data. This module
implements the other five tendencies in full and leaves this one
undone -- see the module docstring's "Waiver-player utilization: scoped
out" section for the full reasoning.

```python
import pandas as pd
from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS
from fantasy_analyzer.players.lineup_tendencies import (
    build_roster_construction_metrics, build_bench_allocation_metrics,
    build_flex_usage_metrics, build_start_sit_tendency_metrics,
    build_positional_preference_metrics,
)

# This module docstring's own hand-checked toy example: Team Alpha rosters
# RB1 (started weeks 1-2), RB2 (started week 1 only), and WR1 (started
# weeks 1-2) -- roster_share: RB 0.6, WR 0.4.
rows = [
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RB1",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 10.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RB1",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 12.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RB2",
     "position": "RB", "started": False, "bench": True, "fantasy_points": 6.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "WR1",
     "position": "WR", "started": True, "bench": False, "fantasy_points": 15.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "WR1",
     "position": "WR", "started": True, "bench": False, "fantasy_points": 9.0},
]
player_week_df = pd.DataFrame(rows, columns=PLAYER_WEEK_COLUMNS + ["fantasy_points"])

print(build_roster_construction_metrics(player_week_df))
print(build_bench_allocation_metrics(player_week_df))
print(build_positional_preference_metrics(player_week_df))

# A two-RB, one-FLEX league. Week 1: 3 RBs started (excess = 3-2 = 1).
# Week 2: 2 RBs + 1 WR started (RB excess = 0, WR excess = 1-0 = 1).
roster_positions = ["RB", "RB", "FLEX", "BN"]
flex_rows = [
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RBa",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 10.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RBb",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 8.0},
    {"season": 2025, "week": 1, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RBc",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 6.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RBa",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 11.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "RBb",
     "position": "RB", "started": True, "bench": False, "fantasy_points": 7.0},
    {"season": 2025, "week": 2, "roster_id": 1, "fantasy_team": "Alpha", "sleeper_player_id": "WRa",
     "position": "WR", "started": True, "bench": False, "fantasy_points": 9.0},
]
flex_player_week_df = pd.DataFrame(flex_rows, columns=PLAYER_WEEK_COLUMNS + ["fantasy_points"])
print(build_flex_usage_metrics(flex_player_week_df, roster_positions))
print(build_start_sit_tendency_metrics(flex_player_week_df, roster_positions)[[
    "season", "roster_id", "weeks_played", "total_actual_points", "total_optimal_points",
    "efficiency_pct", "suboptimal_weeks", "suboptimal_starts_per_week", "suboptimal_sits_per_week",
]])
```

**Verified offline** -- real output:

```text
   season fantasy_team position  distinct_players  rostered_player_weeks  roster_share
0    2025        Alpha       RB                 2                      3           0.6
1    2025        Alpha       WR                 1                      2           0.4
   season fantasy_team position  bench_weeks  bench_share
0    2025        Alpha       RB            1          1.0
   season fantasy_team position  distinct_players  rostered_player_weeks  roster_share  started_weeks  start_share  bench_weeks  bench_share
0    2025        Alpha       RB                 2                      3           0.6              2          0.5            1          1.0
1    2025        Alpha       WR                 1                      2           0.4              2          0.5            0          0.0
   season fantasy_team position  flex_starts  flex_start_share  flex_usage_rank
0    2025        Alpha       RB            1               0.5                1
1    2025        Alpha       WR            1               0.5                1
   season  roster_id  weeks_played  total_actual_points  total_optimal_points  efficiency_pct  suboptimal_weeks  suboptimal_starts_per_week  suboptimal_sits_per_week
0    2025          1             2                 51.0                  51.0             1.0                 0                         0.0                       0.0
```

These numbers reproduce the module docstring's own hand-checked toy
examples exactly: `roster_share` of `0.6`/`0.4` for RB/WR (`3` and `2`
player-weeks out of `5` total), and `flex_starts`/`flex_start_share` tied
at `1`/`0.5` for RB and WR, both at `flex_usage_rank = 1`.

---

### League-wide composite player ranking (FFA-073)

**Answers:** "if I had to rank every player in the league on one list --
across positions, on more than raw points -- what would that list be?"

Module:
[`player_rankings.py`](../src/fantasy_analyzer/players/player_rankings.py)
([module docstring](../src/fantasy_analyzer/players/player_rankings.py#L1)).
Consumes `performance.py`'s output plus a league's `roster_positions` and
`num_teams`, and calls `player_value.py`'s two builders internally -- it
**recomputes no replacement level, VORP, field size, `cv` or
`scoring_ceiling`**.

**Why this exists next to FFA-068's `value_rank`.** That column is already
a league-wide, cross-position ranking, but on a single signal: season
`points_above_replacement`. That makes it purely volume-driven -- a
seventeen-game compiler outranks a nine-game elite producer, a metronome
and a boom/bust player with equal totals tie, and a two-game sample is
unregularized. This module keeps that VORP spine and blends four more
signals onto it.

**The composite.** Five components, each z-scored **within a season across
all positions** using the population standard deviation (`ddof = 0`,
matching `consistency.py` and `performance.py`):

| Component | Definition | Weight field | Default |
|---|---|---|---|
| `z_value` | `z(points_above_replacement)` | `value` | 0.30 |
| `z_rate` | `z(shrunk_ppg_above_replacement)` | `rate` | 0.20 |
| `z_reliability` | `z(-cv)` -- lower volatility ranks higher | `reliability` | 0.20 |
| `z_upside` | `z(scoring_ceiling - replacement_ppg)` | `upside` | 0.15 |
| `z_scarcity` | `z(scarcity_ratio)`, broadcast from the position's row | `scarcity` | 0.15 |

`ranking_score = sum(w_c * z_c) / sum(w_c)` over the components available
for that player. **Cross-position pooling is legal** because four of the
five are already replacement-relative (they subtract the position's own
baseline before pooling) and the fifth, `cv`, is normalized by the player's
own scoring level. The module never pools raw `points_per_game` across
positions.

**Small-sample shrinkage.** `shrunk_ppg_above_replacement = n *
ppg_above_replacement / (n + k)`, with `n = games_played` and `k =
rate_shrinkage_games` (default
[`DEFAULT_RATE_SHRINKAGE_GAMES`](../src/fantasy_analyzer/players/player_rankings.py#L510)
`= 4.0`). This shrinks toward **zero, i.e. toward replacement level** --
the right prior for a player barely observed -- so a two-game, `+10.0`
ppg-above-replacement flash lands at `2*10/(2+4) = 3.33`, not `10.0`.
`k = 0` degenerates to the raw rate exactly. This replaces an arbitrary
`min_games` cutoff: no player is excluded, but a tiny sample cannot
dominate.

**Missing components are dropped, never zero-filled.** `cv` is `NaN` below
two games, `scarcity_ratio` is `NaN` when `replacement_ppg <= 0`, and a
component whose pool has zero variance (or fewer than two usable values) is
`NaN` for *every* player that season rather than `inf`. In each case the
component is dropped for that player and **the surviving weights are
renormalized to sum to 1.0**; `components_used` reports how many of the
five actually entered the score. Zero-filling was rejected deliberately:
`0.0` on a z-scale means "exactly league average", which would silently
assert a measurement nobody made. A player with no usable component gets
`NaN` for `ranking_score` and all three rank columns, and sorts last.

**Ranks.** `league_rank` is a standard competition ("1224") rank on
descending `ranking_score` within the season -- the same convention as
`standings.py`'s `scoring_rank` and `player_value.py`'s `value_rank`, with
ties compared after rounding to 6 decimal places and display order broken
by ascending `sleeper_player_id`. `position_rank` applies the same rule
within `(season, position)`. `league_percentile` is
`1 - (league_rank - 1) / n_ranked`, where `n_ranked` counts only scored
players. All three are `float64`, not `int64` (unlike `value_rank`), because
an unscoreable player's rank is `NaN`.

**Scarcity is deliberately double-counted -- read this before using the
default.** Subtracting `replacement_ppg` already prices positional
thinness once; that is the entire reason a TE at 12 ppg against a 4 ppg TE
baseline can outrank a QB at 22 against 20. `z_scarcity` then prices the
same thinness a **second** time. Because `scarcity_ratio` is a property of
the *position*, this lifts every player at a thin position -- including its
replacement-level ones -- not just the elite ones (visible in the example
below, where a zero-VORP `TE Deep` outranks `QB Volatile`, who banked 8
points above replacement). That is a deliberate opinion about
**draft-capital value**, not a pure measure of realized points.
`RankingWeights(scarcity=0.0)` recovers the undistorted
replacement-relative reading.

**`value` and `rate` are not independent**, and their combined weight is
capped at 0.50 for that reason:
`points_above_replacement == games_played * ppg_above_replacement` for
every frame `performance.py` produces, so the two z-scores are two views of
one quantity and are **exactly equal** whenever `games_played` is constant
across the pool. Shrinkage is the only thing that separates them.

**Two modes.** `mode="retrospective"` (the default) is everything above.
`mode="projected"` is a signature seam only -- it raises
`NotImplementedError` pending a real
[FFA-072](players-data.md) projection provider; the docstring specifies
what it will do (aggregate `ProjectionProvider.projections(season, week)`
into projected season totals, then run the identical pipeline). Any other
`mode` raises `ValueError`, as does a negative `rate_shrinkage_games`, a
negative or `NaN` weight, an all-zero weight vector, a `performance_df`
missing a required column, or duplicate `(season, sleeper_player_id)` rows.

**[`build_league_player_rankings(performance_df, roster_positions, num_teams, *, mode="retrospective", weights=..., rate_shrinkage_games=..., projections_df=None) -> pd.DataFrame`](../src/fantasy_analyzer/players/player_rankings.py#L841)**
returns [`LEAGUE_PLAYER_RANKING_COLUMNS`](../src/fantasy_analyzer/players/player_rankings.py#L474).
Weights are a frozen
[`RankingWeights`](../src/fantasy_analyzer/players/player_rankings.py#L562)
dataclass; the defaults are
[`DEFAULT_RANKING_WEIGHTS`](../src/fantasy_analyzer/players/player_rankings.py#L638).
Also reachable as `PlayerAnalytics.player_ranking_df`.

```python
import pandas as pd
from fantasy_analyzer.players.performance import PLAYER_PERFORMANCE_COLUMNS
from fantasy_analyzer.players.player_rankings import build_league_player_rankings

def row(pid, name, pos, team, ppg, cv, ceiling, g=4):
    return {"season": 2025, "sleeper_player_id": pid, "player_name": name,
            "position": pos, "nfl_team": team, "games_played": g,
            "total_points": ppg * g, "points_per_game": ppg,
            "median_points": ppg, "stdev_points": cv * ppg, "cv": cv,
            "scoring_floor": 0.0, "scoring_ceiling": ceiling,
            "boom_games": 0, "boom_pct": 0.0, "bust_games": 0, "bust_pct": 0.0}

# A 2-team league starting 1 QB / 1 RB / 1 TE -- starter cutoff = 2 per
# position, so each position's 2nd-best player is its replacement level.
rows = [
    row("1", "QB Volatile", "QB", "BUF", 22.0, 0.60, 40.0),
    row("2", "QB Steady",   "QB", "KC",  20.0, 0.10, 23.0),
    row("3", "QB Backup",   "QB", "NYJ", 14.0, 0.30, 18.0),
    row("4", "RB Elite",    "RB", "SF",  18.0, 0.20, 25.0),
    row("5", "RB Mid",      "RB", "DAL", 10.0, 0.40, 16.0),
    row("6", "RB Deep",     "RB", "SEA",  8.0, 0.50, 12.0),
    row("7", "TE Scarce",   "TE", "BAL", 12.0, 0.25, 20.0),
    row("8", "TE Deep",     "TE", "CHI",  4.0, 0.45,  7.0),
]
performance_df = pd.DataFrame(rows, columns=PLAYER_PERFORMANCE_COLUMNS)

ranked = build_league_player_rankings(performance_df, ["QB", "RB", "TE", "BN"], 2)
print(ranked[["player_name", "position", "points_above_replacement", "scarcity_ratio",
              "z_value", "z_reliability", "z_upside", "z_scarcity",
              "components_used", "ranking_score", "league_rank",
              "position_rank"]].to_string(index=False))
```

**Verified offline** -- real output:

```text
player_name position  points_above_replacement  scarcity_ratio   z_value  z_reliability  z_upside  z_scarcity  components_used  ranking_score  league_rank  position_rank
  TE Scarce       TE                      32.0             2.0  1.511710       0.640513  1.087115    1.578540                5       1.283806          1.0            1.0
   RB Elite       RB                      32.0             0.8  1.511710       0.960769  0.953316   -0.050921                5       1.083368          2.0            1.0
  QB Steady       QB                       0.0             0.1 -0.279946       1.601282 -0.652269   -1.001439                5      -0.067773          3.0            1.0
    TE Deep       TE                       0.0             2.0 -0.279946      -0.640513 -0.652269    1.578540                5      -0.129135          4.0            2.0
QB Volatile       QB                       8.0             0.1  0.167968      -1.601282  1.622309   -1.001439                5      -0.143142          5.0            2.0
     RB Mid       RB                       0.0             0.8 -0.279946      -0.320256 -0.250873   -0.050921                5      -0.249293          6.0            2.0
    RB Deep       RB                      -8.0             0.8 -0.727860      -0.960769 -0.786067   -0.050921                5      -0.681632          7.0            3.0
  QB Backup       QB                     -24.0             0.1 -1.623688       0.320256 -1.321262   -1.001439                5      -1.096198          8.0            3.0
```

Hand-checked. Replacement level is each position's 2nd-best `points_per_game`
(QB `20.0`, RB `10.0`, TE `4.0`), so `TE Scarce`'s
`points_above_replacement = 48 - 4.0*4 = 32.0` -- **identical to `RB Elite`'s**
`72 - 10.0*4 = 32.0`, and the two tie on `z_value` accordingly. `scarcity_ratio`
is `(12-4)/4 = 2.0` at TE against `(18-10)/10 = 0.8` at RB, and that is what
separates them: the ratio pool is `{0.1, 0.1, 0.1, 0.8, 0.8, 0.8, 2.0, 2.0}`,
mean `6.7/8 = 0.8375`, population stdev `0.736440`, so
`z_scarcity(TE) = (2.0 - 0.8375)/0.736440 = 1.578540`. Note also that all
eight players have `games_played = 4`, so `z_rate == z_value` exactly here
(see "value and rate are not independent" above) -- it is omitted from the
printed columns for that reason.

Two things this output shows that FFA-068's `value_rank` cannot: `TE Scarce`
outranks `RB Elite` despite identical VORP (the scarcity tilt), and
`QB Steady` (VORP `0.0`) outranks `QB Volatile` (VORP `8.0`) on reliability
and consistency of floor. Whether you want either of those is exactly what
the weights are for.

