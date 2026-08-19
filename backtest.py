#!/usr/bin/env python3
"""Walk-forward backtest with a strict as-of cutoff.

For each gameweek g the model sees gameweeks 1..g-1 of the season under test
plus the (discounted) prior season, and nothing else. The state machine that
enforces that lives in walk.py and is shared with minutes.py; the scoring math
lives in model.py and is shared with project.py. Neither is duplicated here, so
neither can drift away from what ships.

Known limitation, stated loudly: historical availability flags (`status`,
`chance_of_playing_next_round`) were never recorded in the public mirror, so the
backtest runs with availability pinned at 1.0 and is blind to injury news. Live
performance should be BETTER than this. Treat every number here as a lower bound.

Usage:
    python3 backtest.py --season 2025-26 --prior 2024-25
    python3 backtest.py --season 2025-26 --prior 2024-25 --minutes-model
    python3 backtest.py --season 2025-26 --prior 2024-25 --calibrate
"""

import argparse
import json
import math
import os
import sys

import model as M
from score import evaluate
from walk import Walker

HERE = os.path.dirname(os.path.abspath(__file__))
METRICS = ("mae", "rmse", "spearman", "top10_hit", "top30_hit")


def eligible(c, min_matches, min_mins_per_match):
    """Eval population — deliberately independent of the model under test.

    Filtering on the model's own P(start) makes each variant get scored on a
    different, self-selected population: a sharper minutes model excludes the
    easy non-starters and is then judged on a harder residual, which looks like
    a regression when it is not. The population must be fixed by history alone.

    Roughly "players a manager would plausibly consider": enough of a track
    record to be projectable, and playing meaningful minutes when available.
    """
    a = c.agg
    if not a or a["matches"] < min_matches:
        return False
    return (a["mins"] / a["matches"]) >= min_mins_per_match


def run(season, prior_season, minutes_model=None, min_matches=3.0,
        min_mins_per_match=45.0):
    w = Walker(season, prior_season)
    cal = (M.CALIBRATION_MINUTES if minutes_model is not None
           else M.CALIBRATION_HEURISTIC)
    per_gw = []

    for gw, contexts in w.gameweeks():
        # (v0, naive_ppg, naive_recent6, price, actual). The naive columns are
        # the honest bar: FPL's own `xP` in the public mirror is contaminated by
        # in-gameweek information (see README) and is not an ex-ante benchmark.
        preds = []
        for c in contexts:
            if not eligible(c, min_matches, min_mins_per_match):
                continue
            if minutes_model is not None:
                import minutes as MIN
                p = MIN.p_start(minutes_model, c, w.prior_start_rate.get(c.key))
                p_start, p_sub, xmins = M.minutes_from_pstart(p, c.agg)
            else:
                mm = M.minutes_from_history(c.agg, c.recent_starts, 1.0)
                if mm is None:
                    mm = M.cold_start_minutes(c.price)
                p_start, p_sub, xmins = mm

            res = M.project(M.per90(c.agg, c.pos), c.pos, p_start, p_sub, xmins,
                            c.fixtures, defcon=w.defcon_active, calibration=cal)
            if not res:
                continue

            a = c.agg
            ppg = (a["pts"] / a["matches"]) if (a and a["matches"] > 0) else 2.0
            rp = c.recent_pts
            r6 = (sum(rp) / len(rp)) if rp else ppg
            preds.append((res["xp"], ppg * c.n_fix, r6 * c.n_fix, c.price,
                          c.actual_points))

        if len(preds) >= 30:
            e = evaluate([(p[0], p[4]) for p in preds], "v0")
            e["gw"] = gw
            e["baselines"] = {
                "naive_ppg": evaluate([(p[1], p[4]) for p in preds], "ppg"),
                "naive_recent6": evaluate([(p[2], p[4]) for p in preds], "r6"),
                "price_only": evaluate([(p[3], p[4]) for p in preds], "price"),
            }
            e["mean_pred"] = round(sum(p[0] for p in preds) / len(preds), 3)
            e["mean_actual"] = round(sum(p[4] for p in preds) / len(preds), 3)
            per_gw.append(e)

    return per_gw


def _mean(entries, getter):
    n = len(entries)
    return {k: sum(getter(e)[k] for e in entries) / n for k in METRICS}


def summarise(per_gw, label, verbose):
    if not per_gw:
        raise SystemExit("no gameweeks produced results")
    n = len(per_gw)
    ours = _mean(per_gw, lambda e: e)
    bias = (sum(e["mean_pred"] for e in per_gw) /
            sum(e["mean_actual"] for e in per_gw))

    if verbose:
        print("\n{:<5}{:>6}{:>8}{:>10}{:>8}{:>11}".format(
            "GW", "n", "MAE", "spearman", "top30", "ppg_spear"))
        for e in per_gw:
            print("{:<5}{:>6}{:>8.3f}{:>10.3f}{:>8.2f}{:>11.3f}".format(
                e["gw"], e["n"], e["mae"], e["spearman"], e["top30_hit"],
                e["baselines"]["naive_ppg"]["spearman"]))

    print("\n=== {} : {} gameweeks ===".format(label, n))
    print("{:<26}{:>8}{:>8}{:>10}{:>8}{:>8}".format(
        "model", "MAE", "RMSE", "spearman", "top10", "top30"))
    rowfmt = "{:<26}{:>8.3f}{:>8.3f}{:>10.3f}{:>8.2f}{:>8.2f}"
    print(rowfmt.format("v0-baseline", *[ours[k] for k in METRICS]))
    for name in ("naive_ppg", "naive_recent6", "price_only"):
        b = _mean(per_gw, lambda e, nm=name: e["baselines"][nm])
        print(rowfmt.format("  " + name, *[b[k] for k in METRICS]))

    # Always print the paired test. A mean-of-means table makes a 0.005 edge
    # look like a 0.11 edge look like a win; only the paired t says which is
    # real. The model has NO detectable edge over naive_recent6 without the
    # fitted minutes model, and that must never be quotable in isolation.
    print("\npaired over gameweeks (model - baseline spearman):")
    print("{:<22}{:>10}{:>9}{:>8}{:>10}".format(
        "vs", "delta", "SE", "t", "GWs won"))
    sig = {}
    for name in ("naive_ppg", "naive_recent6"):
        diffs = [e["spearman"] - e["baselines"][name]["spearman"] for e in per_gw]
        m = sum(diffs) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in diffs) / (n - 1)) if n > 1 else 0.0
        se = sd / math.sqrt(n) if n > 1 else 0.0
        t = (m / se) if se else float("nan")
        wins = sum(1 for x in diffs if x > 0)
        sig[name] = dict(delta=round(m, 4), se=round(se, 4),
                         t=round(t, 2), wins=wins, n=n)
        flag = "" if abs(t) >= 2.0 else "   <- NOT SIGNIFICANT"
        print("{:<22}{:>10.4f}{:>9.4f}{:>8.2f}{:>7}/{}{}".format(
            name, m, se, t, wins, n, flag))

    print("\nprediction bias (mean pred / mean actual): {:.3f}".format(bias))
    return ours, bias, sig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--prior", default="2024-25")
    ap.add_argument("--min-matches", type=float, default=3.0)
    ap.add_argument("--min-mins-per-match", type=float, default=45.0)
    ap.add_argument("--minutes-model", action="store_true",
                    help="use the fitted P(start) model from minutes.py")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    mm = None
    tag = ""
    if args.minutes_model:
        path = os.path.join(HERE, "out", "minutes_model.json")
        if not os.path.exists(path):
            raise SystemExit("no fitted model - run `python3 minutes.py` first")
        mm = json.load(open(path))
        tag = " +minutes-model"
        if args.season in mm.get("train_seasons", []):
            print("WARNING: {} is in the minutes model's training set. "
                  "Result is IN-SAMPLE and optimistic.".format(args.season))

    per_gw = run(args.season, args.prior, mm,
                 args.min_matches, args.min_mins_per_match)
    label = "{} (prior {}){}".format(args.season, args.prior, tag)
    ours, bias, sig = summarise(per_gw, label, not args.quiet)

    name = "backtest_{}{}.json".format(args.season, "_mm" if mm else "")
    out = os.path.join(HERE, "out", name)
    with open(out, "w") as fh:
        json.dump(dict(season=args.season, prior=args.prior,
                       minutes_model=bool(mm),
                       minutes_train_seasons=(mm.get("train_seasons") if mm else None),
                       in_sample=bool(mm and args.season in mm.get("train_seasons", [])),
                       calibration=M.CALIBRATION,
                       bias=bias, aggregate=ours, significance=sig,
                       per_gw=per_gw), fh, indent=2)
    print("written: {}".format(out))

    if args.calibrate:
        # Must divide the constant ACTUALLY used, not the module default.
        # run() uses CALIBRATION_MINUTES whenever --minutes-model is passed;
        # suggesting M.CALIBRATION (the heuristic constant) ratcheted the
        # minutes path down ~4% on every refit, compounding silently.
        used = M.CALIBRATION_MINUTES if mm else M.CALIBRATION_HEURISTIC
        name = "CALIBRATION_MINUTES" if mm else "CALIBRATION_HEURISTIC"
        print("\nsuggested {} for model.py: {}".format(
            name, round(used / bias, 4)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
