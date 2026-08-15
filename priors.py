#!/usr/bin/env python3
"""Fit the per-90 positional priors that per90() shrinks toward.

model.py carried hand-set values and a comment pointing at a `--fit-priors` flag
that never existed. One of them (defender defensive contribution, 9.5 vs an
observed 7.72) was wrong enough to matter, because the DefCon threshold sits at
10 and the Poisson tail is steep right there.

What the prior should be: the rate we expect from a player we know nothing
about. That is the minutes-weighted population mean per 90 for his position —
weighted, because a player with 3000 minutes is far better evidence about the
underlying rate than one with 50.

Fitted on training seasons only, so a season under test never contributes to the
prior it is scored against.

Usage:
    python3 priors.py --train 2022-23,2023-24,2024-25    # print fitted table
    python3 priors.py --train 2022-23,2023-24,2024-25 --write
"""

import argparse
import os
import re

import model as M
from walk import Walker, player_key

HERE = os.path.dirname(os.path.abspath(__file__))

# Rates that are genuinely position-driven. `psv` (penalty saves) is so rare
# that a fitted value is mostly noise, so it keeps its hand-set floor.
FIT_KEYS = ("xg", "xa", "dc", "bps", "sv", "yc", "rc", "og", "pm")


def collect(seasons):
    """Total minutes and total events per position, across whole seasons.

    Uses end-of-season aggregates deliberately: a prior is a population
    constant, not a per-gameweek feature, so there is no as-of cutoff to
    violate as long as the season under test is excluded from the fit.

    `defensive_contribution` only exists from 2025-26, so it carries its own
    minutes denominator — dividing 2025-26 events by four seasons of minutes
    would understate the rate by ~4x.
    """
    tot = {p: dict(mins=0.0, dc_mins=0.0) for p in (M.GK, M.DEF, M.MID, M.FWD)}
    for p in tot:
        for k in FIT_KEYS:
            tot[p][k] = 0.0

    for season in seasons:
        w = Walker(season, None)
        has_dc = bool(w.rows) and "defensive_contribution" in w.rows[0]
        for _ in w.gameweeks():
            pass  # walking to the end folds every gameweek into w.agg

        pos_of = {player_key(r, w.elem2code): M.POS_FROM_STR.get(r["position"])
                  for r in w.rows}
        for key, a in w.agg.items():
            pos = pos_of.get(key)
            if pos is None or a["mins"] <= 0:
                continue
            tot[pos]["mins"] += a["mins"]
            if has_dc:
                tot[pos]["dc_mins"] += a["mins"]
                tot[pos]["dc"] += a.get("dc", 0.0)
            for k in FIT_KEYS:
                if k != "dc":
                    tot[pos][k] += a.get(k, 0.0)
    return tot


def fit(seasons):
    tot = collect(seasons)
    out = {}
    for pos, t in tot.items():
        row = {}
        for k in FIT_KEYS:
            denom = t["dc_mins"] if k == "dc" else t["mins"]
            row[k] = (t[k] / denom * 90.0) if denom > 0 else M.PRIORS[pos][k]
        row["psv"] = M.PRIORS[pos]["psv"]  # too rare to fit
        out[pos] = row
    return out


def render(fitted, seasons):
    lines = [
        "# Fitted by priors.py on {} — minutes-weighted population mean per 90".format(
            ", ".join(seasons)),
        "# by position. Do not hand-edit: re-run `python3 priors.py --write`,",
        "# then re-fit both CALIBRATION constants, which absorb any drift here.",
        "PRIORS = {",
    ]
    for pos, name in ((M.GK, "GK"), (M.DEF, "DEF"), (M.MID, "MID"), (M.FWD, "FWD")):
        r = fitted[pos]
        pad = " " * (4 - len(name))
        lines.append(
            "    {}:{} dict(xg={:.3f}, xa={:.3f}, dc={:.2f}, bps={:.1f}, sv={:.2f},"
            .format(name, pad, r["xg"], r["xa"], r["dc"], r["bps"], r["sv"]))
        lines.append(
            "              yc={:.3f}, rc={:.4f}, og={:.4f}, pm={:.4f}, psv={:.3f}),"
            .format(r["yc"], r["rc"], r["og"], r["pm"], r["psv"]))
    lines.append("}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="2022-23,2023-24,2024-25")
    ap.add_argument("--write", action="store_true",
                    help="rewrite the PRIORS block in model.py in place")
    args = ap.parse_args()
    seasons = [s for s in args.train.split(",") if s]

    print("fitting priors on: {}".format(", ".join(seasons)))
    fitted = fit(seasons)

    print("\n{:<6}{:>8}{:>8}{:>8}{:>8}{:>8}{:>8}".format(
        "pos", "xg90", "xa90", "dc90", "bps90", "sv90", "yc90"))
    for pos, name in ((M.GK, "GKP"), (M.DEF, "DEF"), (M.MID, "MID"), (M.FWD, "FWD")):
        f, h = fitted[pos], M.PRIORS[pos]
        print("{:<6}{:>8.3f}{:>8.3f}{:>8.2f}{:>8.1f}{:>8.2f}{:>8.3f}".format(
            name, f["xg"], f["xa"], f["dc"], f["bps"], f["sv"], f["yc"]))
        print("{:<6}{:>8.3f}{:>8.3f}{:>8.2f}{:>8.1f}{:>8.2f}{:>8.3f}   <- current"
              .format("", h["xg"], h["xa"], h["dc"], h["bps"], h["sv"], h["yc"]))

    block = render(fitted, seasons)
    if not args.write:
        print("\n{}\n\n(pass --write to apply, then re-run backtest.py --calibrate)"
              .format(block))
        return 0

    path = os.path.join(HERE, "model.py")
    src = open(path).read()
    new = re.sub(r"(?:^#[^\n]*\n)*PRIORS = \{.*?\n\}", block, src, count=1,
                 flags=re.S | re.M)
    if new == src:
        raise SystemExit("could not locate the PRIORS block in model.py")
    open(path, "w").write(new)
    print("\nmodel.py updated. Calibration constants are now stale - "
          "re-run backtest.py --calibrate on both paths.")
    return 0


if __name__ == "__main__":
    main()
