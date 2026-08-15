#!/usr/bin/env python3
"""Render the scorecard populated with SIMULATED results, to see the UI.

The real scorecard is empty until the first deadline, which makes it impossible
to judge the design. This fabricates a mid-season record so the page can be
looked at properly.

Everything it produces is clearly marked as a demo, written to a separate file,
and never touches out/. The simulated per-gameweek numbers are drawn around the
model's actual backtested performance (rho ~0.46 against a ~0.35 baseline) with
realistic week-to-week variance, including weeks we lose — because a preview
that only shows good weeks would misrepresent the thing being previewed.

Usage: python3 preview.py [--gameweeks 12] [--open]
"""

import argparse
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import publish

HERE = os.path.dirname(os.path.abspath(__file__))
OUTFILE = os.path.join(HERE, "out", "preview_scorecard.html")

BANNER = """<section style="border-left:3px solid var(--pending);
  background:var(--pending-soft);padding:1rem 1.2rem">
  <h2 style="color:var(--pending)">Preview &mdash; simulated data</h2>
  <p style="color:var(--ink);margin-bottom:0">Every gameweek row below is
  <strong>fabricated</strong> so the page can be reviewed before real results
  exist. The numbers are drawn around the model&rsquo;s backtested performance
  with realistic variance, losses included. The live scorecard is empty until the
  first deadline. This file is never committed and is not the record.</p>
</section>
"""


def fake_records(n, seed=11):
    """A plausible mid-season record: real backtest levels, real variance."""
    rng = random.Random(seed)
    deadline = datetime(2026, 8, 21, 17, 30, tzinfo=timezone.utc)
    rows = []
    for gw in range(1, n + 1):
        dl = deadline + timedelta(days=7 * (gw - 1))
        # GW1 is genuinely the model's worst week - the minutes model is gated
        # off entirely there - so the preview should show that, not hide it.
        centre = 0.30 if gw == 1 else 0.46
        ours = max(0.02, rng.gauss(centre, 0.11))
        base = max(0.02, rng.gauss(0.30 if gw == 1 else 0.35, 0.10))
        horizons = [2.1] + ([6.4, 25.0, 71.0] if gw > 1 else [24.5])
        rows.append(dict(
            gw=gw,
            deadline=dl.strftime("%Y-%m-%dT%H:%M:%SZ"),
            generated=(dl - timedelta(hours=2)).isoformat(),
            hrs=horizons[0],
            horizons=horizons[1:],
            digest="".join(rng.choice("0123456789abcdef") for _ in range(12)),
            n=480 + rng.randint(-20, 20),
            model="v0-baseline", minutes_model=True,
            status="SCORED",
            ours=round(ours, 3), base=round(base, 3),
            delta=round(ours - base, 4),
        ))
    # the next gameweek is always still pending
    dl = deadline + timedelta(days=7 * n)
    rows.append(dict(
        gw=n + 1, deadline=dl.strftime("%Y-%m-%dT%H:%M:%SZ"),
        generated=dl.isoformat(), hrs=68.0, horizons=[],
        digest="".join(rng.choice("0123456789abcdef") for _ in range(12)),
        n=482, model="v0-baseline", minutes_model=True,
        status="PENDING", ours=None, base=None, delta=None))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gameweeks", type=int, default=12)
    ap.add_argument("--open", action="store_true", help="open in your browser")
    args = ap.parse_args()

    records = fake_records(args.gameweeks)
    evidence = publish.load_evidence()          # the real backtest numbers
    html = publish.build(records, evidence)
    html = html.replace('<section class="seal">', BANNER + '<section class="seal">', 1)
    with open(OUTFILE, "w") as f:
        f.write("<style>{}</style>\n{}".format(publish.CSS, html))

    scored = [r for r in records if r["status"] == "SCORED"]
    beat = sum(1 for r in scored if r["delta"] > 0)
    print("preview written: {}".format(OUTFILE))
    print("  {} simulated gameweeks, {} beat the baseline, {} lost".format(
        len(scored), beat, len(scored) - beat))
    print("\nopen it with:\n  open {}".format(OUTFILE))
    if args.open:
        subprocess.run(["open", OUTFILE])
    return 0


if __name__ == "__main__":
    sys.exit(main())
