#!/usr/bin/env python3
"""Produce projections for the next gameweek from the latest API snapshot.

All scoring math lives in model.py, shared with backtest.py. That is deliberate:
if this file grew its own copy, the published accuracy record would measure
something we don't ship.

Usage:  python3 project.py [--gw N] [--prior 2025-26] [--top 30]
Output: out/projections_gw<N>_<snapshot>.csv  (+ .meta.json for provenance)
"""

import argparse
import collections
import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

import model as M
import minutes as MIN
import walk

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPDIR = os.path.join(HERE, "data", "snapshots")
HISTDIR = os.path.join(HERE, "data", "history")
OUTDIR = os.path.join(HERE, "out")


def fnum(row, key, default=0.0):
    v = row.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def latest_snapshot():
    dirs = sorted(d for d in os.listdir(SNAPDIR)
                  if os.path.isdir(os.path.join(SNAPDIR, d)))
    if not dirs:
        raise SystemExit("no snapshots found - run `python3 snapshot.py` first")
    return os.path.join(SNAPDIR, dirs[-1])


def prior_elem2code(season):
    """Season-local element id -> stable FPL player code."""
    out = {}
    ppath = os.path.join(HISTDIR, season, "players_raw.csv")
    if os.path.exists(ppath):
        for pr in csv.DictReader(open(ppath)):
            try:
                out[int(pr["id"])] = int(pr["code"])
            except (KeyError, ValueError):
                pass
    return out


def prior_key(row, elem2code):
    """Must match walk.player_key() exactly, or live and backtest disagree."""
    try:
        code = elem2code.get(int(float(row["element"])))
    except (KeyError, TypeError, ValueError):
        code = None
    return "c{}".format(code) if code is not None else "n:" + M.norm_name(row["name"])


def element_key(el):
    """The same identity, derived from a live bootstrap element."""
    code = el.get("code")
    if code is not None:
        return "c{}".format(int(code))
    return "n:" + M.norm_name("{} {}".format(
        el.get("first_name", ""), el.get("second_name", "")))


def load_prior(season, elem2code):
    """Prior-season aggregates keyed by stable FPL code.

    Same 0.6 discount the backtest applies, so live and backtested behaviour
    match at the start of a season.
    """
    path = os.path.join(HISTDIR, season, "merged_gw.csv")
    if not os.path.exists(path):
        raise SystemExit("missing {} - run `python3 history.py {}`".format(path, season))
    agg = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            a = agg.setdefault(prior_key(row, elem2code), M.blank_agg())
            mins = fnum(row, "minutes")
            a["mins"] += mins * 0.6
            a["xg"] += fnum(row, "expected_goals") * 0.6
            a["xa"] += fnum(row, "expected_assists") * 0.6
            a["dc"] += fnum(row, "defensive_contribution") * 0.6
            a["bps"] += fnum(row, "bps") * 0.6
            a["sv"] += fnum(row, "saves") * 0.6
            a["yc"] += fnum(row, "yellow_cards") * 0.6
            a["rc"] += fnum(row, "red_cards") * 0.6
            a["og"] += fnum(row, "own_goals") * 0.6
            a["pm"] += fnum(row, "penalties_missed") * 0.6
            a["psv"] += fnum(row, "penalties_saved") * 0.6
            a["starts"] += fnum(row, "starts") * 0.6
            a["apps"] += (1.0 if mins > 0 else 0.0) * 0.6
            a["matches"] += 0.6
            a["pts"] += fnum(row, "total_points") * 0.6
    return agg


HORIZONS_H = [72.0, 24.0, 6.0, 2.0]


def preflight(bootstrap, manifest, gw, minutes_model, force, horizon=None):
    """Refuse to write a projection that would corrupt the public record.

    A published projection is evidence: it carries a pre-deadline timestamp and
    a snapshot hash, and it can never be retracted honestly. So the failure mode
    to design against is not "we published nothing", it is "we published
    something wrong and it is now permanent". Every check below is a reason to
    stop rather than a reason to warn.
    """
    problems = []
    now = datetime.now(timezone.utc)

    deadline = manifest.get("next_deadline_utc")
    if deadline:
        dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        hrs = (dl - now).total_seconds() / 3600.0
        # The horizon gate belongs HERE, not only in tick.py. Running
        # `python3 project.py` by hand used to write straight into the record at
        # any distance from the deadline — a projection made a week early would
        # sit in the record as if it were the committed one. tick.py passes
        # --horizon explicitly; a human has to mean it.
        if horizon is None and hrs > max(HORIZONS_H):
            problems.append(
                "{:.0f}h to deadline, outside every horizon band ({}). The "
                "record takes projections at T-{} only. Use --dry-run to look, "
                "site.py to publish current numbers, or pass --horizon if you "
                "genuinely mean to add a record entry here.".format(
                    hrs, "/".join("{:.0f}h".format(h) for h in HORIZONS_H),
                    "/T-".join("{:.0f}h".format(h) for h in HORIZONS_H)))
        if now >= dl:
            problems.append(
                "DEADLINE PASSED for GW{} ({}). A projection written after the "
                "deadline is not a prediction and must never enter the record."
                .format(gw, deadline))
        elif (dl - now).total_seconds() > 21 * 86400:
            problems.append(
                "deadline is {:.1f} days away - too far out for the fixture "
                "list to be settled".format(
                    (dl - now).total_seconds() / 86400.0))

    snap_age = (now - datetime.fromisoformat(
        manifest["taken_at_utc"].replace("Z", "+00:00"))).total_seconds() / 3600.0
    # A projection made days out is legitimate — it is published as its own
    # horizon and scored as such. What is never acceptable is projecting from a
    # snapshot much older than the projection claims to be.
    if snap_age > 3.0:
        problems.append(
            "snapshot is {:.1f}h old; a projection must be built from a current "
            "snapshot - run snapshot.py again".format(snap_age))

    if manifest.get("next_gw") != gw:
        problems.append(
            "snapshot says next GW is {}, projecting GW{} - mismatched inputs"
            .format(manifest.get("next_gw"), gw))

    if minutes_model is None:
        problems.append(
            "no fitted minutes model. It is the only component with a "
            "statistically significant edge; without it this ships the "
            "configuration that ties a three-line baseline.")
    elif minutes_model.get("train_seasons") != MIN.PRODUCTION_TRAIN:
        problems.append(
            "minutes model trained on {} but the production recipe is {} "
            "- see minutes.PRODUCTION_TRAIN".format(
                minutes_model.get("train_seasons"), MIN.PRODUCTION_TRAIN))

    return problems, (force and problems)


def sanity_check(rows):
    """Distribution checks. Catches a silently broken model, not a crashed one."""
    problems = []
    if not rows:
        return ["no players projected"]
    xps = [r["xp"] for r in rows]
    elig = [r for r in rows if r["eligible"]]
    mean = sum(xps) / len(xps)

    if any(x != x or x in (float("inf"), float("-inf")) for x in xps):
        problems.append("NaN or infinite xP present")
    if not 1.0 <= mean <= 4.0:
        problems.append("mean xP {:.2f} outside the plausible 1.0-4.0 band"
                        .format(mean))
    if max(xps) > 15.0:
        problems.append("top xP {:.2f} implausible for a single gameweek"
                        .format(max(xps)))
    if len(elig) < 100:
        problems.append("only {} eligible players - prior-season data or the "
                        "cross-season join is probably broken".format(len(elig)))
    matched = sum(1 for r in rows if r["matched_prior"])
    if matched < 0.5 * len(rows):
        problems.append("only {}/{} players matched to prior season - check the "
                        "`code` join".format(matched, len(rows)))
    return problems


def preserve_snapshot(snapdir):
    """Copy the snapshot a projection was built from into the committed record.

    `data/snapshots/` is a working cache — the tick writes one every hour, which
    is ~13 GB a year and has no business in version control. But a projection is
    only verifiable if its exact inputs survive, so the handful of snapshots that
    actually produced a projection get preserved here, gzipped (JSON compresses
    about 10x, taking the season's record from ~227 MB to ~25 MB).

    Returns the preserved directory, or None if it already existed.
    """
    dest = os.path.join(OUTDIR, "snapshots", os.path.basename(snapdir))
    if os.path.isdir(dest):
        return None
    os.makedirs(dest, exist_ok=True)
    for fn in sorted(os.listdir(snapdir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(snapdir, fn), "rb") as src:
            with gzip.open(os.path.join(dest, fn + ".gz"), "wb") as dst:
                shutil.copyfileobj(src, dst)
    return dest


def _recent6(pkey, cur_pts, agg):
    """Mean of the last six gameweek scores; points-per-match before six exist."""
    rp = list(cur_pts.get(pkey, []))
    if rp:
        return sum(rp) / len(rp)
    if agg and agg["matches"] > 0:
        return agg["pts"] / agg["matches"]
    return 2.0


def load_current_season(bootstrap, snapdir):
    """Build current-season per-player state from settled gameweeks.

    THE BUG THIS FIXES: the live path previously loaded only the prior season
    and passed `recent_starts=[]` unconditionally. minutes.p_start() gates on
    exactly that, so the fitted minutes model never ran in production at any
    gameweek — the live product silently shipped the "v0 alone" configuration,
    which the backtest shows has NO significant edge over a three-line baseline.

    Folding goes through walk.fold_stats(), the same function the backtest uses,
    so live and backtested aggregates cannot diverge.

    Returns (agg_by_key, recent_starts, recent_pts, last_mins).
    """
    agg, recent, recent_pts, last_mins = {}, {}, {}, {}
    finished = [e["id"] for e in bootstrap.get("events", [])
                if e.get("finished") and e.get("data_checked")]
    if not finished:
        return agg, recent, recent_pts, last_mins, []

    code_of = {el["id"]: el.get("code") for el in bootstrap["elements"]}
    loaded = []
    for gw in sorted(finished):
        path = os.path.join(snapdir, "live_gw{}.json".format(gw))
        if not os.path.exists(path):
            continue
        payload = json.load(open(path))
        for el in payload.get("elements", []):
            code = code_of.get(el.get("id"))
            if code is None:
                continue
            key = "c{}".format(int(code))
            a = agg.setdefault(key, M.blank_agg())
            r = recent.setdefault(key, collections.deque())
            rp = recent_pts.setdefault(key, collections.deque())
            last_mins[key] = walk.fold_stats(a, r, rp, el.get("stats", {}))
        loaded.append(gw)
    return agg, recent, recent_pts, last_mins, loaded


class LiveContext(object):
    """Duck-types walk.Context for the fields minutes.featurise() reads.

    Kept minimal on purpose: if featurise() ever starts reading a field this
    does not supply, the AttributeError is the correct outcome — silently
    defaulting it would make the live model differ from the backtested one.
    """

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def prior_start_rates(season, elem2code):
    """Per-player start rate last season, the feature minutes.py expects."""
    path = os.path.join(HISTDIR, season, "merged_gw.csv")
    acc = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            e = acc.setdefault(prior_key(row, elem2code), [0.0, 0.0])
            e[0] += 1.0 if fnum(row, "starts") > 0 else 0.0
            e[1] += 1.0
    return {k: (v[0] / v[1] if v[1] else None) for k, v in acc.items()}


def live_team_rank(bootstrap, prior):
    """Competition for the shirt, ranked within team+position by prior minutes."""
    groups = {}
    for el in bootstrap["elements"]:
        if el["element_type"] not in M.GOAL_PTS:
            continue
        a = prior.get(element_key(el))
        mins = (a["mins"] / a["matches"]) if (a and a["matches"] > 0) else 0.0
        groups.setdefault((el["team"], el["element_type"]), []).append(
            (mins, el["id"]))
    rank = {}
    for grp in groups.values():
        grp.sort(key=lambda z: -z[0])
        n = float(max(1, len(grp) - 1))
        for i, (_, eid) in enumerate(grp):
            rank[eid] = i / n
    return rank


def prior_team_xg(season):
    """Last season's xG for and against per team, per match.

    The pre-season fallback used to be FPL's 1-5 tier, compressed. That produced
    almost no spread - every fixture came out within 0.98-1.00 of average, which
    made the fixture ticker uniformly green and told the projection model
    essentially nothing about who a player was facing.

    Last season's actual xG has a 2.3x range (0.88 to 1.99 scored, 0.91 to 2.11
    conceded). It is a far better prior for August than a hand-set tier, and it
    is already on disk.
    """
    try:
        from walk import load_season, team_xg_by_gw
        rows, id2name, _ = load_season(season)
    except SystemExit:
        return {}
    xf, xa = team_xg_by_gw(rows, id2name)
    tot = {}
    for (_, t), v in xf.items():
        e = tot.setdefault(t, [0.0, 0.0, 0])
        e[0] += v
        e[2] += 1
    for (_, t), v in xa.items():
        if t in tot:
            tot[t][1] += v
    return {t: (f / n, a / n) for t, (f, a, n) in tot.items() if n}


def team_ratings(bootstrap, prior_season=None):
    """Attack/defence multipliers normalised to a league mean of 1.0.

    In-season FPL publishes granular strength_attack_* / strength_defence_*.
    Before that they are all zero, and the fallback matters more than it looks:
    it is what August projections and the whole first fixture ticker rest on.
    """
    ts = bootstrap["teams"]
    teams = {t["id"]: t for t in ts}
    granular = any(t.get("strength_attack_home") for t in ts)

    prior = prior_team_xg(prior_season) if (prior_season and not granular) else {}
    league = M.LEAGUE_XG_PER_TEAM_MATCH
    # Promoted sides have no prior-season row. Rating them as league-average
    # would be generous; last season's bottom third is the honest guess.
    PROMOTED = (1.10, 1.75)

    def raw(t, kind, is_home):
        if granular:
            return float(t["strength_{}_{}".format(kind, "home" if is_home else "away")])
        if prior:
            fa = prior.get(t["name"], PROMOTED)
            # Shrink toward the league mean: one season is ~38 matches, which is
            # informative but not decisive, and squads change over a summer.
            w = 0.75
            val = fa[0] if kind == "attack" else fa[1]
            return 1000.0 * (w * val + (1 - w) * league) / league
        tier = float(t.get("strength_overall_home" if is_home
                           else "strength_overall_away") or 3)
        return 1000.0 + 60.0 * tier

    idx = {}
    for kind in ("attack", "defence"):
        for is_home in (True, False):
            vals = [raw(t, kind, is_home) for t in ts]
            mean = sum(vals) / len(vals)
            for t, v in zip(ts, vals):
                idx[(t["id"], kind, is_home)] = v / mean if mean else 1.0
    return teams, idx, granular


def availability(el):
    """Fold FPL's injury/suspension flags into [0,1].

    The backtest cannot see these (they were never recorded historically), so
    this is strictly extra information the live model has.
    """
    status = el.get("status", "a")
    chance = el.get("chance_of_playing_next_round")
    if status in ("i", "s", "u", "n"):
        return 0.0
    if chance is not None:
        return float(chance) / 100.0
    if status == "d":
        return 0.5
    return 1.0


def multi_gw_xp(rates, pos, p_start, p_sub, xmins, fixtures, idx, team_id,
                start_gw, n_gw, defcon_cal):
    """Expected points for each of the next n_gw gameweeks.

    Both incumbents lead with this and both research passes ranked it their
    single most-used feature: Scout sells six-gameweek projections, Hub a slider
    out to eight. We were projecting one gameweek, which answers "who do I
    captain" but not "who do I buy" - and buying is the decision people agonise
    over.

    Rates and expected minutes are held constant across the horizon: we do not
    know a player's form in four weeks, so the only thing that legitimately
    varies is who he plays. That is also why the far end of the horizon is
    softer than the near end, and the page says so rather than implying a
    precision it does not have.
    """
    out = []
    for g in range(start_gw, start_gw + n_gw):
        fx = fixtures.get(g, {}).get(team_id, [])
        if not fx:
            out.append(0.0)          # blank gameweek
            continue
        ratings = [(idx[(opp, "defence", not home)],
                    idx[(opp, "attack", not home)], home) for opp, home in fx]
        res = M.project(rates, pos, p_start, p_sub, xmins, ratings,
                        defcon=True, calibration=defcon_cal)
        out.append(round(res["xp"], 2) if res else 0.0)
    return out


def gw_fixtures(fixtures, gw):
    """{team_id: [(opponent_id, is_home), ...]} - a list, so DGWs just work."""
    out = {}
    for fx in fixtures:
        if fx.get("event") != gw:
            continue
        out.setdefault(fx["team_h"], []).append((fx["team_a"], True))
        out.setdefault(fx["team_a"], []).append((fx["team_h"], False))
    return out


def build(snapdir, prior_season, gw=None, use_minutes_model=True, quiet=False,
          n_gw=6):
    """Produce projection rows + provenance metadata from ONE snapshot directory.

    Pure with respect to the snapshot: given the same directory, the same prior
    season, the same fitted minutes model and the same PRIORS, it must produce
    byte-identical output. verify.py depends on that, and so does every claim on
    the public scorecard.
    """
    with open(os.path.join(snapdir, "bootstrap.json")) as f:
        bootstrap = json.load(f)
    with open(os.path.join(snapdir, "fixtures.json")) as f:
        fixtures = json.load(f)
    with open(os.path.join(snapdir, "manifest.json")) as f:
        manifest = json.load(f)

    gw = gw or manifest.get("next_gw")
    if gw is None:
        raise SystemExit("could not determine gameweek; pass --gw")

    minutes_model, prior_start_rate, team_rank = None, {}, {}
    mm_path = os.path.join(OUTDIR, "minutes_model.json")
    e2c = prior_elem2code(prior_season)
    prior = load_prior(prior_season, e2c)
    if use_minutes_model and os.path.exists(mm_path):
        minutes_model = json.load(open(mm_path))
        prior_start_rate = prior_start_rates(prior_season, e2c)
        team_rank = live_team_rank(bootstrap, prior)
        if not quiet:
            print("using fitted minutes model (trained {})".format(
                ", ".join(minutes_model.get("train_seasons", ["?"]))))

    cur_agg, cur_recent, cur_pts, cur_last, loaded_gws = load_current_season(
        bootstrap, snapdir)
    if loaded_gws and not quiet:
        print("current-season state from {} settled gameweek(s): {}".format(
            len(loaded_gws), ", ".join("GW{}".format(g) for g in loaded_gws)))

    teams, idx, granular = team_ratings(bootstrap, prior_season)
    fx = gw_fixtures(fixtures, gw)
    if not granular and not quiet:
        print("note: pre-season - using coarse 1-5 team tiers for fixture strength\n")

    cal = M.CALIBRATION_MINUTES if minutes_model else M.CALIBRATION_HEURISTIC
    # Fixture map for the whole horizon, once, rather than per player.
    horizon = {g: gw_fixtures(fixtures, g) for g in range(gw, gw + n_gw)}
    rows, matched = [], 0
    for el in bootstrap["elements"]:
        pos = el["element_type"]
        if pos not in M.GOAL_PTS:
            continue
        pkey = element_key(el)
        seed = prior.get(pkey)
        cur = cur_agg.get(pkey)
        if seed and cur:
            agg = dict(seed)
            for k, v in cur.items():
                agg[k] = agg.get(k, 0.0) + v
        else:
            agg = dict(cur) if cur else (dict(seed) if seed else None)
        if seed:
            matched += 1

        avail = availability(el)
        price_m = el.get("now_cost", 45) / 10.0
        if minutes_model is not None:
            ctx = LiveContext(pos=pos, price=price_m, agg=agg,
                              recent_starts=list(cur_recent.get(pkey, [])),
                              last_mins=cur_last.get(pkey), days_rest=None,
                              team_rank=team_rank.get(el["id"], 0.5),
                              is_new=(agg is None or agg["matches"] == 0))
            p = MIN.p_start(minutes_model, ctx, prior_start_rate.get(pkey))
            p_start, p_sub, xmins = M.minutes_from_pstart(p, agg, avail)
        else:
            mm = M.minutes_from_history(agg, list(cur_recent.get(pkey, [])), avail)
            if mm is None:
                mm = M.cold_start_minutes(price_m, avail)
            p_start, p_sub, xmins = mm

        opp_list = fx.get(el["team"], [])
        fixture_ratings = [(idx[(opp, "defence", not home)],
                            idx[(opp, "attack", not home)], home)
                           for opp, home in opp_list]
        res = M.project(M.per90(agg, pos), pos, p_start, p_sub, xmins,
                        fixture_ratings, calibration=cal)
        if not res:
            continue

        per_gw = multi_gw_xp(M.per90(agg, pos), pos, p_start, p_sub, xmins,
                             horizon, idx, el["team"], gw, n_gw, cal)
        rows.append(dict(
            element=el["id"], web_name=el["web_name"],
            team=teams[el["team"]]["short_name"], pos=M.POS_TO_STR[pos],
            price=price_m, xp=round(res["xp"], 3), sd=round(res["sd"], 3),
            xmins=round(res["xmins"], 1), p_start=round(res["p_start"], 3),
            n_fix=res["n_fix"], fpl_ep_next=el.get("ep_next"),
            matched_prior=bool(seed),
            naive_recent6=round(_recent6(pkey, cur_pts, agg) * len(opp_list), 3),
            eligible=int(bool(agg and agg["matches"] >= 3.0
                              and agg["mins"] / agg["matches"] >= 45.0)),
            # Horizon projection: one column per gameweek, plus the total that
            # actually drives a transfer decision.
            xp_next=";".join("{:.2f}".format(x) for x in per_gw),
            xp_total=round(sum(per_gw), 2),
        ))

    rows.sort(key=lambda r: -r["xp"])
    meta = {
        "gameweek": gw,
        "snapshot": os.path.basename(snapdir),
        "snapshot_sha256": {k: v["sha256"] for k, v in manifest["files"].items()},
        "deadline_utc": manifest.get("next_deadline_utc"),
        "prior_season": prior_season,
        "model_version": "v0-baseline",
        "calibration": cal,
        "granular_team_strength": granular,
        "minutes_model": (minutes_model.get("train_seasons")
                          if minutes_model else None),
        "minutes_model_sha256": (
            hashlib.sha256(json.dumps(minutes_model, sort_keys=True).encode())
            .hexdigest() if minutes_model else None),
        "priors_sha256": hashlib.sha256(
            repr(sorted((k, sorted(v.items())) for k, v in M.PRIORS.items()))
            .encode()).hexdigest(),
        "n_players": len(rows),
        "horizon_gws": n_gw,
    }
    return rows, meta, dict(bootstrap=bootstrap, manifest=manifest,
                            minutes_model=minutes_model, matched=matched)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gw", type=int, default=None)
    ap.add_argument("--prior", default="2025-26")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--snapshot", default=None,
                    help="snapshot directory (default: most recent)")
    ap.add_argument("--no-minutes-model", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="write despite preflight failures (never for anything "
                         "that will be published)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--horizon", type=float, default=None,
                    help="hours-before-deadline band this projection belongs to")
    args = ap.parse_args()

    snap = args.snapshot or latest_snapshot()
    rows, meta, info = build(snap, args.prior, args.gw,
                             not args.no_minutes_model)

    problems = preflight(info["bootstrap"], info["manifest"], meta["gameweek"],
                         info["minutes_model"], args.force, args.horizon)[0]
    problems += sanity_check(rows)
    if problems:
        print("\nPREFLIGHT FAILED ({} problem(s)):".format(len(problems)))
        for pr in problems:
            print("  - {}".format(pr))
        if not args.force:
            print("\nRefusing to write. This projection would enter a permanent "
                  "public record.\nFix the cause, or pass --force if you have "
                  "read every line above and\nthis output will NOT be published.")
            return 1
        print("\n--force given: writing anyway. Do not publish this.")

    if args.dry_run:
        print("\ndry run: preflight {}, nothing written".format(
            "failed" if problems else "clean"))
        return 0

    os.makedirs(OUTDIR, exist_ok=True)
    kept = preserve_snapshot(snap)
    if kept:
        print("snapshot preserved for verification: {}".format(
            os.path.relpath(kept, HERE)))
    out = os.path.join(OUTDIR, "projections_gw{}_{}.csv".format(
        meta["gameweek"], meta["snapshot"]))
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    meta["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    meta["horizon_h"] = args.horizon
    if meta.get("deadline_utc"):
        meta["hours_before_deadline"] = round(
            (datetime.fromisoformat(meta["deadline_utc"].replace("Z", "+00:00"))
             - datetime.now(timezone.utc)).total_seconds() / 3600.0, 2)
    with open(out.replace(".csv", ".meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print("GW{}  {} players projected  ({} matched to {})".format(
        meta["gameweek"], len(rows), info["matched"], args.prior))
    print("written: {}\n".format(out))
    print("{:<18}{:<5}{:<5}{:>7}{:>7}{:>7}{:>8}".format(
        "player", "team", "pos", "price", "xP", "sd", "fpl_ep"))
    for r in rows[:args.top]:
        print("{:<18}{:<5}{:<5}{:>7.1f}{:>7.2f}{:>7.2f}{:>8}".format(
            r["web_name"][:17], r["team"], r["pos"], r["price"],
            r["xp"], r["sd"], r["fpl_ep_next"]))
    return 0


if __name__ == "__main__":
    # sys.exit, not a bare call: preflight returns 1 on refusal and a cron job
    # must see a non-zero status, or a skipped projection looks like a
    # successful one and the gap goes unnoticed until someone reads the page.
    sys.exit(main() or 0)
