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

# Canonical Player-Week Dataset

Provider output and the player-week fact table converge on this schema. It is
normative: `players/provider.py` and `players/player_week.py` cite it as the
contract every provider must satisfy, so it is stated here rather than in any
one module.

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

---

# Normalized Data Contracts

A `LeagueSnapshot` or similar abstraction should become the common input to
downstream analytics. Matchup normalization and player-week analysis should
each converge on a single canonical frame. The concrete schemas live in the
code and its docstrings (`league/snapshot.py`, `matchups/outcomes.py`,
`players/`); the contracts that the code cannot state for itself are:

- Downstream analytics should consume normalized data rather than raw
  Sleeper API responses.
- Fantasy points should ultimately be calculated using the league's actual
  Sleeper scoring settings rather than relying only on generic provider
  fantasy-point columns.

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

Every non-trivial metric must meet the analytics bar in Definition of Done
below. This applies to metrics in `players/` as much as `analytics/`.

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

# Epics 1–7 — Shipped

All of Epics 1 through 7 are DONE: FFA-001–FFA-057 (Sleeper client, league
normalization, league summary, matchup normalization, matchup analytics,
advanced league analytics), FFA-060–FFA-074 and FFA-084–FFA-086 (player and
position analytics). Per-ticket acceptance criteria, implementation notes and
commit SHAs are archived in `PROGRESS.md`.

---

# Epic 8 — League & Matchup Commentary

FFA-090–FFA-094 are DONE — see `PROGRESS.md`. See
`docs/commentary_plan.md` for the full design. Two notes that outlived the
tickets: FFA-091 intentionally omits the milestone/clinch-elimination field
(no playoff-boundary logic exists yet to support it), and FFA-094 settled on
default model `claude-opus-4-8` at `effort="high"`.

---

# Epic 9 — Waiver-Wire Decision Support

Hardens the FFA-091/092/093 free-agent pipeline (four defects found while
running a real 2026 week-1 board, all measured before being fixed) and adds
the three context layers a waiver decision actually needs: usage, opponent,
and the manager's own roster. FFA-095–FFA-101 are DONE — see `PROGRESS.md`.

---

# Epic 10 — Season Dashboard

One published page covering all three leagues: week-by-week results,
standings, recaps and power rankings, plus the waiver board and lineup call
for the week about to be played. See `docs/dashboard.md` for the refresh
workflow and the published URL.

- **FFA-102** — As-of-Week Standings from Matchups — DONE — `build_standings_through_week`
  in `analytics/standings.py`. `build_standings` reads Sleeper's
  season-cumulative roster counters and structurally cannot describe a past
  week; this re-derives every counter from the week-level matchup frame.
  Explicit regular-season-vs-playoff switch, explicit bye/incomplete rule.
  Tests in `tests/analytics/test_standings_through_week.py`.
- **FFA-105** — Dashboard Bundle Builder — DONE — `scripts/build_dashboard.py`
  composes the existing pipelines into one JSON bundle per season.
- **FFA-106** — Dashboard Page — DONE — `scripts/dashboard_artifact.py` plus
  `scripts/templates/dashboard.html.tpl`, following the `{{DATA}}` pattern
  `draft_board_artifact.py` established.
- **FFA-111** — Opportunity-First ROS Projection — DONE —
  `players/usage_projection.py`, fitted by `scripts/fit_usage_model.py`.
  `projected_ppg` for QB/RB/WR/TE is a per-position blend of a usage model
  and the EB projection. It beat EB at every position in a rolling-origin
  backtest (`docs/valuation-model.md`). Wired into the dashboard's board and
  lineup and into the `free-agents` CLI.
- **FFA-104** — Absent-Prior Projection — DONE — a player with no games and
  fewer than 4 prior-season games gets a fitted absent-prior line (or
  `DEFAULT_ABSENT_PRIOR_RATIO` × the positional mean without a usage model),
  not the positional mean. `WAIVER_QUALITY_FILTER` and `RAW_WAIVER_DEPTH`
  were removed from `build_dashboard.py`.

- **FFA-103** — Teamless players — DONE — the free-agent half of
  `build_player_universe` requires an NFL team (`require_nfl_team`).
- **FFA-107** — Injury/bye awareness — DONE — `players/availability.py`;
  the lineup and the add/drop horizon honor it.
- **FFA-108** — Week completeness — DONE — a week is final only once every
  scheduled NFL game has a score (`completed_nfl_weeks`).

Known follow-ups, none blocking:

- `DEFAULT_DVP_SHRINKAGE_GAMES` (FFA-099) is a documented prior, not a
  fitted value. No backtest measures defense-vs-position accuracy; fitting
  it the way FFA-089/090 fit `n0` is the natural next ticket.
- The three caches (`sleeper/players.json`, `nflverse/player_stats_<season>.csv`,
  `id_crosswalk/db_playerids.csv`) are still never TTL-checked. A stale
  catalog silently produces wrong teams and injury statuses.

---

# Epic 11 — Matchup Tab

All tickets are DONE. This epic added a Matchup tab, now the default, for
the week being played:

- my Sleeper-set lineup against my opponent's, slot by slot, with live
  points and projected finals
- a calibrated win probability
- positional edges, lineup alerts, and a season-to-date comparison.

The design and the bundle contract are in `docs/matchup_tab.md`. The
user-facing description is in `docs/dashboard.md` under "The Matchup tab".

- **FFA-113** — Matchup lineup projection — DONE — `nfl_game_states`
  (`players/opponent_strength.py`) and `players/matchup_projection.py`.
- **FFA-114** — Win probability — DONE — `players/win_probability.py`,
  fitted by `scripts/fit_win_probability.py`. The SD is `c_pos * sqrt(proj)`,
  summed over pending starters, with `lambda` 0.987. On 203 games from the
  three leagues' 2025 seasons it scores Brier 0.234 against a coin flip's
  0.250. `lambda` is weakly identified (bootstrap 0.61–1.85). The results
  are in `docs/win-probability.md`. The parameters file lives in the
  gitignored `.cache/nflverse/`, so rerun the script if the projection
  pipeline changes.
- **FFA-115** — Matchup comparison — DONE — `analytics/matchup_preview.py`
  and `build_sleeper_scored_player_weeks` (`players/player_week.py`).
- **FFA-116** — Bundle wiring — DONE — the `matchup` key in
  `scripts/build_dashboard.py`. The win probability is published only from
  calibrated parameters and only from week 2 on.
- **FFA-117** — Matchup tab page — DONE — `dashboard.html.tpl`.
- **FFA-118** — Docs and board — DONE.

Follow-ups, none blocking:

- All-time head-to-head across seasons via `previous_league_id`.
- Box scores for past weeks on the Season tab, from Sleeper's
  `starters_points`.
- The win probability is uncalibrated for week 1 and for games in progress.
  A game in progress is scored at its live points, which overstates
  certainty mid-game.

---

# Current Kanban Board

## IN PROGRESS

None.

## READY

None.

---

## BACKLOG

None.

Tickets become READY when their dependencies are complete and reviewed.

---

## REVIEW

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
