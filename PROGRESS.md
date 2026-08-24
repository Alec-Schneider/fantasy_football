# Progress

_Last updated by project-tracker: 2026-08-24_

## Current state

Epics 1 through 6 (FFA-001 through FFA-057) are fully shipped and verified against actual code/tests, except **FFA-044** ("Split Regular Season and Playoff H2H"), which remains BACKLOG — the codebase explicitly defers it (see `src/fantasy_analyzer/analytics/head_to_head.py`). Epic 7 has now shipped through FFA-067: provider interface (FFA-060), nflverse provider (FFA-061), ID crosswalk (FFA-062), scoring engine (FFA-063), player-week fact table (FFA-064), performance metrics (FFA-065), position strength (FFA-066), and optimal lineup / roster efficiency (FFA-067). **FFA-068** ("Replacement-Level Player Value") is READY since its only dependency, FFA-065, is DONE. FFA-069 and FFA-070 are unblocked on paper but held in BACKLOG per the sequencing convention; FFA-071 and FFA-072 remain blocked. Two tickets, **FFA-007** and **FFA-014**, have no commit whose message matches their suggested one, but their acceptance criteria are genuinely satisfied — the work was absorbed into the commits for the tickets they support (fixtures landed alongside each endpoint's own commit; normalized-data tests landed alongside FFA-010/011/012/013's own commits) rather than shipped as a separate commit. This run also backfilled the archive entries for FFA-061 through FFA-066, which earlier chore runs compacted out of AGENTS.md without archiving (their original ticket text was recovered verbatim from AGENTS.md git history).

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
