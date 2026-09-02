# The `sleeper` layer

This page covers [`src/fantasy_analyzer/sleeper/`](../src/fantasy_analyzer/sleeper/)
only -- the raw Sleeper HTTP client, its exception types, and the local
player-catalog cache. It sits below every other page in this reference:
[`docs/league.md`](league.md) (page one) builds a `LeagueSnapshot` from the
raw dicts `SleeperClient` returns, and every downstream page inherits that
dependency. `docs/league.md`'s own intro promised this page ("later pages
will cover `sleeper/`, `matchups/`, `analytics/`, and `players/`") -- this is
that page, written last because it needed no other page's normalization
logic to explain, only its own methods.

Conventions on this page (matching `docs/league.md`, `docs/matchups.md`,
`docs/analytics.md`, `docs/players-data.md`, `docs/players-analytics.md`):

- Source links point at a specific line in the current `main` (commit
  `dec9ca5` at time of writing). **Line numbers drift as the code
  changes** -- if a link looks wrong, search the module for the symbol name
  rather than trusting the anchor.
- Sleeper IDs (`user_id`, `roster_id`, `league_id`, `player_id`, `matchup_id`,
  `draft_id`) are the only reliable join keys this layer hands you; usernames
  and display names are mutable labels, never join keys (see AGENTS.md's
  "Data Modeling Guidelines").
- "Verified offline" below means run against real data with
  `.venv/bin/python`, entirely offline: `requests_mock` intercepts every HTTP
  call and serves this repository's own sanitized fixtures under
  `tests/fixtures/sleeper/*.json` -- the same fixtures `tests/sleeper/`
  itself asserts against. **No live Sleeper call was made anywhere on this
  page.** If you want to see this layer verified against a real account, see
  `docs/league.md`'s quick start, which does run live (dated 2026-08-26) one
  layer up, through `load_league_snapshot`.

## What this layer is for

`sleeper/` is the only place in this codebase that talks to the Sleeper HTTP
API. [`SleeperClient`](../src/fantasy_analyzer/sleeper/client.py#L21) is a
thin wrapper: one method per endpoint, each returning Sleeper's raw JSON
response (a `dict` or `list[dict]`) completely unmodified -- no renaming, no
joining, no derived fields. All of that normalization work happens one layer
up, in `fantasy_analyzer.league` ([`docs/league.md`](league.md)) and
`fantasy_analyzer.matchups` ([`docs/matchups.md`](matchups.md)). That split
is deliberate (AGENTS.md's "Separation of Concerns"): this layer can be
tested with mocked HTTP and no normalization logic to get wrong, and every
other layer can be tested with plain dicts and no HTTP to mock.

The one exception to "no processing" is
[`sleeper/cache.py`](../src/fantasy_analyzer/sleeper/cache.py): Sleeper's
full NFL player catalog (`SleeperClient.get_players()`) is a multi-megabyte
JSON blob that changes slowly, so this module adds a thin disk-caching layer
around it -- still no normalization, just avoiding a repeated multi-megabyte
download.

## Quick start: username to league_id to raw building blocks

Put your own Sleeper username, season, and league selection where
`YOUR_SLEEPER_USERNAME` appears below -- `schneidbaby`/2025 is this
package's validation case, not part of the API, and nothing in this layer
hard-codes it.

```python
from fantasy_analyzer.sleeper.client import SleeperClient

client = SleeperClient()

# 1. Username -> Sleeper's immutable user_id.
user = client.get_user("YOUR_SLEEPER_USERNAME")

# 2. Every league that user_id is in for a season.
leagues = client.get_leagues(user["user_id"], season=2025)
league_id = leagues[0]["league_id"]  # pick the league you actually want

# 3. The three raw building blocks docs/league.md's build_league_snapshot
#    composes into a LeagueSnapshot.
league = client.get_league(league_id)
rosters = client.get_rosters(league_id)
users = client.get_users(league_id)
```

**Verified offline** with `.venv/bin/python`, `requests_mock` serving
`tests/fixtures/sleeper/{user,leagues,league,rosters,users}.json` in place
of the real Sleeper API (so the printed values below are this repo's
2-team toy fixture, not a real league):

```text
user_id: 123456789012345678
league_id: 111111111111111111
Test League 2025 10
2 rosters, 2 users
123456789012345678 -> ['Test User']
```

The last line resolves roster 1's raw `owner_id` against `users` by hand --
exactly the join `fantasy_analyzer.league.teams.build_team_mapping` does for
you (see [`docs/league.md`](league.md#leagueteamspy--who-owns-which-roster)).
This layer stops at "here are the raw dicts"; joining them into
`teams_df`/`LeagueSnapshot` is the next page's job.

## Reference

### `fantasy_analyzer.sleeper` (package exports)

[`__init__.py`](../src/fantasy_analyzer/sleeper/__init__.py) re-exports this
layer's public surface. Import from the package directly
(`from fantasy_analyzer.sleeper import ...`) rather than reaching into
submodules -- the
[`__all__`](../src/fantasy_analyzer/sleeper/__init__.py#L17) list is the
contract:

`SleeperClient`, `SleeperAPIError`, `SleeperHTTPError`, `SleeperTimeoutError`,
`SleeperConnectionError`, `DEFAULT_CACHE_PATH`, `load_player_cache`,
`refresh_player_cache`, `get_players_cached`.

Note that `SleeperClient` is importable both as
`fantasy_analyzer.sleeper.SleeperClient` and, as used throughout this doc
series and the test suite, `fantasy_analyzer.sleeper.client.SleeperClient` --
both names resolve to the same class.

### `sleeper/client.py` -- `SleeperClient`

**[`SleeperClient`](../src/fantasy_analyzer/sleeper/client.py#L21)** class,
constructed as
**[`SleeperClient(timeout: int = 10)`](../src/fantasy_analyzer/sleeper/client.py#L26)**
-- `BASE_URL = "https://api.sleeper.app/v1"` is a class attribute (not
configurable per instance). The constructor stores `timeout` (seconds,
applied to every request via `requests`' own `timeout` parameter) and opens
one `requests.Session()` per client instance, reused across every call for
connection pooling -- construct one `SleeperClient` and reuse it for a whole
analysis run rather than building a new one per call.

**[`_get(self, endpoint: str, params: Optional[dict] = None)`](../src/fantasy_analyzer/sleeper/client.py#L30)**
-- private, but it is the single request path every public method below
funnels through, so its behavior explains all of them at once:

- Builds the URL as `f"{BASE_URL}/{endpoint.lstrip('/')}"` -- a leading
  slash on `endpoint` is stripped, so `_get("/foo/bar")` and `_get("foo/bar")`
  hit the identical URL.
- Passes `params` straight to `requests`' own query-string encoding (e.g.
  `bool` params get lowercased by the *caller*, not `_get` itself -- see
  `get_players` below).
- Converts `requests.exceptions.Timeout` -> `SleeperTimeoutError`,
  `requests.exceptions.ConnectionError` -> `SleeperConnectionError`, and any
  non-2xx HTTP status -> `SleeperHTTPError` (see "Exceptions" below for what
  each carries). On success, returns `response.json()` -- the decoded body,
  unmodified.

Every public method's docstring below is Sleeper's own one-line description
of what the endpoint returns; this page adds the shape/behavior detail the
docstrings don't spell out, drawn from `tests/sleeper/test_client.py` and
this repository's fixtures.

| Method | Endpoint | Returns | Notes |
|---|---|---|---|
| [`get_user(username_or_id)`](../src/fantasy_analyzer/sleeper/client.py#L65) | `user/{username_or_id}` | `dict` | Accepts a username *or* a `user_id` -- Sleeper resolves either. **Raises `ValueError`** (not a `SleeperAPIError`) if Sleeper returns HTTP 200 with a literal JSON `null` body, which is how Sleeper signals an unknown username (not a 404) -- see "Exceptions" below. |
| [`get_leagues(user_id, season, sport="nfl")`](../src/fantasy_analyzer/sleeper/client.py#L78) | `user/{user_id}/leagues/{sport}/{season}` | `list[dict]` | `season` is an `int` in the call signature; Sleeper's response echoes it back as a string (`league["season"] == "2025"`). Empty list, not an error, if the user is in no leagues that season. |
| [`get_league(league_id)`](../src/fantasy_analyzer/sleeper/client.py#L82) | `league/{league_id}` | `dict` | Metadata plus the nested `settings` and `scoring_settings` blocks -- see [`docs/league.md`](league.md#leaguesettingspy--league-rules-and-scoring) for how these are normalized into `LeagueSettings`. |
| [`get_rosters(league_id)`](../src/fantasy_analyzer/sleeper/client.py#L86) | `league/{league_id}/rosters` | `list[dict]` | Each roster carries `roster_id`, `owner_id`, `players`, `starters`, and a `settings` block with `wins`/`losses`/`ties`/`fpts`/`fpts_decimal`/etc. (the whole/decimal split `docs/league.md` combines into one float). |
| [`get_users(league_id)`](../src/fantasy_analyzer/sleeper/client.py#L90) | `league/{league_id}/users` | `list[dict]` | Each user carries `user_id`, `display_name`, and a `metadata` dict that may or may not have `team_name` set. |
| [`get_matchups(league_id, week)`](../src/fantasy_analyzer/sleeper/client.py#L98) | `league/{league_id}/matchups/{week}` | `list[dict]` | One entry per **roster** (not per matchup), pairable by shared `matchup_id`. See [`docs/matchups.md`](matchups.md) for how pairs, byes, and the season-long DataFrame are built from this. |
| [`get_winners_bracket(league_id)`](../src/fantasy_analyzer/sleeper/client.py#L106) | `league/{league_id}/winners_bracket` | `list[dict]` | Each entry keyed `r`/`m`/`t1`/`t2`/`w`/`l`, plus optional `t1_from`/`t2_from` (which prior match feeds this slot) and `p` (placement, e.g. `p: 1` marks the championship game). See [`docs/matchups.md`](matchups.md) for normalization into readable placements. |
| [`get_losers_bracket(league_id)`](../src/fantasy_analyzer/sleeper/client.py#L110) | `league/{league_id}/losers_bracket` | `list[dict]` | Same shape as the winners bracket, for the consolation bracket. |
| [`get_transactions(league_id, week)`](../src/fantasy_analyzer/sleeper/client.py#L118) | `league/{league_id}/transactions/{week}` | `list[dict]` | Mixes `"waiver"`/`"free_agent"`/`"trade"` types in one list; `adds`/`drops` are `dict[player_id, roster_id]` and either can be `None` (e.g. a free-agent add with no corresponding drop). |
| [`get_drafts(league_id)`](../src/fantasy_analyzer/sleeper/client.py#L126) | `league/{league_id}/drafts` | `list[dict]` | Each draft carries `draft_id`, `type` (e.g. `"snake"`), `status`, and `slot_to_roster_id`. |
| [`get_draft_picks(draft_id)`](../src/fantasy_analyzer/sleeper/client.py#L130) | `draft/{draft_id}/picks` | `list[dict]` | Ordered by `pick_no` ascending; each pick links `player_id` to `roster_id`/`picked_by`, with `round` and a `metadata` dict duplicating some player info inline. Note this is keyed by `draft_id`, not `league_id` -- get it from `get_drafts()` first. |
| [`get_players(position=None, active=None)`](../src/fantasy_analyzer/sleeper/client.py#L138) | `players/nfl` | `dict` keyed by `player_id` | Sleeper's full player database -- large (5MB+), no pagination. `position` is passed through as-is (e.g. `"QB"`); `active` is converted with `str(active).lower()` before being sent, so `active=True` becomes the query string `active=true`. **Prefer `sleeper/cache.py` (below) over calling this repeatedly.** |

`get_user`'s docstring says "Get Sleeper user information" -- but its actual
behavior (raising `ValueError` on a 200-with-`null` response rather than
returning `None` or raising a `SleeperAPIError`) is only in the code and
`tests/sleeper/test_client.py::test_get_user_raises_for_missing_user`, not
in the docstring itself. Treat that as the documented contract; see "API
notes" in the accompanying report for why this is worth flagging rather than
fixing here.

```python
import requests_mock as requests_mock_lib
from fantasy_analyzer.sleeper.client import SleeperClient

client = SleeperClient()
with requests_mock_lib.Mocker() as m:
    m.get(f"{SleeperClient.BASE_URL}/user/doesnotexist", status_code=200,
          text="null", headers={"Content-Type": "application/json"})
    try:
        client.get_user("doesnotexist")
    except ValueError as exc:
        print("ValueError:", exc)
```

**Verified offline** -- real output: `ValueError: Sleeper user 'doesnotexist' was not found.`

### `sleeper/exceptions.py` -- what raises, and what to catch

All four exceptions live in
[`sleeper/exceptions.py`](../src/fantasy_analyzer/sleeper/exceptions.py) and
share one base class, so a caller that doesn't care *why* a Sleeper call
failed can catch just
**[`SleeperAPIError`](../src/fantasy_analyzer/sleeper/exceptions.py#L8)**:

| Exception | Raised when | Extra attributes | Which calls can raise it |
|---|---|---|---|
| [`SleeperAPIError`](../src/fantasy_analyzer/sleeper/exceptions.py#L8) | Never raised directly -- base class for the three below. | -- | Catch this to handle any Sleeper-API-layer failure generically. |
| [`SleeperHTTPError`](../src/fantasy_analyzer/sleeper/exceptions.py#L12) | Sleeper responds with a 4xx or 5xx status. | `status_code: int`, `response: requests.Response` (the raw response object, so a caller can inspect `.text`/`.headers` if needed) | Every method that calls `_get` -- i.e. every public method in the table above, including `get_players()`. |
| [`SleeperTimeoutError`](../src/fantasy_analyzer/sleeper/exceptions.py#L27) | The request exceeds `client.timeout` seconds. | none beyond the message | Same as above -- any method, via `_get`. |
| [`SleeperConnectionError`](../src/fantasy_analyzer/sleeper/exceptions.py#L31) | The request cannot connect at all (DNS failure, network down, etc.). | none beyond the message | Same as above -- any method, via `_get`. |

**One documented exception to "every method can raise a `SleeperAPIError`":**
[`get_user`](../src/fantasy_analyzer/sleeper/client.py#L65) can *also* raise
a plain built-in `ValueError` for an unknown username -- Sleeper returns
HTTP 200 (not 404) with a literal JSON `null` body in that case, so `_get`
never sees a non-2xx status to turn into a `SleeperHTTPError`. A caller
handling `get_user` specifically needs to catch both `SleeperAPIError` *and*
`ValueError`; every other method in the table above only needs
`SleeperAPIError` (or one of its three subclasses, if you need to
distinguish HTTP failure from timeout from connection failure).

```python
import requests
import requests_mock as requests_mock_lib
from fantasy_analyzer.sleeper import (
    SleeperClient, SleeperConnectionError, SleeperHTTPError, SleeperTimeoutError,
)

client = SleeperClient()

with requests_mock_lib.Mocker() as m:
    m.get(f"{SleeperClient.BASE_URL}/league/does-not-exist", status_code=404)
    try:
        client.get_league("does-not-exist")
    except SleeperHTTPError as exc:
        print("HTTPError:", exc.status_code)

with requests_mock_lib.Mocker() as m:
    m.get(f"{SleeperClient.BASE_URL}/league/111", exc=requests.exceptions.Timeout)
    try:
        client.get_league("111")
    except SleeperTimeoutError:
        print("TimeoutError raised")

with requests_mock_lib.Mocker() as m:
    m.get(f"{SleeperClient.BASE_URL}/league/111", exc=requests.exceptions.ConnectionError)
    try:
        client.get_league("111")
    except SleeperConnectionError:
        print("ConnectionError raised")
```

**Verified offline** -- real output:

```text
HTTPError: 404
TimeoutError raised
ConnectionError raised
```

### `sleeper/cache.py` -- local player-catalog cache

**Answers:** "how do I avoid re-downloading Sleeper's 5MB+ player database
on every run." Sleeper does not version or paginate this endpoint, so this
module is a plain read-through disk cache, one JSON file, no TTL.

- **[`DEFAULT_CACHE_PATH`](../src/fantasy_analyzer/sleeper/cache.py#L28)** =
  `Path(".cache/sleeper/players.json")`, relative to the current working
  directory. Not a hidden global -- every function below takes `path` as an
  explicit argument and defaults to this constant; pass your own path if you
  want the cache elsewhere.
- **No TTL/staleness check, by design** (per the module docstring): the
  Sleeper player catalog changes slowly, and a cache file is used forever
  once written, until a caller explicitly calls `refresh_player_cache` or
  passes `force_refresh=True`.

| Function | Signature | Network? | Behavior |
|---|---|---|---|
| [`load_player_cache`](../src/fantasy_analyzer/sleeper/cache.py#L31) | `(path=DEFAULT_CACHE_PATH) -> Optional[dict]` | Never | `None` if no file exists at `path` yet; otherwise the parsed JSON. |
| [`refresh_player_cache`](../src/fantasy_analyzer/sleeper/cache.py#L46) | `(client, path=DEFAULT_CACHE_PATH) -> dict` | Always | Calls `client.get_players()`, writes the result to `path` (creating parent directories as needed), overwriting any existing file. **This is the only way to invalidate a stale cache.** |
| [`get_players_cached`](../src/fantasy_analyzer/sleeper/cache.py#L64) | `(client, path=DEFAULT_CACHE_PATH, force_refresh=False) -> dict` | Only on a cache miss (or `force_refresh=True`) | The function most callers want: reads the cache if present, else downloads and writes one via `refresh_player_cache`. This is what [`load_league_snapshot`](../src/fantasy_analyzer/league/snapshot.py#L208) uses internally (see [`docs/league.md`](league.md#leaguesnapshotpy--the-composed-object)), at `.cache/sleeper/players.json` by default. |

```python
from pathlib import Path
import requests_mock as requests_mock_lib
import json

from fantasy_analyzer.sleeper import SleeperClient
from fantasy_analyzer.sleeper.cache import (
    load_player_cache, refresh_player_cache, get_players_cached,
)

fixture = json.load(open("tests/fixtures/sleeper/players.json"))
cache_path = Path("/tmp/sleeper_cache_demo/players.json")
client = SleeperClient()

print(load_player_cache(cache_path))  # nothing cached yet -> None

with requests_mock_lib.Mocker() as m:
    m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=fixture)
    get_players_cached(client, cache_path)
    print("network call on cache miss:", m.called)

with requests_mock_lib.Mocker() as m:
    m.get(f"{SleeperClient.BASE_URL}/players/nfl", json={})
    get_players_cached(client, cache_path)
    print("network call on cache hit:", m.called)

with requests_mock_lib.Mocker() as m:
    m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=fixture)
    get_players_cached(client, cache_path, force_refresh=True)
    print("network call with force_refresh=True:", m.called)
```

**Verified offline** -- real output:

```text
None
network call on cache miss: True
network call on cache hit: False
network call with force_refresh=True: True
```

## Edge cases worth knowing (from `tests/sleeper/`)

- **Unknown username returns HTTP 200 with body `null`, not a 404.**
  `get_user` handles this explicitly and raises `ValueError`, the one method
  in this layer whose failure mode isn't a `SleeperAPIError` subclass -- see
  "Exceptions" above.
  ([`test_get_user_raises_for_missing_user`](../tests/sleeper/test_client.py#L143)).
- **A leading slash on the endpoint argument to `_get` is stripped**, so
  `client._get("/foo/bar")` and `client._get("foo/bar")` hit the same URL --
  irrelevant to normal callers (every public method already passes a
  slash-free endpoint), but relevant if you're extending `SleeperClient`
  yourself
  ([`test_get_centralizes_url_construction`](../tests/sleeper/test_client.py#L40)).
- **`get_players(active=True)` lowercases the boolean for the query string**
  (`active=true`, not `active=True`) -- Sleeper's API expects a lowercase
  string, and `_get` itself does no such conversion; `get_players` does it
  before calling `_get`
  ([`test_get_players_with_filters`](../tests/sleeper/test_client.py#L514)).
- **`get_leagues`'s `season` argument is an `int`, but Sleeper's response
  echoes it back as a string** (`league["season"] == "2025"`) -- don't
  compare it to an `int` downstream
  ([`test_get_leagues_for_2025_season_returns_league_list`](../tests/sleeper/test_client.py#L174)).
- **`refresh_player_cache` always overwrites**, even a cache file with
  different/stale content -- there is no merge or diff, just last-write-wins
  ([`test_refresh_player_cache_overwrites_stale_data`](../tests/sleeper/test_cache.py#L92)).
- **`get_players_cached(force_refresh=True)` ignores an existing cache file
  entirely** and always hits the network, then overwrites the cache
  ([`test_get_players_cached_force_refresh_ignores_existing_cache`](../tests/sleeper/test_cache.py#L109)).

## What's next

`SleeperClient`'s raw dicts are the input to
[`fantasy_analyzer.league`](league.md) (normalized league/team/player
structures, `LeagueSnapshot`) and, via `get_matchups`, to
[`fantasy_analyzer.matchups`](matchups.md) (the season matchup DataFrame and
playoff bracket normalization). `sleeper/cache.py`'s `get_players_cached` is
what `load_league_snapshot` calls internally so a full-season analysis
doesn't re-download the player catalog on every run. Neither of those
downstream layers is documented here -- see `docs/league.md` and
`docs/matchups.md`.
