<title>The Schneid Desk</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=IBM+Plex+Mono:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>
  :root {
    --ground: #eaeef2;
    --surface: #ffffff;
    --surface-2: #f4f7f9;
    --surface-3: #e9eef3;
    --ink: #121a22;
    --ink-2: #33414f;
    --muted: #5d6c7a;
    --line: #d2dbe3;
    --line-strong: #b6c3ce;
    --accent: #1f3a5f;
    --accent-ink: #ffffff;
    --accent-soft: #dce6f1;
    --brass: #9a6c12;
    --pos: #1d6b52;
    --pos-soft: #d7ebe2;
    --neg: #9e3639;
    --neg-soft: #f4dedd;
    --shadow: 0 1px 2px rgba(18, 26, 34, .06), 0 8px 24px -16px rgba(18, 26, 34, .3);

    --display: "Bricolage Grotesque", "Trebuchet MS", sans-serif;
    --serif: "Source Serif 4", Georgia, "Times New Roman", serif;
    --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
  }

  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground: #0c1218;
      --surface: #141c24;
      --surface-2: #1a242d;
      --surface-3: #212d38;
      --ink: #e7eef4;
      --ink-2: #c2ceda;
      --muted: #8fa0ae;
      --line: #27333d;
      --line-strong: #3a4956;
      --accent: #85adda;
      --accent-ink: #0c1218;
      --accent-soft: #1b2a3a;
      --brass: #d3a244;
      --pos: #52bf95;
      --pos-soft: #14302a;
      --neg: #e4746f;
      --neg-soft: #35201f;
      --shadow: 0 1px 2px rgba(0, 0, 0, .5), 0 8px 24px -16px rgba(0, 0, 0, .8);
    }
  }

  :root[data-theme="dark"] {
    --ground: #0c1218;
    --surface: #141c24;
    --surface-2: #1a242d;
    --surface-3: #212d38;
    --ink: #e7eef4;
    --ink-2: #c2ceda;
    --muted: #8fa0ae;
    --line: #27333d;
    --line-strong: #3a4956;
    --accent: #85adda;
    --accent-ink: #0c1218;
    --accent-soft: #1b2a3a;
    --brass: #d3a244;
    --pos: #52bf95;
    --pos-soft: #14302a;
    --neg: #e4746f;
    --neg-soft: #35201f;
    --shadow: 0 1px 2px rgba(0, 0, 0, .5), 0 8px 24px -16px rgba(0, 0, 0, .8);
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--ground);
    color: var(--ink);
    font-family: var(--display);
    font-size: 15px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }

  .wrap {
    max-width: 1140px;
    margin: 0 auto;
    padding-inline: 20px;
    padding-block: 0 72px;
  }

  /* ---------- control bar ---------- */

  .bar {
    position: sticky;
    top: env(safe-area-inset-top, 0px);
    z-index: 20;
    /* Opaque fallback first: where color-mix is unsupported the declaration
       below is dropped, and a transparent bar would let the page scroll
       under its own controls. */
    background: var(--ground);
    background: color-mix(in srgb, var(--ground) 88%, transparent);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--line);
  }

  .bar-inner {
    max-width: 1140px;
    margin: 0 auto;
    padding-inline: 20px;
    padding-block: 12px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px 20px;
  }

  .brand {
    display: flex;
    flex-direction: column;
    gap: 1px;
    margin-right: auto;
  }

  .brand b {
    font-family: var(--display);
    font-weight: 800;
    font-size: 17px;
    letter-spacing: -.02em;
  }

  .brand span {
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .seg {
    display: flex;
    background: var(--surface-3);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 3px;
    gap: 2px;
  }

  .seg button {
    font-family: var(--display);
    font-weight: 600;
    font-size: 13px;
    color: var(--muted);
    background: none;
    border: 0;
    border-radius: 999px;
    padding: 6px 14px;
    cursor: pointer;
    white-space: nowrap;
    transition: background .15s, color .15s;
  }

  .seg button:hover { color: var(--ink); }

  .seg button[aria-pressed="true"] {
    background: var(--accent);
    color: var(--accent-ink);
  }

  .stepper {
    display: flex;
    align-items: center;
    gap: 2px;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 3px;
  }

  .stepper button {
    width: 30px;
    height: 28px;
    display: grid;
    place-items: center;
    background: none;
    border: 0;
    border-radius: 999px;
    color: var(--ink);
    font-size: 15px;
    cursor: pointer;
  }

  .stepper button:hover:not(:disabled) { background: var(--surface-3); }
  .stepper button:disabled { color: var(--line-strong); cursor: default; }

  .stepper .label {
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .04em;
    text-transform: uppercase;
    padding: 0 8px;
    min-width: 74px;
    text-align: center;
  }

  /* ---------- section scaffolding ---------- */

  .phase {
    display: flex;
    align-items: baseline;
    gap: 14px;
    margin: 44px 0 18px;
  }

  .phase::after {
    content: "";
    flex: 1;
    height: 1px;
    background: var(--line);
  }

  .phase h2 {
    margin: 0;
    font-family: var(--display);
    font-weight: 800;
    font-size: clamp(21px, 3.4vw, 27px);
    letter-spacing: -.025em;
    text-wrap: balance;
  }

  .phase .tag {
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
  }

  section > h3 {
    margin: 0 0 10px;
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--muted);
  }

  section { margin-bottom: 26px; }

  .panel {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
  }

  /* ---------- my team strip ---------- */

  .me {
    margin-top: 26px;
    background: var(--surface);
    border: 1px solid var(--line);
    border-left: 4px solid var(--accent);
    border-radius: 10px;
    box-shadow: var(--shadow);
    padding: 18px 20px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 18px 30px;
  }

  .me-id { margin-right: auto; }

  .me-id .who {
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .me-id .team {
    font-family: var(--display);
    font-weight: 800;
    font-size: clamp(20px, 3.6vw, 26px);
    letter-spacing: -.025em;
    line-height: 1.15;
  }

  .stat { display: flex; flex-direction: column; gap: 2px; }

  .stat .k {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .stat .v {
    font-family: var(--mono);
    font-size: 19px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .stat .v small {
    font-size: 12px;
    font-weight: 400;
    color: var(--muted);
  }

  /* ---------- matchups ---------- */

  .matchups {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(268px, 1fr));
    gap: 10px;
  }

  .mu {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }

  .mu.mine {
    border-color: var(--accent);
    box-shadow: inset 3px 0 0 var(--accent);
  }

  .mu-row {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }

  .mu-row .nm {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 14px;
    color: var(--muted);
  }

  .mu-row.win .nm { color: var(--ink); font-weight: 600; }

  .mu-row .pts {
    font-family: var(--mono);
    font-size: 14.5px;
    font-variant-numeric: tabular-nums;
    color: var(--muted);
  }

  .mu-row.win .pts { color: var(--ink); font-weight: 600; }

  .mu-foot {
    border-top: 1px dashed var(--line);
    padding-top: 6px;
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: var(--muted);
  }

  /* ---------- recap ---------- */

  .recap {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 24px clamp(18px, 4vw, 34px);
  }

  .recap .body {
    font-family: var(--serif);
    font-size: 16.5px;
    line-height: 1.68;
    color: var(--ink-2);
    max-width: 64ch;
  }

  .recap .body p { margin: 0 0 14px; }
  .recap .body p:last-child { margin-bottom: 0; }
  .recap .body strong { color: var(--ink); font-weight: 600; }

  .recap .body p:first-child::first-letter {
    float: left;
    font-family: var(--display);
    font-weight: 800;
    font-size: 3.1em;
    line-height: .82;
    padding: .06em .09em 0 0;
    color: var(--accent);
  }

  /* ---------- tables ---------- */

  .scroll { overflow-x: auto; }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13.5px;
  }

  th {
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .09em;
    text-transform: uppercase;
    color: var(--muted);
    text-align: right;
    padding: 9px 10px;
    border-bottom: 1px solid var(--line-strong);
    white-space: nowrap;
  }

  th:first-child, td:first-child { text-align: right; width: 1%; }
  th.l, td.l { text-align: left; }

  td {
    padding: 8px 10px;
    text-align: right;
    border-bottom: 1px solid var(--line);
    font-variant-numeric: tabular-nums;
    font-family: var(--mono);
    font-size: 12.5px;
    white-space: nowrap;
  }

  td.l {
    font-family: var(--display);
    font-size: 13.5px;
    white-space: normal;
    min-width: 132px;
  }

  tbody tr:last-child td { border-bottom: 0; }
  tbody tr.mine td { background: var(--accent-soft); }
  tbody tr.mine td.l { font-weight: 700; }

  .rk { color: var(--muted); }
  .pos { color: var(--pos); }
  .neg { color: var(--neg); }

  .sub { color: var(--muted); font-size: 11px; }

  /* diverging power bar */
  .bar-cell { width: 128px; min-width: 128px; padding-right: 14px; }

  .track {
    position: relative;
    height: 15px;
    background: var(--surface-2);
    border-radius: 3px;
  }

  .track::before {
    content: "";
    position: absolute;
    left: 50%;
    top: -1px;
    bottom: -1px;
    width: 1px;
    background: var(--line-strong);
  }

  .track i {
    position: absolute;
    top: 3px;
    bottom: 3px;
    border-radius: 2px;
    display: block;
  }

  /* ---------- pills ---------- */

  .pill {
    display: inline-block;
    font-family: var(--mono);
    font-size: 9.5px;
    font-weight: 600;
    letter-spacing: .07em;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 3px;
    vertical-align: 1px;
  }

  .pill.start { background: var(--pos-soft); color: var(--pos); }
  .pill.sit { background: var(--neg-soft); color: var(--neg); }
  .pill.out { background: var(--neg-soft); color: var(--neg); }
  .pill.q { background: var(--surface-3); color: var(--brass); }
  .pill.bye { background: var(--surface-3); color: var(--muted); }
  .pill.lock { background: var(--surface-3); color: var(--ink-2); }
  .pill.ir { background: var(--surface-3); color: var(--ink-2); }
  .pill.hot { background: var(--surface-3); color: var(--brass); }
  .pill.cold { background: var(--pos-soft); color: var(--pos); }

  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }

  .chips button {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .06em;
    color: var(--muted);
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 4px 11px;
    cursor: pointer;
  }

  .chips button:hover { color: var(--ink); }

  .chips button[aria-pressed="true"] {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-ink);
  }

  /* ---------- lineup ---------- */

  .two {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
    gap: 26px;
    align-items: start;
  }

  .slot {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 9px 14px;
    border-bottom: 1px solid var(--line);
  }

  .slot:last-child { border-bottom: 0; }

  .slot .pos-tag {
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .06em;
    color: var(--muted);
    width: 38px;
    flex: none;
  }

  .slot .nm { flex: 1; min-width: 0; }
  .slot .nm b { font-weight: 600; font-size: 14px; }
  .slot .nm .meta { display: block; font-size: 11px; color: var(--muted); font-family: var(--mono); }

  .slot .pp {
    font-family: var(--mono);
    font-size: 13.5px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .slot.swap { background: var(--pos-soft); }
  .slot.drop-out { background: var(--neg-soft); }
  .slot.empty-slot .nm { color: var(--muted); font-style: italic; }

  .moves { display: flex; flex-direction: column; }

  .move {
    padding: 11px 14px;
    border-bottom: 1px solid var(--line);
    display: flex;
    gap: 10px;
    align-items: baseline;
  }

  .move:last-child { border-bottom: 0; }
  .move .n { font-family: var(--mono); font-size: 11px; color: var(--muted); width: 16px; flex: none; }
  .move .txt { flex: 1; min-width: 0; font-size: 13.5px; }
  .move .txt em { font-style: normal; color: var(--muted); }
  .move .gain { font-family: var(--mono); font-size: 13px; font-weight: 600; color: var(--pos); font-variant-numeric: tabular-nums; }
  .move .gain.flat { color: var(--muted); }
  .move .gain small { display: block; font-size: 10px; font-weight: 400; color: var(--muted); text-align: right; }
  .move .detail { display: block; font-family: var(--mono); font-size: 11px; color: var(--muted); margin-top: 2px; }

  /* ---------- notes ---------- */

  .notes {
    margin-top: 40px;
    border-top: 1px solid var(--line);
    padding-top: 20px;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 18px 30px;
  }

  .note h4 {
    margin: 0 0 5px;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .note p {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--muted);
    max-width: 52ch;
  }

  .empty {
    padding: 20px 16px;
    font-size: 13.5px;
    color: var(--muted);
    text-align: center;
  }

  button:focus-visible, a:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation: none !important; }
  }

  @media (max-width: 760px) {
    .two { grid-template-columns: 1fr; gap: 22px; }
    .me { gap: 14px 22px; }
    .brand { width: 100%; margin-right: 0; }
  }
</style>

<div class="bar">
  <div class="bar-inner">
    <div class="brand">
      <b>The Schneid Desk</b>
      <span id="asof">—</span>
    </div>
    <div class="seg" id="leagues" role="group" aria-label="League"></div>
    <div class="stepper">
      <button id="prev" type="button" aria-label="Previous week">&#8249;</button>
      <span class="label" id="weeklabel">Week —</span>
      <button id="next" type="button" aria-label="Next week">&#8250;</button>
    </div>
  </div>
</div>

<div class="wrap">
  <div class="me" id="me"></div>

  <div class="phase">
    <h2 id="histhead">Week —</h2>
    <span class="tag">what happened</span>
  </div>

  <section>
    <h3>Scoreboard</h3>
    <div class="matchups" id="matchups"></div>
  </section>

  <section>
    <h3>Recap</h3>
    <div class="recap"><div class="body" id="recap"></div></div>
  </section>

  <section>
    <h3>Standings <span class="sub">after this week</span></h3>
    <div class="panel scroll"><table id="standings"></table></div>
  </section>

  <section>
    <h3>Power rankings <span class="sub">record, all-play and scoring, z-scored</span></h3>
    <div class="panel scroll"><table id="power"></table></div>
  </section>

  <div class="phase">
    <h2 id="dechead">Week —</h2>
    <span class="tag">what to do</span>
  </div>

  <div class="two">
    <section>
      <h3>Recommended lineup <span class="sub" id="lineupsub"></span></h3>
      <div class="panel" id="lineup"></div>
    </section>
    <section>
      <h3>Best available moves <span class="sub" id="movessub"></span></h3>
      <div class="panel moves" id="moves"></div>
    </section>
  </div>

  <section>
    <h3>Waiver board <span class="sub">free agents by projected rest-of-season value</span></h3>
    <div class="chips" id="wpos" role="group" aria-label="Position"></div>
    <div class="panel scroll"><table id="waivers"></table></div>
  </section>

  <div class="notes" id="notes"></div>
</div>

<script type="application/json" id="bundle">{{DATA}}</script>
<script>
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("bundle").textContent);
  var leagues = DATA.leagues || [];
  var li = 0;
  var wi = 0;

  try {
    var saved = localStorage.getItem("schneid-desk-league");
    if (saved !== null) {
      var found = leagues.findIndex(function (l) { return l.slug === saved; });
      if (found >= 0) { li = found; }
    }
  } catch (e) { /* private window or blocked storage: fall back to the first league */ }

  function num(v, d) {
    if (v === null || v === undefined || isNaN(v)) { return "—"; }
    return Number(v).toFixed(d === undefined ? 1 : d);
  }

  function signed(v, d) {
    if (v === null || v === undefined || isNaN(v)) { return "—"; }
    var s = Number(v).toFixed(d === undefined ? 1 : d);
    return Number(v) > 0 ? "+" + s : s;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = text; }
    return n;
  }

  function label(team) {
    return team.team_name || team.display_name || ("Roster " + team.roster_id);
  }

  function has(v) {
    return v !== null && v !== undefined && !(typeof v === "number" && isNaN(v));
  }

  // Team defenses are keyed by team code and may carry no name.
  function playerName(p) {
    if (p.full_name) { return p.full_name; }
    if (p.position === "DEF") { return (p.team || p.player_id) + " D/ST"; }
    return p.player_id || "—";
  }

  // Shares arrive as fractions (0.78); tolerate a percentage (78) too.
  function share(v) {
    if (!has(v)) { return null; }
    var x = Number(v);
    return Math.abs(x) <= 1.5 ? x * 100 : x;
  }

  function pct(v) {
    var x = share(v);
    return x === null ? "—" : Math.round(x) + "%";
  }

  // Last-two-games snap share against the season: ±5 points is a trend.
  function snapTrend(p) {
    var season = share(p.snap_share);
    var recent = share(p.snap_share_last2);
    if (season === null || recent === null) { return ""; }
    if (recent - season >= 5) { return " ↑"; }
    if (season - recent >= 5) { return " ↓"; }
    return "";
  }

  // Points over expected per game: a big plus is production the usage
  // does not support -- usually touchdowns.
  var LUCK_THRESHOLD = 3.0;

  function luckPill(p) {
    var poe = p.points_over_expected_per_game;
    if (!has(poe)) { return null; }
    if (poe >= LUCK_THRESHOLD) { return el("span", "pill hot", "TD-luck " + signed(poe, 1)); }
    if (poe <= -LUCK_THRESHOLD) { return el("span", "pill cold", "under exp " + signed(poe, 1)); }
    return null;
  }

  function usageLine(p) {
    var bits = [];
    if (has(p.snap_share)) { bits.push("snap " + pct(p.snap_share) + snapTrend(p)); }
    if (has(p.target_share) && /^(RB|WR|TE)$/.test(p.position)) { bits.push("tgt " + pct(p.target_share)); }
    if (has(p.xfp_per_game)) { bits.push("xFP " + num(p.xfp_per_game, 1)); }
    return bits.join(" · ");
  }

  function modelTitle(p) {
    var bits = [];
    if (p.projection_model) { bits.push("model: " + p.projection_model); }
    if (has(p.usage_projected_ppg)) { bits.push("usage " + num(p.usage_projected_ppg, 1)); }
    if (has(p.eb_projected_ppg)) { bits.push("history " + num(p.eb_projected_ppg, 1)); }
    return bits.join(" · ");
  }

  // The lineup is solved on this week's number: K/DEF carry a
  // market-adjusted weekly projection, everyone else their per-game rate.
  function weekPoints(p) {
    return has(p.lineup_ppg) ? p.lineup_ppg : p.projected_ppg;
  }

  function isKdef(p) {
    return p.projection_source === "kicker_defense" || p.position === "K" || p.position === "DEF";
  }

  function hasUsage(rows) {
    return rows.some(function (r) { return has(r.snap_share) || has(r.xfp_per_game); });
  }

  var posFilter = "ALL";

  // ---- control bar -------------------------------------------------

  var segEl = document.getElementById("leagues");
  leagues.forEach(function (lg, i) {
    var b = el("button", null, lg.short_name);
    b.type = "button";
    b.addEventListener("click", function () {
      li = i;
      wi = leagues[li].weeks.length - 1;
      try { localStorage.setItem("schneid-desk-league", leagues[li].slug); } catch (e) { /* ignore */ }
      render();
    });
    segEl.appendChild(b);
  });

  document.getElementById("prev").addEventListener("click", function () {
    if (wi > 0) { wi--; render(); }
  });
  document.getElementById("next").addEventListener("click", function () {
    if (wi < leagues[li].weeks.length - 1) { wi++; render(); }
  });

  // ---- renderers ---------------------------------------------------

  function renderMe(lg, wk) {
    var box = document.getElementById("me");
    box.innerHTML = "";

    var mine = (lg.teams || []).filter(function (t) { return t.roster_id === lg.my_roster_id; })[0];
    var row = (wk.standings || []).filter(function (s) { return s.roster_id === lg.my_roster_id; })[0];
    var pw = (wk.power_rankings || []).filter(function (p) { return p.roster_id === lg.my_roster_id; })[0];

    var id = el("div", "me-id");
    id.appendChild(el("div", "who", lg.name + " · " + lg.scoring_label + " · " + lg.total_rosters + " teams"));
    id.appendChild(el("div", "team", mine ? label(mine) : "My team"));
    box.appendChild(id);

    function stat(k, v, small) {
      var s = el("div", "stat");
      s.appendChild(el("span", "k", k));
      var val = el("span", "v", v);
      if (small) { val.appendChild(el("small", null, " " + small)); }
      s.appendChild(val);
      return s;
    }

    if (row) {
      box.appendChild(stat("Record", Math.round(row.wins) + "–" + Math.round(row.losses) + (row.ties ? "–" + Math.round(row.ties) : "")));
      box.appendChild(stat("Standing", "#" + row.rank, "of " + lg.total_rosters));
      box.appendChild(stat("Points for", num(row.points_for, 1)));
      box.appendChild(stat("Differential", signed(row.point_diff, 1)));
    }
    if (pw) { box.appendChild(stat("Power", "#" + pw.power_rank, num(pw.power_score, 2))); }

    var up = lg.upcoming_matchup;
    if (up && up.opponent) {
      // Live once any game has kicked off; both sides are 0.0 before that.
      var live = (up.points || 0) > 0 || (up.opponent_points || 0) > 0
        ? num(up.points, 1) + "–" + num(up.opponent_points, 1) + " so far"
        : null;
      box.appendChild(stat("Week " + up.week + " vs", up.opponent, live));
    }
  }

  function renderMatchups(lg, wk) {
    var host = document.getElementById("matchups");
    host.innerHTML = "";
    (wk.results || []).forEach(function (m) {
      var mine = m.roster_1_id === lg.my_roster_id || m.roster_2_id === lg.my_roster_id;
      var card = el("div", "mu" + (mine ? " mine" : ""));
      var w1 = m.winner === m.roster_1_id;
      var w2 = m.winner === m.roster_2_id;

      [[m.owner_1, m.points_1, w1], [m.owner_2, m.points_2, w2]].forEach(function (side) {
        var r = el("div", "mu-row" + (side[2] ? " win" : ""));
        r.appendChild(el("span", "nm", side[0] || "—"));
        r.appendChild(el("span", "pts", num(side[1], 2)));
        card.appendChild(r);
      });

      var foot = m.is_tie ? "Tied" : "Margin " + num(m.margin, 2);
      card.appendChild(el("div", "mu-foot", foot));
      host.appendChild(card);
    });
    if (!(wk.results || []).length) {
      host.appendChild(el("div", "empty", "No completed matchups for this week."));
    }
  }

  function renderRecap(wk) {
    var host = document.getElementById("recap");
    host.innerHTML = "";
    var text = wk.commentary;
    if (!text) {
      host.appendChild(el("p", null, "No recap written for this week yet."));
      return;
    }
    text.split(/\n\s*\n/).forEach(function (para) {
      var p = el("p");
      // The recaps use **bold** for manager names; render those and nothing else.
      para.split(/(\*\*[^*]+\*\*)/).forEach(function (chunk) {
        if (/^\*\*[^*]+\*\*$/.test(chunk)) {
          p.appendChild(el("strong", null, chunk.slice(2, -2)));
        } else if (chunk) {
          p.appendChild(document.createTextNode(chunk));
        }
      });
      host.appendChild(p);
    });
  }

  function table(node, cols, rows, build) {
    node.innerHTML = "";
    var thead = el("thead");
    var htr = el("tr");
    cols.forEach(function (c) {
      var th = el("th", c.cls || null, c.t);
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    node.appendChild(thead);

    var tbody = el("tbody");
    rows.forEach(function (r, i) { tbody.appendChild(build(r, i)); });
    node.appendChild(tbody);
  }

  function renderStandings(lg, wk) {
    table(
      document.getElementById("standings"),
      [{ t: "#" }, { t: "Team", cls: "l" }, { t: "W–L" }, { t: "PF" }, { t: "PA" }, { t: "Diff" }],
      wk.standings || [],
      function (s) {
        var tr = el("tr", s.roster_id === lg.my_roster_id ? "mine" : null);
        tr.appendChild(el("td", "rk", s.rank));
        var name = el("td", "l");
        name.appendChild(document.createTextNode(s.team_name || s.display_name || "—"));
        if (s.team_name && s.display_name) {
          name.appendChild(el("span", "sub", " " + s.display_name));
        }
        tr.appendChild(name);
        tr.appendChild(el("td", null, Math.round(s.wins) + "–" + Math.round(s.losses) + (s.ties ? "–" + Math.round(s.ties) : "")));
        tr.appendChild(el("td", null, num(s.points_for, 1)));
        tr.appendChild(el("td", null, num(s.points_against, 1)));
        tr.appendChild(el("td", s.point_diff >= 0 ? "pos" : "neg", signed(s.point_diff, 1)));
        return tr;
      }
    );
  }

  function renderPower(lg, wk) {
    var rows = wk.power_rankings || [];
    var max = 1;
    rows.forEach(function (p) { max = Math.max(max, Math.abs(p.power_score || 0)); });

    table(
      document.getElementById("power"),
      [{ t: "#" }, { t: "Team", cls: "l" }, { t: "Power score", cls: "l" }, { t: "Score" }, { t: "All-play" }, { t: "Pts/wk" }],
      rows,
      function (p) {
        var tr = el("tr", p.roster_id === lg.my_roster_id ? "mine" : null);
        tr.appendChild(el("td", "rk", p.power_rank));
        tr.appendChild(el("td", "l", p.owner || "—"));

        var cell = el("td", "bar-cell");
        var track = el("div", "track");
        var bar = el("i");
        var v = p.power_score || 0;
        var pct = Math.abs(v) / max * 50;
        if (v >= 0) {
          bar.style.left = "50%";
          bar.style.width = pct + "%";
          bar.style.background = "var(--pos)";
        } else {
          bar.style.right = "50%";
          bar.style.width = pct + "%";
          bar.style.background = "var(--neg)";
        }
        track.appendChild(bar);
        cell.appendChild(track);
        tr.appendChild(cell);

        tr.appendChild(el("td", v >= 0 ? "pos" : "neg", signed(p.power_score, 2)));
        tr.appendChild(el("td", null, num((p.all_play_win_pct || 0) * 100, 0) + "%"));
        tr.appendChild(el("td", null, num(p.mean_points, 1)));
        return tr;
      }
    );
  }

  function injuryPill(p) {
    if (p.on_bye) { return el("span", "pill bye", "Bye " + (p.bye_week || "")); }
    if (!p.injury_status) { return null; }
    var s = String(p.injury_status);
    var cls = /^(Questionable|Probable)$/.test(s) ? "pill q" : "pill out";
    return el("span", cls, s);
  }

  function addPill(parent, pill) {
    if (!pill) { return; }
    parent.appendChild(document.createTextNode(" "));
    parent.appendChild(pill);
  }

  function renderLineup(lg) {
    var host = document.getElementById("lineup");
    var sub = document.getElementById("lineupsub");
    host.innerHTML = "";
    var ln = lg.lineup;
    var starters = (ln && ln.recommended_starters) || [];
    var order = (ln && ln.slot_order) || [];

    if (!ln || (!starters.length && !order.length)) {
      sub.textContent = "";
      host.appendChild(el("div", "empty", "No projection available for this roster."));
      return;
    }

    sub.textContent = "week " + lg.upcoming_week + " · " + num(ln.projected_points, 1) + " projected" +
      (has(ln.locked_points) ? " · " + num(ln.locked_points, 1) + " already in" : "");

    var byId = {};
    starters.forEach(function (p) { byId[p.player_id] = p; });
    if (!order.length) {
      order = starters.map(function (p) { return { slot: p.slot || p.position, player_id: p.player_id }; });
    }

    order.forEach(function (s) {
      var p = s.player_id ? byId[s.player_id] : null;
      if (!p) {
        var gap = el("div", "slot empty-slot");
        gap.appendChild(el("span", "pos-tag", s.slot));
        gap.appendChild(el("div", "nm", "Empty — no available player for this slot"));
        gap.appendChild(el("span", "pp", "—"));
        host.appendChild(gap);
        return;
      }
      var row = el("div", "slot" + (p.currently_starting || p.locked ? "" : " swap"));
      row.appendChild(el("span", "pos-tag", s.slot || p.position));
      var nm = el("div", "nm");
      var b = el("b", null, playerName(p));
      b.title = modelTitle(p);
      nm.appendChild(b);
      if (p.locked) { addPill(nm, el("span", "pill lock", "played")); }
      addPill(nm, p.locked ? null : injuryPill(p));
      addPill(nm, luckPill(p));
      if (p.projection_missing && !p.locked) { addPill(nm, el("span", "pill bye", "no projection")); }
      if (!p.currently_starting && !p.locked) { addPill(nm, el("span", "pill start", "start")); }
      var meta = [(s.slot && s.slot !== p.position ? p.position + " · " : "") + (p.team || "FA")];
      if (isKdef(p)) {
        if (p.week_opponent) { meta.push("vs " + p.week_opponent); }
        meta.push(num(p.projected_ppg, 1) + "/g rest of season");
      } else {
        meta.push(num(p.ppg_to_date, 1) + " ppg so far");
        var usage = usageLine(p);
        if (usage) { meta.push(usage); }
      }
      if (p.locked) { meta.push("game over · locked in"); }
      nm.appendChild(el("span", "meta", meta.join(" · ")));
      row.appendChild(nm);
      row.appendChild(el("span", "pp", num(p.locked ? p.actual_points : weekPoints(p), 1)));
      host.appendChild(row);
    });

    (ln.bench || []).filter(function (p) { return p.currently_starting; }).forEach(function (p) {
      var row = el("div", "slot drop-out");
      row.appendChild(el("span", "pos-tag", p.position));
      var nm = el("div", "nm");
      nm.appendChild(el("b", null, playerName(p)));
      if (p.projection_missing) {
        addPill(nm, el("span", "pill bye", "no projection"));
        nm.appendChild(el("span", "meta", "currently starting · no projection to compare against your bench"));
      } else {
        addPill(nm, el("span", "pill sit", "sit"));
        nm.appendChild(el("span", "meta", "currently starting · projects below your bench"));
      }
      row.appendChild(nm);
      row.appendChild(el("span", "pp", num(weekPoints(p), 1)));
      host.appendChild(row);
    });

    (ln.unavailable || []).forEach(function (p) {
      var row = el("div", "slot drop-out");
      row.appendChild(el("span", "pos-tag", p.position));
      var nm = el("div", "nm");
      nm.appendChild(el("b", null, playerName(p)));
      if (p.locked) { addPill(nm, el("span", "pill lock", "played")); }
      addPill(nm, p.locked ? null : injuryPill(p));
      if (p.in_reserve) { addPill(nm, el("span", "pill ir", "IR slot")); }
      if (p.currently_starting) { addPill(nm, el("span", "pill sit", "in your lineup")); }
      var why = p.locked
        ? "game over · locked on your bench, " + num(p.actual_points, 1) + " not counted"
        : p.on_bye && !p.injury_status
        ? "on bye in week " + lg.upcoming_week
        : "cannot be counted on this week";
      if (p.in_reserve) { why += " · holds no bench spot"; }
      nm.appendChild(el("span", "meta", why));
      row.appendChild(nm);
      row.appendChild(el("span", "pp", num(p.locked ? p.actual_points : p.projected_ppg, 1)));
      host.appendChild(row);
    });
  }

  function renderMoves(lg) {
    var host = document.getElementById("moves");
    var sub = document.getElementById("movessub");
    host.innerHTML = "";
    var ln = lg.lineup || {};
    var hz = ln.horizon;
    sub.textContent = hz
      ? "weeks " + hz.from_week + (hz.through_week > hz.from_week ? "–" + hz.through_week : "") + " · per-week average"
      : "";

    var moves = (ln.add_drop || []).filter(function (m) {
      return (m.net_lineup_gain || 0) > 0.01;
    }).slice(0, 8);

    if (!moves.length) {
      host.appendChild(el("div", "empty", "No free agent improves this lineup over the rest of the regular season. Stand pat."));
      return;
    }

    moves.forEach(function (m, i) {
      var row = el("div", "move");
      row.appendChild(el("span", "n", i + 1));
      var txt = el("div", "txt");
      txt.appendChild(el("strong", null, playerName(m)));
      txt.appendChild(document.createTextNode(" (" + m.position + (m.team ? " · " + m.team : "") + ")"));
      addPill(txt, injuryPill(m));
      if (m.best_drop_name) {
        txt.appendChild(el("em", null, " — drop " + m.best_drop_name));
      } else if ((ln.open_roster_spots || 0) > 0) {
        txt.appendChild(el("em", null, " — into an open roster spot"));
      }
      if (m.starts_immediately) { addPill(txt, el("span", "pill start", "starts")); }
      if (has(m.weeks_evaluated) && m.weeks_evaluated > 1) {
        var bits = [signed(m.net_gain_this_week, 1) + " this week",
                    signed(m.net_lineup_gain_total, 1) + " over " + m.weeks_evaluated + " wks"];
        if (m.bye_week) { bits.push("bye " + m.bye_week); }
        txt.appendChild(el("span", "detail", bits.join(" · ")));
      }
      row.appendChild(txt);
      var gain = el("span", "gain", "+" + num(m.net_lineup_gain, 1));
      if (has(m.weeks_evaluated) && m.weeks_evaluated > 1) { gain.appendChild(el("small", null, "per wk")); }
      row.appendChild(gain);
      host.appendChild(row);
    });
  }

  function renderPositionChips(lg, rows) {
    var host = document.getElementById("wpos");
    host.innerHTML = "";
    var order = ["QB", "RB", "WR", "TE", "K", "DEF"];
    var present = {};
    rows.forEach(function (r) { present[r.position] = true; });
    var positions = order.filter(function (p) { return present[p]; });
    Object.keys(present).forEach(function (p) { if (order.indexOf(p) < 0) { positions.push(p); } });
    if (posFilter !== "ALL" && !present[posFilter]) { posFilter = "ALL"; }
    if (positions.length < 2) { return; }

    ["ALL"].concat(positions).forEach(function (p) {
      var b = el("button", null, p === "ALL" ? "All" : p);
      b.type = "button";
      b.setAttribute("aria-pressed", p === posFilter ? "true" : "false");
      b.addEventListener("click", function () {
        posFilter = p;
        renderWaivers(lg);
      });
      host.appendChild(b);
    });
  }

  function renderWaivers(lg) {
    var all = (lg.free_agents || {}).rows || [];
    renderPositionChips(lg, all);
    var rows = posFilter === "ALL" ? all : all.filter(function (r) { return r.position === posFilter; });
    var usage = hasUsage(all);

    var cols = [
      { t: "#" }, { t: "Player", cls: "l" }, { t: "Pos" }, { t: "NFL" },
      { t: "Proj/g" }, { t: "ROS value" }, { t: "Opp" }
    ];
    if (usage) {
      cols = cols.concat([{ t: "Snap" }, { t: "Tgt%" }, { t: "xFP/g" }, { t: "vs exp" }]);
    } else {
      cols.push({ t: "Tgt/g" });
    }
    cols = cols.concat([{ t: "Bye" }, { t: "Confidence" }]);

    table(document.getElementById("waivers"), cols, rows, function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", "rk", r.board_rank));
      var nm = el("td", "l");
      nm.appendChild(document.createTextNode(playerName(r)));
      if (r.week_locked) {
        var lk = el("span", "pill lock", "played");
        lk.title = "His week " + lg.upcoming_week + " game has kicked off: Sleeper locks him until waivers run.";
        addPill(nm, lk);
      }
      addPill(nm, injuryPill(r));
      addPill(nm, luckPill(r));
      tr.appendChild(nm);
      tr.appendChild(el("td", null, r.position));
      tr.appendChild(el("td", null, r.team || "—"));
      var proj = el("td", null, num(r.projected_ppg, 1));
      proj.title = modelTitle(r);
      tr.appendChild(proj);
      tr.appendChild(el("td", (r.points_above_replacement || 0) >= 0 ? "pos" : "neg", signed(r.points_above_replacement, 1)));
      tr.appendChild(el("td", null, r.week_opponent ? (r.week_is_home ? "vs " : "@ ") + r.week_opponent : (has(r.bye_week) ? "bye" : "—")));
      if (usage) {
        tr.appendChild(el("td", null, has(r.snap_share) ? pct(r.snap_share) + snapTrend(r) : "—"));
        tr.appendChild(el("td", null, /^(RB|WR|TE)$/.test(r.position) ? pct(r.target_share) : "—"));
        tr.appendChild(el("td", null, num(r.xfp_per_game, 1)));
        var poe = r.points_over_expected_per_game;
        tr.appendChild(el("td", has(poe) ? (poe >= 0 ? "pos" : "neg") : null, signed(poe, 1)));
      } else {
        tr.appendChild(el("td", null, has(r.targets_per_game) ? num(r.targets_per_game, 1) : "—"));
      }
      tr.appendChild(el("td", null, r.bye_week || "—"));
      tr.appendChild(el("td", null, r.confidence_tier || "—"));
      return tr;
    });

    if (!rows.length) {
      var t = document.getElementById("waivers");
      var tb = t.querySelector("tbody");
      var tr = el("tr");
      var td = el("td", "l", "No free agents to show.");
      td.colSpan = cols.length;
      tr.appendChild(td);
      tb.appendChild(tr);
    }
  }

  function renderNotes(lg) {
    var host = document.getElementById("notes");
    host.innerHTML = "";
    var fa = lg.free_agents || {};
    var ln = lg.lineup || {};

    var hz = ln.horizon;
    var excluded = ln.excluded_positions || [];
    var availability = "Out and Doubtful players miss this week only; IR, PUP, NA and suspended players are assumed out four weeks — the NFL minimum, so a lower bound. Byes come from the NFL schedule. Nobody unavailable is started, and Questionable players start but are flagged.";
    if (hz) {
      availability += " Moves are scored over weeks " + hz.from_week + "–" + hz.through_week + " with each player's week-by-week availability, so nobody is offered as a drop just for being hurt or on bye this week. IR-slot players are never the drop, and a kicker or defense move is a swap for the one you have. A slot nobody on your roster can fill that week is scored at the position's replacement level — what you could stream — so a backup counts only for his margin over a streamer.";
    }
    if (excluded.length) {
      availability += " No projection exists yet for " + excluded.join(", ") + ", so those slots are left out of the lineup and the moves rather than scored at zero.";
    }
    var locks = ln.locked_teams || [];
    if (locks.length) {
      availability += " " + locks.join(", ") + " have already played in week " + lg.upcoming_week + ", and Sleeper locks their players. A locked starter keeps his slot and his actual points; a locked bench player cannot come in; and their free agents (marked played on the board) cannot be added until waivers run, so they are left out of the moves. A kicker or defense swap waits while yours is locked.";
    }

    var blended = (fa.rows || []).some(function (r) { return r.projection_model === "blend"; });
    var projection = blended
      ? "Rest-of-season points per game for QB, RB, WR and TE blend two models: a usage model (snaps, targets, carries and pass attempts, turned into points with this league's scoring) and the player's own scoring history, shrunk toward a fitted per-position prior. The blend beat history alone at every position in a backtest over seven seasons."
      : "Rest-of-season points per game, shrunk toward a fitted per-position prior.";

    var notes = [
      ["How the board is built",
       projection + " Each player is then measured against the last startable player at his position across the whole league — not just the wire. Ranked on rest-of-season points above replacement, through week " + fa.cutoff_week + "."],
      ["Power score",
       "Equal-weighted z-scores of win percentage, all-play win percentage and mean points, over regular-season games only, recomputed from scratch for each week you select."],
      ["Who can play", availability],
      ["Who is on the board",
       "Free agents with no NFL team never enter the pool. A player with no games this season and fewer than four prior-season games stays on, projected at what players in that spot have historically gone on to score — roughly half the positional average — so he ranks well below the wire's real options."]
    ];
    var kdefShown = (fa.rows || []).some(isKdef) ||
      (ln.recommended_starters || []).some(isKdef);
    if (kdefShown) {
      notes.push(["Kickers and defenses",
        "Projected by their own model, fitted on ten seasons of this league's scoring: each player's season is shrunk hard toward the positional average, because this early there is little to separate one kicker from another. The lineup uses this week's number, nudged by the betting market's implied points; the board and the moves use the rest-of-season rate, against the league's last starting kicker or defense."]);
    }
    if (hasUsage(fa.rows || [])) {
      notes.push(["Reading the usage columns",
        "Snap: share of offensive snaps this season; the arrow compares the last two games (±5 points). Tgt%: share of team targets. xFP/g: points the player's usage would score for an average player. vs exp: actual minus expected per game — a large plus (flagged TD-luck at +" + LUCK_THRESHOLD.toFixed(1) + ") is production the usage does not support, usually touchdowns. Hover a projection for the model behind it."]);
    }

    notes.forEach(function (n) {
      var d = el("div", "note");
      d.appendChild(el("h4", null, n[0]));
      d.appendChild(el("p", null, n[1]));
      host.appendChild(d);
    });
  }

  function render() {
    var lg = leagues[li];
    if (!lg) { return; }
    if (wi > lg.weeks.length - 1) { wi = lg.weeks.length - 1; }
    if (wi < 0) { wi = 0; }
    var wk = lg.weeks[wi] || { standings: [], power_rankings: [], results: [] };

    Array.prototype.forEach.call(segEl.children, function (b, i) {
      b.setAttribute("aria-pressed", i === li ? "true" : "false");
    });

    document.getElementById("weeklabel").textContent = "Week " + wk.week;
    document.getElementById("prev").disabled = wi <= 0;
    document.getElementById("next").disabled = wi >= lg.weeks.length - 1;
    document.getElementById("histhead").textContent = "Week " + wk.week;
    document.getElementById("dechead").textContent = "Week " + lg.upcoming_week;

    renderMe(lg, wk);
    renderMatchups(lg, wk);
    renderRecap(wk);
    renderStandings(lg, wk);
    renderPower(lg, wk);
    renderLineup(lg);
    renderMoves(lg);
    renderWaivers(lg);
    renderNotes(lg);
  }

  var stamp = new Date(DATA.generated_at);
  document.getElementById("asof").textContent =
    "Data as of " + stamp.toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
    });

  wi = (leagues[li] && leagues[li].weeks.length - 1) || 0;
  render();
})();
</script>
