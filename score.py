#!/usr/bin/env python3
"""Score published projections against actuals. This is the product.

Every competitor asserts accuracy. None of them publish it. The scorecard is
the wedge, so it has to be run every gameweek, on projections that were
timestamped before the deadline, and published whether or not it flatters you.

Three metrics, chosen because they answer three different questions:
  MAE         - how wrong is a typical projection, in points
  Spearman    - is the *ordering* right (all that matters for picking a squad)
  Top-N hit   - of the N players we ranked highest, how many were top-N actual

Every metric is also computed for the naive baselines, and for FPL's own
`ep_next` — but ONLY the copy we snapshot ourselves before a deadline. The
`xP` column in the public historical mirror is captured after the gameweek it
claims to predict and is unusable as a benchmark; see the README. The bar that
matters is `naive_recent6`, the mean of a player's last six scores, because
without the fitted minutes model the projection does not reliably beat it.

Usage:
    python3 score.py --projections out/projections_gw1_*.csv --season 2025-26
    python3 score.py --selftest
"""

import argparse
import csv
import glob
import json
import math
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "fpl-projections/0.1"


# --- metrics ----------------------------------------------------------------

def mae(pairs):
    return sum(abs(p - a) for p, a in pairs) / len(pairs)


def rmse(pairs):
    return math.sqrt(sum((p - a) ** 2 for p, a in pairs) / len(pairs))


def _ranks(vals):
    """Average ranks, ties shared - required for Spearman to be correct."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(pairs):
    xs = _ranks([p for p, _ in pairs])
    ys = _ranks([a for _, a in pairs])
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else 0.0


def topn_hit(pairs, n):
    """Fraction of our top-n that appear in the actual top-n.

    Tie-safe. Actual FPL points are small integers, so the top-N boundary is
    almost always tied — GW10 2025-26 had 9 players clear of the cutoff and 6
    tied for the last slot. Naive `sorted(...)[:n]` breaks those ties by list
    order, which made this metric swing by ±0.05 purely on input ordering.

    Ties at the boundary are given fractional credit: a player tied for the last
    k slots among m tied candidates counts k/m. That is the expected hit rate
    under a random tie-break, and it is permutation-invariant.
    """
    if not pairs or n <= 0:
        return 0.0

    def top_weights(values):
        """{index: weight in [0,1]} for membership of the top n, ties shared."""
        order = sorted(range(len(values)), key=lambda i: -values[i])
        w, filled, i = {}, 0, 0
        while i < len(order) and filled < n:
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            group = order[i:j + 1]
            slots = min(len(group), n - filled)
            share = slots / float(len(group))
            for idx in group:
                w[idx] = share
            filled += slots
            i = j + 1
        return w

    pw = top_weights([p for p, _ in pairs])
    aw = top_weights([a for _, a in pairs])
    return sum(pw[i] * aw.get(i, 0.0) for i in pw) / float(n)


def evaluate(pairs, label):
    return {
        "model": label,
        "n": len(pairs),
        "mae": round(mae(pairs), 4),
        "rmse": round(rmse(pairs), 4),
        "spearman": round(spearman(pairs), 4),
        "top10_hit": round(topn_hit(pairs, 10), 3),
        "top30_hit": round(topn_hit(pairs, 30), 3),
    }


# --- actuals ----------------------------------------------------------------

def actuals_from_api(gw):
    """Fetch settled points for a gameweek: {element_id: total_points}."""
    url = "https://fantasy.premierleague.com/api/event/{}/live/".format(gw)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return {e["id"]: e["stats"]["total_points"] for e in data.get("elements", [])}


def actuals_from_history(season, gw):
    """Fallback: read actuals out of the historical mirror."""
    path = os.path.join(HERE, "data", "history", season, "merged_gw.csv")
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            if int(row["GW"]) == gw:
                out[int(row["element"])] = int(row["total_points"])
    return out


# --- scorecard --------------------------------------------------------------

def score(proj_path, gw, actuals, min_pstart=None):
    """Score a projections file, alongside every honest comparator we have.

    `fpl_ep_next` here is legitimate ONLY because project.py copies it out of a
    snapshot taken before the deadline. The same field in the public historical
    mirror is contaminated by in-gameweek information and must never be used.

    The evaluation population comes from the `eligible` column, which project.py
    computes from history alone (>=3 prior matches, >=45 min/match) — the same
    rule as backtest.eligible(). It must NOT be the model's own p_start: doing
    that lets each model select its own test set, and a sharper minutes model
    then gets judged on a harder residual. That defect was measured at
    -0.04 vs +0.11 Spearman, and it used to live in this function.
    """
    rows = list(csv.DictReader(open(proj_path)))
    ours, fpls, price, recent6, skipped, ineligible = [], [], [], [], 0, 0
    for r in rows:
        eid = int(r["element"])
        if eid not in actuals:
            skipped += 1
            continue
        if "eligible" in r:
            if r["eligible"] not in ("1", "True", "true"):
                ineligible += 1
                continue
        elif min_pstart is not None and float(r["p_start"]) < min_pstart:
            # Legacy projections written before the `eligible` column existed.
            ineligible += 1
            continue
        a = float(actuals[eid])
        ours.append((float(r["xp"]), a))
        price.append((float(r["price"]), a))
        if r.get("naive_recent6") not in (None, "", "None"):
            recent6.append((float(r["naive_recent6"]), a))
        ep = r.get("fpl_ep_next")
        if ep not in (None, "", "None"):
            fpls.append((float(ep), a))

    if not ours:
        raise SystemExit("no overlapping players - is GW{} settled yet?".format(gw))

    results = [evaluate(ours, "v0-baseline")]
    if recent6:
        results.append(evaluate(recent6, "naive_recent6"))
    elif rows and "naive_recent6" not in rows[0]:
        print("WARNING: this projections file predates the naive_recent6 column; "
              "the committed weekly baseline cannot be computed for GW{}.".format(gw))
    if fpls:
        results.append(evaluate(fpls, "fpl ep_next (pre-deadline)"))
    results.append(evaluate(price, "price only (baseline)"))

    mean_pred = sum(p for p, _ in ours) / len(ours)
    mean_act = sum(a for _, a in ours) / len(ours)
    return {
        "gameweek": gw,
        "skipped_no_actual": skipped,
        "excluded_ineligible": ineligible,
        "mean_pred": round(mean_pred, 3),
        "mean_actual": round(mean_act, 3),
        "bias": round(mean_pred / mean_act, 3) if mean_act else None,
        "results": results,
    }


def selftest():
    """Validate the metric functions against hand-checkable cases."""
    perfect = [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0)]
    inverted = [(1.0, 4.0), (2.0, 3.0), (3.0, 2.0), (4.0, 1.0)]
    assert abs(spearman(perfect) - 1.0) < 1e-9, spearman(perfect)
    assert abs(spearman(inverted) + 1.0) < 1e-9, spearman(inverted)
    assert abs(mae(perfect)) < 1e-9
    assert abs(mae([(0.0, 2.0), (0.0, 4.0)]) - 3.0) < 1e-9
    assert abs(rmse([(0.0, 3.0), (0.0, 4.0)]) - math.sqrt(12.5)) < 1e-9
    assert abs(topn_hit(perfect, 2) - 1.0) < 1e-9
    assert abs(topn_hit(inverted, 2) - 0.0) < 1e-9
    # tie-safety: must be invariant to input order, and give fractional credit
    tied = [(4.0, 9.0), (3.0, 9.0), (2.0, 9.0), (1.0, 1.0)]
    import random as _r
    vals = set()
    for s in range(25):
        shuffled = tied[:]
        _r.Random(s).shuffle(shuffled)
        vals.add(round(topn_hit(shuffled, 1), 9))
    assert len(vals) == 1, "topn_hit not permutation-invariant: {}".format(vals)
    # 3 players tied for 1 actual slot; we pick one of them -> expect 1/3
    assert abs(topn_hit(tied, 1) - 1.0 / 3.0) < 1e-9, topn_hit(tied, 1)
    # ties must share average ranks, or Spearman silently drifts
    assert _ranks([5.0, 5.0, 1.0]) == [2.5, 2.5, 1.0], _ranks([5.0, 5.0, 1.0])
    print("selftest: all metric checks passed")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projections", help="path or glob to a projections CSV")
    ap.add_argument("--gw", type=int)
    ap.add_argument("--season", default="2025-26",
                    help="only used if the live API has no settled data")
    ap.add_argument("--min-p-start", type=float, default=None,
                    help="legacy fallback for projections lacking `eligible`")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.projections:
        ap.error("--projections is required (or use --selftest)")

    matches = sorted(glob.glob(args.projections))
    if not matches:
        raise SystemExit("no projections file matched: " + args.projections)
    path = matches[-1]

    meta_path = path.replace(".csv", ".meta.json")
    gw = args.gw
    if gw is None and os.path.exists(meta_path):
        gw = json.load(open(meta_path))["gameweek"]
    if gw is None:
        raise SystemExit("could not determine gameweek; pass --gw")

    try:
        actuals = actuals_from_api(gw)
        source = "live API"
        if not any(actuals.values()):
            raise ValueError("gameweek not settled")
    except Exception as e:
        print("live actuals unavailable ({}), falling back to {} history".format(e, args.season))
        actuals = actuals_from_history(args.season, gw)
        source = "history/" + args.season

    card = score(path, gw, actuals, args.min_p_start)
    card["projections_file"] = os.path.basename(path)
    card["actuals_source"] = source

    out = os.path.join(HERE, "out", "scorecard_gw{}.json".format(gw))
    with open(out, "w") as f:
        json.dump(card, f, indent=2)

    print("\nGW{} scorecard  (actuals: {}, n={})".format(
        gw, source, card["results"][0]["n"]))
    print("{:<28}{:>8}{:>8}{:>10}{:>9}{:>9}".format(
        "model", "MAE", "RMSE", "spearman", "top10", "top30"))
    for r in card["results"]:
        print("{:<28}{:>8.3f}{:>8.3f}{:>10.3f}{:>9.2f}{:>9.2f}".format(
            r["model"], r["mae"], r["rmse"], r["spearman"],
            r["top10_hit"], r["top30_hit"]))
    print("\nbias (mean pred / mean actual): {}".format(card["bias"]))
    print("judge on RMSE and spearman, not MAE - see model.py CALIBRATION")
    print("written: {}".format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
