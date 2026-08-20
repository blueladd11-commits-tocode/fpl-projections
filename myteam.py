#!/usr/bin/env python3
"""My Team - the squad you actually field, on a pitch.

The projections page has a squad sidebar, and it was never enough. A 15-man
squad is not a list: it is eleven players in a shape, four on a bench in a
priority order, and one armband that doubles someone's score. Those are the
decisions FPL managers actually make, and none of them are expressible in a
column of names.

Shares localStorage key `fpl.squad` with web.py on purpose - a squad built while
browsing projections is already here when you arrive, and vice versa. The
captain and bench order live alongside it under their own keys.

Usage: python3 myteam.py [--out out/myteam.html] [--open]
"""

import argparse
import json
import os
import subprocess
import sys

import links
import project as P
import rating
import ticker
import web

# kits.py renders the club shirts. It is built separately, so the page must
# still come up without it rather than taking the hourly build down with it.
try:
    import kits
except ImportError:      # pragma: no cover - only until kits.py lands
    kits = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


# The page's own styles, kept separate from what it inherits so the
# collision check below can compare the two.
OWN_CSS = """
/* minmax(0,...) on every track, not 1fr. A bare 1fr is minmax(auto,1fr), and
   that auto minimum is the grid item min-content - which for a wrapping flex
   row of player cards Chrome resolves to something enormous. The track grew to
   10425px inside a 637px container and the pitch, which clips its overflow,
   rendered as an empty green box with all fifteen cards centred 5000px off to
   the right. */
.cols{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(0,1fr);
  gap:1.1rem;align-items:start}
.cols>*{min-width:0}
@media (max-width:64rem){.cols{grid-template-columns:minmax(0,1fr)}}

/* The pitch. Drawn in CSS, not photographed: an image would be the only
   external asset on the whole site, and a gradient reproduces the mown stripes
   that make a pitch read as a pitch at a fraction of the bytes.

   Green stays green in both themes. A pitch that turns charcoal in dark mode
   stops being a pitch, and this is the one surface on the site where the real
   world already decided what colour it is. */
.pitch{position:relative;overflow:hidden;border-radius:6px 6px 0 0;
  border:1px solid var(--line);border-bottom:0;padding:1.6rem .6rem .8rem;
  background:
    /* mown stripes, then the field itself */
    repeating-linear-gradient(180deg,
      rgba(255,255,255,.045) 0 44px, rgba(0,0,0,.045) 44px 88px),
    linear-gradient(178deg,#1E7A3E 0%,#186B36 55%,#13592D 100%)}
:root[data-theme="light"] .pitch,
:root:not([data-theme="dark"]) .pitch{background:
    repeating-linear-gradient(180deg,
      rgba(255,255,255,.07) 0 44px, rgba(0,0,0,.04) 44px 88px),
    linear-gradient(178deg,#2E9B52 0%,#248A46 55%,#1C7539 100%)}

/* Markings are an SVG overlay, not stacked CSS gradients. The gradient version
   drew the penalty area as a set of full-width bands that read as a grid laid
   over the grass rather than as a box. An SVG says what it means, scales with
   the pitch, and costs about three hundred bytes. */
.marks{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;
  z-index:0}
.marks *{fill:none;stroke:rgba(255,255,255,.42);stroke-width:2}

.players{position:relative;z-index:1}
.pline{display:flex;justify-content:center;gap:.45rem;flex-wrap:wrap;
  margin-bottom:1rem;position:relative;z-index:1}

/* The player card, shaped the way the FPL app shapes it: shirt on top, a dark
   name plate, and a lighter plate under it carrying the number. The two plates
   are what make a row of these read as a team sheet rather than as a grid of
   buttons. */
.pl{width:7.1rem;cursor:pointer;position:relative;text-align:center;
  background:none;border:0;padding:0}
.pl .kit{display:block;margin:0 auto .2rem;width:2.9rem;height:2.9rem}

.pl:focus-visible{outline:2px solid #fff;outline-offset:3px;border-radius:4px}

/* Doubt is worth more than precision here: an amber flag on a player who then
   plays costs less than a confident one who turns out to be injured. */
.pl.doubt .plate .nm{background:#FFE9C2}
.pl.out .plate .nm{background:#FFD2CC}


.arm{position:absolute;top:-.2rem;right:.35rem;width:1.1rem;height:1.1rem;
  border-radius:50%;font-family:var(--mono);font-size:.58rem;font-weight:700;
  display:flex;align-items:center;justify-content:center;z-index:2;
  background:#fff;color:#0B0F13;border:1px solid rgba(0,0,0,.3)}
.pl.cap .arm{background:var(--accent);color:#0B0F13}
.pl.vice .arm{background:#0B0F13;color:#fff}

/* The bench sits off the grass, the way it does in the app. */
.bench{background:var(--panel);border:1px solid var(--line);border-top:0;
  border-radius:0 0 6px 6px;padding:.7rem .5rem .4rem}
.bench .lbl{font-family:var(--mono);font-size:.58rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:.5rem;
  display:flex;justify-content:space-between;padding:0 .3rem}
.bench .pline{margin-bottom:.3rem}

.bo{position:absolute;top:-.2rem;left:.35rem;width:1.1rem;height:1.1rem;
  border-radius:50%;font-family:var(--mono);font-size:.56rem;z-index:2;
  display:flex;align-items:center;justify-content:center;
  background:var(--ground);border:1px solid var(--line);color:var(--ink-2)}

/* Drafts. A tab strip, because the question people actually have is "which of
   my two teams scores more", and that is only answerable side by side. */
.drafts{display:flex;align-items:stretch;gap:.25rem;flex-wrap:wrap;
  margin-bottom:.7rem}
.drafts button{font-family:var(--mono);font-size:.66rem;padding:.4rem .7rem;
  background:var(--panel);border:1px solid var(--line);color:var(--ink-2);
  cursor:pointer;border-radius:3px;display:flex;align-items:center;gap:.4rem}
.drafts button:hover{color:var(--ink);border-color:var(--ink-3)}
.drafts button.on{background:var(--accent);color:var(--ground);
  border-color:var(--accent);font-weight:700}
.drafts button .pts{font-variant-numeric:tabular-nums;opacity:.75;
  font-size:.62rem}
.drafts button.on .pts{opacity:.9}
.drafts .add{color:var(--accent);border-style:dashed}
/* .teambar, not .bar: web.CSS owns .bar for the points meter on the
   projections table - 7px tall with an accent fill - which is exactly the
   stray teal strip this row sprouted, plus a 7px-tall container its children
   overflowed. Same collision as .pick, same lesson. */
.teambar{display:flex;justify-content:space-between;align-items:center;
  gap:.6rem;flex-wrap:wrap;margin-bottom:.6rem}
.teambar .drafts{margin-bottom:0}
.dtools{display:flex;gap:.35rem;flex-wrap:wrap}
.dtools button{font-family:var(--mono);font-size:.6rem;letter-spacing:.05em;
  text-transform:uppercase;padding:.3rem .55rem;background:none;
  border:1px solid var(--line);color:var(--ink-3);cursor:pointer;border-radius:3px}
.dtools button:hover{color:var(--ink);border-color:var(--ink-3)}
.dtools .danger:hover{color:var(--loss);border-color:var(--loss)}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(6.2rem,1fr));
  gap:.5rem;margin-bottom:.9rem}
.tiles div{background:var(--panel);border:1px solid var(--line);padding:.5rem .6rem}
.tiles .k{font-family:var(--mono);font-size:.56rem;letter-spacing:.11em;
  text-transform:uppercase;color:var(--ink-3)}
.tiles .v{font-family:var(--mono);font-size:1.15rem;color:var(--ink);
  font-variant-numeric:tabular-nums;margin-top:.1rem}
.tiles .v.bad{color:var(--loss)}
.tiles .v.good{color:var(--accent)}
.tiles .hero{border-color:var(--accent);background:var(--accent-soft)}
.tiles .hero .k{color:var(--accent)}
.tiles .hero .v{font-size:1.7rem;color:var(--accent);font-weight:700}
.tiles .v small{display:block;font-size:.58rem;color:var(--ink-3);letter-spacing:.04em;
  text-transform:uppercase;margin-top:.15rem;font-weight:400}

/* The plate under the shirt, and the three fixture cells under that. This is
   the anatomy every serious FPL tool converges on, because it answers "who,
   for how much, against whom" without a tap. */
.pl .plate{display:flex;align-items:stretch;border-radius:3px 3px 0 0;
  overflow:hidden;font-size:.68rem;line-height:1.55}
.pl .plate .nm{flex:1;background:#fff;color:#12171C;font-weight:700;
  padding:.12rem .28rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  text-align:left}
.pl .plate .pr{background:#EDEFF1;color:#454F58;font-family:var(--mono);
  padding:.1rem .28rem;font-size:.58rem}
.pl .fcs{display:flex;border-radius:0 0 3px 3px;overflow:hidden}
.pl .fc{flex:1;min-width:0;display:flex;flex-direction:column;
  padding:.08rem .1rem;font-family:var(--mono);color:#12171C}
.pl .fc b{font-size:.68rem;font-weight:700;font-variant-numeric:tabular-nums}
.pl .fc i{font-size:.5rem;font-style:normal;opacity:.72;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.pl .fc.blank{background:#D3D8DC;color:#5E6873}
.pl.sel .plate .nm{background:var(--accent);color:#0B0F13}
.tiles .v small{font-size:.6rem;color:var(--ink-3);letter-spacing:0}

.side{background:var(--panel);border:1px solid var(--line);padding:.85rem .9rem}
.side h2{font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 .55rem;font-weight:600}
.need{display:flex;gap:.3rem;flex-wrap:wrap;margin-bottom:.6rem}
.need span{font-family:var(--mono);font-size:.62rem;padding:.16rem .42rem;
  border:1px solid var(--line);color:var(--ink-2)}
.need span.done{border-color:var(--accent);color:var(--accent)}
/* .roster, not .pick: web.CSS already owns .pick for the
   projections page, and its display:flex flattened this list to a
   single horizontal row - 60 players rendered, 2 visible. */
.roster{max-height:23rem;overflow-y:auto;margin:.5rem -.3rem 0}
.roster button{display:flex;width:100%;align-items:center;gap:.45rem;
  background:none;border:0;border-bottom:1px solid var(--line);
  padding:.32rem .3rem;text-align:left;cursor:pointer;color:inherit;font:inherit}
.roster button:hover{background:var(--accent-soft)}
.roster button:disabled{opacity:.35;cursor:not-allowed}
.roster .n{flex:1;font-size:.79rem;color:var(--ink);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.roster .x{font-family:var(--mono);font-size:.68rem;color:var(--ink-2);
  font-variant-numeric:tabular-nums}
.msg{font-size:.78rem;color:var(--ink-2);margin:.5rem 0 0}
.msg.bad{color:var(--loss)}
.act{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.7rem}
.act button{font-family:var(--mono);font-size:.62rem;letter-spacing:.06em;
  text-transform:uppercase;padding:.36rem .6rem;background:var(--panel);
  border:1px solid var(--line);color:var(--ink-2);cursor:pointer}
.act button:hover{color:var(--ink);border-color:var(--ink-3)}
.act button.go{border-color:var(--accent);color:var(--accent)}
.note{font-size:.84rem;color:var(--ink-2);max-width:66ch}
.empty{text-align:center;padding:2.6rem 1rem;color:rgba(255,255,255,.85);
  font-size:.9rem}
.bigbuild{font-family:var(--mono);font-size:.8rem;letter-spacing:.05em;
  text-transform:uppercase;padding:.7rem 1.3rem;background:var(--accent);
  color:#0B0F13;border:0;border-radius:4px;cursor:pointer;font-weight:700}
.bigbuild:hover{filter:brightness(1.08)}

/* A five-man defensive line has to fit on one row on a phone or the pitch stops
   reading as a pitch. 343px of pitch, less padding and four gaps, leaves about
   60px a card - which is what sets the card width here, not taste. */
@media (max-width:30rem){
  /* Three fixture cells inside a 60px card gives each one 20px, which cannot
     hold "TOT (H)". On a phone the next game is the one that matters; the other
     two are still a tap away on the projections page. */
  .pl .fc:nth-child(n+2){display:none}
  .pl .fc i{font-size:.46rem}
  /* Five defenders across a 375px screen leaves 61px a card after padding and
     gaps. 4.15rem is 66px, which is why the five-man line was wrapping - the
     card width here is arithmetic, not taste. */
  .pl{width:3.8rem;padding:0}
  .pl .kit{width:1.9rem;height:1.9rem;margin-bottom:.12rem}
  .pl .plate{font-size:.56rem}
  .pl .plate .pr{display:none}
  .pline{gap:.25rem}
}
@media (max-width:26rem){
  .pitch{padding:.7rem .35rem 0}
  .pline{gap:.25rem;margin-bottom:.6rem}
  .pl .nm{font-size:.61rem}
  .pl .mt{font-size:.54rem}
  .pl .fx{font-size:.5rem}
  .arm,.bo{width:.9rem;height:.9rem;font-size:.5rem}
}
.imp{background:var(--panel);border:1px solid var(--line);padding:.85rem .9rem;
  margin-bottom:.9rem}
.imp[hidden]{display:none}
.imp ol{margin:.4rem 0 .6rem;padding-left:1.1rem;font-size:.8rem;color:var(--ink-2)}
.imp li{margin:.25rem 0}
.imp input[type=text]{width:8rem}
.imp textarea{width:100%;height:4.5rem;font-family:var(--mono);font-size:.7rem;
  background:var(--ground);color:var(--ink);border:1px solid var(--line);padding:.4rem}
.imp a{color:var(--accent)}
"""

CSS = web.CSS + (kits.CSS if kits else "") + OWN_CSS


JS = r"""
const LIMITS={GKP:2,DEF:5,MID:5,FWD:3}, BUDGET=100.0, MAX_PER_CLUB=3;
const ORDER=["GKP","DEF","MID","FWD"];
// The position codes are storage keys. These are what a person reads.
const POS_WORD={GKP:"Keepers",DEF:"Defenders",MID:"Midfielders",FWD:"Forwards"};
const POS_ONE={GKP:"Keeper",DEF:"Def",MID:"Mid",FWD:"Fwd"};
// FPL allows any shape with 1 GK, at least 3 DEF and at least 1 FWD.
// The eight legal shapes. [3,3,4] is not among them: it needs four forwards
// and the squad may only hold three.
const SHAPES=[[3,4,3],[3,5,2],[4,3,3],[4,4,2],[4,5,1],[5,3,2],[5,4,1],[5,2,3]];
const byId=Object.fromEntries(DATA.map(d=>[d.i,d]));

let squad=[], cap=null, vice=null, bench=[], sel=null, q="", npos="ALL";

function esc(s){return String(s).replace(/[&<>\x22]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\x22":"&quot;"}[c]));}
const FOLD={"\u00F8":"o","\u0142":"l","\u0111":"d","\u0131":"i","\u00DF":"ss",
  "\u00E6":"ae","\u0153":"oe","\u00F0":"d","\u00FE":"th"};
function norm(s){return s.toLowerCase().replace(/[\u00E0-\u017F]/g,c=>FOLD[c]||c)
  .normalize("NFD").replace(/[\u0300-\u036F]/g,"");}

/* ---- drafts and state -------------------------------------------------- */
// A draft is a whole team: fifteen players, who is benched and in what order,
// and the armbands. People do not compare players in the abstract, they compare
// TEAMS - "do I go Salah and a cheap defence, or spread it" - and that question
// is only answerable with both teams in front of you.
//
// The ACTIVE draft is mirrored into the old fpl.squad / fpl.cap / fpl.vice /
// fpl.bench keys on every save. Those are what the projections page and the
// planner read, and they predate drafts; keeping them in step means switching
// draft here switches what those pages show, and a squad built over there still
// lands in the draft you are looking at.
let drafts=[], active=0;

function blankDraft(name){
  return {name:name||"Draft 1", squad:[], bench:[], cap:null, vice:null};
}
function cur(){return drafts[active]||blankDraft();}

// Everything below reads these, so they stay as plain top-level bindings and
// are simply re-pointed at the active draft. Rewriting every reference to
// cur().squad would have touched a hundred lines of verified logic for no gain.
function bind(){
  const d=cur();
  squad=d.squad; bench=d.bench; cap=d.cap; vice=d.vice;
}
function commit(){
  const d=cur();
  d.squad=squad; d.bench=bench; d.cap=cap; d.vice=vice;
}

function cleanDraft(raw, fallbackName){
  // Shape, not just parseability. A stored object where an array belonged once
  // threw on every subsequent load, with no in-app way to recover.
  const o = (raw && typeof raw==="object") ? raw : {};
  const sq = Array.isArray(o.squad)
    ? o.squad.filter(x=>typeof x==="number"&&byId[x]) : [];
  const bn = Array.isArray(o.bench)
    ? o.bench.filter(x=>typeof x==="number"&&sq.includes(x)) : [];
  const cp = (typeof o.cap==="number"&&sq.includes(o.cap))?o.cap:null;
  const vc = (typeof o.vice==="number"&&sq.includes(o.vice)&&o.vice!==cp)
    ? o.vice : null;
  const nm = (typeof o.name==="string"&&o.name.trim())
    ? o.name.trim().slice(0,24) : fallbackName;
  return {name:nm, squad:sq, bench:bn, cap:cp, vice:vc};
}

function load(){
  let stored=null;
  try{ stored=JSON.parse(localStorage.getItem("fpl.drafts.v1")||"null"); }
  catch(e){ stored=null; }

  if(stored && Array.isArray(stored.drafts) && stored.drafts.length){
    drafts=stored.drafts.map((d,i)=>cleanDraft(d,"Draft "+(i+1)));
    active=(typeof stored.active==="number" &&
            stored.active>=0 && stored.active<drafts.length) ? stored.active : 0;
    bind(); return;
  }

  // First run after drafts shipped: adopt whatever single squad already exists
  // rather than greeting a returning user with an empty pitch.
  let sq=[], bn=[], cp=null, vc=null;
  try{
    const raw=JSON.parse(localStorage.getItem("fpl.squad")||"[]");
    sq=Array.isArray(raw)?raw.filter(x=>typeof x==="number"&&byId[x]):[];
    const c=JSON.parse(localStorage.getItem("fpl.cap")||"null");
    cp=(typeof c==="number"&&sq.includes(c))?c:null;
    const v=JSON.parse(localStorage.getItem("fpl.vice")||"null");
    vc=(typeof v==="number"&&sq.includes(v)&&v!==cp)?v:null;
    const b=JSON.parse(localStorage.getItem("fpl.bench")||"[]");
    bn=Array.isArray(b)?b.filter(x=>typeof x==="number"&&sq.includes(x)):[];
  }catch(e){}
  drafts=[{name:"Draft 1", squad:sq, bench:bn, cap:cp, vice:vc}];
  active=0; bind();
}

function save(){
  commit();
  try{
    localStorage.setItem("fpl.drafts.v1",
      JSON.stringify({v:1, active:active, drafts:drafts}));
    // Mirror the active draft into the keys the other pages read.
    localStorage.setItem("fpl.squad",JSON.stringify(squad));
    localStorage.setItem("fpl.cap",JSON.stringify(cap));
    localStorage.setItem("fpl.vice",JSON.stringify(vice));
    localStorage.setItem("fpl.bench",JSON.stringify(bench));
  }catch(e){}
}

function draftPoints(d){
  // What a draft is worth, for the tab strip. Uses the same best-eleven and
  // captain rules as the pitch, so the number on the tab and the number above
  // the pitch can never disagree.
  const members=d.squad.map(i=>byId[i]).filter(Boolean);
  if(members.length<11) return null;
  const onBench=new Set(d.bench);
  let xi=d.squad.filter(i=>!onBench.has(i));
  if(!legalXI(xi)){
    const g=members.filter(x=>x.p==="GKP").sort((a,b)=>b.xp-a.xp);
    const dd=members.filter(x=>x.p==="DEF").sort((a,b)=>b.xp-a.xp);
    const mm=members.filter(x=>x.p==="MID").sort((a,b)=>b.xp-a.xp);
    const ff=members.filter(x=>x.p==="FWD").sort((a,b)=>b.xp-a.xp);
    let best=null;
    for(const [nd,nm,nf] of SHAPES){
      if(dd.length<nd||mm.length<nm||ff.length<nf||!g.length) continue;
      const t=[g[0],...dd.slice(0,nd),...mm.slice(0,nm),...ff.slice(0,nf)];
      const tot=t.reduce((s,x)=>s+x.xp,0);
      if(!best||tot>best.tot) best={t,tot};
    }
    if(!best) return null;
    xi=best.t.map(x=>x.i);
  }
  let tot=xi.reduce((s,i)=>s+(byId[i]?byId[i].xp:0),0);
  if(d.cap&&xi.includes(d.cap)) tot+=byId[d.cap].xp;
  return tot;
}

function switchTo(i){
  save();
  active=Math.max(0,Math.min(drafts.length-1,i));
  bind(); sel=null; save(); render();
}

/* ---- eleven ------------------------------------------------------------ */
function shapeOf(ids){
  const c={GKP:0,DEF:0,MID:0,FWD:0};
  ids.forEach(i=>{if(byId[i])c[byId[i].p]++;});
  return c;
}
function legalXI(ids){
  if(ids.length!==11) return false;
  const c=shapeOf(ids);
  if(c.GKP!==1) return false;
  return SHAPES.some(s=>s[0]===c.DEF&&s[1]===c.MID&&s[2]===c.FWD);
}
// The bench IS the state, not the eleven. Storing the eleven meant every added
// player silently joined the starting side and pushed someone out without
// saying so; storing who is benched leaves the eleven as whatever remains.
function starters(){return squad.filter(i=>!bench.includes(i));}

function autoBench(){
  const members=squad.map(i=>byId[i]).filter(Boolean);
  const g=members.filter(d=>d.p==="GKP").sort((a,b)=>b.xp-a.xp);
  const d=members.filter(d=>d.p==="DEF").sort((a,b)=>b.xp-a.xp);
  const m=members.filter(d=>d.p==="MID").sort((a,b)=>b.xp-a.xp);
  const f=members.filter(d=>d.p==="FWD").sort((a,b)=>b.xp-a.xp);
  if(!g.length) return false;
  let best=null;
  for(const [nd,nm,nf] of SHAPES){
    if(d.length<nd||m.length<nm||f.length<nf) continue;
    const xi=[g[0],...d.slice(0,nd),...m.slice(0,nm),...f.slice(0,nf)];
    const tot=xi.reduce((s,x)=>s+x.xp,0);
    if(!best||tot>best.tot) best={xi,tot};
  }
  if(!best) return false;
  const inXI=new Set(best.xi.map(d=>d.i));
  // Bench order matters: an outfield sub only comes on in the order you set,
  // so the highest-xP reserve goes first. The reserve keeper is never in that
  // queue - he can only replace the keeper.
  const rest=squad.filter(i=>!inXI.has(i)).map(i=>byId[i]).filter(Boolean);
  const gk=rest.filter(d=>d.p==="GKP").map(d=>d.i);
  const out=rest.filter(d=>d.p!=="GKP").sort((a,b)=>b.xp-a.xp).map(d=>d.i);
  bench=gk.concat(out);
  return true;
}

function swap(a,b){
  const onBench=bench.includes(a)?a:b, onPitch=bench.includes(a)?b:a;
  if(bench.includes(onPitch)||!bench.includes(onBench)) return "Pick one starter and one substitute.";
  const pa=byId[onPitch].p, pb=byId[onBench].p;
  // A keeper can only ever swap with the other keeper. Every other swap has to
  // leave a shape FPL would actually accept, which is why this checks the
  // resulting eleven rather than trusting position counts.
  if((pa==="GKP")!==(pb==="GKP")) return "A goalkeeper can only swap with the other goalkeeper.";
  const next=starters().filter(i=>i!==onPitch).concat([onBench]);
  if(!legalXI(next)) return "That leaves an illegal formation - FPL needs 3+ defenders and 1+ forward.";
  bench=bench.filter(i=>i!==onBench).concat([onPitch]);
  if(byId[onPitch].p!=="GKP"){
    const gk=bench.filter(i=>byId[i].p==="GKP");
    const out=bench.filter(i=>byId[i].p!=="GKP");
    bench=gk.concat(out);
  }
  return null;
}

/* ---- issues ------------------------------------------------------------ */
function issues(){
  const members=squad.map(i=>byId[i]).filter(Boolean);
  const out=[];
  const cost=members.reduce((s,d)=>s+d.c,0);
  if(cost>BUDGET) out.push("\u00A3"+(cost-BUDGET).toFixed(1)+"m over budget");
  for(const pos of ORDER){
    const n=members.filter(d=>d.p===pos).length;
    if(n>LIMITS[pos]) out.push(n+" "+pos+" (max "+LIMITS[pos]+")");
  }
  const clubs={};
  members.forEach(d=>{clubs[d.t]=(clubs[d.t]||0)+1;});
  for(const [t,n] of Object.entries(clubs))
    if(n>MAX_PER_CLUB) out.push(n+" from "+t+" (max "+MAX_PER_CLUB+")");
  return out;
}
function canAdd(d){
  if(squad.includes(d.i)) return "in squad";
  if(squad.length>=15) return "squad full";
  const members=squad.map(i=>byId[i]).filter(Boolean);
  if(members.filter(x=>x.p===d.p).length>=LIMITS[d.p]) return LIMITS[d.p]+" "+d.p+" already";
  if(members.filter(x=>x.t===d.t).length>=MAX_PER_CLUB) return "3 from "+d.t;
  // Budget is checked against what is still needed, not just the running total:
  // spending 99m on fourteen players leaves a legal squad you cannot complete.
  const spent=members.reduce((s,x)=>s+x.c,0);
  const after=spent+d.c;
  let floor=0;
  for(const pos of ORDER){
    const short=LIMITS[pos]-members.filter(x=>x.p===pos).length-(pos===d.p?1:0);
    if(short>0) floor+=short*CHEAP[pos];
  }
  if(after+floor>BUDGET+1e-9) return "no room in budget";
  return null;
}

/* ---- auto pick --------------------------------------------------------- */
// Greedy by value, then a repair pass. A true optimum is a knapsack problem and
// not worth solving in a page - but greedy alone reliably burns the budget on
// two premiums and fills the rest with players who will not start, so the
// second pass matters more than the first.
function autoFill(){
  const pool=DATA.filter(d=>d.e&&d.ps>=55).slice();
  const need={GKP:2,DEF:5,MID:5,FWD:3};
  squad.forEach(i=>{if(byId[i])need[byId[i].p]--;});
  const rank=pool.map(d=>[d, d.xp/Math.max(d.c,0.1)]).sort((a,b)=>b[1]-a[1]);
  for(const [d] of rank){
    if(squad.length>=15) break;
    if(need[d.p]<=0) continue;
    if(canAdd(d)) continue;
    squad.push(d.i); need[d.p]--;
  }
  for(let pass=0;pass<3;pass++){
    let moved=false;
    for(const id of squad.slice()){
      const cur=byId[id];
      const rest=squad.filter(i=>i!==id);
      const spent=rest.reduce((s,i)=>s+byId[i].c,0);
      let best=null;
      for(const d of pool){
        if(squad.includes(d.i)||d.p!==cur.p||d.xp<=cur.xp) continue;
        if(spent+d.c>BUDGET) continue;
        const clubN=rest.filter(i=>byId[i].t===d.t).length;
        if(clubN>=MAX_PER_CLUB) continue;
        if(!best||d.xp>best.xp) best=d;
      }
      if(best){squad=rest.concat([best.i]);moved=true;}
    }
    if(!moved) break;
  }
  bench=[];cap=null;vice=null;
  autoBench();
  if(!cap){
    const xi=starters().map(i=>byId[i]).sort((a,b)=>b.xp-a.xp);
    if(xi[0]) cap=xi[0].i;
    if(xi[1]) vice=xi[1].i;
  }
}

/* ---- import ------------------------------------------------------------ */
// FPL serves no CORS headers on any endpoint, so this page can never fetch a
// team itself. Four public CORS proxies were tested and all four are dead or
// paywalled, and routing someone else's team through a third party would
// contradict the promise this page makes anyway.
//
// The user's own browser, though, is same-origin with FPL and already signed
// in. So: open their picks in a tab, paste the result back. Two taps, no
// backend, nothing transmitted.
//
// The picks endpoint 404s until a deadline has passed, which means it is 404
// for everyone before the season starts. That is a normal answer here, not a
// failure, and the message says so rather than blaming the user.
function importUrl(){
  const id=(document.getElementById("tid").value||"").replace(/[^0-9]/g,"");
  return id ? "https://fantasy.premierleague.com/api/entry/"+id+"/event/"+GW+"/picks/"
            : "https://fantasy.premierleague.com/api/bootstrap-static/";
}
function applyPicks(text){
  // People paste with whatever the browser wrapped around it - selection
  // artifacts, a stray label, whitespace. Find the {...} inside rather than
  // demanding a surgically clean copy, and never say "JSON" to anyone.
  const a=text.indexOf("{"), b=text.lastIndexOf("}");
  let j=null;
  if(a>=0&&b>a){ try{ j=JSON.parse(text.slice(a,b+1)); }catch(e){} }
  if(!j) return "That does not look like the right page. Tap \u201Copen your "+
    "team\u201D above, then on that page select everything, copy, and paste "+
    "the lot here \u2014 it will look like code, and that is fine.";
  if(j.detail) return "FPL says your team is not available yet. Teams stay "+
    "hidden until the first deadline passes \u2014 after that this works. "+
    "Also worth checking the team number is this season\u2019s.";
  const picks=j.picks;
  if(!Array.isArray(picks)||!picks.length)
    return "That page did not contain a team. Use the \u201Copen your "+
    "team\u201D link above rather than the FPL homepage.";
  const known=picks.filter(p=>byId[p.element]);
  if(known.length<11) return "Only "+known.length+" of those players exist in "+
    "this season\u2019s game \u2014 that team number looks like last "+
    "season\u2019s. Grab the new one from your Points page.";
  // position 1-11 is the eleven, 12 the reserve keeper, 13-15 the sub order.
  const sorted=known.slice().sort((a,b)=>a.position-b.position);
  squad=sorted.map(p=>p.element);
  bench=sorted.filter(p=>p.position>11).map(p=>p.element);
  const c=known.find(p=>p.is_captain), v=known.find(p=>p.is_vice_captain);
  cap=c?c.element:null; vice=v?v.element:null;
  if(!legalXI(starters())) autoBench();
  return null;
}

/* ---- render ------------------------------------------------------------ */
// Green is a kind fixture, red a hard one, scaled to the spread actually
// present rather than to a fixed ramp - a fixed one never reaches either end.
const FDR_RANGE=(function(){
  const v=[];
  for(const t in FIX) for(const col of FIX[t]) for(const f of col) v.push(f[2]);
  return v.length?[Math.min.apply(null,v),Math.max.apply(null,v)]:[1,1];
})();
function fdr(v){
  const [lo,hi]=FDR_RANGE;
  const t=hi>lo?Math.max(0,Math.min(1,(v-lo)/(hi-lo))):0.5;
  return "hsl("+((1-t)*135).toFixed(0)+",58%,"+(76-t*12).toFixed(0)+"%)";
}

function fixtureCells(d){
  // One cell per gameweek: what we think he scores, and who against. This is
  // the row that turns a projection into a decision - 4.4 against the best
  // defence in the league is a different number from 4.4 at home to a promoted
  // side, and the opponent is what tells you which one you are looking at.
  const cols=FIX[d.t]||[];
  let out="";
  for(let k=0;k<GWS.length;k++){
    const col=cols[k]||[];
    const pts=(d.g&&d.g[k]!==undefined)?d.g[k]:null;
    if(!col.length){
      out+='<span class="fc blank"><b>&mdash;</b><i>no game</i></span>';
      continue;
    }
    const opp=col.map(c=>c[0]+(c[1]?" (H)":" (A)")).join(" + ");
    out+='<span class="fc" style="background:'+fdr(col[0][2])+'">'+
      '<b>'+(pts===null?"&mdash;":pts.toFixed(1))+'</b>'+
      '<i>'+esc(opp)+'</i></span>';
  }
  return out;
}

function card(id,onBench,pos){
  const d=byId[id];
  if(!d) return "";
  const cls=["pl"];
  if(sel===id) cls.push("sel");
  if(id===cap) cls.push("cap"); else if(id===vice) cls.push("vice");
  if(d.ps<55) cls.push("doubt");
  if(d.ps<25) cls.push("out");
  const arm=(id===cap?"C":(id===vice?"V":""));
  return '<button type="button" class="'+cls.join(" ")+'" data-id="'+id+'" '+
    'aria-label="'+esc(d.n)+', '+POS_ONE[d.p]+', '+d.t+
    (arm?", "+(arm==="C"?"captain":"vice-captain"):"")+'">'+
    (arm?'<span class="arm">'+arm+'</span>':"")+
    (onBench&&pos?'<span class="bo">'+pos+'</span>':"")+
    KIT(d.t)+
    '<span class="plate">'+
      '<span class="nm">'+esc(d.n)+'</span>'+
      '<span class="pr">\u00A3'+d.c.toFixed(1)+'</span>'+
    '</span>'+
    '<span class="fcs">'+fixtureCells(d)+'</span>'+
    '</button>';
}

/* ---- team rating ------------------------------------------------------- */
// One number for the whole squad, which is the question people actually ask -
// "is my team any good" - and the one a per-player rating cannot answer.
//
// Scored against what is ACHIEVABLE rather than against an absolute, because
// the ceiling moves: in a week of kind fixtures every decent squad projects
// higher, and a rating that drifted up with it would be measuring the week
// rather than the manager. So: where does this team sit between a competent
// cheap squad and the best squad the model can assemble for the same 100m.
let RATING_REF=null;

// The ceiling has to be a team you could actually field, not the best eleven
// names in the game. Built from the best legal 15 the budget allows - the same
// greedy-then-repair routine the Build me a squad button runs - because a
// ceiling nobody can reach makes every real squad look broken. The first
// version used the best eleven regardless of price and rated the model own
// optimal team 19 out of 100.
function optimalXIPoints(){
  const pool=DATA.filter(d=>d.e&&d.ps>=55);
  const need={GKP:2,DEF:5,MID:5,FWD:3};
  let sq=[];
  const cost=()=>sq.reduce((s,i)=>s+byId[i].c,0);
  const clubs=()=>{const c={};sq.forEach(i=>{c[byId[i].t]=(c[byId[i].t]||0)+1;});return c;};
  const rank=pool.map(d=>[d,d.xp/Math.max(d.c,0.1)]).sort((a,b)=>b[1]-a[1]);
  for(const [d] of rank){
    if(sq.length>=15) break;
    if(need[d.p]<=0||sq.includes(d.i)) continue;
    if((clubs()[d.t]||0)>=MAX_PER_CLUB) continue;
    let floorLeft=0;
    for(const p of ORDER){
      const short=need[p]-(p===d.p?1:0);
      if(short>0) floorLeft+=short*CHEAP[p];
    }
    if(cost()+d.c+floorLeft>BUDGET+1e-9) continue;
    sq.push(d.i); need[d.p]--;
  }
  for(let pass=0;pass<3;pass++){
    let moved=false;
    for(const id of sq.slice()){
      const c0=byId[id], rest=sq.filter(i=>i!==id);
      const spent=rest.reduce((s,i)=>s+byId[i].c,0);
      let best=null;
      for(const d of pool){
        if(sq.includes(d.i)||d.p!==c0.p||d.xp<=c0.xp) continue;
        if(spent+d.c>BUDGET) continue;
        if(rest.filter(i=>byId[i].t===d.t).length>=MAX_PER_CLUB) continue;
        if(!best||d.xp>best.xp) best=d;
      }
      if(best){sq=rest.concat([best.i]);moved=true;}
    }
    if(!moved) break;
  }
  const mem=sq.map(i=>byId[i]);
  const by=p=>mem.filter(x=>x.p===p).sort((a,b)=>b.xp-a.xp);
  const g=by("GKP"), d=by("DEF"), m=by("MID"), f=by("FWD");
  if(!g.length) return null;
  let best=null;
  for(const [nd,nm,nf] of SHAPES){
    if(d.length<nd||m.length<nm||f.length<nf) continue;
    const xi=[g[0]].concat(d.slice(0,nd),m.slice(0,nm),f.slice(0,nf));
    const tot=xi.reduce((s,x)=>s+x.xp,0)+
      xi.slice().sort((a,b)=>b.xp-a.xp)[0].xp;   // captained, like a real team
    if(!best||tot>best) best=tot;
  }
  return best;
}

function cheapestXIPoints(){
  // The did-no-thinking team: the cheapest players we still expect to start.
  const pool=DATA.filter(d=>d.e&&d.ps>=55);
  const by=p=>pool.filter(x=>x.p===p).slice().sort((a,b)=>a.c-b.c||b.xp-a.xp);
  const g=by("GKP"), d=by("DEF"), m=by("MID"), f=by("FWD");
  if(!g.length||d.length<5||m.length<5||f.length<3) return null;
  const xi=[g[0]].concat(d.slice(0,4),m.slice(0,4),f.slice(0,2));
  const tot=xi.reduce((s,x)=>s+x.xp,0);
  return tot+xi.slice().sort((a,b)=>b.xp-a.xp)[0].xp;
}

function ratingRef(){
  if(RATING_REF) return RATING_REF;
  RATING_REF={ceiling:optimalXIPoints(), floor:cheapestXIPoints()};
  return RATING_REF;
}

function teamRating(){
  const ref=ratingRef();
  if(!ref.ceiling||!ref.floor||ref.ceiling<=ref.floor) return null;
  const xi=starters();
  if(!legalXI(xi)) return null;
  let pts=xi.reduce((s,i)=>s+(byId[i]?byId[i].xp:0),0);
  // The armband is part of the team, so it is part of the rating. A squad with
  // the wrong captain IS a worse team, and hiding that would make the number
  // agree with itself while disagreeing with the scoreboard.
  if(cap&&xi.includes(cap)) pts+=byId[cap].xp;
  const t=(pts-ref.floor)/(ref.ceiling-ref.floor);
  return Math.max(1,Math.min(99,Math.round(t*100)));
}
function ratingWord(r){
  if(r===null) return "";
  if(r>=88) return "outstanding";
  if(r>=76) return "strong";
  if(r>=62) return "decent";
  if(r>=45) return "work to do";
  return "needs a rebuild";
}

function renderDrafts(){
  const bar=document.getElementById("drafts");
  bar.innerHTML=drafts.map((d,i)=>{
    const p=draftPoints(d);
    return '<button data-draft="'+i+'" class="'+(i===active?"on":"")+'">'+
      esc(d.name)+'<span class="pts">'+
      (p===null?d.squad.length+"/15":p.toFixed(1)+" pts")+'</span></button>';
  }).join("")+
  (drafts.length<6
    ? '<button class="add" id="dnew" title="Start another team">+ New draft</button>'
    : "");
}

function render(){
  commit();
  renderDrafts();
  const members=squad.map(i=>byId[i]).filter(Boolean);
  const xi=starters();
  const shape=shapeOf(xi);
  const problems=issues();

  const cost=members.reduce((s,d)=>s+d.c,0);
  const capD=byId[cap];
  const xiXp=xi.reduce((s,i)=>s+(byId[i]?byId[i].xp:0),0);
  const total=xiXp+(capD&&xi.includes(cap)?capD.xp:0);

  const tr=teamRating();
  const psrEl=document.getElementById("t-psr");
  psrEl.innerHTML=(tr===null?"&mdash;":tr)+
    '<small id="t-psrw">'+(tr===null?"pick a full eleven":ratingWord(tr))+'</small>';
  psrEl.className="v"+(tr!==null&&tr>=76?" good":"");

  // Four tiles, one thing each. Formation rides under the player count and
  // the spend under the money, because six boxes was two too many for a page
  // a first-timer has to read at a glance.
  const nEl=document.getElementById("t-n");
  nEl.innerHTML=members.length+'<small>'+
    (legalXI(xi)?("in a "+shape.DEF+"-"+shape.MID+"-"+shape.FWD):"of 15")+
    '</small>';
  nEl.className="v"+(members.length>15?" bad":"");
  const bankEl=document.getElementById("t-bank");
  bankEl.innerHTML="\u00A3"+(BUDGET-cost).toFixed(1)+
    'm<small>\u00A3'+cost.toFixed(1)+"m spent</small>";
  bankEl.className="v"+(cost>BUDGET?" bad":"");
  document.getElementById("t-xp").textContent=
    legalXI(xi)?total.toFixed(1):"\u2014";

  const pitch=document.getElementById("pitch");
  if(!members.length){
    pitch.innerHTML='<div class="empty">No team yet.<br><br>'+
      '<button class="bigbuild" type="button">Build me a squad</button>'+
      '<br><br>or add players from the list.</div>';
  }else{
    const rows=ORDER.map(pos=>{
      const ids=xi.filter(i=>byId[i].p===pos);
      if(!ids.length) return "";
      return '<div class="pline">'+ids
        .sort((a,b)=>byId[b].xp-byId[a].xp)
        .map(i=>card(i,false)).join("")+"</div>";
    }).join("");
    const bo=bench.map((i,n)=>card(i,true,byId[i].p==="GKP"?"G":String(n)));
    pitch.innerHTML=rows+
      (bench.length?'<div class="bench"><div class="lbl"><span>Bench</span>'+
        '<span>order matters</span></div><div class="pline">'+
        bo.join("")+"</div></div>":"");
  }

  const msg=document.getElementById("msg");
  msg.className=problems.length?"msg bad":"msg";
  msg.textContent=problems.length?("Illegal squad: "+problems.join("; ")):
    (members.length===15
      ? (legalXI(xi)?"Legal squad and a legal eleven."
                    :"15 picked. Tap Auto to set a valid eleven.")
      : (15-members.length)+" more to a full squad.");

  // The filter buttons double as the "what do I still need" display, which
  // saves a whole row: "Defenders 3/5" filters AND reports.
  document.querySelectorAll(".seg button").forEach(b=>{
    const p=b.dataset.pos;
    if(!POS_WORD[p]) return;
    const n=members.filter(d=>d.p===p).length;
    b.textContent=POS_WORD[p]+" "+n+"/"+LIMITS[p];
  });

  renderPick();
}

function renderPick(){
  const nq=norm(q);
  const list=DATA.filter(d=>{
    if(npos!=="ALL"&&d.p!==npos) return false;
    if(nq&&!norm(d.n).includes(nq)&&!norm(d.t).includes(nq)) return false;
    return true;
  }).slice(0,60);
  document.getElementById("pick").innerHTML=list.map(d=>{
    const why=canAdd(d);
    const inSquad=squad.includes(d.i);
    return '<button data-add="'+d.i+'"'+((why&&!inSquad)?" disabled":"")+
      ' title="'+esc(why||"add to squad")+'">'+
      KIT(d.t)+
      '<span class="n">'+esc(d.n)+'</span>'+
      '<span class="x">'+d.c.toFixed(1)+"</span>"+
      '<span class="x">'+d.xp.toFixed(2)+"</span>"+
      '<span class="x" style="width:2.6rem;text-align:right;opacity:.7">'+
      (inSquad?"in":(why?"\u2014":"+"))+"</span></button>";
  }).join("")||'<p class="msg">Nobody matches that search.</p>';
}

/* ---- events ------------------------------------------------------------ */
function flash(text){
  const m=document.getElementById("msg");
  m.className="msg bad";m.textContent=text;
  setTimeout(render,2400);
}

function tapPlayer(id){
  if(sel===null){sel=id;render();return;}
  if(sel===id){sel=null;render();return;}
  const err=swap(sel,id);
  sel=null;
  if(err){flash(err);return;}
  save();render();
}

document.addEventListener("DOMContentLoaded",()=>{
  load();
  if(squad.length&&!bench.length) autoBench();

  document.getElementById("pitch").addEventListener("click",e=>{
    if(e.target.closest(".bigbuild")){
      document.getElementById("fill").click();return;
    }
    const el=e.target.closest(".pl");
    if(el) tapPlayer(+el.dataset.id);
  });
  document.getElementById("pitch").addEventListener("keydown",e=>{
    const el=e.target.closest(".pl");
    if(!el) return;
    if(e.key==="Enter"||e.key===" "){e.preventDefault();tapPlayer(+el.dataset.id);}
    if(e.key==="c"||e.key==="C"){setCap(+el.dataset.id);}
    if(e.key==="v"||e.key==="V"){setVice(+el.dataset.id);}
  });
  document.getElementById("pitch").addEventListener("contextmenu",e=>{
    const el=e.target.closest(".pl");
    if(!el) return;
    e.preventDefault();setCap(+el.dataset.id);
  });

  document.getElementById("pick").addEventListener("click",e=>{
    const b=e.target.closest("button[data-add]");
    if(!b) return;
    const id=+b.dataset.add;
    if(squad.includes(id)){
      squad=squad.filter(i=>i!==id);
      bench=bench.filter(i=>i!==id);
      if(cap===id)cap=null; if(vice===id)vice=null;
    }else{
      const why=canAdd(byId[id]);
      if(why){flash("Cannot add "+byId[id].n+": "+why);return;}
      squad.push(id);
      // A new player lands on the bench rather than displacing a starter
      // silently. Auto is one tap away if you want the model to decide.
      bench.push(id);
    }
    save();render();
  });

  document.getElementById("q").addEventListener("input",e=>{
    q=e.target.value.trim();renderPick();
  });
  document.querySelectorAll(".seg button").forEach(b=>
    b.addEventListener("click",()=>{
      npos=b.dataset.pos;
      document.querySelectorAll(".seg button").forEach(o=>
        o.setAttribute("aria-pressed",o===b?"true":"false"));
      renderPick();
    }));

  document.getElementById("auto").addEventListener("click",()=>{
    if(!autoBench()){flash("Need a goalkeeper before an eleven can be set.");return;}
    const xi=starters().map(i=>byId[i]).sort((a,b)=>b.xp-a.xp);
    if(xi[0])cap=xi[0].i;
    if(xi[1])vice=xi[1].i;
    save();render();
  });
  document.getElementById("fill").addEventListener("click",()=>{
    autoFill();save();render();
  });
  document.getElementById("clear").addEventListener("click",()=>{
    squad.length=0;bench.length=0;cap=null;vice=null;sel=null;save();render();
  });

  document.getElementById("drafts").addEventListener("click",e=>{
    const t=e.target.closest("button");
    if(!t) return;
    if(t.id==="dnew"){
      save();
      drafts.push(blankDraft("Draft "+(drafts.length+1)));
      active=drafts.length-1; bind(); sel=null; save(); render();
      return;
    }
    if(t.dataset.draft!==undefined) switchTo(+t.dataset.draft);
  });
  document.getElementById("drename").addEventListener("click",()=>{
    const name=prompt("Name this draft", cur().name);
    if(name===null) return;
    cur().name=(name.trim()||cur().name).slice(0,24);
    save(); render();
  });
  document.getElementById("ddup").addEventListener("click",()=>{
    if(drafts.length>=6){flash("Six drafts is the limit.");return;}
    save();
    const c=cur();
    // Copy the arrays, do not share them - two tabs pointing at one array is a
    // duplicate that edits its own original.
    drafts.push({name:(c.name+" copy").slice(0,24), squad:c.squad.slice(),
                 bench:c.bench.slice(), cap:c.cap, vice:c.vice});
    active=drafts.length-1; bind(); save(); render();
  });
  document.getElementById("ddel").addEventListener("click",()=>{
    if(drafts.length<2){flash("This is your only draft.");return;}
    if(!confirm("Delete "+cur().name+"?")) return;
    drafts.splice(active,1);
    active=Math.max(0,active-1); bind(); sel=null; save(); render();
  });

  const panel=document.getElementById("imp");
  const link=document.getElementById("tlink");
  // Before the first deadline FPL returns nothing for ANY team, so showing
  // the paste flow would walk every new visitor into an error that is not
  // their fault. Say so instead, once, in words.
  document.getElementById("implocked").hidden=IMPORTABLE;
  document.getElementById("impform").hidden=!IMPORTABLE;
  document.getElementById("impbtn").addEventListener("click",()=>{
    panel.hidden=!panel.hidden;
    if(!panel.hidden&&IMPORTABLE) document.getElementById("tid").focus();
  });
  document.getElementById("noimp").addEventListener("click",()=>{panel.hidden=true;});
  document.getElementById("noimp2").addEventListener("click",()=>{panel.hidden=true;});
  document.getElementById("tid").addEventListener("input",()=>{
    link.href=importUrl();
  });
  link.href=importUrl();
  document.getElementById("doimp").addEventListener("click",()=>{
    const box=document.getElementById("paste");
    const m=document.getElementById("impmsg");
    const err=applyPicks(box.value||"");
    if(err){m.className="msg bad";m.textContent=err;return;}
    save();panel.hidden=true;box.value="";
    m.className="msg";m.textContent="";
    render();
  });

  render();
});

function setCap(id){
  if(!squad.includes(id)) return;
  if(vice===id) vice=cap;
  cap=id;save();render();
}
function setVice(id){
  if(!squad.includes(id)||id===cap) return;
  vice=id;save();render();
}
"""


def build(rows, gw, deadline, shorts, fix, gws):
    data = web.prepare(rows)
    # The shirts render client-side, so the markup has to cross into JS. One
    # string per club, looked up by short name - 20 entries, not 460 copies.
    sprite = kits.sprite() if kits else ""
    markup = {s: kits.shirt(s) for s in shorts} if kits else {}

    cheap = {}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        prices = [float(r["price"]) for r in rows if r["pos"] == pos]
        cheap[pos] = round(min(prices), 1) if prices else 4.0

    body = """<div class="wrap">
{nav}
<header>
  <h1>My team &mdash; gameweek {gw}</h1>
  <p class="note">Pick your fifteen, choose a captain, and see what they
  should score. Saved in this browser only &mdash; nothing is uploaded.</p>
  <details class="gloss" style="margin-top:.7rem;max-width:44rem">
    <summary>How this works</summary>
    <dl>
      <div><dt>Swap players</dt><dd>Tap a starter, then a substitute. We stop
        any swap the game would not allow.</dd></div>
      <div><dt>Captain</dt><dd>Right-click a player (or press <kbd>C</kbd>) to
        give him the armband and double his score. <kbd>V</kbd> for
        vice-captain.</dd></div>
      <div><dt>Drafts</dt><dd>Keep up to six different teams and flick between
        them &mdash; each tab shows what that team should score.</dd></div>
      <div><dt>Stuck?</dt><dd>Hit <em>Build me a squad</em> and we pick a full
        fifteen inside the budget for you.</dd></div>
    </dl>
  </details>
</header>

<section class="imp" id="imp" hidden aria-label="Bring in my FPL team">
  <div id="implocked" hidden>
    <p class="note"><strong>Not just yet.</strong> FPL keeps everyone&rsquo;s
    team hidden until the first deadline has passed, so there is nothing to
    bring in before then &mdash; for anyone. Build your team here in the
    meantime; from gameweek 2 this button pulls your real one in two taps.</p>
    <div class="act" style="margin:.6rem 0 0"><button id="noimp2">Okay</button></div>
  </div>
  <div id="impform">
    <ol>
      <li>Find your team number: open your <em>Points</em> page on the FPL
        site and it is the number in the web address. (It changes every
        season, so last year&rsquo;s will not work.)</li>
      <li>Team number <input type="text" id="tid" inputmode="numeric"
        placeholder="1234567" aria-label="FPL team number">
        then <a id="tlink" href="#" target="_blank" rel="noopener">open your
        team</a> &mdash; it opens on the official FPL site, where you are
        already signed in.</li>
      <li>On that page: select everything (<kbd>Ctrl</kbd>+<kbd>A</kbd> or
        <kbd>&#8984;</kbd>+<kbd>A</kbd>), copy, and paste it here:</li>
    </ol>
    <textarea id="paste" placeholder="Paste here — it will look like code. That is fine, we read it for you."
      aria-label="Paste your team page here"></textarea>
    <div class="act" style="margin:.6rem 0 0"><button id="doimp" class="go">Load
      this team</button><button id="noimp">Cancel</button></div>
    <p class="msg" id="impmsg">Nothing is uploaded. What you paste is read
      right here and never leaves your browser.</p>
  </div>
</section>

<div class="teambar">
  <div class="drafts" id="drafts" role="tablist" aria-label="Your teams"></div>
  <div class="dtools">
    <button id="drename">Rename</button>
    <button id="ddup">Copy</button>
    <button id="ddel" class="danger">Delete</button>
  </div>
</div>

<div class="act">
  <button id="fill" class="go">Build me a squad</button>
  <button id="impbtn">Bring in my FPL team</button>
  <button id="auto">Best eleven &amp; captain</button>
  <button id="clear">Start over</button>
</div>

<div class="tiles">
  <div class="hero"><div class="k">PS Rating</div>
    <div class="v" id="t-psr">&mdash;</div></div>
  <div><div class="k">Players</div><div class="v" id="t-n">0<small>/15</small></div></div>
  <div><div class="k">Money left</div><div class="v" id="t-bank">&pound;100.0m</div></div>
  <div><div class="k">Points this week</div><div class="v" id="t-xp">&mdash;</div></div>
</div>

<div class="cols">
  <div>
    <div class="pitch">
      <svg class="marks" viewBox="0 0 300 380" preserveAspectRatio="none"
        aria-hidden="true">
        <rect x="1" y="1" width="298" height="378"/>
        <rect x="90" y="1" width="120" height="52"/>
        <rect x="123" y="1" width="54" height="22"/>
        <path d="M117 53a40 40 0 0 0 66 0"/>
        <line x1="1" y1="379" x2="299" y2="379"/>
        <circle cx="150" cy="379" r="46"/>
      </svg>
      <div class="players" id="pitch"></div>
    </div>
    <p class="msg" id="msg"></p>
  </div>

  <aside class="side" aria-label="Add players">
    <h2>Add players</h2>
    <div class="controls" style="padding:0;border:0;background:none;margin:0">
      <div class="seg" role="group" aria-label="Position">
        <button data-pos="ALL" aria-pressed="true">All</button>
        <button data-pos="GKP" aria-pressed="false">Keepers</button>
        <button data-pos="DEF" aria-pressed="false">Defenders</button>
        <button data-pos="MID" aria-pressed="false">Midfielders</button>
        <button data-pos="FWD" aria-pressed="false">Forwards</button>
      </div>
    </div>
    <input type="search" id="q" placeholder="Search player or club"
      aria-label="Search player or club" style="width:100%;margin-top:.5rem">
    <div class="roster" id="pick"></div>
  </aside>
</div>

<footer>Deadline {deadline} &middot; projections rebuilt hourly &middot;
squad and captain stored locally in this browser &middot;
<a href="{fixtures}" style="color:var(--accent)">fixture difficulty</a></footer>
</div>
{sprite}
<script>const DATA={data};const CHEAP={cheap};const GW={gw};const KITS={kitmap};
const FIX={fix};const GWS={gws};const IMPORTABLE={importable};
function KIT(t){{return KITS[t]||"";}}{js}</script>""".format(
        nav=links.nav("myteam"), gw=gw, deadline=deadline,
        projections=links.href("projections"), fixtures=links.href("fixtures"),
        sprite=sprite, data=json.dumps(data, separators=(",", ":")),
        cheap=json.dumps(cheap),
        kitmap=json.dumps(markup, separators=(",", ":")),
        fix=json.dumps(fix, separators=(",", ":")),
        gws=json.dumps(gws, separators=(",", ":")),
        importable=("true" if gw > 1 else "false"), js=JS)
    return links.document("FPL my team", body, CSS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(OUT, "myteam.html"))
    ap.add_argument("--prior", default="2025-26")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    snap = P.latest_snapshot()
    manifest = json.load(open(os.path.join(snap, "manifest.json")))
    bootstrap = json.load(open(os.path.join(snap, "bootstrap.json")))
    shorts = sorted(t["short_name"] for t in bootstrap["teams"])
    fixtures = json.load(open(os.path.join(snap, "fixtures.json")))
    rows, _, _ = P.build(snap, args.prior, quiet=True)
    gw = manifest.get("next_gw") or 1
    deadline = (manifest.get("next_deadline") or "").replace("T", " ")[:16] + " UTC"

    # Three gameweeks of opponents, matching what the cards show. Same source
    # and same convention as the fixture ticker, so the two pages cannot
    # disagree about who anyone is playing.
    grid, short, _, _ = ticker.build_grid(bootstrap, fixtures, gw, 3, args.prior)
    fix = {short[t]: [[list(c) for c in col] for col in cols]
           for t, cols in grid.items()}
    gws = list(range(gw, gw + 3))
    html = build(rows, gw, deadline, shorts, fix, gws)

    clashes = web.css_collisions(OWN_CSS, allow=("empty",))
    if clashes:
        print("REFUSING TO WRITE - CSS class names collide with web.CSS: "
              + ", ".join(clashes))
        return 1
    problems = web.lint_js(html, ("#pitch", "#pick", "DOMContentLoaded"))
    if problems:
        print("REFUSING TO WRITE - generated JavaScript looks broken:")
        for pr in problems:
            print("  - {}".format(pr))
        return 1

    if os.path.exists(args.out):
        prev = open(args.out, encoding="utf-8").read()
        if web._payload(prev) == web._payload(html):
            print("my team: unchanged, not rewritten")
            return 0
    with open(args.out, "w") as f:
        f.write(html)
    print("my team: {}  ({} players, {} bytes)".format(
        args.out, len(rows), len(html)))
    if args.open:
        subprocess.run(["open", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
