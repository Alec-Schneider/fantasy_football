# The `free-agents` CLI subcommand (FFA-093)

Usage documentation for `fantasy-analyzer free-agents`, the CLI surface over
the rest-of-season (ROS) waiver-wire ranking pipeline:
[`players/free_agents.py`](../src/fantasy_analyzer/players/free_agents.py)
(FFA-091), [`players/ros_backtest.py`](../src/fantasy_analyzer/players/ros_backtest.py)
(FFA-089), [`players/ros_projection.py`](../src/fantasy_analyzer/players/ros_projection.py)
(FFA-090), and [`players/waiver_rankings.py`](../src/fantasy_analyzer/players/waiver_rankings.py)
(FFA-092), composed in
[`cli.py`](../src/fantasy_analyzer/cli.py) by
`build_free_agent_rankings`/`run_free_agents`.

This is a usage doc, not a methodology writeup -- see each module's own
docstring for how the projection and VORP ranking are computed, and
[`docs/ros-projection-accuracy.md`](ros-projection-accuracy.md) for measured
accuracy of the underlying shrinkage projection (this CLI loads those fitted
`n0` values when they have been persisted -- see below).

## Usage

```bash
fantasy-analyzer free-agents <league_id> --season <year> --week <n> \
    [--position POS] [--top N] [--format text|json]
```

| Argument | Required | Meaning |
|---|---|---|
| `league_id` | yes (positional) | Sleeper `league_id`. |
| `--season` | yes | Season year to score nflverse weekly stats against, e.g. `2026`. |
| `--week` | yes | Cutoff week -- the last completed week. Rest-of-season is projected from after this week. |
| `--position` | no | Filter to one position (e.g. `WR`). Omit for every position. |
| `--top` | no | Number of top-ranked free agents to print, by ascending `waiver_rank` (default `25`). |
| `--format` | no | `text` (a plain-text table with a header line) or `json` (a JSON array of records, via `DataFrame.to_json(orient="records")` -- `NaN`/missing values serialize to `null`, keeping the output valid, parseable JSON). Defaults to `text`. |

No `username` argument -- like `summary`, this subcommand takes a
`league_id` directly (resolve one first with `fantasy-analyzer leagues
<username> --season <year>` if you don't already have it).

Example:

```bash
fantasy-analyzer free-agents 999999999999999999 --season 2026 --week 3 --position RB --top 10
```

## What it prints

A header line (`Free agents -- league <id>, season <season>, through week
<week>[, position <position>]`) followed by the ranking table, sorted by
ascending `waiver_rank` (rank 1 = most points above replacement). Columns
match
[`WAIVER_WIRE_RANKING_COLUMNS`](../src/fantasy_analyzer/players/waiver_rankings.py) --
notably `projected_ppg`, `projected_ros_points`, `points_above_replacement`,
`waiver_rank`, `confidence_tier`, `prior_season_games`, and the
`OPPORTUNITY_SUMMARY_COLUMNS` usage figures (`"low"`/`"medium"`/`"high"`, based on
games played to date -- see that module's docstring).

**Edge cases**, all handled without a crash or an ugly empty-table dump:

- **No free agents at all** (every startable-position player in the catalog
  is rostered): prints `"No free agents found."` instead of an empty table.
- **`--position` with zero matches**: prints `"No free agents found at
  position <POS>."`.
- **A free agent with no Sleeper<->nflverse ID crosswalk match**: still gets
  a row (per FFA-091/092's "don't drop, null" convention), with every
  projection/VORP column `NaN`/`null` rather than being silently excluded.
- **`--week` at or past the season's effective end**
  (`DEFAULT_SEASON_END_WEEK = 17`, from `ros_backtest.py`): `remaining_games`
  clamps to `0` and `projected_ros_points` is `0.0` for everyone -- this
  subcommand does not special-case it further, since `waiver_rankings.py`
  already defines that behavior.

## What the ranking is measured against (Epic 9)

Four composition choices carry most of this subcommand's accuracy. All four
were originally made the other way, and all four were measured on live 2026
week-1 data before being changed -- see `PROGRESS.md`'s Epic 9 section for
the numbers.

**Crosswalk (FFA-097).** Uses `build_robust_id_crosswalk` (the
DynastyProcess union), not the catalog-only `build_id_crosswalk`. The
catalog-only version resolved 111 of 615 NFL-signed free agents in a
12-team league; the union resolves 520. An unresolved free agent gets no
projection at all, so a sparse crosswalk does not degrade a board -- it
removes four fifths of the wire from it. Pass `crosswalk=` to
`build_free_agent_rankings` to reuse one across leagues, or to keep a test
offline.

**Replacement level (FFA-095).** Measured over the whole league, rostered
players included, not over the free-agent pool alone. Over the pool alone
the "last startable RB" was the 36th-best *unrostered* RB at 1.9 ppg
rather than the league's 8.5, which inflated positional VORP and made the
cross-position ordering an artifact of which position had the longer tail
of unrostered junk.

**Prior-season sample size (FFA-096).** `prior_season_ppg` is only trusted
at `DEFAULT_MIN_PRIOR_GAMES = 4` games or more; below that it falls back
to the positional mean -- or, for a player with no games this season
either, to the fitted absent-prior line (FFA-104, below). Since a player
with no games this season has a
blend weight of exactly zero, an untrusted one-game prior would otherwise
*become* his whole projection. The raw value and the new
`prior_season_games` column are still reported, so a board can show the
thin sample rather than hide it.

**Shrinkage parameters (FFA-101).** Loads a fitted `ShrinkageParameters`
from `.cache/nflverse/shrinkage_parameters.json` when one exists, falling
back to the uniform, unfitted `DEFAULT_N0 = 3.0` otherwise. Create the
fitted file once with:

```bash
python scripts/fetch_nflverse_seasons.py --start 2016 --end 2025   # if not already cached
python scripts/fit_shrinkage_parameters.py --start 2016 --end 2025
```

The uniform fallback is directionally reasonable but measurably less
accurate than the validated per-position values (`n0={RB: 2.0, WR: 2.0,
TE: 2.5, QB: 4.0}`) that
[`docs/ros-projection-accuracy.md`](ros-projection-accuracy.md) reports.

**Projection model (FFA-111, FFA-104).** Loads the fitted usage model from
`.cache/nflverse/usage_model_parameters.json` and the season's snap-count
and expected-points caches, and passes them with the league's scoring
settings. `projected_ppg` is then the per-position blend of the
opportunity-first usage model and the shrinkage projection. A player with no
games and no trusted prior gets the fitted absent-prior line, scored in the
league. `projection_model` says which applied per row (`blend`, `eb`,
`absent_prior`). Without the parameter file the ranking is the shrinkage
projection alone, and without the snap caches it uses the no-snap usage
model. Create or refresh them with:

```bash
python scripts/fetch_usage_seasons.py --start 2014 --end 2026   # snap counts + expected points
python scripts/fit_usage_model.py --start 2015 --end 2025
```

See [`docs/valuation-model.md`](valuation-model.md) for the model and its
backtest.

## Context columns beside the ranking

The ranking table now also carries, for every free agent:

- **Season-to-date usage** (FFA-098) --
  `OPPORTUNITY_SUMMARY_COLUMNS`: `targets_per_game`, `carries_per_game`,
  `target_share`, `air_yards_share`, `wopr`, `racr`,
  `air_yards_per_game`, and per-game receiving/rushing/passing EPA. All
  per-game over the observed weeks. These are **descriptive only** and
  feed no projection -- they exist so a reader can tell a one-game spike on
  two targets and a long touchdown from a one-game spike on eleven
  targets. nflverse carries no snap counts at any stage.

Two further layers are available but are *not* applied by this subcommand,
since both need inputs it does not fetch:

- `players/opponent_strength.py` (FFA-099) -- future-week opponent from
  the real NFL schedule, shrunk defense-vs-position, implied team totals,
  bye weeks, and a bye-aware remaining-games count. Note that this
  subcommand's `remaining_games` is a schedule-blind constant for every
  player.
- `players/roster_fit.py` (FFA-100) -- whether an add actually improves a
  specific manager's best starting lineup, whom it displaces, and the
  cheapest player to drop.

## No-network testing

Like the `commentary` subcommand family, `run_free_agents` takes an
injectable `provider`
(`fantasy_analyzer.players.provider.PlayerStatsProvider`) so tests can
supply an in-memory fake instead of the real
`NflverseWeeklyStatsProvider` -- see `tests/test_cli.py`'s
`FakeWeeklyStatsProvider` and the `free-agents` test block for the pattern.
