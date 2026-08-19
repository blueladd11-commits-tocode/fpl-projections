#!/usr/bin/env python3
"""M2: a fitted expected-minutes model, with its own eval.

Expected minutes is the largest single error source in FPL projection (15.9% of
players the v0 heuristic expects to start do not play at all), so it gets its
own model, its own target and its own metrics rather than living as a heuristic
buried inside the points model.

Target: did this player start? Logistic regression, fitted by SGD, pure stdlib.
Trained on one set of seasons and evaluated on a season it never saw — the
calibration constant in model.py is fitted in-sample and this deliberately is
not.

Usage:
    python3 minutes.py --train 2023-24,2024-25 --test 2025-26
    python3 minutes.py --eval-only          # load out/minutes_model.json
"""

import argparse
import json
import math
import os
import random

import model as M
from walk import Walker

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
WEIGHTS = os.path.join(OUT, "minutes_model.json")

# Production recipe: the TWO most recent completed seasons, and no more.
# Measured out-of-sample on 2025-26 (Spearman of the resulting projections):
#     2024-25 only                   0.459
#     2023-24 + 2024-25              0.462   <- best
#     + 2022-23                      0.443
#     all four                       0.429
# Older seasons describe a different game (no defensive contribution before
# 2025-26, a different BPS formula, different rotation norms), so recency beats
# volume here. Adding history actively hurts — do not "improve" this by
# training on everything available.
PRODUCTION_TRAIN = ["2024-25", "2025-26"]

PRIOR_SEASON = {
    "2023-24": "2022-23",
    "2024-25": "2023-24",
    "2025-26": "2024-25",
    "2026-27": "2025-26",
}

FEATURES = [
    "started_last", "recent3", "recent6", "season_rate", "prior_rate",
    "last_mins90", "price", "is_new", "team_rank", "days_rest", "no_rest_info",
    "no_recent", "no_season", "no_prior",
    "is_def", "is_mid", "is_fwd",
]


def featurise(ctx, prior_rate):
    """Feature vector for one player-gameweek. Reads only as-of state.

    Deliberately never touches ctx.actual_*; those exist for the label only.

    Missing values are encoded as 0 PLUS an explicit indicator, never as a -1
    sentinel. A linear model reads -1 as a real quantity, and since `last_mins90`
    carries the largest weight, every GW1 player was getting the same large
    spurious contribution from "no previous match". That made the fitted model
    WORSE than the heuristic in GW1 (Brier 0.188 vs 0.171, starts over-predicted
    by 21%) — precisely the gameweek the product launches in. With indicators the
    model can learn the cold-start regime as its own thing.
    """
    rs = ctx.recent_starts
    a = ctx.agg
    has_season = bool(a and a["matches"] > 0)
    has_prior = prior_rate is not None
    days = ctx.days_rest
    return [
        rs[-1] if rs else 0.0,
        (sum(rs[-3:]) / len(rs[-3:])) if rs else 0.0,
        (sum(rs) / len(rs)) if rs else 0.0,
        (a["starts"] / a["matches"]) if has_season else 0.0,
        prior_rate if has_prior else 0.0,
        (ctx.last_mins / 90.0) if ctx.last_mins is not None else 0.0,
        ctx.price,
        1.0 if ctx.is_new else 0.0,
        ctx.team_rank if ctx.team_rank is not None else 0.5,
        min(days, 21.0) if days is not None else 0.0,
        0.0 if days is not None else 1.0,
        0.0 if rs else 1.0,
        0.0 if has_season else 1.0,
        0.0 if has_prior else 1.0,
        1.0 if ctx.pos == M.DEF else 0.0,
        1.0 if ctx.pos == M.MID else 0.0,
        1.0 if ctx.pos == M.FWD else 0.0,
    ]


def p_start(mdl, ctx, prior_rate):
    """P(start) for one player — the single entry point for both paths.

    Gated, because the fitted model is measurably WORSE than the heuristic
    before a player has any current-season match. Out-of-sample on 2025-26 GW1:

        heuristic            Brier 0.1705   AUC 0.8012
        general fitted model Brier 0.1873   AUC 0.7271
        GW1-dedicated model  Brier 0.1908   AUC 0.7535

    Every within-season feature is empty in GW1 and those rows are ~2% of
    training data, so the fitted weights simply do not describe that regime. A
    dedicated cold-start model was tried and also lost. Last season's start rate
    — which is all the heuristic uses — is genuinely the better estimator here.

    This matters more than its size suggests: GW1 is when the product launches
    and when the most people look at it.
    """
    if not ctx.recent_starts:
        mm = M.minutes_from_history(ctx.agg, ctx.recent_starts, 1.0)
        if mm is None:
            mm = M.cold_start_minutes(ctx.price)
        return mm[0]
    return predict(mdl, featurise(ctx, prior_rate))


def collect(seasons):
    """Build (X, y) with a strict as-of cutoff, plus the heuristic's prediction."""
    X, y, heur = [], [], []
    for season in seasons:
        w = Walker(season, PRIOR_SEASON.get(season))
        for gw, contexts in w.gameweeks():
            for c in contexts:
                X.append(featurise(c, w.prior_start_rate.get(c.key)))
                y.append(c.actual_started)
                mm = M.minutes_from_history(c.agg, c.recent_starts, 1.0)
                if mm is None:
                    mm = M.cold_start_minutes(c.price)
                heur.append(mm[0])
    return X, y, heur


def standardise(X):
    n, d = len(X), len(X[0])
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    var = [sum((row[j] - mean[j]) ** 2 for row in X) / n for j in range(d)]
    std = [math.sqrt(v) if v > 1e-12 else 1.0 for v in var]
    return mean, std


def apply_std(x, mean, std):
    return [(x[j] - mean[j]) / std[j] for j in range(len(x))]


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def fit(X, y, epochs=12, lr=0.25, l2=1e-4, seed=0):
    mean, std = standardise(X)
    Z = [apply_std(x, mean, std) for x in X]
    d = len(Z[0])
    w = [0.0] * d
    b = 0.0
    idx = list(range(len(Z)))
    rng = random.Random(seed)
    for ep in range(epochs):
        rng.shuffle(idx)
        step = lr / (1.0 + ep)
        for i in idx:
            z = b + sum(w[j] * Z[i][j] for j in range(d))
            err = sigmoid(z) - y[i]
            b -= step * err
            for j in range(d):
                w[j] -= step * (err * Z[i][j] + l2 * w[j])
    return dict(w=w, b=b, mean=mean, std=std, features=FEATURES)


def predict(mdl, x):
    z = mdl["b"] + sum(wj * v for wj, v in
                       zip(mdl["w"], apply_std(x, mdl["mean"], mdl["std"])))
    return sigmoid(z)


# --- metrics ----------------------------------------------------------------

def brier(p, y):
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(y)


def logloss(p, y):
    eps = 1e-12
    return -sum(yi * math.log(max(pi, eps)) + (1 - yi) * math.log(max(1 - pi, eps))
                for pi, yi in zip(p, y)) / len(y)


def auc(p, y):
    """Mann-Whitney U, with tied predictions sharing average rank."""
    pairs = sorted(zip(p, y))
    ranks, i = [0.0] * len(pairs), 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    pos = sum(1 for _, yi in pairs if yi > 0.5)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    s = sum(r for r, (_, yi) in zip(ranks, pairs) if yi > 0.5)
    return (s - pos * (pos + 1) / 2.0) / (pos * neg)


def calibration_table(p, y, bins=10):
    rows = []
    for b in range(bins):
        lo, hi = b / float(bins), (b + 1) / float(bins)
        sel = [(pi, yi) for pi, yi in zip(p, y) if lo <= pi < hi or (b == bins - 1 and pi == 1.0)]
        if len(sel) < 20:
            continue
        rows.append((lo, hi, len(sel),
                     sum(q[0] for q in sel) / len(sel),
                     sum(q[1] for q in sel) / len(sel)))
    return rows


def report(name, p, y):
    print("{:<26}{:>9.4f}{:>10.4f}{:>8.4f}".format(
        name, brier(p, y), logloss(p, y), auc(p, y)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default=",".join(PRODUCTION_TRAIN))
    ap.add_argument("--test", default="2025-26")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--eval-only", action="store_true")
    args = ap.parse_args()

    test_seasons = [s for s in args.test.split(",") if s]

    if args.eval_only:
        mdl = json.load(open(WEIGHTS))
    else:
        train_seasons = [s for s in args.train.split(",") if s]
        print("collecting training data: {}".format(", ".join(train_seasons)))
        Xtr, ytr, htr = collect(train_seasons)
        print("  {:,} player-gameweeks, {:.1%} started".format(
            len(ytr), sum(ytr) / len(ytr)))
        print("fitting logistic regression ({} epochs)...".format(args.epochs))
        mdl = fit(Xtr, ytr, epochs=args.epochs)
        os.makedirs(OUT, exist_ok=True)
        with open(WEIGHTS, "w") as f:
            json.dump(dict(mdl, train_seasons=train_seasons), f, indent=2)
        ptr = [predict(mdl, x) for x in Xtr]
        print("\nIN-SAMPLE ({})".format(", ".join(train_seasons)))
        print("{:<26}{:>9}{:>10}{:>8}".format("model", "Brier", "logloss", "AUC"))
        report("  fitted", ptr, ytr)
        report("  v0 heuristic", htr, ytr)

    overlap = [t for t in test_seasons if t in mdl.get("train_seasons", [])]
    if overlap:
        print("\nWARNING: {} is in the training set. The figures below are "
              "IN-SAMPLE and optimistic - pass --test with a held-out season "
              "for the number that counts.".format(", ".join(overlap)))
    print("\ncollecting test data: {}".format(", ".join(test_seasons)))
    Xte, yte, hte = collect(test_seasons)
    print("  {:,} player-gameweeks, {:.1%} started".format(
        len(yte), sum(yte) / len(yte)))
    pte = [predict(mdl, x) for x in Xte]

    print("\n{} ({})".format(
        "IN-SAMPLE (optimistic)" if overlap
        else "OUT-OF-SAMPLE  <- the number that counts",
        ", ".join(test_seasons)))
    print("{:<26}{:>9}{:>10}{:>8}".format("model", "Brier", "logloss", "AUC"))
    report("fitted minutes model", pte, yte)
    report("v0 heuristic", hte, yte)
    base = sum(yte) / len(yte)
    report("constant base rate", [base] * len(yte), yte)

    print("\ncalibration (out-of-sample)")
    print("{:<14}{:>8}{:>12}{:>12}".format("bucket", "n", "mean_pred", "observed"))
    for lo, hi, n, mp, ob in calibration_table(pte, yte):
        print("{:<14}{:>8}{:>12.3f}{:>12.3f}".format(
            "{:.1f}-{:.1f}".format(lo, hi), n, mp, ob))

    print("\nweights (standardised, larger |w| = more influential)")
    for nm, wv in sorted(zip(mdl["features"], mdl["w"]), key=lambda z: -abs(z[1])):
        print("  {:<16}{:>8.3f}".format(nm, wv))
    print("\nweights written: {}".format(WEIGHTS))


if __name__ == "__main__":
    main()
