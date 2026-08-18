#!/usr/bin/env python3
"""Shared walk-forward state machine over a season.

One implementation of "what did we know before gameweek g", used by backtest.py
and minutes.py. Duplicating this was the obvious next place for the live and
evaluation paths to silently diverge, which is the thing model.py exists to stop.

The critical invariant: `Context` objects are yielded BEFORE gameweek g is
folded into state, and every field on them is derived only from gameweeks
1..g-1 plus the prior season. Outcome fields are namespaced under `.actual_*`
so that using one as a feature is a visible mistake rather than an invisible one.
"""

import collections
import csv
import os
from datetime import datetime

import model as M

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "data", "history")

PRIOR_WEIGHT = 0.6  # discount on last season's evidence


def fnum(row, key, default=0.0):
    v = row.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def load_season(season):
    path = os.path.join(HIST, season, "merged_gw.csv")
    if not os.path.exists(path):
        raise SystemExit("missing {} - run `python3 history.py {}`".format(path, season))
    rows = list(csv.DictReader(open(path)))
    id2name = {}
    tpath = os.path.join(HIST, season, "teams.csv")
    if os.path.exists(tpath):
        id2name = {int(t["id"]): t["name"] for t in csv.DictReader(open(tpath))}

    # Season-local element id -> stable FPL player code. `code` is the only
    # identifier that survives across seasons; element ids are re-issued every
    # year and names are not stable in the mirror.
    elem2code = {}
    ppath = os.path.join(HIST, season, "players_raw.csv")
    if os.path.exists(ppath):
        for pr in csv.DictReader(open(ppath)):
            try:
                elem2code[int(pr["id"])] = int(pr["code"])
            except (KeyError, ValueError):
                pass
    return rows, id2name, elem2code


def player_key(row, elem2code):
    """Stable cross-season identity for a player.

    Joining on normalised names lost 8.8% of returning players: the mirror
    renames people between seasons (`robert lynch sanchez` / `robert sanchez`,
    `matheus nunes` / `matheus luiz nunes`). Those players then look brand new,
    lose their entire history, and fail the eligibility filter until GW4 — worst
    exactly in the opening gameweeks. Fall back to the name only if the code is
    genuinely unavailable.
    """
    try:
        code = elem2code.get(int(float(row["element"])))
    except (KeyError, TypeError, ValueError):
        code = None
    return "c{}".format(code) if code is not None else "n:" + M.norm_name(row["name"])


def parse_kickoff(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:19].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


class Context(object):
    """Everything knowable about one player before one gameweek."""

    __slots__ = ("key", "name", "pos", "price", "team", "agg", "recent_starts",
                 "recent_pts", "last_mins", "days_rest", "fixtures", "n_fix",
                 "team_rank", "is_new", "actual_points", "actual_minutes",
                 "actual_started")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class TeamRatings(object):
    """Shrunk attack/defence ratings normalised so the league mean is 1.0."""

    def __init__(self, prior=None, k=6.0):
        self.k = k
        self.acc = collections.defaultdict(lambda: dict(fo=0.0, ag=0.0, n=0.0))
        if prior:
            for t, (fo, ag, n) in prior.items():
                self.acc[t] = dict(fo=fo, ag=ag, n=n)

    def observe(self, team, xg_for, xg_against):
        a = self.acc[team]
        a["fo"] += xg_for
        a["ag"] += xg_against
        a["n"] += 1.0

    def rating(self, team):
        a = self.acc.get(team)
        base = M.LEAGUE_XG_PER_TEAM_MATCH
        if not a or a["n"] == 0:
            return 1.0, 1.0
        w = a["n"] / (a["n"] + self.k)
        atk = (w * (a["fo"] / a["n"]) + (1 - w) * base) / base
        dfn = (w * (a["ag"] / a["n"]) + (1 - w) * base) / base
        return atk, dfn


def team_xg_by_gw(rows, id2name):
    xg_for = collections.defaultdict(float)
    played, opp_of = set(), {}
    for r in rows:
        gw, t = int(r["GW"]), r["team"]
        xg_for[(gw, t)] += fnum(r, "expected_goals")
        played.add((gw, t))
        opp = id2name.get(int(fnum(r, "opponent_team")))
        if opp:
            opp_of.setdefault((gw, t), set()).add(opp)
    xg_against = collections.defaultdict(float)
    # sorted(), not raw set iteration. Python randomises string hashing per
    # process, so set order varies between runs, and summing the same floats in
    # a different order changes the last bits. Everything downstream claims to
    # be byte-reproducible from a recorded snapshot; that claim cannot rest on
    # PYTHONHASHSEED.
    for key in sorted(played):
        for opp in sorted(opp_of.get(key, ())):
            xg_against[key] += xg_for.get((key[0], opp), M.LEAGUE_XG_PER_TEAM_MATCH)
    return xg_for, xg_against


def seed_from_prior(prior_rows, prior_id2name, prior_elem2code):
    # `defensive_contribution` does not exist in mirrors before 2025-26. Reading
    # it as 0.0 does not merely lose information: per90() divides dc by TOTAL
    # minutes including the seeded ones, so a returning full-time player enters
    # the season with a dc/90 rate deflated by ~37%, while a genuinely new
    # player gets an unbiased one. Impute at the positional prior instead, which
    # is rate-neutral.
    has_dc = bool(prior_rows) and "defensive_contribution" in prior_rows[0]

    agg, prior_start_rate = {}, {}
    for r in prior_rows:
        key = player_key(r, prior_elem2code)
        a = agg.setdefault(key, M.blank_agg())
        mins = fnum(r, "minutes")
        w = PRIOR_WEIGHT
        a["mins"] += mins * w
        a["xg"] += fnum(r, "expected_goals") * w
        a["xa"] += fnum(r, "expected_assists") * w
        if has_dc:
            a["dc"] += fnum(r, "defensive_contribution") * w
        else:
            pos = M.POS_FROM_STR.get(r["position"], M.MID)
            a["dc"] += M.PRIORS[pos]["dc"] * (mins / 90.0) * w
        a["bps"] += fnum(r, "bps") * w
        a["sv"] += fnum(r, "saves") * w
        a["yc"] += fnum(r, "yellow_cards") * w
        a["rc"] += fnum(r, "red_cards") * w
        a["og"] += fnum(r, "own_goals") * w
        a["pm"] += fnum(r, "penalties_missed") * w
        a["psv"] += fnum(r, "penalties_saved") * w
        a["starts"] += fnum(r, "starts") * w
        a["apps"] += (1.0 if mins > 0 else 0.0) * w
        a["matches"] += w
        a["pts"] += fnum(r, "total_points") * w
        s = prior_start_rate.setdefault(key, [0.0, 0.0])
        s[0] += 1.0 if fnum(r, "starts") > 0 else 0.0
        s[1] += 1.0

    xf, xa = team_xg_by_gw(prior_rows, prior_id2name)
    tacc = {}
    for (_, t), v in xf.items():
        e = tacc.setdefault(t, [0.0, 0.0, 0.0])
        e[0] += v * 0.5
        e[2] += 0.5
    for (_, t), v in xa.items():
        if t in tacc:
            tacc[t][1] += v * 0.5
    return (agg,
            {k: (v[0] / v[1] if v[1] else None) for k, v in prior_start_rate.items()},
            {t: tuple(v) for t, v in tacc.items()})


STAT_KEYS = (
    ("mins", "minutes"), ("xg", "expected_goals"), ("xa", "expected_assists"),
    ("dc", "defensive_contribution"), ("bps", "bps"), ("sv", "saves"),
    ("yc", "yellow_cards"), ("rc", "red_cards"), ("og", "own_goals"),
    ("pm", "penalties_missed"), ("psv", "penalties_saved"),
    ("starts", "starts"), ("pts", "total_points"),
)


def fold_stats(agg, recent, recent_pts, stats, dc_prior=None):
    """Fold one player-gameweek of raw stats into the running aggregate.

    Shared by walk.Walker._fold (historical CSV rows) and project.py (live
    `event/<gw>/live/` payloads) so the two cannot compute aggregates
    differently. `stats` is any mapping using FPL's own field names.

    `dc_prior` imputes defensive contribution when the source predates the stat
    — see seed_from_prior for why reading it as 0.0 corrupts the rate.
    """
    for our, theirs in STAT_KEYS:
        if our == "dc" and dc_prior is not None:
            continue
        agg[our] += fnum(stats, theirs)
    mins = fnum(stats, "minutes")
    if dc_prior is not None:
        agg["dc"] += dc_prior * (mins / 90.0)
    agg["apps"] += 1.0 if mins > 0 else 0.0
    agg["matches"] += 1.0
    if recent is not None:
        recent.append(1.0 if fnum(stats, "starts") > 0 else 0.0)
        while len(recent) > 6:
            recent.popleft()
    if recent_pts is not None:
        recent_pts.append(fnum(stats, "total_points"))
        while len(recent_pts) > 6:
            recent_pts.popleft()
    return mins


class Walker(object):
    def __init__(self, season, prior_season=None):
        self.season = season
        self.defcon_active = season >= "2025-26"
        self.rows, self.id2name, self.elem2code = load_season(season)
        self.by_gw = collections.defaultdict(list)
        for r in self.rows:
            self.by_gw[int(r["GW"])].append(r)

        if prior_season:
            prows, pid2, pcode = load_season(prior_season)
            seed_agg, self.prior_start_rate, seed_team = seed_from_prior(
                prows, pid2, pcode)
        else:
            seed_agg, self.prior_start_rate, seed_team = {}, {}, {}

        self.agg = {k: dict(v) for k, v in seed_agg.items()}
        self.recent = collections.defaultdict(collections.deque)
        self.recent_pts = collections.defaultdict(collections.deque)
        self.last_mins = {}
        self.last_kick = {}
        self.ratings = TeamRatings(prior=seed_team)
        self.xf, self.xa = team_xg_by_gw(self.rows, self.id2name)

    def _team_rank(self, gw_rows):
        """Rank each player among same-team, same-position peers by recent minutes.

        A proxy for competition for the shirt: rank 0 is the incumbent. Computed
        purely from state already accumulated, so it stays inside the cutoff.
        """
        groups = collections.defaultdict(list)
        for r in gw_rows:
            key = player_key(r, self.elem2code)
            a = self.agg.get(key)
            recent_mins = (a["mins"] / a["matches"]) if (a and a["matches"] > 0) else 0.0
            groups[(r["team"], r["position"])].append((recent_mins, key))
        rank = {}
        for grp in groups.values():
            grp.sort(key=lambda z: -z[0])
            n = float(max(1, len(grp) - 1))
            for i, (_, key) in enumerate(grp):
                rank[key] = i / n
        return rank

    def gameweeks(self):
        """Yield (gw, [Context, ...]) for each gameweek, in order."""
        for gw in sorted(self.by_gw):
            gw_rows = self.by_gw[gw]
            grouped = collections.defaultdict(list)
            for r in gw_rows:
                grouped[player_key(r, self.elem2code)].append(r)
            rank = self._team_rank(gw_rows)

            contexts = []
            for key, prs in grouped.items():
                r0 = prs[0]
                pos = M.POS_FROM_STR.get(r0["position"])
                if pos is None:
                    continue
                a = self.agg.get(key)
                kick = parse_kickoff(r0.get("kickoff_time"))
                prev = self.last_kick.get(key)
                days = ((kick - prev).total_seconds() / 86400.0
                        if (kick and prev) else None)

                fixtures = []
                for r in prs:
                    opp = self.id2name.get(int(fnum(r, "opponent_team")))
                    atk, dfn = self.ratings.rating(opp) if opp else (1.0, 1.0)
                    fixtures.append((dfn, atk,
                                     str(r["was_home"]).lower() == "true"))

                contexts.append(Context(
                    key=key, name=r0["name"], pos=pos, team=r0["team"],
                    price=fnum(r0, "value", 45.0) / 10.0,
                    # COPY, never alias. `_fold` mutates Walker.agg in place, so
                    # handing out a reference means anything that materialises
                    # the generator (list(w.gameweeks())) silently gives every
                    # gameweek the END-OF-SEASON aggregate. Consumers happen to
                    # read inside the loop today; that is not a guarantee.
                    agg=(dict(a) if a is not None else None),
                    recent_starts=list(self.recent[key]),
                    recent_pts=list(self.recent_pts[key]),
                    last_mins=self.last_mins.get(key),
                    days_rest=days,
                    fixtures=fixtures, n_fix=len(prs),
                    team_rank=rank.get(key, 0.5),
                    is_new=(a is None or a["matches"] == 0),
                    actual_points=sum(fnum(r, "total_points") for r in prs),
                    actual_minutes=sum(fnum(r, "minutes") for r in prs),
                    actual_started=1.0 if any(fnum(r, "starts") > 0 for r in prs) else 0.0,
                ))

            yield gw, contexts
            self._fold(gw_rows)

    def _fold(self, gw_rows):
        """Fold a completed gameweek into state. Only called after yielding."""
        for r in gw_rows:
            key = player_key(r, self.elem2code)
            a = self.agg.setdefault(key, M.blank_agg())
            mins = fold_stats(a, self.recent[key], self.recent_pts[key], r)
            self.last_mins[key] = mins
            k = parse_kickoff(r.get("kickoff_time"))
            if k:
                self.last_kick[key] = k
        for t in set(r["team"] for r in gw_rows):
            gw = int(gw_rows[0]["GW"])
            self.ratings.observe(t, self.xf.get((gw, t), M.LEAGUE_XG_PER_TEAM_MATCH),
                                 self.xa.get((gw, t), M.LEAGUE_XG_PER_TEAM_MATCH))
