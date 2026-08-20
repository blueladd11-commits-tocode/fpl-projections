#!/usr/bin/env python3
"""PS Rating - one number out of 100 for how good a pick a player is.

A projection of 4.96 points is precise and almost useless at a glance. Nobody
knows whether 4.96 is good until they have scrolled the whole table. A rating
does the comparing for you, and that is the entire job: it is a READING AID on
top of the model, not a second model.

WHY IT IS A PERCENTILE-ISH CURVE AND NOT RAW POINTS
---------------------------------------------------
Forwards score more than defenders. Any rating built on raw expected points
hands every high number to forwards, and then a defender rated 34 tells you
nothing about whether he is a good defender. So each component is normalised
WITHIN POSITION against the established-player pool, which is what makes a
defender's 85 and a forward's 85 mean the same thing: top of their own trade.

WHAT GOES IN, AND WHY EACH ONE IS THERE AND NOT SOMEWHERE ELSE
--------------------------------------------------------------
The parts have to be genuinely different questions or the rating just re-reads
expected points four times and calls it a blend.

  this week   (0.50)  ability x minutes x fixture, the core question
  next six    (0.25)  is he a keeper or a one-week punt - a great fixture and a
                      dreadful month after it is a different pick
  upside      (0.15)  haul chance RELATIVE to his own expected points. Taken raw
                      this is just expected points again; as a ratio it asks a
                      separate question - does he explode or does he tick along?
                      That is the captaincy question, and two players on the same
                      projection can be miles apart on it
  value       (0.10)  points per million, the tiebreaker, deliberately small:
                      the cheapest points in the game do not win mini-leagues

MINUTES ARE A PENALTY, NOT A COMPONENT
---------------------------------------
Expected points already contains the start probability, so adding it again as a
fifth ingredient would double count it and the rating would drift toward nailed
on mediocrity. But a player who might not start is not merely a lower average -
he is a different KIND of risk, because the downside is a blank rather than a
poor return. So he is scored on his merits and then penalised for the doubt,
which is the honest shape of it.

The rating is computed here, at the page, and deliberately NOT written into the
committed projection CSV. That file is reproduced byte for byte by verify.py,
and a presentation number has no business forcing a change to the permanent
record. Every input it uses is already in the record, so nothing is lost.

    python3 rating.py --selftest
"""

import argparse
import math
import sys

WEIGHTS = {"xp": 0.50, "tot": 0.25, "upside": 0.15, "value": 0.10}

# Below this start probability the doubt starts costing rating points, and at
# zero it costs the full penalty. 0.75 rather than 0.5 because a three-in-four
# starter is already a real problem for a captaincy pick, and the number people
# actually get burned by is the 60% one they assumed was fine.
START_SAFE = 0.75
START_PENALTY = 22.0

# Slope of the curve from normalised score to 0-100. 1.15 puts a median player
# near 50, a good one near 75 and a genuinely elite one in the high 80s, while
# leaving the 90s rare enough to mean something.
SLOPE = 1.15


def _robust(values):
    """Median and a spread that a few huge outliers cannot wreck.

    Haaland is a 4-sigma event in his own position most weeks. With a plain
    standard deviation he drags the mean up and the spread out, every other
    forward is pushed below average, and the rating says the position is weak
    when what is actually true is that one player is exceptional.
    """
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0, 1.0
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    devs = sorted(abs(v - med) for v in vals)
    mad = devs[n // 2] if n % 2 else (devs[n // 2 - 1] + devs[n // 2]) / 2.0
    # 1.4826 makes the median absolute deviation comparable to a standard
    # deviation for normal-ish data, so SLOPE means the same thing either way.
    spread = mad * 1.4826
    return med, (spread if spread > 1e-9 else 1.0)


def _z(value, med, spread):
    return (float(value) - med) / spread


def _curve(score):
    """Squash an unbounded score onto 0-100 with a logistic.

    Clipping a linear scale would pile players onto 0 and 100 and lose every
    distinction at the ends, which are exactly the ends people care about.
    """
    return 100.0 / (1.0 + math.exp(-SLOPE * score))


def compute(rows, pool_key="e"):
    """Add a `psr` (0-100) and `psr_band` to every row, in place.

    `rows` are the prepared page rows from web.prepare: dicts with xp, tot, h10,
    ppm, ps, p and an eligibility flag. Normalising against the ESTABLISHED pool
    only is the point of pool_key - include the 300 players who will not kick a
    ball and the median collapses, every regular starter looks superb, and the
    rating stops discriminating where it matters.
    """
    if not rows:
        return rows

    pool = [r for r in rows if r.get(pool_key)] or rows
    stats = {}
    for pos in {r["p"] for r in rows}:
        group = [r for r in pool if r["p"] == pos] or [r for r in rows
                                                       if r["p"] == pos]
        stats[pos] = {
            "xp": _robust([r["xp"] for r in group]),
            "tot": _robust([r.get("tot") or 0.0 for r in group]),
            "upside": _robust([_upside(r) for r in group]),
            "value": _robust([r.get("ppm") or 0.0 for r in group]),
        }

    for r in rows:
        s = stats[r["p"]]
        parts = {
            "xp": _z(r["xp"], *s["xp"]),
            "tot": _z(r.get("tot") or 0.0, *s["tot"]),
            "upside": _z(_upside(r), *s["upside"]),
            "value": _z(r.get("ppm") or 0.0, *s["value"]),
        }
        score = sum(WEIGHTS[k] * v for k, v in parts.items())
        psr = _curve(score)

        # The doubt penalty. ps arrives as a percentage.
        p_start = float(r.get("ps") or 0) / 100.0
        if p_start < START_SAFE:
            shortfall = (START_SAFE - p_start) / START_SAFE
            psr -= START_PENALTY * shortfall

        r["psr"] = int(round(max(1.0, min(99.0, psr))))
        r["psr_band"] = band(r["psr"])
    return rows


def _upside(row):
    """Haul chance per point of projection.

    Raw haul chance is mostly a restatement of expected points - of course the
    6.0 player hauls more often than the 2.0 player. Dividing it out asks the
    question that is actually separate: for what he is projected, is this a
    player who explodes or one who ticks along? Guarded because a projection can
    round to zero for a fringe player and the ratio would blow up.
    """
    xp = float(row.get("xp") or 0.0)
    h10 = float(row.get("h10") or 0.0)
    return h10 / xp if xp > 0.5 else 0.0


def band(psr):
    """A word for the number, because 78 and 74 are not different decisions."""
    if psr >= 85:
        return "elite"
    if psr >= 72:
        return "strong"
    if psr >= 58:
        return "solid"
    if psr >= 42:
        return "fringe"
    return "avoid"


BAND_CSS = """
.psr{display:inline-flex;align-items:center;justify-content:center;
  min-width:2.1rem;padding:.1rem .3rem;border-radius:3px;font-family:var(--mono);
  font-size:.74rem;font-weight:700;font-variant-numeric:tabular-nums;
  border:1px solid transparent}
.psr-elite{background:var(--accent);color:var(--ground);border-color:var(--accent)}
.psr-strong{background:var(--accent-soft);color:var(--accent);
  border-color:var(--accent)}
.psr-solid{background:transparent;color:var(--ink);border-color:var(--line)}
.psr-fringe{background:transparent;color:var(--ink-3);border-color:var(--line)}
.psr-avoid{background:transparent;color:var(--loss);border-color:var(--line)}
"""


def _selftest():
    """The properties that have to hold, checked rather than assumed."""
    import random
    random.seed(7)
    rows = []
    for pos, base in (("GKP", 3.0), ("DEF", 3.4), ("MID", 4.2), ("FWD", 4.8)):
        for i in range(60):
            xp = max(0.2, random.gauss(base, 1.2))
            rows.append(dict(p=pos, xp=xp, tot=xp * 6 * random.uniform(.8, 1.2),
                             h10=xp * random.uniform(1.5, 3.0),
                             ppm=xp / random.uniform(4.5, 13.0),
                             ps=random.choice([95, 90, 80, 60, 30]), e=1,
                             n="{}{}".format(pos, i)))
    compute(rows)
    fails = []

    if not all(1 <= r["psr"] <= 99 for r in rows):
        fails.append("rating escaped 1-99")

    # Comparable across positions: no position may own the top of the scale.
    for pos in ("GKP", "DEF", "MID", "FWD"):
        top = [r for r in rows if r["p"] == pos and r["psr"] >= 80]
        if not top:
            fails.append("no {} can reach 80 - not comparable across "
                         "positions".format(pos))

    # The doubt penalty must bite: same numbers, worse start chance, lower rating.
    a = dict(p="MID", xp=5.0, tot=30.0, h10=12.0, ppm=0.6, ps=95, e=1)
    b = dict(a, ps=40)
    compute([r for r in rows] + [a, b])
    if not a["psr"] > b["psr"]:
        fails.append("a doubtful starter is not rated below a nailed-on one")

    # One exceptional player must not drag his whole position down.
    quiet = [r["psr"] for r in rows if r["p"] == "FWD"]
    freak = dict(p="FWD", xp=40.0, tot=240.0, h10=90.0, ppm=3.0, ps=95, e=1)
    compute(rows + [freak])
    after = [r["psr"] for r in rows if r["p"] == "FWD"]
    drift = sum(abs(x - y) for x, y in zip(quiet, after)) / len(quiet)
    if drift > 3.0:
        fails.append("one outlier moved his position by {:.1f} rating points "
                     "- the spread is not robust".format(drift))

    for f in fails:
        print("  FAIL: {}".format(f))
    if not fails:
        print("selftest: all rating properties hold")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
