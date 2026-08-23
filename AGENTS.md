# AGENTS.md

## Project Overview

This repository contains a fantasy football analytics application built around Sleeper league data.

The initial development and validation season is **2025**.

The primary Sleeper username used for development is:

```text
schneidbaby
```

The application should begin as a lightweight Python analytics package. Avoid adding a database, web UI, or unnecessary infrastructure until the core data model and analytics are stable.

The project roadmap has seven major parts:

1. Sleeper client
2. League normalization
3. League summary
4. Matchup normalization
5. Matchup analytics
6. Advanced league analytics
7. Advanced player / position analytics

---

# Product Goals

The application should eventually answer questions such as:

- What leagues is a Sleeper user in?
- What are the rules and scoring settings for each league?
- Who are the teams, owners, and players?
- What were the final standings?
- Who played whom each week?
- What is the head-to-head record between any two managers?
- Who had the hardest or easiest schedule?
- Which teams were lucky or unlucky relative to weekly scoring?
- Which teams were strongest at each position?
- Which managers optimized their starting lineups most effectively?
- Which players provided the most value relative to position and replacement level?
- Which players drove specific matchup wins and losses?

The first complete release should focus on retrospective analysis of the **2025 season**.

---

# Architecture Principles

## Source of Truth

Use **Sleeper** as the source of truth for:

- users
- leagues
- league rules
- scoring settings
- roster positions
- owners
- rosters
- weekly matchups
- transactions
- drafts
- playoff brackets
- Sleeper player IDs

For advanced player statistics, use a provider abstraction.

The preferred first external provider is **nflverse**.

Do not tightly couple advanced player analysis to an undocumented Sleeper endpoint.

---

## Separation of Concerns

Keep data access separate from analytics.

Recommended structure:

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

Suggested responsibilities:

```text
sleeper/
    Raw Sleeper API communication and caching.

league/
    League normalization, owner/roster mappings, league snapshots.

matchups/
    Weekly matchup retrieval and matchup normalization.

analytics/
    Standings, head-to-head, all-play, luck, consistency,
    power rankings, and other derived metrics.

players/
    Player-provider interfaces, nflverse integration,
    fantasy scoring, positional analysis, and roster efficiency.
```

---

# Technical Guidelines

- Use Python.
- Prefer simple, typed Python modules.
- Use `requests` for initial Sleeper HTTP access unless there is a strong reason to change.
- Use `pandas` for analytical tables.
- Use ordinary Python dictionaries/dataclasses/domain objects where appropriate.
- Avoid a database for V1.
- Local JSON or Parquet caching is acceptable.
- Public functions should have type hints.
- Public functions should have concise docstrings.
- Keep API/network code isolated from calculations.
- Analytics functions should be deterministic and testable without live HTTP calls.
- Unit tests must not depend on Sleeper being online.
- Use sanitized fixture responses for API-related tests.
- Do not introduce a web framework unless explicitly requested.
- Do not introduce notebooks as the primary implementation path.
- Notebook exploration is acceptable only when it leads to tested package code.
- Prefer small, reviewable commits.
- One feature per commit wherever practical.

---

# Data Modeling Guidelines

Internally prefer immutable IDs over names whenever possible.

For Sleeper:

```text
user_id
roster_id
league_id
player_id
matchup_id
```

Usernames and display names may change and should be treated as labels, not primary keys.

The primary development user is `schneidbaby`, but code must not hard-code that username into library logic.

---

# Core Domain Objects

The application should converge on a normalized league representation such as:

```python
snapshot.league
snapshot.teams_df
snapshot.users_df
snapshot.rosters_df
snapshot.players_df
snapshot.scoring_settings
snapshot.roster_positions
```

A `LeagueSnapshot` or similar abstraction should become the common input to downstream analytics.

---

# Canonical Matchup Dataset

Matchup normalization should ultimately produce a DataFrame with fields similar to:

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

The exact schema may evolve, but downstream analytics should consume normalized data rather than raw Sleeper API responses.

---

# Canonical Player-Week Dataset

Advanced player analysis should eventually converge on a player-week fact table similar to:

```text
season
week
sleeper_player_id
gsis_id
player_name
position
nfl_team

roster_id
fantasy_team

started
bench

passing_yds
passing_tds
rushing_yds
rushing_tds
receptions
receiving_yds
receiving_tds

fantasy_points
```

Do not assume the above list is exhaustive.

Fantasy points should ultimately be calculated using the league's actual Sleeper scoring settings rather than relying only on generic provider fantasy-point columns.

---

# Agent Roles

Agents should behave as one of the following primary roles.

## Software Engineer Agent

Owns:

- project structure
- API clients
- domain models
- caching
- interfaces
- CLI/API surfaces
- error handling
- test infrastructure
- package quality

The Software Engineer Agent should not invent statistical methodology without documenting assumptions.

---

## Data Engineer Agent

Owns:

- nflverse ingestion
- external data-provider adapters
- Sleeper-to-provider player ID mappings
- canonical analytical fact tables
- caching and persistence formats
- data validation and reconciliation

The Data Engineer Agent should optimize for reproducibility and clean schemas before performance.

---

## Data Scientist Agent

Owns:

- metric definitions
- standings-derived metrics
- head-to-head analytics
- all-play records
- expected wins
- schedule luck
- strength of schedule
- consistency
- player value
- roster efficiency
- positional strength
- power-ranking methodology

Every non-trivial metric must have:

1. a written mathematical or procedural definition
2. at least one hand-checkable toy example
3. tests for ties and missing values where applicable
4. explicit regular-season versus playoff behavior

---

# Kanban Workflow

Use the following status flow:

```text
BACKLOG -> READY -> IN PROGRESS -> REVIEW -> DONE
```

A ticket should not move to `DONE` until all acceptance criteria pass.

Agents should work only on tickets that are:

- explicitly assigned, or
- marked `READY`

When completing a ticket, report:

- files changed
- tests added or changed
- commands run
- test results
- any assumptions
- any follow-up tickets discovered

Do not silently expand a ticket into unrelated features.

---

# Definition of Done

Every feature ticket must satisfy:

```text
[ ] implementation complete
[ ] unit tests added or updated
[ ] existing tests pass
[ ] no live API dependency in unit tests
[ ] public functions have useful type hints
[ ] public functions have concise docstrings
[ ] relevant edge cases are handled
[ ] README updated if user-facing behavior changed
[ ] commit scope matches the ticket
```

Analytics tickets must additionally satisfy:

```text
[ ] metric is explicitly defined
[ ] toy example is tested by hand
[ ] tied values are handled
[ ] missing values are handled where relevant
[ ] regular season vs playoff behavior is explicit
```

---

# Epic 1 — Sleeper Client

## FFA-001 — Bootstrap Python Project

**Status:** READY  
**Owner:** Software Engineer

**Suggested commit:**

```text
chore: bootstrap fantasy analyzer project
```

### Scope

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

### Acceptance Criteria

- package installs locally
- `pytest` runs successfully
- formatting/linting configuration exists
- supported Python version is defined
- `requests` and `pandas` are declared dependencies

---

## FFA-002 — Add Base Sleeper HTTP Client

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-001

**Suggested commit:**

```text
feat: add Sleeper API HTTP client
```

### Scope

Implement a reusable `SleeperClient`.

Expected capabilities:

```python
SleeperClient
_get()
timeout handling
HTTP error handling
session reuse
```

### Acceptance Criteria

- successful requests return decoded JSON
- 4xx/5xx responses produce useful exceptions
- timeout behavior is covered by tests
- URL construction is centralized

---

## FFA-003 — Add User and League Discovery

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-002

**Suggested commit:**

```text
feat: add Sleeper user and league discovery
```

### Scope

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

### Acceptance Criteria

- username resolves to permanent Sleeper `user_id`
- 2025 leagues can be retrieved
- nonexistent users are handled cleanly
- no downstream code relies on username as an immutable identifier

---

## FFA-004 — Add Core League Endpoints

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-002

**Suggested commit:**

```text
feat: add Sleeper league roster and user endpoints
```

### Scope

Implement:

```python
get_league()
get_users()
get_rosters()
```

### Acceptance Criteria

The client can retrieve:

- league metadata
- league rules
- scoring settings
- roster positions
- league users
- rosters

---

## FFA-005 — Add Historical Season Endpoints

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-002

**Suggested commit:**

```text
feat: add Sleeper matchup playoff and transaction endpoints
```

### Scope

Implement:

```python
get_matchups()
get_winners_bracket()
get_losers_bracket()
get_transactions()
get_drafts()
get_draft_picks()
```

### Acceptance Criteria

- weekly matchups can be fetched
- playoff brackets can be fetched
- transactions can be fetched
- drafts and draft picks can be fetched
- fixtures cover representative responses

---

## FFA-006 — Add Cached Sleeper Player Catalog

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-002

**Suggested commit:**

```text
feat: add cached Sleeper player catalog
```

### Scope

Implement:

```python
get_players()
load_player_cache()
refresh_player_cache()
```

### Acceptance Criteria

- Sleeper player catalog can be retrieved
- player catalog can be cached locally
- normal analysis does not require repeatedly downloading the full catalog
- cache behavior is tested

---

## FFA-007 — Add Sleeper API Contract Fixtures

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-003, FFA-004, FFA-005, FFA-006

**Suggested commit:**

```text
test: add Sleeper API contract fixtures
```

### Scope

Create sanitized representative API fixtures.

### Acceptance Criteria

- main test suite runs without internet access
- public API parsing behavior is covered by fixtures
- no private or unnecessary personal information is committed

---

# Epic 2 — Normalize League Data

## FFA-010 — Build Team and Owner Mapping

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-004

**Suggested commit:**

```text
feat: normalize Sleeper owners and rosters
```

### Scope

Create stable mappings between:

```text
user_id
roster_id
display_name
team_name
```

### Acceptance Criteria

- each roster can resolve to its owner when available
- missing owners are handled
- display/team names remain labels, not keys

---

## FFA-011 — Normalize League Settings

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-004

**Suggested commit:**

```text
feat: normalize league scoring and roster settings
```

### Scope

Normalize:

- scoring settings
- roster slots
- league size
- playoff configuration
- waiver configuration
- season metadata

### Acceptance Criteria

- downstream code does not need to understand raw Sleeper setting shapes
- scoring and roster settings are available in predictable structures

---

## FFA-012 — Normalize Player Metadata

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-006

**Suggested commit:**

```text
feat: enrich rosters with Sleeper player metadata
```

### Scope

Convert raw Sleeper player IDs into useful player metadata.

Example:

```text
4984 -> Josh Allen | QB | BUF | 4984
```

### Acceptance Criteria

- roster player IDs resolve to metadata when available
- unknown or retired player IDs do not crash normalization

---

## FFA-013 — Build LeagueSnapshot Service

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-010, FFA-011, FFA-012

**Suggested commit:**

```text
feat: add LeagueSnapshot service
```

### Scope

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

### Acceptance Criteria

- one call can construct a normalized league snapshot
- downstream analytics do not need raw endpoint joins
- snapshot construction is tested from fixtures

---

## FFA-014 — Add Normalized Data Tests

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-013

**Suggested commit:**

```text
test: add normalized league data coverage
```

### Acceptance Criteria

- owner/roster mapping tested
- scoring normalization tested
- missing owner/player cases tested
- normalized schemas tested

---

# Epic 3 — League Summary

## FFA-020 — Build Base Standings

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-013

**Suggested commit:**

```text
feat: add league standings analysis
```

### Metrics

- wins
- losses
- ties
- win percentage
- points for
- points against
- point differential

### Acceptance Criteria

- standings reconcile to Sleeper roster records
- ties are handled
- ranking rules are documented

---

## FFA-021 — Add Scoring Summary Metrics

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-020

**Suggested commit:**

```text
feat: add league scoring summary metrics
```

### Metrics

- points per game
- points against per game
- scoring rank
- average margin
- high score
- low score

---

## FFA-022 — Identify Regular Season and Playoff Boundaries

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-011

**Suggested commit:**

```text
feat: derive regular season and playoff boundaries
```

### Acceptance Criteria

- regular-season weeks are explicit
- playoff weeks are explicit
- downstream analytics can filter either period reliably

---

## FFA-023 — Build League Summary API

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-020, FFA-021, FFA-022

**Suggested commit:**

```text
feat: add league summary service
```

Expected interface:

```python
analysis.league_summary()
analysis.standings()
```

---

## FFA-024 — Add CLI League Summary

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-023

**Suggested commit:**

```text
feat: add CLI league summary
```

### Goal

Allow a simple local command to inspect a 2025 league before any UI exists.

---

# Epic 4 — Normalize Matchups

## FFA-030 — Load Full Season Matchups

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-005, FFA-022

**Suggested commit:**

```text
feat: load full season of Sleeper matchups
```

### Acceptance Criteria

- all relevant 2025 weeks can be loaded
- week metadata is retained
- playoff status is retained

---

## FFA-031 — Pair Opponents by Matchup ID

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-030

**Suggested commit:**

```text
feat: pair weekly opponents by matchup id
```

### Acceptance Criteria

- two teams sharing a matchup ID are paired
- incomplete/bye-like cases are handled explicitly
- pairing logic is unit tested

---

## FFA-032 — Normalize Matchup Outcomes

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-031

**Suggested commit:**

```text
feat: normalize fantasy matchup outcomes
```

### Derive

- winner
- loser
- tie
- margin
- score differential

---

## FFA-033 — Build Season Matchup DataFrame

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-032

**Suggested commit:**

```text
feat: build season matchup dataframe
```

### Target Schema

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

## FFA-034 — Reconcile Matchups to Standings

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-033

**Suggested commit:**

```text
test: reconcile weekly matchups to season standings
```

### Acceptance Criteria

Derived:

- wins
- losses
- points for
- points against

must reconcile to Sleeper season records within explicitly documented tolerances.

---

# Epic 5 — User-vs-User Matchup Analytics

## FFA-040 — Head-to-Head Records

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-033

**Suggested commit:**

```text
feat: add manager head-to-head records
```

### Metrics

- meetings
- wins
- losses
- ties
- total points
- average points
- average opponent points

---

## FFA-041 — Head-to-Head Matrix

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-040

**Suggested commit:**

```text
feat: add league head-to-head matrix
```

Example output:

```text
        Alec   Mike   Joe
Alec      —     3-2   2-0
Mike     2-3     —    1-2
Joe      0-2    2-1    —
```

---

## FFA-042 — Rivalry and Margin Statistics

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-040

**Suggested commit:**

```text
feat: add rivalry and matchup margin metrics
```

### Metrics

- average margin
- closest game
- largest win
- largest loss
- highest scoring matchup

---

## FFA-043 — Add Matchup History Query API

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-040, FFA-041, FFA-042

**Suggested commit:**

```text
feat: add matchup history query service
```

Expected interface:

```python
analysis.head_to_head(team_a, team_b)
analysis.head_to_head_matrix()
```

---

## FFA-044 — Split Regular Season and Playoff H2H

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-022, FFA-040

**Suggested commit:**

```text
feat: split head-to-head results by season phase
```

---

# Epic 6 — Advanced League Analytics

## FFA-050 — Weekly Scoring Ranks

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-033

**Suggested commit:**

```text
feat: add weekly scoring ranks
```

---

## FFA-051 — All-Play Records

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-050

**Suggested commit:**

```text
feat: add all-play standings
```

For each week, calculate how a team would have performed against every other team.

---

## FFA-052 — Expected Wins and Schedule Luck

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-051

**Suggested commit:**

```text
feat: add expected wins and schedule luck
```

### Example

```text
Actual Record:     8-6
Expected Record:  10.0-4.0
Schedule Luck:    -2.0 wins
```

The exact expected-wins formulation must be documented and tested.

---

## FFA-053 — Team Consistency Metrics

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-050

**Suggested commit:**

```text
feat: add team consistency metrics
```

Potential metrics:

- weekly standard deviation
- coefficient of variation where appropriate
- median score
- scoring floor
- scoring ceiling
- boom/bust frequency

---

## FFA-054 — Strength of Schedule

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-033

**Suggested commit:**

```text
feat: add strength of schedule metrics
```

Definitions must be documented before implementation.

---

## FFA-055 — Normalize Playoff Bracket and Final Placements

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-005

**Suggested commit:**

```text
feat: normalize playoff bracket and final placements
```

---

## FFA-056 — League Power Ranking Model

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-050, FFA-051, FFA-052, FFA-053, FFA-054, FFA-055

**Suggested commit:**

```text
feat: add league power ranking model
```

Do not build an opaque score.

The model must document:

- included features
- weights or estimation method
- scaling
- tie-breaking
- interpretation

---

## FFA-057 — Advanced League Analytics API

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-051 through FFA-056

**Suggested commit:**

```text
feat: expose advanced league analytics
```

Expected interfaces may include:

```python
analysis.all_play()
analysis.schedule_luck()
analysis.consistency()
analysis.strength_of_schedule()
analysis.power_rankings()
```

---

# Epic 7 — Advanced Player / Position Analytics

## FFA-060 — Define Player Data Provider Interface

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-012

**Suggested commit:**

```text
feat: define player data provider interface
```

### Goal

Prevent the analytics layer from depending directly on nflverse or any other single provider.

---

## FFA-061 — Add nflverse Weekly Stat Provider

**Status:** BACKLOG  
**Owner:** Data Engineer  
**Depends on:** FFA-060

**Suggested commit:**

```text
feat: add nflverse weekly player stats provider
```

---

## FFA-062 — Build Sleeper to nflverse Player ID Crosswalk

**Status:** BACKLOG  
**Owner:** Data Engineer  
**Depends on:** FFA-061

**Suggested commit:**

```text
feat: map Sleeper player ids to nflverse ids
```

Prefer explicit ID mappings over fuzzy name matching.

---

## FFA-063 — Build League-Specific Fantasy Scoring Engine

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-011, FFA-061

**Suggested commit:**

```text
feat: calculate fantasy points from league scoring rules
```

### Acceptance Criteria

- scoring is derived from the actual league configuration
- representative scoring categories are tested
- unsupported scoring fields are surfaced clearly

---

## FFA-064 — Build Player-Week Fact Table

**Status:** BACKLOG  
**Owner:** Data Engineer  
**Depends on:** FFA-062, FFA-063

**Suggested commit:**

```text
feat: build player-week fantasy fact table
```

This becomes the foundation for all player analytics.

---

## FFA-065 — Player Performance Metrics

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-064

**Suggested commit:**

```text
feat: add player performance analytics
```

### Metrics

- weekly fantasy points
- points per game
- median score
- volatility
- ceiling
- floor
- boom rate
- bust rate

---

## FFA-066 — Position Strength Analytics

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-065

**Suggested commit:**

```text
feat: add positional strength analytics
```

### Analyze

- QB production
- RB production
- WR production
- TE production
- positional league rank
- share of roster scoring
- positional depth
- positional consistency

---

## FFA-067 — Optimal Lineup and Roster Efficiency

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-064

**Suggested commit:**

```text
feat: add optimal lineup and roster efficiency
```

### Metrics

- actual starter score
- optimal legal lineup score
- points left on bench
- lineup efficiency percentage
- frequency of suboptimal start/sit decisions

The optimizer must respect league roster-position rules.

---

## FFA-068 — Replacement-Level Player Value

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-065

**Suggested commit:**

```text
feat: add replacement-level player value
```

Possible outputs:

- points above positional average
- points above replacement
- positional scarcity
- league-relative player value

Replacement-level methodology must be explicitly documented.

---

## FFA-069 — Matchup Player Contribution Analysis

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-033, FFA-064

**Suggested commit:**

```text
feat: add player matchup contribution analysis
```

Analyze:

- which players drove a win or loss
- positional advantages
- player contribution to margin
- best and worst starters

---

## FFA-070 — Manager Lineup Tendencies

**Status:** BACKLOG  
**Owner:** Data Scientist  
**Depends on:** FFA-067

**Suggested commit:**

```text
feat: add manager lineup tendency analytics
```

Analyze:

- FLEX usage
- roster construction
- bench allocation
- start/sit tendencies
- waiver-player utilization
- positional preferences

---

## FFA-071 — Player Analytics API

**Status:** BACKLOG  
**Owner:** Software Engineer  
**Depends on:** FFA-065 through FFA-070

**Suggested commit:**

```text
feat: expose player and positional analytics
```

Expected DataFrames may include:

```python
analysis.player_weekly_df
analysis.player_season_df
analysis.position_summary_df
analysis.roster_efficiency_df
analysis.player_value_df
```

---

## FFA-072 — Projection and Ranking Provider Interface

**Status:** BACKLOG  
**Owner:** Data Engineer  
**Depends on:** FFA-071

**Suggested commit:**

```text
feat: add projection and ranking provider interface
```

### Goal

Enable future:

- projections
- rest-of-season rankings
- waiver recommendations
- trade values
- start/sit recommendations
- opponent adjustments

Do not implement vendor-specific logic until the interface is stable.

---

# Release Boundaries

## V1 MVP

Tickets:

```text
FFA-001 through FFA-057
```

V1 should answer:

- what leagues exist
- league rules and scoring
- league rosters
- standings
- full matchup history
- user-vs-user records
- scoring ranks
- all-play standings
- expected wins
- schedule luck
- consistency
- strength of schedule
- playoff results
- power rankings

---

## V1.5 — Player Intelligence

Tickets:

```text
FFA-060 through FFA-072
```

Adds:

- player performance
- positional strength
- roster efficiency
- player value
- matchup player contributions
- manager tendencies
- future projection-provider support

---

# Dependency Strategy

Do not parallelize too aggressively at the beginning.

Recommended initial sequence:

```text
FFA-001
   |
FFA-002
   |
   +--> FFA-003
   +--> FFA-004
   +--> FFA-005
   +--> FFA-006
```

Then:

```text
FFA-004 + FFA-006
        |
FFA-010 + FFA-011 + FFA-012
        |
      FFA-013
```

The first useful vertical milestone is:

```text
FFA-001
   |
FFA-002
   |
FFA-003 + FFA-004
   |
FFA-010 + FFA-011
   |
FFA-013
   |
FFA-020
   |
FFA-023

OUTPUT:
Working 2025 league summary
```

The matchup branch can then proceed in parallel:

```text
FFA-005
   |
FFA-030
   |
FFA-031
   |
FFA-032
   |
FFA-033
  /     \
Epic 5  Epic 6
```

Part 7 should begin only after league-specific scoring and matchup structures are trusted.

---

# Current Kanban Board

## READY

### FFA-001 — Bootstrap Python Project

This is the next ticket to implement.

---

## BACKLOG

```text
FFA-002 through FFA-072
```

Tickets become READY when their dependencies are complete and reviewed.

---

## IN PROGRESS

None.

---

## REVIEW

None.

---

## DONE

None.

---

# Instructions for Codex and Other Coding Agents

When given a ticket:

1. Read this file before making changes.
2. Work only on the requested ticket.
3. Inspect the repository before deciding implementation details.
4. Reuse existing abstractions rather than creating parallel ones.
5. Do not rewrite unrelated code.
6. Do not implement downstream backlog features unless required by the current ticket.
7. Add or update tests with the implementation.
8. Run the relevant test suite.
9. Run formatting/linting checks if configured.
10. Summarize exactly what changed.

Before marking work complete, respond with:

```text
Ticket:
Status:

Implementation:
- ...

Files changed:
- ...

Tests:
- ...

Commands run:
- ...

Assumptions:
- ...

Follow-up:
- ...
```

If a requested ticket conflicts with an established architecture decision in this file, flag the conflict instead of silently changing the architecture.

If the repository state makes a ticket impossible exactly as written, make the smallest reasonable adjustment and clearly document it.

---

# Initial Development Target

The initial working dataset is:

```text
Sleeper username: schneidbaby
Season: 2025
Sport: NFL
```

The application must support arbitrary Sleeper users and leagues despite using this account as the initial development and validation case.

The first implementation task is:

```text
FFA-001 — Bootstrap Python Project
```
