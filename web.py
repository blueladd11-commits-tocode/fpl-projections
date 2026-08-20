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

import links
import rating
import words

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def _meta_order(path):
    """(gameweek, filename) so ordering is numeric on the gameweek."""
    m = re.search(r"projections_gw(\d+)_", os.path.basename(path))
    return (int(m.group(1)) if m else -1, os.path.basename(path))


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
    # Required by the page. A record entry written before a column existed is
    # still a valid record entry - it must never be regenerated, because it is a
    # committed pre-deadline artifact - but the PRODUCT cannot render from it.
    # Falling back to 0.0 silently shipped a captaincy column of all zeros.
    NEEDED = ("xp", "price", "sd", "xmins", "p_start", "n_fix", "eligible",
              "element", "xp_total", "xp_next", "p6", "p10", "p15")

    # Sort by (gameweek, timestamp), NOT lexicographically. Plain string sort
    # puts projections_gw9_... after projections_gw10_..., so from GW10 to the
    # end of the season the product page would have frozen on GW9 - showing a
    # deadline weeks in the past and calling it this week's projection.
    metas = sorted(glob.glob(os.path.join(OUT, "projections_gw*.meta.json")),
                   key=_meta_order)
    if metas:
        meta = json.load(open(metas[-1]))
        rows = list(csv.DictReader(open(metas[-1].replace(".meta.json", ".csv"))))
        missing = [c for c in NEEDED if rows and c not in rows[0]]
        if not missing:
            return rows, meta, "record"
        print("record entry lacks {}; computing live instead".format(
            ", ".join(missing)))

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
            tot=float(r.get("xp_total") or 0),
            h6=float(r.get("p6") or 0), h10=float(r.get("p10") or 0),
            h15=float(r.get("p15") or 0),
            g=[float(x) for x in (r.get("xp_next") or "").split(";") if x],
        ))
    out.sort(key=lambda d: -d["xp"])
    # Computed here, at the page, and deliberately not written into the
    # committed projection CSV: verify.py reproduces that file byte for byte,
    # and a presentation number has no business changing the permanent record.
    # Every input the rating uses is already in it.
    rating.compute(out)
    return out


CSS = links.CSS + words.CSS + rating.BAND_CSS + """
:root{
  --ground:#EDEFF1; --panel:#FFFFFF; --line:#D3D8DC;
  --ink:#12171C; --ink-2:#454F58; --ink-3:#5E6873;
  --accent:#0F7F6E; --accent-soft:#D9EFEA; --warn:#9A6B12; --loss:#A83A2E;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0D1116; --panel:#151B22; --line:#27313A;
  --ink:#E6EBEF; --ink-2:#A9B5BF; --ink-3:#8A97A2;
  --accent:#3ED9BC; --accent-soft:#12312C; --warn:#E0A83A; --loss:#E8705F;
}}
:root[data-theme="dark"]{
  --ground:#0D1116; --panel:#151B22; --line:#27313A;
  --ink:#E6EBEF; --ink-2:#A9B5BF; --ink-3:#8A97A2;
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
.spark{display:inline-flex;align-items:flex-end;gap:1px;height:12px;
  margin-left:.45rem;vertical-align:middle}
.spark i{width:3px;background:var(--accent);opacity:.55;display:block}
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
.seg.tx{margin:.3rem 0 .5rem;width:100%}
.seg.tx button{flex:1;font-size:.66rem;padding:.3rem .2rem}
.tx-row{display:flex;align-items:baseline;gap:.35rem;font-size:.78rem;
  padding:.22rem 0;border-bottom:1px solid var(--line)}
.tx-row .out{color:var(--ink-2);text-decoration:line-through;flex:1;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tx-row .arw{color:var(--ink-3);font-family:var(--mono)}
.tx-row .in{color:var(--ink);font-weight:600;flex:1;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.tx-row .gain{font-family:var(--mono);color:var(--accent);font-weight:600}
.tx-row .cost{font-family:var(--mono);font-size:.7rem;color:var(--ink-3);width:3.2rem;
  text-align:right}

"""

JS = r"""
const NG=(DATA[0]&&DATA[0].g?DATA[0].g.length:1);
// label, then the line under it saying what the number means. The sub is not
// decoration: a heading reading "Points" with nothing under it is friendlier
// than "xP" but no more informative, and being vague is not the same as being
// welcoming.
const COLS=[["n","Player","",0],["psr","PS Rating","out of 100",1],
  ["t","Club","",0],["p","Position","",0],
  ["c","Price","",1],
  ["xp","Points","this week",1],
  ["tot","Next "+NG,"weeks total",1],
  ["h10","Big week","chance of 10+",1],
  ["ppm","Value","per \u00A31m",1],
  ["ps","Starting","likelihood",1],
  ["m","Minutes","expected",1]];
// Short enough for a table cell, still a word rather than a code.
const POS={GKP:"Keeper",DEF:"Def",MID:"Mid",FWD:"Fwd"};
let sortKey="tot", sortDir=-1, posFilter="ALL", onlyEligible=true;
const maxXp=Math.max(...DATA.map(d=>d.xp));

function view(){
  const q=norm(document.getElementById("q").value.trim());
  const team=document.getElementById("team").value;
  let rows=DATA.filter(d=>
    (posFilter==="ALL"||d.p===posFilter) &&
    (team==="ALL"||d.t===team) &&
    (!onlyEligible||d.e===1) &&
    (!q||norm(d.n).includes(q)));
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
    '<tr><td colspan="'+COLS.length+'" class="empty">No players match those filters.</td></tr>';return;}
  tb.innerHTML=rows.map(d=>{
    const w=Math.max(1,Math.round(d.xp/maxXp*46));
    const risky=d.ps<70;
    // Sparkline over the horizon. The shape is the point: a flat 4.0 and a
    // 2-then-6 both total 8, and they are completely different transfers.
    const mx=Math.max(...d.g,0.1);
    const spark=d.g.map(v=>'<i style="height:'+
      Math.max(1,Math.round(v/mx*11))+'px" title="'+v.toFixed(2)+'"></i>').join("");
    return '<tr data-i="'+d.i+'"'+(squad.includes(d.i)?' class="picked"':'')+'>'+
      '<td class="name">'+esc(d.n)+(d.f>1?' <span class="pill">DGW</span>':'')+'</td>'+
      '<td class="num"><span class="psr psr-'+d.psr_band+'">'+d.psr+
      '</span></td>'+
      '<td class="mono">'+d.t+'</td><td class="mono">'+POS[d.p]+'</td>'+
      '<td class="num mono">'+d.c.toFixed(1)+'</td>'+
      '<td class="num mono"><span class="bar" style="width:'+w+'px"></span>'+
        d.xp.toFixed(2)+'</td>'+
      '<td class="num mono">'+d.tot.toFixed(1)+
        '<span class="spark">'+spark+'</span></td>'+
      '<td class="num mono" title="P(6+) '+d.h6.toFixed(1)+'%  P(15+) '+
        d.h15.toFixed(1)+'%">'+d.h10.toFixed(1)+'</td>'+
      '<td class="num mono">'+d.ppm.toFixed(3)+'</td>'+
      '<td class="num mono'+(risky?' risk':'')+'">'+d.ps+'</td>'+
      '<td class="num mono">'+d.m+'</td></tr>';
  }).join("");
  tb.querySelectorAll("tr[data-i]").forEach(tr=>
    tr.addEventListener("click",()=>toggle(+tr.dataset.i)));
}
// Fold diacritics so a normal keyboard can reach every player: 36 of 468 were
// unreachable - odegaard, nunez, gyokeres, guehi, gross, joao, kadioglu.
const FOLD={"\u00f8":"o","\u0142":"l","\u0111":"d","\u0131":"i","\u00df":"ss",
  "\u00e6":"ae","\u0153":"oe","\u00f0":"d","\u00fe":"th"};
function norm(s){
  return s.toLowerCase().replace(/[\u00e0-\u017f]/g,c=>FOLD[c]||c)
          .normalize("NFD").replace(/[\u0300-\u036f]/g,"");
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
    document.getElementById("sq-tx").innerHTML="";
    body.innerHTML='<p class="hint">Click any row in the table to add a player. '+
      'Real FPL rules apply: \u00A3100m to spend, 2 keepers, 5 defenders, '+
      '5 midfielders and 3 forwards, and no more than 3 from any one club.</p>';
    renderSuggestions(members);
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
    renderSuggestions(members);
    body.querySelectorAll("button[data-rm]").forEach(b=>
      b.addEventListener("click",e=>{
        e.stopPropagation();
        squad=squad.filter(i=>i!==+b.dataset.rm);
        save();renderSquad();render();
      }));
  }
}

// --- transfer suggestions --------------------------------------------------
// Both research passes ranked this the feature users name when explaining why
// they pay. It is a one-transfer search: for every player owned, every
// affordable replacement in the same position, ranked by the gain over the
// projection horizon rather than over this week alone - because a transfer you
// make now you live with for weeks.
//
// The risk profile is copied deliberately from Hub's "Optimised Manager
// Profile". It converts "the model is wrong" into "the model is mis-tuned",
// which is a conversation you can win.
const PROFILES={
  safe:   {label:"Safer",   minStart:85, penalise:1.4},
  bal:    {label:"Balanced",minStart:65, penalise:0.7},
  bold:   {label:"Bolder",  minStart:40, penalise:0.0}
};
let profile="bal";

function suggestions(members){
  const owned=new Set(members.map(d=>d.i));
  const spent=members.reduce((s,d)=>s+d.c,0);
  const bank=BUDGET-spent;
  const clubs={}; members.forEach(d=>{clubs[d.t]=(clubs[d.t]||0)+1;});
  const P=PROFILES[profile];
  // Penalise only the player coming IN. Applying it to the player going out
  // too meant a risk-averse profile INFLATED the advertised gain - bench fodder
  // always has the lower start%, so Safer showed +15.9 where the true
  // six-gameweek gain was +12.9. Risk aversion must discount, never flatter.
  const score=d=>d.tot;
  const risk=d=>(P.penalise*(100-d.ps)/100)*NG;

  const out=[];
  for(const o of members){
    for(const c of DATA){
      if(owned.has(c.i)||c.p!==o.p) continue;
      if(c.ps<P.minStart) continue;
      if(c.c>o.c+bank+1e-9) continue;                     // affordable
      // 3-per-club still has to hold after the swap
      if(c.t!==o.t&&(clubs[c.t]||0)>=MAX_PER_CLUB) continue;
      const gain=(score(c)-risk(c))-score(o);
      if(gain>0) out.push({o,c,gain,cost:c.c-o.c});
    }
  }
  out.sort((a,b)=>b.gain-a.gain);
  // Distinct on BOTH sides. Deduping only on the player sold produced five
  // different ways to buy the same striker, which is one decision presented as
  // five - the sort of thing that makes a tool feel like it is padding.
  const soldSeen=new Set(), boughtSeen=new Set(), top=[];
  for(const s of out){
    if(soldSeen.has(s.o.i)||boughtSeen.has(s.c.i)) continue;
    soldSeen.add(s.o.i); boughtSeen.add(s.c.i); top.push(s);
    if(top.length===5) break;
  }
  return {top,bank};
}

function renderSuggestions(members){
  const el=document.getElementById("sq-tx");
  if(members.length<11){ el.innerHTML=""; return; }
  const {top,bank}=suggestions(members);
  el.innerHTML='<div class="line">Transfers &middot; '+PROFILES[profile].label+
    ' &middot; bank \u00A3'+bank.toFixed(1)+'m</div>'+
    '<div class="seg tx" role="group" aria-label="Risk profile">'+
    Object.entries(PROFILES).map(([k,v])=>
      '<button data-prof="'+k+'" aria-pressed="'+(k===profile)+'">'+
      v.label+'</button>').join("")+'</div>'+
    (top.length?top.map(s=>
      '<div class="tx-row"><span class="out">'+esc(s.o.n)+'</span>'+
      '<span class="arw">\u2192</span><span class="in">'+esc(s.c.n)+'</span>'+
      '<span class="gain">+'+s.gain.toFixed(1)+'</span>'+
      '<span class="cost">'+(Math.abs(s.cost)<0.05?"":(s.cost>0?"\u2212":"+"))+
      '\u00A3'+Math.abs(s.cost).toFixed(1)+'m</span></div>').join("")
      : '<p class="hint">No transfer improves this squad under the '+
        PROFILES[profile].label.toLowerCase()+' profile.</p>')+
    '<p class="hint">Gain is projected points over '+NG+' gameweeks, risk-adjusted. '+
    'Assumes selling price equals current price.</p>';
  el.querySelectorAll("button[data-prof]").forEach(b=>
    b.addEventListener("click",e=>{
      e.stopPropagation(); profile=b.dataset.prof; renderSquad();
    }));
}

const MAX_SQUAD=15;
function toggle(id){
  if(!squad.includes(id) && squad.length>=MAX_SQUAD){
    // Refuse rather than accept and then report "-1 more to a full squad."
    const el=document.getElementById("sq-tx");
    if(el) el.insertAdjacentHTML("afterbegin",
      '<p class="warn" id="sq-full">Squad is full at 15. Remove a player first.</p>');
    setTimeout(()=>{const w=document.getElementById("sq-full"); if(w) w.remove();},2600);
    return;
  }
  squad = squad.includes(id) ? squad.filter(i=>i!==id) : squad.concat([id]);
  save();renderSquad();render();
}
function save(){try{localStorage.setItem("fpl.squad",JSON.stringify(squad));}catch(e){}}
function load(){
  // Shape, not just parseability. A stored object rather than an array threw
  // "squad.includes is not a function" on every load thereafter, leaving a page
  // that drew its nav, filters and header with zero rows and a counter still
  // reading "162 of 468 players" - and no in-app way to recover.
  try{
    const raw=JSON.parse(localStorage.getItem("fpl.squad")||"[]");
    squad=Array.isArray(raw)?raw.filter(x=>typeof x==="number"&&byId[x]):[];
  }catch(e){squad=[];}
}

document.addEventListener("DOMContentLoaded",()=>{
  load();
  const thead=document.getElementById("th");
  thead.innerHTML=COLS.map(([k,label,sub,num])=>
    '<th data-k="'+k+'" class="'+(num?"num":"")+'" tabindex="0">'+label+
    (sub?'<span class="sub">'+sub+'</span>':"")+'</th>').join("");
  // The sort arrow goes in its own element. Setting textContent here used to
  // flatten the heading and the small line under it into one text node, so the
  // first sort turned "Points / expected this week" into "Pointsexpected this
  // week" - and it happened on load, before anyone clicked anything.
  const mark=k=>{
    thead.querySelectorAll("th").forEach(o=>{
      o.removeAttribute("aria-sort");
      let a=o.querySelector(".arw");
      if(!a){a=document.createElement("span");a.className="arw";
             o.insertBefore(a,o.firstChild.nextSibling||null);}
      a.textContent = o.dataset.k===k
        ? (sortDir===1?" \u25b2":" \u25bc") : "";
    });
    const cur=thead.querySelector('th[data-k="'+k+'"]');
    if(cur) cur.setAttribute("aria-sort",sortDir===1?"ascending":"descending");
  };
  thead.querySelectorAll("th").forEach(th=>{
    const go=()=>{
      const k=th.dataset.k;
      // Numbers are more useful high-to-low on first click; names are not.
      sortDir = (sortKey===k) ? -sortDir : (k==="n"||k==="t"||k==="p" ? 1 : -1);
      sortKey=k;
      mark(sortKey);
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
  mark(sortKey);          // the table IS sorted on load; say so
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
        made_s = "locked in {}".format(words.horizon(made))
    else:
        made_s = "built pre-deadline"

    body = """<div class="wrap">
{nav}
<header>
  <h1>Gameweek {gw} projections</h1>
  <p class="sub">How many points we think every player will score this week,
  and over the next {ng}. Tap any column heading to sort by it.</p>
  <p class="sub" style="font-size:.78rem;color:var(--ink-3)">Deadline {dl} UTC
  &middot; {made} &middot; data fingerprint <code>{snap}</code> &middot;
  <a href="{scorecard}" style="color:var(--accent)">how accurate we have
  been</a></p>
</header>

<div class="controls">
  <div class="seg" role="group" aria-label="Filter by position">
    <button data-pos="ALL" aria-pressed="true">Everyone</button>
    <button data-pos="GKP" aria-pressed="false">Keepers</button>
    <button data-pos="DEF" aria-pressed="false">Defenders</button>
    <button data-pos="MID" aria-pressed="false">Midfielders</button>
    <button data-pos="FWD" aria-pressed="false">Forwards</button>
  </div>
  <input type="search" id="q" placeholder="Search player" aria-label="Search player">
  <select id="team" aria-label="Filter by team">
    <option value="ALL">All teams</option>
    {teamopts}
  </select>
  <label class="chk"><input type="checkbox" id="elig" checked>
    Hide fringe players</label>
  <span class="count" id="count"></span>
</div>

{glossary}

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
      <div><span class="k">Best eleven scores</span><span class="v" id="sq-xp">&mdash;</span></div>
      <div><span class="k">Formation</span><span class="v" id="sq-shape">&mdash;</span></div>
    </div>
    <div id="sq-list"></div>
    <div id="sq-tx"></div>
  </aside>
</div>

<footer>Generated {now} UTC &middot; every projection is timestamped and
reproducible from its snapshot &mdash; <a href="{scorecard}" style="color:var(--accent)">see how accurate these have actually been</a></footer>
</div>
<script>const DATA={data};{js}</script>""".format(
        js=JS, data=json.dumps(data, separators=(",", ":")),
        scorecard=links.href("scorecard"), nav=links.nav("projections"),
        gw=gw, dl=dl, made=made_s, ng=len(data[0]["g"]) if data else 6,
        glossary=words.glossary_html(),
        snap=(meta.get("snapshot_sha256", {}).get("bootstrap.json", "")[:12]),
        teamopts="\n    ".join(
            '<option value="{0}">{0}</option>'.format(t) for t in teams),
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    return links.document("FPL projections", body, CSS)


def _payload(html):
    """The page minus its volatile fields, for change detection.

    Comparing whole pages was wrong: the header shows a generated-at stamp AND
    the snapshot digest, and FPL's bootstrap response changes every hour on
    fields the model never reads (transfer counts, ownership percentages). So
    the digest moved hourly while not a single projected point did, and the
    scheduled job committed 46 times in three days with zero real change.

    What a reader cares about is whether any projection moved. Compare that.
    """
    # Mask only the genuinely volatile bits. Comparing just the data payload
    # was too narrow: a template or navigation change never altered it, so the
    # page silently refused to republish and the new nav link never shipped.
    out = re.sub(r"Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", "", html)
    out = re.sub(r"snapshot <code>[0-9a-f]+</code>", "snapshot", out)
    out = re.sub(r"snapshot [0-9a-f]{8,}", "snapshot", out)
    return out


def lint_page(html):
    """Whole-page checks that apply to every builder, JS or not.

    A raw UTF-8 character in HTML text renders as mojibake over plain HTTP just
    as surely as one in a script, and the scorecard has no script for lint_js
    to inspect. Pages must be ASCII; use entities.
    """
    bad = sorted(set(c for c in html if ord(c) > 127))
    return ["non-ASCII in page: {} - use HTML entities".format(" ".join(bad))] if bad else []


# Browser and language builtins the generated pages use. Anything called that
# is neither defined in the page nor listed here is almost certainly a typo or
# a half-applied edit.
JS_GLOBALS = frozenset("""
if for while switch catch return typeof function Math JSON Object Array String
Number Boolean Set Map Date RegExp parseInt parseFloat isNaN setTimeout
setInterval clearTimeout encodeURIComponent decodeURIComponent localStorage
document window console fetch alert confirm prompt requestAnimationFrame
navigator location history structuredClone
""".split())


def _strip_strings(js):
    """Blank out string literals and comments, preserving length.

    Comments have to be handled here, not skipped later: an apostrophe in an
    ordinary English comment - "FPL's own data" - otherwise opens a string that
    never closes, and every line after it is treated as quoted. That silently
    blinded the whole check while still reporting confident-looking failures.
    """
    out, i, n = [], 0, len(js)
    quote = None
    while i < n:
        ch = js[i]
        nxt = js[i + 1] if i + 1 < n else ""
        if quote:
            if ch == "\\":
                out.append("  ")
                i += 2
                continue
            out.append(ch if ch == quote else " ")
            if ch == quote:
                quote = None
            i += 1
        elif ch == "/" and nxt == "/":
            j = js.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif ch == "/" and nxt == "*":
            j = js.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " * (j - i))
            i = j
        elif ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def lint_js(html, required=("#tb", "DOMContentLoaded")):
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
    for needed in required:
        if needed not in js and needed.lstrip("#") not in js:
            problems.append("missing expected reference: {}".format(needed))

    # Two runtime failures that a syntax check cannot see, both of which have
    # shipped: a function called but never defined (an edit that inserted the
    # call sites and silently missed the definitions), and getElementById on an
    # id the markup does not contain. Either throws inside DOMContentLoaded, and
    # everything registered after the throw never runs - so the page draws its
    # shell and nothing else, which is indistinguishable from "no data yet".
    # String literals are blanked first. Without that, `hsl(` inside a CSS
    # colour string reads as a call to an undefined function, and every such
    # false positive trains you to ignore the linter.
    bare = _strip_strings(js)
    defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", bare))
    defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", bare))
    defined |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*=\s*(?:function|\()", bare))
    # Parameters count as defined. A callback passed in and then invoked -
    # `const row=(label,fn)=>...fn(w)` - is not an undefined function, and
    # without this the check reports one on every page that takes a callback.
    for params in re.findall(r"function\s*[\w$]*\s*\(([^)]*)\)", bare):
        defined |= set(re.findall(r"[A-Za-z_$][\w$]*", params))
    for params in re.findall(r"\(([^()]*)\)\s*=>", bare):
        defined |= set(re.findall(r"[A-Za-z_$][\w$]*", params))
    defined |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*=>", bare))
    for name in sorted(set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", bare))):
        if name in defined or name in JS_GLOBALS:
            continue
        problems.append("calls {}() which is never defined in this page".format(name))

    # Ids are matched against the whole document, not just the static markup:
    # a page may legitimately create an element and then look it up.
    for el in sorted(set(re.findall(r"getElementById\(\"([^\"]+)\"\)", js))):
        if 'id="{}"'.format(el) not in html:
            problems.append("getElementById({!r}) but nothing in the page ever "
                            "carries that id".format(el))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(OUT, "projections.html"))
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--prior", default="2025-26")
    args = ap.parse_args()

    rows, meta, source = latest_projection(args.prior)
    html = build(rows, meta, source)
    problems = lint_js(html, ("#tb", "#th", "sq-n", "DOMContentLoaded"))
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
