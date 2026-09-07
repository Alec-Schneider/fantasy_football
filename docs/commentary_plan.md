# Plan: League & Matchup Commentary via Claude

## The Pro-account question, answered first

**Claude Pro (claude.ai) does not include programmatic API access.** Pro is a
chat-UI subscription; the Anthropic API (`api.anthropic.com`) is a separate
product with its own pay-as-you-go billing and API key, provisioned at
[console.anthropic.com](https://console.anthropic.com). Having Pro doesn't
unlock a Python `anthropic` client call.

That leaves three realistic ways to actually get commentary written, in order
of setup cost:

1. **Manual copy/paste into claude.ai (uses your existing Pro plan, $0 extra).**
   The package generates a fully-formed prompt (see below); you paste it into
   a Claude chat each week and get commentary back. Zero new infrastructure.
2. **Ask Claude Code to do it (uses your existing Claude Code access, no API key).**
   Claude Pro/Max plans include some amount of Claude Code usage. You (or a
   scheduled agent, via the `schedule` skill) can hand this session the same
   context bundle and have it write the commentary directly — no `anthropic`
   SDK, no separate billing, but usage counts against your Claude Code limits
   and it's a Claude Code session doing the writing, not a script you can run
   unattended outside that environment.
3. **Automate with the Anthropic API (new API key, metered billing).**
   A small `commentary/client.py` provider (same shape as the existing
   `players/nflverse_client.py`) calls the API directly from a script, so the
   whole pipeline — pull data, build prompt, get commentary, post it somewhere
   — runs unattended (cron, GitHub Action, etc.) without a human in the loop.

Recommendation: build the prompt-generation piece first (useful under mode 1
or 2 immediately, costs nothing), and treat mode 3 as an optional later
ticket once you know you want full automation.

---

## What already exists that this can reuse

The `analytics/` and `players/` layers already compute everything a
commentary prompt needs — this plan adds a layer *on top* of them, not a
parallel data path (per AGENTS.md's separation-of-concerns rule).

| Need | Existing source |
|---|---|
| Weekly matchup pairings & scores | `matchups/season_matchups.py`, `analytics/matchup_history.py` |
| Win/loss, margin | `matchups/outcomes.py` |
| Historical head-to-head | `analytics/head_to_head.py`, `analytics/rivalries.py` |
| Standings, scoring summary | `analytics/standings.py`, `analytics/summary.py` |
| Power rankings (week-over-week) | `analytics/power_rankings.py` |
| Weekly scoring ranks / league-wide highs & lows | `analytics/weekly_scores.py` |
| All-play record (how a team fared vs. the whole league that week) | `analytics/all_play.py` |
| Expected wins / schedule luck | `analytics/schedule_luck.py` |
| Consistency (boom/bust) | `analytics/consistency.py` |
| Strength of schedule | `analytics/strength_of_schedule.py` |
| Which players drove a matchup win/loss | `players/matchup_contribution.py` |
| Lineup efficiency / bench points left on the table | `players/lineup_efficiency.py` |
| Manager tendencies (start/sit patterns) | `players/lineup_tendencies.py` |
| Player value vs. replacement | `players/player_value.py`, `players/player_rankings.py` |

None of this needs to change. The new work is purely: assemble the right
subset of it into a structured, LLM-friendly bundle for a given week or
league.

---

## New module: `fantasy_analyzer/commentary/`

Following the existing package layout, add a new top-level package:

```text
src/fantasy_analyzer/commentary/
├── __init__.py
├── context.py      # pure functions: analytics objects -> structured dict/dataclass
├── prompts.py       # pure functions: structured dict -> prompt text (Jinja/f-strings)
└── client.py         # OPTIONAL, later: Anthropic API call wrapper (mode 3 only)
```

`context.py` and `prompts.py` have **no network dependency** and are fully
unit-testable with fixture data, consistent with AGENTS.md's "analytics
functions must be deterministic and testable without live HTTP" rule. They
take already-computed `LeagueSnapshot` / matchup / analytics DataFrames as
input — the same objects the CLI and notebooks already build.

`client.py` (mode 3 only) is the one piece allowed to touch the network, kept
isolated exactly like `sleeper/client.py` and `players/nflverse_client.py`
already isolate *their* network calls from computation.

### Two context builders

**1. Weekly matchup context** — `build_matchup_context(snapshot, matchups_df, week)`

For each pairing that week, assembles:
- final score, margin, projected score if available
- top contributors on each side (from `matchup_contribution`)
- bench points left on the table (from `lineup_efficiency`) — "would have won
  if they'd started X"
- all-play record for the week (was this a top-half score that just ran into
  a buzzsaw, or a bottom-half win?)
- historical head-to-head record between these two managers
- notable streaks (win streak snapped, revenge game, etc.)

**2. League-wide weekly recap context** — `build_league_week_context(snapshot, analytics, week)`

- standings after the week, and movement since last week
- power ranking deltas
- weekly scoring leaderboard (highest/lowest score, biggest blowout, closest
  game)
- schedule luck outliers (team that's over/under-performing expected wins)
- any milestone (clinched playoff spot, mathematically eliminated, etc. —
  only if `playoffs.py` boundary logic says so)

Both return a plain dataclass/dict — inspect it directly in a notebook,
`json.dumps` it, or feed it to `prompts.py`.

### Prompt templates

`prompts.py` turns a context object into prompt text with a fixed structure:
role/goal framing, the data (as a compact table or JSON block, not prose —
let Claude do the writing), and explicit constraints (tone, length, which
teams/managers to call out by name, "don't invent stats not present in the
data"). Two templates to start:

- `weekly_matchup_prompt(context, tone="witty")` — one prompt per matchup, or
  a combined prompt covering all matchups in a week
- `league_week_recap_prompt(context, tone="witty")` — one prompt for the
  league-wide recap

Keep tone/length as parameters, not hardcoded — leagues differ in how much
snark they want.

---

## CLI surface

Add a `commentary` subcommand mirroring the existing `summary` subcommand:

```bash
# Print a ready-to-paste prompt for a week's matchups.
fantasy-analyzer commentary matchups <league_id> --week 3

# Print a ready-to-paste prompt for the league-wide weekly recap.
fantasy-analyzer commentary recap <league_id> --week 3

# Mode 3 only, later: generate and print the finished commentary directly.
fantasy-analyzer commentary matchups <league_id> --week 3 --generate
```

Without `--generate`, the command just prints the prompt text to stdout —
you copy it into claude.ai or hand it to this session. `--generate` is the
only path that touches `commentary/client.py` and requires
`ANTHROPIC_API_KEY` to be set; everything else stays zero-cost.

---

## Suggested ticket sequence

Following AGENTS.md's Data Scientist / Software Engineer split:

- **FFA-080** — Build weekly matchup context builder (`commentary/context.py`,
  matchup half) — Data Scientist agent — defines exactly which fields go in,
  with a hand-checkable toy example (per AGENTS.md's analytics
  Definition-of-Done)
- **FFA-081** — Build league-week recap context builder (`commentary/context.py`,
  league half) — Data Scientist agent
- **FFA-082** — Build prompt templates (`commentary/prompts.py`) — Software
  Engineer agent
- **FFA-083** — Add `commentary` CLI subcommand (prompt-only, no API) —
  Software Engineer agent
- **FFA-084** *(optional, do only once you want full automation)* — Add
  `commentary/client.py` Anthropic API provider + `--generate` flag —
  Software Engineer agent — requires deciding on API billing first

FFA-080/081 can happen in parallel; FFA-082 depends on both; FFA-083 depends
on FFA-082; FFA-084 is independent and can slip to a later sprint.

---

## Automation / cadence (once the manual flow works)

If you want this to run itself instead of you remembering to run it every
Tuesday:

- **No API key:** use the `schedule` skill to create a scheduled cloud agent
  that runs Claude Code weekly (after Sleeper's Tuesday stat corrections),
  reads the context bundle, writes commentary, and posts it wherever you want
  (Slack, a repo file, etc.). Counts against Claude Code usage, not API
  billing.
- **With an API key (FFA-084):** a plain cron job or GitHub Action calling
  `fantasy-analyzer commentary ... --generate` and posting the output (e.g.
  to a Discord/Slack webhook). Fully unattended, metered per-token cost.

Either way, cache the generated commentary per `(league_id, week)` so a rerun
doesn't regenerate (and re-bill, in mode 3) work that already happened —
consistent with the existing `sleeper/cache.py` / `nflverse_cache.py` pattern
elsewhere in the codebase.
