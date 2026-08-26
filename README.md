# Fantasy Football Analyzer

A lightweight Python analytics package for fantasy football leagues hosted on
[Sleeper](https://sleeper.com). See `AGENTS.md` for the full project roadmap,
architecture principles, and ticket-based workflow. API reference and usage
guides live under [`docs/`](docs/): [`docs/league.md`](docs/league.md) (the
`league/` layer), [`docs/matchups.md`](docs/matchups.md) (the `matchups/`
layer), [`docs/analytics.md`](docs/analytics.md) (the `analytics/` layer),
and the `players/` layer, split across [`docs/players-data.md`](docs/players-data.md)
(ingestion: nflverse, scoring, the player-week fact table) and
[`docs/players-analytics.md`](docs/players-analytics.md) (performance,
position strength, lineup efficiency, player value, matchup contribution,
and lineup tendencies).

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

## Notebook

`notebooks/league_walkthrough.ipynb` walks through the league and matchup
analytics against your own live Sleeper data -- league discovery, the
`LeagueSnapshot`, standings, the full matchup normalization pipeline,
head-to-head history, and the Epic 6 advanced league analytics (all-play,
schedule luck, consistency, strength of schedule, power rankings, playoff
brackets). See the notebook's first cell for kernel setup.

`notebooks/roster_analysis.ipynb` runs a full end-to-end roster analysis
for one team's season -- player value, position strength, weekly lineup
efficiency, matchup player contribution, and lineup tendencies (Epic 7,
FFA-064 through FFA-070) -- then applies the same analysis to every team in
the league and compares them with charts (power ranking, lineup
efficiency, schedule luck, a position-strength heatmap, and roster
composition). Also needs the `matplotlib` dev extra; see the notebook's
first cell for kernel setup.
