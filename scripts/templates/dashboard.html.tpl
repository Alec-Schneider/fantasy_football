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
    --wp-me: #1f3a5f;
    --wp-opp: #b3beca;
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
      --wp-me: #85adda;
      --wp-opp: #4a5967;
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
    --wp-me: #85adda;
    --wp-opp: #4a5967;
    --shadow: 0 1px 2px rgba(0, 0, 0, .5), 0 8px 24px -16px rgba(0, 0, 0, .8);
  }

  * { box-sizing: border-box; }

  [hidden] { display: none !important; }

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

  .seg button[aria-pressed="true"],
  .seg button[aria-selected="true"] {
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

  /* ---------- matchup tab ---------- */

  .mx > .phase:first-child { margin-top: 26px; }

  .sb {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 10px;
  }

  .tcard {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .tcard.mine {
    border-left: 4px solid var(--accent);
    box-shadow: var(--shadow);
  }

  .tcard .who {
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
    overflow-wrap: anywhere;
  }

  .tcard .tname {
    font-weight: 800;
    font-size: clamp(15px, 2.8vw, 21px);
    letter-spacing: -.02em;
    line-height: 1.2;
    overflow-wrap: anywhere;
  }

  .tcard .rec {
    font-family: var(--mono);
    font-size: 11.5px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }

  .tcard .score {
    font-family: var(--mono);
    font-weight: 600;
    font-size: clamp(28px, 6vw, 42px);
    line-height: 1.1;
    margin-top: 6px;
    font-variant-numeric: tabular-nums;
  }

  .tcard .sub2 {
    font-family: var(--mono);
    font-size: 11.5px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }

  .tcard .sub2 b { color: var(--ink-2); font-weight: 600; }

  .wp { margin-top: 10px; padding: 14px 16px; }

  .wp .status {
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 10px;
  }

  .wp .lbls {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    margin-bottom: 5px;
  }

  .wp .split {
    display: flex;
    height: 12px;
    border-radius: 6px;
    overflow: hidden;
    background: var(--wp-opp);
  }

  .wp .split i { display: block; background: var(--wp-me); }

  .wp .margin {
    margin-top: 8px;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }

  .wp .margin b { color: var(--ink); font-weight: 600; }

  .h2h { overflow: hidden; }

  .h2h-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 64px minmax(0, 1fr);
    align-items: center;
    gap: 10px;
    padding: 9px 14px;
    border-bottom: 1px solid var(--line);
  }

  .h2h-row:last-child { border-bottom: 0; }
  .h2h-row.edge-me { background: var(--pos-soft); }
  .h2h-row.edge-opp { background: var(--neg-soft); }

  .h2h-head {
    background: var(--surface-2);
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .09em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .h2h-head span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .h2h-head .mid { text-align: center; }

  .h2h-row .mid {
    text-align: center;
    font-family: var(--mono);
    font-variant-numeric: tabular-nums;
  }

  .h2h-row .mid .sl { font-size: 11px; font-weight: 600; letter-spacing: .06em; color: var(--ink-2); }
  .h2h-row .mid .ed { display: block; font-size: 10px; color: var(--muted); }

  .hs { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .hs .nm { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .hs .nm b { font-weight: 600; font-size: 14px; }
  .hs .nm .meta { display: block; font-size: 11px; color: var(--muted); font-family: var(--mono); }
  .hs.gap .nm { color: var(--muted); font-style: italic; }

  .hs .nums {
    font-family: var(--mono);
    font-variant-numeric: tabular-nums;
    text-align: right;
    min-width: 46px;
  }

  .hs.opp { flex-direction: row-reverse; }
  .hs.opp .nums { text-align: left; }
  .hs.mine .nm { text-align: right; }
  .hs .nums .p { display: block; font-size: 13.5px; font-weight: 600; }
  .hs .nums .a { display: block; font-size: 11px; color: var(--muted); }

  .pill.live { background: var(--pos-soft); color: var(--pos); }

  .edges { padding: 6px 14px; }

  .edge-row {
    display: grid;
    grid-template-columns: 52px minmax(0, 1fr) 54px 92px;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
    font-family: var(--mono);
    font-variant-numeric: tabular-nums;
  }

  .edge-row .g { font-size: 11px; font-weight: 600; letter-spacing: .06em; color: var(--ink-2); }
  .edge-row .track { height: 16px; }
  .edge-row .v { font-size: 12.5px; font-weight: 600; text-align: right; }
  .edge-row .vals { font-size: 11px; color: var(--muted); text-align: right; white-space: nowrap; }

  .alerts { overflow: hidden; }

  .alert {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--line);
    font-size: 13.5px;
  }

  .alert:last-child { border-bottom: 0; }

  .alert .who {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: .09em;
    text-transform: uppercase;
    color: var(--muted);
    width: 54px;
    flex: none;
  }

  .alert .txt { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .alert .txt .sub { margin-left: 4px; }

  .alert button {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .05em;
    color: var(--accent);
    background: none;
    border: 1px solid var(--accent);
    border-radius: 999px;
    padding: 3px 11px;
    cursor: pointer;
  }

  .alert.ok { color: var(--muted); }

  .stats td.best { font-weight: 700; color: var(--pos); }
  .stats td.l { min-width: 0; white-space: nowrap; }
  .stats td { color: var(--ink-2); }
  .stats th.l { text-align: left; }

  .cmp-gap { margin-top: 12px; }

  .meetings {
    margin-top: 12px;
    padding: 12px 14px;
    font-size: 13.5px;
  }

  .meetings .gm {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    padding-top: 6px;
    font-family: var(--mono);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    color: var(--muted);
  }

  details.benches { margin-bottom: 26px; }

  details.benches summary {
    cursor: pointer;
    padding: 12px 14px;
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--muted);
  }

  details.benches summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .halves {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    border-top: 1px solid var(--line);
  }

  .halves > div + div { border-left: 1px solid var(--line); }

  .halves h4 {
    margin: 0;
    padding: 10px 14px 4px;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .halves .slot { flex-wrap: wrap; }
  .halves .slot .nm { overflow-wrap: anywhere; }

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

  @media (max-width: 560px) {
    .wrap, .bar-inner { padding-inline: 16px; }
    .tcard { padding: 12px 12px; }
    .h2h-row { grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr); gap: 6px; padding: 8px 8px; }
    .hs, .hs.opp { flex-direction: column; align-items: flex-start; gap: 2px; }
    .hs .nm b { font-size: 13px; }
    .hs .nm .meta { font-size: 10.5px; }
    .hs .nums, .hs.opp .nums { text-align: left; display: flex; gap: 6px; align-items: baseline; }
    .hs.mine { align-items: flex-end; }
    .h2h-row .mid .sl { font-size: 10px; letter-spacing: 0; }
    .edge-row { grid-template-columns: 44px minmax(0, 1fr) 48px; }
    .edge-row .vals { display: none; }
    .alert .who { width: 100%; }
    .halves { grid-template-columns: 1fr; }
    .halves > div + div { border-left: 0; border-top: 1px solid var(--line); }
    .stats td, .stats th { padding-inline: 6px; }
  }
</style>

<div class="bar">
  <div class="bar-inner">
    <div class="brand">
      <b>The Schneid Desk</b>
      <span id="asof">—</span>
    </div>
    <div class="seg" id="tabs" role="tablist" aria-label="View">
      <button type="button" role="tab" id="tab-matchup" aria-controls="panel-matchup" aria-selected="true">Matchup</button>
      <button type="button" role="tab" id="tab-season" aria-controls="panel-season" aria-selected="false" tabindex="-1">Season</button>
    </div>
    <div class="seg" id="leagues" role="group" aria-label="League"></div>
    <div class="stepper" id="stepper" hidden>
      <button id="prev" type="button" aria-label="Previous week">&#8249;</button>
      <span class="label" id="weeklabel">Week —</span>
      <button id="next" type="button" aria-label="Next week">&#8250;</button>
    </div>
  </div>
</div>

<div class="wrap">
<div id="panel-matchup" class="mx" role="tabpanel" aria-labelledby="tab-matchup"></div>

<div id="panel-season" role="tabpanel" aria-labelledby="tab-season" hidden>
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

  // ---- matchup tab -------------------------------------------------

  var SLOT_NAMES = { SUPER_FLEX: "SFLX", WRRB_FLEX: "W/R", REC_FLEX: "W/T", FLEX: "FLEX" };

  function slotName(s) {
    if (!s) { return "—"; }
    return SLOT_NAMES[s] || String(s);
  }

  function teamLabel(lg, side) {
    var t = (lg.teams || []).filter(function (x) { return x.roster_id === side.roster_id; })[0];
    if (t) { return label(t); }
    return side.team_name || side.owner || ("Roster " + side.roster_id);
  }

  function recordText(ts) {
    return Math.round(ts.wins || 0) + "–" + Math.round(ts.losses || 0) + (ts.ties ? "–" + Math.round(ts.ties) : "");
  }

  function mxSection(title, sub) {
    var s = el("section");
    var h = el("h3", null, title);
    if (sub) { h.appendChild(el("span", "sub", " " + sub)); }
    s.appendChild(h);
    return s;
  }

  function mxEmpty(host, headline, reason) {
    host.appendChild(el("div", "empty", headline));
    var r = el("div", "empty", reason);
    r.style.paddingTop = "0";
    host.appendChild(r);
  }

  function statusLine(mu) {
    var g = mu.nfl_games || {};
    var bits = [mu.phase === "live" ? "Live" : "Pre-game"];
    if (mu.phase === "live" && has(g.final) && has(g.total)) {
      bits.push(g.final + " of " + g.total + " NFL games final");
    } else if (has(g.total)) {
      bits.push(g.total + " NFL games this week");
    }
    return bits.join(" · ");
  }

  function teamCard(lg, side, ts, mine) {
    var c = el("div", "tcard" + (mine ? " mine" : ""));
    c.appendChild(el("div", "who", side.owner || "—"));
    c.appendChild(el("div", "tname", teamLabel(lg, side)));
    c.appendChild(el("div", "rec", ts ? recordText(ts) + (has(ts.rank) ? " · #" + ts.rank + " of " + lg.total_rosters : "") : "No record yet"));
    c.appendChild(el("div", "score", num(side.points, 1)));
    var proj = el("div", "sub2");
    proj.appendChild(document.createTextNode("proj "));
    proj.appendChild(el("b", null, num(side.projected_total, 1)));
    c.appendChild(proj);
    var rem = side.players_remaining;
    c.appendChild(el("div", "sub2", has(rem) ? rem + " to play" : "—"));
    return c;
  }

  function renderScoreboard(host, lg, mu) {
    var sec = mxSection("Scoreboard");
    var cmp = mu.comparison;
    var grid = el("div", "sb");
    grid.appendChild(teamCard(lg, mu.me, cmp && cmp.me, true));
    grid.appendChild(teamCard(lg, mu.opponent, cmp && cmp.opponent, false));
    sec.appendChild(grid);

    var wp = el("div", "panel wp");
    wp.appendChild(el("div", "status", statusLine(mu)));
    var prob = mu.win_probability;
    var margin = prob && has(prob.projected_margin)
      ? prob.projected_margin
      : (has(mu.me.projected_total) && has(mu.opponent.projected_total) ? mu.me.projected_total - mu.opponent.projected_total : null);

    if (prob && has(prob.me) && has(prob.opponent)) {
      var mePct = Math.max(0, Math.min(100, Number(prob.me) * 100));
      var lb = el("div", "lbls");
      lb.appendChild(el("span", null, "You " + Math.round(mePct) + "%"));
      lb.appendChild(el("span", null, Math.round(Number(prob.opponent) * 100) + "% Opp"));
      wp.appendChild(lb);
      var split = el("div", "split");
      split.setAttribute("role", "img");
      split.setAttribute("aria-label", "Win probability " + Math.round(mePct) + " percent you, " + Math.round(100 - mePct) + " percent opponent");
      var seg = el("i");
      seg.style.width = mePct + "%";
      split.appendChild(seg);
      wp.appendChild(split);
    }
    var mg = el("div", "margin");
    mg.appendChild(document.createTextNode("Projected margin "));
    mg.appendChild(el("b", null, signed(margin, 1)));
    if (prob && has(prob.margin_sd)) { mg.appendChild(document.createTextNode(" ± " + num(prob.margin_sd, 1))); }
    if (!prob) { mg.appendChild(document.createTextNode(" · no win probability yet")); }
    wp.appendChild(mg);
    sec.appendChild(wp);
    host.appendChild(sec);
  }

  function gameChip(r) {
    var st = r.game_state;
    if (st === "in_progress") { return el("span", "pill live", "Live"); }
    if (st === "final") { return el("span", "pill lock", "Final"); }
    if (st === "bye") { return el("span", "pill bye", "Bye"); }
    if (st === "scheduled") {
      var txt = "Scheduled";
      if (r.kickoff) {
        var d = new Date(r.kickoff);
        if (!isNaN(d.getTime())) {
          txt = d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
        }
      }
      return el("span", "pill lock", txt);
    }
    return null;
  }

  function slotSide(r, cls) {
    var side = el("div", "hs " + cls);
    var nm = el("div", "nm");
    if (!r || !r.player_id) {
      side.className += " gap";
      nm.appendChild(document.createTextNode("Empty"));
      side.appendChild(nm);
      return side;
    }
    nm.appendChild(el("b", null, playerName(r)));
    addPill(nm, injuryPill(r));
    var meta = [(r.position || "—") + " · " + (r.team || "FA")];
    if (r.nfl_opponent) { meta.push((r.is_home ? "vs " : "@") + r.nfl_opponent); }
    var metaEl = el("span", "meta", meta.join(" · "));
    addPill(metaEl, gameChip(r));
    nm.appendChild(metaEl);

    var nums = el("div", "nums");
    var p = el("span", "p", num(r.projection, 1));
    p.title = "Projection";
    nums.appendChild(p);
    if (has(r.actual_points)) {
      var a = el("span", "a", num(r.actual_points, 1) + " pts");
      a.title = "Actual points so far";
      nums.appendChild(a);
    }
    side.appendChild(nums);
    side.appendChild(nm);
    return side;
  }

  function renderHeadToHead(host, lg, mu) {
    var sec = mxSection("Lineups, head to head", "projection · actual");
    var panel = el("div", "panel h2h");
    var head = el("div", "h2h-row h2h-head");
    head.appendChild(el("span", null, teamLabel(lg, mu.me)));
    head.appendChild(el("span", "mid", "Slot"));
    head.appendChild(el("span", null, teamLabel(lg, mu.opponent)));
    panel.appendChild(head);

    var mine = mu.me.starters || [];
    var theirs = mu.opponent.starters || [];
    var n = Math.max(mine.length, theirs.length);
    if (!n) { panel.appendChild(el("div", "empty", "No starting slots to compare.")); }
    for (var i = 0; i < n; i++) {
      var a = mine[i] || null;
      var b = theirs[i] || null;
      var edge = a && b && has(a.expected_points) && has(b.expected_points) ? a.expected_points - b.expected_points : null;
      var cls = "h2h-row";
      if (edge !== null && edge >= 1) { cls += " edge-me"; }
      else if (edge !== null && edge <= -1) { cls += " edge-opp"; }
      var row = el("div", cls);
      row.appendChild(slotSide(a, "mine"));
      var mid = el("div", "mid");
      mid.appendChild(el("span", "sl", slotName((a && a.slot) || (b && b.slot))));
      mid.appendChild(el("span", "ed", edge === null ? "" : signed(edge, 1)));
      row.appendChild(mid);
      row.appendChild(slotSide(b, "opp"));
      panel.appendChild(row);
    }
    sec.appendChild(panel);
    host.appendChild(sec);
  }

  function renderPositionalEdge(host, lg, mu) {
    var sec = mxSection("Positional edge", "projected points, you minus opponent");
    var rows = mu.position_edges || [];
    var panel = el("div", "panel edges");
    if (!rows.length) {
      panel.appendChild(el("div", "empty", "No positional comparison available."));
    }
    var max = 1;
    rows.forEach(function (r) { if (has(r.edge)) { max = Math.max(max, Math.abs(r.edge)); } });
    rows.forEach(function (r) {
      var row = el("div", "edge-row");
      row.appendChild(el("span", "g", r.group));
      var track = el("div", "track");
      var bar = el("i");
      var v = has(r.edge) ? Number(r.edge) : 0;
      bar.style.width = (Math.abs(v) / max * 50) + "%";
      if (v >= 0) { bar.style.left = "50%"; bar.style.background = "var(--pos)"; }
      else { bar.style.right = "50%"; bar.style.background = "var(--neg)"; }
      track.appendChild(bar);
      row.appendChild(track);
      row.appendChild(el("span", "v " + (v > 0 ? "pos" : v < 0 ? "neg" : ""), signed(r.edge, 1)));
      row.appendChild(el("span", "vals", num(r.me, 1) + " vs " + num(r.opponent, 1)));
      panel.appendChild(row);
    });
    sec.appendChild(panel);
    host.appendChild(sec);
  }

  function alertSeverity(reason) {
    return /^(Questionable|Probable|Doubtful)$/.test(String(reason)) ? "pill q" : "pill out";
  }

  function alertRow(who, nodes) {
    var row = el("div", "alert");
    row.appendChild(el("span", "who", who));
    var txt = el("div", "txt");
    nodes.forEach(function (n) { txt.appendChild(typeof n === "string" ? document.createTextNode(n) : n); });
    row.appendChild(txt);
    return row;
  }

  function renderAlerts(host, lg, mu) {
    var sec = mxSection("Alerts");
    var panel = el("div", "panel alerts");
    var count = 0;

    function addAlerts(who, list) {
      (list || []).forEach(function (a) {
        var nodes = [el("strong", null, a.full_name || (a.reason === "Empty slot" ? "Empty slot" : playerName(a)))];
        if (a.slot) { nodes.push(el("span", "sub", " " + slotName(a.slot))); }
        nodes.push(" ");
        nodes.push(el("span", alertSeverity(a.reason), a.reason || "Issue"));
        panel.appendChild(alertRow(who, nodes));
        count++;
      });
    }
    addAlerts("You", mu.me.alerts);

    if (has(mu.my_recommended_gain) && mu.my_recommended_gain > 0.05) {
      var row = alertRow("You", ["Recommended lineup projects ", el("strong", "pos", "+" + num(mu.my_recommended_gain, 1))]);
      var btn = el("button", null, "See lineup call");
      btn.type = "button";
      btn.addEventListener("click", function () {
        setTab("season", true);
        var t = document.getElementById("lineup");
        if (t && t.scrollIntoView) { t.scrollIntoView({ block: "start" }); }
      });
      row.appendChild(btn);
      panel.appendChild(row);
      count++;
    }

    addAlerts("Opp", mu.opponent.alerts);

    var opp = mu.opponent;
    if (has(opp.optimal_total) && has(opp.projected_total) && opp.optimal_total - opp.projected_total > 0.05) {
      panel.appendChild(alertRow("Opp", ["Leaving ", el("strong", "neg", num(opp.optimal_total - opp.projected_total, 1)),
        " on the bench (best lineup " + num(opp.optimal_total, 1) + " vs " + num(opp.projected_total, 1) + " set)"]));
      count++;
    }

    if (!count) {
      var ok = el("div", "alert ok", "No lineup issues");
      panel.appendChild(ok);
    }
    sec.appendChild(panel);
    host.appendChild(sec);
  }

  // [label, getter, how to compare: "hi" / "lo" / null]
  function winPct(ts) {
    var g = (ts.wins || 0) + (ts.losses || 0) + (ts.ties || 0);
    return g ? ((ts.wins || 0) + 0.5 * (ts.ties || 0)) / g : null;
  }

  function allPlayPct(ts) {
    var g = (ts.all_play_wins || 0) + (ts.all_play_losses || 0) + (ts.all_play_ties || 0);
    return g ? ((ts.all_play_wins || 0) + 0.5 * (ts.all_play_ties || 0)) / g : null;
  }

  var STAT_ROWS = [
    ["Record", function (t) { return recordText(t); }, winPct, "hi"],
    ["Rank", function (t) { return has(t.rank) ? "#" + t.rank : "—"; }, function (t) { return t.rank; }, "lo"],
    ["Points for", function (t) { return num(t.points_for, 1); }, function (t) { return t.points_for; }, "hi"],
    ["Points against", function (t) { return num(t.points_against, 1); }, function (t) { return t.points_against; }, "lo"],
    ["PPG", function (t) { return num(t.ppg, 1); }, function (t) { return t.ppg; }, "hi"],
    ["Last 3 PPG", function (t) { return num(t.last3_ppg, 1); }, function (t) { return t.last3_ppg; }, "hi"],
    ["High", function (t) { return num(t.high, 1); }, function (t) { return t.high; }, "hi"],
    ["Low", function (t) { return num(t.low, 1); }, function (t) { return t.low; }, "hi"],
    ["Weekly SD", function (t) { return num(t.stdev_points, 1); }, null, null],
    ["All-play", function (t) {
      return Math.round(t.all_play_wins || 0) + "–" + Math.round(t.all_play_losses || 0) + (t.all_play_ties ? "–" + Math.round(t.all_play_ties) : "");
    }, allPlayPct, "hi"],
    ["Power rank", function (t) { return has(t.power_rank) ? "#" + t.power_rank : "—"; }, function (t) { return t.power_rank; }, "lo"]
  ];

  // Returns "me", "opp" or null: who holds the better value.
  function betterSide(a, b, how) {
    if (!how || !has(a) || !has(b) || Number(a) === Number(b)) { return null; }
    var meBetter = how === "hi" ? Number(a) > Number(b) : Number(a) < Number(b);
    return meBetter ? "me" : "opp";
  }

  function renderComparison(host, lg, mu) {
    var cmp = mu.comparison;
    var sec = mxSection("Season comparison", cmp && has(cmp.through_week) ? "through week " + cmp.through_week : "");
    if (!cmp || !cmp.me || !cmp.opponent) {
      var p0 = el("div", "panel");
      p0.appendChild(el("div", "empty", "No completed weeks yet"));
      sec.appendChild(p0);
      host.appendChild(sec);
      return;
    }

    var wrap = el("div", "panel scroll stats");
    var t = el("table");
    table(t, [{ t: "Stat", cls: "l" }, { t: teamLabel(lg, mu.me) }, { t: teamLabel(lg, mu.opponent) }], STAT_ROWS, function (d) {
      var tr = el("tr");
      tr.appendChild(el("td", "l", d[0]));
      var best = d[2] ? betterSide(d[2](cmp.me), d[2](cmp.opponent), d[3]) : null;
      tr.appendChild(el("td", best === "me" ? "best" : null, d[1](cmp.me)));
      tr.appendChild(el("td", best === "opp" ? "best" : null, d[1](cmp.opponent)));
      return tr;
    });
    wrap.appendChild(t);
    sec.appendChild(wrap);

    var positions = cmp.positions || [];
    if (positions.length) {
      var wrap2 = el("div", "panel scroll stats cmp-gap");
      var t2 = el("table");
      table(t2, [{ t: "Pos", cls: "l" }, { t: "You PPG" }, { t: "Rank" }, { t: "Opp PPG" }, { t: "Rank" }], positions, function (r) {
        var tr = el("tr");
        var best = betterSide(r.me_ppg, r.opponent_ppg, "hi");
        tr.appendChild(el("td", "l", r.position));
        tr.appendChild(el("td", best === "me" ? "best" : null, num(r.me_ppg, 1)));
        tr.appendChild(el("td", "rk", has(r.me_rank) ? "#" + r.me_rank : "—"));
        tr.appendChild(el("td", best === "opp" ? "best" : null, num(r.opponent_ppg, 1)));
        tr.appendChild(el("td", "rk", has(r.opponent_rank) ? "#" + r.opponent_rank : "—"));
        return tr;
      });
      wrap2.appendChild(t2);
      sec.appendChild(wrap2);
    }

    var h2h = cmp.head_to_head;
    var meet = el("div", "panel meetings");
    if (h2h && h2h.meetings > 0) {
      meet.appendChild(el("div", null, "This season: " + (h2h.wins || 0) + "–" + (h2h.losses || 0) + (h2h.ties ? "–" + h2h.ties : "") +
        " in " + h2h.meetings + (h2h.meetings === 1 ? " meeting" : " meetings")));
      (h2h.games || []).forEach(function (g) {
        var line = el("div", "gm");
        line.appendChild(el("span", null, "Week " + g.week));
        line.appendChild(el("span", null, num(g.points, 1) + "–" + num(g.opponent_points, 1)));
        meet.appendChild(line);
      });
    } else {
      meet.appendChild(el("div", null, "No meetings yet this season."));
    }
    sec.appendChild(meet);
    host.appendChild(sec);
  }

  function benchColumn(title, rows) {
    var col = el("div");
    col.appendChild(el("h4", null, title));
    if (!rows.length) { col.appendChild(el("div", "empty", "Empty bench")); }
    rows.forEach(function (r) {
      var row = el("div", "slot");
      row.appendChild(el("span", "pos-tag", slotName(r.slot)));
      var nm = el("div", "nm");
      nm.appendChild(el("b", null, playerName(r)));
      addPill(nm, injuryPill(r));
      addPill(nm, gameChip(r));
      var meta = [(r.position || "—") + " · " + (r.team || "FA")];
      if (r.nfl_opponent) { meta.push((r.is_home ? "vs " : "@") + r.nfl_opponent); }
      nm.appendChild(el("span", "meta", meta.join(" · ")));
      row.appendChild(nm);
      row.appendChild(el("span", "pp", num(r.projection, 1)));
      col.appendChild(row);
    });
    return col;
  }

  function renderBenches(host, lg, mu) {
    var mine = mu.me.bench || [];
    var theirs = mu.opponent.bench || [];
    var d = el("details", "panel benches");
    d.appendChild(el("summary", null, "Benches · " + mine.length + " and " + theirs.length));
    var halves = el("div", "halves");
    halves.appendChild(benchColumn(teamLabel(lg, mu.me), mine));
    halves.appendChild(benchColumn(teamLabel(lg, mu.opponent), theirs));
    d.appendChild(halves);
    host.appendChild(d);
  }

  function renderMatchup(lg) {
    var host = document.getElementById("panel-matchup");
    host.innerHTML = "";
    var mu = lg.matchup;
    var wkNo = has(lg.upcoming_week) ? lg.upcoming_week : "—";

    if (!mu || !mu.me || !mu.opponent) {
      var ph = el("div", "phase");
      ph.appendChild(el("h2", null, "Week " + wkNo));
      ph.appendChild(el("span", "tag", "this week's matchup"));
      host.appendChild(ph);
      var box = el("div", "panel");
      var reason = !("matchup" in lg)
        ? "This bundle was built without matchup data. Rebuild the dashboard to add it."
        : lg.upcoming_matchup
        ? "The matchup data for this week is unavailable."
        : "No opponent was found for your roster: a bye week, or the schedule is not posted yet.";
      mxEmpty(box, "No matchup this week", reason);
      host.appendChild(box);
      return;
    }

    var ph2 = el("div", "phase");
    ph2.appendChild(el("h2", null, "Week " + (has(mu.week) ? mu.week : wkNo)));
    ph2.appendChild(el("span", "tag", "you vs " + (mu.opponent.owner || "opponent")));
    host.appendChild(ph2);

    // Sections fail independently: a malformed one is replaced by a notice.
    [renderScoreboard, renderHeadToHead, renderPositionalEdge, renderAlerts, renderComparison, renderBenches]
      .forEach(function (fn) {
        var tmp = el("div");
        try {
          fn(tmp, lg, mu);
        } catch (e) {
          var bad = el("div", "panel");
          bad.style.marginBottom = "26px";
          bad.appendChild(el("div", "empty", "This section could not be shown."));
          host.appendChild(bad);
          return;
        }
        while (tmp.firstChild) { host.appendChild(tmp.firstChild); }
      });
  }

  // ---- tabs --------------------------------------------------------

  var TABS = ["matchup", "season"];
  var tab = "matchup";

  try {
    var savedTab = localStorage.getItem("schneid-desk-tab");
    if (TABS.indexOf(savedTab) >= 0) { tab = savedTab; }
  } catch (e) { /* private window or blocked storage: default to Matchup */ }

  function applyTab() {
    TABS.forEach(function (name) {
      var on = name === tab;
      var b = document.getElementById("tab-" + name);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      document.getElementById("panel-" + name).hidden = !on;
    });
    document.getElementById("stepper").hidden = tab !== "season";
  }

  function setTab(name, focus) {
    if (TABS.indexOf(name) < 0) { return; }
    tab = name;
    try { localStorage.setItem("schneid-desk-tab", name); } catch (e) { /* ignore */ }
    applyTab();
    if (focus) { document.getElementById("tab-" + name).focus(); }
  }

  TABS.forEach(function (name, i) {
    var b = document.getElementById("tab-" + name);
    b.addEventListener("click", function () { setTab(name, false); });
    b.addEventListener("keydown", function (ev) {
      var to = null;
      if (ev.key === "ArrowRight") { to = TABS[(i + 1) % TABS.length]; }
      else if (ev.key === "ArrowLeft") { to = TABS[(i + TABS.length - 1) % TABS.length]; }
      else if (ev.key === "Home") { to = TABS[0]; }
      else if (ev.key === "End") { to = TABS[TABS.length - 1]; }
      if (to) { ev.preventDefault(); setTab(to, true); }
    });
  });

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
    try { renderMatchup(lg); } catch (e) {
      var mxh = document.getElementById("panel-matchup");
      mxh.innerHTML = "";
      mxh.appendChild(el("div", "empty", "The matchup could not be shown for this league."));
    }
  }

  var stamp = new Date(DATA.generated_at);
  document.getElementById("asof").textContent =
    "Data as of " + stamp.toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
    });

  wi = (leagues[li] && leagues[li].weeks.length - 1) || 0;
  applyTab();
  render();
})();
</script>
