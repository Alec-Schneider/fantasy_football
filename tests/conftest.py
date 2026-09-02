"""Shared pytest fixtures and helpers."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str):
    """Load and parse a JSON fixture from the tests/fixtures directory."""
    path = FIXTURES_DIR.joinpath(*parts)
    return json.loads(path.read_text())


@pytest.fixture
def load_sleeper_fixture():
    """Return a callable that loads a sanitized Sleeper API fixture by name."""

    def _load(filename: str):
        return load_fixture("sleeper", filename)

    return _load


@pytest.fixture
def nflverse_fixture_path() -> Path:
    """Path to the sanitized nflverse player-stats CSV fixture."""
    return FIXTURES_DIR / "nflverse" / "player_stats.csv"


@pytest.fixture
def nflverse_games_fixture_path() -> Path:
    """Path to the sanitized nflverse games/schedule CSV fixture."""
    return FIXTURES_DIR / "nflverse" / "games.csv"


@pytest.fixture
def id_crosswalk_fixture_path() -> Path:
    """Path to the sanitized DynastyProcess player-ID crosswalk CSV fixture."""
    return FIXTURES_DIR / "id_crosswalk" / "db_playerids.csv"
