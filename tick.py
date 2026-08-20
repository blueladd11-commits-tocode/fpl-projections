#!/usr/bin/env python3
"""One idempotent job that does whatever the season currently needs.

Run this hourly. It decides what to do from state rather than from the clock,
which matters because FPL deadlines move week to week and a fixed-time cron
would either miss one or fire against stale team news.

Each tick, in order:

  1. SNAPSHOT   always, then record the committed price/ownership sample — the record depends on captures we cannot recreate.
  2. PROJECT    if the deadline is within PROJECT_WINDOW_H and this gameweek
                has no projection yet. Late is better than early: team news
                lands in the last few hours, and project.py refuses outright
                once the deadline passes.
  3. SCORE      any settled gameweek that has a projection but no scorecard.
  4. PUBLISH    regenerate ALL pages — the scorecard (the record) and the
                projections page (the product). The projections page is rebuilt
                every tick, not only when the record changes, because it shows
                current numbers and would otherwise sit stale all week.
  5. VERIFY     re-derive every published projection from its own snapshot.

Idempotent by construction: every step is guarded by "has this already been
done", so running it twice in an hour is harmless and missing an hour is
recoverable. Exit is non-zero if anything failed, so a silent cron failure
shows up as a failure rather than as an unexplained gap in the record.

Install:
    crontab -l 2>/dev/null | grep -q fpl-projections || \\
      (crontab -l 2>/dev/null; echo "17 * * * * cd $HOME/fpl-projections && \\
       /usr/bin/python3 tick.py >> data/tick.log 2>&1") | crontab -
"""

import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SNAPDIR = os.path.join(HERE, "data", "snapshots")

# Projection horizons, in hours before the deadline. One projection is written
# per band, each timestamped and hashed independently.
#
# The earlier design took a single shot inside a 6h window, which conflated two
# different things. The PRODUCT is a page people consult all week — Scout, Hub
# and Pundit all publish days ahead and update as team news lands, because that
# is what the thing is for. The RECORD is the accuracy evidence, and needs a
# frozen pre-deadline capture.
#
# Publishing at several horizons serves both, and is strictly more informative
# than one number: it shows how much the projection improves as news arrives.
# Nobody in this market publishes that. It also removes the single point of
# failure — a machine asleep at T-3h still has T-24h and T-72h in the record.
#
# The headline scored entry is the LAST pre-deadline projection; the rest are
# published alongside it as the horizon curve.
HORIZONS_H = [72.0, 24.0, 6.0, 2.0]


def log(msg):
    print("[{}] {}".format(
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"), msg))
    sys.stdout.flush()


def run(args, label):
    """Run a step, returning True on success. Never raises: one broken step
    must not stop the others, or a scoring bug would also stop snapshotting."""
    # out/ is what GitHub Pages serves, and there the four pages sit in one
    # directory, so nav must be relative. links.json holds absolute artifact
    # URLs for artifact publishing; letting it leak into the hourly rebuild
    # would silently repoint every nav tab on the live site off to claude.ai.
    env = dict(os.environ, FPL_LINKS="relative")
    try:
        p = subprocess.run([sys.executable] + args, cwd=HERE, env=env,
                           capture_output=True, text=True, timeout=900)
    except Exception as e:
        log("{}: FAILED to launch ({})".format(label, e))
        return False
    if p.returncode != 0:
        log("{}: exit {}".format(label, p.returncode))
        for line in (p.stdout or "").strip().splitlines()[-12:]:
            log("    {}".format(line))
        for line in (p.stderr or "").strip().splitlines()[-6:]:
            log("    ! {}".format(line))
        return False
    log("{}: ok".format(label))
    return True


def latest_snapshot():
    dirs = sorted(d for d in os.listdir(SNAPDIR)
                  if os.path.isdir(os.path.join(SNAPDIR, d)))
    return os.path.join(SNAPDIR, dirs[-1]) if dirs else None


def horizon_band(hrs_to_deadline):
    """Which horizon band are we in? None if the deadline is still far off."""
    for h in sorted(HORIZONS_H):
        if hrs_to_deadline <= h:
            return h
    return None


def projected_bands(gw):
    """Horizon bands already written for this gameweek."""
    bands = set()
    for m in glob.glob(os.path.join(OUT,
                                    "projections_gw{}_*.meta.json".format(gw))):
        try:
            b = json.load(open(m)).get("horizon_h")
        except Exception:
            continue
        if b is not None:
            bands.add(float(b))
    return bands


def have_projection(gw):
    return bool(glob.glob(os.path.join(
        OUT, "projections_gw{}_*.meta.json".format(gw))))


def have_scorecard(gw):
    return os.path.exists(os.path.join(OUT, "scorecard_gw{}.json".format(gw)))


def settled_gameweeks(bootstrap):
    return [e["id"] for e in bootstrap.get("events", [])
            if e.get("finished") and e.get("data_checked")]


def main():
    os.makedirs(OUT, exist_ok=True)
    failures, changed = 0, False

    # 1. snapshot, always
    if not run(["snapshot.py"], "snapshot"):
        failures += 1

    # Record the price/ownership sample immediately after snapshotting. This
    # is the one dataset that cannot be bought or backfilled, and the CI runner
    # discards data/ when it terminates - out/prices/ is committed.
    if not run(["prices.py"], "price sample"):
        failures += 1

    snap = latest_snapshot()
    if not snap:
        log("no snapshot available; nothing else can run")
        return 1
    bootstrap = json.load(open(os.path.join(snap, "bootstrap.json")))
    manifest = json.load(open(os.path.join(snap, "manifest.json")))

    # 2. project, if we are inside the window and have not already
    gw = manifest.get("next_gw")
    deadline = manifest.get("next_deadline_utc")
    if gw is None or not deadline:
        log("no upcoming gameweek in the snapshot; season may be over")
    else:
        hrs = (datetime.fromisoformat(deadline.replace("Z", "+00:00"))
               - datetime.now(timezone.utc)).total_seconds() / 3600.0
        band = horizon_band(hrs)
        done = projected_bands(gw)
        if band is not None and band in done:
            log("GW{}: T-{:.0f}h band already projected ({:.1f}h to deadline)"
                .format(gw, band, hrs))
        elif band is not None and hrs >= 0:
            log("GW{}: {:.1f}h to deadline, projecting at the T-{:.0f}h horizon"
                .format(gw, hrs, band))
            if run(["project.py", "--top", "0", "--horizon", str(band)],
                   "project T-{:.0f}h".format(band)):
                changed = True
            else:
                failures += 1
        elif hrs < 0:
            # Deliberately loud. A gap here is a hole in the public record and
            # cannot be backfilled honestly — the snapshot exists, but a
            # projection built from it now would not be a prediction.
            if done:
                log("GW{}: deadline passed {:.1f}h ago; record has the T-{} "
                    "horizon(s)".format(
                        gw, -hrs, "/".join("{:.0f}h".format(b)
                                           for b in sorted(done, reverse=True))))
            else:
                log("GW{}: DEADLINE PASSED {:.1f}h ago WITH NO PROJECTION AT ANY "
                    "HORIZON. This gameweek is permanently missing from the "
                    "record.".format(gw, -hrs))
                failures += 1
        else:
            log("GW{}: {:.1f}h to deadline, waiting (first horizon is T-{:.0f}h)"
                .format(gw, hrs, max(HORIZONS_H)))

    # 3. score anything settled that we projected but have not scored
    for done_gw in settled_gameweeks(bootstrap):
        if not have_projection(done_gw) or have_scorecard(done_gw):
            continue
        log("GW{}: settled and unscored, scoring".format(done_gw))
        if run(["score.py", "--projections",
                os.path.join(OUT, "projections_gw{}_*.csv".format(done_gw))],
               "score GW{}".format(done_gw)):
            changed = True
        else:
            failures += 1

    # 4a. the scorecard only changes when the record does
    if changed:
        if not run(["publish.py"], "publish scorecard"):
            failures += 1
    else:
        log("publish scorecard: record unchanged, skipped")

    # 4b. the projections page always rebuilds. It reflects the latest snapshot,
    # which changed at step 1, so "nothing changed" is never true for it — and a
    # product page showing last week's numbers is worse than no product page.
    if not run(["web.py"], "publish projections"):
        failures += 1
    if not run(["ticker.py"], "publish fixtures"):
        failures += 1
    if not run(["myteam.py"], "publish my team"):
        failures += 1
    if not run(["setpieces.py"], "publish set pieces"):
        failures += 1
    if not run(["index.py"], "publish landing page"):
        failures += 1

    # 5. the record must still hold
    if not run(["verify.py"], "verify"):
        failures += 1

    log("tick complete: {}".format(
        "OK" if failures == 0 else "{} failure(s)".format(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
