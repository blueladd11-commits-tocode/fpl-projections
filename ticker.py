#!/usr/bin/env python3
"""Fixture ticker — the second tool every FPL service sells.

Both Scout and Hub ship one, and it is the tool people use for planning rather
than for this week. Ours differs in one substantive way.

FPL publishes a single 1-5 difficulty per fixture, and every ticker on the
market re-colours that number. It conflates two different questions:

    "is this a good fixture to own an ATTACKER in?"   -> how leaky is the opponent
    "is this a good fixture to own a DEFENDER in?"    -> how toothless is the opponent

Those come apart constantly. A newly promoted side concedes freely AND scores
little: excellent to attack, excellent to defend against. A strong attacking
team that presses high can be hard to score against and dangerous to keep a
clean sheet against. One number cannot say both, so this shows them separately,
computed from the same fitted team ratings the projection model uses rather than
from FPL's hand-set tiers.

Usage: python3 ticker.py [--gameweeks 8] [--out out/fixtures.html] [--open]
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import model as M
import project as P
import web

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def build_grid(bootstrap, fixtures, start_gw, n_gw, prior_season):
    """{team_id: [ [ (opp_short, is_home, atk_diff, def_diff), ... ], ... ]}

    A list per gameweek, because a team can have two fixtures (a double) or
    none (a blank). Every ticker that assumes one fixture per gameweek quietly
    misleads people in exactly the weeks that matter most.
    """
    teams, idx, granular = P.team_ratings(bootstrap, prior_season)
    short = {t["id"]: t["short_name"] for t in bootstrap["teams"]}

    grid = {t["id"]: [[] for _ in range(n_gw)] for t in bootstrap["teams"]}
    for fx in fixtures:
        ev = fx.get("event")
        if ev is None or not (start_gw <= ev < start_gw + n_gw):
            continue
        col = ev - start_gw
        for tid, opp, home in ((fx["team_h"], fx["team_a"], True),
                               (fx["team_a"], fx["team_h"], False)):
            # Attacking difficulty = how good the opponent's DEFENCE is.
            # Defensive difficulty = how good the opponent's ATTACK is.
            atk = idx[(opp, "defence", not home)]
            dfn = idx[(opp, "attack", not home)]
            # Venue matters in both directions.
            atk *= 0.94 if home else 1.06
            dfn *= 0.92 if home else 1.08
            grid[tid][col].append((short[opp], home, round(atk, 4), round(dfn, 4)))
    return grid, short, teams, granular


def summarise(grid, n_gw):
    """Mean difficulty per team over the horizon, and fixture count."""
    out = {}
    for tid, cols in grid.items():
        flat = [c for col in cols for c in col]
        n = len(flat)
        out[tid] = dict(
            n=n,
            atk=(sum(c[2] for c in flat) / n) if n else 1.0,
            dfn=(sum(c[3] for c in flat) / n) if n else 1.0,
            blanks=sum(1 for col in cols if not col),
            doubles=sum(1 for col in cols if len(col) > 1),
        )
    return out


CSS = web.CSS + """
.tick{border-collapse:separate;border-spacing:2px;width:100%;min-width:46rem}
.tick th{position:static;background:transparent;border:0;padding:.3rem .4rem}
.tick td{border:0;padding:0}
.tm{font-family:var(--mono);font-weight:600;color:var(--ink);white-space:nowrap;
  padding-right:.5rem !important;font-size:.82rem}
.cell{display:flex;flex-direction:column;gap:2px}
.fx{font-family:var(--mono);font-size:.7rem;padding:.3rem .2rem;text-align:center;
  border-radius:2px;color:#0B0F13;font-weight:600;letter-spacing:.02em}
.fx.blank{background:transparent;border:1px dashed var(--line);color:var(--ink-3)}
.sum{font-family:var(--mono);font-size:.78rem;text-align:right;color:var(--ink-2);
  font-variant-numeric:tabular-nums;padding-left:.5rem !important}
.legend{display:flex;align-items:center;gap:.4rem;font-size:.74rem;color:var(--ink-3);
  font-family:var(--mono)}
.legend i{display:inline-block;width:1.6rem;height:.7rem;border-radius:2px}
.note{font-size:.84rem;color:var(--ink-2);max-width:66ch}
"""

JS = r"""
const N=GRID.gws.length;
let mode="atk", sortKey="atk";

// Green = easy, red = hard. Ratings are normalised so 1.0 is league average;
// the useful range in practice is about 0.7 to 1.4.
function colour(v){
  const t=Math.max(0,Math.min(1,(v-0.70)/0.70));   // 0 easy .. 1 hard
  const h=(1-t)*140;                                // 140 green -> 0 red
  return "hsl("+h.toFixed(0)+",62%,"+(58-t*8).toFixed(0)+"%)";
}

function render(){
  const rows=[...GRID.teams].sort((a,b)=>{
    if(sortKey==="name") return a.name.localeCompare(b.name);
    return GRID.sum[a.id][sortKey]-GRID.sum[b.id][sortKey];   // easiest first
  });
  document.getElementById("tb").innerHTML=rows.map(t=>{
    const s=GRID.sum[t.id];
    const cells=GRID.fixtures[t.id].map(col=>{
      if(!col.length) return '<td><div class="cell">'+
        '<div class="fx blank">&mdash;</div></div></td>';
      return '<td><div class="cell">'+col.map(f=>{
        const v = mode==="atk" ? f[2] : f[3];
        return '<div class="fx" style="background:'+colour(v)+'" '+
          'title="'+(mode==="atk"?"attacking":"defensive")+' difficulty '+
          v.toFixed(2)+'">'+f[0]+(f[1]?"":" (a)")+'</div>';
      }).join("")+'</div></td>';
    }).join("");
    const extra=[s.doubles?s.doubles+"\u00D7DGW":"",s.blanks?s.blanks+"\u00D7BGW":""]
      .filter(Boolean).join(" ");
    return '<tr><td class="tm">'+t.short+'</td>'+cells+
      '<td class="sum">'+GRID.sum[t.id][sortKey].toFixed(2)+
      (extra?' <span style="opacity:.6">'+extra+'</span>':'')+'</td></tr>';
  }).join("");
}

document.addEventListener("DOMContentLoaded",()=>{
  document.getElementById("hdr").innerHTML='<th></th>'+
    GRID.gws.map(g=>'<th>GW'+g+'</th>').join("")+'<th class="sum">Mean</th>';
  document.querySelectorAll(".seg button").forEach(b=>
    b.addEventListener("click",()=>{
      mode=b.dataset.mode; sortKey=mode;
      document.querySelectorAll(".seg button").forEach(o=>
        o.setAttribute("aria-pressed",o===b?"true":"false"));
      document.getElementById("modenote").textContent=
        mode==="atk"
          ? "Green = the opponent concedes. Rank teams whose ATTACKERS you want."
          : "Green = the opponent rarely scores. Rank teams whose DEFENDERS and keeper you want.";
      render();
    }));
  render();
});
"""


def build(bootstrap, fixtures, start_gw, n_gw, granular, prior_season):
    grid, short, teams, _ = build_grid(bootstrap, fixtures, start_gw, n_gw, prior_season)
    summ = summarise(grid, n_gw)
    payload = dict(
        gws=list(range(start_gw, start_gw + n_gw)),
        teams=[dict(id=t["id"], short=t["short_name"], name=t["name"])
               for t in bootstrap["teams"]],
        fixtures={str(k): v for k, v in grid.items()},
        sum={str(k): dict(atk=round(v["atk"], 4), dfn=round(v["dfn"], 4),
                          blanks=v["blanks"], doubles=v["doubles"], n=v["n"])
             for k, v in summ.items()},
    )
    # keys must be strings for the JS lookup to work off object indexing
    payload["fixtures"] = {str(k): v for k, v in grid.items()}

    caveat = ("" if granular else
              "<strong>Pre-season:</strong> FPL has not published granular team "
              "strength yet, so these are built from last season&rsquo;s expected "
              "goals for and against, shrunk toward the league mean. Promoted "
              "sides are rated at last season&rsquo;s bottom third. ")

    return """<style>{css}</style>
<div class="wrap">
<nav aria-label="Sections"><a href="projections.html">Projections</a>\
<a href="fixtures.html" aria-current="page">Fixtures</a>\
<a href="setpieces.html">Set pieces</a><a href="scorecard.html">Accuracy record</a></nav>
<header>
  <h1>Fixture ticker &mdash; GW{a} to GW{b}</h1>
  <p class="note">{caveat}Every other ticker colours FPL&rsquo;s single 1&ndash;5
  difficulty rating, which answers two different questions with one number. A
  promoted side concedes freely <em>and</em> scores little &mdash; great to
  attack, great to defend against. These are separated, and computed from the
  same fitted team ratings the projection model uses.</p>
</header>

<div class="controls">
  <div class="seg" role="group" aria-label="Difficulty type">
    <button data-mode="atk" aria-pressed="true">FOR ATTACKERS</button>
    <button data-mode="dfn" aria-pressed="false">FOR DEFENDERS</button>
  </div>
  <span class="legend"><i style="background:hsl(140,62%,58%)"></i>easy
    <i style="background:hsl(70,62%,54%)"></i><i style="background:hsl(0,62%,50%)"></i>hard</span>
  <span class="count" id="modenote">Green = the opponent concedes. Rank teams
    whose ATTACKERS you want.</span>
</div>

<div class="scroll">
  <table class="tick">
    <thead><tr id="hdr"></tr></thead>
    <tbody id="tb"></tbody>
  </table>
</div>

<footer>Teams sorted easiest first over the horizon &middot; (a) = away &middot;
lowercase mean is the average difficulty across the window &middot;
<a href="projections.html" style="color:var(--accent)">this week&rsquo;s projections</a></footer>
</div>
<script>const GRID={data};{js}</script>""".format(
        css=CSS, js=JS, data=json.dumps(payload, separators=(",", ":")),
        a=start_gw, b=start_gw + n_gw - 1, caveat=caveat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gameweeks", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(OUT, "fixtures.html"))
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--prior", default="2025-26")
    args = ap.parse_args()

    snap = P.latest_snapshot()
    bootstrap = json.load(open(os.path.join(snap, "bootstrap.json")))
    fixtures = json.load(open(os.path.join(snap, "fixtures.json")))
    manifest = json.load(open(os.path.join(snap, "manifest.json")))
    start = manifest.get("next_gw") or 1

    _, _, granular = P.team_ratings(bootstrap, args.prior)
    html = build(bootstrap, fixtures, start, args.gameweeks, granular, args.prior)

    problems = web.lint_js(html, ("#tb", "#hdr", "DOMContentLoaded"))
    if problems:
        print("REFUSING TO WRITE - generated JavaScript looks broken:")
        for pr in problems:
            print("  - {}".format(pr))
        return 1

    if os.path.exists(args.out):
        prev = open(args.out, encoding="utf-8").read()
        if web._payload(prev) == web._payload(html):
            print("fixture ticker: unchanged, not rewritten")
            return 0
    with open(args.out, "w") as f:
        f.write(html)
    print("fixture ticker: {}  (GW{}-{})".format(
        args.out, start, start + args.gameweeks - 1))
    if args.open:
        subprocess.run(["open", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
