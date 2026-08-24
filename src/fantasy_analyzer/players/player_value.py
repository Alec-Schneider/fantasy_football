"""League-relative player value and positional scarcity metrics (FFA-068).

Consumes FFA-065's
:func:`~fantasy_analyzer.players.performance.build_player_performance_metrics`
output (one row per ``(season, sleeper_player_id)`` describing the shape of
that player's scoring distribution) plus the calling league's lineup
structure -- ``roster_positions`` (the slot list,
``LeagueSnapshot.roster_positions``) and ``num_teams`` (the team count,
``LeagueSettings.total_rosters``) -- and answers the FFA-068 question for
every qualifying player: how much did this player produce **relative to his
position** and **relative to a replacement-level player at his position**,
and how does that value rank across the whole league?

This is the first module in the player stack that is explicitly
*league-relative*: ``performance.py`` (FFA-065) and ``position_strength.py``
(FFA-066) describe a player's/team's own production in absolute terms, and
this module adds the "vs. the league" layer on top of FFA-065's output
without recomputing any of it -- ``points_per_game``, ``total_points`` and
``games_played`` are read straight from the input frame, never recomputed.
It performs no network access and makes no provider-specific assumptions.

This module is designed to be called on a ``performance_df`` scoped to one
league-season at a time, the same implicit assumption every other analytics
module in this codebase makes (``fantasy_team`` labels and scoring settings
are league-specific). Passing a frame that spans multiple leagues in the
same season would conflate their player pools into one replacement baseline
and is not supported.

Replacement-level methodology -- the definition this ticket must document
--------------------------------------------------------------------------------

**Replacement level** at a position is the expected weekly production of the
best player a manager could acquire for free (the classic "waiver wire"
baseline), and it is approximated here as the ``points_per_game`` of the
player at the league's **starter cutoff** for that position. The full
procedure, per ``(season, position)`` group:

1. **Count the league's starting slots at the position.** Each slot in
   ``roster_positions`` is mapped to the set of positions it can accept
   using :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
   -- the exact eligibility mapping FFA-067 documents and uses. A slot
   counts toward **every** position it can accept: a ``FLEX`` slot
   therefore counts as one additional starter at each of RB, WR, and TE (and
   a ``SUPER_FLEX`` at each of QB/RB/WR/TE). Counting flex slots at every
   eligible position is a deliberate choice among two conventions: the
   alternative -- allocating the flex baseline to a single position (usually
   WR) -- bakes in an assertion about how managers actually fill flex slots,
   which is league-behavior, not league-rules; counting the slot at every
   eligible position is a pure statement about the league's rules and keeps
   the baseline monotone (adding a flex slot never *lowers* any position's
   starter count). Bench slots (``BN``, ``IR``, or any unrecognized label)
   contribute nothing. This yields ``slots(position)``, the number of
   starting slots per team at the position.
2. **Compute the starter cutoff.** ``cutoff = num_teams * slots(position)``
   -- the number of players at the position the league starts in a single
   week (e.g. 12 in a 12-team 1-QB league, 24 in a 12-team 2-RB league with
   no flex counting).
3. **Pick the replacement player.** Rank the position's qualifying players
   by descending ``points_per_game``, ties broken by ascending
   ``sleeper_player_id`` (a deterministic display order; ties share the same
   ``points_per_game``, so the replacement *value* is tie-invariant). The
   replacement player is the one at rank ``min(cutoff, field_size)``, where
   ``field_size`` is the number of qualifying players at the position in
   the frame -- i.e. **the cutoff is clamped to the worst rostered player
   when the league does not roster enough players at the position**. This
   clamp is the module's documented answer to the "not enough players"
   case: the frame contains only rostered players (see "Rostered-only
   caveat" below), so when the league rosters fewer than ``cutoff`` players
   at a position, the best available free agent is below every rostered
   player and the tightest observable upper bound on his production is the
   worst rostered player's ``points_per_game``; using that bound makes
   every player's value-above-replacement conservative (understated), never
   overstated.
4. **Handle the no-starting-slots case.** If ``cutoff < 1`` (the league has
   no starting slots at the position -- e.g. ``num_teams = 0``, or a
   position with no slots in ``roster_positions``), the replacement player
   is likewise the worst rostered player at the position, for the same
   "tightest observable bound" reason as the clamp.
5. **``replacement_ppg``** is the replacement player's ``points_per_game``,
   the same value for every player at that ``(season, position)``.

The result is the classic "last-starter" VORP baseline, with flex slots
counted everywhere eligible. The absolute size of a
``points_above_replacement`` number depends on this convention (counting the
flex slot at every eligible position makes the RB baseline the 36th-best
RB in a 12-team 2-RB-1-FLEX league rather than the 24th-best); the
*trade-off* it documents -- that the baseline convention shifts all VORP
values at a position together -- is exactly why this module also reports
the convention-free per-position means and the league-relative
``value_rank``, which do not depend on it.

Player value metrics (one row per player-season)
-----------------------------------------------------

Let ``P`` be a player's position group in his season, ``m_ppg(P)`` and
``m_total(P)`` the arithmetic means of ``points_per_game`` and
``total_points`` over the position's qualifying players, ``r(P)`` the
position's ``replacement_ppg``, and ``g`` the player's ``games_played``.

- **position_players** -- the number of qualifying players at the position
  in the league that season (the field size behind every position-level
  value in the row).
- **position_mean_ppg** / **position_mean_total** -- ``m_ppg(P)`` /
  ``m_total(P)``, the position's average production. "Points above
  positional average" from AGENTS.md's ticket text, made concrete.
- **ppg_above_position_average** -- ``points_per_game - m_ppg(P)``, the
  rate version: how far above the position's typical per-game production
  the player scored.
- **total_above_position_average** -- ``total_points - m_total(P)``, the
  volume version: how far above the position's typical season total the
  player scored. This deliberately conflates rate and volume (a
  seventeen-game average player will usually sit above a part-season
  player of equal rate) -- that is what "above the position's average
  season total" literally asks, and the rate version above is the
  games-neutral companion column.
- **replacement_ppg** -- ``r(P)``, denormalized onto each row so the frame
  is self-contained for value questions.
- **ppg_above_replacement** -- ``points_per_game - r(P)``, the rate VORP:
  how much better per game the player is than a replacement-level player.
- **points_above_replacement** -- ``total_points - r(P) * g``, the season
  VORP: the player's total minus what a replacement-level player would have
  scored in the same number of games. This is the ticket's headline
  "points above replacement": the number of points this player contributed
  beyond what the league could have gotten for free, volume included. A
  player at or below replacement has ``<= 0`` here.
- **value_rank** -- the "league-relative player value" from the ticket:
  standard competition ("1224") ranking by descending
  ``points_above_replacement`` **across all positions within the season**,
  the identical convention ``standings.py``'s ``scoring_rank`` and
  ``position_strength.py``'s ``positional_rank`` use: players tied on the
  computed value share a rank, and the next distinct rank skips the number
  of tied players. ``value_rank = 1`` is the player who produced the most
  points above replacement in the league that season, whatever his
  position. Because the frame is one-league-scoped (see above), "the
  league" here is exactly the player pool in the input. Ties are exact
  ties on the computed float (see "Missing values / edge cases" below).

Positional scarcity (one row per position-season)
-----------------------------------------------------

:func:`build_position_scarcity_metrics` summarizes the same replacement
computations at the position grain:

- **players** -- the field size (qualifying players at the position).
- **position_starters** -- ``num_teams * slots(position)``, the league's
  starting slots at the position before clamping -- context for how much
  of the field the league actually starts.
- **replacement_rank** -- the rank actually used for the baseline (the
  clamped cutoff, i.e. ``min(cutoff, players)``, or ``players`` when
  ``cutoff < 1``): which player in the field *is* replacement this season.
- **best_ppg** -- the position's best ``points_per_game``.
- **replacement_ppg** -- as defined above.
- **ppg_gap_to_replacement** -- ``best_ppg - replacement_ppg``: how much
  the position's best production exceeds a free pickup's, in absolute
  points per game.
- **scarcity_ratio** -- ``ppg_gap_to_replacement / replacement_ppg``, the
  same gap expressed relative to the replacement level, so scarcity is
  comparable across positions with very different scoring levels: a QB
  position where the best outscores replacement by 10 ppg on a 20-ppg
  baseline (ratio 0.5) is less scarce than a TE position where the best
  outscores replacement by 10 ppg on a 10-ppg baseline (ratio 1.0). The
  ratio is the module's reading of the ticket's "positional scarcity":
  how much elite production at the position exceeds what is freely
  available. ``NaN`` when ``replacement_ppg <= 0`` (see "Missing values /
  edge cases" below).

Regular season vs. playoffs: this module is phase-agnostic
-------------------------------------------------------------

``performance_df`` (FFA-065's output) has no ``is_playoff`` column --
FFA-064's ``player_week_df`` has none either, the identical situation
``performance.py``, ``position_strength.py`` and ``lineup_efficiency.py``
document -- so this module makes no phase distinction of its own and
cannot: every week that entered the input frame enters the same
replacement computation, regular season and playoff weeks alike.

A caller wanting a phase-specific view must pre-filter ``player_week_df``
on ``week`` against the calling league's playoff-start boundary (FFA-022,
``LeagueSettings.playoff_week_start``) **before** calling FFA-065, so that
the ``performance_df`` passed here already reflects the desired phase --
the same caller-filters-first pattern the three sibling modules document.
Note that playoff weeks included in a performance frame will shift the
replacement baseline *and* every player's VORP together, since the baseline
is computed from whatever the caller's frame contains.

Rostered-only caveat (what this module cannot see)
-----------------------------------------------------

FFA-064's ``player_week_df`` row universe is **rostered** players, not
league-wide players; free agents are not in the frame (see that module's
docstring, which explicitly notes replacement-level work as the future
consumer of a league-wide row source that it does not itself provide).
Consequently the replacement baseline here is computed from the league's
rostered-and-played players only. When the league rosters at least
``cutoff`` players at a position this is the standard VORP reading and the
bias is mild (rostered players at the cutoff are generally better than
free agents, so the baseline is an upper bound and VORP values are
conservative); when it rosters fewer, the clamp documented above is the
module's explicit fallback rather than a silent wrong answer. A future
ticket that adds a league-wide (free-agent-inclusive) player-week source
can feed this module the same way without changing its interface.

Grouping key: ``(season, position)`` -- seasons are never pooled
---------------------------------------------------------------------

Like ``performance.py`` and ``position_strength.py``, and unlike
``consistency.py``'s pooled-season default, seasons are never pooled: all
means, replacement levels, and value ranks are computed within one
``season``, so a multi-season ``performance_df`` produces separate rows per
season (a player's role, offense, and the league's player pool can all
change completely between years). A caller who wants a multi-season career
view should pre-aggregate this module's own season rows.

Missing values / edge cases
-----------------------------

- **Empty ``performance_df``**: both builders return an empty DataFrame
  with their expected columns.
- **A row with missing ``season``, ``sleeper_player_id``, or ``position``**:
  not expected under FFA-065's contract for ``season``/``sleeper_player_id``
  and only reachable for ``position`` via that module's documented
  "unresolved identity -> ``None``" fallback; such a row cannot be assigned
  to a position group and is skipped entirely -- it contributes to no
  position's field, means, or replacement level and gets no value row,
  mirroring ``performance.py``'s and ``position_strength.py``'s identical
  handling of ungroupable rows.
- **A row with missing ``games_played``, ``points_per_game``, or
  ``total_points``**: not expected under FFA-065's contract (all three are
  always defined for every emitted row, since a row only exists with at
  least one qualifying game); if a hand-built input contains one, the row
  is skipped defensively rather than corrupting the position means or a
  VORP with a ``NaN``.
- **Ties at the replacement cutoff**: the cutoff *player* is chosen by a
  deterministic sort (descending ``points_per_game``, then ascending
  ``sleeper_player_id``), but the ``replacement_ppg`` value is identical
  for every tied player, so ties at the cutoff are value-invariant -- see
  step 3 of the methodology above.
- **Ties in ``value_rank``**: standard competition ranking on the computed
  ``points_above_replacement`` float, using exact equality -- the identical
  exact-float convention ``position_strength.py``'s ``positional_rank``
  uses on its computed totals. Two mathematically-equal VORP values that
  differ by floating-point rounding (e.g. totals that are non-terminating
  fractions) can in principle be split into adjacent ranks; this is a
  documented cosmetic limitation, not a correctness error.
- **``cutoff < 1``** (``num_teams <= 0``, or a position with no starting
  slots in ``roster_positions``): replacement is the worst rostered player
  at the position, the tightest observable bound -- see step 4 of the
  methodology above. Both builders remain total (they never raise for a
  degenerate league configuration).
- **Negative ``replacement_ppg``** (reachable for a position whose scoring
  can go negative, e.g. DEF): ``ppg_above_replacement`` /
  ``points_above_replacement`` remain well-defined (plain subtraction), but
  ``scarcity_ratio`` is ``NaN`` -- a negative denominator has no
  percentage meaning, the identical "where appropriate" guard
  ``consistency.py``'s ``cv`` applies to its own denominator.
- **Positions outside {QB, RB, WR, TE} are not dropped**: K, DEF, or any
  position value present in the input gets the same treatment as the four
  headline positions, matching ``position_strength.py``'s generic-position
  decision -- the starter-slot counting comes from
  ``START_SLOT_ELIGIBILITY``, which is generic, and a league that starts
  kickers should see kicker value and scarcity like any other position.
  A caller who wants strictly the four AGENTS.md headline positions can
  filter ``position.isin(["QB", "RB", "WR", "TE"])`` after calling.

Column dtypes
--------------

In both frames, ``season`` and every count/rank column are plain ``int64``
(never undefined for a row that exists), every points/ratio column is
``float64`` with undefined values as ``NaN``, and the label columns
(``sleeper_player_id``, ``player_name``, ``position``, ``nfl_team``) are
``object`` -- a label may legitimately be ``None`` if FFA-065 never
resolved it. Test undefined values with ``pd.isna``, not ``is None``.
"""

from __future__ import annotations

from statistics import fmean
from typing import Any

import pandas as pd

from fantasy_analyzer.players.lineup_efficiency import START_SLOT_ELIGIBILITY

#: Column order for the DataFrame returned by
#: :func:`build_player_value_metrics`.
PLAYER_VALUE_COLUMNS = [
    "season",
    "sleeper_player_id",
    "player_name",
    "position",
    "nfl_team",
    "games_played",
    "points_per_game",
    "total_points",
    "position_players",
    "position_mean_ppg",
    "ppg_above_position_average",
    "position_mean_total",
    "total_above_position_average",
    "replacement_ppg",
    "ppg_above_replacement",
    "points_above_replacement",
    "value_rank",
]

#: Column order for the DataFrame returned by
#: :func:`build_position_scarcity_metrics`.
POSITION_SCARCITY_COLUMNS = [
    "season",
    "position",
    "players",
    "position_starters",
    "replacement_rank",
    "best_ppg",
    "replacement_ppg",
    "ppg_gap_to_replacement",
    "scarcity_ratio",
]

#: Player-value metric columns cast to ``float64`` so undefined values are
#: ``NaN`` and the dtype does not vary with the data -- see "Column dtypes"
#: in the module docstring.
_PLAYER_FLOAT_COLUMNS = [
    "points_per_game",
    "total_points",
    "position_mean_ppg",
    "ppg_above_position_average",
    "position_mean_total",
    "total_above_position_average",
    "replacement_ppg",
    "ppg_above_replacement",
    "points_above_replacement",
]

#: Position-scarcity metric columns cast to ``float64`` for the same reason.
_SCARCITY_FLOAT_COLUMNS = [
    "best_ppg",
    "replacement_ppg",
    "ppg_gap_to_replacement",
    "scarcity_ratio",
]

#: Player-identity label columns carried through from ``performance_df`` --
#: see "Column dtypes" in the module docstring.
_PLAYER_LABEL_COLUMNS = ["sleeper_player_id", "player_name", "position", "nfl_team"]


def _starter_slots(roster_positions: list[str]) -> dict[str, int]:
    """Starting slots per position per team, from the league's slot list.

    Maps each slot through ``START_SLOT_ELIGIBILITY`` (FFA-067's documented
    mapping, reused wholesale) and counts the slot toward every position it
    can accept -- see step 1 of the module docstring's replacement-level
    methodology. Bench slots (``BN``, ``IR``, unrecognized labels) are not
    in the mapping and contribute nothing.
    """
    slots: dict[str, int] = {}
    for slot in roster_positions or []:
        eligible = START_SLOT_ELIGIBILITY.get(slot)
        if eligible is None:
            continue
        for position in eligible:
            slots[position] = slots.get(position, 0) + 1
    return slots


def _normalize_players(performance_df: pd.DataFrame) -> list[dict[str, Any]]:
    """The rows of ``performance_df`` this module can assign to a value group.

    Skips rows missing ``season``/``sleeper_player_id``/``position`` (cannot
    be grouped) and rows missing any of ``games_played``/``points_per_game``/
    ``total_points`` (would corrupt means or VORP with ``NaN``) -- see the
    module docstring's "Missing values / edge cases" section. The three
    value columns are read straight from FFA-065's output, never recomputed.
    """
    players: list[dict[str, Any]] = []
    for row in performance_df.itertuples(index=False):
        season = getattr(row, "season", None)
        player_id = getattr(row, "sleeper_player_id", None)
        position = getattr(row, "position", None)
        if pd.isna(season) or pd.isna(player_id) or pd.isna(position):
            continue

        games_played = getattr(row, "games_played", None)
        points_per_game = getattr(row, "points_per_game", None)
        total_points = getattr(row, "total_points", None)
        if pd.isna(games_played) or pd.isna(points_per_game) or pd.isna(total_points):
            continue

        players.append(
            {
                "season": int(season),
                "sleeper_player_id": player_id,
                "player_name": getattr(row, "player_name", None),
                "position": position,
                "nfl_team": getattr(row, "nfl_team", None),
                "games_played": int(games_played),
                "points_per_game": float(points_per_game),
                "total_points": float(total_points),
            }
        )
    return players


def _position_summaries(
    players: list[dict[str, Any]],
    starter_slots: dict[str, int],
    num_teams: int,
) -> dict[tuple[int, str], dict[str, Any]]:
    """Per-``(season, position)`` field, replacement, and mean summaries.

    Applies the exact definitions in the module docstring's
    "Replacement-level methodology" section: starter cutoff
    ``num_teams * slots(position)``, clamped to the field size (or to the
    worst rostered player when the cutoff is below 1), with the replacement
    player chosen by a deterministic sort (descending ``points_per_game``,
    then ascending ``sleeper_player_id``) whose chosen *value* is
    tie-invariant.
    """
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for player in players:
        groups.setdefault((player["season"], player["position"]), []).append(player)

    summaries: dict[tuple[int, str], dict[str, Any]] = {}
    for (season, position), group in groups.items():
        ordered = sorted(
            group,
            key=lambda player: (
                -player["points_per_game"],
                str(player["sleeper_player_id"]),
            ),
        )
        field_size = len(group)
        cutoff = num_teams * starter_slots.get(position, 0)
        # Clamp the baseline rank: field_size when the league has no
        # starting slots at the position (cutoff < 1), otherwise the cutoff
        # itself, capped at the field -- see steps 3-4 of the methodology.
        replacement_rank = field_size if cutoff < 1 else min(cutoff, field_size)
        summaries[(season, position)] = {
            "players": field_size,
            "position_starters": cutoff,
            "replacement_rank": replacement_rank,
            "replacement_ppg": ordered[replacement_rank - 1]["points_per_game"],
            "mean_ppg": fmean(player["points_per_game"] for player in group),
            "mean_total": fmean(player["total_points"] for player in group),
            "best_ppg": ordered[0]["points_per_game"],
        }
    return summaries


def _assign_value_ranks(rows: list[dict[str, Any]]) -> None:
    """Assign ``value_rank`` in place, within each season, across positions.

    Standard competition ("1224") ranking by descending
    ``points_above_replacement`` -- the identical convention
    ``position_strength.py``'s ``positional_rank`` uses, with the same
    exact-float tie convention -- see the module docstring's "Player value
    metrics" section.
    """
    by_season: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_season.setdefault(row["season"], []).append(row)

    for season_rows in by_season.values():
        ordered = sorted(
            season_rows,
            key=lambda row: (
                -row["points_above_replacement"],
                str(row["sleeper_player_id"]),
            ),
        )
        current_rank = 0
        previous_points = None
        for position, row in enumerate(ordered, start=1):
            if row["points_above_replacement"] != previous_points:
                current_rank = position
                previous_points = row["points_above_replacement"]
            row["value_rank"] = current_rank


def build_player_value_metrics(
    performance_df: pd.DataFrame,
    roster_positions: list[str],
    num_teams: int,
) -> pd.DataFrame:
    """Build one row per player-season of league-relative value metrics.

    Adds the league-relative layer to FFA-065's per-player-season output:
    for every qualifying player, the position's field size, mean
    ``points_per_game`` and mean ``total_points``, the player's points
    above each of those position averages, the position's replacement
    ``points_per_game``, the player's per-game and season-total points
    above replacement, and his league-wide ``value_rank``. See the module
    docstring for the full replacement-level methodology (the starter
    cutoff, the flex-slot convention, the clamping rules), the exact
    metric formulas, the phase-agnostic caller-filters-first contract, and
    the rostered-only caveat.

    Args:
        performance_df: A
            :data:`~fantasy_analyzer.players.performance.PLAYER_PERFORMANCE_COLUMNS`-shaped
            DataFrame as produced by
            :func:`~fantasy_analyzer.players.performance.build_player_performance_metrics`.
            ``games_played``/``points_per_game``/``total_points`` are read
            from it directly, never recomputed. Expects one league-season
            at a time (see the module docstring).
        roster_positions: The league's ordered roster-slot list (e.g.
            ``LeagueSnapshot.roster_positions``), used to count starting
            slots per position via ``START_SLOT_ELIGIBILITY``.
        num_teams: The number of teams in the league (e.g.
            ``LeagueSettings.total_rosters``), the multiplier from
            per-team starting slots to the league-wide starter cutoff.

    Returns:
        A DataFrame with columns :data:`PLAYER_VALUE_COLUMNS`, one row per
        ``(season, sleeper_player_id)`` in the input that has a resolvable
        position and complete value columns, sorted by ascending ``season``,
        then ascending ``value_rank`` (best value first), then
        ``sleeper_player_id`` (a deterministic display order). Returns an
        empty DataFrame with the expected columns if the input is empty or
        no row is usable.
    """
    if performance_df.empty:
        return pd.DataFrame(columns=PLAYER_VALUE_COLUMNS)

    players = _normalize_players(performance_df)
    if not players:
        return pd.DataFrame(columns=PLAYER_VALUE_COLUMNS)

    summaries = _position_summaries(
        players, _starter_slots(roster_positions), num_teams
    )

    rows: list[dict[str, Any]] = []
    for player in players:
        summary = summaries[(player["season"], player["position"])]
        replacement_ppg = summary["replacement_ppg"]
        rows.append(
            {
                "season": player["season"],
                "sleeper_player_id": player["sleeper_player_id"],
                "player_name": player["player_name"],
                "position": player["position"],
                "nfl_team": player["nfl_team"],
                "games_played": player["games_played"],
                "points_per_game": player["points_per_game"],
                "total_points": player["total_points"],
                "position_players": summary["players"],
                "position_mean_ppg": summary["mean_ppg"],
                "ppg_above_position_average": (
                    player["points_per_game"] - summary["mean_ppg"]
                ),
                "position_mean_total": summary["mean_total"],
                "total_above_position_average": (
                    player["total_points"] - summary["mean_total"]
                ),
                "replacement_ppg": replacement_ppg,
                "ppg_above_replacement": (player["points_per_game"] - replacement_ppg),
                "points_above_replacement": (
                    player["total_points"] - replacement_ppg * player["games_played"]
                ),
            }
        )

    _assign_value_ranks(rows)

    rows.sort(
        key=lambda row: (
            row["season"],
            row["value_rank"],
            str(row["sleeper_player_id"]),
        )
    )

    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["games_played"] = result["games_played"].astype(int)
    result["position_players"] = result["position_players"].astype(int)
    result["value_rank"] = result["value_rank"].astype(int)
    for column in _PLAYER_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    # Assigned as explicit object-dtype Series, mirroring performance.py's
    # identical handling: pandas' string-dtype inference would otherwise
    # upcast a column mixing real labels with ``None`` into a dtype that
    # silently turns ``None`` into ``NaN``.
    for label_column in _PLAYER_LABEL_COLUMNS:
        result[label_column] = pd.Series(result[label_column].tolist(), dtype=object)

    return result[PLAYER_VALUE_COLUMNS]


def build_position_scarcity_metrics(
    performance_df: pd.DataFrame,
    roster_positions: list[str],
    num_teams: int,
) -> pd.DataFrame:
    """Build one row per ``(season, position)`` of replacement and scarcity
    metrics.

    Summarizes the same replacement-level computation the player frame
    uses, at the position grain: field size, league-wide starting slots,
    the baseline rank actually used, the position's best ``points_per_game``,
    its ``replacement_ppg``, the absolute gap between them, and the
    replacement-relative ``scarcity_ratio``. See the module docstring for
    the full methodology and the ratio's definition (and its ``NaN`` guard
    for non-positive replacement levels).

    Args:
        performance_df: Same contract as
            :func:`build_player_value_metrics`.
        roster_positions: Same contract as
            :func:`build_player_value_metrics`.
        num_teams: Same contract as
            :func:`build_player_value_metrics`.

    Returns:
        A DataFrame with columns :data:`POSITION_SCARCITY_COLUMNS`, one row
        per ``(season, position)`` that has at least one usable player in
        the input, sorted by ascending ``season`` then ``position``.
        ``scarcity_ratio`` is ``NaN`` when ``replacement_ppg <= 0``.
        Returns an empty DataFrame with the expected columns if the input is
        empty or no row is usable.
    """
    if performance_df.empty:
        return pd.DataFrame(columns=POSITION_SCARCITY_COLUMNS)

    players = _normalize_players(performance_df)
    summaries = _position_summaries(
        players, _starter_slots(roster_positions), num_teams
    )
    if not summaries:
        return pd.DataFrame(columns=POSITION_SCARCITY_COLUMNS)

    rows: list[dict[str, Any]] = []
    for (season, position), summary in summaries.items():
        replacement_ppg = summary["replacement_ppg"]
        gap = summary["best_ppg"] - replacement_ppg
        rows.append(
            {
                "season": season,
                "position": position,
                "players": summary["players"],
                "position_starters": summary["position_starters"],
                "replacement_rank": summary["replacement_rank"],
                "best_ppg": summary["best_ppg"],
                "replacement_ppg": replacement_ppg,
                "ppg_gap_to_replacement": gap,
                # A non-positive denominator has no percentage meaning --
                # the identical "where appropriate" guard consistency.py's
                # cv applies to its own denominator.
                "scarcity_ratio": (
                    gap / replacement_ppg if replacement_ppg > 0 else None
                ),
            }
        )

    rows.sort(key=lambda row: (row["season"], str(row["position"])))

    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["players"] = result["players"].astype(int)
    result["position_starters"] = result["position_starters"].astype(int)
    result["replacement_rank"] = result["replacement_rank"].astype(int)
    for column in _SCARCITY_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    result["position"] = pd.Series(result["position"].tolist(), dtype=object)

    return result[POSITION_SCARCITY_COLUMNS]
