<title>{{TITLE}}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --ground:#f2f5f2; --surface:#ffffff; --surface-2:#e8eee9;
  --ink:#111f1b; --ink-2:#3f544d; --ink-3:#6d837b;
  --line:#d2ddd7; --line-2:#bccbc4;
  --teal:#215f55; --teal-soft:#e0edea;
  --amber:#9d5f0b; --amber-soft:#f6ecda;
  --clay:#933724; --clay-soft:#f6e4df;
  --rb:#215f55; --wr:#6f4590; --te:#9d5f0b; --qb:#27547f; --k:#6d837b; --def:#525d59;
  --shadow:0 1px 2px rgba(17,31,27,.06), 0 4px 14px rgba(17,31,27,.05);
  --radius:10px;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#0b1513; --surface:#121e1b; --surface-2:#1a2825;
    --ink:#e7efeb; --ink-2:#a6bab3; --ink-3:#7b918a;
    --line:#243330; --line-2:#31443f;
    --teal:#59b0a0; --teal-soft:#152e2a;
    --amber:#d9a04a; --amber-soft:#32260f;
    --clay:#d47a63; --clay-soft:#331a14;
    --rb:#59b0a0; --wr:#b18bd0; --te:#d9a04a; --qb:#7aabd8; --k:#7b918a; --def:#8b9a95;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 4px 16px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --ground:#0b1513; --surface:#121e1b; --surface-2:#1a2825;
  --ink:#e7efeb; --ink-2:#a6bab3; --ink-3:#7b918a;
  --line:#243330; --line-2:#31443f;
  --teal:#59b0a0; --teal-soft:#152e2a;
  --amber:#d9a04a; --amber-soft:#32260f;
  --clay:#d47a63; --clay-soft:#331a14;
  --rb:#59b0a0; --wr:#b18bd0; --te:#d9a04a; --qb:#7aabd8; --k:#7b918a; --def:#8b9a95;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 4px 16px rgba(0,0,0,.3);
}

*{box-sizing:border-box}
body{
  background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.5; margin:0;
  -webkit-text-size-adjust:100%;
}
.wrap{max-width:1080px; margin:0 auto; padding:0 20px 72px}

/* ---------- masthead ---------- */
header.mast{
  border-bottom:2px solid var(--ink); margin-bottom:26px;
  padding:26px 0 16px;
}
.eyebrow{
  font-family:"IBM Plex Mono",monospace; font-size:11px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--ink-3); margin:0 0 8px;
}
h1{
  font-family:Oswald,"Arial Narrow",sans-serif; font-weight:600;
  font-size:clamp(30px,6vw,46px); line-height:1.02; letter-spacing:-.01em;
  margin:0 0 14px; text-wrap:balance; text-transform:uppercase;
}
.mast-facts{
  display:flex; flex-wrap:wrap; gap:0; border-top:1px solid var(--line);
  padding-top:12px;
}
.fact{padding-right:28px; margin-right:28px; border-right:1px solid var(--line)}
.fact:last-child{border-right:0; margin-right:0; padding-right:0}
.fact dt{
  font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--ink-3); margin:0 0 2px;
}
.fact dd{
  margin:0; font-family:Oswald,sans-serif; font-size:19px; font-weight:500;
  font-variant-numeric:tabular-nums;
}

/* ---------- sections ---------- */
section{margin:0 0 44px}
h2{
  font-family:Oswald,sans-serif; font-weight:500; text-transform:uppercase;
  letter-spacing:.03em; font-size:22px; margin:0 0 4px;
}
.sub{color:var(--ink-2); font-size:14px; margin:0 0 18px; max-width:66ch}
.sub code{
  font-family:"IBM Plex Mono",monospace; font-size:12.5px;
  background:var(--surface-2); padding:1px 5px; border-radius:4px;
}

/* ---------- pick rail ---------- */
.rail{
  display:flex; flex-wrap:wrap; gap:4px; padding-bottom:4px;
}
.rail .cell{
  flex:1 1 52px;
  background:var(--surface); border:1px solid var(--line); border-radius:6px;
  padding:8px 4px; text-align:center; min-width:52px;
}
.rail .cell .rd{
  font-family:"IBM Plex Mono",monospace; font-size:9.5px; color:var(--ink-3);
  letter-spacing:.06em;
}
.rail .cell .pk{
  font-family:Oswald,sans-serif; font-size:19px; font-weight:600;
  font-variant-numeric:tabular-nums; line-height:1.15;
}
.rail .cell.pair{border-color:var(--teal); background:var(--teal-soft)}
.gap-note{
  display:flex; gap:10px; align-items:baseline; margin-top:12px;
  font-size:13.5px; color:var(--ink-2);
}
.gap-note b{color:var(--teal); font-family:"IBM Plex Mono",monospace}

/* ---------- turn cards ---------- */
.turns{display:grid; gap:14px; grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}
.turn{
  background:var(--surface); border:1px solid var(--line);
  border-radius:var(--radius); box-shadow:var(--shadow); overflow:hidden;
}
.turn > header{
  display:flex; align-items:baseline; gap:10px;
  padding:11px 14px; border-bottom:1px solid var(--line);
  background:var(--surface-2);
}
.turn .rnum{
  font-family:Oswald,sans-serif; font-size:15px; font-weight:600;
  text-transform:uppercase; letter-spacing:.04em;
}
.turn .pnum{
  font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--ink-3);
  margin-left:auto;
}
.plist{list-style:none; margin:0; padding:4px 0}
.plist li{
  display:grid; grid-template-columns:34px 1fr auto; gap:9px;
  align-items:center; padding:6px 14px;
}
.plist li + li{border-top:1px solid var(--line)}
.pos{
  font-family:Oswald,sans-serif; font-size:10.5px; font-weight:600;
  letter-spacing:.06em; text-align:center; padding:2.5px 0; border-radius:4px;
  color:#fff;
}
.pos.RB{background:var(--rb)} .pos.WR{background:var(--wr)}
.pos.TE{background:var(--te)} .pos.QB{background:var(--qb)}
.pos.K{background:var(--k)}   .pos.DEF{background:var(--def)}
.pname{font-weight:500; font-size:14px; line-height:1.25}
.pmeta{
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; color:var(--ink-3);
  margin-top:1px;
}
.pmeta .val{color:var(--amber); font-weight:500}
.avail{text-align:right; min-width:66px}
.avail .pct{
  font-family:Oswald,sans-serif; font-size:16px; font-weight:500;
  font-variant-numeric:tabular-nums; line-height:1;
}
.bar{
  height:3px; border-radius:2px; background:var(--surface-2);
  margin-top:4px; overflow:hidden;
}
.bar span{display:block; height:100%; background:var(--teal)}
.bar.warn span{background:var(--clay)}

/* ---------- cliffs ---------- */
.cliffs{display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.cliff{
  background:var(--surface); border:1px solid var(--line);
  border-radius:var(--radius); padding:14px 16px 16px;
}
.cliff h3{
  font-family:Oswald,sans-serif; font-size:14px; font-weight:600; margin:0 0 2px;
  text-transform:uppercase; letter-spacing:.05em;
}
.cliff .lede{font-size:12px; color:var(--ink-3); margin:0 0 12px}
.crow{display:grid; grid-template-columns:1fr 44px; gap:8px; align-items:center; margin-bottom:5px}
.crow .cn{font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.crow .cnum{
  display:inline-block; min-width:18px; color:var(--ink-3);
  font-family:"IBM Plex Mono",monospace; font-size:10px; font-variant-numeric:tabular-nums;
}
.cbar{height:11px; background:var(--surface-2); border-radius:2px; overflow:hidden}
.cbar span{display:block; height:100%}
.cval{
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; color:var(--ink-3);
  text-align:right; font-variant-numeric:tabular-nums;
}
.crow.drop{position:relative; margin-top:13px; padding-top:9px}
.crow.drop::before{
  content:"tier break"; position:absolute; top:-1px; left:0; right:0;
  border-top:1.5px dashed var(--clay);
  font-family:"IBM Plex Mono",monospace; font-size:8.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--clay); padding-top:2px;
}

/* ---------- tables ---------- */
.tablewrap{overflow-x:auto; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:13.5px}
th,td{padding:7px 12px; text-align:left; white-space:nowrap}
thead th{
  font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-3); font-weight:400;
  border-bottom:1px solid var(--line-2); background:var(--surface-2);
  position:sticky; top:0;
}
tbody tr + tr td{border-top:1px solid var(--line)}
td.num{font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums; text-align:right}
td.rk{font-family:Oswald,sans-serif; font-weight:600; font-size:15px; color:var(--ink-2)}
.chip{
  font-family:Oswald,sans-serif; font-size:10px; font-weight:600; letter-spacing:.05em;
  padding:2px 6px; border-radius:4px; color:#fff;
}
.pill{
  font-family:"IBM Plex Mono",monospace; font-size:11px; padding:2px 7px;
  border-radius:20px; font-variant-numeric:tabular-nums;
}
.pill.up{background:var(--amber-soft); color:var(--amber)}
.pill.down{background:var(--clay-soft); color:var(--clay)}
.scroll-tall{max-height:520px; overflow-y:auto}

/* ---------- two-up ---------- */
.twoup{display:grid; gap:18px; grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}

/* ---------- notes ---------- */
.note{
  background:var(--surface); border:1px solid var(--line);
  border-left:3px solid var(--clay); border-radius:var(--radius);
  padding:14px 18px; margin-bottom:14px;
}
.note h3{
  font-family:Oswald,sans-serif; font-size:14px; text-transform:uppercase;
  letter-spacing:.05em; margin:0 0 6px; font-weight:600;
}
.note.teal{border-left-color:var(--teal)}
.note p{margin:0 0 8px; font-size:13.5px; color:var(--ink-2); max-width:74ch}
.note p:last-child{margin-bottom:0}
.note b{color:var(--ink)}
.method{font-size:13px; color:var(--ink-2)}
.method li{margin-bottom:7px; max-width:74ch}
footer{
  border-top:1px solid var(--line); padding-top:16px; margin-top:40px;
  font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--ink-3);
}
@media (max-width:640px){
  .fact{padding-right:16px; margin-right:16px}
}
</style>

<div class="wrap">

<header class="mast">
  <p class="eyebrow">{{EYEBROW}}</p>
  <h1>{{HEADLINE}}</h1>
  <dl class="mast-facts">
{{MAST_FACTS}}
    <div class="fact"><dt>Pool ranked</dt><dd id="f-pool">&mdash;</dd></div>
  </dl>
</header>

<section>
  <h2>{{PICKS_HEADING}}</h2>
  <p class="sub">{{PICKS_SUB}}</p>
  <div class="rail" id="rail"></div>
  <p class="gap-note">{{GAP_NOTE}}</p>
</section>

<section>
  <h2>Targets at each turn</h2>
  <p class="sub">Ranked by <b>expected value</b> &mdash; a player's value over replacement multiplied by the chance he is still on the board when your pick arrives. Capped at three per position, because the fourth-best available tight end is not a real choice when you start one. Kickers and defenses are hidden until the final three rounds.</p>
  <div class="turns" id="turns"></div>
</section>

<section>
  <h2>Where each position falls off</h2>
  <p class="sub">{{CLIFF_SUB}}</p>
  <div class="cliffs" id="cliffs"></div>
</section>

<section>
  <h2>Value and reach against the market</h2>
  <p class="sub">Difference between a player's average draft position and where this board ranks him, measured only against players the market has actually priced. Positive means the room is letting him fall; negative means the room likes him more than the numbers do.</p>
  <div class="twoup">
    <div>
      <h3 style="font-family:Oswald,sans-serif;font-size:13px;text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px;color:var(--amber)">Falling to you</h3>
      <div class="tablewrap"><table id="t-values"></table></div>
    </div>
    <div>
      <h3 style="font-family:Oswald,sans-serif;font-size:13px;text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px;color:var(--clay)">Going too early</h3>
      <div class="tablewrap"><table id="t-reaches"></table></div>
    </div>
  </div>
</section>

<section>
  <h2>Full board</h2>
  <p class="sub">Top {{BOARD_N}} of the ranked pool. <code>VOR</code> is value over replacement for this exact roster; <code>&Delta;ADP</code> is the market gap above; <code>SRC</code> shows whether the rank uses both the 2026 market and 2025 production, or the market alone.</p>
  <div class="tablewrap scroll-tall"><table id="t-board"></table></div>
</section>

<section>
  <h2>Read this before you pick</h2>

{{NOTES}}
  </ol>
</section>

<footer id="foot">&mdash;</footer>
</div>

<script>
const DATA = {{DATA}};

const POS = ["RB","WR","TE","QB","K","DEF"];
const num = (v, d=1) => (v === null || v === undefined) ? "—" : Number(v).toFixed(d);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));

/* ---- masthead ---- */
document.getElementById("f-pool").textContent = DATA.counts.board;
document.getElementById("foot").textContent = DATA.meta.footer;

/* ---- pick rail ---- */
document.getElementById("rail").innerHTML = DATA.picks.map((p, i) => {
  const gapNext = i < DATA.picks.length - 1 ? DATA.picks[i+1] - p : null;
  const gapPrev = i > 0 ? p - DATA.picks[i-1] : null;
  const sg = DATA.meta.shortGap;
  const pair = sg !== null && (gapNext === sg || gapPrev === sg);
  return '<div class="cell' + (pair ? ' pair' : '') + '">' +
    '<div class="rd">R' + (i+1) + '</div><div class="pk">' + p + '</div></div>';
}).join("");

/* ---- turn cards ---- */
document.getElementById("turns").innerHTML = DATA.turns.map(t => {
  const rows = t.targets.length ? t.targets.map(p => {
    const pct = Math.round(p.p * 100);
    const warn = p.p < 0.55;
    const bits = [];
    bits.push("ADP " + num(p.adp));
    bits.push("VOR " + num(p.vor, 2));
    if (p.bye) bits.push("bye " + p.bye);
    let meta = bits.join("  ·  ");
    if (p.delta !== null && p.delta >= 12) {
      meta += '  ·  <span class="val">+' + Math.round(p.delta) + ' vs ADP</span>';
    }
    return '<li>' +
      '<span class="pos ' + p.pos + '">' + p.pos + '</span>' +
      '<span><span class="pname">' + esc(p.name) + '</span>' +
        '<span class="pmeta">' + meta + '</span></span>' +
      '<span class="avail"><span class="pct">' + pct + '%</span>' +
        '<span class="bar' + (warn ? ' warn' : '') + '"><span style="width:' + pct + '%"></span></span>' +
      '</span></li>';
  }).join("") : '<li><span></span><span class="pmeta">No scored targets remain.</span><span></span></li>';

  return '<article class="turn"><header>' +
    '<span class="rnum">Round ' + t.round + '</span>' +
    '<span class="pnum">pick ' + t.pick + ' overall</span></header>' +
    '<ul class="plist">' + rows + '</ul></article>';
}).join("");

/* ---- cliffs ---- */
const CLIFF_NOTE = DATA.cliffNotes || {};
document.getElementById("cliffs").innerHTML = (DATA.cliffOrder || POS.slice(0,4)).map(pos => {
  const rows = DATA.cliffs[pos] || [];
  const max = Math.max(...rows.map(r => r.vor), 0.01);
  let biggestDrop = -1, dropIdx = -1;
  for (let i = 1; i < rows.length; i++) {
    const d = rows[i-1].vor - rows[i].vor;
    if (d > biggestDrop) { biggestDrop = d; dropIdx = i; }
  }
  const bars = rows.map((r, i) => {
    const w = Math.max(2, (r.vor / max) * 100);
    return '<div class="crow' + (i === dropIdx ? ' drop' : '') + '">' +
      '<div><div class="cn"><span class="cnum">' + (i+1) + '</span>' + esc(r.name) + '</div>' +
      '<div class="cbar"><span style="width:' + w + '%;background:var(--' + pos.toLowerCase() + ')"></span></div></div>' +
      '<div class="cval">' + num(r.vor, 2) + '</div></div>';
  }).join("");
  return '<div class="cliff"><h3 style="color:var(--' + pos.toLowerCase() + ')">' + pos + '</h3>' +
    '<p class="lede">' + CLIFF_NOTE[pos] + '</p>' + bars + '</div>';
}).join("");

/* ---- value / reach tables ---- */
function deltaTable(el, rows, dir) {
  document.getElementById(el).innerHTML =
    '<thead><tr><th>Player</th><th>Pos</th><th style="text-align:right">ADP</th>' +
    '<th style="text-align:right">&Delta;</th></tr></thead><tbody>' +
    rows.map(r =>
      '<tr><td>' + esc(r.name) + '</td>' +
      '<td><span class="chip pos ' + r.pos + '">' + r.pos + '</span></td>' +
      '<td class="num">' + num(r.adp) + '</td>' +
      '<td class="num"><span class="pill ' + dir + '">' +
        (r.delta > 0 ? "+" : "") + Math.round(r.delta) + '</span></td></tr>'
    ).join("") + '</tbody>';
}
deltaTable("t-values", DATA.values, "up");
deltaTable("t-reaches", DATA.reaches, "down");

/* ---- full board ---- */
document.getElementById("t-board").innerHTML =
  '<thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Tm</th>' +
  '<th style="text-align:right">Bye</th><th style="text-align:right">ADP</th>' +
  '<th style="text-align:right">ECR</th><th style="text-align:right">VOR</th>' +
  '<th style="text-align:right">&Delta;ADP</th><th>SRC</th></tr></thead><tbody>' +
  DATA.overall.map(r => {
    let d = "—";
    if (r.delta !== null) {
      const cls = r.delta >= 0 ? "up" : "down";
      d = '<span class="pill ' + cls + '">' + (r.delta > 0 ? "+" : "") + Math.round(r.delta) + '</span>';
    }
    const src = r.comp === 2 ? "both" : "mkt";
    return '<tr><td class="rk">' + Math.round(r.rank) + '</td>' +
      '<td>' + esc(r.name) + '</td>' +
      '<td><span class="chip pos ' + r.pos + '">' + r.pos + (r.posrank ? " " + Math.round(r.posrank) : "") + '</span></td>' +
      '<td class="num">' + (r.team || "—") + '</td>' +
      '<td class="num">' + (r.bye ? Math.round(r.bye) : "—") + '</td>' +
      '<td class="num">' + num(r.adp) + '</td>' +
      '<td class="num">' + num(r.ecr) + '</td>' +
      '<td class="num">' + num(r.vor, 2) + '</td>' +
      '<td class="num">' + d + '</td>' +
      '<td class="num" style="color:var(--ink-3);font-size:11px">' + src + '</td></tr>';
  }).join("") + '</tbody>';
</script>
