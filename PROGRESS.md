# Progress

_Last updated by project-tracker: 2026-08-24_

## Current state

Epics 1 through 6 (FFA-001 through FFA-057) are fully shipped and verified against actual code/tests, except **FFA-044** ("Split Regular Season and Playoff H2H"), which remains BACKLOG — the codebase explicitly defers it (see `src/fantasy_analyzer/analytics/head_to_head.py`). Epic 7 has now shipped through FFA-072, plus FFA-069: provider interface (FFA-060), nflverse provider (FFA-061), ID crosswalk (FFA-062), scoring engine (FFA-063), player-week fact table (FFA-064), performance metrics (FFA-065), position strength (FFA-066), optimal lineup / roster efficiency (FFA-067), replacement-level player value (FFA-068), player analytics API (FFA-071), projection/ranking provider interface (FFA-072), and matchup player contribution analysis (FFA-069). FFA-070 ("Manager Lineup Tendencies") has since shipped as `1d6b98b`, and FFA-073 ("League-Wide Composite Player Value Ranking") — a ticket raised by the repo owner after this summary was written, not in the original roadmap — shipped as `570429b`/`32dbcaa`/`6629f59`; both entries are archived below, but the rest of this paragraph predates them and reflects the 2026-08-24 project-tracker run. Two tickets, **FFA-007** and **FFA-014**, have no commit whose message matches their suggested one, but their acceptance criteria are genuinely satisfied — the work was absorbed into the commits for the tickets they support (fixtures landed alongside each endpoint's own commit; normalized-data tests landed alongside FFA-010/011/012/013's own commits) rather than shipped as a separate commit. This run also backfilled the archive entries for FFA-061 through FFA-066, which earlier chore runs compacted out of AGENTS.md without archiving (their original ticket text was recovered verbatim from AGENTS.md git history).

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
