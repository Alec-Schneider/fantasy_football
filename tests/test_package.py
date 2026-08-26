"""Sanity checks that the fantasy_analyzer package is installed and importable."""

import fantasy_analyzer
import fantasy_analyzer.players

#: The team-defense input path (nflverse_schedule_client, nflverse_schedule_cache,
#: points_allowed, nflverse_defense), which was the one part of ``players/`` missing
#: from the package's ``__all__``. ``DEFAULT_CACHE_DIR`` is aliased on the way out
#: because ``nflverse_cache`` already exports one under
#: ``NFLVERSE_DEFAULT_CACHE_DIR``.
TEAM_DEFENSE_EXPORTS = [
    "NflverseScheduleClient",
    "NFLVERSE_SCHEDULE_DEFAULT_CACHE_DIR",
    "load_games_cache",
    "refresh_games_cache",
    "get_games_cached",
    "NflverseScheduleProvider",
    "POINTS_ALLOWED_COLUMNS",
    "normalize_points_allowed",
    "NflverseTeamDefenseProvider",
    "TEAM_CODE_ALIASES",
    "TEAM_DEFENSE_RAW_STAT_COLUMNS",
    "build_team_defense_stats",
]


def test_package_imports() -> None:
    """The top-level package should import without error."""
    assert fantasy_analyzer is not None


def test_players_team_defense_exports_are_public() -> None:
    """The team-defense input path should be listed in ``players.__all__``."""
    exported = fantasy_analyzer.players.__all__

    missing = [name for name in TEAM_DEFENSE_EXPORTS if name not in exported]
    assert missing == []


def test_players_team_defense_exports_are_importable() -> None:
    """Every team-defense name in ``__all__`` should resolve on the package."""
    unresolved = [
        name
        for name in TEAM_DEFENSE_EXPORTS
        if not hasattr(fantasy_analyzer.players, name)
    ]
    assert unresolved == []


def test_players_all_entries_resolve() -> None:
    """No name in ``players.__all__`` should be stale or duplicated."""
    exported = fantasy_analyzer.players.__all__

    assert [
        name for name in exported if not hasattr(fantasy_analyzer.players, name)
    ] == []
    assert len(exported) == len(set(exported))
