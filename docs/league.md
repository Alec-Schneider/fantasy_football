# The `league` layer

This is page one of the `fantasy_analyzer` reference. It covers
[`src/fantasy_analyzer/league/`](../src/fantasy_analyzer/league/) only. Later pages
will cover `sleeper/`, `matchups/`, `analytics/`, and `players/`.

## What this layer is for

`league/` turns raw Sleeper API responses (plain dicts and lists of dicts) into
typed, joined, predictable Python objects. It does **no network I/O** except in
the one convenience function that explicitly fetches
([`load_league_snapshot`](../src/fantasy_analyzer/league/snapshot.py#L208)) — every
other function in this package takes already-fetched data and returns a normalized
result, deterministically, with no HTTP calls. That's what makes it unit-testable
offline and safe to call repeatedly.

The object nearly everything downstream consumes is
[`LeagueSnapshot`](../src/fantasy_analyzer/league/snapshot.py#L45): one dataclass
holding a league's settings, its roster-to-owner mapping, its users, its rosters,
and metadata for every player rostered in the league. Build one of these first;
almost every other page in this doc series starts from it.

Conventions used on this page (and later pages should follow):

- Source links point at a specific line in the current `main` (commit `2198f55`
  at time of writing). **Line numbers drift as the code changes** — if a link
  looks wrong, search the module for the symbol name rather than trusting the
  anchor.
- Sleeper IDs (`user_id`, `roster_id`, `league_id`, `player_id`) are always
  strings except `roster_id`, which Sleeper represents as an int. Display
  names and team names are labels only — never join keys.
- "Verified" below means run against real data with `.venv/bin/python`, either
  the offline test fixtures under `tests/fixtures/sleeper/` or (marked
  separately) a live Sleeper league. Nothing here is a guessed shape.

## Quick start: username to a readable snapshot

Put your own Sleeper username, season, and (once you know it) `league_id` where
`YOUR_...` appears below — `schneidbaby` / `2025` is just the case this package
was validated against, not part of the API.

```python
from fantasy_analyzer.sleeper.client import SleeperClient
from fantasy_analyzer.league import load_league_snapshot, derive_season_boundaries

client = SleeperClient()

# 1. Look up your user_id, then list your leagues for a season, to find a
#    league_id. (sleeper/ is next page's topic -- this is the minimum needed
#    to get a league_id.)
user = client.get_user("YOUR_SLEEPER_USERNAME")
leagues = client.get_leagues(user["user_id"], season=2025)
league_id = leagues[0]["league_id"]  # pick the league you actually want

# 2. Build the normalized snapshot in one call.
snapshot = load_league_snapshot(client, league_id)

# 3. Read things off it.
print(snapshot.league.name, snapshot.league.total_rosters)
print(snapshot.teams_df)  # who owns which roster
print(snapshot.roster_positions)  # league's starting lineup shape
print(snapshot.scoring_settings)  # league's actual point values

# 4. Explicit week boundaries for regular season vs. playoffs (18 is the 2025
#    NFL/Sleeper season length -- pass whatever is true for your season).
boundaries = derive_season_boundaries(snapshot.league, total_weeks=18)
print(boundaries.regular_season_weeks, boundaries.playoff_weeks)
```

**Verified live** against the Sleeper API (a real account, not shown above) on
2026-08-26. Real output for that run's `teams_df`:

```text
   roster_id             owner_id    display_name       team_name
0          1  1124895994132406272  callahanmancan  callahanmancan
1          2  1257880184422404096    TaylorDucote    TaylorDucote
2          3  1124901188417331200      hankleeman      hankleeman
3          4   865610532865060864     schneidbaby     schneidbaby
```

and `derive_season_boundaries(..., total_weeks=18)` for that league (a 4-team
league with `playoff_week_start=16`):

```text
SeasonBoundaries(regular_season_weeks=[1, 2, ..., 15], playoff_weeks=[16, 17, 18],
                  playoff_week_start=16, total_weeks=18)
```

That confirms the call sequence works end-to-end against live Sleeper data.
Column contents obviously vary by league — don't treat the values above as
anything but a shape check.

### The same thing, offline (what the tests actually assert)

If you don't want live HTTP (e.g. writing a test, or no network), skip
`load_league_snapshot` and call
[`build_league_snapshot`](../src/fantasy_analyzer/league/snapshot.py#L157)
directly with already-fetched dicts:

```python
from fantasy_analyzer.league import build_league_snapshot

snapshot = build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)
```

Run against `tests/fixtures/sleeper/{league,users,rosters,players}.json`
(2-team toy league), this prints (verified with `.venv/bin/python`):

```text
>>> snapshot.teams_df
   roster_id            owner_id display_name    team_name
0          1  123456789012345678    Test User  The Testers
1          2  223456789012345678   Other User   Other User

>>> snapshot.rosters_df
   roster_id            owner_id  wins  losses  ties     fpts  fpts_against       players starters
0          1  123456789012345678     5       3     0  1050.42        980.15  [1000, 1001]   [1000]
1          2  223456789012345678     4       4     0   975.30        968.88        [1002]   [1002]

>>> snapshot.players_df
  player_id        full_name position team
0      1000  Test Player One       QB  SEA
1      1001              NaN      NaN  NaN
2      1002  Test Player Two       RB   KC
```

(Player `1001` is on roster 1 but not in the fixture's player catalog — see
"Edge cases" below for why that's `NaN` rather than an error.)

## Reference

### `fantasy_analyzer.league` (package exports)

[`__init__.py`](../src/fantasy_analyzer/league/__init__.py) re-exports the
public surface of every module below. Import from the package directly
(`from fantasy_analyzer.league import ...`) rather than reaching into
submodules — the `__all__` list is the contract:

`build_league_snapshot`, `build_team_mapping`, `derive_season_boundaries`,
`is_playoff_week`, `LeagueSettings`, `LeagueSnapshot`, `load_league_snapshot`,
`normalize_league_settings`, `resolve_player`, `resolve_roster_players`,
`SeasonBoundaries`.

### `league/snapshot.py` — the composed object

**[`LeagueSnapshot`](../src/fantasy_analyzer/league/snapshot.py#L45)** —
frozen dataclass, the common input for downstream analytics.

| Attribute | Type | Contents |
|---|---|---|
| `league` | `LeagueSettings` | normalized metadata/scoring/roster rules (see below) |
| `teams_df` | `DataFrame` | one row per roster: `["roster_id", "owner_id", "display_name", "team_name"]` |
| `users_df` | `DataFrame` | one row per league user: `["user_id", "display_name", "team_name"]` |
| `rosters_df` | `DataFrame` | one row per roster: `["roster_id", "owner_id", "wins", "losses", "ties", "fpts", "fpts_against", "players", "starters"]` |
| `players_df` | `DataFrame` | one row per distinct rostered player ID: `["player_id", "full_name", "position", "team"]` |
| `scoring_settings` | `dict[str, float]` | passthrough of `league.scoring_settings` |
| `roster_positions` | `list[str]` | passthrough of `league.roster_positions`, including bench slots |

Notes confirmed by reading and running the code:

- `rosters_df.fpts` / `fpts_against` are Sleeper's split whole/decimal counters
  combined into one float by
  [`_combine_points_setting`](../src/fantasy_analyzer/league/snapshot.py#L98)
  (`whole + decimal/100`). If the whole-number field is entirely absent, the
  result is `None` — a real *missing setting*, distinguished from a real zero.
- `rosters_df.players` / `starters` are Python lists of Sleeper player-ID
  strings (verbatim from Sleeper), not exploded into separate rows.
- `players_df` is deduplicated **league-wide** (across all rosters, in
  first-seen order) — not per-roster. To get one team's roster's player
  metadata, filter `players_df` by the IDs in that team's `rosters_df.players`
  row, or call
  [`resolve_roster_players`](../src/fantasy_analyzer/league/players.py#L69)
  directly on that list.

**[`build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog) -> LeagueSnapshot`](../src/fantasy_analyzer/league/snapshot.py#L157)**
— the pure composition function, no network access. Arguments are exactly the
raw dicts/lists `SleeperClient.get_league`, `.get_users`, `.get_rosters`, and
`.get_players()` (or `get_players_cached`) return.

**[`load_league_snapshot(client, league_id, player_cache_path=DEFAULT_CACHE_PATH, force_refresh_players=False) -> LeagueSnapshot`](../src/fantasy_analyzer/league/snapshot.py#L208)**
— thin wrapper that fetches league, users, and rosters via `client`, loads the
player catalog via
[`get_players_cached`](../src/fantasy_analyzer/sleeper/cache.py#L64) (from
`fantasy_analyzer.sleeper.cache`, cached at `.cache/sleeper/players.json` by
default), and calls `build_league_snapshot`. Prefer `build_league_snapshot`
directly in tests or when you already have the raw data.

### `league/teams.py` — who owns which roster

**[`build_team_mapping(users, rosters) -> DataFrame`](../src/fantasy_analyzer/league/teams.py#L18)**
— joins raw `get_users()` to raw `get_rosters()` on the immutable
`user_id`/`owner_id` pair. Returns columns
`["roster_id", "owner_id", "display_name", "team_name"]` (one row per roster).
`team_name` falls back to `display_name` when the user hasn't set
`metadata.team_name` in Sleeper. This is what backs `LeagueSnapshot.teams_df`.

### `league/settings.py` — league rules and scoring

**[`LeagueSettings`](../src/fantasy_analyzer/league/settings.py#L18)** — frozen
dataclass. Fields: `league_id`, `name`, `season` (string, e.g. `"2025"`),
`season_type`, `status`, `total_rosters`, `scoring_settings` (`dict[str, float]`,
e.g. `{"pass_td": 4, "rec": 0.5}`), `roster_positions` (`list[str]`, includes
`"BN"` bench slots and league-defined slots like `"FLEX"`),
`playoff_week_start`, `playoff_teams`, `waiver_type`, `waiver_budget`,
`trade_deadline`, `draft_id`, `previous_league_id`. Every optional field
defaults to `None` (or `{}`/`[]`) rather than raising when Sleeper's response
omits it.

**[`normalize_league_settings(raw_league) -> LeagueSettings`](../src/fantasy_analyzer/league/settings.py#L61)**
— builds the above from the raw dict returned by `SleeperClient.get_league()`.
This is what backs `LeagueSnapshot.league`.

### `league/players.py` — resolving player IDs to names/positions/teams

**[`resolve_player(player_id, player_catalog) -> dict`](../src/fantasy_analyzer/league/players.py#L28)**
— resolves one Sleeper `player_id` against the raw player catalog dict
(`SleeperClient.get_players()`, keyed by `player_id`). Returns
`{"player_id", "full_name", "position", "team"}`. `full_name` falls back to
`"{first_name} {last_name}"` when the catalog entry has no `full_name` key.
Unresolvable IDs (team-abbreviation defenses like `"BUF"`, or a player missing
from a stale cache) come back with every field but `player_id` set to `None`
— this never raises.

**[`resolve_roster_players(player_ids, player_catalog) -> DataFrame`](../src/fantasy_analyzer/league/players.py#L69)**
— vectorized form of the above: one row per entry in `player_ids`, in the
original order, duplicates preserved. Columns:
`["player_id", "full_name", "position", "team"]`. This is what backs
`LeagueSnapshot.players_df` (called there with the league-wide deduplicated ID
list, not a single roster's list).

### `league/season.py` — regular season vs. playoff weeks

Sleeper does not expose a single "how many weeks is this season" field — it
depends on playoff format and is season-specific. You must supply
`total_weeks` yourself (e.g. `18` for the 2025 NFL/Sleeper season); nothing in
this module assumes a season length.

**[`SeasonBoundaries`](../src/fantasy_analyzer/league/season.py#L25)** — frozen
dataclass: `regular_season_weeks: list[int]`, `playoff_weeks: list[int]`,
`playoff_week_start: Optional[int]`, `total_weeks: int`.

**[`derive_season_boundaries(league_settings, total_weeks) -> SeasonBoundaries`](../src/fantasy_analyzer/league/season.py#L46)**
— weeks `1..playoff_week_start-1` are regular season, weeks
`playoff_week_start..total_weeks` are playoffs. If
`league_settings.playoff_week_start` is `None`, the whole `1..total_weeks`
range is treated as regular season (no playoffs assumed) rather than guessing.

**[`is_playoff_week(week, boundaries) -> bool`](../src/fantasy_analyzer/league/season.py#L99)**
— membership check against `boundaries.playoff_weeks`; `False` for any week
outside `1..total_weeks` too.

## Edge cases worth knowing (from `tests/league/`)

These are covered by tests, not always spelled out in the docstrings:

- **Roster with no owner** (`owner_id is None`, e.g. an unclaimed/orphaned
  team): `teams_df`/`rosters_df` get a row with `owner_id`, `display_name`,
  `wins` etc. all `None` rather than the row being dropped or the call
  raising ([`test_build_league_snapshot_handles_roster_with_no_owner`](../tests/league/test_snapshot.py#L156)).
- **`owner_id` present but not in `users`** (orphaned/left-league owner):
  `display_name`/`team_name` come back `None`; `owner_id` is preserved as-is
  ([`test_build_team_mapping_handles_owner_id_not_in_users`](../tests/league/test_teams.py#L66)).
- **Sparse/empty raw league dict** (e.g. just `{"league_id": "1"}`): every
  `LeagueSnapshot` DataFrame comes back empty-but-correctly-columned, not
  `None` and not a crash
  ([`test_build_league_snapshot_handles_sparse_league_settings`](../tests/league/test_snapshot.py#L177)).
- **A player rostered by more than one team**: appears once in `players_df`,
  in first-seen order across rosters
  ([`test_build_league_snapshot_deduplicates_player_id_shared_across_rosters`](../tests/league/test_snapshot.py#L195)).
- **Display names are not unique**: two users can share a `display_name`;
  `build_team_mapping` still resolves each roster correctly because it joins
  on `user_id`/`owner_id`, never on the name
  ([`test_build_team_mapping_uses_ids_not_names_as_join_key`](../tests/league/test_teams.py#L92)).
- **`playoff_week_start == 1`**: the entire season is playoffs and
  `regular_season_weeks` is `[]` — not an error.
- **`fpts` whole-number field entirely absent** (not just zero): treated as a
  missing setting and reported as `None`, distinct from a real `0`.

## What's next

A `LeagueSnapshot` is the input to the matchup-normalization pipeline
(`fantasy_analyzer.matchups`) and to the league-level analytics
(`fantasy_analyzer.analytics`) — standings, head-to-head, all-play, schedule
luck, consistency, strength of schedule, power rankings, playoff brackets. It
also feeds the player-analytics layer (`fantasy_analyzer.players`), which
consumes `snapshot.scoring_settings` to compute real fantasy points from
nflverse stats rather than a generic provider's point totals. Those layers
are documented on their own pages, not here.
