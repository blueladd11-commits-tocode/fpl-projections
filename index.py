#!/usr/bin/env python3
"""Landing page — the root of the published site.

Without it, the Pages root is a 404 and the only way in is to know a filename.
Deliberately thin: it exists to route, and to state the one claim the project
is built around before anyone clicks anything.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import links
import web

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

CARDS = (
    ("projections", "Projections",
     "Expected points for every player over the next six gameweeks, with the "
     "chance of a double-digit haul, a squad builder and transfer suggestions."),
    ("myteam", "My team",
     "Your fifteen on a pitch: a legal eleven, a bench in the order it "
     "actually comes on, and one armband that doubles a score. Or let the "
     "model build the squad for you."),
    ("planner", "Transfer planner",
     "A calendar, not six stacked squads &mdash; a row is a squad slot, so a "
     "transfer is a change of occupant partway along it. Free transfers, "
     "hits, bank and chip legality all computed as you go."),
    ("fixtures", "Fixture ticker",
     "Difficulty split into attacking and defensive views &mdash; because a "
     "promoted side concedes freely <em>and</em> scores little, and one number "
     "cannot say both."),
    ("setpieces", "Set-piece takers",
     "Ranked penalty, free-kick and corner duty for all 20 clubs, refreshed "
     "hourly, with listed takers we do not expect to start flagged."),
    ("scorecard", "Accuracy record",
     "Every projection timestamped before its deadline and scored against a "
     "hard baseline. Including the weeks we lose."),
)

CSS = web.CSS + """
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));gap:1rem}
.card{display:block;background:var(--panel);border:1px solid var(--line);
  padding:1.1rem 1.2rem;text-decoration:none}
.card:hover{border-color:var(--accent)}
.card h2{font-family:var(--mono);font-size:.92rem;color:var(--ink);margin:0 0 .4rem;
  font-weight:650}
.card p{font-size:.85rem;color:var(--ink-2);margin:0}
.lede{font-size:1rem;color:var(--ink-2);max-width:62ch}
.lede strong{color:var(--ink)}
"""


def main():
    n_records = len([f for f in os.listdir(OUT)
                     if f.startswith("projections_gw") and f.endswith(".meta.json")])
    n_scored = len([f for f in os.listdir(OUT)
                    if f.startswith("scorecard_gw")])

    cards = "".join(
        '<a class="card" href="{}"><h2>{}</h2><p>{}</p></a>'.format(
            links.href(key), title, blurb) for key, title, blurb in CARDS)

    body = """<div class="wrap">
<header>
  <h1>Fantasy Premier League projections</h1>
  <p class="lede">A points model whose <strong>accuracy record is published and
  checkable</strong>. Every projection is written before its gameweek deadline,
  alongside the SHA-256 of the exact API snapshot it came from, and scored
  afterwards against a baseline anyone could build in an afternoon. Weeks we
  lose appear in the same table as weeks we win.</p>
  <p class="lede">{n_records} gameweek projection(s) on record, {n_scored}
  scored so far. Updated hourly.</p>
</header>
<div class="cards">{cards}</div>
<footer>Built from the free Fantasy Premier League API &middot; no affiliation
with the Premier League &middot; generated {now} UTC</footer>
</div>""".format(cards=cards, n_records=n_records, n_scored=n_scored,
                 now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

    html = links.document("Fantasy Premier League projections", body, CSS)
    problems = web.lint_page(html)
    if problems:
        print("REFUSING TO WRITE index:")
        for p in problems:
            print("  - {}".format(p))
        return 1
    out = os.path.join(OUT, "index.html")
    with open(out, "w") as f:
        f.write(html)
    print("landing page: {}".format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
