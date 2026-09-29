# Progress

_Last updated by project-tracker: 2026-08-24 (FFA-074 entry appended and committed 2026-09-01 outside a full project-tracker run — see that entry for details)_

## Current state

Epics 1 through 6 (FFA-001 through FFA-057) are fully shipped and verified against actual code/tests, except **FFA-044** ("Split Regular Season and Playoff H2H"), which remains BACKLOG — the codebase explicitly defers it (see `src/fantasy_analyzer/analytics/head_to_head.py`). Epic 7 has now shipped through FFA-072, plus FFA-069: provider interface (FFA-060), nflverse provider (FFA-061), ID crosswalk (FFA-062), scoring engine (FFA-063), player-week fact table (FFA-064), performance metrics (FFA-065), position strength (FFA-066), optimal lineup / roster efficiency (FFA-067), replacement-level player value (FFA-068), player analytics API (FFA-071), projection/ranking provider interface (FFA-072), and matchup player contribution analysis (FFA-069). FFA-070 ("Manager Lineup Tendencies") has since shipped as `1d6b98b`, and FFA-073 ("League-Wide Composite Player Value Ranking") — a ticket raised by the repo owner after this summary was written, not in the original roadmap — shipped as `570429b`/`32dbcaa`/`6629f59`; both entries are archived below, but the rest of this paragraph predates them and reflects the 2026-08-24 project-tracker run. Two tickets, **FFA-007** and **FFA-014**, have no commit whose message matches their suggested one, but their acceptance criteria are genuinely satisfied — the work was absorbed into the commits for the tickets they support (fixtures landed alongside each endpoint's own commit; normalized-data tests landed alongside FFA-010/011/012/013's own commits) rather than shipped as a separate commit. This run also backfilled the archive entries for FFA-061 through FFA-066, which earlier chore runs compacted out of AGENTS.md without archiving (their original ticket text was recovered verbatim from AGENTS.md git history).

**FFA-074** ("League-Wide Free-Agent Player Pool & ID-Crosswalk Coverage Fix") has since shipped as `cf40276`/`8e357fa`/`7db0ba6`/`4d7f45f` — see its own entry at the end of Epic 7 for the full story. It extends FFA-062 (a new, more complete DynastyProcess-backed crosswalk source alongside the original) and FFA-064 (a new `build_league_wide_player_week_fact_table` alongside the original rostered-only builder) to fix a real ranking-quality bug the repo owner caught by inspection: a depth free agent ranking implausibly high in a first cut of a "top 100" report built on FFA-073.

---

## Epic 1 — Sleeper Client

### FFA-001 — Bootstrap Python Project
**Commit:** `0c2889a` `chore: bootstrap fantasy analyzer project`
**Owner:** Software Engineer

**Scope**

Create the initial Python package.

Suggested structure:

```text
fantasy-football-analyzer/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── src/
│   └── fantasy_analyzer/
│       ├── __init__.py
│       ├── sleeper/
│       ├── league/
│       ├── matchups/
│       ├── analytics/
│       └── players/
└── tests/
```

**Acceptance Criteria**

- package installs locally
- `pytest` runs successfully
- formatting/linting configuration exists
- supported Python version is defined
- `requests` and `pandas` are declared dependencies

---

### FFA-002 — Add Base Sleeper HTTP Client
**Commit:** `e7dcbf5` `feat: add Sleeper API HTTP client`
**Owner:** Software Engineer
**Depends on:** FFA-001

**Scope**

Implement a reusable `SleeperClient`.

Expected capabilities:

```python
SleeperClient
_get()
timeout handling
HTTP error handling
session reuse
```

**Acceptance Criteria**

- successful requests return decoded JSON
- 4xx/5xx responses produce useful exceptions
- timeout behavior is covered by tests
- URL construction is centralized

---

### FFA-003 — Add User and League Discovery
**Commit:** `7f1d689` `feat: add Sleeper user and league discovery`
**Owner:** Software Engineer
**Depends on:** FFA-002

**Scope**

Implement:

```python
get_user()
get_leagues()
```

Expected development workflow:

```python
client.get_user("schneidbaby")
client.get_leagues(user_id=..., season=2025)
```

**Acceptance Criteria**

- username resolves to permanent Sleeper `user_id`
- 2025 leagues can be retrieved
- nonexistent users are handled cleanly
- no downstream code relies on username as an immutable identifier

---

### FFA-004 — Add Core League Endpoints
**Commit:** `a9ef6ec` `feat: add Sleeper league roster and user endpoints`
**Owner:** Software Engineer
**Depends on:** FFA-002

**Scope**

Implement:

```python
get_league()
get_users()
get_rosters()
```

**Acceptance Criteria**

The client can retrieve:

- league metadata
- league rules
- scoring settings
- roster positions
- league users
- rosters

---

### FFA-005 — Add Historical Season Endpoints
**Commit:** `d3db957` `feat: add Sleeper matchup playoff and transaction endpoints`
**Owner:** Software Engineer
**Depends on:** FFA-002

**Scope**

Implement:

```python
get_matchups()
get_winners_bracket()
get_losers_bracket()
get_transactions()
get_drafts()
get_draft_picks()
```

**Acceptance Criteria**

- weekly matchups can be fetched
- playoff brackets can be fetched
- transactions can be fetched
- drafts and draft picks can be fetched
- fixtures cover representative responses

---

### FFA-006 — Add Cached Sleeper Player Catalog
**Commit:** `a33d0d7` `feat: add cached Sleeper player catalog`
**Owner:** Software Engineer
**Depends on:** FFA-002

**Scope**

Implement:

```python
get_players()
load_player_cache()
refresh_player_cache()
```

**Acceptance Criteria**

- Sleeper player catalog can be retrieved
- player catalog can be cached locally
- normal analysis does not require repeatedly downloading the full catalog
- cache behavior is tested

---

### FFA-007 — Add Sleeper API Contract Fixtures
**Commit:** *(no dedicated commit — fixtures for each endpoint were added alongside that endpoint's own commit: `e7dcbf5`, `7f1d689`, `a9ef6ec`, `a33d0d7`, `d3db957`)*
**Owner:** Software Engineer
**Depends on:** FFA-003, FFA-004, FFA-005, FFA-006

**Verification note:** No commit message matches `test: add Sleeper API contract fixtures`. Verified by hand instead: `tests/fixtures/sleeper/` contains sanitized fixtures for every endpoint (`user.json`, `leagues.json`, `league.json`, `rosters.json`, `users.json`, `matchups.json`, `winners_bracket.json`, `losers_bracket.json`, `transactions.json`, `drafts.json`, `draft_picks.json`, `players.json`); `tests/sleeper/test_client.py` exercises every client method exclusively via `requests_mock` against these fixtures; the full suite (406 tests) passes with no network access (`python -m pytest -q`); fixture usernames/ids (`testuser`, `123456789012345678`, etc.) are synthetic, not real personal data. Acceptance criteria genuinely satisfied.

**Scope**

Create sanitized representative API fixtures.

**Acceptance Criteria**

- main test suite runs without internet access
- public API parsing behavior is covered by fixtures
- no private or unnecessary personal information is committed

---

## Epic 2 — Normalize League Data

### FFA-010 — Build Team and Owner Mapping
**Commit:** `bf0bf79` `feat: normalize Sleeper owners and rosters`
**Owner:** Software Engineer
**Depends on:** FFA-004

**Scope**

Create stable mappings between:

```text
user_id
roster_id
display_name
team_name
```

**Acceptance Criteria**

- each roster can resolve to its owner when available
- missing owners are handled
- display/team names remain labels, not keys

---

### FFA-011 — Normalize League Settings
**Commit:** `ef3340e` `feat: normalize league scoring and roster settings`
**Owner:** Software Engineer
**Depends on:** FFA-004

**Scope**

Normalize:

- scoring settings
- roster slots
- league size
- playoff configuration
- waiver configuration
- season metadata

**Acceptance Criteria**

- downstream code does not need to understand raw Sleeper setting shapes
- scoring and roster settings are available in predictable structures

---

### FFA-012 — Normalize Player Metadata
**Commit:** `63d40df` `feat: enrich rosters with Sleeper player metadata`
**Owner:** Software Engineer
**Depends on:** FFA-006

**Scope**

Convert raw Sleeper player IDs into useful player metadata.

Example:

```text
4984 -> Josh Allen | QB | BUF | 4984
```

**Acceptance Criteria**

- roster player IDs resolve to metadata when available
- unknown or retired player IDs do not crash normalization

---

### FFA-013 — Build LeagueSnapshot Service
**Commit:** `e5e5428` `feat: add LeagueSnapshot service`
**Owner:** Software Engineer
**Depends on:** FFA-010, FFA-011, FFA-012

**Scope**

Create the normalized league representation used by downstream analysis.

Expected interface:

```python
snapshot.league
snapshot.teams_df
snapshot.users_df
snapshot.rosters_df
snapshot.players_df
snapshot.scoring_settings
snapshot.roster_positions
```

**Acceptance Criteria**

- one call can construct a normalized league snapshot
- downstream analytics do not need raw endpoint joins
- snapshot construction is tested from fixtures

---

### FFA-014 — Add Normalized Data Tests
**Commit:** *(no dedicated commit — coverage was added alongside `bf0bf79`, `ef3340e`, `63d40df`, `e5e5428`, and extended further in `f1e4ce1`)*
**Owner:** Software Engineer
**Depends on:** FFA-013

**Verification note:** No commit message matches `test: add normalized league data coverage`. Verified by hand instead: `tests/league/test_teams.py` covers owner/roster mapping including missing-owner and owner-id-not-in-users cases; `tests/league/test_settings.py` covers scoring normalization; `tests/league/test_players.py` and `tests/league/test_snapshot.py` cover missing/unknown player cases; `tests/league/test_snapshot.py` explicitly asserts the normalized schema (exact column lists) for `teams_df`, `users_df`, `rosters_df`, `players_df`. Acceptance criteria genuinely satisfied.

**Acceptance Criteria**

- owner/roster mapping tested
- scoring normalization tested
- missing owner/player cases tested
- normalized schemas tested

---

## Epic 3 — League Summary

### FFA-020 — Build Base Standings
**Commit:** `f1e4ce1` `feat: add league standings analysis`
**Owner:** Data Scientist
**Depends on:** FFA-013

**Metrics**

- wins
- losses
- ties
- win percentage
- points for
- points against
- point differential

**Acceptance Criteria**

- standings reconcile to Sleeper roster records
- ties are handled
- ranking rules are documented

---

### FFA-021 — Add Scoring Summary Metrics
**Commit:** `069c82c` `feat: add league scoring summary metrics`
**Owner:** Data Scientist
**Depends on:** FFA-020

**Metrics**

- points per game
- points against per game
- scoring rank
- average margin
- high score
- low score

---

### FFA-022 — Identify Regular Season and Playoff Boundaries
**Commit:** `3423eef` `feat: derive regular season and playoff boundaries`
**Owner:** Software Engineer
**Depends on:** FFA-011

**Acceptance Criteria**

- regular-season weeks are explicit
- playoff weeks are explicit
- downstream analytics can filter either period reliably

---

### FFA-023 — Build League Summary API
**Commit:** `b0afc8a` `feat: add league summary service`
**Owner:** Software Engineer
**Depends on:** FFA-020, FFA-021, FFA-022

Expected interface:

```python
analysis.league_summary()
analysis.standings()
```

---

### FFA-024 — Add CLI League Summary
**Commit:** `ac37952` `feat: add CLI league summary`
**Owner:** Software Engineer
**Depends on:** FFA-023

**Goal**

Allow a simple local command to inspect a 2025 league before any UI exists.

---

## Epic 4 — Normalize Matchups

### FFA-030 — Load Full Season Matchups
**Commit:** `ecb0182` `feat: load full season of Sleeper matchups`
**Owner:** Software Engineer
**Depends on:** FFA-005, FFA-022

**Acceptance Criteria**

- all relevant 2025 weeks can be loaded
- week metadata is retained
- playoff status is retained

---

### FFA-031 — Pair Opponents by Matchup ID
**Commit:** `0522af8` `feat: pair weekly opponents by matchup id`
**Owner:** Software Engineer
**Depends on:** FFA-030

**Acceptance Criteria**

- two teams sharing a matchup ID are paired
- incomplete/bye-like cases are handled explicitly
- pairing logic is unit tested

---

### FFA-032 — Normalize Matchup Outcomes
**Commit:** `00dba42` `feat: normalize fantasy matchup outcomes`
**Owner:** Data Scientist
**Depends on:** FFA-031

**Derive**

- winner
- loser
- tie
- margin
- score differential

---

### FFA-033 — Build Season Matchup DataFrame
**Commit:** `d4b9d4e` `feat: build season matchup dataframe`
**Owner:** Data Scientist
**Depends on:** FFA-032

**Target Schema**

```text
season
week
is_playoff
matchup_id
roster_1_id
roster_2_id
owner_1
owner_2
points_1
points_2
winner
loser
margin
```

---

### FFA-034 — Reconcile Matchups to Standings
**Commit:** `c718115` `test: reconcile weekly matchups to season standings`
**Owner:** Software Engineer
**Depends on:** FFA-033

**Acceptance Criteria**

Derived:

- wins
- losses
- points for
- points against

must reconcile to Sleeper season records within explicitly documented tolerances.

---

## Epic 5 — User-vs-User Matchup Analytics

### FFA-040 — Head-to-Head Records
**Commit:** `ea5307f` `feat: add manager head-to-head records`
**Owner:** Data Scientist
**Depends on:** FFA-033

**Metrics**

- meetings
- wins
- losses
- ties
- total points
- average points
- average opponent points

---

### FFA-041 — Head-to-Head Matrix
**Commit:** `429e512` `feat: add league head-to-head matrix`
**Owner:** Data Scientist
**Depends on:** FFA-040

Example output:

```text
        Alec   Mike   Joe
Alec      —     3-2   2-0
Mike     2-3     —    1-2
Joe      0-2    2-1    —
```

---

### FFA-042 — Rivalry and Margin Statistics
**Commit:** `ecedc16` `feat: add rivalry and matchup margin metrics`
**Owner:** Data Scientist
**Depends on:** FFA-040

**Metrics**

- average margin
- closest game
- largest win
- largest loss
- highest scoring matchup

---

### FFA-043 — Add Matchup History Query API
**Commit:** `610a9e4` `feat: add matchup history query service`
**Owner:** Software Engineer
**Depends on:** FFA-040, FFA-041, FFA-042

Expected interface:

```python
analysis.head_to_head(team_a, team_b)
analysis.head_to_head_matrix()
```

---

### FFA-044 — Split Regular Season and Playoff H2H
**Commit:** `99ecf96` `feat: split head-to-head results by season phase`
**Owner:** Data Scientist
**Depends on:** FFA-022, FFA-040

**Verification note:** `build_head_to_head_records` (FFA-040,
`src/fantasy_analyzer/analytics/head_to_head.py`) is unchanged: it still
applies no `is_playoff` filter of its own, preserving the FFA-040-through-
FFA-054 "caller filters `season_matchup_df` before calling" convention.
FFA-044 instead adds the phase split as a layer above it, in
`MatchupHistory` (FFA-043, `src/fantasy_analyzer/analytics/matchup_history.py`):
two new precomputed attributes, `regular_season_head_to_head_df` and
`playoff_head_to_head_df`, each built in `__post_init__` by pre-filtering
`season_matchup_df` on `is_playoff` and calling the unmodified
`build_head_to_head_records` against that slice, plus a new
`head_to_head_by_phase(team_a, team_b)` lookup mirroring `head_to_head`'s
shape. It returns a new frozen `HeadToHeadByPhase(roster_id,
opponent_roster_id, regular_season, playoffs)` dataclass, where each of
`regular_season`/`playoffs` is an `Optional[HeadToHeadPhaseRecord]` — a new,
smaller dataclass carrying only FFA-040's record fields (meetings, wins,
losses, ties, points), deliberately without FFA-042's rivalry statistics
(`scored_meetings`, `avg_margin`, extremum games), since the ticket asks
only about the head-to-head record and a phase-aware rivalry view was
judged out of scope. Either phase field is `None` if the pair never met in
that phase (not a zero-meetings record); the whole lookup returns `None`
only if the pair never met in *either* phase, matching `head_to_head`'s own
never-met `None`. The existing combined `head_to_head`/`head_to_head_df`/
`rivalry_df`/`head_to_head_matrix` behavior is untouched and re-tested for
regression. FFA-041 (matrix) and FFA-042 (rivalries) were not given
phase-aware counterparts — out of scope per the ticket, which named only
head-to-head. 15 new tests in `tests/analytics/test_matchup_history.py`,
including a hand-built toy season with known regular-season-only,
playoff-only, and both-phase pairings (verified by hand arithmetic in the
test docstring), a tie within a phase, a missing-points meeting within a
phase (counted toward `meetings`, not toward wins/losses/points), a playoff
bye row excluded from the playoff pairing scan, unmapped-owner handling,
directional mirroring, and empty/all-bye-season edge cases; full suite
passes (625 tests) and `ruff check`/`ruff format --check` are clean on
every file touched.

---

## Epic 6 — Advanced League Analytics

### FFA-050 — Weekly Scoring Ranks
**Commit:** `778a56b` `feat: add weekly scoring ranks`
**Owner:** Data Scientist
**Depends on:** FFA-033

---

### FFA-051 — All-Play Records
**Commit:** `4fe92e9` `feat: add all-play standings`
**Owner:** Data Scientist
**Depends on:** FFA-050

For each week, calculate how a team would have performed against every other team.

---

### FFA-052 — Expected Wins and Schedule Luck
**Commit:** `c30aa36` `feat: add expected wins and schedule luck`
**Owner:** Data Scientist
**Depends on:** FFA-051

**Example**

```text
Actual Record:     8-6
Expected Record:  10.0-4.0
Schedule Luck:    -2.0 wins
```

The exact expected-wins formulation must be documented and tested.

---

### FFA-053 — Team Consistency Metrics
**Commit:** `caefabc` `feat: add team consistency metrics`
**Owner:** Data Scientist
**Depends on:** FFA-050

Potential metrics:

- weekly standard deviation
- coefficient of variation where appropriate
- median score
- scoring floor
- scoring ceiling
- boom/bust frequency

---

### FFA-054 — Strength of Schedule
**Commit:** `df35d07` `feat: add strength of schedule metrics`
**Owner:** Data Scientist
**Depends on:** FFA-033

Definitions must be documented before implementation.

---

### FFA-055 — Normalize Playoff Bracket and Final Placements
**Commit:** `5b5acd1` `feat: normalize playoff bracket and final placements`
**Owner:** Software Engineer
**Depends on:** FFA-005

---

### FFA-056 — League Power Ranking Model
**Commit:** `d2d9718` `feat: add league power ranking model`
**Owner:** Data Scientist
**Depends on:** FFA-050, FFA-051, FFA-052, FFA-053, FFA-054, FFA-055

Do not build an opaque score.

The model must document:

- included features
- weights or estimation method
- scaling
- tie-breaking
- interpretation

---

### FFA-057 — Advanced League Analytics API
**Commit:** `f134398` `feat: expose advanced league analytics`
**Owner:** Software Engineer
**Depends on:** FFA-051 through FFA-056

Expected interfaces may include:

```python
analysis.all_play()
analysis.schedule_luck()
analysis.consistency()
analysis.strength_of_schedule()
analysis.power_rankings()
```

---

## Epic 7 — Advanced Player / Position Analytics

### FFA-060 — Define Player Data Provider Interface
**Commit:** `098cff1` `feat: define player data provider interface`
**Owner:** Software Engineer
**Depends on:** FFA-012

**Goal**

Prevent the analytics layer from depending directly on nflverse or any other single provider.

---

### FFA-061 — Add nflverse Weekly Stat Provider
**Commit:** `635eff8` `feat: add nflverse weekly player stats provider`
**Owner:** Data Engineer
**Depends on:** FFA-060

**Suggested commit:** `feat: add nflverse weekly player stats provider`

**Verification note:** The original AGENTS.md ticket block carried no Scope or Acceptance Criteria text beyond the suggested commit. Verified against code instead: `src/fantasy_analyzer/players/nflverse_provider.py` provides `NflverseWeeklyStatsProvider`, satisfying the FFA-060 `PlayerStatsProvider` protocol and backed by nflverse's cumulative `player_stats.csv.gz` release asset via a disk-cache layer (`nflverse_cache.py`) mirroring `sleeper/cache.py`; `tests/players/test_nflverse_provider.py` runs against the sanitized fixture `tests/fixtures/nflverse/player_stats.csv` with no network access. (This commit also created PROGRESS.md and archived FFA-001 through FFA-060.)

---

### FFA-062 — Build Sleeper to nflverse Player ID Crosswalk
**Commit:** `85058c4` `feat: map Sleeper player ids to nflverse ids`
**Owner:** Data Engineer
**Depends on:** FFA-061

**Verification note:** `src/fantasy_analyzer/players/crosswalk.py` builds the `(sleeper_player_id, gsis_id)` mapping by extracting the `gsis_id` field native to Sleeper's own player catalog — it never inspects name/position/team, so the ticket's "prefer explicit ID mappings over fuzzy name matching" constraint holds by construction.

**Scope**

Prefer explicit ID mappings over fuzzy name matching.

---

### FFA-063 — Build League-Specific Fantasy Scoring Engine
**Commit:** `2513d33` `feat: calculate fantasy points from league scoring rules`
**Owner:** Data Scientist
**Depends on:** FFA-011, FFA-061

**Verification note:** `src/fantasy_analyzer/players/scoring.py` derives `fantasy_points` from the league's actual Sleeper `scoring_settings` and surfaces unsupported scoring keys via `ScoringResult.unsupported_scoring_keys` rather than silently producing wrong points.

**Acceptance Criteria**

- scoring is derived from the actual league configuration
- representative scoring categories are tested
- unsupported scoring fields are surfaced clearly

---

### FFA-064 — Build Player-Week Fact Table
**Commit:** `a106cf9` `feat: build player-week fantasy fact table`
**Owner:** Data Engineer
**Depends on:** FFA-062, FFA-063

**Verification note:** `src/fantasy_analyzer/players/player_week.py` produces `PlayerWeekFactTable` with `PLAYER_WEEK_COLUMNS` — `season`, `week`, `roster_id`, `fantasy_team`, `sleeper_player_id`, `gsis_id`, `player_name`, `position`, `nfl_team`, `started`, `bench` — followed by the provider's raw stat columns and a final `fantasy_points` column. The fact table has **no `is_playoff` column**; phase filtering is the caller's job (see FFA-065/066/067 verification notes).

**Scope**

This becomes the foundation for all player analytics.

---

### FFA-065 — Player Performance Metrics
**Commit:** `60e6c9d` `feat: add player performance analytics`
**Owner:** Data Scientist
**Depends on:** FFA-064

**Verification note:** `src/fantasy_analyzer/players/performance.py` implements the ticket's metrics as one row per player-season describing the shape of the player's weekly scoring distribution. It is phase-agnostic — `player_week_df` (FFA-064's output) has no `is_playoff` column, so callers pre-filter by week for phase-specific views (documented in the module docstring).

**Metrics**

- weekly fantasy points
- points per game
- median score
- volatility
- ceiling
- floor
- boom rate
- bust rate

---

### FFA-066 — Position Strength Analytics
**Commit:** `0774b17` `feat: add positional strength analytics`
**Owner:** Data Scientist
**Depends on:** FFA-065

**Verification note:** `src/fantasy_analyzer/players/position_strength.py` implements the ticket's metrics as one row per `(season, fantasy_team, position)`. Phase-agnostic like FFA-065 (the fact table has no `is_playoff` column; callers filter by week first).

**Analyze**

- QB production
- RB production
- WR production
- TE production
- positional league rank
- share of roster scoring
- positional depth
- positional consistency

---

### FFA-067 — Optimal Lineup and Roster Efficiency
**Commit:** `e619eb7` `feat: add optimal lineup and roster efficiency`
**Owner:** Data Scientist
**Depends on:** FFA-064

**Verification note:** Implemented in `src/fantasy_analyzer/players/lineup_efficiency.py` (`build_lineup_efficiency_metrics` / `build_roster_efficiency_metrics`) with 19 new tests in `tests/players/test_lineup_efficiency.py`; full suite passes (548 tests) and `ruff check src tests` is clean. The optimal-lineup problem (assign rostered players to the league's slots, each player at most once, maximizing points, FLEX/SuperFlex eligibility) is solved exactly by a dynamic program over per-position count vectors — because every player has exactly one position the objective separates, so feasibility is tracked by the DP and each count vector's value is the sum of its positions' top-k scores. Ties break deterministically toward the manager's actual lineup, so a tie is never counted as a mistake; `NaN` fantasy points count as `0.0`; players with missing positions are ineligible for the optimal lineup. The module is phase-agnostic: the FFA-064 fact table has no `is_playoff` column (the same situation `performance.py` and `position_strength.py` document), so callers pre-filter by week for phase-specific views. Discrepancy check: the FFA-067 ticket text in AGENTS.md (current and historical) never claimed the fact table has an `is_playoff` column — the only `is_playoff` in AGENTS.md is the Canonical Matchup Dataset schema, a different table — so the module's phase-agnostic behavior is consistent with the ticket as written.

**Scope**

The optimizer must respect league roster-position rules.

**Metrics**

- actual starter score
- optimal legal lineup score
- points left on bench
- lineup efficiency percentage
- frequency of suboptimal start/sit decisions

---

### FFA-068 — Replacement-Level Player Value
**Commit:** `eff25d7` `feat: add replacement-level player value` (hardened by `b18c5e0`)
**Owner:** Data Scientist
**Depends on:** FFA-065

**Verification note:** Implemented in `src/fantasy_analyzer/players/player_value.py` (`build_player_value_metrics` / `build_position_scarcity_metrics`) with 28 tests in `tests/players/test_player_value.py`; full suite passes (576 tests) and `ruff check src tests` is clean. Replacement level at a position is the `points_per_game` of the player at the league's starter cutoff per `(season, position)`: cutoff = `num_teams` × starting slots eligible for the position, flex slots counted at every eligible position (via FFA-067's `START_SLOT_ELIGIBILITY` plus Sleeper's IDP slot labels), clamped to the worst rostered player when the field is smaller or the league has no starting slots there — the clamp is a documented heuristic, not a bound (VORP can be overstated when a better free agent exists). Outputs: points above positional average (rate and total), points above replacement (rate and season VORP), `value_rank` (standard competition "1224" across positions within the season, ties judged on the VORP rounded to six decimals), and per-position scarcity (`position_starters`, `replacement_rank`, `best_ppg`, `replacement_ppg`, `ppg_gap_to_replacement`, `scarcity_ratio`). The post-review hardening commit `b18c5e0` fixed findings verified by execution: `num_teams=None`/float coercion, IDP slot eligibility, duplicate `(season, sleeper_player_id)` rows and missing required columns now raise `ValueError`, fractional `games_played` preserved verbatim, empty-string identity treated as missing, empty-frame dtypes matching the documented contract, `None` labels preserved, and float-noise tie ranking.

**Possible outputs**

- points above positional average
- points above replacement
- positional scarcity
- league-relative player value

---

### FFA-071 — Player Analytics API
**Commit:** `6771979` `feat: expose player and positional analytics`
**Owner:** Software Engineer
**Depends on:** FFA-065 through FFA-070 (FFA-069/FFA-070 still BACKLOG; every expected frame came from the DONE subset FFA-065–FFA-068)

**Verification note:** Implemented in `src/fantasy_analyzer/players/player_analytics.py` — a frozen `PlayerAnalytics` dataclass plus a pure `build_player_analytics(...)` factory, mirroring `analytics/league_analytics.py`'s FFA-057 shape (no network access, no new metrics, callers build the player-week fact table first). Takes `player_week_df` (FFA-064), `roster_positions`/`num_teams` (league structure, not a `LeagueSnapshot`), and per-module boom/bust thresholds as constructor fields (frames are attributes, not methods, so thresholds can't be per-call arguments). Exposes seven frames: the five the ticket lists (`player_weekly_df`, `player_season_df`, `position_summary_df`, `roster_efficiency_df`, `player_value_df`) plus two extras that are the second output of dependencies that produce two (`lineup_efficiency_df`, `position_scarcity_df`), following the `playoff_brackets()`/`final_placements()` precedent. `player_season_df` is computed once at construction (reused by the two FFA-068 frames); every other frame is a lazy, unmemoized passthrough. Phase-agnostic and scoped to one league-season, inherited unchanged from its inputs. 24 new tests in `tests/players/test_player_analytics.py` (composition equality, argument passthrough, a hand-computed lineup-efficiency toy example, empty input, `num_teams=None`, missing values, tied VORP ranks, negative-threshold edge cases); full suite passes (600 tests) and `ruff check src tests` is clean. FFA-069/FFA-070 frames are explicitly not exposed yet — no placeholders were added; unblocks FFA-072.

Expected DataFrames:

```python
analysis.player_weekly_df
analysis.player_season_df
analysis.position_summary_df
analysis.roster_efficiency_df
analysis.player_value_df
```

---

### FFA-072 — Projection and Ranking Provider Interface
**Commit:** `7d314af` `feat: add projection and ranking provider interface`
**Owner:** Data Engineer
**Depends on:** FFA-071

**Verification note:** Implemented in `src/fantasy_analyzer/players/projections.py`, the FFA-072 analog of FFA-060's `provider.py`: a `@runtime_checkable` `Protocol` (`ProjectionProvider`, not `abc.ABC`, for the same cross-role/no-inheritance reasons documented in `provider.py`) exposing one method, `projections(season, week) -> pd.DataFrame`, mirroring `weekly_stats(season, week)`'s per-week scope. `PROJECTION_IDENTITY_COLUMNS` requires `season`, `week`, `source`, `sleeper_player_id`, `gsis_id`, `player_name`, `position`, `nfl_team` as an ordered prefix — one column beyond `PLAYER_WEEK_IDENTITY_COLUMNS`: `source`, added because (unlike an observed stat) a projection is inherently one vendor/methodology's opinion, so multiple providers' rows need to coexist without colliding on `(season, week, sleeper_player_id)`. No projection-value column (e.g. `projected_points`) is required, matching FFA-060's exclusion of stat columns, per the ticket's "do not implement vendor-specific logic" instruction. `validate_projection_columns(df)` mirrors `validate_player_week_columns`. The module defines only the single per-week projection lookup; it does not implement ROS rankings, waiver recommendations, trade values, start/sit recommendations, or opponent-adjustment methodology — the module docstring documents, without implementing, how each of those five would consume `projections()` output in a future ticket (e.g. ROS rankings would call `projections()` across remaining weeks and aggregate; opponent adjustments could ride on an optional, unconstrained provider-specific column). Missing-value and empty-result conventions (an unpublished season/week returns an empty, correctly-columned DataFrame; `sleeper_player_id`/`gsis_id` may be `None` per row; a player with no projection has no row, not a sentinel row) mirror FFA-060 exactly. 10 new tests in `tests/players/test_projections.py` (protocol conformance via a plain `FakeProjectionProvider` with no inheritance, week filtering, required-columns-present, missing `sleeper_player_id`, empty-result shape, no-row-for-unprojected-player, the `source` column, and `validate_projection_columns`'s accept/reject behavior including out-of-order and missing-column cases); full suite passes (610 tests) and `ruff check src tests` is clean. No network access anywhere in the module or its tests. Nothing on the current kanban board lists FFA-072 as a dependency, so completing it does not unblock any other ticket; FFA-044, FFA-069, and FFA-070 remain the unblocked-on-paper BACKLOG tickets.

**Goal**

Enable future:

- projections
- rest-of-season rankings
- waiver recommendations
- trade values
- start/sit recommendations
- opponent adjustments

Do not implement vendor-specific logic until the interface is stable.

---

### FFA-069 — Matchup Player Contribution Analysis
**Commit:** `3289bb0` `feat: add player matchup contribution analysis`
**Owner:** Data Scientist
**Depends on:** FFA-033, FFA-064

**Verification note:** Implemented in `src/fantasy_analyzer/players/matchup_contribution.py` — three functions joining FFA-033's `season_matchup_df` with FFA-064's `player_week_df` on `(season, week, roster_id)`, scoped to started players in paired (non-bye) matchups only. `build_matchup_player_contributions` returns one row per started player per roster-week: `fantasy_points` is used directly as the player's contribution to his own roster's signed margin (exact by linearity, since `margin = sum(own started points) - sum(opponent started points)`), plus `share_of_team_points` (`fantasy_points / team_points`, where `team_points` is Sleeper's own recorded `points_1`/`points_2`, not a re-sum), the roster's opponent/result/signed `margin`, and `contribution_rank` (standard competition ranking within the roster-week by descending `fantasy_points`, ties broken by ascending `sleeper_player_id`) — the module's answer to "best/worst starters" and "who drove a win or loss" (filter `contribution_rank == 1` and read `result`), deliberately without pulling in a season-average baseline from FFA-065/068 since FFA-069's stated dependencies are FFA-033/FFA-064 only. `build_positional_matchup_advantage` returns one row per `(season, week, roster_id, position)`, using each started player's own `player_week_df.position` (not the roster slot — FLEX attribution is explicitly out of scope), over the *union* of positions started by either side that week (so a team that started nobody at a position still gets a zero row if its opponent did) — `own_points - opponent_points = positional_advantage`, which sums back to the roster-week's own `margin` across every resolvable-position row. `reconcile_matchup_points` is the ticket-requested internal consistency check (mirroring `matchups/reconciliation.py`'s tolerance pattern, `MATCHUP_POINTS_TOLERANCE = 1e-6`): compares Sleeper's recorded `points_1`/`points_2` against the summed started `fantasy_points` from `player_week_df` per roster-week, and documents — rather than hides — that a mismatch is a real, expected possibility (unsupported scoring keys, provider data gaps, or a roster-week never loaded into `player_week_df` at all, which reports `started_points = NaN`/`points_match = False` rather than assuming zero) since the two sides are independently computed, not two views of the same Sleeper counters. All three functions are phase-agnostic (no `is_playoff` filter, matching `power_rankings.py`'s documented convention) and exclude bye rows entirely (matching `head_to_head.py`'s convention). 23 new tests in `tests/players/test_matchup_contribution.py` (a hand-computed toy example spanning a decisive win/loss, a tie, and a bye; tied contribution ranks; missing/NaN `fantasy_points`; duplicate player ids; an incomplete matchup with missing points; missing `position`; a roster-week absent from `player_week_df` entirely; and reconciliation match/mismatch/custom-tolerance cases); full suite passes (633 tests) and `ruff check`/`ruff format --check` are clean on the new files. Exported from `src/fantasy_analyzer/players/__init__.py`. Not yet wired into `PlayerAnalytics` (FFA-071) — that module's docstring already documents it will add an accessor "in exactly the same shape as the others" when this ticket lands; doing so here would be out of this ticket's scope.

**Analyze**

- which players drove a win or loss
- positional advantages
- player contribution to margin
- best and worst starters

---

### FFA-070 — Manager Lineup Tendencies
**Commit:** `1d6b98b` `feat: add manager lineup tendency analytics`
**Owner:** Data Scientist
**Depends on:** FFA-067

**Verification note:** Implemented in `src/fantasy_analyzer/players/lineup_tendencies.py` with 26 new tests in `tests/players/test_lineup_tendencies.py`; full suite passes (636 tests) and `ruff check src tests` is clean. Five of the ticket's six "Analyze" bullets are implemented as one row per `(season, fantasy_team, position)` (matching `position_strength.py`'s grain): `build_roster_construction_metrics` (distinct players and rostered player-weeks per position, and each position's share of the team's total rostered player-weeks), `build_bench_allocation_metrics` (benched player-weeks per position and their team-season share; a position never benched gets no row), `build_flex_usage_metrics` (which position most often filled a FLEX-type slot in the manager's **actual** lineup — computed in closed form as the season sum of `max(0, started_count(position) - fixed_slot_count(position))` per week, rather than reusing FFA-067's optimizer, because `player_week_df` never carries a per-player slot label so there is no "actual slot assignment" to recover and this question does not need the optimizer's search; includes a standard-competition `flex_usage_rank` within each manager-season), and `build_positional_preference_metrics` (a rollup combining roster-construction, start, and bench counts/shares for one manager-season view, computed as one shared accumulation rather than three separately-merged frames to guarantee a complete, consistent position universe). The fifth, `build_start_sit_tendency_metrics`, is a thin wrapper over FFA-067's `build_roster_efficiency_metrics` (every column unchanged) plus two derived rate columns (`suboptimal_starts_per_week`, `suboptimal_sits_per_week`); it deliberately does not attempt a per-position wrong-start/wrong-sit breakdown, since FFA-067's optimizer does not expose which position each suboptimal decision belongs to and reconstructing that would be a materially larger extension of FFA-067 itself, out of this ticket's scope. All five are phase-agnostic (the FFA-064 fact table has no `is_playoff` column; callers filter by week first), matching every sibling FFA-06x module.

**Scope decision — waiver-player utilization:** investigated and deliberately **not implemented**. `SleeperClient.get_transactions(league_id, week)` exists in `src/fantasy_analyzer/sleeper/client.py` and is tested against a fixture, but nothing in `src/` normalizes its output — a repo-wide search for "transaction" outside that client method and its own test/fixture found nothing. Building a usable "acquisition method per rostered player-week" dataset needs fetching transactions per week for a whole season (unlike this package's other single-shot endpoint wrappers), reconciling three transaction types' `adds`/`drops` against roster history, resolving draft-day baseline state via `get_draft_picks` (a second new data source), and designing a caching strategy and canonical schema for a genuinely new dataset — Data/Software Engineer-owned data-access work, not a Data Scientist composition on top of already-normalized data, per AGENTS.md's role split. The module docstring documents this reasoning in full and specifies what a follow-up ticket would need.

**Analyze**

- FLEX usage
- roster construction
- bench allocation
- start/sit tendencies
- waiver-player utilization (scoped out — see verification note)
- positional preferences

---

### FFA-073 — League-Wide Composite Player Value Ranking
**Commits:** `570429b` `feat(players): add league-wide composite player value ranking`, `32dbcaa` `refactor(players): cap the collinear value+rate weight at half the blend`, `6629f59` `feat(players): expose the FFA-073 ranking frame on PlayerAnalytics`
**Owner:** Data Scientist
**Depends on:** FFA-065, FFA-068, FFA-072

**Origin:** Not in the original AGENTS.md roadmap. Raised directly by the repo owner ("a league wide ranking of each player based on their stats and position and relative value"), scoped in-session, and filed as FFA-073 — the next free number after FFA-072.

**Verification note:** Implemented in `src/fantasy_analyzer/players/player_rankings.py` (~1040 lines, ~470 of them the specification docstring, per this repo's docstring-is-the-spec convention). The module exists because FFA-068's `value_rank` is already a league-wide cross-position ranking but on a **single** signal — season `points_above_replacement` — which makes it purely volume-driven: a 17-game compiler outranks a 9-game elite producer, a metronome ties a boom/bust player at equal totals, and a 2-game sample is unregularized. `build_league_player_rankings(performance_df, roster_positions, num_teams, *, mode, weights, rate_shrinkage_games, projections_df)` blends five components, each z-scored **within season across all positions** using the population stdev (`ddof = 0`, matching `consistency.py`/`performance.py`): `z_value` = z(`points_above_replacement`), `z_rate` = z(shrunk `ppg_above_replacement`), `z_reliability` = z(`-cv`), `z_upside` = z(`scoring_ceiling - replacement_ppg`), and `z_scarcity` = z(`scarcity_ratio`) broadcast from the position's row. `ranking_score = sum(w_c * z_c) / sum(w_c)`. Cross-position pooling is legal because four of the five components are already replacement-relative and the fifth (`cv`) is normalized by the player's own scoring level; the module never pools raw `points_per_game`. It **recomputes nothing** — it calls FFA-068's `build_player_value_metrics` and `build_position_scarcity_metrics` and reads their output, the same way FFA-068 reads FFA-065's.

**Small-sample handling:** `shrunk_ppg_above_replacement = n * ppg_above_replacement / (n + k)`, `k = DEFAULT_RATE_SHRINKAGE_GAMES = 4.0`, shrinking toward zero (= replacement level, the right prior for a barely-observed player) so a 2-game `+10.0` flash lands at `3.33`. `k = 0` degenerates to the raw rate exactly. This replaces an arbitrary `min_games` cutoff: nobody is excluded, but a tiny sample cannot dominate.

**Missing components are dropped and the surviving weights renormalized to 1.0**, never zero-filled — `0.0` on a z-scale asserts "exactly league average", a measurement nobody made. `components_used` reports how many of the five entered each score. A zero-variance pool (or fewer than 2 usable values) yields `NaN` for that component for every player in the season rather than `inf`; a player with no usable component gets `NaN` `ranking_score`/ranks and sorts last. `league_rank`/`position_rank` are standard competition ("1224") ranks on descending `ranking_score`, ties compared after rounding to 6 dp and display-ordered by ascending `sleeper_player_id` (matching `player_value.py`); `league_percentile = 1 - (league_rank - 1) / n_ranked` over scored players only. All three rank columns are `float64`, not `int64` like `value_rank`, because an unscoreable player's rank is `NaN` — a documented divergence.

**Two modes, per an explicit product decision by the repo owner:** `mode="retrospective"` is fully implemented; `mode="projected"` is a signature seam that raises `NotImplementedError`, with the docstring specifying what it will do (aggregate `ProjectionProvider.projections(season, week)` into projected season totals, then run the identical pipeline). Inventing projection methodology now is exactly what FFA-072 defers, so the parameter and the `projections_df` seam ship for API stability and nothing more.

**Scarcity is weighted on by default (0.15) and this deliberately double-counts positional thinness** — also an explicit owner decision, taken over the recommendation to default it to `0.0`. Subtracting `replacement_ppg` already prices scarcity once; `z_scarcity` prices it again. Because `scarcity_ratio` is a property of the *position*, the tilt lifts **every** player at a thin position including its replacement-level ones, not just the elite ones — in `docs/players-analytics.md`'s worked example a zero-VORP `TE Deep` outranks `QB Volatile`, who banked 8 points above replacement. The module docstring states this plainly rather than burying it, frames it as an opinion about draft-capital value rather than a measure of realized points, and documents `RankingWeights(scarcity=0.0)` as the undistorted reading.

**Weight rebalance (`32dbcaa`), found in review of the initial implementation:** the first defaults were `0.40/0.25/0.15/0.10/0.10`. But `points_above_replacement == games_played * ppg_above_replacement` for every frame FFA-065 produces, so `z_value` and `z_rate` are two views of one quantity and are *exactly equal* whenever `games_played` is constant across the pool (every full-season frame, and every hand-built toy). The original defaults therefore put 0.65 of the blend on one signal counted twice, at the expense of the three components carrying independent information. Rebalanced to `value 0.30 / rate 0.20 / reliability 0.20 / upside 0.15 / scarcity 0.15` — same 1.0 total, value+rate capped at 0.50 — with the collinearity and the cap documented as their own docstring section and asserted by a test. The same review retired `test_scarcity_weight_zero_recovers_the_untilted_reading`'s original premise ("removing scarcity flips RB2/QB2 back"): it had held by a margin of 0.065 and was insensitive to the value/rate split, i.e. over-fitted to the toy rather than a property of the metric. It now asserts the robust claim — scarcity is a per-position constant, so dropping it is level-shifting (WR1's deficit to QB3 collapses from 0.340 to 0.047) and need not reorder anyone.

**Wiring (`6629f59`):** `PlayerAnalytics.player_ranking_df` plus `ranking_weights` and `rate_shrinkage_games` fields, both declared after `season_matchup_df` so existing positional constructor calls are unaffected; `build_player_analytics` forwards them. Like `player_value_df`, the accessor reads the eagerly built `player_season_df` rather than rebuilding the performance frame, so a custom `player_boom_bust_threshold` flows through. Five public names exported from `fantasy_analyzer.players`.

**Tests:** 28 in `tests/players/test_player_rankings.py` (a hand-checked 6-player/3-position toy computed by hand and reproduced in the test docstring; ties on score, `position_rank` and `league_percentile`; missing `cv`; `NaN` `scarcity_ratio`; zero usable components; zero-variance pools; single-player frame; weight renormalization; custom weights; `scarcity=0.0`; invalid weights including `NaN`; shrinkage on/off and `n+k==0`; both mode errors; column order and dtypes; empty frame; missing column; duplicate rows; `None` labels; seasons never pooled) plus 10 in `tests/players/test_player_analytics.py` for the wiring. Full suite **783 passed**; `ruff check src tests` clean; `ruff format --check` clean on all five changed files. Entirely offline — no live Sleeper or nflverse call.

**Docs:** new "League-wide composite player ranking (FFA-073)" section in `docs/players-analytics.md`, with a worked 8-player/3-position example whose printed output was verified to match the code block byte-for-byte, and a hand-check of the `z_scarcity` derivation. The page's module list, layer map, `PlayerAnalytics` attribute table (now fifteen attributes) and source-line anchors were updated with it; `README.md`'s docs paragraph names the new capability.

**Known limitations (documented in-module, not defects):**

- The weights are **an opinion, not a fitted model** — nothing was estimated from data, backtested, or validated on a holdout, and the module makes no predictive claim. Small `ranking_score` differences, or a few places of `league_rank` over a ~150-player single season, are not meaningful.
- Inherited from FFA-064/065/068 and unfixable here: **rostered-players-only pool** (replacement level can be overstated in under-rostered positions), **phase-agnostic** (callers pre-filter weeks against `playoff_week_start`), and **one league-season per call**.
- `_is_missing`/`_empty_frame` are duplicated from `player_value.py` with cross-referencing docstrings rather than imported, since this codebase does not import private names across modules.

**Follow-up candidates (not filed):** tiering on top of `ranking_score`; a CLI surface; and the real work behind `mode="projected"`, which needs a concrete `ProjectionProvider` implementation first.

**Analyze**

- league-wide value ranking across all positions
- composite of production, rate, reliability, upside and positional scarcity
- configurable weights with a documented, overridable default opinion

---

### FFA-074 — League-Wide Free-Agent Player Pool & ID-Crosswalk Coverage Fix
**Status:** DONE (`cf40276` league-wide fact table, `8e357fa` DynastyProcess crosswalk, `7db0ba6` script wiring, `4d7f45f` unrelated sleeper.md docs page committed alongside in the same session).
**Owner:** Data Engineer (crosswalk/data-source work) + Data Scientist (pool-scoping decision)
**Depends on:** FFA-062, FFA-064, FFA-073

**Origin:** Not in the original AGENTS.md roadmap. The repo owner asked for a "top 100 valuable players" report built from FFA-073's ranking, then, after reviewing it, flagged that a real bench/depth player (Mack Hollins) was ranking implausibly high on very ordinary per-game numbers and asked for the model to be re-evaluated against real stats and league scoring rather than trusted at face value. Investigating that report surfaced two separate, compounding bugs in the data feeding FFA-073, both fixed in this ticket. Filed as FFA-074 — the next free number after FFA-073.

**Bug 1 — FFA-064's row universe was rostered-only, with no league-wide alternative.** `build_player_week_fact_table` (by design, per its own docstring) only ever produces rows for players someone in the league actually rostered that week, so a first attempt at a "top 100" report silently had no way to see a high-scoring free agent at all, and FFA-068/FFA-073's replacement-level baseline was computed from a pool of only ~50-65 players league-wide instead of the real ~600-player skill-position universe — understating replacement level for every position and making value/scarcity numbers look better than they should for anyone who happened to be well-mapped.

**Fix:** added `build_league_wide_player_week_fact_table` alongside (not replacing) `build_player_week_fact_table` in `src/fantasy_analyzer/players/player_week.py` — same `PlayerWeekFactTable` output shape, row universe is every `(week, sleeper_player_id)` the configured provider has stats for, with real roster context (`roster_id`/`fantasy_team`/`started`/`bench`) preserved for players who were actually rostered and `roster_id=None`/`fantasy_team=None`/`started=False`/`bench=False` for everyone else. A provider row with no resolvable `sleeper_player_id` is dropped (every downstream FFA-06x module is keyed on that ID). Shared identity-enrichment/scoring logic was refactored into private helpers (`_collect_weekly_rows`, `_concat_stats`, `_empty_fact_table`, `_finalize_fact_table`) so neither builder duplicates the other. 7 new tests in `tests/players/test_player_week.py` (16 existing tests untouched and still passing) cover: a free agent's `fantasy_points` computed correctly, an unresolvable-ID row dropped, rostered rows carrying identical context to the rostered-only builder, row-count accounting, column shape, empty input, and the unsupported-scoring-keys diagnostic.

**Bug 2 (the one that actually explained the implausible ranking) — the Sleeper-catalog-derived ID crosswalk only covers ~32% of real players, and the gap is not correlated with player quality.** `build_id_crosswalk` (FFA-062) has always built its Sleeper<->nflverse mapping from Sleeper's own catalog `gsis_id` field — a deliberate, documented choice to prefer an explicit ID over fuzzy name matching. But that field is simply blank for most of Sleeper's ~12,000-player catalog, including some of 2025's best players — verified directly against the live catalog: Justin Jefferson's own Sleeper entry has `gsis_id: None`. Once free agents entered the pool (Bug 1's fix), this meant most of the *real* competition at a position was invisible, so a merely well-ID-mapped, unremarkable player (Mack Hollins, 6.2 PPG) could rank in the 90th+ percentile purely because the players who should have outranked him were never in the frame at all. A second, independent artifact from the same widened pool: nflverse tracks incidental stats for every position on a roster (a lineman's fumble recovery, a corner's tackle, ...), and a position this league cannot even start (fullback, 6 players league-wide once free agents were in scope) produced a near-zero replacement baseline, letting several ~1-3 PPG fullbacks rank in the top 30 on scarcity alone.

**Fix (crosswalk coverage):** added a second, more complete crosswalk source. New modules `src/fantasy_analyzer/players/id_crosswalk_client.py` (`PlayerIdCrosswalkClient`, mirrors `nflverse_schedule_client.py`'s single-cumulative-CSV shape exactly) and `id_crosswalk_cache.py` (mirrors `nflverse_schedule_cache.py`) download and cache DynastyProcess's `db_playerids.csv` — a community-maintained, actively-updated multi-platform ID crosswalk verified directly to carry a populated `sleeper_id` for effectively its entire ~12,500-row table, including Justin Jefferson correctly cross-referenced to both his real `sleeper_id` and `gsis_id`. `build_id_crosswalk_from_player_ids` in `crosswalk.py` normalizes it to the same `CROSSWALK_COLUMNS` shape `build_id_crosswalk` produces — still a pure explicit ID-to-ID join, never name/position/team fuzzy matching, so the module's original no-fuzzy-matching stance (grounded in AGENTS.md's "prefer immutable IDs" principle) is unchanged, only the *source* of the IDs is more complete. Handles the source's numeric `sleeper_id` column (a naive `str()` cast renders `"4984.0"`, not `"4984"` — fixed via an int cast before the string cast) and applies the same last-value-wins collision policy `build_id_crosswalk` already documents, extended to both `gsis_id` and `sleeper_player_id` since either could collide in a third-party multi-platform table. The original `build_id_crosswalk` is unchanged and remains available as the lighter-weight, no-extra-network-hop option. 21 new tests across `tests/players/test_crosswalk.py` (9), `test_id_crosswalk_client.py` (3), and `test_id_crosswalk_cache.py` (6), plus a new sanitized fixture (`tests/fixtures/id_crosswalk/db_playerids.csv`) covering a normal match, a missing-`sleeper_id` row, a missing-`gsis_id` row, and both collision cases.

**This is a new, second-party network dependency** (DynastyProcess, not an official nflverse release, so a smaller-team/single-maintainer availability profile) — flagged explicitly to the repo owner rather than added silently, per AGENTS.md's instruction to flag rather than silently change an established architecture decision. `scripts/player_analysis.py`'s new `build_robust_id_crosswalk` prefers the DynastyProcess source and unions in the Sleeper-catalog crosswalk for anything it doesn't cover, but falls back to the Sleeper-only crosswalk alone (with a stderr warning) if the DynastyProcess fetch fails — coverage degrades rather than the whole pipeline breaking.

**Fix (non-fantasy position pollution):** `scripts/player_analysis.py` adds `fantasy_relevant_positions(roster_positions)`, which unions `lineup_efficiency.py`'s public `START_SLOT_ELIGIBILITY` over every non-bench roster slot (falling back to a slot's own literal label for an unrecognized/IDP slot, so an IDP league still gets its defensive positions counted). `load_analytics` filters the league-wide fact table to this set before building `PlayerAnalytics` whenever `include_free_agents=True`, so kickers, defenses, and offensive skill positions are ranked, and linemen/corners/fullbacks/etc. never enter the replacement-level or scarcity computation for a standard league. This is script-level composition policy, not a library change — the library's `build_league_wide_player_week_fact_table` stays fully general (a real IDP league would want those positions in its own pool).

**Script wiring:** `scripts/player_analysis.py`'s `load_analytics` gained `include_free_agents: bool = False` (default preserves the original rostered-only behavior) and now builds its crosswalk via `build_robust_id_crosswalk`; a matching `--include-free-agents` CLI flag was added. New `scripts/composite_ranking_report.py` (and `scripts/run_composite_ranking_report.sh`) builds FFA-073's `player_ranking_df` for one or more leagues and writes each to CSV, defaulting to the league-wide, free-agent-inclusive, DynastyProcess-backed pool (`--rostered-only` opts back into the narrower original scope); output written to `scripts/output/` (untracked, like the rest of `scripts/`).

**Result, verified against the two real 2025 leagues used for the report:** free agents in the top 100 dropped from 42-49 per league (the pre-fix, Bug-1-only state) to 1-3 (post-fix), and the fullback anomaly (4 fullbacks in the top 30) disappeared entirely. The corrected top of the board opens with Jonathan Taylor, Jahmyr Gibbs, Christian McCaffrey, De'Von Achane, Bijan Robinson — plausible 2025 fantasy stars — where the pre-fix version had Mack Hollins at #23 overall on 6.2 PPG.

**Tests:** 28 new (7 in `test_player_week.py`, 9 in `test_crosswalk.py`, 3 in `test_id_crosswalk_client.py`, 6 in `test_id_crosswalk_cache.py`, plus a new fixture). Full suite **809 passed** (up from 790 at session start); `ruff check src scripts tests` clean.

**Known limitations (documented in-module, not defects):**

- DynastyProcess coverage, while near-total as of this ticket, is a third-party asset this codebase does not control; a future schema change or discontinuation degrades silently to the lower-coverage Sleeper-only fallback rather than failing loudly — acceptable for a "best available" crosswalk, but worth remembering if rankings quietly regress later.
- `fantasy_relevant_positions`'s IDP fallback (an unrecognized slot label is assumed to accept its own literal position) is untested against a real IDP league, since no IDP league was available to verify against this session.
- The DynastyProcess-vs-Sleeper-catalog union policy (`build_robust_id_crosswalk`) is script-level, not library-level; a caller of the library directly must still choose a crosswalk source themselves.

**Follow-up candidates (not filed):** promoting `build_robust_id_crosswalk` and `fantasy_relevant_positions` into the library proper if another caller besides this script turns out to need them; a scheduled/periodic DynastyProcess cache refresh policy (today it is manual, via `--force-refresh-stats`); reconciling the two "top 100" artifact versions published this session so only the corrected one remains visible to the repo owner (the corrected version was republished to the same Artifact URL, so this is likely already resolved, but was not independently re-verified in this entry).

---

### FFA-084 — Fix Draft Pick-Value Sign Bug and Convert to a Value Scale
**Owner:** Data Scientist
**Depends on:** FFA-078, FFA-079

**Origin:** Not in the original AGENTS.md roadmap. The repo owner reviewed the FFA-077..083 draft grade reports (published as Artifacts for the NWC/New Wave/Zipline leagues) and reported that the grades "seem to value the end rounds way too much and don't break down why some teams are better." Investigating surfaced two compounding, independent bugs in `draft_grade.py`'s `pick_value` metric — one a genuine sign inversion, the other an ordinal-scale error — filed as FFA-084 (next free number after FFA-083).

**Bug 1 — the sign was backwards.** The original formula, `pick_value = expected_pick - pick_no`, produces a *positive* number exactly when a player is taken at a *smaller* (earlier) pick number than his predicted slot — i.e. a reach — and a *negative* number when he falls past his predicted slot to a real steal. This is the opposite of the module's own documented intent ("positive means taken later than expected -- a steal") and of standard fantasy usage. Confirmed independently three ways: by hand against the module's own toy example (a player predicted at pick 10, actually taken at pick 24 — i.e. he fell 14 picks, a textbook steal — produced `pick_value = -14` and was labeled "reach" in both the docstring and the shipped test suite); by re-deriving the formula from the stated sign rule (which requires `pick_value = pick_no - expected_pick`, not the reverse); and by running the real 2026 NWC board, where the bug reproduced exactly as predicted (Christian McCaffrey, predicted around pick 6, fell to pick 10 — a real steal — graded as `pick_value = -0.93` under the old formula's sign convention). Because `avg_pick_value` is 50% of every team's blended grade by default, this was not a cosmetic error: every team's "best pick" and "worst pick" were the *actual worst and best* picks, swapped, and `reach_count`/`value_count` were counting the wrong thing in every league's published report.

**Bug 2 — even with the sign fixed, diffing raw pick *positions* (an ordinal scale) is the same error `draft_board.py`'s own module docstring explicitly calls out and works around for `adp`/`ecr`: "the gap between rank 1 and rank 2 is enormous in true fantasy value; the gap between rank 150 and rank 151 is negligible." A 20-pick swing among the flat, bunched-together replacement-level talent of round 15 was scored identically to a 20-pick swing in round 2, which is why late-round "reaches"/"steals" dominated `avg_pick_value` and made the grades feel like they overweighted the end of the draft — exactly the symptom reported.

**Fix:** `pick_value` is now a value-scale quantity, not a rank-scale one. `draft_grade.py` builds a `(draft_rank, draft_score)` lookup curve from the board (the full-board population, since `pick_no` is a real physical draft slot spanning every pick, not just the ADP-having subset), interpolating linearly between the two bracketing ranks (clamped at the ends) to answer "what value does the board expect from whoever goes at this exact pick slot" — `expected_value_at_pick`, a new reported column. `pick_value = draft_score(player actually taken) - expected_value_at_pick`. This reuses the board's own log-shaped `draft_score` scale (already compressed at the tail via `draft_board.py`'s `-ln(rank)` transform) rather than inventing a second curve, and fixes both bugs at once: the sign now matches stated intent (verified against the real NWC board — Christian McCaffrey's fall to pick 10 now grades `+0.69`, a steal), and the magnitude naturally shrinks for late-round noise because `draft_score` itself flattens there. `expected_pick`/`expected_pick_source` (the player's own predicted rank, ADP-pool-preferred-over-draft_rank-fallback) are unchanged and still reported, now purely informational.

**`draft_report.py`'s `reach_count`/`value_count` threshold** was originally `num_teams` (i.e. "more than one full round early/late," a pick-count unit). Since `pick_value` is no longer pick-count-scale, this was recalibrated to a new `REACH_VALUE_THRESHOLD = 0.30` constant — numerically identical to `draft_board.py`'s own `DEFAULT_TIER_GAP_THRESHOLD`, reused (not imported, per this codebase's no-private-cross-module-import convention) as "roughly one board tier's worth of surprise." No other `draft_report.py` logic needed to change — `best_pick`/`worst_pick` selection already picked on sign, and now selects correctly once the underlying values are correct.

**Tests:** `tests/players/test_draft_grade.py` rewritten (18 tests) with board fixtures that now carry `draft_rank`/`draft_score` alongside `adp_pool_rank` (a real board always has all three; the old formula only needed the latter) and a hand-checked five-point linear toy curve (rank 1..5 → `draft_score` 3.0..-1.0) reused across the toy-example, tie-interpolation, and clamping tests. `tests/players/test_draft_report.py`'s two threshold-dependent tests updated for the new `0.30` constant. Full suite **939 passed** before moving to FFA-085/086.

**Data note:** the three published draft-grade Artifact reports (NWC, New Wave, Zipline) were built with the buggy formula and were regenerated and republished as part of FFA-086 below, including all-new hand-written commentary (the old commentary cited the old, now-known-wrong numbers and could not simply be carried forward — see FFA-086's "commentary" note).

---

### FFA-085 — Fitted Real-Points Draft Value Curve
**Owner:** Data Scientist
**Depends on:** FFA-064, FFA-068, FFA-073, FFA-077, FFA-084

**Origin:** Second half of the same repo-owner request that produced FFA-084 — the grades should also be explainable "based on ... future ranking towards actually winning week by week by scoring the most points possible." `draft_board.py`'s `vor`/`draft_score` are deliberately *not* points-scale (that module's own docstring: "no season-long point projection is in scope"); this ticket builds the missing points-scale signal from real history instead of inventing a new arbitrary curve.

**Design:** for a league's already-completed prior season, its normalized draft picks (FFA-077, `pick_no`/`sleeper_player_id`) join to that same season's FFA-073 composite ranking (`points_above_replacement`, real fantasy points over replacement) on `sleeper_player_id`, giving real `(pick_no, points_above_replacement)` pairs. `fit_points_value_curve` (new module `src/fantasy_analyzer/players/draft_points_value.py`) fits `points_above_replacement = intercept + slope * ln(pick_no)` by closed-form ordinary least squares (no external regression library) — the same log-of-rank shape `draft_board.py` already assumes, now with real fitted coefficients. Keeper picks and K/DEF positions are excluded from the fitting sample (identical rationale to `draft_grade.py`'s keeper exclusion and `draft_board.py`'s `DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS`, respectively). `PointsValueCurve.value_at(x)` evaluates the fit for any pick number or board rank (both live on the same 1-indexed ordinal scale), clamped at `x >= 1`.

`score_points_value` then evaluates the fitted curve against a *different* (typically upcoming) draft's picks and board: `projected_points_value = curve.value_at(draft_rank of the player taken)` ("given where this year's board ranks him, what does history say a player at that rank is worth in real points"), `expected_points_value_at_pick = curve.value_at(pick_no actually used)` ("what does history say this exact slot returns"), `pick_value_points = projected_points_value - expected_points_value_at_pick`. Same sign convention as `draft_grade.py`'s `pick_value`; the two are complementary, not identical, since one answers "more value than this year's market expects" and the other "more real points than history says this slot returns."

**Real-data validation:** fit against NWC's actual 2025 draft (158 usable picks after exclusions), the curve came back `intercept≈176, slope≈-39.7, r_squared≈0.38` — a sane, monotonically-declining points-by-pick curve (pick 1 ≈ +176 points above replacement, pick 192 ≈ -33), with R² in the expected range for a single-season, ~160-pick sample (individual player outcomes are noisy; this is explicitly documented as a rough estimate, not a precise projection, and `r_squared`/`n_picks` travel with every `PointsValueCurve` for exactly this reason).

**Regression found and fixed during implementation:** `score_points_value`'s `pd.DataFrame(rows, columns=...)` construction silently converted `excluded_reason`'s `None` values to `NaN` for a real ~190-row draft (though not for a 1-row test fixture, which is why it wasn't caught until running against live data) — a pandas 3.0 behavior where a column mixing a real string ("keeper") with `None` infers a string dtype that normalizes `None` to `NaN`, unlike an otherwise-identical bool/`None` column (`is_keeper`), which stays `object` dtype with `None` intact. This broke every downstream `is None` check on `excluded_reason` (including the phase-breakdown code in FFA-086, where every team's per-round pick counts came back `0` until this was found and fixed). Fixed by re-normalizing `excluded_reason`/`expected_pick_source` back to real `None` after construction, the same pattern `draft_grade.py` already uses for its own new object columns. A regression test (`test_excluded_reason_stays_real_none_not_nan_across_many_rows`, ~40 rows to actually reproduce the pandas behavior) was added since a small fixture cannot catch it. **This same latent pattern (a pass-through string/`None` column silently losing `None` across any `pd.DataFrame(list_of_dicts)` reconstruction) was not audited across the rest of the codebase** — flagged here as a known risk, not fixed elsewhere, since doing so was out of this ticket's scope.

**Data pipeline:** new `scripts/fetch_season_draft_picks.py` (generic, any season/league_id, mirrors `draft_report_2026.py`'s own fetch pattern) pulled each league's actual 2025 draft; `scripts/composite_ranking_report.py` (existing, FFA-073/074) regenerated the missing 2025 "prior" CSVs for New Wave and Zipline (only NWC's existed on disk before this session). `draft_league_presets.py` gained a `prior_draft_csv` field per league pointing at the new files.

**Tests:** 19 in `tests/players/test_draft_points_value.py` (a hand-checked perfect-fit toy curve — pick_no ∈ {1,2,4,8} on an evenly-spaced ln-grid paired with exactly-linear `points_above_replacement` values, `r_squared=1.0` — plus keeper/K-DEF exclusion, fewer-than-two-points and zero-variance degenerate cases, the `None`-vs-`NaN` regression, and every missing-value path). Full suite **959 passed**.

**Known limitations (documented in-module, not defects):**

- Single-season, single-league sample (~127-158 usable picks per league) — genuinely noisy; `r_squared` in the 0.3-0.4 range is expected, not a bug, and is surfaced everywhere the curve's numbers are shown so nobody reads them as a precise projection.
- The curve is fit per-league (its own scoring format/team count), never pooled across leagues — avoids a half-PPR/full-PPR normalization problem, but means each league's curve is even smaller-sample than a pooled one would be.
- No live 2026 season data exists yet to validate the curve's actual out-of-sample accuracy (today's date is within the 2026 season's first weeks) — this is a forward projection whose calibration cannot be checked until real 2026 results accumulate.

---

### FFA-086 — Draft Report Phase-Breakdown and Points-Value Explanation
**Owner:** Software Engineer (script/report layer)
**Depends on:** FFA-081, FFA-084, FFA-085

**Origin:** Third part of the same repo-owner request — the reports should "break down why some teams are better and should be valued higher," not just show a single blended grade.

**Design:** `draft_report_2026.py` (script layer, not the core `players` package — this is pure display aggregation of already-tested numbers, not a new metric definition) gained `build_points_value_team_summary`, which buckets each team's scoreable, non-excluded picks into early/mid/late thirds of the draft by round (`_pick_phase`, a simple round-fraction split, league-size-agnostic) and reports each phase's pick count plus average `pick_value` (board-relative) and average `pick_value_points` (real-points-scale, from FFA-085) — directly answering "where in the draft did this team actually win or lose value." A team's `total_points_value` (sum of `projected_points_value` across scoreable picks) is also surfaced as a new "Proj. pts value" stat. The HTML template (`templates/draft_report_artifact.html.tpl`) gained a "Value by draft phase" block per team card and a footer note reporting the fitted curve's `n_picks`/`r_squared` inline, so the caveat travels with the numbers.

**Wiring is fully optional/graceful:** `load_prior_draft` (new, mirrors `load_prior`) returns `None` rather than raising when a league has no `prior_draft_csv` configured or the file doesn't exist yet, so a league without FFA-085's historical data still gets a complete FFA-084 report, just without the points-value columns/section.

**Commentary note:** the three published draft-grade reports (NWC, New Wave, Zipline Artifacts) had hand-written per-team commentary from the original FFA-083 session. Regenerating the reports for FFA-084's fix necessarily overwrote that commentary with template placeholders (`{{COMMENTARY_ROSTER_N}}`), and — critically — the *old* commentary could not simply be restored, because it explicitly cited pick values computed under FFA-084's now-confirmed-backwards sign bug (e.g. one team's old "Best pick" citation was, under the corrected numbers, actually that same team's *worst* pick). All 32 team paragraphs (12 NWC + 10 New Wave + 10 Zipline) were rewritten from scratch against a precomputed facts sheet (best/worst picks by corrected `pick_value_points`, phase breakdown, roster construction) built directly from the regenerated CSVs, so no stale or incorrect number could carry forward into the new prose.

**Tests:** one new integration test in `tests/test_draft_report_script.py` (`test_main_single_league_wires_points_value_curve_when_prior_draft_available`) verifying the full pipeline wires a fitted curve through to both the picks CSV and the HTML's phase-breakdown/footer text when prior-season data is supplied; the existing single-league test's `_stub_market_and_prior` fixture was extended to also stub `load_prior_draft` for determinism. Full suite **959 passed**.

**Known limitations (documented in-module, not defects):**

- The early/mid/late phase split is a fixed thirds-of-the-draft rule, not tied to any positional or roster-construction logic — a team's "Early" phase picks might all be one position, which the breakdown doesn't call out.
- Phase-breakdown aggregation lives in the script layer, not the core `players` package, per AGENTS.md's "thin composition" convention for `scripts/` — a future caller wanting this same breakdown outside this script would need to either duplicate it or the aggregation would need promoting into the library.

**Follow-up candidates (not filed):** auditing the rest of the codebase for the same pandas string/`None`-column pattern FFA-085 found and fixed locally; validating the FFA-085 points curve's real accuracy once 2026 results accumulate; promoting the phase-breakdown aggregation into the `players` package if a second caller needs it.

**Follow-up candidates (not filed):** promoting `build_robust_id_crosswalk` and `fantasy_relevant_positions` into the library proper if another caller besides this script turns out to need them; a scheduled/periodic DynastyProcess cache refresh policy (today it is manual, via `--force-refresh-stats`); reconciling the two "top 100" artifact versions published this session so only the corrected one remains visible to the repo owner (the corrected version was republished to the same Artifact URL, so this is likely already resolved, but was not independently re-verified in this entry).

---

## Epic 8 — League & Matchup Commentary

Design doc: `docs/commentary_plan.md`. Ticket numbers renumbered to FFA-090+ when implementation started, since the plan doc's original FFA-080-084 numbering collided with FFA-084 through FFA-086 (draft-grade work), which had since taken those numbers.

### FFA-090 — Weekly Matchup Commentary Context Builder
**Owner:** Data Scientist
**Depends on:** FFA-033 (season matchup df), FFA-064 (player-week fact table), FFA-069 (matchup contribution), FFA-067 (lineup efficiency), FFA-040 (head-to-head), FFA-051 (all-play)

New package `src/fantasy_analyzer/commentary/`, `context.py`. `build_matchup_context(snapshot, season_matchup_df, player_week_df, week, *, top_n_contributors=3, projected_points=None) -> list[MatchupContext]` assembles, per non-bye pairing that week: final score/margin/projected score, top contributors each side (`players/matchup_contribution.py`), bench points left on the table + top bench scorer (`players/lineup_efficiency.py`), that week's all-play record each side (`analytics/all_play.py` + `analytics/weekly_scores.py`), head-to-head history entering the week (`analytics/head_to_head.py`, filtered to weeks before `week`), and a new small, documented streak/revenge-game derivation (`STREAK_MIN_LENGTH = 2`, walks chronological prior meetings between the two rosters — not a new analytics module, just local derivation). Returns frozen, JSON-serializable dataclasses (`MatchupContext`, `PlayerContribution`, `BenchScorer`, `AllPlayWeekRecord`, `TeamWeekSummary`, `HeadToHead`, `Streak`). Pure, no network calls.

**Tests:** `tests/commentary/test_context.py` (8 tests total, shared with FFA-091) — empty-input, bye-exclusion, missing-player-data, and first-meeting/no-history edge cases, plus a fully hand-checked week-3 matchup (final score/margin, top contributors incl. a rank tie, bench points left on the table, a snapped 2-game streak, two independently-verified revenge games) against a hand-built 4-roster/3-week toy season fixture.

### FFA-091 — League-Week Recap Commentary Context Builder
**Owner:** Data Scientist
**Depends on:** FFA-020 (standings), FFA-056 (power rankings), FFA-050 (weekly scores), FFA-052 (schedule luck)

Same module. `build_league_week_context(snapshot, analytics, standings_df, week, *, previous_standings_df=None) -> LeagueWeekContext` assembles standings + movement since last week (`analytics/standings.py`; standings/previous-standings are caller-supplied since `build_standings` only exposes Sleeper's live cumulative counters, not a per-week-filterable history), power-ranking deltas (`analytics/power_rankings.py`, filtered `week <= N` vs `<= N-1`), the week's scoring leaderboard — highest/lowest/biggest blowout/closest game (`analytics/weekly_scores.py` + `season_matchup_df.margin`), and schedule-luck outliers (`analytics/schedule_luck.py`, same week-filtering convention). Returns `LeagueWeekContext` composed of `StandingsMovement`, `PowerRankingDelta`, `ScoringLeaderboardEntry`, `MatchupExtreme`, `WeeklyScoringLeaderboard`, `ScheduleLuckOutlier`, `ScheduleLuckOutliers`.

**Milestone field intentionally omitted:** the design doc asked for "clinched playoff spot / mathematically eliminated" flags, but `matchups/playoffs.py`'s only boundary logic (`build_final_placements`) resolves a placement only from an already-played bracket match — it cannot determine clinch/elimination status mid-regular-season, which requires combinatorial remaining-schedule simulation against `playoff_teams` that no module in this repo currently computes. Omitted rather than inventing that logic; flagged as a follow-up ticket candidate.

**Tests:** shared `tests/commentary/test_context.py` — empty-analytics and week-1/no-previous-week edge cases, plus a fully hand-checked week-3 league recap (standings + rank movement, weekly leaderboard, schedule-luck outliers derived from a shown-in-comments 9-comparison-per-roster all-play calculation). Power-ranking-delta assertions are structural only (the underlying z-score arithmetic is already covered by `test_power_rankings.py`). Full suite **967 passed** after FFA-090/091.

### FFA-092 — Commentary Prompt Templates
**Owner:** Software Engineer
**Depends on:** FFA-090, FFA-091

`src/fantasy_analyzer/commentary/prompts.py` — pure, network-free functions rendering context dataclasses into a fixed three-part prompt structure (role/goal framing, a JSON data block via `dataclasses.asdict` + `json.dumps(..., indent=2, default=str)`, explicit constraints incl. "don't invent stats not present in the data"). `tone` (`"witty"` / `"straightforward"`, via `TONE_DESCRIPTIONS`) and `max_words` are real parameters, not hardcoded, on all three functions: `weekly_matchup_prompt(context, *, tone="witty", max_words=150)` (one matchup), `combined_matchup_prompt(contexts, *, tone="witty", max_words=120)` (all of a week's matchups in one prompt), `league_week_recap_prompt(context, *, tone="witty", max_words=400)`.

**Tests:** `tests/commentary/test_prompts.py`, 15 tests — role framing / data block / constraints all present; JSON block round-trips and matches the source context; tone changes wording; `max_words` reflected; combined prompt covers every matchup incl. empty-list case; recap prompt data/wording.

### FFA-093 — Commentary CLI Subcommand (prompt-only)
**Owner:** Software Engineer
**Depends on:** FFA-092

Extended `src/fantasy_analyzer/cli.py` with a `commentary` subcommand mirroring the existing `summary` subcommand's plumbing style:
```
fantasy-analyzer commentary matchups <league_id> --week N --total-weeks N [--tone TONE] [--per-matchup]
fantasy-analyzer commentary recap <league_id> --week N --total-weeks N [--tone TONE]
```
Both print prompt text to stdout only — no `--generate` flag (that's FFA-094, untouched, not stubbed). `build_commentary_inputs(client, league_id, total_weeks, *, provider=None)` reuses the existing normalization chain (`load_league_snapshot` → `derive_season_boundaries` → `load_season_matchups` → `pair_season_matchups` → `derive_season_outcomes` → `build_season_matchup_df`, plus `build_player_week_fact_table`, `build_standings`, `build_league_analytics`) rather than inventing a new fetch path, same pattern `scripts/player_analysis.py`/`run_summary` already use. `run_commentary_matchups`/`run_commentary_recap` build context via FFA-090/091's builders and format with FFA-092's prompt functions. `--per-matchup` selects per-matchup prompts; default is the combined prompt.

**Scope-narrowing choice (deliberate, not an oversight):** the default (no injected `provider`) uses `build_id_crosswalk` (Sleeper-catalog-only `gsis_id` crosswalk), not the richer DynastyProcess-backed `build_robust_id_crosswalk` that `scripts/player_analysis.py` uses — keeps the CLI's default path to one network dependency instead of two, at the cost of lower player-name coverage in `top_contributors`/bench-scorer fields for real-world runs. Flagged as a follow-up candidate if contributor-name coverage turns out to matter for commentary quality.

README.md updated with the two new `commentary` CLI examples alongside the existing `leagues`/`summary` ones.

**Tests:** `tests/test_cli.py` — 12 new tests: argument parsing for both sub-subcommands (incl. required sub-subcommand), `run_commentary_matchups` (combined/per-matchup/no-matchups-for-week), `run_commentary_recap`, and `main()` end-to-end for both (mocked via `requests_mock` against existing fixtures, `total_weeks=1` to keep the matchups mock minimal, `NflverseWeeklyStatsProvider` monkeypatched to a fake). Full suite **987 passed**; `ruff check`/`ruff format` clean across all Epic 8 files (a pre-existing formatting drift in `context.py`/`test_context.py` from FFA-090/091, flagged by the FFA-092/093 agent, was reformatted in the same pass).

**Follow-up candidates (not filed):** a milestone/clinch-elimination context field (needs new playoff-simulation logic); swapping the CLI's default crosswalk to the DynastyProcess-backed one for better player-name coverage.

### FFA-094 — Anthropic API Commentary Client + `--generate` flag
**Owner:** Software Engineer
**Depends on:** FFA-093

API-billing decision made: default model `claude-opus-4-8` at `output_config.effort="high"`. New `src/fantasy_analyzer/commentary/client.py` — `CommentaryClient` wraps the `anthropic` SDK (`anthropic>=1.4` added to `pyproject.toml` dependencies); `generate(prompt, *, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT, max_tokens=DEFAULT_MAX_TOKENS) -> str` sends one user-turn message and concatenates the response's `text` content blocks (skipping `thinking`/other block types). Credentials resolve from the environment via the SDK's own default (`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / an `ant auth login` profile) — never hardcoded. An optional `client` constructor parameter accepts any object exposing `messages.create(...)`, letting tests and other callers inject a fake instead of a real network-backed `anthropic.Anthropic()`. Anthropic API failures (`anthropic.APIError` and subclasses) and an empty-text response both raise a new `CommentaryGenerationError`.

`cli.py`'s `commentary matchups`/`commentary recap` subcommands gained a `--generate` flag. `run_commentary_matchups`/`run_commentary_recap` gained `generate: bool = False` and an injectable `commentary_client` parameter (mirroring the existing `provider` injection pattern): when `generate` is `False` (default), behavior is unchanged (prints the raw prompt(s)); when `True`, each prompt is sent through `CommentaryClient.generate(...)` and the generated text is returned instead (one call per prompt — so `--per-matchup --generate` makes one API call per matchup). `main()` passes `args.generate` through and added `CommentaryGenerationError` to its existing `except (SleeperAPIError, ValueError)` handler so a failed generation prints a friendly `Error: ...` and exits 1 instead of an unhandled traceback.

**Tests:** `tests/commentary/test_client.py` (6 new tests, all against an injected fake `messages.create`, no live API call) — text-block concatenation, non-text-block skipping, default model/effort/message-shape assertions, explicit override passthrough, empty-response and wrapped-API-error `CommentaryGenerationError` cases. `tests/test_cli.py` gained a `FakeCommentaryClient` fixture and 8 new tests: `--generate` flag parsing on both sub-subcommands (incl. its `False` default), `run_commentary_matchups`/`run_commentary_recap` returning generated text instead of the prompt (combined and per-matchup call-count cases), and a `main()` end-to-end case with `CommentaryClient` monkeypatched to the fake. Full suite **998 passed**; `ruff check` clean on all touched files.

**Assumptions:** effort/model are ordinary keyword arguments with the billing-decision values as defaults, not hardcoded — a caller can override either per-call. No `thinking` parameter is set (Opus 4.8 does not think by default when omitted); commentary generation didn't seem to warrant extended-thinking cost given `effort="high"` already governs response depth. `--generate` makes one Anthropic API call per prompt each invocation (no caching/retries added beyond the SDK's own default retry-on-429/5xx behavior) since 093's design doc did not call for either.

**Follow-up candidates (not filed):** batching per-matchup `--generate` calls into a single request if per-matchup Anthropic spend becomes a concern; surfacing `response.usage`/cost in CLI output for cost visibility; a config knob for `model`/`effort` instead of only code-level keyword overrides.

---

## Epic 9 — Waiver-Wire Decision Support

Triggered by running a real 2026 week-1 free-agent board and finding the
output unusable: the top of the CLI's ranking was Tyreek Hill, Kareem Hunt
and Zach Ertz — none of them on an NFL roster — and the board was topped by
quarterbacks and kickers in one-QB leagues. Four separate defects, each
measured on live 2026 data before being fixed, plus the three context
layers the board was missing.

### FFA-095 — League-Wide Replacement Population for Waiver Rankings
**Owner:** Data Scientist
**Depends on:** FFA-068 (player value / VORP), FFA-092 (waiver rankings)

`build_waiver_wire_rankings` passed only `free_agent_pool` to
`build_player_value_metrics`, which silently redefined "replacement level"
as *the last startable player among free agents* rather than *in the
league*. Because the free-agent pool is the entire unrostered Sleeper
catalog, its tail is full of players who will never take a snap, so the bar
collapsed. Measured on 2026 week 1, 12-team: replacement ppg went
`QB 11.3 / RB 1.9 / TE 5.4` (wire) vs `QB 17.5 / RB 8.5 / TE 6.7` (league).
The RB case is the clearest — the "last startable RB" was the 36th-best
*unrostered* RB at 1.92 ppg. This inflated positional VORP and made the
cross-position ordering an artifact of which position had the longer junk
tail.

New keyword `replacement_population` (a second pool-shaped frame, normally
`build_free_agent_pool([], ...)`). The union is projected and valued
together; rostered players are then dropped and only free agents returned.
`waiver_rank` is re-derived over the filtered rows using
`player_value._assign_value_ranks`' exact rule (competition "1224" ranking
on `points_above_replacement` rounded to 6dp), so it stays a rank among
*claimable* players rather than a sparse remnant of a league-wide rank.
Default is `None` = original behavior, so no existing caller changes.

Documented knock-on effect: with a league-wide population the
positional-mean fallback prior for a zero-game player also becomes
league-wide. That is the consistent choice once the frame of reference is
the league, and it is tested explicitly.

**Tests:** `tests/players/test_waiver_rankings.py` — bar rises and rostered
players are not returned (isolated on the one player whose projection is
population-independent: zero games + a trusted prior); `waiver_rank` stays
a 1..n prefix; the fallback-prior widening is asserted with hand arithmetic
(`mean(9.0, 20.0, 18.0, 16.0) = 15.75`); an empty `replacement_population`
is frame-equal to the default.

### FFA-096 — Minimum Prior-Season Games Guard
**Owner:** Data Scientist
**Depends on:** FFA-090 (ROS projection), FFA-092

`prior_season_ppg` had no sample-size guard: a one-game prior was trusted
exactly like a seventeen-game one. Since `games_to_date = 0` forces the
blend weight `w` to exactly zero, that one game *became* the whole
projection. Concretely, Phil Mafah carried a 9.90 ppg prior earned in a
single week-18 2025 appearance and floated up the board above genuinely
productive players.

New `min_prior_games` keyword (`DEFAULT_MIN_PRIOR_GAMES = 4`). A player
below the threshold is **not dropped** and his `prior_season_ppg` is still
reported — the guard nulls only the *resolved* prior, which then falls back
to the positional mean exactly as for a player with no prior season at all.
New output column `prior_season_games` so a board can show how thin the
sample is. `min_prior_games=0` disables the guard.

**Behavior change:** this is on by default, so a projection built on a
1-3 game prior now differs from before. Two existing toy tests asserted the
old behavior; the fixture was widened from 2 to 4 identical prior weeks so
the documented arithmetic is unchanged (prior ppg is 5.0 either way) and
the guard case got its own dedicated tests.

**Tests:** same file — the thin-prior fallback with reported-but-untrusted
raw values; `min_prior_games=0` restoring the untrusted prior; the guard
reaching the *blended* population too, not just zero-game rows
(`0.5714 * 9.0 + 0.4286 * 30.0 = 18.0` unguarded vs `9.0` guarded);
negative-value rejection.

### FFA-097 — Promote `build_robust_id_crosswalk` into the Package
**Owner:** Data Engineer
**Depends on:** FFA-062, FFA-074

`cli.build_free_agent_rankings` used `build_id_crosswalk(catalog)` —
Sleeper's own sparse `gsis_id` field — which matched **111 of 615**
NFL-signed free agents in a measured 12-team league (RB 12/108, WR 26/222).
An unresolved free agent gets `has_crosswalk = False` and therefore no
projection at all, so this removed four fifths of the wire from the board
rather than degrading it gracefully. The DynastyProcess union resolved
**520 of 615**.

That union already existed as `build_robust_id_crosswalk` but lived in
`scripts/player_analysis.py`, unreachable from the package. Moved verbatim
to `players/crosswalk.py` (its network/cache imports are function-local so
the module stays otherwise pure); `player_analysis.py` now imports it and
its two now-unused imports plus `requests` were dropped.

`build_free_agent_rankings`/`run_free_agents` gained an injectable
`crosswalk` parameter mirroring the existing `provider` seam, so a test can
stay fully offline and a multi-league run can build the crosswalk once.

### FFA-098 — Carry Opportunity Columns Through to the Waiver Board
**Owner:** Data Engineer
**Depends on:** FFA-087 (provider opportunity columns), FFA-092

FFA-087 carried ten opportunity columns through the nflverse provider and
into the cache, but `build_scored_player_weeks` filtered them to a
hardcoded tuple of three (`target_share`, `air_yards_share`, `wopr`) plus
`targets`/`carries`, and the waiver board surfaced none of them. Replaced
with `CARRIED_OPPORTUNITY_COLUMNS` covering all ten, with a test asserting
it stays a superset of the provider's own `OPPORTUNITY_COLUMNS` so the two
cannot drift.

`build_free_agent_ros_projections` now emits `OPPORTUNITY_SUMMARY_COLUMNS`
— ten **per-game** figures over the observed weeks. Share/ratio columns
(already per-game rates) average across weeks; volume and EPA columns are
totals divided by `games_to_date`, so a week a receiver played and drew
zero targets is a real zero rather than a skipped row. These are
descriptive only and feed no projection: they exist so a reader can tell a
one-game spike on two targets and a long touchdown from a one-game spike on
eleven targets — the "touchdown trap" `ros_projection.py`'s own docstring
names but, pricing in points space, inherits.

nflverse's weekly player stats carry **no snap counts** at any stage, so no
snap-share column is available.

**Tests:** per-game summary arithmetic for both column families incl. the
zero-target-week case; NaN (not a missing column) when the source lacks
them; NaN for unplayed and uncrosswalked players; survival into the ranking
output.

### FFA-099 — Opponent Strength, Defense-vs-Position and Schedule Context
**Owner:** Data Scientist
**Depends on:** FFA-073 (nflverse schedule client/cache), FFA-092

New `players/opponent_strength.py`. The schedule client and cache from
FFA-073 already existed but had **never been populated** —
`.cache/nflverse/games.csv` did not exist, so no future-week opponent was
reachable. (nflverse's `opponent_team` on the weekly stats covers completed
weeks only.) `build_scored_player_weeks` also now carries
`CARRIED_CONTEXT_COLUMNS = ("team", "opponent_team")` so realized points
can be attributed to the defense that allowed them.

- `normalize_schedule(games, season)` — one row per game becomes two
  team-week rows, regular season only, with `implied_team_total` derived
  from `total_line`/`spread_line` (nflverse states the spread from the
  **home** team's perspective).
- `bye_weeks(schedule, season_end_week)` — a team's bye is the week it has
  no row.
- `build_defense_vs_position(...)` — fantasy points allowed per game per
  `(defense, position)`, scored with the **league's own** settings (a PPR
  and a standard league genuinely have different defense-vs-WR rankings),
  divided by the positional league mean and then shrunk toward 1.0 by
  `(n * raw + k) / (n + k)`. At the default `k = 6` a week-2 defense
  carries 25% of its raw signal. Raw early-season DvP is noise, and early
  season is exactly when a waiver board is consulted.
- `add_matchup_context(...)` — appends `week_opponent`, `week_is_home`,
  `week_implied_team_total`, `week_dvp_multiplier`,
  `matchup_adjusted_ppg`, `bye_week`, `remaining_schedule_multiplier`,
  `remaining_games_scheduled`, `schedule_adjusted_ros_points`.
  `remaining_games_scheduled` is the first **bye-aware** games count in the
  pipeline — `waiver_rankings`' `remaining_games` is a schedule-blind
  constant for every player, an overstatement that module's docstring
  already flagged.

**`projected_ppg` is never overwritten** (asserted by a test): every
adjusted figure is a separate column, because `k` is an unfitted prior —
no backtest in this repo measures defense-vs-position accuracy, unlike
`n0`. Documented as a follow-up ticket.

Measured availability: week-2 Vegas lines were present on all 16 games but
only **48 of 272** 2026 regular-season games carried one, so implied totals
inform the this-week view and are `NaN` for the rest of the season — the
honest representation rather than an extrapolated number.

`SLEEPER_TO_NFLVERSE_TEAM` handles the only two vocabulary disagreements,
verified against the full 2026 catalog and schedule: `LAR -> LA` and the
legacy `OAK -> LV`.

**Tests:** `tests/players/test_opponent_strength.py`, 19 tests — the
implied-total sign convention in both directions (and that the two sides
sum to the total), postseason exclusion, bye derivation, the module
docstring's hand-checked DvP worked example, shrinkage monotonicity,
position-group summing within a week, no-opponent rows ignored, the
`projected_ppg` no-overwrite guarantee, unsigned/bye/no-projection cases,
and empty inputs. Two real bugs were caught here: a team on bye in the
target week with nothing left to play was misread as an unknown team, and
`schedule_adjusted_ros_points` returned `NaN` instead of `0.0` at zero
games remaining.

### FFA-100 — Roster-Fit Add/Drop Analysis
**Owner:** Data Scientist
**Depends on:** FFA-067 (lineup efficiency), FFA-092

New `players/roster_fit.py`. A league-level VORP ranking answers "who are
the best unrostered players"; a manager is holding "does this player start
for *me*, and over whom". A tight end 2.5 points above replacement is a
significant add for the manager starting a replacement-level tight end and
worth nothing to the manager who already rosters two better ones.

- `optimal_lineup(players, roster_positions)` — exact best startable
  lineup by projected points, via the same count-vector dynamic program
  FFA-067 uses and reusing its `START_SLOT_ELIGIBILITY` verbatim (one
  source of truth for what a `FLEX` accepts). Returns a `LineupSolution`
  carrying the chosen starters, so two solutions can be differenced to
  name who was displaced.
- `build_drop_candidates(...)` — each rostered player's **marginal value**,
  `best_lineup(roster) - best_lineup(roster - player)`. Zero means the
  best lineup is unchanged without him. This is deliberately *not* "worst
  projection": a backup QB at 18.0 ppg in a one-QB league has marginal
  value 0.0 while an RB at 9.0 does not — tested explicitly.
- `build_add_drop_candidates(...)` — `starting_ppg_gain`, who the
  candidate `displaces`, the cheapest `best_drop`, and `net_lineup_gain`
  for the executable transaction (which can be below `starting_ppg_gain`
  when the only droppable player is himself a starter, and is never above).

**Why not reuse `build_lineup_efficiency_metrics` directly:** it solves the
lineup for *realized* weeks and needs `started`/`bench` flags and actual
points as ground truth. A waiver decision is about weeks that have not
happened; feeding it a synthetic player-week frame would mean fabricating
exactly the columns it trusts. Same algorithm, different inputs.

Explicit scope limits in the module docstring: per-game rates not season
totals, no bye-week or injury planning on the drop side (it names
FFA-099's `bye_week` as the column to cross-reference), no handcuff logic,
no FAAB/waiver-priority/roster-size rules. `max_candidates` (default 60)
caps the search, since one lineup is solved per candidate.

**Tests:** `tests/players/test_roster_fit.py`, 20 tests — the module
docstring's hand-checked worked example, FLEX preference flipping,
SUPER_FLEX taking a second QB, unstartable/unprojected players ignored,
marginal values for all four toy roster slots, the backup-QB case, gain and
displacement, a candidate who does not crack the lineup, net gain falling
below starting gain when the drop is a starter, and empty inputs.

### FFA-101 — Persisted Fitted Shrinkage Parameters
**Owner:** Software Engineer
**Depends on:** FFA-088 (multi-season corpus), FFA-090

The follow-up `docs/free-agents-cli.md` named and left unimplemented.
`save_shrinkage_parameters` / `load_shrinkage_parameters` round-trip a
`ShrinkageParameters` as JSON at
`.cache/nflverse/shrinkage_parameters.json`. `load_` returns `None` for
both "no file" and "unreadable file", so the caller's fallback path is the
same either way — a corrupt fit and a missing fit are equally reasons to
use the uniform default, and neither should take down a ranking.

New `scripts/fit_shrinkage_parameters.py` runs the fit once over the cached
seasons (defaults to standard PPR scoring, since `n0` describes how fast a
position's evidence accumulates and is not very sensitive to the ruleset;
`--league-id` fits against a real league's settings instead).

`build_free_agent_rankings` now loads the fitted set when present and falls
back to uniform `DEFAULT_N0 = 3.0` otherwise.

**Tests:** `tests/players/test_ros_projection.py` — round-trip incl.
nested-directory creation and behavioral equivalence (`n0_for`) rather than
only field equality; missing file; two corrupt-file shapes; a partial file
falling back to defaults per-field.

### Epic 9 CLI wiring

`cli.build_free_agent_rankings` now composes all four fixes: robust
crosswalk (FFA-097), league-wide `replacement_population` (FFA-095), the
FFA-096 guard via its default, and a loaded fitted parameter set
(FFA-101). Its docstring's "shrinkage-parameter tradeoff" section was
rewritten into a "three composition choices" section naming the measured
impact of each, since all three had previously been documented as
deliberate simplifications.

**Follow-ups (recorded in AGENTS.md, none blocking):** fit
`DEFAULT_DVP_SHRINKAGE_GAMES` the way FFA-089/090 fit `n0`; TTL-check the
three caches; no D/ST at any stage (nflverse carries no team-defense
player-week rows); bye/injury awareness on FFA-100's drop side.

---

## Epic 10 — Season Dashboard

### FFA-102 — As-of-Week Standings from Matchups
**Owner:** Data Scientist
**Depends on:** FFA-033 (season matchup frame), FFA-020 (standings shape)

`build_standings_through_week(season_matchup_df, teams_df, week, *,
include_playoffs=False)` in `analytics/standings.py`.

The gap it fills was already documented in two places as structural:
`build_standings`' own docstring ("Sleeper does not split these cumulative
roster counters by season phase ... phase-specific standings require
per-week, per-matchup data") and `build_league_week_context`'s ("this
function cannot derive 'standings as of week N' for an arbitrary past
week"). Both were true of `build_standings`, which reads Sleeper's running
roster totals. Neither was true of the data — FFA-033's matchup frame has
had the week-level granularity since Epic 4. This re-derives every counter
from it and returns the same `STANDINGS_COLUMNS` shape, so it is a drop-in
for existing consumers. Both docstrings updated.

**Metric definitions.** Wins/losses/ties counted from
`winner`/`loser`/`is_tie` (roster IDs, per `season_matchups.py`'s column
semantics); `points_for`/`points_against` summed from whichever side of the
pairing the roster sits on; `win_pct` and the `win_pct` → `points_for`
competition-ranking rule reused unchanged from `build_standings`, via a
new shared `_competition_ranks` helper.

**Regular season vs. playoffs — explicit**, unlike the two functions it
sits beside. `include_playoffs` defaults to `False`.

**Incomplete matchups contribute nothing.** A bye (no `roster_2_id`) or an
unscored week adds no record and no points to either side. Crediting a bye
team's points against no opposing total would inflate its differential by a
full game and break the league-wide symmetry that makes `point_diff`
comparable. A team whose every game is incomplete appears 0-0-0 rather than
being dropped.

**Tests:** `tests/analytics/test_standings_through_week.py` — 11 tests, each
with hand-computed arithmetic in its docstring: a four-team/two-week toy
example, week truncation, ties at half a win, a two-key rank tie ("1224"),
the playoff switch in both directions, byes and unscored rows, a team with
no games, week 0, both empty-input cases, and shape-compatibility with
`build_standings`.

### FFA-105 — Dashboard Bundle Builder
**Owner:** Data Engineer

`scripts/build_dashboard.py` writes one `bundle.json` covering every league
and every completed week. A composition script only — every number comes
from an already-tested package function.

Deliberately does *not* call `cli.build_commentary_inputs`, which also
builds the player-week fact table (the pipeline's most expensive step) that
nothing on this page needs. Mirrors `cli.build_free_agent_rankings`'s three
accuracy-critical choices inline rather than calling it, because the page
needs the intermediate `scored_weeks` frame for defense-vs-position and for
rostered-player projections, which that function does not return.

Three bugs found and fixed while validating against live data:

- `add_matchup_context` takes the **cutoff** week and builds context for
  `week + 1` itself; passing the upcoming week described the week after the
  one being planned for.
- The raw `waiver_rank` is computed pre-filter, so the displayed board had
  gaps (1, 2, 6, 7, 9…) reading as missing players. Added a post-filter
  `board_rank`; `waiver_rank` is retained.
- Passing week-0 standings as `previous_standings_df` for a week-1 recap
  reported every manager but one falling up to eleven places, since before
  any game every team is tied at rank 1. Week 1 now passes `None`.

Also joins `injury_status`/`injury_body_part` from the Sleeper catalog,
which the waiver schema carries no field for, and resolves the upcoming
week's opponent from the raw Sleeper pairing.

**Commentary:** writes each league-week's prompt into the bundle and folds
in a recap from `<out>/commentary/<slug>_week<N>.md` when one exists. No
Anthropic API call, so no key and no per-run billing; the Claude session
doing the refresh writes the recaps. Past weeks persist on disk.

### FFA-106 — Dashboard Page
**Owner:** Software Engineer

`scripts/dashboard_artifact.py` + `scripts/templates/dashboard.html.tpl`,
following the `{{DATA}}` template pattern `draft_board_artifact.py`
established. Split from FFA-105 so iterating on the page does not re-rank
three leagues of free agents. The bundle is inlined rather than fetched —
a published Artifact's CSP is hostile to outbound requests, and inlining
means the page renders complete on first paint.

The page is organized around a real distinction: week-scoped history
(scoreboard, recap, standings, power rankings, all recomputed for the
selected week) versus decisions for the week about to be played (waiver
board, lineup), which deliberately do not follow the week picker.

**Follow-ups filed as READY (FFA-103, FFA-104, FFA-107)** — all three
measured against live 2026 data, all three worked around at display time in
`build_dashboard.py` rather than patched in `src/`. FFA-107 in particular
was found by observing two players with `injury_status: "Out"` placed in a
recommended starting lineup.

See `docs/dashboard.md` for the refresh workflow and published URL.
