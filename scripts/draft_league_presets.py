"""Shared 2026 league presets for the ``scripts/draft_*`` family of scripts.

Extracted from ``draft_board_artifact.py`` (FFA-081) so
``draft_report_2026.py`` (FFA-081/082) can reuse the exact same league
metadata without duplicating it. Values mirror
``scripts/draft_guide_2026_league.sh`` -- all confirmed against Sleeper's
2026 league settings.

``league_id`` values (FFA-082)
--------------------------------------------------------------------------

:data:`LEAGUES` was originally built for the pre-draft market/board tools
(``draft_guide_2026.py``, ``draft_board_artifact.py``), neither of which
ever needed a real Sleeper ``league_id`` -- they take ``--slot``/``--teams``
etc. directly and never call the Sleeper API. ``draft_report_2026.py``
(FFA-081/082) is the first consumer that fetches a league's actual draft
from Sleeper, so it needs one.

Each preset's ``league_id`` below is that league's **2026-season** Sleeper
``league_id`` (looked up via ``get_leagues(user_id, 2026)`` for
``schneidbaby`` and matched by name/``previous_league_id`` back to the
2025 ``league_id`` embedded in that preset's ``prior_csv`` filename). It is
deliberately a different ID from the 2025 one in ``prior_csv`` -- Sleeper
mints a new ``league_id`` each season and links seasons via
``previous_league_id``.

``prior_draft_csv`` (FFA-085)
--------------------------------------------------------------------------

Each preset's **2025-season** normalized draft picks (``pick_no``,
``sleeper_player_id``, ``is_keeper``, ...), written by
``scripts/fetch_season_draft_picks.py``. Joined against ``prior_csv``
(that same 2025 season's realized ``points_above_replacement``) by
:func:`~fantasy_analyzer.players.draft_points_value.fit_points_value_curve`
to fit a real-points draft value curve -- see that module's docstring.
Both files describe the *same* already-completed 2025 season and share the
same 2025 ``league_id`` (embedded in both filenames), distinct from the
2026 ``league_id`` below.
"""

from __future__ import annotations

from typing import Any

#: Known leagues, keyed by CLI slug.
LEAGUES: dict[str, dict[str, Any]] = {
    "nwc": {
        "title": "NWC FFL, est. 2011",
        "short_title": "NWC FFL",
        "teams": 12,
        "rounds": 16,
        "scoring": "half-ppr",
        "scoring_label": "Half PPR",
        "roster_positions": "QB,RB,RB,WR,WR,TE,FLEX,K,DEF,BN,BN,BN,BN,BN,BN,BN",
        "prior_csv": (
            "scripts/output/draft2026/NWC_FFL_2025_prior_1257477810625196032.csv"
        ),
        "prior_draft_csv": (
            "scripts/output/draft2026/NWC_FFL_2025_draft_1257477810625196032.csv"
        ),
        "out_prefix": "NWC",
        # 2026-season league_id (2025's was 1257477810625196032).
        "league_id": "1389350137481932800",
    },
    "new-wave": {
        "title": "New Wave Friends League",
        "short_title": "New Wave",
        "teams": 10,
        "rounds": 15,
        "scoring": "ppr",
        "scoring_label": "Full PPR",
        "roster_positions": "QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,BN,BN,BN,BN,BN",
        "prior_csv": (
            "scripts/output/draft2026/New_Wave_2025_prior_1260307567133859840.csv"
        ),
        "prior_draft_csv": (
            "scripts/output/draft2026/New_Wave_2025_draft_1260307567133859840.csv"
        ),
        "out_prefix": "NewWave",
        # 2026-season league_id (2025's was 1260307567133859840).
        "league_id": "1389754945892274176",
    },
    "zipline": {
        "title": "Just Here For The Zipline",
        "short_title": "Zipline",
        "teams": 10,
        "rounds": 16,
        "scoring": "half-ppr",
        "scoring_label": "Half PPR",
        "roster_positions": "QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,BN,BN,BN,BN,BN,BN",
        "prior_csv": (
            "scripts/output/draft2026/Zipline_2025_prior_1262800342051999744.csv"
        ),
        "prior_draft_csv": (
            "scripts/output/draft2026/Zipline_2025_draft_1262800342051999744.csv"
        ),
        "out_prefix": "Zipline",
        # 2026-season league_id (2025's was 1262800342051999744).
        "league_id": "1389707229824815104",
    },
}
