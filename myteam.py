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
import web

# kits.py renders the club shirts. It is built separately, so the page must
# still come up without it rather than taking the hourly build down with it.
try:
    import kits
except ImportError:      # pragma: no cover - only until kits.py lands
    kits = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


CSS = web.CSS + (kits.CSS if kits else "") + """
/* minmax(0,...) on every track, not 1fr. A bare 1fr is minmax(auto,1fr), and
   that auto minimum is the grid item min-content - which for a wrapping flex
   row of player cards Chrome resolves to something enormous. The track grew to
   10425px inside a 637px container and the pitch, which clips its overflow,
   rendered as an empty green box with all fifteen cards centred 5000px off to
   the right. */
.cols{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);
  gap:1.1rem;align-items:start}
.cols>*{min-width:0}
@media (max-width:60rem){.cols{grid-template-columns:minmax(0,1fr)}}

/* The pitch. Drawn, not photographed: a background image would be the only
   external asset on the whole site and would cost more than it says. */
.pitch{background:
    linear-gradient(180deg,var(--turf-a) 0%,var(--turf-b) 100%);
  border:1px solid var(--line);border-radius:3px;padding:.9rem .5rem 0;
  position:relative;overflow:hidden}
:root{--turf-a:#E4EAE6;--turf-b:#D7E0DA}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --turf-a:#111A19;--turf-b:#0E1614}}
:root[data-theme="dark"]{--turf-a:#111A19;--turf-b:#0E1614}
.pitch:before{content:"";position:absolute;inset:0;pointer-events:none;
  background:
    linear-gradient(90deg,transparent 49.7%,var(--line) 49.7%,
      var(--line) 50.3%,transparent 50.3%) no-repeat center/1px 100%;
  opacity:.5}
.line{display:flex;justify-content:center;gap:.4rem;flex-wrap:wrap;
  margin-bottom:.85rem;position:relative;z-index:1}

.pl{width:5.3rem;background:var(--panel);border:1px solid var(--line);
  border-radius:3px;padding:.3rem .25rem .28rem;text-align:center;cursor:pointer;
  position:relative}
.pl:hover{border-color:var(--ink-3)}
.pl:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.pl.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.pl .nm{font-size:.7rem;color:var(--ink);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;font-weight:600;line-height:1.25}
.pl .mt{font-family:var(--mono);font-size:.6rem;color:var(--ink-2);
  font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.pl .fx{font-family:var(--mono);font-size:.55rem;color:var(--ink-3);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pl .kit{display:block;margin:0 auto .12rem}
/* Doubt is worth more than precision here: a red name that turns out to play is
   a smaller cost than a black name that turns out to be injured. */
.pl.doubt .nm{color:var(--warn)}
.pl.out .nm{color:var(--loss)}

.arm{position:absolute;top:-.35rem;right:-.35rem;width:1.05rem;height:1.05rem;
  border-radius:50%;font-family:var(--mono);font-size:.55rem;font-weight:700;
  display:flex;align-items:center;justify-content:center;border:1px solid var(--line);
  background:var(--panel);color:var(--ink-3)}
.pl.cap .arm{background:var(--accent);color:var(--ground);border-color:var(--accent)}
.pl.vice .arm{background:var(--accent-soft);color:var(--accent);
  border-color:var(--accent)}

.bench{margin-top:.2rem;border-top:1px dashed var(--line);padding-top:.7rem}
.bench .lbl{font-family:var(--mono);font-size:.58rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:.4rem;
  display:flex;justify-content:space-between}
.bench .line{margin-bottom:.6rem}
.bench .pl{opacity:.82}
.bo{position:absolute;top:-.35rem;left:-.35rem;width:1.05rem;height:1.05rem;
  border-radius:50%;font-family:var(--mono);font-size:.55rem;
  display:flex;align-items:center;justify-content:center;
  background:var(--ground);border:1px solid var(--line);color:var(--ink-3)}

.tot{display:grid;grid-template-columns:repeat(auto-fit,minmax(6.2rem,1fr));
  gap:.5rem;margin-bottom:.9rem}
.tot div{background:var(--panel);border:1px solid var(--line);padding:.5rem .6rem}
.tot .k{font-family:var(--mono);font-size:.56rem;letter-spacing:.11em;
  text-transform:uppercase;color:var(--ink-3)}
.tot .v{font-family:var(--mono);font-size:1.15rem;color:var(--ink);
  font-variant-numeric:tabular-nums;margin-top:.1rem}
.tot .v.bad{color:var(--loss)}
.tot .v small{font-size:.6rem;color:var(--ink-3);letter-spacing:0}

.side{background:var(--panel);border:1px solid var(--line);padding:.85rem .9rem}
.side h2{font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 .55rem;font-weight:600}
.need{display:flex;gap:.3rem;flex-wrap:wrap;margin-bottom:.6rem}
.need span{font-family:var(--mono);font-size:.62rem;padding:.16rem .42rem;
  border:1px solid var(--line);color:var(--ink-2)}
.need span.done{border-color:var(--accent);color:var(--accent)}
.pick{max-height:23rem;overflow-y:auto;margin:.5rem -.3rem 0}
.pick button{display:flex;width:100%;align-items:center;gap:.45rem;
  background:none;border:0;border-bottom:1px solid var(--line);
  padding:.32rem .3rem;text-align:left;cursor:pointer;color:inherit;font:inherit}
.pick button:hover{background:var(--accent-soft)}
.pick button:disabled{opacity:.35;cursor:not-allowed}
.pick .n{flex:1;font-size:.79rem;color:var(--ink);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.pick .x{font-family:var(--mono);font-size:.68rem;color:var(--ink-2);
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
.empty{text-align:center;padding:2.4rem 1rem;color:var(--ink-3);font-size:.85rem}

/* A five-man defensive line has to fit on one row on a phone or the pitch stops
   reading as a pitch. 343px of pitch, less padding and four gaps, leaves about
   60px a card - which is what sets the card width here, not taste. */
@media (max-width:26rem){
  .pitch{padding:.7rem .35rem 0}
  .line{gap:.25rem;margin-bottom:.6rem}
  .pl{width:3.72rem;padding:.25rem .12rem .22rem}
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

/* ---- state ------------------------------------------------------------- */
// Same key as the projections page: a squad picked while browsing is already
// here. Shape is validated, not just parseability - a stored object rather than
// an array once threw on every subsequent load with no in-app way to recover.
function load(){
  try{
    const raw=JSON.parse(localStorage.getItem("fpl.squad")||"[]");
    squad=Array.isArray(raw)?raw.filter(x=>typeof x==="number"&&byId[x]):[];
  }catch(e){squad=[];}
  try{
    const c=JSON.parse(localStorage.getItem("fpl.cap")||"null");
    cap=(typeof c==="number"&&squad.includes(c))?c:null;
    const v=JSON.parse(localStorage.getItem("fpl.vice")||"null");
    vice=(typeof v==="number"&&squad.includes(v)&&v!==cap)?v:null;
    const b=JSON.parse(localStorage.getItem("fpl.bench")||"[]");
    bench=Array.isArray(b)?b.filter(x=>typeof x==="number"&&squad.includes(x)):[];
  }catch(e){cap=vice=null;bench=[];}
}
function save(){
  try{
    localStorage.setItem("fpl.squad",JSON.stringify(squad));
    localStorage.setItem("fpl.cap",JSON.stringify(cap));
    localStorage.setItem("fpl.vice",JSON.stringify(vice));
    localStorage.setItem("fpl.bench",JSON.stringify(bench));
  }catch(e){}
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
  let j;
  try{ j=JSON.parse(text); }
  catch(e){ return "That is not JSON. Copy the whole page, braces included."; }
  if(j&&j.detail) return "FPL replied: "+j.detail+". Picks stay hidden until a "+
    "gameweek deadline has passed, so before the season starts there is nothing "+
    "to import yet.";
  const picks=j&&j.picks;
  if(!Array.isArray(picks)||!picks.length)
    return "No picks in that JSON. Check the tab you copied ends in /picks/.";
  const known=picks.filter(p=>byId[p.element]);
  if(known.length<11) return "Only "+known.length+" of those players are in this "+
    "gameweek data. That usually means the picks are from a different season.";
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
function card(id,onBench,pos){
  const d=byId[id];
  if(!d) return "";
  const cls=["pl"];
  if(sel===id) cls.push("sel");
  if(id===cap) cls.push("cap"); else if(id===vice) cls.push("vice");
  if(d.ps<55) cls.push("doubt");
  if(d.ps<25) cls.push("out");
  const arm=(id===cap?"C":(id===vice?"V":""));
  return '<div class="'+cls.join(" ")+'" data-id="'+id+'" tabindex="0" role="button" '+
    'aria-label="'+esc(d.n)+', '+POS_ONE[d.p]+', '+d.t+'">'+
    (arm?'<span class="arm">'+arm+'</span>':"")+
    (onBench&&pos?'<span class="bo">'+pos+'</span>':"")+
    KIT(d.t)+
    '<div class="nm">'+esc(d.n)+'</div>'+
    '<div class="mt">'+d.xp.toFixed(2)+" pts</div>"+
    '<div class="fx">'+esc(d.t)+" \u00B7 \u00A3"+d.c.toFixed(1)+"</div>"+
    '</div>';
}

function render(){
  const members=squad.map(i=>byId[i]).filter(Boolean);
  const xi=starters();
  const shape=shapeOf(xi);
  const problems=issues();

  const cost=members.reduce((s,d)=>s+d.c,0);
  const capD=byId[cap];
  const xiXp=xi.reduce((s,i)=>s+(byId[i]?byId[i].xp:0),0);
  const total=xiXp+(capD&&xi.includes(cap)?capD.xp:0);

  document.getElementById("t-n").innerHTML=members.length+
    '<small>/15</small>';
  document.getElementById("t-n").className="v"+(members.length>15?" bad":"");
  document.getElementById("t-cost").textContent="\u00A3"+cost.toFixed(1)+"m";
  document.getElementById("t-cost").className="v"+(cost>BUDGET?" bad":"");
  document.getElementById("t-bank").textContent="\u00A3"+(BUDGET-cost).toFixed(1)+"m";
  document.getElementById("t-bank").className="v"+(cost>BUDGET?" bad":"");
  document.getElementById("t-xp").textContent=
    legalXI(xi)?total.toFixed(1):"\u2014";
  document.getElementById("t-shape").textContent=
    legalXI(xi)?(shape.DEF+"-"+shape.MID+"-"+shape.FWD):"\u2014";

  const pitch=document.getElementById("pitch");
  if(!members.length){
    pitch.innerHTML='<div class="empty">No squad yet.<br>Pick players on the '+
      'right, or let the model build one.</div>';
  }else{
    const rows=ORDER.map(pos=>{
      const ids=xi.filter(i=>byId[i].p===pos);
      if(!ids.length) return "";
      return '<div class="line">'+ids
        .sort((a,b)=>byId[b].xp-byId[a].xp)
        .map(i=>card(i,false)).join("")+"</div>";
    }).join("");
    const bo=bench.map((i,n)=>card(i,true,byId[i].p==="GKP"?"G":String(n)));
    pitch.innerHTML=rows+
      (bench.length?'<div class="bench"><div class="lbl"><span>Bench</span>'+
        '<span>order matters</span></div><div class="line">'+
        bo.join("")+"</div></div>":"");
  }

  const msg=document.getElementById("msg");
  msg.className=problems.length?"msg bad":"msg";
  msg.textContent=problems.length?("Illegal squad: "+problems.join("; ")):
    (members.length===15
      ? (legalXI(xi)?"Legal squad and a legal eleven."
                    :"15 picked. Tap Auto to set a valid eleven.")
      : (15-members.length)+" more to a full squad.");

  document.getElementById("need").innerHTML=ORDER.map(pos=>{
    const n=members.filter(d=>d.p===pos).length;
    return '<span class="'+(n>=LIMITS[pos]?"done":"")+'">'+POS_WORD[pos]+" "+n+"/"+
      LIMITS[pos]+"</span>";
  }).join("");

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
    squad=[];bench=[];cap=null;vice=null;sel=null;save();render();
  });

  const panel=document.getElementById("imp");
  const link=document.getElementById("tlink");
  document.getElementById("impbtn").addEventListener("click",()=>{
    panel.hidden=!panel.hidden;
    if(!panel.hidden) document.getElementById("tid").focus();
  });
  document.getElementById("noimp").addEventListener("click",()=>{panel.hidden=true;});
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


def build(rows, gw, deadline, shorts):
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
  <p class="note">Your fifteen, the way you would actually line them up.</p>
  <ul class="note" style="padding-left:1.1rem;margin:.5rem 0 0">
    <li><strong>Tap a starter, then a substitute</strong> to swap them. We will
      stop you if the swap would leave a formation the game does not allow.</li>
    <li><strong>Right-click a player</strong> (or press <kbd>C</kbd>) to give
      him the armband and double his score. <kbd>V</kbd> makes him
      vice-captain.</li>
    <li><strong>Not sure where to start?</strong> Hit
      <em>Build me a squad</em> and we will pick fifteen inside the budget.</li>
  </ul>
  <p class="note" style="margin-top:.6rem;font-size:.8rem;color:var(--ink-3)">
  Your squad is saved in this browser and nowhere else &mdash; nothing is
  uploaded. It shows up on the
  <a href="{projections}" style="color:var(--accent)">projections</a> page too.</p>
</header>

<section class="imp" id="imp" hidden aria-label="Import an FPL team">
  <ol>
    <li>Your team id is the number in the URL when you open
      <em>Points</em> or <em>Gameweek history</em> on the FPL site. It is
      reissued every season, so last year&rsquo;s will not work.</li>
    <li>Team id <input type="text" id="tid" inputmode="numeric"
      placeholder="1234567" aria-label="FPL team id">
      <a id="tlink" href="#" target="_blank" rel="noopener">open your picks</a>
      &mdash; opens on fantasy.premierleague.com, where you are already signed in.</li>
    <li>Copy everything on that page and paste it here:</li>
  </ol>
  <textarea id="paste" placeholder="Paste the JSON from that tab"
    aria-label="Paste picks JSON"></textarea>
  <div class="act" style="margin:.6rem 0 0"><button id="doimp" class="go">Load
    this team</button><button id="noimp">Cancel</button></div>
  <p class="msg" id="impmsg">Nothing is uploaded. The paste is read here, in
    this tab, and never leaves the browser.</p>
</section>

<div class="act">
  <button id="fill" class="go">Build me a squad</button>
  <button id="impbtn">Import my FPL team</button>
  <button id="auto">Auto eleven &amp; captain</button>
  <button id="clear">Clear</button>
</div>

<div class="tot">
  <div><div class="k">Players picked</div><div class="v" id="t-n">0<small>/15</small></div></div>
  <div><div class="k">Cost</div><div class="v" id="t-cost">&pound;0.0m</div></div>
  <div><div class="k">In the bank</div><div class="v" id="t-bank">&pound;100.0m</div></div>
  <div><div class="k">Points this week</div><div class="v" id="t-xp">&mdash;</div></div>
  <div><div class="k">Formation</div><div class="v" id="t-shape">&mdash;</div></div>
</div>

<div class="cols">
  <div>
    <div class="pitch" id="pitch"></div>
    <p class="msg" id="msg"></p>
  </div>

  <aside class="side" aria-label="Add players">
    <h2>Add players</h2>
    <div class="need" id="need"></div>
    <div class="controls" style="padding:0;border:0;background:none;margin:0">
      <div class="seg" role="group" aria-label="Position">
        <button data-pos="ALL" aria-pressed="true">Everyone</button>
        <button data-pos="GKP" aria-pressed="false">Keepers</button>
        <button data-pos="DEF" aria-pressed="false">Defenders</button>
        <button data-pos="MID" aria-pressed="false">Midfielders</button>
        <button data-pos="FWD" aria-pressed="false">Forwards</button>
      </div>
    </div>
    <input type="search" id="q" placeholder="Search player or club"
      aria-label="Search player or club" style="width:100%;margin-top:.5rem">
    <div class="pick" id="pick"></div>
  </aside>
</div>

<footer>Deadline {deadline} &middot; projections rebuilt hourly &middot;
squad and captain stored locally in this browser &middot;
<a href="{fixtures}" style="color:var(--accent)">fixture difficulty</a></footer>
</div>
{sprite}
<script>const DATA={data};const CHEAP={cheap};const GW={gw};const KITS={kitmap};
function KIT(t){{return KITS[t]||"";}}{js}</script>""".format(
        nav=links.nav("myteam"), gw=gw, deadline=deadline,
        projections=links.href("projections"), fixtures=links.href("fixtures"),
        sprite=sprite, data=json.dumps(data, separators=(",", ":")),
        cheap=json.dumps(cheap),
        kitmap=json.dumps(markup, separators=(",", ":")), js=JS)
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
    rows, _, _ = P.build(snap, args.prior, quiet=True)
    gw = manifest.get("next_gw") or 1
    deadline = (manifest.get("next_deadline") or "").replace("T", " ")[:16] + " UTC"

    html = build(rows, gw, deadline, shorts)

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
