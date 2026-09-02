# The `players` layer, part 1: data (Epic 7)

This is page four of the `fantasy_analyzer` reference (see
[`docs/league.md`](league.md) for the `league/` layer,
[`docs/matchups.md`](matchups.md) for the `matchups/` layer, and
[`docs/analytics.md`](analytics.md) for the `analytics/` layer). It covers
half of [`src/fantasy_analyzer/players/`](../src/fantasy_analyzer/players/)
-- the ingestion/data-engineering half. The other half -- metrics built on
top of the fact table this page produces -- is
[`docs/players-analytics.md`](players-analytics.md).

`players/` is large (~7,800 lines across 20 modules), so it is split along
the same seam AGENTS.md draws between its Data Engineer and Data Scientist
roles:

- **This page**: how raw nflverse data becomes a league-scored player-week
  fact table -- the provider interface, nflverse ingestion/caching, the
  Sleeper<->nflverse ID crosswalk, league scoring, the fact table itself,
  team-defense inputs, and the projection-provider interface.
- **[`docs/players-analytics.md`](players-analytics.md)**: the metrics built
  on that fact table -- player performance, position strength, lineup
  efficiency, replacement-level value, matchup contribution, and manager
  tendencies.

Conventions on this page (matching the earlier three pages):

- Source links point at a specific line in the current `main` (commit
  `b3115d6` at time of writing). **Line numbers drift as the code
  changes** -- if a link looks wrong, search the module for the symbol name
  rather than trusting the anchor.
- Sleeper IDs (`sleeper_player_id`, `roster_id`, ...) and nflverse's native
  `gsis_id` are always the join keys; display names/labels are for reading,
  never for joining.
- "Verified" below means run with `.venv/bin/python`, **entirely offline**,
  against this repository's own fixture files:
  `tests/fixtures/nflverse/player_stats.csv`,
  `tests/fixtures/nflverse/games.csv`,
  `tests/fixtures/sleeper/players.json`, and
  `tests/fixtures/sleeper/league.json` -- plus small in-memory
  `PlayerStatsProvider`/`ProjectionProvider` stand-ins for the modules that
  would otherwise need a live HTTP call. **No network access was made
  anywhere on this page** -- everything nflverse-shaped that would normally
  come from a live download is read from the fixture CSVs above instead.
  `NflverseClient`/`NflverseScheduleClient` themselves (the actual HTTP
  calls) are described but not run.

## What this layer is for

`players/` turns raw nflverse player statistics into fantasy points computed
under **this league's own** Sleeper scoring rules, joined onto **this
league's own** weekly rosters -- not a generic provider's own
`fantasy_points`/`fantasy_points_ppr` columns, which reflect someone else's
scoring assumptions, not this league's. The pipeline, in the order a reader
would actually run it:

```text
NflverseClient.download_player_stats(season)   (raw HTTP download, one release
        |                                        asset per season)
        v
nflverse_cache (disk cache: one CSV per season, no TTL, explicit refresh)
        |
        v
normalize_player_stats(raw, season, week, id_crosswalk=...)
        |    (filter to one week; rename nflverse's raw columns to the
        |     provider-agnostic identity schema; optionally resolve
        |     sleeper_player_id via the crosswalk)
        v
NflverseWeeklyStatsProvider   (a PlayerStatsProvider: caches + normalizes,
        |                       one weekly_stats(season, week) call at a time)
        v
build_player_week_fact_table(weeks, teams_df, players_df, provider,
        |                     scoring_settings)
        |    (join provider stats onto Sleeper's own weekly rosters;
        |     compute fantasy_points from the league's real scoring_settings)
        v
player_week_df   -- the canonical fact table this page documents, and the
                    input every metric in docs/players-analytics.md is built on
```

Team-defense scoring (`DEF` roster slots) is a separate side-path, since a
defense is a team, not a player nflverse's per-player table covers directly
-- see "Team-defense scoring inputs" below. The
[`crosswalk.py`](../src/fantasy_analyzer/players/crosswalk.py) step (Sleeper
`player_id` <-> nflverse `gsis_id`) sits alongside ingestion, feeding
`normalize_player_stats`'s optional `id_crosswalk` argument.

Every function on this page performs **no network access** except the two
explicit HTTP clients (`NflverseClient`, `NflverseScheduleClient`) and the
thin fetching wrappers built directly on them (`get_player_stats_cached`,
`get_games_cached`, and the `weekly_stats`/`points_allowed` methods of the
provider classes, when their cache misses). Every other function -- the
normalization, crosswalk, scoring, and fact-table steps -- takes
already-fetched data and returns a normalized result deterministically, so
it is unit-testable offline, exactly like every other layer in this
reference.

## Quick start: nflverse fixtures to a scored player-week fact table

Fully offline, using this repository's own fixture files: a tiny
`PlayerStatsProvider` reads `tests/fixtures/nflverse/player_stats.csv`
directly (standing in for a real `NflverseWeeklyStatsProvider`, which would
instead download/cache that same shape of data from nflverse), and the
crosswalk is built from `tests/fixtures/sleeper/players.json` (whose player
`"1000"` already carries the same `gsis_id` -- `"00-0034857"`, Josh Allen --
that the nflverse fixture uses, so the two fixtures line up on purpose).

```python
import json
import pandas as pd

from fantasy_analyzer.matchups.loader import WeekMatchups
from fantasy_analyzer.players.crosswalk import build_id_crosswalk
from fantasy_analyzer.players.nflverse_provider import normalize_player_stats
from fantasy_analyzer.players.player_week import build_player_week_fact_table


class FixtureProvider:
    """A tiny PlayerStatsProvider backed by this repo's own nflverse fixture CSV.

    A real NflverseWeeklyStatsProvider does the same normalize_player_stats
    call, but downloads/caches `raw` from nflverse instead of reading a CSV
    fixture -- see "nflverse ingestion" below.
    """

    def __init__(self, id_crosswalk=None):
        self._raw = pd.read_csv("tests/fixtures/nflverse/player_stats.csv")
        self._id_crosswalk = id_crosswalk

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        return normalize_player_stats(
            self._raw, season, week, id_crosswalk=self._id_crosswalk
        )


# Sleeper's own player catalog carries a native gsis_id field -- build the
# ID crosswalk from it (see docs/league.md for LeagueSnapshot.players_df,
# which is resolved from this same catalog).
player_catalog = json.load(open("tests/fixtures/sleeper/players.json"))
crosswalk = build_id_crosswalk(player_catalog)
provider = FixtureProvider(id_crosswalk=crosswalk)

# One week of raw Sleeper rosters (see docs/matchups.md's WeekMatchups).
# Sleeper player_id "1000" (Josh Allen, per the crosswalk) starts; "1003" is
# rostered but nflverse has no stats row for him this week at all.
week1 = WeekMatchups(
    season="2025",
    week=1,
    is_playoff=False,
    matchups=[
        {
            "roster_id": 1,
            "matchup_id": 1,
            "starters": ["1000"],
            "players": ["1000", "1003"],
        },
    ],
)

teams_df = pd.DataFrame(
    [{"roster_id": 1, "owner_id": "u1", "display_name": "Alec", "team_name": "Alec"}]
)
players_df = pd.DataFrame(
    [{"player_id": pid, **p} for pid, p in player_catalog.items()]
)[["player_id", "full_name", "position", "team"]]

# This league's real scoring settings (not a generic provider fantasy-points
# column) -- see docs/league.md's LeagueSettings.scoring_settings.
scoring_settings = json.load(open("tests/fixtures/sleeper/league.json"))["scoring_settings"]

result = build_player_week_fact_table(
    [week1], teams_df, players_df, provider, scoring_settings
)
print(result.player_week_df[[
    "season", "week", "roster_id", "fantasy_team", "sleeper_player_id",
    "player_name", "position", "nfl_team", "started", "bench",
    "passing_yards", "rushing_yards", "fantasy_points",
]])
print(result.unsupported_scoring_keys)
```

**Verified offline** with `.venv/bin/python`. Real output:

```text
   season  week  roster_id fantasy_team sleeper_player_id        player_name position nfl_team  started  bench  passing_yards  rushing_yards  fantasy_points
0    2025     1          1         Alec              1000         Josh Allen       QB      BUF     True  False          245.0           30.0            26.8
1    2025     1          1         Alec              1003  Test Player Three       WR      CIN    False   True            NaN            NaN             0.0

[]
```

Player `1003` gets a row -- with `player_name`/`position`/`nfl_team` falling
back to `players_df` (Sleeper's own catalog) since the provider had no stats
row for him -- and `fantasy_points = 0.0` rather than the row being dropped,
which is the whole point of joining from Sleeper's rosters rather than from
"every player the provider has stats for." Josh Allen's `26.8` is
`245 * 0.04 (pass_yd) + 2 * 4 (pass_td) + 30 * 0.1 (rush_yd) + 1 * 6
(rush_td)` under this fixture league's real `scoring_settings`
(`{'pass_yd': 0.04, 'pass_td': 4, 'pass_int': -2, 'rush_yd': 0.1, 'rush_td':
6, 'rec': 0.5, 'rec_yd': 0.1, 'rec_td': 6, 'fum_lost': -2}`) -- hand-checked
against the raw fixture row.

## The canonical player-week schema

[`build_player_week_fact_table`](../src/fantasy_analyzer/players/player_week.py#L275)
(FFA-064) is the analog of `season_matchup_df`
([`docs/matchups.md`](matchups.md#the-canonical-season_matchup_df-schema)):
the one table every player-analytics function in
[`docs/players-analytics.md`](players-analytics.md) reads instead of
re-deriving. Its `player_week_df` has columns
[`PLAYER_WEEK_COLUMNS`](../src/fantasy_analyzer/players/player_week.py#L176)
as a prefix, followed by whatever raw stat columns the configured provider
supplied (union across every week processed, in first-seen order), then
`fantasy_points` last:

| Column | Meaning |
|---|---|
| `season` | NFL season, normalized to `int` (e.g. `2025`) -- unlike `season_matchup_df`, which treats season as an opaque label; see "`season` is normalized to `int`" below. |
| `week` | NFL week number (`int`). |
| `roster_id` | The Sleeper roster this player was rostered on that week. |
| `fantasy_team` | Display-name label resolved from `teams_df["display_name"]` by `roster_id`, or `None` if unmapped. |
| `sleeper_player_id` | The Sleeper player id -- the row universe's own key (see "Row universe" below); for a team-defense row (not built by this module -- see below) this holds the team code instead. |
| `gsis_id` | nflverse's native player id, from the provider's join; `None` if the provider had no row for this player (or the provider was never configured with a crosswalk that would populate it in the other direction). |
| `player_name` | From the provider's join first, falling back to Sleeper's own `players_df` (`full_name`) if the provider had no value -- see "Identity enrichment order" below. `None` if neither source has one. |
| `position` | Same enrichment order as `player_name`. |
| `nfl_team` | Same enrichment order as `player_name`. |
| `started` | `True` if this player id was in that roster/week's raw Sleeper `starters` list. |
| `bench` | `True` if rostered (`players` list) and *not* in `starters`. For a standard roster, `started`/`bench` are exact complements. |
| *(provider stat columns)* | Whatever the configured provider's `weekly_stats` supplied beyond its own identity columns -- e.g. nflverse's `passing_yards`, `receptions`, etc. (see [`RAW_STAT_COLUMNS`](../src/fantasy_analyzer/players/nflverse_provider.py#L128) below). `NaN` for a rostered player the provider had no row for at all. |
| `fantasy_points` | This league's own scoring, from [`calculate_fantasy_points`](../src/fantasy_analyzer/players/scoring.py#L266) -- never a generic provider `fantasy_points`/`fantasy_points_ppr` column. `0.0` (not `NaN`) for a rostered player with no provider stats. |

**Row universe: rostered players, not "every player with stats."** Rows
come from Sleeper's own weekly roster data (each raw matchup entry's
`players` list -- starters and bench together), left-joined against
provider stats -- not the other way around. This is a deliberate design
choice for two reasons: (1) `roster_id`/`fantasy_team`/`started`/`bench` are
only meaningful for a rostered player, and building from "every player the
provider has stats for" would pull in every league-wide free agent, which
has no roster context to report (FFA-068's replacement-level-value work,
covered in [`docs/players-analytics.md`](players-analytics.md), needs
league-wide players for a *different* reason and is a separate row-source
concern, not an extension of this table); (2) a rostered player who did not
play (bye, inactive, no provider data) still needs a row, so a later
lineup-efficiency analysis can see "this bench spot held a player who scored
zero" versus "this bench spot was empty" -- exactly what the quick start's
`1003` row demonstrates.

**Identity enrichment order: provider first, Sleeper catalog second.**
`player_name`/`position`/`nfl_team` come from the provider's join first (see
the quick start's Josh Allen row); if that produced no match (or `None`
fields), this module falls back to `players_df` (Sleeper's own catalog,
keyed by the same `sleeper_player_id`) -- see the quick start's `1003` row.
If neither source has a value, the field stays `None`. `gsis_id` has no such
fallback (Sleeper's catalog is not itself a source of GSIS ids to this
module).

**`season` is normalized to `int`, unlike `season_matchup_df`.** This module
must call `provider.weekly_stats(season: int, week: int)` and join the
result back on `(season, week, sleeper_player_id)`, so `week.season` is
coerced with `int(...)` up front. A week whose `season` is `None` (a
`WeekMatchups` with no season label) raises `ValueError` if it has any
roster entries to process (there is nothing to look the provider up
against); a `season=None` week with zero roster entries is silently
skipped.

**Byes and `matchup_id` are irrelevant here.** This module reads
`WeekMatchups.matchups` directly and never inspects `matchup_id` -- a bye
entry is processed exactly like any other roster entry, since per-player
stats and lineup context don't depend on whether Sleeper paired that roster
with an opponent that week.

**Regular season vs. playoffs:** not this module's concern at all --
`build_player_week_fact_table` takes whatever `list[WeekMatchups]` it is
given (a full season or any subset, e.g. already pre-filtered to
`is_playoff == False`) and processes every week identically. There is no
`is_playoff` column on this frame; filtering by phase is the caller's job,
exactly as with `season_matchup_df`.

**Missing values / edge cases**, confirmed against `tests/players/test_player_week.py`:

- **Empty `weeks`, or every week with zero roster entries:** `player_week_df`
  is empty with the `PLAYER_WEEK_COLUMNS` prefix and no stat columns.
  `unsupported_scoring_keys` is still computed (an empty stats frame is a
  legal, cheap input to `calculate_fantasy_points`).
- **A `roster_id` absent from `teams_df`** (or an empty `teams_df`):
  `fantasy_team = None`, not an error.
- **A duplicate player id within one entry's `players` list** (should not
  occur in real Sleeper data): preserved as duplicate rows, mirroring
  `resolve_roster_players`'s own duplicate-preserving convention.
- **A raw matchup entry missing the `players` key entirely** (this
  repository's minimal shared `tests/fixtures/sleeper/matchups.json`
  predates that field): falls back to treating `starters` as the row
  universe for that roster, rather than raising or silently emitting no
  rows.

## Reference

### `fantasy_analyzer.players` (package exports)

[`__init__.py`](../src/fantasy_analyzer/players/__init__.py) re-exports the
public surface of **every** module on this page. Import from the package
directly (`from fantasy_analyzer.players import ...`) for anything in its
[`__all__`](../src/fantasy_analyzer/players/__init__.py#L119) list:

`PLAYER_WEEK_IDENTITY_COLUMNS`, `PlayerStatsProvider`,
`validate_player_week_columns`, `PROJECTION_IDENTITY_COLUMNS`,
`ProjectionProvider`, `validate_projection_columns`, `NflverseClient`,
`NflverseWeeklyStatsProvider`, `RAW_STAT_COLUMNS`, `normalize_player_stats`,
`NFLVERSE_DEFAULT_CACHE_DIR`, `load_player_stats_cache`,
`refresh_player_stats_cache`, `get_player_stats_cached`,
`CROSSWALK_COLUMNS`, `build_id_crosswalk`, `gsis_to_sleeper_lookup`,
`sleeper_to_gsis_lookup`, `SCORING_KEY_TO_STAT_COLUMNS`, `ScoringResult`,
`calculate_fantasy_points`, `PLAYER_WEEK_COLUMNS`, `PlayerWeekFactTable`,
`build_player_week_fact_table`,
[`NflverseScheduleClient`](../src/fantasy_analyzer/players/__init__.py#L144),
`NFLVERSE_SCHEDULE_DEFAULT_CACHE_DIR`, `load_games_cache`,
`refresh_games_cache`, `get_games_cached`, `NflverseScheduleProvider`,
`POINTS_ALLOWED_COLUMNS`, `normalize_points_allowed`,
`NflverseTeamDefenseProvider`, `TEAM_CODE_ALIASES`,
`TEAM_DEFENSE_RAW_STAT_COLUMNS`,
[`build_team_defense_stats`](../src/fantasy_analyzer/players/__init__.py#L155),
plus every symbol covered on
[`docs/players-analytics.md`](players-analytics.md).

**Naming note:** the team-defense input path (section 6 below --
`nflverse_schedule_client.py`, `nflverse_schedule_cache.py`,
`points_allowed.py`, `nflverse_defense.py`) contributes the last twelve
names above. Its schedule cache has its own module-level
[`DEFAULT_CACHE_DIR`](../src/fantasy_analyzer/players/nflverse_schedule_cache.py#L21),
which would collide with section 2's per-player
[`nflverse_cache.DEFAULT_CACHE_DIR`](../src/fantasy_analyzer/players/nflverse_cache.py#L40),
so it is re-exported **aliased** as
[`NFLVERSE_SCHEDULE_DEFAULT_CACHE_DIR`](../src/fantasy_analyzer/players/__init__.py#L57)
-- the same aliasing convention `__init__.py` already uses for
`NFLVERSE_DEFAULT_CACHE_DIR` and the two `BOOM_BUST_THRESHOLD_STDEVS`
constants. Both point at `.cache/nflverse`; they differ only in which file
inside it they own (`player_stats_<season>.csv` vs `games.csv`).
Submodule imports (`from fantasy_analyzer.players.nflverse_defense import
NflverseTeamDefenseProvider`) keep working and are used by some examples
further down this page.

---

### 1. The provider interface (FFA-060)

**Answers:** "what must any source of weekly player statistics implement to
plug into this codebase" -- the seam FFA-061's nflverse provider (and any
future provider) sits behind, so `player_week.py` and everything above it
never depend on nflverse specifically.

Module:
[`players/provider.py`](../src/fantasy_analyzer/players/provider.py) --
[module docstring](../src/fantasy_analyzer/players/provider.py#L1). Uses
`typing.Protocol` (`@runtime_checkable`), not `abc.ABC` -- any object with a
matching `weekly_stats` method satisfies it structurally, no inheritance,
matching this codebase's existing duck-typed conventions (`SleeperClient`,
`LeagueSnapshot`, ...).

**[`PLAYER_WEEK_IDENTITY_COLUMNS`](../src/fantasy_analyzer/players/provider.py#L154)**
-- `["season", "week", "sleeper_player_id", "gsis_id", "player_name",
"position", "nfl_team"]` -- the columns every provider's `weekly_stats`
result must carry, in this order, as a prefix. No per-stat column
(`passing_yds`, etc.) is required: different providers expose different
stat categories, and requiring a fixed stat schema here would bake one
provider's shape into a supposedly provider-agnostic interface.
`sleeper_player_id` is part of the required *schema* but not required to be
*populated* -- a provider with no crosswalk returns `None` for it (check
with `pandas.isna()`, not `is None`, once it's in a DataFrame column).

**[`PlayerStatsProvider`](../src/fantasy_analyzer/players/provider.py#L166)**
(Protocol) -- one method:
`weekly_stats(self, season: int, week: int) -> pd.DataFrame`. One week at a
time, mirroring `SleeperClient.get_matchups(league_id, week)`. Returns an
*empty* DataFrame (same identity columns) for a season/week the provider has
no data for yet -- an expected outcome, not an error. A player who did not
play that week simply has no row (this is a fact table of observed
player-weeks, not a roster cross-product).

**[`validate_player_week_columns(stats: pd.DataFrame) -> None`](../src/fantasy_analyzer/players/provider.py#L205)**
-- lightweight contract check: confirms `PLAYER_WEEK_IDENTITY_COLUMNS` are
present, in order, as a prefix of `stats.columns`. Does not check row
values. Raises `ValueError` if a required column is missing or the leading
columns are out of order.

```python
import pandas as pd
from fantasy_analyzer.players.provider import (
    PLAYER_WEEK_IDENTITY_COLUMNS, validate_player_week_columns,
)

class FakePlayerStatsProvider:
    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        if (season, week) != (2025, 1):
            return pd.DataFrame(columns=PLAYER_WEEK_IDENTITY_COLUMNS)
        return pd.DataFrame([{
            "season": 2025, "week": 1, "sleeper_player_id": None,
            "gsis_id": "00-0034857", "player_name": "Josh Allen",
            "position": "QB", "nfl_team": "BUF", "passing_yards": 245,
        }])

provider = FakePlayerStatsProvider()
week1 = provider.weekly_stats(2025, 1)
validate_player_week_columns(week1)   # no exception
print(week1)
print(provider.weekly_stats(2025, 2))  # no data for this week -> empty frame
```

**Verified offline** -- real output:

```text
   season  week sleeper_player_id     gsis_id player_name position nfl_team  passing_yards
0    2025     1              None  00-0034857  Josh Allen       QB      BUF            245

Empty DataFrame
Columns: [season, week, sleeper_player_id, gsis_id, player_name, position, nfl_team]
Index: []
```

---

### 2. nflverse ingestion: client, cache, provider (FFA-061)

**Answers:** "where does real weekly player-stats data actually come from,
and how is it cached locally." (The sibling per-*game* schedule/score pull
-- `nflverse_schedule_client.py` / `nflverse_schedule_cache.py`, needed for
team-defense points-allowed -- follows the identical client/cache split but
is covered in "Team-defense scoring inputs" (section 6 below), next to the
`points_allowed.py` normalization step that actually consumes it.)

**HTTP client --**
[`players/nflverse_client.py`](../src/fantasy_analyzer/players/nflverse_client.py)
([module docstring](../src/fantasy_analyzer/players/nflverse_client.py#L1)).
[`NflverseClient`](../src/fantasy_analyzer/players/nflverse_client.py#L38)
downloads nflverse's `stats_player_week_<season>.csv.gz` release asset (the
`stats_player` GitHub release tag) -- **one release asset per season**, a
migration from an older, now-frozen cumulative-all-seasons asset (see the
module docstring for why). Its one public method,
[`download_player_stats(season: int) -> pd.DataFrame`](../src/fantasy_analyzer/players/nflverse_client.py#L53),
returns nflverse's raw, unrenamed columns; a 404 (no asset published yet
for that season) returns an empty DataFrame rather than raising, any other
non-2xx response raises `requests.exceptions.RequestException`. **Not run on
this page** (it makes a real HTTP call) -- exercised here only through the
`FixtureProvider` stand-ins that read the equivalent CSV shape from a local
fixture file instead.

**Disk cache --**
[`players/nflverse_cache.py`](../src/fantasy_analyzer/players/nflverse_cache.py)
([module docstring](../src/fantasy_analyzer/players/nflverse_cache.py#L1)).
One CSV file per season at
`<cache_dir>/player_stats_<season>.csv`, default
[`DEFAULT_CACHE_DIR = Path(".cache/nflverse")`](../src/fantasy_analyzer/players/nflverse_cache.py#L40)
(relative to the current working directory; callers may pass any other
directory). **No time-to-live/staleness check** -- nflverse updates on its
own schedule, so a cached file is used forever until you explicitly ask for
a refresh.

- [`load_player_stats_cache(season, cache_dir=DEFAULT_CACHE_DIR) -> Optional[pd.DataFrame]`](../src/fantasy_analyzer/players/nflverse_cache.py#L48)
  -- `None` if no cache file exists yet for `season`; makes no network calls.
- [`refresh_player_stats_cache(client, season, cache_dir=DEFAULT_CACHE_DIR) -> pd.DataFrame`](../src/fantasy_analyzer/players/nflverse_cache.py#L65)
  -- **always** hits the network via `client.download_player_stats(season)`
  and (over)writes the cache file. **This is how you invalidate/refresh the
  cache.**
- [`get_player_stats_cached(client, season, cache_dir=DEFAULT_CACHE_DIR, force_refresh=False) -> pd.DataFrame`](../src/fantasy_analyzer/players/nflverse_cache.py#L88)
  -- the one most callers want: loads from cache if present and
  `force_refresh=False`, otherwise downloads and caches a fresh copy. Pass
  `force_refresh=True` to force a fresh download even if a cache file
  exists.

```python
import pandas as pd
from pathlib import Path
from fantasy_analyzer.players.nflverse_cache import (
    get_player_stats_cached, load_player_stats_cache,
)

class FakeNflverseClient:
    """Stands in for NflverseClient -- no network, matches its shape."""
    def __init__(self):
        self.calls = 0
    def download_player_stats(self, season: int) -> pd.DataFrame:
        self.calls += 1
        return pd.DataFrame([{"season": season, "week": 1, "player_id": "00-0034857"}])

cache_dir = Path("/tmp/nflverse_cache_demo")
client = FakeNflverseClient()

print(load_player_stats_cache(2025, cache_dir))   # nothing cached yet -> None

first = get_player_stats_cached(client, 2025, cache_dir)   # downloads + writes
print("calls after 1st get_player_stats_cached:", client.calls)

second = get_player_stats_cached(client, 2025, cache_dir)  # reads cache
print("calls after 2nd (cache hit):", client.calls)

third = get_player_stats_cached(client, 2025, cache_dir, force_refresh=True)
print("calls after force_refresh=True:", client.calls)
```

**Verified offline** -- real output:

```text
None
calls after 1st get_player_stats_cached: 1
calls after 2nd (cache hit): 1
calls after force_refresh=True: 2
```

**Normalization --**
[`players/nflverse_provider.py`](../src/fantasy_analyzer/players/nflverse_provider.py)
([module docstring](../src/fantasy_analyzer/players/nflverse_provider.py#L1)).

**[`normalize_player_stats(raw, season, week, id_crosswalk=None) -> pd.DataFrame`](../src/fantasy_analyzer/players/nflverse_provider.py#L160)**
filters nflverse's raw per-season table to one week and renames columns to
the identity schema: `season`/`week` (int, filter args -- not inferred from
`raw`), `gsis_id` <- `player_id`, `player_name` <- `player_display_name`
(**not** nflverse's own abbreviated `player_name` column, e.g. `"J.Allen"`
-- that would collide with this schema's own `player_name`), `position` <-
`position`, `nfl_team` <- `team`. `sleeper_player_id` stays `None` unless
`id_crosswalk` (a [`build_id_crosswalk`](#3-sleeper-nflverse-id-crosswalk-ffa-062)
DataFrame) is supplied, in which case it's populated via
[`gsis_to_sleeper_lookup`](../src/fantasy_analyzer/players/crosswalk.py#L118)
for every row whose `gsis_id` has a match. Beyond the identity prefix, a
fixed set of raw stat columns is passed through --
[`RAW_STAT_COLUMNS`](../src/fantasy_analyzer/players/nflverse_provider.py#L128)
(basic passing/rushing/receiving counts, two-point conversions, and kicking
stats) -- **deliberately excluding** nflverse's own
`fantasy_points`/`fantasy_points_ppr` (that's `scoring.py`'s job, using
*this league's* rules, not nflverse's generic ones) and advanced/efficiency
metrics (`passing_epa`, `racr`, etc.). Individual-level defensive stats are
in the raw release but not passed through here either -- see "Team-defense
scoring inputs" below.

**[`NflverseWeeklyStatsProvider`](../src/fantasy_analyzer/players/nflverse_provider.py#L225)**
-- a concrete `PlayerStatsProvider`. Constructor:
`__init__(self, client: Optional[NflverseClient] = None, cache_dir:
Union[str, Path] = DEFAULT_CACHE_DIR, force_refresh: bool = False,
id_crosswalk: Optional[pd.DataFrame] = None)`. Each season's raw table is
downloaded/cached **at most once per provider instance**, on the first
`weekly_stats` call for that season, then reused in memory for every later
call on that same season -- construct a new provider (or pass
`force_refresh=True` at construction) for a fresh mid-session download.

The quick-start example above is exactly this shape, with `FixtureProvider`
standing in for `NflverseWeeklyStatsProvider` so the whole example runs
offline against `tests/fixtures/nflverse/player_stats.csv` instead of a
live download.

```python
import json
import pandas as pd
from fantasy_analyzer.players.nflverse_provider import normalize_player_stats
from fantasy_analyzer.players.crosswalk import build_id_crosswalk

raw = pd.read_csv("tests/fixtures/nflverse/player_stats.csv")
player_catalog = json.load(open("tests/fixtures/sleeper/players.json"))
crosswalk = build_id_crosswalk(player_catalog)

normalized = normalize_player_stats(raw, season=2025, week=1, id_crosswalk=crosswalk)
print(normalized[["season", "week", "sleeper_player_id", "gsis_id",
                   "player_name", "position", "nfl_team",
                   "passing_yards", "rushing_yards"]])
```

**Verified offline** -- real output:

```text
   season  week sleeper_player_id     gsis_id  player_name position nfl_team  passing_yards  rushing_yards
0    2025     1              1000  00-0034857   Josh Allen       QB      BUF          245.0           30.0
1    2025     1               NaN         NaN  Some Rookie       RB      NaN            0.0           10.0
2    2025     1               NaN  00-0044920  Kris Booter        K      SEA            NaN            NaN
```

`sleeper_player_id` is populated (`1000`) only for Josh Allen, the one
player whose `gsis_id` is in the crosswalk; "Some Rookie" (no `gsis_id` in
the nflverse fixture at all) and Kris Booter (no Sleeper catalog entry in
this fixture) both stay unresolved.

---

### 3. Sleeper<->nflverse ID crosswalk (FFA-062)

**Answers:** "how do I go from a Sleeper `player_id` to nflverse's
`gsis_id`, or back" -- built by extraction, not name/position/team fuzzy
matching, since Sleeper's own player catalog already carries a native
`gsis_id` field on most players.

Module:
[`players/crosswalk.py`](../src/fantasy_analyzer/players/crosswalk.py) --
[module docstring](../src/fantasy_analyzer/players/crosswalk.py#L1).

**[`build_id_crosswalk(player_catalog: dict) -> pd.DataFrame`](../src/fantasy_analyzer/players/crosswalk.py#L74)**
-- `player_catalog` is the raw Sleeper player catalog dict (keyed by
`player_id`), e.g. from `SleeperClient.get_players()` (see
[`docs/sleeper.md`](sleeper.md) for that method, and
[`docs/league.md`](league.md) for how the same catalog feeds
`LeagueSnapshot`). Returns
[`CROSSWALK_COLUMNS`](../src/fantasy_analyzer/players/crosswalk.py#L71) =
`["sleeper_player_id", "gsis_id", "full_name", "position", "team"]`, one row
per Sleeper player with a **non-empty** `gsis_id`. A player with `gsis_id`
missing, `None`, or blank contributes **no row** (never a row of `None`
fields) -- there is nothing to map them to, and a `None`-to-`None` join
would spuriously match every such player against nflverse's own
unidentified rows. If two Sleeper players somehow share a `gsis_id`, the
policy is **last-value-wins** (per catalog iteration/insertion order).

**[`gsis_to_sleeper_lookup(crosswalk) -> dict[str, str]`](../src/fantasy_analyzer/players/crosswalk.py#L118)**
/
**[`sleeper_to_gsis_lookup(crosswalk) -> dict[str, str]`](../src/fantasy_analyzer/players/crosswalk.py#L133)**
-- fast `dict` views derived from the crosswalk DataFrame, for a caller
that just needs one join key mapped to the other (this is what
`normalize_player_stats` uses internally).

```python
import json
from fantasy_analyzer.players.crosswalk import build_id_crosswalk, gsis_to_sleeper_lookup

player_catalog = json.load(open("tests/fixtures/sleeper/players.json"))
print(player_catalog)

crosswalk = build_id_crosswalk(player_catalog)
print(crosswalk)
print(gsis_to_sleeper_lookup(crosswalk))
```

**Verified offline** -- real output:

```text
{'1000': {'player_id': '1000', 'full_name': 'Test Player One', 'position': 'QB', 'team': 'SEA', 'gsis_id': '00-0034857'}, '1002': {'player_id': '1002', 'full_name': 'Test Player Two', 'position': 'RB', 'team': 'KC', 'gsis_id': None}, '1003': {'player_id': '1003', 'full_name': 'Test Player Three', 'position': 'WR', 'team': 'CIN'}}
  sleeper_player_id     gsis_id        full_name position team
0              1000  00-0034857  Test Player One       QB  SEA
{'00-0034857': '1000'}
```

Only `"1000"` produces a row: `"1002"` has `gsis_id: null` and `"1003"` has
no `gsis_id` key at all.

---

### 4. League-specific fantasy scoring (FFA-063)

**Answers:** "how many fantasy points did this player-week actually score,
in *this league's* scoring system" -- the step that turns raw counting
stats into points using the league's real Sleeper `scoring_settings`, never
a generic provider fantasy-point column.

Module:
[`players/scoring.py`](../src/fantasy_analyzer/players/scoring.py) --
[module docstring](../src/fantasy_analyzer/players/scoring.py#L1), which
carries the full Sleeper-scoring-key -> raw-stat-column mapping table.

**One formula for every category:** Sleeper's `scoring_settings` values are
already expressed in the unit each category is scored in (`pass_td: 4` = 4
points per *event*, `pass_yd: 0.04` = 0.04 points per *yard*), so every
supported category reduces to
`points_from_category = raw_stat_value * scoring_weight`, summed across
categories. See
[`SCORING_KEY_TO_STAT_COLUMNS`](../src/fantasy_analyzer/players/scoring.py#L206)
for the full 24-key mapping table (`pass_yd`, `pass_td`, `pass_int`,
`pass_cmp`, `pass_att`, `pass_sack`, `pass_2pt`, `rush_att`, `rush_yd`,
`rush_td`, `rush_2pt`, `rec`, `rec_tgt`, `rec_yd`, `rec_td`, `rec_2pt`,
`fum_lost` (sums three separate nflverse fumbles-lost columns),
`fgm_0_19`/`fgm_20_29`/`fgm_30_39`/`fgm_40_49`, `fgm_50p` (sums two nflverse
50-59/60+ bands), `fgmiss`, `xpm`, `xpmiss`).

**Deliberately unmapped, surfaced rather than guessed at:** `fum` (total
fumbles -- nflverse only exposes fumbles *lost* per play type, no "total"
count to sum), `bonus_rec_te`/any yardage-tier bonus (needs conditional
logic this flat raw-stat-times-weight shape can't express correctly), and
every team-`DEF`/IDP key (`sack`, `int`, `fum_rec`, `pts_allow_*`, etc. --
nflverse's defensive stats are per-*player*, not per-team, and points
allowed isn't in this provider's table at all; see "Team-defense scoring
inputs" below).

**[`ScoringResult`](../src/fantasy_analyzer/players/scoring.py#L240)** --
frozen dataclass: `points_df` (`stats` with one appended `fantasy_points`
column) and `unsupported_scoring_keys` (`list[str]`, sorted -- every
`scoring_settings` key with no mapping, so the caller can see, rather than
silently miss, an unsupported league scoring category).

**[`calculate_fantasy_points(stats: pd.DataFrame, scoring_settings: Mapping[str, float]) -> ScoringResult`](../src/fantasy_analyzer/players/scoring.py#L266)**
-- `stats` is a raw per-stat frame shaped like a `PlayerStatsProvider`
result; only the stat columns actually referenced by `scoring_settings` need
be present. An **absent** mapped stat column contributes zero for every row;
a **present but `NaN`** value contributes zero for that row (via
`.fillna(0)`) -- never `NaN` propagation into `fantasy_points`. No tie
handling is needed: each row's points come only from that row's own stats
and the same settings dict, so identical inputs produce identical output.
**Phase-agnostic**: no notion of regular season vs. playoffs at all -- one
row is one player's one NFL week, scored identically regardless of a
league's `playoff_week_start`; any phase filtering is the caller's job.

```python
import json
import pandas as pd
from fantasy_analyzer.players.nflverse_provider import normalize_player_stats
from fantasy_analyzer.players.crosswalk import build_id_crosswalk
from fantasy_analyzer.players.scoring import calculate_fantasy_points

raw = pd.read_csv("tests/fixtures/nflverse/player_stats.csv")
crosswalk = build_id_crosswalk(json.load(open("tests/fixtures/sleeper/players.json")))
normalized = normalize_player_stats(raw, season=2025, week=1, id_crosswalk=crosswalk)

scoring_settings = json.load(open("tests/fixtures/sleeper/league.json"))["scoring_settings"]
print(scoring_settings)

result = calculate_fantasy_points(normalized, scoring_settings)
print(result.points_df[["player_name", "passing_yards", "rushing_yards", "fantasy_points"]])
print(result.unsupported_scoring_keys)
```

**Verified offline** -- real output:

```text
{'pass_yd': 0.04, 'pass_td': 4, 'pass_int': -2, 'rush_yd': 0.1, 'rush_td': 6, 'rec': 0.5, 'rec_yd': 0.1, 'rec_td': 6, 'fum_lost': -2}
   player_name  passing_yards  rushing_yards  fantasy_points
0   Josh Allen          245.0           30.0            26.8
1  Some Rookie            0.0           10.0             1.0
2  Kris Booter            NaN            NaN             0.0

[]
```

Hand-checked: Josh Allen's raw fixture row has `passing_tds=2`,
`rushing_tds=1` (not printed above) alongside the 245 passing/30 rushing
yards shown, so `26.8 = 245*0.04 + 2*4 + 30*0.1 + 1*6`. Some Rookie has no
`gsis_id` (so scores independently of the crosswalk) and `1.0 = 10*0.1`
rushing yards, no touchdowns. Kris Booter's row has every mapped stat
`NaN`/absent under this particular `scoring_settings` (which has no
`fgm_*`/`xpm` keys), so his `fantasy_points` is `0.0`. `[]` means every key
in this fixture league's `scoring_settings` was supported.

---

### 5. The player-week fact table (FFA-064)

See ["The canonical player-week schema"](#the-canonical-player-week-schema)
above -- that section (and the Quick Start it follows) covers
[`build_player_week_fact_table`](../src/fantasy_analyzer/players/player_week.py#L275)
and [`PlayerWeekFactTable`](../src/fantasy_analyzer/players/player_week.py#L192)
in full: signature, schema, row-universe design decision, identity
enrichment order, `season` normalization, and edge cases. This section is
the join point where the roster data (page three, `matchups/`), the
provider stats (sections 1-2 above), and the scoring engine (section 4
above) finally meet.

---

### 6. Team-defense scoring inputs

**Answers:** "how do I score a Sleeper `DEF` roster slot" -- a whole team's
defense/special-teams unit, not an individual player, so it needs a
different data path than sections 1-5 above.

A Sleeper `DEF` slot is identified by team code (e.g. `"SEA"`), not a
per-player id -- confirmed against this project's real league rosters,
whose `players` lists contain entries like `"NE"`/`"LAR"` alongside normal
numeric Sleeper player ids. Neither `nflverse_client.py`'s per-player table
nor `nflverse_provider.normalize_player_stats` (scoped to individual
rostered players) produces a row like that, and points allowed -- the input
every `pts_allow_*` Sleeper scoring key needs -- isn't in the per-player
table at all (it's a per-*game*, not per-player, fact). This is genuinely
two separate raw-data problems, solved by two modules:

**Points allowed --**
[`players/points_allowed.py`](../src/fantasy_analyzer/players/points_allowed.py)
([module docstring](../src/fantasy_analyzer/players/points_allowed.py#L1)),
backed by
[`players/nflverse_schedule_client.py`](../src/fantasy_analyzer/players/nflverse_schedule_client.py)
/
[`players/nflverse_schedule_cache.py`](../src/fantasy_analyzer/players/nflverse_schedule_cache.py)
-- mirroring the client/cache split above, except nflverse's `schedules`
release is a **single cumulative** `games.csv` asset covering every season
(1999-present), not one file per season, so
[`NflverseScheduleClient`](../src/fantasy_analyzer/players/nflverse_schedule_client.py#L31)`.download_games()`
takes no `season` argument and the cache
([`DEFAULT_CACHE_DIR`](../src/fantasy_analyzer/players/nflverse_schedule_cache.py#L21)
= `.cache/nflverse`, same directory as the per-player cache) is one file,
`<cache_dir>/games.csv`. Same
[`load_games_cache`](../src/fantasy_analyzer/players/nflverse_schedule_cache.py#L29)
/
[`refresh_games_cache`](../src/fantasy_analyzer/players/nflverse_schedule_cache.py#L46)
/
[`get_games_cached`](../src/fantasy_analyzer/players/nflverse_schedule_cache.py#L65)
shape as section 2's per-season cache -- no time-to-live check here either,
same reasoning.

```python
import pandas as pd
from pathlib import Path
from fantasy_analyzer.players.nflverse_schedule_cache import (
    get_games_cached, load_games_cache,
)

class FakeNflverseScheduleClient:
    """Stands in for NflverseScheduleClient -- no network, matches its shape."""
    def __init__(self):
        self.calls = 0
    def download_games(self) -> pd.DataFrame:
        self.calls += 1
        return pd.DataFrame([{"season": 2025, "week": 1, "home_team": "BUF", "home_score": 41}])

cache_dir = Path("/tmp/nflverse_schedule_cache_demo")
client = FakeNflverseScheduleClient()

print(load_games_cache(cache_dir))   # nothing cached yet -> None

first = get_games_cached(client, cache_dir)   # downloads + writes
print("calls after 1st get_games_cached:", client.calls)

second = get_games_cached(client, cache_dir)  # reads cache
print("calls after 2nd (cache hit):", client.calls)

third = get_games_cached(client, cache_dir, force_refresh=True)
print("calls after force_refresh=True:", client.calls)
```

**Verified offline** -- real output:

```text
None
calls after 1st get_games_cached: 1
calls after 2nd (cache hit): 1
calls after force_refresh=True: 2
```

Identical cache-hit/miss/`force_refresh` behavior to section 2's
`get_player_stats_cached` example, as expected from the shared
`nflverse_cache.py`/`nflverse_schedule_cache.py` design.

**[`normalize_points_allowed(games: pd.DataFrame) -> pd.DataFrame`](../src/fantasy_analyzer/players/points_allowed.py#L76)**
filters nflverse's raw games table to **regular season only**
(`game_type == "REG"`; the NFL's actual postseason -- `"WC"`/`"DIV"`/
`"CON"`/`"SB"` -- is always excluded, since NFL postseason week numbers
restart from 1 within each round and would otherwise collide with a
fantasy league's own late-season week numbers) and games with a **final
score already recorded** (both `home_score`/`away_score` non-null -- an
unplayed/in-progress game is excluded entirely, not emitted with a `NaN`
points-allowed value). Returns
[`POINTS_ALLOWED_COLUMNS`](../src/fantasy_analyzer/players/points_allowed.py#L73)
= `["season", "week", "team", "points_allowed"]`, **two rows per game**
(each team's points allowed is the *other* team's score). Team codes are
nflverse-native (e.g. `"LA"`, not Sleeper's `"LAR"`) -- unaliased at this
step; see below for where that alignment happens.

**[`NflverseScheduleProvider`](../src/fantasy_analyzer/players/points_allowed.py#L132)**
-- `points_allowed(season, week) -> pd.DataFrame` (columns `team`,
`points_allowed` only -- `season`/`week` are dropped since every row already
matches the request). The full cumulative games table is downloaded/cached
at most once per instance, on the first call, reused thereafter regardless
of which season/week is later requested.

**Team-defense aggregation --**
[`players/nflverse_defense.py`](../src/fantasy_analyzer/players/nflverse_defense.py)
([module docstring](../src/fantasy_analyzer/players/nflverse_defense.py#L1)).
[`build_team_defense_stats(raw_stats, points_allowed, season, week) -> pd.DataFrame`](../src/fantasy_analyzer/players/nflverse_defense.py#L104)
takes nflverse's **raw** (not `normalize_player_stats`-filtered) per-season
player table -- because that normalization step drops the individual
defensive/special-teams columns this function needs -- filters to
`season`/`week`, and sums
[`TEAM_DEFENSE_RAW_STAT_COLUMNS`](../src/fantasy_analyzer/players/nflverse_defense.py#L89)
(`def_sacks`, `def_interceptions`, `def_fumbles_forced`, `def_tds`,
`def_safeties`, `def_punt_blocks`, `def_pat_blocks`, `def_fg_blocks`,
`fumble_recovery_opp`, `fumble_recovery_tds`, `special_teams_tds`) grouped
by `team`, then joins in that team's `points_allowed`. Returns a
`PLAYER_WEEK_IDENTITY_COLUMNS`-prefixed frame -- `sleeper_player_id` and
`nfl_team` both hold the **Sleeper-aliased** team code (via
[`TEAM_CODE_ALIASES`](../src/fantasy_analyzer/players/nflverse_defense.py#L77)
= `{"LA": "LAR"}`, the one known nflverse/Sleeper mismatch verified against
this project's real rosters -- not necessarily exhaustive for historical
relocated franchises), `gsis_id`/`player_name` always `None`, `position`
always `"DEF"` -- followed by the present defense stat columns and
`points_allowed` (`NaN` if that team's game hasn't been played/published
yet). One row per team with **any** player-week row that week; a team on a
bye produces no row at all (mirroring `PlayerStatsProvider`'s "no data yet"
convention).

**[`NflverseTeamDefenseProvider`](../src/fantasy_analyzer/players/nflverse_defense.py#L191)**
-- a `PlayerStatsProvider` (same `weekly_stats(season, week)` shape as
`NflverseWeeklyStatsProvider`, but one row per *team* instead of per
rostered player), wrapping `build_team_defense_stats` with the same
per-season in-memory caching pattern.

**Scope of this ticket, stated plainly:** this is raw aggregation only.
Mapping these raw counts onto Sleeper's actual `sack`/`int`/`fum_rec`/`ff`/
`def_td`/`def_st_td`/`pts_allow_*` scoring keys (several of which look like
near-duplicates of each other, e.g. `def_st_ff` and `st_ff` at the same
weight in this project's real league) is **explicitly deferred** to a
follow-up ticket, to be verified against Sleeper's own already-computed DEF
points before being trusted -- `scoring.py`'s `SCORING_KEY_TO_STAT_COLUMNS`
has no entries for any of these keys yet, so they always land in
`unsupported_scoring_keys` today for a league that scores IDP/team defense.

```python
import pandas as pd
from fantasy_analyzer.players.points_allowed import normalize_points_allowed
from fantasy_analyzer.players.nflverse_defense import build_team_defense_stats

games = pd.read_csv("tests/fixtures/nflverse/games.csv")
print(games)

points_allowed = normalize_points_allowed(games)
print(points_allowed)

# Hand-built (the shared nflverse fixture CSV carries no defensive columns),
# mirroring tests/players/test_nflverse_defense.py's own fixture rows.
raw_stats = pd.DataFrame([
    {"season": 2025, "week": 1, "team": "BUF", "def_sacks": 2, "def_interceptions": 1},
    {"season": 2025, "week": 1, "team": "BUF", "special_teams_tds": 1},
    {"season": 2025, "week": 1, "team": "LA", "def_sacks": 3, "fumble_recovery_opp": 1},
])
team_defense = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)
print(team_defense)
```

**Verified offline** -- real output:

```text
   season  week game_type home_team  home_score away_team  away_score
0    2025     1       REG       BUF        41.0       BAL        40.0
1    2025     1       REG       SEA        13.0        SF        17.0
2    2025     2       REG        GB        27.0       WAS        18.0
3    2025     1        WC        KC        20.0       DEN        17.0
4    2025     3       REG       DAL         NaN       NYG         NaN
5    2024     1       REG        KC        27.0       BAL        20.0

   season  week team  points_allowed
0    2025     1  BUF            40.0
1    2025     1  SEA            17.0
2    2025     2   GB            18.0
3    2024     1   KC            20.0
4    2025     1  BAL            41.0
5    2025     1   SF            13.0
6    2025     2  WAS            27.0
7    2024     1  BAL            27.0

   season  week sleeper_player_id gsis_id player_name position nfl_team  def_sacks  def_interceptions  fumble_recovery_opp  special_teams_tds  points_allowed
0    2025     1               BUF    None        None      DEF      BUF        2.0                1.0                  0.0                1.0            40.0
1    2025     1               LAR    None        None      DEF      LAR        3.0                0.0                  1.0                0.0             NaN
```

Row-3 (the `"WC"` postseason game) and row-4 (the unplayed `DAL`/`NYG` game,
both scores `NaN`) both correctly produce no `points_allowed` rows. `"LA"`
aliases to `"LAR"` in the team-defense output, but the points-allowed join
happens on the **nflverse-native** code (`"LA"`) *before* aliasing -- and
since this fixture's `games.csv` has no `"LA"`/Rams game at all, `LAR`'s
`points_allowed` correctly comes back `NaN` rather than a guessed value.

---

### 7. The projection-provider interface (FFA-072)

**Answers:** "what would a future projections/rankings/waiver/trade-value
vendor plug into" -- deliberately **no methodology, no vendor, no ranking
logic** is implemented by this ticket; only the seam.

Module:
[`players/projections.py`](../src/fantasy_analyzer/players/projections.py)
([module docstring](../src/fantasy_analyzer/players/projections.py#L1)),
mirroring `provider.py`'s shape exactly (`Protocol`, DataFrame return,
identity-column prefix, `validate_*_columns` helper).

**[`PROJECTION_IDENTITY_COLUMNS`](../src/fantasy_analyzer/players/projections.py#L200)**
-- `["season", "week", "source", "sleeper_player_id", "gsis_id",
"player_name", "position", "nfl_team"]`. The one column beyond
`PLAYER_WEEK_IDENTITY_COLUMNS` is **`source`** -- a short provider/vendor
label (e.g. `"nflverse"`), placed right after `season`/`week` since, like
them, it identifies *which row this is describing* rather than *who it's
about*. Unlike an observed stat, a projection is one methodology's opinion,
so multiple vendors' rows can coexist in one concatenated frame without
colliding on `(season, week, sleeper_player_id)`. No projection *value*
column (e.g. `projected_points`) is required, for the same reason no raw
stat column is required on `PLAYER_WEEK_IDENTITY_COLUMNS`.

**[`ProjectionProvider`](../src/fantasy_analyzer/players/projections.py#L213)**
(Protocol) -- one method:
`projections(self, season: int, week: int) -> pd.DataFrame`. Same
empty-frame-for-no-data, no-row-for-unprojected-player conventions as
`PlayerStatsProvider.weekly_stats`.

**[`validate_projection_columns(projections: pd.DataFrame) -> None`](../src/fantasy_analyzer/players/projections.py#L252)**
-- identical contract check to `validate_player_week_columns`, against
`PROJECTION_IDENTITY_COLUMNS` instead.

**What is explicitly not implemented, per AGENTS.md's "no vendor-specific
logic yet" instruction:** no concrete provider, no rest-of-season ranking
aggregation, no waiver-value comparison, no trade-value math, no start/sit
logic, no opponent-adjustment methodology. The module docstring sketches how
each of AGENTS.md's six listed future capabilities would eventually be built
as a function *on top of* `projections()` plus other already-canonical
inputs (e.g. FFA-068's replacement-level value, covered in
[`docs/players-analytics.md`](players-analytics.md)) -- none of that is
implemented here.

```python
import pandas as pd
from fantasy_analyzer.players.projections import (
    PROJECTION_IDENTITY_COLUMNS, validate_projection_columns,
)

class FakeProjectionProvider:
    def projections(self, season: int, week: int) -> pd.DataFrame:
        if (season, week) != (2025, 2):
            return pd.DataFrame(columns=PROJECTION_IDENTITY_COLUMNS)
        return pd.DataFrame([{
            "season": 2025, "week": 2, "source": "example-vendor",
            "sleeper_player_id": "1000", "gsis_id": "00-0034857",
            "player_name": "Josh Allen", "position": "QB", "nfl_team": "BUF",
            "projected_points": 24.7,
        }])

provider = FakeProjectionProvider()
week2 = provider.projections(2025, 2)
validate_projection_columns(week2)  # no exception
print(week2)
```

**Verified offline** -- real output:

```text
   season  week          source sleeper_player_id     gsis_id player_name position nfl_team  projected_points
0    2025     2  example-vendor              1000  00-0034857  Josh Allen       QB      BUF              24.7
```

## What's next

[`docs/players-analytics.md`](players-analytics.md) covers everything built
on top of `player_week_df`: player performance metrics, position strength,
lineup efficiency and roster efficiency, replacement-level player value,
matchup player contribution, and manager lineup tendencies -- led by
`PlayerAnalytics`, the Epic 7 analog of `LeagueAnalytics`
([`docs/analytics.md`](analytics.md)) and `MatchupHistory`.
