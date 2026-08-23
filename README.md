# Fantasy Football Analyzer

A lightweight Python analytics package for fantasy football leagues hosted on
[Sleeper](https://sleeper.com). See `AGENTS.md` for the full project roadmap,
architecture principles, and ticket-based workflow.

The initial development and validation season is **2025**, using the Sleeper
username `schneidbaby` as the primary development account. The application is
built to support arbitrary Sleeper users and leagues.

## Project layout

```text
src/
└── fantasy_analyzer/
    ├── sleeper/     # Raw Sleeper API communication and caching
    ├── league/      # League normalization, owner/roster mappings, snapshots
    ├── matchups/    # Weekly matchup retrieval and normalization
    ├── analytics/   # Standings, head-to-head, all-play, luck, power rankings
    └── players/     # Player-provider interfaces, nflverse, scoring, roster efficiency
tests/
```

## Development setup

Create a virtual environment and install the package in editable mode with
its development dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Run the test suite:

```bash
.venv/bin/pytest
```

Run lint/format checks:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

## CLI

Once installed, a `fantasy-analyzer` console script is available for quick
local inspection of a Sleeper league:

```bash
# Find your league_id by listing a user's leagues for a season.
fantasy-analyzer leagues schneidbaby --season 2025

# Print standings and scoring summary for a league.
fantasy-analyzer summary <league_id> --total-weeks 18
```
