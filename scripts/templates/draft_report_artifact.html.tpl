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
.sub{color:var(--ink-2); font-size:14px; margin:0 0 18px; max-width:70ch}
.sub code{
  font-family:"IBM Plex Mono",monospace; font-size:12.5px;
  background:var(--surface-2); padding:1px 5px; border-radius:4px;
}

/* ---------- team grade cards ---------- */
.grade-grid{display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.grade-card{
  background:var(--surface); border:1px solid var(--line);
  border-radius:var(--radius); box-shadow:var(--shadow); overflow:hidden;
}
.grade-card > header{
  display:flex; align-items:center; gap:14px;
  padding:14px 16px; border-bottom:1px solid var(--line);
  background:var(--surface-2);
}
.grade-badge{
  font-family:Oswald,sans-serif; font-weight:600; font-size:28px;
  line-height:1; padding:6px 12px; border-radius:8px; color:#fff;
  min-width:44px; text-align:center; flex-shrink:0;
}
.grade-badge.grade-good{background:var(--teal)}
.grade-badge.grade-mid{background:var(--amber)}
.grade-badge.grade-bad{background:var(--clay)}
.grade-badge.grade-none{background:var(--ink-3); font-size:14px; padding:10px 8px}
.grade-card .team-id h3{
  font-family:Oswald,sans-serif; font-size:17px; font-weight:600; margin:0;
  text-transform:uppercase; letter-spacing:.02em;
}
.grade-card .team-id .rank{
  font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--ink-3);
  margin-top:2px;
}
.grade-card .body{padding:14px 16px 16px}
.ungraded-note{
  font-size:13px; color:var(--ink-2); background:var(--surface-2);
  border-radius:6px; padding:9px 11px; margin:0 0 12px;
}
.pickline{display:grid; grid-template-columns:56px 1fr auto; gap:8px; align-items:baseline; margin-bottom:8px}
.pickline .lbl{
  font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--ink-3);
}
.pickline .who{font-size:13.5px}
.pickline .val{
  font-family:"IBM Plex Mono",monospace; font-size:12px; font-variant-numeric:tabular-nums;
}
.pickline .val.up{color:var(--teal)}
.pickline .val.down{color:var(--clay)}
.stat-row{
  display:flex; flex-wrap:wrap; gap:14px; margin:10px 0 12px;
  padding-top:10px; border-top:1px solid var(--line);
}
.stat{font-size:11.5px; color:var(--ink-3); font-family:"IBM Plex Mono",monospace}
.stat b{color:var(--ink); font-family:"IBM Plex Sans",sans-serif; font-size:13px}
.posbar{list-style:none; margin:0; padding:0}
.posbar li{
  display:grid; grid-template-columns:44px 1fr 22px; gap:8px; align-items:center;
  margin-bottom:4px; font-size:12px;
}
.posbar .pos{
  font-family:Oswald,sans-serif; font-size:10.5px; font-weight:600;
  letter-spacing:.05em; color:var(--ink-2);
}
.posbar .track{height:8px; background:var(--surface-2); border-radius:4px; overflow:hidden}
.posbar .track span{display:block; height:100%; background:var(--ink-3)}
.posbar .n{
  text-align:right; font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--ink-3);
}
.commentary{
  margin:14px 0 0; padding-top:12px; border-top:1px dashed var(--line-2);
  font-size:13.5px; color:var(--ink-2); font-style:italic; white-space:pre-wrap;
}

.phase-breakdown{margin:12px 0 0; padding-top:10px; border-top:1px solid var(--line)}
.phase-title{
  font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.06em;
  text-transform:uppercase; color:var(--ink-3); margin:0 0 6px;
}
.phase-title .ph-hint{text-transform:none; letter-spacing:0}
.phase-list{list-style:none; margin:0; padding:0}
.phase-list li{
  display:grid; grid-template-columns:1fr auto; gap:8px; align-items:baseline;
  margin-bottom:4px; font-size:12.5px;
}
.ph-lbl{color:var(--ink-2)}
.ph-n{
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; color:var(--ink-3);
  margin-left:6px;
}
.ph-val{font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums}
.ph-val.up{color:var(--teal)}
.ph-val.down{color:var(--clay)}
.ph-sub{color:var(--ink-3); font-size:11px}

/* ---------- overview bars (JS-rendered from DATA) ---------- */
.overview{list-style:none; margin:0; padding:0}
.overview li{
  display:grid; grid-template-columns:160px 1fr 90px; gap:10px; align-items:center;
  margin-bottom:6px;
}
.overview .name{font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.overview .track{height:14px; background:var(--surface-2); border-radius:3px; overflow:hidden; position:relative}
.overview .track .zero{position:absolute; top:0; bottom:0; width:1px; background:var(--line-2)}
.overview .track span{position:absolute; top:0; bottom:0; display:block}
.overview .zval{
  text-align:right; font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--ink-3);
}

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
  </dl>
</header>

<section>
  <h2>Draft rank overview</h2>
  <p class="sub">Every team's blended <code>overall_z</code> (population z-score of total value over replacement and average pick value, see <code>draft_report.py</code>), best team first. Zero is average for this draft.</p>
  <ul class="overview" id="overview"></ul>
</section>

<section>
  <h2>Team draft grades</h2>
  <p class="sub">One card per team. <b>Value by draft phase</b> breaks the grade down by early/mid/late round, in real projected points (fit from this league's own prior draft -- see the footer). <b>Commentary</b> paragraphs are placeholders left for a manual/agent narrative pass -- see the script's module docstring for the search-and-replace workflow.</p>
  <div class="grade-grid">
{{TEAM_CARDS}}
  </div>
</section>

<footer id="foot">{{FOOTER}}</footer>
</div>

<script>
const DATA = {{DATA}};

const num = (v, d=2) => (v === null || v === undefined) ? "—" : Number(v).toFixed(d);

/* ---- draft rank overview (JS-rendered bar list) ---- */
const zs = DATA.teams.map(t => t.overall_z).filter(z => z !== null && z !== undefined);
const maxAbs = Math.max(0.5, ...zs.map(z => Math.abs(z)));
document.getElementById("overview").innerHTML = DATA.teams.map(t => {
  const z = t.overall_z;
  let bar = "";
  if (z !== null && z !== undefined) {
    const pct = Math.min(50, Math.abs(z) / maxAbs * 50);
    const color = z >= 0 ? "var(--teal)" : "var(--clay)";
    const left = z >= 0 ? "50%" : (50 - pct) + "%";
    bar = '<span style="left:' + left + ';width:' + pct + '%;background:' + color + '"></span>';
  }
  return '<li><span class="name">' + t.team_name + '</span>' +
    '<span class="track"><span class="zero" style="left:50%"></span>' + bar + '</span>' +
    '<span class="zval">' + (z === null || z === undefined ? "unscored" : num(z)) + '</span></li>';
}).join("");
</script>