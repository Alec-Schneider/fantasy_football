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

- **FFA-001** — Bootstrap Python Project — DONE (`0c2889a`) — see PROGRESS.md
- **FFA-002** — Add Base Sleeper HTTP Client — DONE (`e7dcbf5`) — see PROGRESS.md
- **FFA-003** — Add User and League Discovery — DONE (`7f1d689`) — see PROGRESS.md
- **FFA-004** — Add Core League Endpoints — DONE (`a9ef6ec`) — see PROGRESS.md
- **FFA-005** — Add Historical Season Endpoints — DONE (`d3db957`) — see PROGRESS.md
- **FFA-006** — Add Cached Sleeper Player Catalog — DONE (`a33d0d7`) — see PROGRESS.md
- **FFA-007** — Add Sleeper API Contract Fixtures — DONE (absorbed into per-endpoint commits) — see PROGRESS.md

---

# Epic 2 — Normalize League Data

- **FFA-010** — Build Team and Owner Mapping — DONE (`bf0bf79`) — see PROGRESS.md
- **FFA-011** — Normalize League Settings — DONE (`ef3340e`) — see PROGRESS.md
- **FFA-012** — Normalize Player Metadata — DONE (`63d40df`) — see PROGRESS.md
- **FFA-013** — Build LeagueSnapshot Service — DONE (`e5e5428`) — see PROGRESS.md
- **FFA-014** — Add Normalized Data Tests — DONE (absorbed into FFA-010/011/012/013 commits) — see PROGRESS.md

---

# Epic 3 — League Summary

- **FFA-020** — Build Base Standings — DONE (`f1e4ce1`) — see PROGRESS.md
- **FFA-021** — Add Scoring Summary Metrics — DONE (`069c82c`) — see PROGRESS.md
- **FFA-022** — Identify Regular Season and Playoff Boundaries — DONE (`3423eef`) — see PROGRESS.md
- **FFA-023** — Build League Summary API — DONE (`b0afc8a`) — see PROGRESS.md
- **FFA-024** — Add CLI League Summary — DONE (`ac37952`) — see PROGRESS.md

---

# Epic 4 — Normalize Matchups

- **FFA-030** — Load Full Season Matchups — DONE (`ecb0182`) — see PROGRESS.md
- **FFA-031** — Pair Opponents by Matchup ID — DONE (`0522af8`) — see PROGRESS.md
- **FFA-032** — Normalize Matchup Outcomes — DONE (`00dba42`) — see PROGRESS.md
- **FFA-033** — Build Season Matchup DataFrame — DONE (`d4b9d4e`) — see PROGRESS.md
- **FFA-034** — Reconcile Matchups to Standings — DONE (`c718115`) — see PROGRESS.md

---

# Epic 5 — User-vs-User Matchup Analytics

- **FFA-040** — Head-to-Head Records — DONE (`ea5307f`) — see PROGRESS.md
- **FFA-041** — Head-to-Head Matrix — DONE (`429e512`) — see PROGRESS.md
- **FFA-042** — Rivalry and Margin Statistics — DONE (`ecedc16`) — see PROGRESS.md
- **FFA-043** — Add Matchup History Query API — DONE (`610a9e4`) — see PROGRESS.md

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

- **FFA-050** — Weekly Scoring Ranks — DONE (`778a56b`) — see PROGRESS.md
- **FFA-051** — All-Play Records — DONE (`4fe92e9`) — see PROGRESS.md
- **FFA-052** — Expected Wins and Schedule Luck — DONE (`c30aa36`) — see PROGRESS.md
- **FFA-053** — Team Consistency Metrics — DONE (`caefabc`) — see PROGRESS.md
- **FFA-054** — Strength of Schedule — DONE (`df35d07`) — see PROGRESS.md
- **FFA-055** — Normalize Playoff Bracket and Final Placements — DONE (`5b5acd1`) — see PROGRESS.md
- **FFA-056** — League Power Ranking Model — DONE (`d2d9718`) — see PROGRESS.md
- **FFA-057** — Advanced League Analytics API — DONE (`f134398`) — see PROGRESS.md

---

# Epic 7 — Advanced Player / Position Analytics

- **FFA-060** — Define Player Data Provider Interface — DONE (`098cff1`) — see PROGRESS.md
- **FFA-061** — Add nflverse Weekly Stat Provider — DONE (`635eff8`) — see PROGRESS.md
- **FFA-062** — Build Sleeper to nflverse Player ID Crosswalk — DONE (`85058c4`) — see PROGRESS.md
- **FFA-063** — Build League-Specific Fantasy Scoring Engine — DONE (`2513d33`) — see PROGRESS.md
- **FFA-064** — Build Player-Week Fact Table — DONE (`a106cf9`) — see PROGRESS.md
- **FFA-065** — Player Performance Metrics — DONE (`60e6c9d`) — see PROGRESS.md
- **FFA-066** — Position Strength Analytics — DONE (`0774b17`) — see PROGRESS.md
- **FFA-067** — Optimal Lineup and Roster Efficiency — DONE (`e619eb7`) — see PROGRESS.md
- **FFA-068** — Replacement-Level Player Value — DONE (`eff25d7`, hardened `b18c5e0`) — see PROGRESS.md

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

**Status:** IN PROGRESS  
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

None.

---

## BACKLOG

```text
FFA-044, FFA-069, FFA-070, FFA-072
```

FFA-044 is unblocked on paper (FFA-022 and FFA-040 are both DONE) but is
intentionally left in BACKLOG rather than READY here since it is not the
next ticket in the recommended sequence; an agent may still pick it up if
explicitly assigned. FFA-069 (deps FFA-033, FFA-064) and FFA-070 (dep
FFA-067) are likewise unblocked on paper and stay in BACKLOG for the same
reason; FFA-072 remains blocked behind FFA-071.

Tickets become READY when their dependencies are complete and reviewed.

---

## IN PROGRESS

### FFA-071 — Player Analytics API

Its dependency, FFA-068, is DONE. Every DataFrame the ticket expects
(`player_weekly_df`, `player_season_df`, `position_summary_df`,
`roster_efficiency_df`, `player_value_df`) is produced by FFA-065 through
FFA-068, all DONE; the FFA-069 and FFA-070 frames can be added to the API
when those tickets land.

---

## REVIEW

None.

---

## DONE

FFA-001 through FFA-057, FFA-060 through FFA-068 — see PROGRESS.md.

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
