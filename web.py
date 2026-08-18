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

Usage: python3 web.py [--out out/projections.html] [--open]
"""

import argparse
import csv
import glob
import json
import os
import re
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
            i=int(r["element"]),
        ))
    out.sort(key=lambda d: -d["xp"])
    return out


CSS = """
:root{
  --ground:#EDEFF1; --panel:#FFFFFF; --line:#D3D8DC;
  --ink:#12171C; --ink-2:#4C565F; --ink-3:#78838C;
  --accent:#0F7F6E; --accent-soft:#D9EFEA; --warn:#9A6B12; --loss:#A83A2E;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0D1116; --panel:#151B22; --line:#27313A;
  --ink:#E6EBEF; --ink-2:#9AA7B2; --ink-3:#6B7883;
  --accent:#3ED9BC; --accent-soft:#12312C; --warn:#E0A83A; --loss:#E8705F;
}}
:root[data-theme="dark"]{
  --ground:#0D1116; --panel:#151B22; --line:#27313A;
  --ink:#E6EBEF; --ink-2:#9AA7B2; --ink-3:#6B7883;
  --accent:#3ED9BC; --accent-soft:#12312C; --warn:#E0A83A; --loss:#E8705F;
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
.layout{display:grid;grid-template-columns:1fr;gap:1.4rem}
@media(min-width:1080px){.layout{grid-template-columns:1fr 21rem;align-items:start}}
.squad{background:var(--panel);border:1px solid var(--line);padding:1rem;
  position:sticky;top:1rem}
.squad h2{font-family:var(--mono);font-size:.72rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 .7rem}
.tot{display:grid;grid-template-columns:1fr 1fr;gap:.55rem;margin-bottom:.8rem}
.tot div{background:var(--ground);border:1px solid var(--line);padding:.5rem .6rem}
.tot .k{font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);
  font-family:var(--mono)}
.tot .v{font-family:var(--mono);font-size:1.1rem;color:var(--ink);font-weight:600;
  font-variant-numeric:tabular-nums}
.tot .v.bad{color:var(--loss)}
.line{font-family:var(--mono);font-size:.6rem;letter-spacing:.1em;color:var(--ink-3);
  text-transform:uppercase;margin:.6rem 0 .25rem}
.pick{display:flex;align-items:center;gap:.4rem;padding:.22rem .3rem;font-size:.8rem;
  border-bottom:1px solid var(--line)}
.pick .nm{flex:1;color:var(--ink);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.pick .xp{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink-2)}
.pick button{background:none;border:0;color:var(--ink-3);cursor:pointer;font-size:1rem;
  line-height:1;padding:0 .15rem}
.pick button:hover{color:var(--loss)}
.pick.benched .nm,.pick.benched .xp{opacity:.45}
.warn{font-size:.76rem;color:var(--loss);margin:.5rem 0 0}
.hint{font-size:.76rem;color:var(--ink-3);margin:.5rem 0 0}
tr.picked{background:var(--accent-soft)}
tr{cursor:pointer}
.loss{color:var(--loss)}
nav{display:flex;gap:.1rem;font-family:var(--mono);font-size:.72rem;
  letter-spacing:.06em;text-transform:uppercase}
nav a{padding:.4rem .75rem;border:1px solid var(--line);color:var(--ink-2);
  text-decoration:none}
nav a[aria-current="page"]{background:var(--accent);color:var(--ground);
  border-color:var(--accent)}
nav a:hover:not([aria-current]){color:var(--ink);border-color:var(--ink-3)}
nav a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

"""

JS = r"""
const COLS=[["n","Player",0],["t","Team",0],["p","Pos",0],["c","\u00A3",1],
  ["xp","xP",1],["sd","\u00B1",1],["ppm","xP/\u00A3m",1],["ps","Start %",1],["m","xMins",1]];
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
    return '<tr data-i="'+d.i+'"'+(squad.includes(d.i)?' class="picked"':'')+'>'+
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
  tb.querySelectorAll("tr[data-i]").forEach(tr=>
    tr.addEventListener("click",()=>toggle(+tr.dataset.i)));
}
function esc(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}


// --- squad -----------------------------------------------------------------
// FPL's actual constraints. Enforcing them is the point: a "my team" view that
// lets you pick 6 forwards tells you nothing about a team you could field.
const LIMITS={GKP:2,DEF:5,MID:5,FWD:3}, BUDGET=100.0, MAX_PER_CLUB=3;
// Valid outfield shapes, always 1 GK. FPL allows anything from 3-4-3 to 5-4-1
// provided at least 3 DEF and at least 1 FWD.
const SHAPES=[[3,4,3],[3,5,2],[4,3,3],[4,4,2],[4,5,1],[5,3,2],[5,4,1],[5,2,3],[3,3,4]];
let squad=[];
const byId=Object.fromEntries(DATA.map(d=>[d.i,d]));

function bestXI(members){
  // Pick the highest-xP legal starting eleven. Bench is whatever is left.
  const g=members.filter(d=>d.p==="GKP").sort((a,b)=>b.xp-a.xp);
  const d=members.filter(d=>d.p==="DEF").sort((a,b)=>b.xp-a.xp);
  const m=members.filter(d=>d.p==="MID").sort((a,b)=>b.xp-a.xp);
  const f=members.filter(d=>d.p==="FWD").sort((a,b)=>b.xp-a.xp);
  if(!g.length) return null;
  let best=null;
  for(const [nd,nm,nf] of SHAPES){
    if(d.length<nd||m.length<nm||f.length<nf) continue;
    const xi=[g[0],...d.slice(0,nd),...m.slice(0,nm),...f.slice(0,nf)];
    const tot=xi.reduce((s,x)=>s+x.xp,0);
    if(!best||tot>best.tot) best={xi,tot,shape:nd+"-"+nm+"-"+nf};
  }
  return best;
}

function squadIssues(members){
  const out=[];
  const cost=members.reduce((s,d)=>s+d.c,0);
  if(cost>BUDGET) out.push("\u00A3"+(cost-BUDGET).toFixed(1)+"m over budget");
  for(const [pos,max] of Object.entries(LIMITS)){
    const n=members.filter(d=>d.p===pos).length;
    if(n>max) out.push(n+" "+pos+" (max "+max+")");
  }
  const clubs={};
  members.forEach(d=>{clubs[d.t]=(clubs[d.t]||0)+1;});
  for(const [t,n] of Object.entries(clubs))
    if(n>MAX_PER_CLUB) out.push(n+" from "+t+" (max "+MAX_PER_CLUB+")");
  return out;
}

function renderSquad(){
  const members=squad.map(i=>byId[i]).filter(Boolean);
  const cost=members.reduce((s,d)=>s+d.c,0);
  const xi=bestXI(members);
  const issues=squadIssues(members);
  const full=members.length===15;

  document.getElementById("sq-n").textContent=members.length+"/15";
  document.getElementById("sq-n").className="v"+(members.length>15?" bad":"");
  document.getElementById("sq-cost").textContent="\u00A3"+cost.toFixed(1)+"m";
  document.getElementById("sq-cost").className="v"+(cost>BUDGET?" bad":"");
  document.getElementById("sq-xp").textContent=xi?xi.tot.toFixed(1):"\u2014";
  document.getElementById("sq-shape").textContent=
    xi&&full?xi.shape:(members.length?"\u2014":"\u2014");

  const bench=xi?members.filter(d=>!xi.xi.includes(d)):members;
  const body=document.getElementById("sq-list");
  if(!members.length){
    body.innerHTML='<p class="hint">Click any row in the table to add a player. '+
      'Real FPL limits apply: 100m budget, 2/5/5/3 by position, max 3 per club.</p>';
  }else{
    const line=(label,arr,benched)=>arr.length?'<div class="line">'+label+'</div>'+
      arr.map(d=>'<div class="pick'+(benched?" benched":"")+'">'+
        '<span class="nm">'+esc(d.n)+' <span style="opacity:.5">'+d.t+'</span></span>'+
        '<span class="xp">'+d.xp.toFixed(2)+'</span>'+
        '<button data-rm="'+d.i+'" aria-label="Remove '+esc(d.n)+'">&times;</button>'+
        '</div>').join(""):"";
    body.innerHTML=
      (xi?line("Starting "+xi.shape,xi.xi,false):"")+
      line(xi?"Bench":"Squad",bench,!!xi)+
      (issues.length?'<p class="warn">'+issues.map(esc).join("<br>")+'</p>':"")+
      (!full?'<p class="hint">'+(15-members.length)+' more to a full squad.</p>':"");
    body.querySelectorAll("button[data-rm]").forEach(b=>
      b.addEventListener("click",e=>{
        e.stopPropagation();
        squad=squad.filter(i=>i!==+b.dataset.rm);
        save();renderSquad();render();
      }));
  }
}

function toggle(id){
  squad = squad.includes(id) ? squad.filter(i=>i!==id) : squad.concat([id]);
  save();renderSquad();render();
}
function save(){try{localStorage.setItem("fpl.squad",JSON.stringify(squad));}catch(e){}}
function load(){try{squad=JSON.parse(localStorage.getItem("fpl.squad")||"[]");}catch(e){squad=[];}}

document.addEventListener("DOMContentLoaded",()=>{
  load();
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
  render();renderSquad();
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

<div class="layout">
  <div class="scroll">
    <table>
      <thead><tr id="th"></tr></thead>
      <tbody id="tb"></tbody>
    </table>
  </div>
  <aside class="squad" aria-label="Your squad">
    <h2>Your squad</h2>
    <div class="tot">
      <div><span class="k">Players</span><span class="v" id="sq-n">0/15</span></div>
      <div><span class="k">Cost</span><span class="v" id="sq-cost">&pound;0.0m</span></div>
      <div><span class="k">Best XI xP</span><span class="v" id="sq-xp">&mdash;</span></div>
      <div><span class="k">Shape</span><span class="v" id="sq-shape">&mdash;</span></div>
    </div>
    <div id="sq-list"></div>
  </aside>
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


def _payload(html):
    """The projection data alone, for change detection.

    Comparing whole pages was wrong: the header shows a generated-at stamp AND
    the snapshot digest, and FPL's bootstrap response changes every hour on
    fields the model never reads (transfer counts, ownership percentages). So
    the digest moved hourly while not a single projected point did, and the
    scheduled job committed 46 times in three days with zero real change.

    What a reader cares about is whether any projection moved. Compare that.
    """
    m = re.search(r"const DATA=(\[.*?\]);", html, re.S)
    return m.group(1) if m else html


def lint_js(html):
    """Catch the failure mode that blanks the page without any visible error.

    A single unescaped quote inside a generated JS string literal throws a
    SyntaxError, the whole script never executes, and the page still renders
    its static shell — headers, filters, an empty table — looking merely empty
    rather than broken. That shipped once. This is a cheap structural check, not
    a parser, but it catches exactly that class of mistake.
    """
    js = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    problems = []
    for n, line in enumerate(js.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("const DATA="):
            continue  # the data literal is JSON and legitimately full of quotes
        # Walk the line tracking string state. An apostrophe inside a
        # double-quoted string is fine; an unescaped one closing a single-quoted
        # string early is what blanks the page.
        quote, i, esc = None, 0, False
        while i < len(line):
            ch = line[i]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break  # trailing comment
            i += 1
        if quote:
            problems.append("line {}: unterminated {} string: {}".format(
                n, "single" if quote == "'" else "double", stripped[:90]))
    nonascii = sorted(set(c for c in js if ord(c) > 127))
    if nonascii:
        problems.append(
            "non-ASCII in JS: {} - use \\uXXXX escapes. The page carries no "
            "charset declaration, so raw UTF-8 renders as mojibake when served "
            "over plain HTTP.".format(" ".join(nonascii)))
    for needed in ("#tb", "#th", "sq-n", "DOMContentLoaded"):
        if needed not in js and needed.lstrip("#") not in js:
            problems.append("missing expected reference: {}".format(needed))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(OUT, "projections.html"))
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--prior", default="2025-26")
    args = ap.parse_args()

    rows, meta, source = latest_projection(args.prior)
    html = build(rows, meta, source)
    problems = lint_js(html)
    if problems:
        print("REFUSING TO WRITE - generated JavaScript looks broken:")
        for pr in problems:
            print("  - {}".format(pr))
        return 1

    # Only rewrite when something a reader would notice has changed. The page
    # carries a "Generated ... UTC" stamp, so a byte comparison always differs
    # and the hourly job would commit 24 times a day saying nothing. Compare
    # with that line masked out; git history already records when it ran.
    if os.path.exists(args.out):
        prev = open(args.out, encoding="utf-8").read()
        if _payload(prev) == _payload(html):
            print("projections page: no projection changed, not rewritten")
            if args.open:
                subprocess.run(["open", args.out])
            return 0

    with open(args.out, "w") as f:
        f.write(html)
    print("projections page: {}".format(args.out))
    print("  GW{}, {} players, {} established, source: {}".format(
        meta.get("gameweek"), len(rows),
        sum(1 for r in rows if r["eligible"] == "1"), source))
    if args.open:
        subprocess.run(["open", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
