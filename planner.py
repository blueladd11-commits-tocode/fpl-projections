#!/usr/bin/env python3
"""The transfer calendar.

Every other planner on the market is six stacked squads with a week selector.
This one is a calendar because of a single structural decision: a row is a squad
SLOT, not a player. A slot is a timeline - it holds Raya from GW9 and Sanchez
from GW13 - so a transfer renders as a change of occupant partway along a row.
Everything else follows from that.

The bottom six rows are the ledger, and they are the reason the page exists.
Free transfers before and after, transfers made, hits taken, bank, expected
points, cumulative net. "Wildcard GW9, two transfers GW10" is a question about
consequences, and the consequences are the product.

Rules come from the snapshot's own game_settings and chips array rather than
from anybody's summary of them, because the summaries are wrong in three places
that matter - most importantly that Wildcard and Free Hit do not exist in GW1.

Usage: python3 planner.py [--gameweeks 6] [--out out/planner.html] [--open]
"""

import argparse
import json
import os
import subprocess
import sys

import links
import project as P
import ticker
import web

try:
    import kits
except ImportError:      # pragma: no cover - only until kits.py lands
    kits = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

CHIP_LABEL = {"wildcard": "Wildcard", "freehit": "Free Hit",
              "bboost": "Bench Boost", "3xc": "Triple Captain"}


def chip_rules(bootstrap):
    """The chips array, which is definitive, reduced to what the page needs.

    Read start_event and stop_event rather than hardcoding 19/20: FPL has moved
    the half boundary before, and the common summary that you get four chips
    from GW1 is simply wrong - wildcard and freehit both start at GW2.
    """
    out = []
    for c in bootstrap.get("chips") or []:
        name = c.get("name")
        if name not in CHIP_LABEL:
            continue
        out.append(dict(
            id=c.get("id"), name=name, label=CHIP_LABEL[name],
            start=c.get("start_event"), stop=c.get("stop_event"),
            team=(c.get("chip_type") == "team"),
        ))
    return sorted(out, key=lambda d: (d["start"] or 0, d["name"]))


def settings(bootstrap):
    """Squad and transfer limits, from the game's own config."""
    gs = bootstrap.get("game_settings") or {}
    extra = gs.get("max_extra_free_transfers")
    return dict(
        # max_extra_free_transfers is the number ABOVE the standing one, so the
        # familiar "cap of 5" is 1 + 4.
        ft_cap=1 + int(extra) if extra is not None else 5,
        budget=float(gs.get("squad_total_spend") or 1000) / 10.0,
        sell_fee=float(gs.get("transfers_sell_on_fee") or 0.5),
        hit=int(gs.get("transfers_cost") or 4),
    )


CSS = web.CSS + (kits.CSS if kits else "") + """
.cal{border-collapse:separate;border-spacing:2px;width:100%;min-width:44rem}
.cal th,.cal td{border:0;padding:0;background:transparent}
.cal thead th{position:sticky;top:0;z-index:2;background:var(--ground);
  padding:0 0 2px}
.hd{background:var(--panel);border:1px solid var(--line);padding:.35rem .3rem;
  text-align:center;font-family:var(--mono)}
.hd .g{font-size:.72rem;color:var(--ink);font-weight:650}
.hd .d{font-size:.56rem;color:var(--ink-3);letter-spacing:.02em}
.chipbtn{display:block;width:100%;margin-top:.25rem;font-family:var(--mono);
  font-size:.55rem;letter-spacing:.06em;padding:.16rem .1rem;cursor:pointer;
  background:var(--ground);border:1px dashed var(--line);color:var(--ink-3)}
.chipbtn:hover{border-color:var(--ink-3);color:var(--ink)}
.chipbtn.on{background:var(--accent);color:var(--ground);border-style:solid;
  border-color:var(--accent);font-weight:700}

.slot{font-family:var(--mono);font-size:.6rem;color:var(--ink-3);
  letter-spacing:.06em;text-align:right;padding-right:.4rem !important;
  white-space:nowrap}
.cell{display:block;width:100%;text-align:center;border:1px solid transparent;
  border-radius:2px;padding:.24rem .15rem;cursor:pointer;font:inherit;
  color:#0B0F13;font-family:var(--mono)}
.cell:hover{border-color:var(--ink)}
.cell:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.cell .o{display:block;font-size:.62rem;font-weight:650;letter-spacing:.02em;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell .x{display:block;font-size:.56rem;opacity:.75;
  font-variant-numeric:tabular-nums}
/* A transfer is a change of occupant partway along the row. Two pixels of
   left border say that better than an arrow, and survive at 60px wide. */
.cell.new{border-left:2px solid var(--ink)}
.cell.blank{background:transparent !important;border:1px dashed var(--line);
  color:var(--ink-3)}
.nmcell{display:flex;align-items:center;gap:.25rem;font-size:.66rem;
  color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  padding:.1rem .2rem .1rem 0}
.nmcell .kit{flex:none}
.nmcell b{font-weight:600;overflow:hidden;text-overflow:ellipsis}

.led td,.led th{font-family:var(--mono);font-size:.62rem;
  font-variant-numeric:tabular-nums;text-align:center;padding:.22rem .2rem;
  background:var(--panel);border-top:1px solid var(--line)}
.led th{text-align:right;color:var(--ink-3);letter-spacing:.06em;
  padding-right:.4rem;background:transparent;border-top:0}
.led td.warn{color:var(--warn)}
.led td.loss{color:var(--loss)}
.led tr.big td{font-size:.75rem;color:var(--ink);font-weight:650}

.sheet{position:fixed;left:0;right:0;bottom:0;z-index:40;
  background:var(--panel);border-top:1px solid var(--line);
  /* svh, not vh: the collapsing URL bar on iOS makes vh overshoot and hides
     the confirm button under the browser chrome. */
  max-height:80svh;display:flex;flex-direction:column;
  box-shadow:0 -8px 30px rgba(0,0,0,.35)}
.sheet[hidden]{display:none}
.sheet header{display:flex;align-items:baseline;gap:.5rem;padding:.7rem .9rem;
  border-bottom:1px solid var(--line)}
.sheet h2{margin:0;font-family:var(--mono);font-size:.7rem;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink-3);font-weight:600}
.sheet .sub{font-size:.78rem;color:var(--ink-2);flex:1}
.sheet .body{overflow-y:auto;padding:.6rem .9rem 1.1rem}
.sheet .x{background:none;border:1px solid var(--line);color:var(--ink-2);
  font-family:var(--mono);font-size:.62rem;padding:.2rem .5rem;cursor:pointer}
.opt{display:flex;width:100%;gap:.5rem;align-items:center;background:none;
  border:0;border-bottom:1px solid var(--line);padding:.4rem .1rem;
  text-align:left;cursor:pointer;color:inherit;font:inherit}
.opt:hover:not(:disabled){background:var(--accent-soft)}
.opt:disabled{opacity:.45;cursor:not-allowed}
.opt .n{flex:1;font-size:.82rem;color:var(--ink)}
.opt .m{font-family:var(--mono);font-size:.68rem;color:var(--ink-2);
  font-variant-numeric:tabular-nums}
.opt .m.up{color:var(--accent)}
.opt .m.dn{color:var(--loss)}
.opt .why{font-size:.68rem;color:var(--ink-3)}
.act{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.8rem}
.act button{font-family:var(--mono);font-size:.62rem;letter-spacing:.06em;
  text-transform:uppercase;padding:.36rem .6rem;background:var(--panel);
  border:1px solid var(--line);color:var(--ink-2);cursor:pointer}
.act button:hover{color:var(--ink);border-color:var(--ink-3)}
.act button.go{border-color:var(--accent);color:var(--accent)}
.note{font-size:.84rem;color:var(--ink-2);max-width:66ch}
.empty{text-align:center;padding:2.6rem 1rem;color:var(--ink-3);font-size:.86rem}
.io{font-family:var(--mono);font-size:.66rem;color:var(--ink-2);
  padding:.5rem .1rem 0;border-top:1px solid var(--line);margin-top:.5rem}
.io b{color:var(--ink);font-weight:600}
.io .bad{color:var(--loss)}
@media (max-width:40rem){
  .cal{min-width:38rem}
  .slot{font-size:.53rem}
  .cell .o{font-size:.56rem}
}
"""


JS = r"""
const FT_CAP=CFG.ft_cap, HIT=CFG.hit, SELL_FEE=CFG.sell_fee;
const byId=Object.fromEntries(PLAYERS.map(d=>[d.i,d]));
const SLOTS=[["GKP",2],["DEF",5],["MID",5],["FWD",3]];
const SLOT_KEYS=[];
SLOTS.forEach(([p,n])=>{for(let k=1;k<=n;k++) SLOT_KEYS.push(p+k);});
// The key stays MID3 because it is persisted state; only the label changes.
const SLOT_WORD={GKP:"Keeper",DEF:"Defender",MID:"Midfielder",FWD:"Forward"};
function slotName(key){
  const p=key.replace(/[0-9]/g,""), n=key.replace(/[^0-9]/g,"");
  return (SLOT_WORD[p]||p)+" "+n;
}

// plan.moves: {gw, slot, out, in}. plan.chips: {gw: chipName}.
let plan={v:1, base:GWS[0].n, squad:{}, moves:[], chips:{}};
let sheet=null, q="";

function esc(s){return String(s).replace(/[&<>\x22]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\x22":"&quot;"}[c]));}
const FOLD={"\u00F8":"o","\u0142":"l","\u0111":"d","\u0131":"i","\u00DF":"ss",
  "\u00E6":"ae","\u0153":"oe","\u00F0":"d","\u00FE":"th"};
function norm(s){return s.toLowerCase().replace(/[\u00E0-\u017F]/g,c=>FOLD[c]||c)
  .normalize("NFD").replace(/[\u0300-\u036F]/g,"");}

/* ---- state ------------------------------------------------------------- */
// fpl.squad is the SEED, never the destination. The planner's squad is a
// hypothetical at some future gameweek; writing it back over the real one is a
// data-loss bug waiting to happen, so the only route back is an explicit
// "save as my team" action.
function seedFromSquad(){
  let ids=[];
  try{
    const raw=JSON.parse(localStorage.getItem("fpl.squad")||"[]");
    ids=Array.isArray(raw)?raw.filter(x=>typeof x==="number"&&byId[x]):[];
  }catch(e){ids=[];}
  const bucket={GKP:[],DEF:[],MID:[],FWD:[]};
  ids.forEach(i=>{const d=byId[i]; if(bucket[d.p]) bucket[d.p].push(i);});
  const out={};
  SLOTS.forEach(([p,n])=>{
    for(let k=1;k<=n;k++){
      const id=bucket[p][k-1];
      if(id!==undefined) out[p+k]=id;
    }
  });
  return out;
}
function loadPlan(){
  let stored=null;
  try{ stored=JSON.parse(localStorage.getItem("fpl.plan.v1")||"null"); }
  catch(e){ stored=null; }
  // Shape, not just parseability - the same guard web.py needed after a stored
  // object threw on every subsequent load with no in-app way to recover.
  const ok = stored && typeof stored==="object" && stored.v===1
    && stored.squad && typeof stored.squad==="object"
    && Array.isArray(stored.moves) && stored.chips && typeof stored.chips==="object";
  if(!ok){ plan={v:1, base:GWS[0].n, squad:seedFromSquad(), moves:[], chips:{}}; return; }
  plan=stored;
  // A plan made three gameweeks ago is anchored to a deadline that has passed.
  // Rebase rather than silently showing moves in weeks that no longer exist.
  if(plan.base!==GWS[0].n){
    plan.base=GWS[0].n;
    plan.moves=plan.moves.filter(m=>m.gw>=GWS[0].n);
    const keep={};
    Object.keys(plan.chips).forEach(g=>{if(+g>=GWS[0].n) keep[g]=plan.chips[g];});
    plan.chips=keep;
  }
  plan.moves=plan.moves.filter(m=>byId[m["in"]]&&SLOT_KEYS.indexOf(m.slot)>=0);
  if(!Object.keys(plan.squad).length) plan.squad=seedFromSquad();
}
function savePlan(){
  try{ localStorage.setItem("fpl.plan.v1",JSON.stringify(plan)); }catch(e){}
}

/* ---- the fold ---------------------------------------------------------- */
// One pure function of (plan, data). When a solver eventually exists it will
// emit a plan object and this same fold will draw it.
function simulate(){
  const weeks=[];
  const occ=Object.assign({},plan.squad);
  let ft=1, bank=CFG.bank, cum=0;
  for(const ev of GWS){
    const g=ev.n;
    const chip=plan.chips[g]||null;
    const moves=plan.moves.filter(m=>m.gw===g);
    const free=(chip==="wildcard"||chip==="freehit");
    const ftBefore=ft;
    let spend=0;
    for(const m of moves){
      const out=byId[m.out], inn=byId[m["in"]];
      if(out) spend-=sellPrice(out);
      if(inn) spend+=inn.c;
      occ[m.slot]=m["in"];
    }
    bank-=spend;
    const n=moves.length;
    let hits=0;
    if(!free){
      hits=Math.max(0,n-ft)*HIT;
      ft=Math.min(FT_CAP, Math.max(0, ft-n)+1);
    }else{
      // Banked transfers pass through a wildcard or free hit untouched and
      // then accrue normally: 2 FT + WC in GW6 leaves 3 in GW7.
      ft=Math.min(FT_CAP, ft+1);
    }

    const ids=SLOT_KEYS.map(k=>occ[k]).filter(x=>x!==undefined);
    const scored=ids.map(i=>({i,xp:xpAt(i,g)}));
    const xi=bestXI(scored);
    let xp=xi?xi.tot:0;
    if(xi&&xi.cap) xp+=xi.cap.xp*(chip==="3xc"?2:1);
    if(chip==="bboost") xp=scored.reduce((s,d)=>s+d.xp,0)+(xi&&xi.cap?xi.cap.xp:0);
    const net=xp-hits;
    cum+=net;
    weeks.push({g, chip, moves, hits, ftBefore, ftAfter:ft, bank, xp, net, cum,
                occ:Object.assign({},occ), issues:validate(ids,bank)});
    // A free hit reverts everything at the next deadline - squad, bank and
    // prices. Modelling it as anything other than an isolated branch is wrong.
    if(chip==="freehit"){
      for(const m of moves) occ[m.slot]=m.out;
      bank+=spend;
    }
  }
  return weeks;
}
function sellPrice(d){
  // Purchase price is not tracked yet, so selling price is the listed price.
  // The 50% sell-on fee only bites on a player who has RISEN since you bought
  // him, so this is exact for anyone planning from today and optimistic for a
  // squad held a while. Said plainly on the page rather than hidden.
  return d.c;
}
function xpAt(id,g){
  const d=byId[id];
  if(!d) return 0;
  const k=g-GWS[0].n;
  return (d.g&&d.g[k]!==undefined)?d.g[k]:0;
}
const SHAPES=[[3,4,3],[3,5,2],[4,3,3],[4,4,2],[4,5,1],[5,3,2],[5,4,1],[5,2,3]];
function bestXI(scored){
  const by=p=>scored.filter(s=>byId[s.i].p===p).sort((a,b)=>b.xp-a.xp);
  const g=by("GKP"), d=by("DEF"), m=by("MID"), f=by("FWD");
  if(!g.length) return null;
  let best=null;
  for(const [nd,nm,nf] of SHAPES){
    if(d.length<nd||m.length<nm||f.length<nf) continue;
    const xi=[g[0],...d.slice(0,nd),...m.slice(0,nm),...f.slice(0,nf)];
    const tot=xi.reduce((s,x)=>s+x.xp,0);
    if(!best||tot>best.tot) best={xi,tot};
  }
  if(best) best.cap=best.xi.slice().sort((a,b)=>b.xp-a.xp)[0];
  return best;
}
function validate(ids,bank){
  const out=[];
  if(bank<-1e-9) out.push("over budget by \u00A3"+(-bank).toFixed(1)+"m");
  const clubs={};
  ids.forEach(i=>{const t=byId[i].t; clubs[t]=(clubs[t]||0)+1;});
  for(const t in clubs) if(clubs[t]>3) out.push(clubs[t]+" from "+t);
  const seen={};
  for(const i of ids){ if(seen[i]) out.push(byId[i].n+" twice"); seen[i]=1; }
  return out;
}

/* ---- chips ------------------------------------------------------------- */
// Legality with the reason spelled out, which nobody ships and which is about
// forty lines. The rule everyone misses is the last one.
function chipLegality(name,g){
  const defs=CHIPS.filter(c=>c.name===name);
  const inWindow=defs.filter(c=>g>=c.start&&g<=c.stop);
  if(!inWindow.length){
    const next=defs.filter(c=>c.start>g).sort((a,b)=>a.start-b.start)[0];
    return next ? "not available until GW"+next.start
                : "the window for this chip has closed";
  }
  const here=plan.chips[g];
  if(here&&here!==name) return "GW"+g+" already has "+label(here);
  // One of each per half, and the halves come from the chip windows themselves.
  const win=inWindow[0];
  for(const gs in plan.chips){
    const og=+gs;
    if(og===g||plan.chips[gs]!==name) continue;
    if(og>=win.start&&og<=win.stop)
      return "already planned for GW"+og+" in this half";
  }
  if(name==="freehit"){
    for(const gs in plan.chips){
      const og=+gs;
      if(og!==g&&plan.chips[gs]==="freehit"&&Math.abs(og-g)===1)
        return "Free Hit cannot be played in consecutive gameweeks, and one is "+
               "planned for GW"+og;
    }
  }
  return null;
}
function label(name){
  const c=CHIPS.find(c=>c.name===name);
  return c?c.label:name;
}

/* ---- render ------------------------------------------------------------ */
function fdrColour(v,lo,hi){
  const t=hi>lo?Math.max(0,Math.min(1,(v-lo)/(hi-lo))):0.5;
  return "hsl("+((1-t)*140).toFixed(0)+",62%,"+(58-t*8).toFixed(0)+"%)";
}
let RANGE={atk:[1,1],dfn:[1,1]};
(function(){
  const a=[],d=[];
  for(const t in FIX) for(const col of FIX[t]) for(const f of col){a.push(f[2]);d.push(f[3]);}
  if(a.length) RANGE={atk:[Math.min(...a),Math.max(...a)],
                      dfn:[Math.min(...d),Math.max(...d)]};
})();

function render(){
  const weeks=simulate();
  const head=document.getElementById("hd");
  head.innerHTML='<th></th>'+weeks.map(w=>{
    const ev=GWS.find(e=>e.n===w.g);
    const chip=w.chip?label(w.chip):"+ chip";
    return '<th><div class="hd"><div class="g">GW'+w.g+'</div>'+
      '<div class="d">'+esc(ev.d)+'</div>'+
      '<button class="chipbtn'+(w.chip?" on":"")+'" data-chip="'+w.g+'">'+
      esc(chip)+'</button></div></th>';
  }).join("");

  const body=document.getElementById("bd");
  if(!Object.keys(plan.squad).length){
    body.innerHTML='<tr><td colspan="'+(weeks.length+1)+'"><div class="empty">'+
      'No squad to plan with yet.<br>Build one on <a href="'+MYTEAM+
      '" style="color:var(--accent)">My team</a> and it appears here.</div></td></tr>';
    document.getElementById("led").innerHTML="";
    document.getElementById("io").innerHTML="";
    return;
  }
  body.innerHTML=SLOT_KEYS.map(slot=>{
    let prev=null;
    const cells=weeks.map(w=>{
      const id=w.occ[slot];
      const d=id!==undefined?byId[id]:null;
      const changed=(prev!==null&&id!==prev);
      prev=id;
      if(!d) return '<td><div class="cell blank">&mdash;</div></td>';
      const col=(FIX[d.t]||[])[w.g-GWS[0].n]||[];
      const usesAtk=(d.p==="MID"||d.p==="FWD");
      if(!col.length) return '<td><button class="cell blank'+(changed?" new":"")+
        '" data-slot="'+slot+'" data-gw="'+w.g+'"><span class="o">BGW</span>'+
        '<span class="x">0.00</span></button></td>';
      const f=col[0];
      const v=usesAtk?f[2]:f[3];
      const rng=usesAtk?RANGE.atk:RANGE.dfn;
      const opp=col.map(c=>c[1]?c[0]:c[0].toLowerCase()).join("+");
      return '<td><button class="cell'+(changed?" new":"")+'" data-slot="'+slot+
        '" data-gw="'+w.g+'" style="background:'+fdrColour(v,rng[0],rng[1])+'" '+
        'aria-label="'+esc(d.n)+' GW'+w.g+' versus '+esc(opp)+'">'+
        '<span class="o">'+esc(opp)+'</span>'+
        '<span class="x">'+xpAt(id,w.g).toFixed(2)+'</span></button></td>';
    }).join("");
    const first=weeks[0].occ[slot];
    const d=first!==undefined?byId[first]:null;
    return '<tr><th class="slot">'+slotName(slot)+
      (d?'<div class="nmcell">'+KIT(d.t)+'<b>'+esc(d.n)+'</b></div>':"")+
      '</th>'+cells+'</tr>';
  }).join("");

  const led=document.getElementById("led");
  const row=(label,fn,cls)=>'<tr'+(cls||"")+'><th>'+label+'</th>'+
    weeks.map(w=>fn(w)).join("")+'</tr>';
  led.innerHTML=
    row("Free transfers",w=>'<td'+(w.ftBefore>=FT_CAP&&!w.moves.length?
        ' class="warn"':'')+'>'+w.ftBefore+"\u2192"+w.ftAfter+"</td>")+
    row("Moves made",w=>'<td>'+(w.chip==="wildcard"?"WILDCARD":
        w.chip==="freehit"?"FREE HIT":(w.moves.length||"\u2014"))+"</td>")+
    row("Points cost",w=>'<td'+(w.hits?' class="loss"':'')+'>'+
        (w.hits?"-"+w.hits:"0")+"</td>")+
    row("Money left",w=>'<td'+(w.bank<0?' class="loss"':'')+'>\u00A3'+
        w.bank.toFixed(1)+"m</td>")+
    row("Points that week",w=>'<td>'+w.xp.toFixed(1)+"</td>")+
    row("Running total",w=>'<td>'+w.cum.toFixed(1)+"</td>",' class="big"');

  const problems=[];
  weeks.forEach(w=>w.issues.forEach(p=>problems.push("GW"+w.g+": "+p)));
  const io=weeks.filter(w=>w.moves.length).map(w=>
    '<div>GW'+w.g+' &rsaquo; '+w.moves.map(m=>{
      const o=byId[m.out], i=byId[m["in"]];
      return '<b>'+esc(i?i.n:"?")+'</b> \u00A3'+(i?i.c.toFixed(1):"?")+
        ' in for '+esc(o?o.n:"empty")+(o?' \u00A3'+sellPrice(o).toFixed(1):"");
    }).join(" \u00B7 ")+'</div>').join("");
  document.getElementById("io").innerHTML=
    (problems.length?'<div class="bad">'+esc(problems.join(" \u00B7 "))+"</div>":"")+
    (io||'<div style="opacity:.65">No transfers planned. Tap any cell to move '+
     'a player in from that gameweek onward.</div>');
}

/* ---- sheet ------------------------------------------------------------- */
function openSheet(html,title,sub){
  document.getElementById("sh-t").textContent=title;
  document.getElementById("sh-s").textContent=sub||"";
  document.getElementById("sh-b").innerHTML=html;
  document.getElementById("sheet").hidden=false;
}
function closeSheet(){document.getElementById("sheet").hidden=true;sheet=null;q="";}

function cellSheet(slot,gw){
  sheet={slot,gw};
  const weeks=simulate();
  const w=weeks.find(x=>x.g===gw);
  const cur=w?byId[w.occ[slot]]:null;
  const mine=plan.moves.find(m=>m.gw===gw&&m.slot===slot);
  const acts='<div class="act">'+
    '<button class="go" id="sh-tx">Transfer from GW'+gw+'</button>'+
    (mine?'<button id="sh-undo">Undo the GW'+gw+' move</button>':"")+
    '<button id="sh-close2">Cancel</button></div>';
  openSheet(acts, slotName(slot)+" \u00B7 gameweek "+gw,
    cur?("currently "+cur.n+" ("+cur.t+", \u00A3"+cur.c.toFixed(1)+"m)"):"empty slot");
}

function txSheet(){
  const {slot,gw}=sheet;
  const pos=slot.replace(/[0-9]/g,"");
  const weeks=simulate();
  const w=weeks.find(x=>x.g===gw);
  const outId=w.occ[slot];
  const out=outId!==undefined?byId[outId]:null;
  const budget=w.bank+(out?sellPrice(out):0);
  const held=new Set(Object.keys(w.occ).filter(k=>k!==slot).map(k=>w.occ[k]));
  const clubs={};
  held.forEach(i=>{const t=byId[i].t; clubs[t]=(clubs[t]||0)+1;});
  // The number the decision actually turns on: xP over the REST of the horizon,
  // not this week alone.
  const rest=GWS.filter(e=>e.n>=gw).map(e=>e.n);
  const base=out?rest.reduce((s,g)=>s+xpAt(out.i,g),0):0;
  const nq=norm(q);
  const list=PLAYERS.filter(d=>{
    // The incumbent is excluded from his own replacement list. He is not in
    // `held` - that set is what the club and budget maths needs him out of -
    // so without this you can transfer a player for himself and book a move
    // that costs a free transfer and changes nothing.
    if(d.p!==pos||held.has(d.i)||d.i===outId) return false;
    if(!nq) return true;
    return norm(d.n).includes(nq)||norm(d.t).includes(nq)||
           d.c.toFixed(1).indexOf(nq)===0;
  }).map(d=>({d, gain:rest.reduce((s,g)=>s+xpAt(d.i,g),0)-base}))
    .sort((a,b)=>b.gain-a.gain).slice(0,40);

  const rows=list.map(({d,gain})=>{
    const short=d.c-budget;
    const clubFull=(clubs[d.t]||0)>=3;
    const why=short>1e-9?("\u00A3"+short.toFixed(1)+"m short")
             :(clubFull?"3 from "+d.t:"");
    return '<button class="opt" data-in="'+d.i+'"'+(why?" disabled":"")+'>'+
      KIT(d.t)+'<span class="n">'+esc(d.n)+'</span>'+
      '<span class="m">\u00A3'+d.c.toFixed(1)+'</span>'+
      '<span class="m '+(gain>0?"up":(gain<0?"dn":""))+'">'+
      (gain>=0?"+":"")+gain.toFixed(2)+'</span>'+
      '<span class="m" style="opacity:.6">'+d.ps+'%</span>'+
      (why?'<span class="why">'+esc(why)+'</span>':"")+'</button>';
  }).join("")||'<p class="note">Nobody matches that.</p>';

  openSheet('<input type="search" id="sh-q" placeholder="Name, club or price" '+
    'aria-label="Search" style="width:100%;margin-bottom:.5rem" value="'+esc(q)+'">'+
    '<p class="note" style="margin:.1rem 0 .5rem;font-size:.72rem">Budget at GW'+
    gw+': \u00A3'+budget.toFixed(1)+'m. The number is expected points gained over '+
    'GW'+gw+'\u2013'+GWS[GWS.length-1].n+', against the player leaving.</p>'+rows,
    "Bring in a "+slotName(slot).replace(/ \d+$/,"").toLowerCase(),
    out?("out: "+out.n+" \u00A3"+sellPrice(out).toFixed(1)+"m"):"empty slot");
  const box=document.getElementById("sh-q");
  box.focus();
  box.addEventListener("input",e=>{
    q=e.target.value.trim();
    const at=e.target.selectionStart;
    txSheet();
    const nb=document.getElementById("sh-q");
    if(nb){nb.focus();nb.setSelectionRange(at,at);}
  });
}

function chipSheet(gw){
  const rows=CHIPS.filter((c,i,a)=>a.findIndex(x=>x.name===c.name)===i)
    .map(c=>{
      const why=chipLegality(c.name,gw);
      const on=plan.chips[gw]===c.name;
      return '<button class="opt" data-chipset="'+c.name+'"'+
        ((why&&!on)?" disabled":"")+'>'+
        '<span class="n">'+esc(c.label)+(on?" \u2713":"")+'</span>'+
        (why?'<span class="why">'+esc(why)+'</span>':
             '<span class="m up">available</span>')+'</button>';
    }).join("");
  openSheet(rows+(plan.chips[gw]?'<div class="act" style="margin-top:.7rem">'+
    '<button id="sh-nochip">Remove '+esc(label(plan.chips[gw]))+
    '</button></div>':""),
    "Chips \u00B7 GW"+gw, "one chip per gameweek");
  sheet={gw};
}

/* ---- events ------------------------------------------------------------ */
document.addEventListener("DOMContentLoaded",()=>{
  loadPlan();
  render();

  document.getElementById("bd").addEventListener("click",e=>{
    const b=e.target.closest("button[data-slot]");
    if(b) cellSheet(b.dataset.slot,+b.dataset.gw);
  });
  document.getElementById("hd").addEventListener("click",e=>{
    const b=e.target.closest("button[data-chip]");
    if(b) chipSheet(+b.dataset.chip);
  });
  document.getElementById("sh-b").addEventListener("click",e=>{
    const t=e.target.closest("button");
    if(!t) return;
    if(t.id==="sh-close2"){closeSheet();return;}
    if(t.id==="sh-tx"){txSheet();return;}
    if(t.id==="sh-undo"){
      plan.moves=plan.moves.filter(m=>!(m.gw===sheet.gw&&m.slot===sheet.slot));
      savePlan();closeSheet();render();return;
    }
    if(t.id==="sh-nochip"){
      delete plan.chips[sheet.gw];savePlan();closeSheet();render();return;
    }
    if(t.dataset.chipset){
      plan.chips[sheet.gw]=t.dataset.chipset;savePlan();closeSheet();render();return;
    }
    if(t.dataset["in"]){
      const {slot,gw}=sheet;
      const w=simulate().find(x=>x.g===gw);
      const outId=w.occ[slot];
      plan.moves=plan.moves.filter(m=>!(m.gw===gw&&m.slot===slot));
      plan.moves.push({gw, slot, out:outId===undefined?null:outId,
                       "in":+t.dataset["in"]});
      plan.moves.sort((a,b)=>a.gw-b.gw);
      savePlan();closeSheet();render();
    }
  });
  document.getElementById("sh-x").addEventListener("click",closeSheet);
  document.addEventListener("keydown",e=>{
    if(e.key==="Escape") closeSheet();
  });
  document.getElementById("reseed").addEventListener("click",()=>{
    plan={v:1, base:GWS[0].n, squad:seedFromSquad(), moves:[], chips:{}};
    savePlan();render();
  });
  document.getElementById("wipe").addEventListener("click",()=>{
    plan.moves=[];plan.chips={};savePlan();render();
  });
});
"""


def build(rows, bootstrap, fixtures, start_gw, n_gw, prior):
    data = web.prepare(rows)
    grid, short, _, _ = ticker.build_grid(bootstrap, fixtures, start_gw, n_gw,
                                          prior)
    # The grid is keyed by team id; the player payload carries short names, so
    # rekey once here rather than shipping a second lookup table.
    fix = {}
    for tid, cols in grid.items():
        fix[short[tid]] = [[list(c) for c in col] for col in cols]

    events = {e["id"]: e for e in bootstrap.get("events") or []}
    gws = []
    for g in range(start_gw, start_gw + n_gw):
        ev = events.get(g) or {}
        dl = (ev.get("deadline_time") or "")[:16].replace("T", " ")
        gws.append(dict(n=g, d=dl))

    cfg = settings(bootstrap)
    cfg["bank"] = 0.0
    chips = chip_rules(bootstrap)
    shorts = sorted(t["short_name"] for t in bootstrap["teams"])
    markup = {s: kits.shirt(s) for s in shorts} if kits else {}
    # The shirt markup is a <use> reference; without the sprite in the
    # document it resolves to nothing and renders as empty space.
    sprite = kits.sprite() if kits else ""

    first = next((c for c in chips if c["name"] == "wildcard"), None)
    caveat = ("" if not first else
              "Worth knowing: you cannot play a Wildcard or Free Hit in "
              "gameweek 1. Both unlock in gameweek {}, whatever the season "
              "previews told you.".format(first["start"]))

    body = """<div class="wrap">
{nav}
<header>
  <h1>Transfer planner &mdash; gameweeks {a} to {b}</h1>
  <p class="note">Plan the next six weeks before you commit to anything.</p>
  <ul class="note" style="padding-left:1.1rem;margin:.5rem 0 0">
    <li><strong>Tap any square</strong> to swap that player from that week
      onward. Each row is one place in your squad, so you can see exactly when
      a new signing takes over.</li>
    <li><strong>Tap &ldquo;chip&rdquo;</strong> at the top of a week to plan a
      Wildcard, Free Hit, Bench Boost or Triple Captain. Anything you cannot
      legally play that week is greyed out with the reason.</li>
    <li><strong>Green fixtures are the kind ones.</strong> Attackers and
      defenders are coloured differently on purpose: an opponent who leaks
      goals is good news for your forwards and bad news for your defence.</li>
    <li><strong>The rows underneath keep score</strong> &mdash; free
      transfers, what any extra moves cost you, money left, and your running
      points total.</li>
  </ul>
  <p class="note" style="margin-top:.6rem;font-size:.8rem;color:var(--ink-3)">
  {caveat}</p>
</header>

<div class="act">
  <button id="reseed" class="go">Reload squad from My team</button>
  <button id="wipe">Clear planned moves</button>
</div>

<div class="scroll">
  <table class="cal">
    <thead><tr id="hd"></tr></thead>
    <tbody id="bd"></tbody>
    <tbody class="led" id="led"></tbody>
  </table>
</div>
<div class="io" id="io"></div>

<footer>Expected points come from the same model as the
<a href="{scorecard}" style="color:var(--accent)">published accuracy record</a>
&middot; selling prices assume no price change since purchase &middot; the plan
is stored in this browser only</footer>
</div>

{sprite}
<section class="sheet" id="sheet" hidden aria-label="Planner actions">
  <header><h2 id="sh-t"></h2><span class="sub" id="sh-s"></span>
    <button class="x" id="sh-x">Close</button></header>
  <div class="body" id="sh-b"></div>
</section>
<script>const PLAYERS={data};const FIX={fix};const GWS={gws};
const CHIPS={chips};const CFG={cfg};const KITS={kitmap};
const MYTEAM="{myteam}";
function KIT(t){{return KITS[t]||"";}}{js}</script>""".format(
        nav=links.nav("planner"), a=start_gw, b=start_gw + n_gw - 1,
        sprite=sprite,
        caveat=caveat, scorecard=links.href("scorecard"),
        myteam=links.href("myteam"),
        data=json.dumps(data, separators=(",", ":")),
        fix=json.dumps(fix, separators=(",", ":")),
        gws=json.dumps(gws, separators=(",", ":")),
        chips=json.dumps(chips, separators=(",", ":")),
        cfg=json.dumps(cfg, separators=(",", ":")),
        kitmap=json.dumps(markup, separators=(",", ":")), js=JS)
    return links.document("FPL transfer planner", body, CSS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gameweeks", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(OUT, "planner.html"))
    ap.add_argument("--prior", default="2025-26")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    snap = P.latest_snapshot()
    bootstrap = json.load(open(os.path.join(snap, "bootstrap.json")))
    fixtures = json.load(open(os.path.join(snap, "fixtures.json")))
    manifest = json.load(open(os.path.join(snap, "manifest.json")))
    start = manifest.get("next_gw") or 1

    rows, _, _ = P.build(snap, args.prior, quiet=True)
    html = build(rows, bootstrap, fixtures, start, args.gameweeks, args.prior)

    problems = web.lint_js(html, ("#bd", "#hd", "#led", "DOMContentLoaded"))
    if problems:
        print("REFUSING TO WRITE - generated JavaScript looks broken:")
        for pr in problems:
            print("  - {}".format(pr))
        return 1

    if os.path.exists(args.out):
        prev = open(args.out, encoding="utf-8").read()
        if web._payload(prev) == web._payload(html):
            print("planner: unchanged, not rewritten")
            return 0
    with open(args.out, "w") as f:
        f.write(html)
    print("planner: {}  (GW{}-{}, {} chips, {} bytes)".format(
        args.out, start, start + args.gameweeks - 1,
        len(chip_rules(bootstrap)), len(html)))
    if args.open:
        subprocess.run(["open", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
