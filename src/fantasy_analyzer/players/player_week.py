"""Build the canonical player-week fantasy fact table (FFA-064).

This module is the join point where three previously-separate FFA-06x
pieces finally meet: Sleeper's own weekly roster data (who had a player
rostered, and whether they started or sat -- see
:mod:`fantasy_analyzer.matchups.loader`), a
:class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`'s raw
per-player stat counts (FFA-060/061, e.g.
:class:`~fantasy_analyzer.players.nflverse_provider.NflverseWeeklyStatsProvider`),
and FFA-063's league-scoring engine
(:func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`). The
result is the one row-per-(week, rostered player) table AGENTS.md's
"Canonical Player-Week Dataset" describes, and the foundation every later
player-analytics ticket (FFA-065 through FFA-070) is expected to build on.

Row universe: rostered players, not "every player with stats" (design
decision)
----------------------------------------------------------------------------

A naive approach would build this table from whatever player-weeks a
:class:`PlayerStatsProvider` happens to have data for. This module
deliberately does the opposite: the row universe comes from Sleeper's own
weekly roster data -- specifically, each raw matchup entry's ``players``
list (the roster's full player-id set for that week, starters and bench
together) in :attr:`~fantasy_analyzer.matchups.loader.WeekMatchups.matchups`
-- and provider stats are left-joined onto *that*. Two reasons:

1. ``roster_id``, ``fantasy_team``, ``started``, and ``bench`` are only
   meaningful for a player who was actually on a fantasy roster that week.
   Building from "every player the provider has stats for" would pull in
   every free agent league-wide, which has no roster/lineup context to
   report and is out of scope for this ticket (see FFA-068's future
   replacement-level-value work, which *does* need league-wide players --
   noted as a follow-up below, not implemented here).
2. A rostered player who did not play (bye week, inactive, or a provider
   with no data for them that week) still needs a row: dropping them would
   make it impossible for future roster-efficiency analysis (FFA-067) to
   see "this bench spot held a player who scored zero" versus "this bench
   spot was empty." A rostered player with no matching provider row
   therefore still gets a row here, with every stat column ``NaN`` and
   ``fantasy_points`` computed from those (zero, since
   :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`
   already treats a missing/``NaN`` stat as a zero contribution) rather
   than silently vanishing.

   This is a deliberate departure from ``PlayerStatsProvider.weekly_stats``'s
   own "a player who did not play has no row" convention -- but that
   convention describes the *raw provider's* fact table (an observed-stats
   log), not this roster-aware one. The two tables have different
   semantics on purpose; this module's left join is exactly what
   reconciles them.

Identity enrichment order: nflverse first, Sleeper catalog second
----------------------------------------------------------------------

``player_name``/``position``/``nfl_team`` are populated from the provider's
join first (e.g. nflverse's ``player_display_name``/``position``/
``recent_team``). For a rostered player whose provider join produced no
match (no row, or a row with those fields themselves ``None``), this module
falls back to ``LeagueSnapshot.players_df`` (``full_name``/``position``/
``team``) -- Sleeper's own player catalog, keyed by the same Sleeper
``player_id``, already resolved league-wide by
:func:`fantasy_analyzer.league.players.resolve_roster_players`. If neither
source has a value, the field stays ``None`` -- this module never raises
for an unresolvable player. ``gsis_id`` has no such fallback (Sleeper's
catalog is not itself a source of GSIS IDs to this module, only the
crosswalk feeding the provider is) and stays whatever the provider join
produced.

``started`` / ``bench``: two explicit booleans, not one column
--------------------------------------------------------------------

AGENTS.md's Canonical Player-Week Dataset lists ``started`` and ``bench``
as two separate fields, so this module computes both explicitly rather than
collapsing them into one ternary/enum column:

- ``started``: ``True`` if the player ID appears in that roster/week's raw
  Sleeper ``starters`` list.
- ``bench``: ``True`` if the player ID appears in that roster/week's
  ``players`` list (which it always does, since that list is this
  module's row universe -- see above) **and** is not in ``starters``.

For a standard Sleeper roster these two are exact complements over the row
universe (every rostered player is either starting or benched), but keeping
them as two explicit columns matches AGENTS.md's schema and leaves room for
a future non-binary lineup slot (e.g. IR) without a breaking schema change.

Missing ``players`` field on a raw matchup entry
------------------------------------------------------

Sleeper's real weekly matchup response carries a ``players`` key per roster
entry (starters + bench). This repository's minimal shared fixture
(``tests/fixtures/sleeper/matchups.json``) predates that need and may omit
it. If a raw entry has no ``players`` key at all, this module falls back to
treating that entry's ``starters`` list as its only known players -- a
degraded-but-safe default (a real Sleeper response always has ``players``
as a superset of ``starters``) rather than raising or silently producing no
rows for that roster.

Byes and ``matchup_id``
------------------------

This module reads :attr:`WeekMatchups.matchups` directly and never inspects
``matchup_id`` at all -- per-player stats and roster/lineup context do not
depend on whether Sleeper paired a roster with an opponent that week. A bye
entry (``matchup_id: null``, per
:mod:`fantasy_analyzer.matchups.pairing`'s convention) is processed exactly
like any other entry. This module deliberately does not import
``matchups.pairing`` or ``matchups.outcomes`` -- pairing/outcome status is
irrelevant here.

``season`` is normalized to ``int``, unlike the matchups modules
------------------------------------------------------------------------

:mod:`fantasy_analyzer.matchups.season_matchups` treats ``season`` as an
opaque label, carried through unchanged from whatever
:class:`~fantasy_analyzer.matchups.loader.WeekMatchups` was given. This
module cannot do that: it must call
``PlayerStatsProvider.weekly_stats(season: int, week: int)`` and then join
the provider's ``season`` column (always ``int``, per that interface) back
against Sleeper's roster rows on ``(season, week, sleeper_player_id)``. So
this module normalizes ``week.season`` to ``int(week.season)`` up front,
and the ``season`` column in this module's output is always that ``int`` --
not necessarily the original string Sleeper returned (e.g. ``"2025"`` ->
``2025``). A week whose ``season`` is ``None`` (``WeekMatchups``'s own
documented default when no label was supplied) cannot be joined against a
provider and raises ``ValueError`` if that week has any roster entries to
process; a week with ``season=None`` and no matchup entries is silently
skipped, since there is nothing to look up.

Multiple weeks / a whole season
------------------------------------

:func:`build_player_week_fact_table` takes a full ``list[WeekMatchups]``
(a season, or any subset -- e.g. just the weeks already loaded for a
league) plus ``teams_df``, an identity-fallback ``players_df``, a
configured provider, and a league's ``scoring_settings``, and returns the
combined fact table across every week. Like every other composition
function in this codebase (``build_season_matchup_df``,
``build_league_snapshot``, ...) it performs no network access of its own;
the provider is a already-configured collaborator, called once per distinct
``(season, week)`` that actually has roster entries to resolve.

Not implemented here (see FFA-065 through FFA-070)
--------------------------------------------------------

This module only builds the fact table. It deliberately does not compute
any *metric* on top of it (points per game, volatility, optimal lineup,
replacement-level value, ...) -- those are separate, later tickets.

A second row source: :func:`build_league_wide_player_week_fact_table`
------------------------------------------------------------------------

The rostered-only scope above is deliberate for
:func:`build_player_week_fact_table`, and stays unchanged: ``roster_id``/
``fantasy_team``/``started``/``bench`` are only meaningful for a player
someone actually rostered, so that function's row universe stays exactly
Sleeper's roster data.

But FFA-068's replacement-level value work (and everything built on it --
FFA-073's composite ranking among them) computes "replacement level" from
whatever player pool it is handed, and a pool of only *this league's*
rostered players understates it: the correct baseline is the best player a
manager could have added off the wire, which by definition is never on
anyone's roster. :func:`build_league_wide_player_week_fact_table` is the
separate, new row-source this module's own docstring anticipated -- not an
extension of the rostered-only function's contract, a second function
alongside it, reusing the same identity-enrichment and scoring tail. Its
row universe is every player the configured provider has stats for that
week with a resolvable ``sleeper_player_id``, still left-enriched with
roster context where a player happens to be rostered (``roster_id``/
``fantasy_team``/``started``/``bench`` populated exactly as the rostered-only
function would), and with ``roster_id = None``, ``fantasy_team = None``,
``started = False``, ``bench = False`` for everyone else -- a free agent is,
truthfully, on nobody's bench. A provider row with no resolvable
``sleeper_player_id`` (the crosswalk found no match) is dropped rather than
included as an unidentifiable row, since every downstream FFA-06x module is
keyed on that ID. Both functions return the identical
:class:`PlayerWeekFactTable` shape, so any caller of one can switch to the
other without touching FFA-065 through FFA-073.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from fantasy_analyzer.matchups.loader import WeekMatchups
from fantasy_analyzer.players.provider import PlayerStatsProvider
from fantasy_analyzer.players.scoring import calculate_fantasy_points

#: Column order for the identity/roster-context prefix of the DataFrame
#: returned by :func:`build_player_week_fact_table`. Any provider-specific
#: raw stat columns (e.g.
#: :data:`~fantasy_analyzer.players.nflverse_provider.RAW_STAT_COLUMNS`)
#: follow this prefix, in the order the configured provider supplied them,
#: with ``fantasy_points`` always last. See the module docstring's naming
#: note: a provider's own stat-column names (e.g. nflverse's
#: ``passing_yards``) are kept as-is rather than renamed to match
#: AGENTS.md's illustrative (and explicitly non-exhaustive) schema.
PLAYER_WEEK_COLUMNS = [
    "season",
    "week",
    "roster_id",
    "fantasy_team",
    "sleeper_player_id",
    "gsis_id",
    "player_name",
    "position",
    "nfl_team",
    "started",
    "bench",
]


@dataclass(frozen=True)
class PlayerWeekFactTable:
    """The output of :func:`build_player_week_fact_table`: facts plus diagnostics.

    Mirrors :class:`~fantasy_analyzer.players.scoring.ScoringResult`'s
    shape for the same reason: a caller must not be able to get
    ``player_week_df`` without also seeing (or deliberately ignoring)
    ``unsupported_scoring_keys``, since a league whose scoring rules aren't
    fully supported would otherwise have silently-wrong ``fantasy_points``
    with no visible signal.

    Attributes:
        player_week_df: Columns :data:`PLAYER_WEEK_COLUMNS`, followed by
            whatever raw stat columns the configured provider supplied
            (union across every week processed, in first-seen order), then
            ``fantasy_points`` (float) last. One row per (week, roster,
            rostered player) -- see the module docstring for the exact row
            universe and missing-data handling.
        unsupported_scoring_keys: ``scoring_settings`` keys
            :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`
            could not map to a raw stat column, sorted. Empty if every key
            was applied.
    """

    player_week_df: pd.DataFrame
    unsupported_scoring_keys: list[str]


def _resolve_season(
    season: Optional[str], week: int, has_entries: bool
) -> Optional[int]:
    """Normalize a ``WeekMatchups.season`` label to ``int`` for provider calls.

    Returns ``None`` (meaning "nothing to process") only when ``season`` is
    ``None`` and there are no roster entries for this week -- a week with
    entries but no season label cannot be resolved and raises instead. See
    the module docstring's "``season`` is normalized to ``int``" section.
    """
    if season is None:
        if has_entries:
            raise ValueError(
                f"week {week} has roster entries but no season label; "
                "a season is required to look up provider stats."
            )
        return None
    return int(season)


def _week_roster_rows(
    week: WeekMatchups, season: int, owner_by_roster: Mapping[int, object]
) -> list[dict]:
    """Build one identity/roster-context row per rostered player in ``week``.

    Reads each raw Sleeper matchup entry's ``players`` list (falling back to
    ``starters`` if ``players`` is absent -- see the module docstring) as
    the row universe; ``matchup_id`` is never inspected. Duplicate player
    IDs within one entry's ``players`` list (should not occur in real data)
    are preserved as duplicate rows, mirroring
    :func:`~fantasy_analyzer.league.players.resolve_roster_players`'s
    duplicate-preserving convention.
    """
    rows: list[dict] = []
    for entry in week.matchups:
        roster_id = entry.get("roster_id")
        starters = list(entry.get("starters") or [])
        players = list(entry.get("players") or starters)
        fantasy_team = owner_by_roster.get(roster_id)

        for player_id in players:
            rows.append(
                {
                    "season": season,
                    "week": week.week,
                    "roster_id": roster_id,
                    "fantasy_team": fantasy_team,
                    "sleeper_player_id": player_id,
                    "started": player_id in starters,
                    "bench": player_id not in starters,
                }
            )

    return rows


def build_player_week_fact_table(
    weeks: list[WeekMatchups],
    teams_df: pd.DataFrame,
    players_df: pd.DataFrame,
    provider: PlayerStatsProvider,
    scoring_settings: Mapping[str, float],
) -> PlayerWeekFactTable:
    """Build the player-week fantasy fact table for one or more weeks.

    Pure composition: performs no network access itself. ``provider`` is
    called once per distinct ``(season, week)`` that has at least one
    roster entry to resolve.

    Args:
        weeks: One or more weeks of raw Sleeper matchups, as produced by
            :func:`~fantasy_analyzer.matchups.loader.collect_season_matchups`
            or :func:`~fantasy_analyzer.matchups.loader.load_season_matchups`
            (a full season, or any subset). Order is preserved in the
            output.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame (see
            :func:`~fantasy_analyzer.league.teams.build_team_mapping`) used
            to resolve ``roster_id -> fantasy_team``, via the same
            ``display_name`` dict-lookup pattern
            ``matchups.season_matchups`` uses for ``owner_1``/``owner_2``: a
            roster_id absent from ``teams_df`` (or an empty ``teams_df``)
            resolves to ``fantasy_team = None`` rather than raising.
        players_df: A ``LeagueSnapshot.players_df``-shaped DataFrame (see
            :func:`~fantasy_analyzer.league.players.resolve_roster_players`)
            used as the identity fallback for ``player_name``/``position``/
            ``nfl_team`` when the provider's join has no value -- see the
            module docstring's "Identity enrichment order" section.
        provider: A configured
            :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`
            supplying raw per-player stat counts.
        scoring_settings: A league's Sleeper scoring category -> point value
            mapping, e.g. ``LeagueSnapshot.scoring_settings``. Passed
            through unmodified to
            :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`.

    Returns:
        A :class:`PlayerWeekFactTable`. ``player_week_df`` is empty (with
        the expected ``PLAYER_WEEK_COLUMNS`` prefix and no stat columns) if
        ``weeks`` is empty or every week has no roster entries.

    Raises:
        ValueError: If a week has roster entries but
            :attr:`~fantasy_analyzer.matchups.loader.WeekMatchups.season` is
            ``None`` -- see the module docstring.
    """
    owner_by_roster = _owner_by_roster(teams_df)
    roster_rows, fetched_stats = _collect_weekly_rows(weeks, provider, owner_by_roster)

    if not roster_rows:
        return _empty_fact_table(scoring_settings)

    roster_df = pd.DataFrame(roster_rows, columns=_ROSTER_ROW_COLUMNS)
    stats_df = _concat_stats(fetched_stats)

    merged = roster_df.merge(
        stats_df, on=["season", "week", "sleeper_player_id"], how="left"
    )

    return _finalize_fact_table(merged, players_df, scoring_settings)


def build_league_wide_player_week_fact_table(
    weeks: list[WeekMatchups],
    teams_df: pd.DataFrame,
    players_df: pd.DataFrame,
    provider: PlayerStatsProvider,
    scoring_settings: Mapping[str, float],
) -> PlayerWeekFactTable:
    """Build the player-week fact table over every player the provider covers.

    See the module docstring's "A second row source" section for why this
    function exists alongside :func:`build_player_week_fact_table` rather
    than as a parameter on it. Row universe: every ``(week,
    sleeper_player_id)`` the configured ``provider`` has stats for, for
    every week in ``weeks`` that has at least one roster entry -- not just
    the players this league happened to roster. A player who *was* rostered
    that week gets the identical ``roster_id``/``fantasy_team``/``started``/
    ``bench`` values :func:`build_player_week_fact_table` would give him; a
    player who was not gets ``roster_id = None``, ``fantasy_team = None``,
    ``started = False``, ``bench = False``. A provider row with no
    resolvable ``sleeper_player_id`` is dropped (see the module docstring)
    rather than emitted as an unidentifiable row.

    Args:
        weeks: Same as :func:`build_player_week_fact_table`.
        teams_df: Same as :func:`build_player_week_fact_table`.
        players_df: Same as :func:`build_player_week_fact_table`.
        provider: Same as :func:`build_player_week_fact_table`. Every player
            it reports stats for, per week, is a candidate row here (not
            only players present in ``weeks``' roster entries).
        scoring_settings: Same as :func:`build_player_week_fact_table`.

    Returns:
        A :class:`PlayerWeekFactTable`, the identical shape
        :func:`build_player_week_fact_table` returns. Rows are ordered by
        ascending ``week``; within a week, rostered players keep
        :func:`build_player_week_fact_table`'s relative order and
        free-agent-only rows follow. Empty under the identical conditions as
        the rostered-only function.

    Raises:
        ValueError: Identical to :func:`build_player_week_fact_table`.
    """
    owner_by_roster = _owner_by_roster(teams_df)
    roster_rows, fetched_stats = _collect_weekly_rows(weeks, provider, owner_by_roster)

    if not roster_rows and not fetched_stats:
        return _empty_fact_table(scoring_settings)

    roster_df = pd.DataFrame(roster_rows, columns=_ROSTER_ROW_COLUMNS)
    stats_df = _concat_stats(fetched_stats)

    merged = roster_df.merge(
        stats_df, on=["season", "week", "sleeper_player_id"], how="outer"
    )

    # A provider row with no resolvable sleeper_player_id cannot be
    # identified by anything downstream -- drop it rather than emit an
    # unidentifiable row (see the module docstring).
    merged = merged[merged["sleeper_player_id"].notna()]

    # Free-agent-only rows (right-side-only in the outer join) start with
    # NaN roster_id/fantasy_team -- correct, nobody rostered them -- and NaN
    # started/bench, which this function defines as False: a free agent is
    # on nobody's bench.
    merged["started"] = merged["started"].fillna(False).astype(bool)
    merged["bench"] = merged["bench"].fillna(False).astype(bool)

    merged = merged.sort_values(["week"], kind="stable").reset_index(drop=True)

    return _finalize_fact_table(merged, players_df, scoring_settings)


#: Columns of the intermediate roster-context frame both builders join
#: provider stats onto. Not part of the public output shape -- see
#: :data:`PLAYER_WEEK_COLUMNS` for that.
_ROSTER_ROW_COLUMNS = [
    "season",
    "week",
    "roster_id",
    "fantasy_team",
    "sleeper_player_id",
    "started",
    "bench",
]


def _owner_by_roster(teams_df: pd.DataFrame) -> dict:
    """``roster_id -> display_name``, or ``{}`` for an empty ``teams_df``."""
    return (
        teams_df.set_index("roster_id")["display_name"].to_dict()
        if not teams_df.empty
        else {}
    )


def _collect_weekly_rows(
    weeks: list[WeekMatchups],
    provider: PlayerStatsProvider,
    owner_by_roster: Mapping[int, object],
) -> tuple[list[dict], list[pd.DataFrame]]:
    """Shared week loop: roster rows plus one provider fetch per resolvable week.

    Identical for both builders -- they diverge only in how ``stats_df`` is
    joined onto the resulting ``roster_df`` (left vs. outer), not in how
    either input is collected.
    """
    roster_rows: list[dict] = []
    fetched_stats: list[pd.DataFrame] = []
    for week in weeks:
        has_entries = bool(week.matchups)
        season = _resolve_season(week.season, week.week, has_entries)
        if not has_entries:
            continue

        roster_rows.extend(_week_roster_rows(week, season, owner_by_roster))
        fetched_stats.append(provider.weekly_stats(season, week.week))

    return roster_rows, fetched_stats


def _concat_stats(fetched_stats: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate one season's worth of per-week provider frames."""
    return (
        pd.concat(fetched_stats, ignore_index=True, sort=False)
        if fetched_stats
        else pd.DataFrame(columns=["season", "week", "sleeper_player_id"])
    )


def _empty_fact_table(scoring_settings: Mapping[str, float]) -> PlayerWeekFactTable:
    """The shared "no rows to build" result for either builder."""
    empty_df = pd.DataFrame(columns=PLAYER_WEEK_COLUMNS + ["fantasy_points"])
    # calculate_fantasy_points' unsupported-key determination depends only
    # on scoring_settings, not on any row/column of the stats frame passed
    # in -- an empty frame is a legal, cheap way to reuse that logic here
    # rather than duplicating it.
    unsupported = calculate_fantasy_points(
        pd.DataFrame(), scoring_settings
    ).unsupported_scoring_keys
    return PlayerWeekFactTable(
        player_week_df=empty_df, unsupported_scoring_keys=unsupported
    )


def _finalize_fact_table(
    merged: pd.DataFrame,
    players_df: pd.DataFrame,
    scoring_settings: Mapping[str, float],
) -> PlayerWeekFactTable:
    """Identity enrichment + scoring tail shared by both builders.

    ``merged`` is a roster-context frame already left- or outer-joined with
    provider stats, one row per (week, player) to emit.
    """
    for column in ("gsis_id", "player_name", "position", "nfl_team"):
        if column not in merged.columns:
            merged[column] = None

    if not players_df.empty:
        catalog = players_df.set_index("player_id")
        name_by_id = catalog["full_name"].to_dict()
        position_by_id = catalog["position"].to_dict()
        team_by_id = catalog["team"].to_dict()

        fallback_name = merged["sleeper_player_id"].map(name_by_id)
        fallback_position = merged["sleeper_player_id"].map(position_by_id)
        fallback_team = merged["sleeper_player_id"].map(team_by_id)

        merged["player_name"] = merged["player_name"].where(
            merged["player_name"].notna(), fallback_name
        )
        merged["position"] = merged["position"].where(
            merged["position"].notna(), fallback_position
        )
        merged["nfl_team"] = merged["nfl_team"].where(
            merged["nfl_team"].notna(), fallback_team
        )

    stat_columns = [
        column for column in merged.columns if column not in PLAYER_WEEK_COLUMNS
    ]

    scoring_result = calculate_fantasy_points(merged, scoring_settings)
    points_df = scoring_result.points_df

    ordered_columns = PLAYER_WEEK_COLUMNS + stat_columns + ["fantasy_points"]
    player_week_df = points_df[ordered_columns].reset_index(drop=True)

    return PlayerWeekFactTable(
        player_week_df=player_week_df,
        unsupported_scoring_keys=scoring_result.unsupported_scoring_keys,
    )


#: Sleeper's placeholder for an empty starting slot in ``starters``.
_EMPTY_SLOT_ID = "0"


def _catalog_identity(player_id: str, catalog: Mapping[str, Mapping[str, Any]]) -> dict:
    """``player_name``/``position``/``nfl_team`` for one Sleeper player id.

    A team defense is keyed by its team abbreviation (``"PIT"``) with catalog
    position ``DEF``; when the catalog lacks the entry (or its ``team``), an
    all-letters upper-case id is treated as a defense and its own abbreviation
    is the ``nfl_team``. Anything else unresolvable stays ``None``.
    """
    entry = catalog.get(player_id) or {}
    name = entry.get("full_name")
    if not name:
        name = " ".join(
            part for part in (entry.get("first_name"), entry.get("last_name")) if part
        )
    position = entry.get("position")
    team = entry.get("team")
    looks_like_defense = player_id.isalpha() and player_id.isupper()
    if position == "DEF" or (not entry and looks_like_defense):
        position = "DEF"
        team = team or player_id
        name = name or player_id
    return {
        "player_name": name or None,
        "position": position,
        "nfl_team": team,
    }


def build_sleeper_scored_player_weeks(
    raw_weeks: Mapping[int, Sequence[Mapping[str, Any]]],
    catalog: Mapping[str, Mapping[str, Any]],
    teams_df: pd.DataFrame,
    season: int | str,
    *,
    through_week: Optional[int] = None,
) -> pd.DataFrame:
    """Build a player-week frame scored by Sleeper itself, with no provider.

    Why this exists: :func:`build_player_week_fact_table` needs an nflverse
    provider, an ID crosswalk and the scoring engine, which is the right
    path for value-over-replacement work but heavy for "how much did each
    team's started QB/RB/WR/TE/K/DEF produce". Every Sleeper matchup entry
    already carries ``players_points``, the per-player scores that actually
    decided the matchups, so this is a cheap alternative for started-
    production questions. Its ``fantasy_points`` are **Sleeper's**, not this
    package's scoring engine, and it carries no raw stat columns.

    One row per ``(week, roster_id, player_id)`` in each roster-week's
    ``players`` (``starters`` if ``players`` is absent). ``started`` is
    membership in ``starters`` and ``bench`` its inverse. Sleeper's empty-slot
    placeholder id ``"0"`` is skipped. ``fantasy_team`` is the roster's
    ``display_name`` in ``teams_df`` (``None`` if unmapped), as
    :func:`build_player_week_fact_table` labels it. ``position``,
    ``player_name`` and ``nfl_team`` come from ``catalog`` (see
    :func:`_catalog_identity` for team defenses).

    A player absent from ``players_points`` gets ``fantasy_points = 0.0``:
    Sleeper recorded no score for them that week (bye, inactive, game not yet
    played). Pass ``through_week`` so unplayed future weeks are not emitted
    as zeros.

    The frame is shaped for
    :func:`~fantasy_analyzer.players.position_strength.build_position_strength_metrics`:
    :data:`PLAYER_WEEK_COLUMNS` followed by ``fantasy_points``. ``gsis_id`` is
    ``None`` (Sleeper cannot supply it). With no raw stat columns,
    ``positional_depth`` from that function is ``0`` for every group; the
    started-production columns are unaffected.

    Args:
        raw_weeks: ``week -> Sleeper /matchups/<week>`` payload.
        catalog: Sleeper player catalog keyed by player id.
        teams_df: ``LeagueSnapshot.teams_df``-shaped frame.
        season: Season label, normalized to ``int`` as elsewhere in this module.
        through_week: If given, only weeks ``<= through_week`` are emitted.

    Returns:
        A DataFrame with columns ``PLAYER_WEEK_COLUMNS + ["fantasy_points"]``,
        ordered by week, then payload order. Empty (correct columns) if there
        is nothing to emit.
    """
    season_int = int(season)
    owner_by_roster = _owner_by_roster(teams_df)
    rows: list[dict] = []
    for week in sorted(raw_weeks):
        if through_week is not None and week > through_week:
            continue
        for entry in raw_weeks[week] or []:
            roster_id = entry.get("roster_id")
            starters = list(entry.get("starters") or [])
            players = list(entry.get("players") or starters)
            points = entry.get("players_points") or {}
            fantasy_team = owner_by_roster.get(roster_id)
            for player_id in players:
                if player_id == _EMPTY_SLOT_ID:
                    continue
                score = points.get(player_id)
                rows.append(
                    {
                        "season": season_int,
                        "week": week,
                        "roster_id": roster_id,
                        "fantasy_team": fantasy_team,
                        "sleeper_player_id": player_id,
                        "gsis_id": None,
                        **_catalog_identity(player_id, catalog),
                        "started": player_id in starters,
                        "bench": player_id not in starters,
                        "fantasy_points": 0.0 if score is None else float(score),
                    }
                )

    columns = PLAYER_WEEK_COLUMNS + ["fantasy_points"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)
