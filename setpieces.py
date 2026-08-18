#!/usr/bin/env python3
"""Set-piece takers, ordered, per club.

Penalty and corner duty swings FPL returns more than almost any other single
fact about a player, and it is the thing most likely to change quietly over a
summer. Fantasy Football Scout maintains its list by hand and stamps it "last
verified GW__".

They need not. FPL publishes it in bootstrap-static and almost nobody surfaces
it: `penalties_order`, `direct_freekicks_order` and
`corners_and_indirect_freekicks_order`, each an integer rank where 1 is first
choice. This page is that data, joined to our own projections so the answer to
"who takes the penalties, and is he worth owning" is on one screen.

Usage: python3 setpieces.py [--out out/setpieces.html] [--open]
"""

import argparse
import json
import os
import subprocess
import sys

import model as M
import project as P
import web

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

ORDERS = (("pen", "penalties_order", "Penalties"),
          ("fk", "direct_freekicks_order", "Direct free kicks"),
          ("ck", "corners_and_indirect_freekicks_order", "Corners &amp; indirect"))


def collect(bootstrap, proj_by_element):
    """Per team: the ordered taker list for each set-piece type."""
    teams = {t["id"]: t for t in bootstrap["teams"]}
    out = {}
    for t in bootstrap["teams"]:
        out[t["id"]] = {key: [] for key, _, _ in ORDERS}

    for el in bootstrap["elements"]:
        if el["element_type"] not in M.GOAL_PTS:
            continue
        pr = proj_by_element.get(el["id"], {})
        for key, field, _ in ORDERS:
            order = el.get(field)
            if not order:
                continue
            out[el["team"]][key].append(dict(
                o=int(order),
                n=el["web_name"],
                p=M.POS_TO_STR[el["element_type"]],
                c=el["now_cost"] / 10.0,
                xp=pr.get("xp"),
                ps=pr.get("ps"),
                # A first-choice taker who is not expected to start is the
                # single most misleading row on a page like this.
                risk=bool(pr.get("ps") is not None and pr["ps"] < 70),
            ))
    for tid in out:
        for key in out[tid]:
            out[tid][key].sort(key=lambda d: d["o"])
    return out, {t["id"]: t["short_name"] for t in bootstrap["teams"]}


CSS = web.CSS + """
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr));gap:1rem}
.club{background:var(--panel);border:1px solid var(--line);padding:.9rem 1rem}
.club h2{font-family:var(--mono);font-size:.9rem;letter-spacing:.06em;margin:0 0 .7rem;
  color:var(--ink);font-weight:650}
.grp{font-family:var(--mono);font-size:.6rem;letter-spacing:.11em;text-transform:uppercase;
  color:var(--ink-3);margin:.7rem 0 .25rem}
.tk{display:flex;align-items:baseline;gap:.45rem;font-size:.83rem;padding:.16rem 0;
  border-bottom:1px solid var(--line)}
.tk .o{font-family:var(--mono);font-size:.68rem;color:var(--ink-3);width:1rem}
.tk .nm{flex:1;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tk .meta{font-family:var(--mono);font-size:.72rem;color:var(--ink-2);
  font-variant-numeric:tabular-nums}
.tk.risk .nm{color:var(--warn)}
.none{font-size:.78rem;color:var(--ink-3);font-style:italic}
.note{font-size:.85rem;color:var(--ink-2);max-width:66ch}
"""

JS = r"""
const ORDERS=[["pen","Penalties"],["fk","Direct free kicks"],["ck","Corners &amp; indirect"]];
let only="all";

function render(){
  const q=document.getElementById("q").value.trim().toLowerCase();
  document.getElementById("grid").innerHTML=DATA.teams.map(t=>{
    const club=DATA.takers[t.id];
    const groups=ORDERS.filter(([k])=>only==="all"||only===k).map(([k,label])=>{
      let list=club[k];
      if(q) list=list.filter(d=>d.n.toLowerCase().includes(q));
      if(!list.length) return q?"":'<div class="grp">'+label+
        '</div><div class="none">none listed</div>';
      return '<div class="grp">'+label+'</div>'+list.map(d=>
        '<div class="tk'+(d.risk?" risk":"")+'">'+
        '<span class="o">'+d.o+'</span>'+
        '<span class="nm">'+d.n+'</span>'+
        '<span class="meta">'+d.c.toFixed(1)+
        (d.xp!=null?"  "+d.xp.toFixed(2)+" xP":"")+
        (d.ps!=null?"  "+d.ps+"%":"")+'</span></div>').join("");
    }).join("");
    if(q && !groups.replace(/<div class="grp">[^<]*<\/div>/g,"").trim()) return "";
    return '<div class="club"><h2>'+t.name+'</h2>'+groups+'</div>';
  }).join("")||'<p class="none">No takers match that search.</p>';
}

document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".seg button").forEach(b=>
    b.addEventListener("click",()=>{
      only=b.dataset.only;
      document.querySelectorAll(".seg button").forEach(o=>
        o.setAttribute("aria-pressed",o===b?"true":"false"));
      render();
    }));
  document.getElementById("q").addEventListener("input",render);
  render();
});
"""


def build(bootstrap, takers, short, counts):
    teams = sorted(bootstrap["teams"], key=lambda t: t["name"])
    payload = dict(
        teams=[dict(id=str(t["id"]), name=t["name"], short=t["short_name"])
               for t in teams],
        takers={str(k): v for k, v in takers.items()},
    )
    return """<style>{css}</style>
<div class="wrap">
<nav aria-label="Sections"><a href="projections.html">Projections</a>\
<a href="fixtures.html">Fixtures</a>\
<a href="setpieces.html" aria-current="page">Set pieces</a>\
<a href="scorecard.html">Accuracy record</a></nav>
<header>
  <h1>Set-piece takers</h1>
  <p class="note">Ranked first, second and third choice per club, straight from
  FPL&rsquo;s own team data &mdash; {pen} penalty takers, {fk} direct free-kick
  takers, {ck} on corners. Penalty duty moves more FPL points than almost any
  other single fact about a player, and it changes quietly over a summer.
  A name in <span style="color:var(--warn)">amber</span> is a listed taker our
  model does <em>not</em> expect to start, which is the most misleading row on a
  page like this &mdash; first-choice penalties are worth nothing from the bench.</p>
</header>

<div class="controls">
  <div class="seg" role="group" aria-label="Set-piece type">
    <button data-only="all" aria-pressed="true">ALL</button>
    <button data-only="pen" aria-pressed="false">PENS</button>
    <button data-only="fk" aria-pressed="false">FREE KICKS</button>
    <button data-only="ck" aria-pressed="false">CORNERS</button>
  </div>
  <input type="search" id="q" placeholder="Search player" aria-label="Search player">
</div>

<div class="grid" id="grid"></div>

<footer>Source: FPL bootstrap-static, refreshed hourly &middot; xP and start
probability from our own model &middot;
<a href="projections.html" style="color:var(--accent)">full projections</a></footer>
</div>
<script>const DATA={data};{js}</script>""".format(
        css=CSS, js=JS, data=json.dumps(payload, separators=(",", ":")),
        pen=counts["pen"], fk=counts["fk"], ck=counts["ck"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(OUT, "setpieces.html"))
    ap.add_argument("--prior", default="2025-26")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    snap = P.latest_snapshot()
    bootstrap = json.load(open(os.path.join(snap, "bootstrap.json")))

    rows, _, _ = P.build(snap, args.prior, quiet=True)
    proj = {r["element"]: dict(xp=round(r["xp"], 2),
                               ps=round(r["p_start"] * 100)) for r in rows}

    takers, short = collect(bootstrap, proj)
    counts = {k: sum(len(t[k]) for t in takers.values()) for k, _, _ in ORDERS}
    html = build(bootstrap, takers, short, counts)

    problems = web.lint_js(html, ("#grid", "DOMContentLoaded"))
    if problems:
        print("REFUSING TO WRITE - generated JavaScript looks broken:")
        for pr in problems:
            print("  - {}".format(pr))
        return 1

    if os.path.exists(args.out):
        prev = open(args.out, encoding="utf-8").read()
        if web._payload(prev) == web._payload(html):
            print("set pieces: unchanged, not rewritten")
            return 0
    with open(args.out, "w") as f:
        f.write(html)
    print("set pieces: {}  ({} pens, {} FKs, {} corners)".format(
        args.out, counts["pen"], counts["fk"], counts["ck"]))
    if args.open:
        subprocess.run(["open", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
