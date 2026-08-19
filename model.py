#!/usr/bin/env python3
"""Shared projection model. Imported by both project.py (live) and backtest.py.

The point of this module existing is that the backtest must exercise the *same*
scoring code as the live path. If they drift, the accuracy record measures
something we don't ship.

Nothing in here touches the network, the filesystem, or the clock. Everything is
a pure function of features passed in, which is what makes the as-of cutoff in
the backtest enforceable.
"""

import math
import unicodedata

# --- FPL scoring: verified against game_config.scoring in a 2026/27 snapshot -
GK, DEF, MID, FWD = 1, 2, 3, 4
POS_FROM_STR = {"GK": GK, "GKP": GK, "DEF": DEF, "MID": MID, "FWD": FWD}
POS_TO_STR = {GK: "GKP", DEF: "DEF", MID: "MID", FWD: "FWD"}

GOAL_PTS = {GK: 10, DEF: 6, MID: 5, FWD: 4}
CS_PTS = {GK: 4, DEF: 4, MID: 1, FWD: 0}
ASSIST_PTS = 3
DEFCON_THRESHOLD = {GK: 999, DEF: 10, MID: 12, FWD: 12}
DEFCON_PTS = 2

# Shrinkage strength in minutes: a player with SHRINK minutes of history gets a
# 50/50 blend of his own rate and the positional prior.
SHRINK = 600.0

# Fitted by priors.py on 2022-23, 2023-24, 2024-25, 2025-26 — minutes-weighted population mean per 90
# by position. Do not hand-edit: re-run `python3 priors.py --write`,
# then re-fit both CALIBRATION constants, which absorb any drift here.
PRIORS = {
    GK:   dict(xg=0.000, xa=0.002, dc=0.00, bps=16.0, sv=3.02,
              yc=0.073, rc=0.0010, og=0.0063, pm=0.0000, psv=0.020),
    DEF:  dict(xg=0.049, xa=0.052, dc=7.69, bps=15.1, sv=0.00,
              yc=0.183, rc=0.0071, og=0.0095, pm=0.0000, psv=0.000),
    MID:  dict(xg=0.152, xa=0.118, dc=8.58, bps=16.9, sv=0.00,
              yc=0.199, rc=0.0055, og=0.0020, pm=0.0024, psv=0.000),
    FWD:  dict(xg=0.386, xa=0.069, dc=4.80, bps=17.8, sv=0.00,
              yc=0.163, rc=0.0039, og=0.0012, pm=0.0092, psv=0.000),
}

RATE_KEYS = ("xg", "xa", "dc", "bps", "sv", "yc", "rc", "og", "pm", "psv")

# League baselines, used to normalise team ratings.
LEAGUE_XG_PER_TEAM_MATCH = 1.42
HOME_ATK, AWAY_ATK = 1.06, 0.94
HOME_DEF, AWAY_DEF = 0.92, 1.08

# Calibration multipliers, fitted by backtest.py --calibrate.
#
# TWO constants, because the expected-minutes path changes the level of the
# projections and a single global figure silently mis-calibrates whichever path
# it was not fitted for. The live product runs the minutes model, so it was the
# one being served the wrong constant.
#
# Refit after priors.py replaced the hand-set PRIORS. Residual bias, all
# out-of-sample, on the seasons each was fitted across:
#   heuristic path : 1.034 / 0.987 / 0.992  (2023-24 / 2024-25 / 2025-26)
#   minutes model  : 1.049 / 0.974          (2024-25 / 2025-26)
#
# Refit both whenever a scoring term changes: a calibration constant silently
# absorbs any systematic error left beneath it, so a correct rule fix applied
# without recalibrating makes projections worse rather than better.
#
# Neither affects Spearman (verified bit-identical across 0.80-1.20) — they move
# bias, MAE and RMSE only. Calibrating to mean-unbiasedness raises MAE, because
# FPL points are right-skewed and MAE is minimised near the conditional median.
# Unbiased means win anyway: the optimiser sums xP over 11-15 players, where a
# systematic shortfall compounds linearly.
CALIBRATION_HEURISTIC = 1.120
CALIBRATION_MINUTES = 1.165

# Default for callers that do not say which path they are on.
CALIBRATION = CALIBRATION_HEURISTIC


# NFKD decomposes accents into base + combining mark, but these letters are
# atomic codepoints with no decomposition, so stripping combining marks leaves
# them untouched and `jørgen strand larsen` / `łukasz fabianski` never match.
_LETTER_FOLD = {
    "ø": "o", "Ø": "o", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d",
    "ı": "i", "İ": "i", "ð": "d", "Ð": "d", "þ": "th", "Þ": "th",
    "ß": "ss", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ŋ": "n",
}


def norm_name(s):
    """Fallback identity only — prefer walk.player_key(), which joins on the
    stable FPL `code`. Names are not stable across seasons in the mirror."""
    s = "".join(_LETTER_FOLD.get(c, c) for c in (s or ""))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("-", " ").replace("'", "").split())


def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def blank_agg():
    d = dict(mins=0.0, starts=0.0, apps=0.0, matches=0.0, pts=0.0)
    for k in RATE_KEYS:
        d[k] = 0.0
    return d


def per90(agg, pos):
    """Shrink observed per-90 rates toward the positional prior."""
    p = PRIORS[pos]
    m = agg["mins"] if agg else 0.0
    w = m / (m + SHRINK)
    out = {}
    for k in RATE_KEYS:
        own = (agg.get(k, 0.0) / m * 90.0) if (agg and m > 0) else p[k]
        out[k] = w * own + (1 - w) * p[k]
    return out


def e_floor_div(lam, divisor, kmax=16):
    """E[floor(N / divisor)] for N ~ Poisson(lam).

    FPL pays on *completed* groups: one goal conceded costs a defender nothing,
    two cost 1 point; two saves score nothing, three score 1. Dividing the
    expectation instead of taking the expectation of the floor over-penalises
    goals conceded by ~0.235 pts/fixture at league-average lambda and
    over-credits keeper saves by ~0.33.
    """
    if lam <= 0:
        return 0.0
    return sum((k // divisor) * poisson_pmf(k, lam) for k in range(kmax))


def minutes_from_history(agg, recent_starts, availability):
    """P(start), P(sub) and expected minutes.

    `recent_starts` is a list of 0/1 over the most recent matches (newest last),
    which is what makes this responsive to a player losing his place. `agg` is
    the longer-run aggregate. `availability` in [0,1] folds in injury/suspension
    flags — in the backtest this is always 1.0, because historical status flags
    were never recorded, so backtested accuracy is a LOWER BOUND on live.

    This is the crudest and most valuable part of the model. See README M2.
    """
    if agg and agg["matches"] > 0:
        long_rate = agg["starts"] / agg["matches"]
        sub_rate = max(0.0, (agg["apps"] - agg["starts"]) / agg["matches"])
    else:
        long_rate, sub_rate = None, 0.2

    if recent_starts:
        recent_rate = sum(recent_starts) / float(len(recent_starts))
        n = len(recent_starts)
        w = min(1.0, n / 6.0) * 0.7  # trust recent form, but not blindly
        p_start = w * recent_rate + (1 - w) * (long_rate if long_rate is not None
                                               else recent_rate)
    elif long_rate is not None:
        p_start = long_rate
    else:
        p_start = None  # caller supplies a cold-start prior

    if p_start is None:
        return None
    p_start = max(0.0, min(1.0, p_start)) * availability
    p_sub = max(0.0, min(1.0, sub_rate)) * availability
    xmins = p_start * 84.0 + p_sub * 20.0
    return p_start, p_sub, xmins


def minutes_from_pstart(p_start, agg, availability=1.0):
    """Expected minutes given an externally-supplied P(start) — see minutes.py.

    Only the starting probability is modelled properly; the sub-appearance rate
    stays a historical rate, because sub minutes are worth far less and the
    error there is second-order.
    """
    if agg and agg["matches"] > 0:
        sub_rate = max(0.0, (agg["apps"] - agg["starts"]) / agg["matches"])
    else:
        sub_rate = 0.2
    p_start = max(0.0, min(1.0, p_start)) * availability
    p_sub = max(0.0, min(1.0, sub_rate)) * availability
    return p_start, p_sub, p_start * 84.0 + p_sub * 20.0


def cold_start_minutes(price, availability=1.0):
    """No PL history: new signing, promotion, youth.

    Price is the market's read on expected involvement and is a surprisingly
    good proxy. Wrong most visibly in August, which is when it matters most.
    """
    p_start = max(0.15, min(0.85, (price - 3.8) / 4.0)) * availability
    p_sub = 0.2 * availability
    return p_start, p_sub, p_start * 84.0 + p_sub * 20.0


def project_fixture(rates, pos, p_start, p_sub, xmins, opp_def, opp_atk, is_home,
                    defcon=True, calibration=None):
    """Expected points and variance for one player in one fixture.

    `opp_def` / `opp_atk` are the opponent's ratings normalised so 1.0 is
    league-average; >1 defence means a harder fixture for our attacker.
    """
    atk_mult = (1.0 / max(0.35, opp_def)) * (HOME_ATK if is_home else AWAY_ATK)
    m90 = xmins / 90.0

    lam_g = rates["xg"] * m90 * atk_mult
    lam_a = rates["xa"] * m90 * atk_mult

    lam_conceded = (LEAGUE_XG_PER_TEAM_MATCH * max(0.35, opp_atk)
                    * (HOME_DEF if is_home else AWAY_DEF))
    p_cs = poisson_pmf(0, lam_conceded)
    p_60 = p_start * 0.88

    pts = 0.0
    pts += lam_g * GOAL_PTS[pos]
    pts += lam_a * ASSIST_PTS
    # Appearance: 2 points only for reaching 60 minutes, 1 otherwise. Using
    # p_start * 2 asserted that every starter lasts 60, contradicting the
    # p_60 gate used two lines below for the clean sheet.
    pts += p_60 * 2.0 + (p_start - p_60) * 1.0 + p_sub * 1.0
    pts += p_60 * p_cs * CS_PTS[pos]

    # Goals conceded: -1 per completed pair, for GK and DEF only. Scaled by the
    # share of the match played, since the penalty has no 60-minute gate.
    if pos in (GK, DEF):
        pts -= e_floor_div(lam_conceded * m90, 2)
    if pos == GK:
        pts += e_floor_div(rates["sv"] * m90, 3)
        pts += rates["psv"] * m90 * 5.0          # penalty saves

    if defcon and pos in (DEF, MID, FWD):
        # Defensive contribution points did not exist before 2025/26. Scoring
        # them in an earlier-season backtest silently mis-specifies the target.
        lam_dc = rates["dc"] * m90
        thr = DEFCON_THRESHOLD[pos]
        p_hit = 1.0 - sum(poisson_pmf(k, lam_dc) for k in range(thr))
        pts += p_hit * DEFCON_PTS

    # Disciplinary and penalty misses. Omitting these over-projected defenders
    # by ~0.21 pts/90 and midfielders by ~0.19, concentrated in exactly the
    # high-defensive-contribution players the model is designed to surface.
    pts -= (rates["yc"] * 1.0 + rates["rc"] * 3.0
            + rates["og"] * 2.0 + rates["pm"] * 2.0) * m90

    # NOTE: the BPS formula was re-specified for 2026/27 (CBI now 1 BPS per 3
    # actions not 2, tackled-against no longer -1, keeper saves restructured).
    # These priors and this transform were fitted on the old formula, so expect
    # defender bonus to be over-projected and GK/attacker bonus under-projected
    # until this is refit on 2026/27 data. See README.
    pts += max(0.0, (rates["bps"] * m90 - 20.0) / 12.0)

    var = lam_g * (GOAL_PTS[pos] ** 2) + lam_a * (ASSIST_PTS ** 2)
    var += p_60 * p_cs * (1 - p_cs) * (CS_PTS[pos] ** 2)
    return pts * (CALIBRATION if calibration is None else calibration), var


def _conv(a, b):
    """Convolve two points distributions (dicts of points -> probability)."""
    out = {}
    for k1, p1 in a.items():
        if p1 < 1e-9:
            continue
        for k2, p2 in b.items():
            if p2 < 1e-9:
                continue
            out[k1 + k2] = out.get(k1 + k2, 0.0) + p1 * p2
    return out


def points_pmf(rates, pos, p_start, p_sub, xmins, fixtures, defcon=True,
               calibration=None, kmax=6):
    """The full distribution of FPL points, not just its mean.

    Captaincy is not a mean-maximisation problem. Doubling a steady 5.5 is worth
    less than doubling a volatile 5.0 when you need to make up rank, and worth
    more when you are protecting a lead. A single expected-points number cannot
    express that, and every service in this market throws the distribution away.

    Built by convolving the components that are genuinely independent-ish:
    goals ~ Poisson, assists ~ Poisson, clean sheet ~ Bernoulli, appearance.
    Bonus and the disciplinary terms are folded in at their expectation, since
    they are small and modelling their shape adds noise rather than signal.

    Returns {points: probability}. Approximate, and deliberately so - it is far
    closer to the truth than a normal approximation around the mean, which is
    what an sd alone implies and which is badly wrong for a quantity that is
    mostly 1, 2 or 6.

    Its mean tracks project()'s xP to within about 0.45 points on the top
    players. That gap is real and comes from bucketing to whole points plus
    folding the small terms in at expectation; the two are not meant to be
    identical, and xP remains the number to use when summing a squad. Use this
    only for questions about shape - captaincy, ceilings, rank risk.
    """
    cal = CALIBRATION if calibration is None else calibration
    dist = {0.0: 1.0}
    for opp_def, opp_atk, is_home in fixtures:
        atk_mult = (1.0 / max(0.35, opp_def)) * (HOME_ATK if is_home else AWAY_ATK)
        m90 = xmins / 90.0
        lam_g = rates["xg"] * m90 * atk_mult
        lam_a = rates["xa"] * m90 * atk_mult
        lam_conceded = (LEAGUE_XG_PER_TEAM_MATCH * max(0.35, opp_atk)
                        * (HOME_DEF if is_home else AWAY_DEF))
        p_cs = poisson_pmf(0, lam_conceded)
        p_60 = p_start * 0.88

        goals = {float(k * GOAL_PTS[pos]): poisson_pmf(k, lam_g)
                 for k in range(kmax)}
        assists = {float(k * ASSIST_PTS): poisson_pmf(k, lam_a)
                   for k in range(kmax)}
        appear = {2.0: p_60, 1.0: max(0.0, p_start - p_60) + p_sub,
                  0.0: max(0.0, 1.0 - p_start - p_sub)}
        cs_pts = CS_PTS[pos]
        clean = ({cs_pts: p_60 * p_cs, 0.0: 1.0 - p_60 * p_cs}
                 if cs_pts else {0.0: 1.0})

        # Everything else enters at expectation: small, and its shape is noise.
        flat = 0.0
        if pos in (GK, DEF):
            flat -= e_floor_div(lam_conceded * m90, 2)
        if pos == GK:
            flat += e_floor_div(rates["sv"] * m90, 3) + rates["psv"] * m90 * 5.0
        if defcon and pos in (DEF, MID, FWD):
            lam_dc = rates["dc"] * m90
            thr = DEFCON_THRESHOLD[pos]
            flat += (1.0 - sum(poisson_pmf(k, lam_dc)
                               for k in range(thr))) * DEFCON_PTS
        flat -= (rates["yc"] + rates["rc"] * 3.0 + rates["og"] * 2.0
                 + rates["pm"] * 2.0) * m90
        flat += max(0.0, (rates["bps"] * m90 - 20.0) / 12.0)

        one = _conv(_conv(goals, assists), _conv(appear, clean))
        one = {k + flat: v for k, v in one.items()}
        dist = _conv(dist, one)

    # Calibrate and bucket to whole points, which is what FPL actually pays.
    out = {}
    for k, v in dist.items():
        if v < 1e-7:
            continue
        b = int(round(k * cal))
        out[b] = out.get(b, 0.0) + v
    tot = sum(out.values()) or 1.0
    return {k: v / tot for k, v in out.items()}


def haul_probs(pmf, thresholds=(6, 10, 15)):
    """P(scoring at least N). The shape of a captaincy decision."""
    return {t: sum(v for k, v in pmf.items() if k >= t) for t in thresholds}


def project(rates, pos, p_start, p_sub, xmins, fixtures, defcon=True,
            calibration=None):
    """Sum over fixtures so double gameweeks need no special casing.

    `fixtures` is a list of (opp_def, opp_atk, is_home).
    """
    if xmins <= 0.5 or not fixtures:
        return None
    xp, var = 0.0, 0.0
    for opp_def, opp_atk, is_home in fixtures:
        p, v = project_fixture(rates, pos, p_start, p_sub, xmins,
                               opp_def, opp_atk, is_home, defcon=defcon,
                               calibration=calibration)
        xp += p
        var += v
    return dict(xp=xp, sd=math.sqrt(var), xmins=xmins,
                p_start=p_start, n_fix=len(fixtures))
