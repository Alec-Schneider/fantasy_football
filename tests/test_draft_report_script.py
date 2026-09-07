"""Tests for ``scripts/draft_report_2026.py`` (FFA-081/082/083).

Follows ``tests/test_cli.py``'s convention: all Sleeper HTTP access is
mocked with ``requests_mock`` against the sanitized fixtures under
``tests/fixtures/sleeper/`` -- no live Sleeper dependency. The draft-market
pipeline (``get_draft_market_player_pool_cached``) and the FFA-073
retrospective CSV loader (``load_prior``) are monkeypatched directly on the
imported script module, mirroring how ``tests/players/test_draft_market_cache.py``
avoids the live FFC/DynastyProcess vendor network -- no vendor HTTP calls
are made either.

``scripts/`` is not a package (same as ``composite_ranking_report.py``'s own
sibling-script imports), so this file inserts it onto ``sys.path`` before
importing ``draft_report_2026``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import draft_report_2026 as report_script  # noqa: E402

import fantasy_analyzer.league.snapshot as snapshot_module  # noqa: E402
from fantasy_analyzer.players.draft_grade import SCORED_DRAFT_PICK_COLUMNS  # noqa: E402
from fantasy_analyzer.players.draft_market import (  # noqa: E402
    DRAFT_MARKET_POOL_COLUMNS,
)
from fantasy_analyzer.sleeper.client import SleeperClient  # noqa: E402

DRAFT_ID = "999999999999999999"


def _mock_draft_endpoints(
    m: requests_mock_lib.Mocker, load_sleeper_fixture, league_id: str
) -> None:
    """Mock every Sleeper endpoint ``run_one_league`` touches for one league.

    Reuses the fixtures the rest of the suite already relies on
    (``league.json``/``users.json``/``rosters.json``/``drafts.json``/
    ``draft_picks.json``) regardless of ``league_id`` in the URL -- the
    fixture bodies' own internal ``league_id``/``draft_id`` fields are not
    read against the URL, so the same fixture content can be reused for a
    second "different" league in the multi-league tests below.
    """
    m.get(
        f"{SleeperClient.BASE_URL}/league/{league_id}",
        json=load_sleeper_fixture("league.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/league/{league_id}/users",
        json=load_sleeper_fixture("users.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/league/{league_id}/rosters",
        json=load_sleeper_fixture("rosters.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/league/{league_id}/drafts",
        json=load_sleeper_fixture("drafts.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/draft/{DRAFT_ID}/picks",
        json=load_sleeper_fixture("draft_picks.json"),
    )


def _market_row(sleeper_player_id: str, position: str, adp: float) -> dict:
    """A minimal :data:`DRAFT_MARKET_POOL_COLUMNS`-shaped row."""
    return {
        "sleeper_player_id": sleeper_player_id,
        "player_name": f"Test Player {sleeper_player_id}",
        "position": position,
        "nfl_team": "TST",
        "adp": adp,
        "adp_sd": None,
        "adp_best": None,
        "adp_worst": None,
        "ecr": adp,
        "ecr_sd": None,
        "ecr_best": None,
        "ecr_worst": None,
        "position_ecr": None,
        "bye_week": 7.0,
    }


def _fake_market_df() -> pd.DataFrame:
    """A tiny market pool covering the three players in ``draft_picks.json``."""
    return pd.DataFrame(
        [
            _market_row("1000", "RB", 1.0),
            _market_row("2000", "WR", 2.0),
            _market_row("2001", "QB", 20.0),
        ],
        columns=DRAFT_MARKET_POOL_COLUMNS,
    )


@pytest.fixture(autouse=True)
def _stub_player_catalog(monkeypatch: pytest.MonkeyPatch, load_sleeper_fixture) -> None:
    """Stub the Sleeper player-catalog cache lookup ``load_league_snapshot`` makes.

    Without this, ``load_league_snapshot``'s default cache path
    (``.cache/sleeper/players.json``) would silently prefer a real,
    developer-machine cache file if one happens to exist on disk, instead
    of exercising this test's mocked/fixture data -- this stub makes the
    test deterministic regardless of ambient local cache state.
    """
    monkeypatch.setattr(
        snapshot_module,
        "get_players_cached",
        lambda *args, **kwargs: load_sleeper_fixture("players.json"),
    )


@pytest.fixture(autouse=True)
def _stub_market_and_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the vendor market pool and the FFA-073 prior-CSV loader.

    No live FantasyFootballCalculator/FantasyPros/DynastyProcess network
    call is made, and no dependency on the (gitignored,
    developer-generated) ``prior_csv`` files the real league presets point
    at -- mirrors how ``tests/players/test_draft_market_cache.py`` isolates
    those vendor calls.
    """
    monkeypatch.setattr(
        report_script,
        "get_draft_market_player_pool_cached",
        lambda *args, **kwargs: _fake_market_df(),
    )
    monkeypatch.setattr(report_script, "load_prior", lambda prior_csv: None)


# -------------------------
# build_arg_parser()
# -------------------------


def test_build_arg_parser_league_and_league_id_are_repeatable() -> None:
    parser = report_script.build_arg_parser()
    args = parser.parse_args(
        [
            "--league", "nwc", "--league-id", "111",
            "--league", "zipline", "--league-id", "222",
        ]
    )

    assert args.league == ["nwc", "zipline"]
    assert args.league_id == ["111", "222"]


def test_build_arg_parser_market_refresh_defaults_false() -> None:
    parser = report_script.build_arg_parser()
    args = parser.parse_args(["--league", "nwc", "--league-id", "111"])

    assert args.market_refresh is False


def test_build_arg_parser_market_refresh_flag_sets_true() -> None:
    parser = report_script.build_arg_parser()
    args = parser.parse_args(
        ["--league", "nwc", "--league-id", "111", "--market-refresh"]
    )

    assert args.market_refresh is True


def test_build_arg_parser_rejects_unknown_league_slug() -> None:
    parser = report_script.build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--league", "not-a-real-league", "--league-id", "111"])


# -------------------------
# main() -- single league
# -------------------------


def test_main_single_league_writes_expected_outputs(
    tmp_path: Path, load_sleeper_fixture
) -> None:
    league_id = "111111111111111111"

    with requests_mock_lib.Mocker() as m:
        _mock_draft_endpoints(m, load_sleeper_fixture, league_id)
        exit_code = report_script.main(
            [
                "--league", "nwc", "--league-id", league_id,
                "--out-dir", str(tmp_path),
            ]
        )

    assert exit_code == 0

    stem = "NWC_2026_draft_report"
    picks_path = tmp_path / f"{stem}_picks_scored.csv"
    grades_path = tmp_path / f"{stem}_team_grades.csv"
    html_path = tmp_path / f"{stem}_artifact.html"

    assert picks_path.exists()
    assert grades_path.exists()
    assert html_path.exists()

    picks_df = pd.read_csv(picks_path)
    assert list(picks_df.columns) == SCORED_DRAFT_PICK_COLUMNS
    assert len(picks_df) == 3  # draft_picks.json fixture has 3 picks

    grades_df = pd.read_csv(grades_path)
    assert len(grades_df) == 2  # rosters.json fixture has 2 teams
    assert "position_counts" in grades_df.columns
    # position_counts must be a JSON string, not a raw Python dict repr.
    for raw in grades_df["position_counts"]:
        assert isinstance(json.loads(raw), dict)
    assert "total_vor_rank" in grades_df.columns
    assert "num_teams" in grades_df.columns

    html_text = html_path.read_text()
    # Both fixture roster_ids' commentary placeholders must survive into
    # the static HTML, literally, for the FFA-083 manual pass.
    assert "{{COMMENTARY_ROSTER_1}}" in html_text
    assert "{{COMMENTARY_ROSTER_2}}" in html_text

    leaderboard_path = tmp_path / "combined_leaderboard.csv"
    assert leaderboard_path.exists()
    leaderboard_df = pd.read_csv(leaderboard_path)
    assert list(leaderboard_df.columns) == [
        "league",
        "team_name",
        "grade_letter",
        "overall_z",
        "draft_rank",
    ]
    assert "total_vor" not in leaderboard_df.columns
    assert len(leaderboard_df) == 2


# -------------------------
# main() -- multi-league (FFA-082)
# -------------------------


def test_main_multi_league_writes_combined_leaderboard(
    tmp_path: Path, load_sleeper_fixture
) -> None:
    nwc_league_id = "222222222222222222"
    zipline_league_id = "333333333333333333"

    with requests_mock_lib.Mocker() as m:
        _mock_draft_endpoints(m, load_sleeper_fixture, nwc_league_id)
        _mock_draft_endpoints(m, load_sleeper_fixture, zipline_league_id)
        exit_code = report_script.main(
            [
                "--league", "nwc", "--league-id", nwc_league_id,
                "--league", "zipline", "--league-id", zipline_league_id,
                "--out-dir", str(tmp_path),
            ]
        )

    assert exit_code == 0
    assert (tmp_path / "NWC_2026_draft_report_team_grades.csv").exists()
    assert (tmp_path / "Zipline_2026_draft_report_team_grades.csv").exists()

    leaderboard_df = pd.read_csv(tmp_path / "combined_leaderboard.csv")
    assert "total_vor" not in leaderboard_df.columns
    assert len(leaderboard_df) == 4  # 2 teams x 2 leagues
    assert set(leaderboard_df["league"]) == {
        "NWC FFL, est. 2011",
        "Just Here For The Zipline",
    }


def test_main_league_and_league_id_count_mismatch_is_system_exit(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit):
        report_script.main(
            [
                "--league", "nwc", "--league-id", "111",
                "--league", "zipline",
                "--out-dir", str(tmp_path),
            ]
        )


def test_main_continues_after_one_league_fails(
    tmp_path: Path, load_sleeper_fixture, capsys: pytest.CaptureFixture
) -> None:
    bad_league_id = "444444444444444444"
    good_league_id = "555555555555555555"

    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/league/{bad_league_id}", status_code=404
        )
        _mock_draft_endpoints(m, load_sleeper_fixture, good_league_id)
        exit_code = report_script.main(
            [
                "--league", "nwc", "--league-id", bad_league_id,
                "--league", "zipline", "--league-id", good_league_id,
                "--out-dir", str(tmp_path),
            ]
        )

    assert exit_code == 0  # the surviving league still counts as success
    stderr = capsys.readouterr().err
    assert "NWC FFL" in stderr or "nwc" in stderr

    assert not (tmp_path / "NWC_2026_draft_report_team_grades.csv").exists()
    assert (tmp_path / "Zipline_2026_draft_report_team_grades.csv").exists()

    leaderboard_df = pd.read_csv(tmp_path / "combined_leaderboard.csv")
    assert len(leaderboard_df) == 2  # only the surviving league's 2 teams
    assert set(leaderboard_df["league"]) == {"Just Here For The Zipline"}


def test_main_returns_one_when_every_league_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/000", status_code=404)
        exit_code = report_script.main(
            ["--league", "nwc", "--league-id", "000", "--out-dir", str(tmp_path)]
        )

    assert exit_code == 1
    assert capsys.readouterr().err
