#!/usr/bin/env python3
"""Build the projections page — the thing a user actually opens.

Until this existed the repo contained a proof and no product: a scorecard
arguing the numbers are trustworthy, and a CSV. Nobody subscribes to a CSV.
Scout and Hub sell tools you look things up in, and this is the minimum
version of that: every player, sortable, filterable, with the model's
uncertainty and start probability visible rather than hidden behind a
single number.

Self-contained: data is embedded as JSON, all interaction is client-side, no
network calls. That is a hard requirement — it has to work as a static file,
and the artifact sandbox blocks outbound requests anyway.

Usage: python3 site.py [--out out/projections.html] [--open]
"""

import argparse
import csv
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def latest_projection(prior_season):
    """Current projections, from the record if there is one, else computed live.

    These are two different things and the page should show the freshest:
      - the RECORD is what we committed to before a deadline, and is what the
        scorecard scores;
      - the PRODUCT is "what does the model think right now", which is what
        somebody opening the page wants.

    Before the first deadline the record is empty and the product still has to
    work, so fall through to building from the latest snapshot. Nothing is
    written to the record by this path.
    """
    metas = sorted(glob.glob(os.path.join(OUT, "projections_gw*.meta.json")))
    if metas:
        meta = json.load(open(metas[-1]))
        rows = list(csv.DictReader(open(metas[-1].replace(".meta.json", ".csv"))))
        return rows, meta, "record"

    import project as P
    snap = P.latest_snapshot()
    rows, meta, _ = P.build(snap, prior_season, quiet=True)
    # build() returns typed rows; the record path returns CSV strings. Normalise
    # so prepare() has one shape to handle rather than two.
    rows = [{k: ("1" if v is True else "0" if v is False else str(v))
             for k, v in r.items()} for r in rows]
    meta["hours_before_deadline"] = None
    return rows, meta, "live"


def prepare(rows):
    out = []
    for r in rows:
        xp = float(r["xp"])
        price = float(r["price"])
        out.append(dict(
            n=r["web_name"], t=r["team"], p=r["pos"], c=price,
            xp=round(xp, 2),
            sd=round(float(r["sd"]), 2),
            m=round(float(r["xmins"])),
            ps=round(float(r["p_start"]) * 100),
            ppm=round(xp / price, 3) if price else 0.0,
            f=int(r["n_fix"]),
            e=int(r["eligible"]),
        ))
    out.sort(key=lambda d: -d["xp"])
    return out


CSS = """
:root{
  --ground:#EDEFF1; --panel:#FFFFFF; --line:#D3D8DC;
  --ink:#12171C; --ink-2:#4C565F; --ink-3:#78838C;
  --accent:#0F7F6E; --accent-soft:#D9EFEA; --warn:#9A6B12;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0D1116; --panel:#151B22; --line:#27313A;
  --ink:#E6EBEF; --ink-2:#9AA7B2; --ink-3:#6B7883;
  --accent:#3ED9BC; --accent-soft:#12312C; --warn:#E0A83A;
}}
:root[data-theme="dark"]{
  --ground:#0D1116; --panel:#151B22; --line:#27313A;
  --ink:#E6EBEF; --ink-2:#9AA7B2; --ink-3:#6B7883;
  --accent:#3ED9BC; --accent-soft:#12312C; --warn:#E0A83A;
}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);
  margin:0;padding:clamp(1rem,3vw,2rem);line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:72rem;margin:0 auto;display:flex;flex-direction:column;gap:1.4rem}
h1{font-family:var(--mono);font-size:clamp(1.3rem,3.5vw,1.7rem);margin:0;
  letter-spacing:-.02em;font-weight:650}
.sub{color:var(--ink-2);font-size:.88rem;margin:.3rem 0 0}
.sub code{font-family:var(--mono);font-size:.82rem}
.controls{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;
  background:var(--panel);border:1px solid var(--line);padding:.8rem}
.seg{display:flex;border:1px solid var(--line)}
.seg button{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;
  background:transparent;color:var(--ink-2);border:0;padding:.42rem .7rem;
  cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--accent);color:var(--ground)}
.seg button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
input[type=search],select{font-family:var(--sans);font-size:.85rem;padding:.4rem .55rem;
  background:var(--ground);color:var(--ink);border:1px solid var(--line)}
label.chk{font-size:.8rem;color:var(--ink-2);display:flex;align-items:center;gap:.35rem;
  cursor:pointer}
.count{margin-left:auto;font-family:var(--mono);font-size:.76rem;color:var(--ink-3)}
.scroll{overflow-x:auto;background:var(--panel);border:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font-size:.86rem;min-width:44rem}
th{position:sticky;top:0;background:var(--panel);text-align:left;font-family:var(--mono);
  font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);
  padding:.55rem .6rem;border-bottom:1px solid var(--line);cursor:pointer;
  white-space:nowrap;user-select:none}
th:hover{color:var(--ink)}
th[aria-sort]{color:var(--accent)}
th.num,td.num{text-align:right}
td{padding:.45rem .6rem;border-bottom:1px solid var(--line);color:var(--ink-2);
  font-variant-numeric:tabular-nums;white-space:nowrap}
td.name{font-weight:600;color:var(--ink)}
td.mono{font-family:var(--mono)}
tbody tr:hover{background:var(--accent-soft)}
.bar{display:inline-block;height:.45rem;background:var(--accent);vertical-align:middle;
  margin-right:.4rem;min-width:1px}
.pill{font-family:var(--mono);font-size:.66rem;padding:.1rem .35rem;
  border:1px solid var(--line);color:var(--ink-3)}
.risk{color:var(--warn)}
footer{color:var(--ink-3);font-size:.76rem;font-family:var(--mono)}
.empty{padding:2rem;text-align:center;color:var(--ink-3)}
nav{display:flex;gap:.1rem;font-family:var(--mono);font-size:.72rem;
  letter-spacing:.06em;text-transform:uppercase}
nav a{padding:.4rem .75rem;border:1px solid var(--line);color:var(--ink-2);
  text-decoration:none}
nav a[aria-current="page"]{background:var(--accent);color:var(--ground);
  border-color:var(--accent)}
nav a:hover:not([aria-current]){color:var(--ink);border-color:var(--ink-3)}
nav a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

"""

JS = """
const COLS=[["n","Player",0],["t","Team",0],["p","Pos",0],["c","£",1],
  ["xp","xP",1],["sd","±",1],["ppm","xP/£m",1],["ps","Start %",1],["m","xMins",1]];
let sortKey="xp", sortDir=-1, posFilter="ALL", onlyEligible=true;
const maxXp=Math.max(...DATA.map(d=>d.xp));

function view(){
  const q=document.getElementById("q").value.trim().toLowerCase();
  const team=document.getElementById("team").value;
  let rows=DATA.filter(d=>
    (posFilter==="ALL"||d.p===posFilter) &&
    (team==="ALL"||d.t===team) &&
    (!onlyEligible||d.e===1) &&
    (!q||d.n.toLowerCase().includes(q)));
  rows.sort((a,b)=>{
    const x=a[sortKey],y=b[sortKey];
    if(typeof x==="string")return sortDir*x.localeCompare(y);
    return sortDir*(x-y);
  });
  return rows;
}

function render(){
  const rows=view();
  document.getElementById("count").textContent=
    rows.length+" of "+DATA.length+" players";
  const tb=document.getElementById("tb");
  if(!rows.length){tb.innerHTML=
    '<tr><td colspan="9" class="empty">No players match those filters.</td></tr>';return;}
  tb.innerHTML=rows.map(d=>{
    const w=Math.max(1,Math.round(d.xp/maxXp*46));
    const risky=d.ps<70;
    return '<tr>'+
      '<td class="name">'+esc(d.n)+(d.f>1?' <span class="pill">DGW</span>':'')+'</td>'+
      '<td class="mono">'+d.t+'</td><td class="mono">'+d.p+'</td>'+
      '<td class="num mono">'+d.c.toFixed(1)+'</td>'+
      '<td class="num mono"><span class="bar" style="width:'+w+'px"></span>'+
        d.xp.toFixed(2)+'</td>'+
      '<td class="num mono">'+d.sd.toFixed(2)+'</td>'+
      '<td class="num mono">'+d.ppm.toFixed(3)+'</td>'+
      '<td class="num mono'+(risky?' risk':'')+'">'+d.ps+'</td>'+
      '<td class="num mono">'+d.m+'</td></tr>';
  }).join("");
}
function esc(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

document.addEventListener("DOMContentLoaded",()=>{
  const thead=document.getElementById("th");
  thead.innerHTML=COLS.map(([k,label,num])=>
    '<th data-k="'+k+'" class="'+(num?"num":"")+'" tabindex="0">'+label+'</th>').join("");
  thead.querySelectorAll("th").forEach(th=>{
    const go=()=>{
      const k=th.dataset.k;
      // Numbers are more useful high-to-low on first click; names are not.
      sortDir = (sortKey===k) ? -sortDir : (k==="n"||k==="t"||k==="p" ? 1 : -1);
      sortKey=k;
      thead.querySelectorAll("th").forEach(o=>o.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort",sortDir===1?"ascending":"descending");
      render();
    };
    th.addEventListener("click",go);
    th.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();go();}});
  });
  document.querySelectorAll(".seg button").forEach(b=>{
    b.addEventListener("click",()=>{
      posFilter=b.dataset.pos;
      document.querySelectorAll(".seg button").forEach(o=>
        o.setAttribute("aria-pressed",o===b?"true":"false"));
      render();
    });
  });
  document.getElementById("q").addEventListener("input",render);
  document.getElementById("team").addEventListener("change",render);
  document.getElementById("elig").addEventListener("change",e=>{
    onlyEligible=e.target.checked;render();});
  render();
});
"""


def build(rows, meta, source="record"):
    data = prepare(rows)
    teams = sorted(set(d["t"] for d in data))
    gw = meta.get("gameweek")
    dl = (meta.get("deadline_utc") or "")[:16].replace("T", " ")
    made = meta.get("hours_before_deadline")
    if source == "live":
        made_s = ("computed just now &mdash; not yet the committed "
                  "pre-deadline projection")
    elif made is not None:
        made_s = "built {:.0f}h before the deadline".format(made)
    else:
        made_s = "built pre-deadline"

    return """<style>{css}</style>
<div class="wrap">
<nav aria-label="Sections"><a href="projections.html" aria-current="page">Projections</a><a href="scorecard.html">Accuracy record</a></nav>
<header>
  <h1>Gameweek {gw} projections</h1>
  <p class="sub">Deadline {dl} UTC &middot; {made} &middot; snapshot
  <code>{snap}</code>. <strong>xP</strong> is expected points, <strong>&plusmn;</strong>
  its standard deviation, <strong>Start&nbsp;%</strong> the modelled probability of
  starting. Sort any column; click again to reverse.</p>
</header>

<div class="controls">
  <div class="seg" role="group" aria-label="Filter by position">
    <button data-pos="ALL" aria-pressed="true">ALL</button>
    <button data-pos="GKP" aria-pressed="false">GKP</button>
    <button data-pos="DEF" aria-pressed="false">DEF</button>
    <button data-pos="MID" aria-pressed="false">MID</button>
    <button data-pos="FWD" aria-pressed="false">FWD</button>
  </div>
  <input type="search" id="q" placeholder="Search player" aria-label="Search player">
  <select id="team" aria-label="Filter by team">
    <option value="ALL">All teams</option>
    {teamopts}
  </select>
  <label class="chk"><input type="checkbox" id="elig" checked>
    Established players only</label>
  <span class="count" id="count"></span>
</div>

<div class="scroll">
  <table>
    <thead><tr id="th"></tr></thead>
    <tbody id="tb"></tbody>
  </table>
</div>

<footer>Generated {now} UTC &middot; every projection is timestamped and
reproducible from its snapshot &mdash; <a href="scorecard.html" style="color:var(--accent)">see how accurate these have actually been</a></footer>
</div>
<script>const DATA={data};{js}</script>""".format(
        css=CSS, js=JS, data=json.dumps(data, separators=(",", ":")),
        gw=gw, dl=dl, made=made_s,
        snap=(meta.get("snapshot_sha256", {}).get("bootstrap.json", "")[:12]),
        teamopts="\n    ".join(
            '<option value="{0}">{0}</option>'.format(t) for t in teams),
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(OUT, "projections.html"))
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--prior", default="2025-26")
    args = ap.parse_args()

    rows, meta, source = latest_projection(args.prior)
    with open(args.out, "w") as f:
        f.write(build(rows, meta, source))
    print("projections page: {}".format(args.out))
    print("  GW{}, {} players, {} established, source: {}".format(
        meta.get("gameweek"), len(rows),
        sum(1 for r in rows if r["eligible"] == "1"), source))
    if args.open:
        subprocess.run(["open", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
