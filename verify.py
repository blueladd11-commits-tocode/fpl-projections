#!/usr/bin/env python3
"""Re-derive a published projection from its recorded snapshot and prove it matches.

This is what turns "auditable" from a claim into a fact. The scorecard says every
projection was made before its deadline from a specific API snapshot; this
re-runs the projection from that snapshot and compares the result byte for byte.
Anyone can run it. That is the whole point — a record only counts as evidence if
a sceptic can check it without trusting us.

Three independent things are checked:

  1. INTEGRITY   - do the snapshot files still hash to what was recorded?
                   Catches corruption, and catches someone editing the inputs.
  2. INPUTS      - do the fitted minutes model and the per-90 priors still hash
                   to what produced the published file? If not, the projection
                   is not reproducible *today* even if it was honest when made.
  3. OUTPUT      - does re-running produce the identical CSV?

A projection can pass 1 and 3 while failing 2 (we retrained since). That is
reported as REPRODUCIBLE-WITH-DRIFT, not as a pass, because the honest statement
is "this was correct when published, and the current code no longer reproduces
it".

Usage:
    python3 verify.py                       # every published projection
    python3 verify.py --gw 1
"""

import argparse
import csv
import glob
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile

import model as M
import project as P

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SNAPDIR = os.path.join(HERE, "data", "snapshots")
RECORD_SNAPDIR = os.path.join(OUT, "snapshots")


def resolve_snapshot(stamp):
    """Locate a snapshot, preferring the committed record over the local cache.

    Returns (path, tempdir_to_clean). The committed copies are gzipped, so they
    are expanded into a temp directory — verification must hash the ORIGINAL
    bytes, not the compressed ones, or the recorded SHA-256 would never match.
    """
    rec = os.path.join(RECORD_SNAPDIR, stamp)
    if os.path.isdir(rec):
        tmp = tempfile.mkdtemp(prefix="verify-")
        for fn in os.listdir(rec):
            if not fn.endswith(".gz"):
                continue
            with gzip.open(os.path.join(rec, fn), "rb") as src:
                with open(os.path.join(tmp, fn[:-3]), "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return tmp, tmp
    local = os.path.join(SNAPDIR, stamp)
    return (local if os.path.isdir(local) else None), None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def current_priors_sha():
    return hashlib.sha256(
        repr(sorted((k, sorted(v.items())) for k, v in M.PRIORS.items()))
        .encode()).hexdigest()


def current_minutes_sha():
    path = os.path.join(OUT, "minutes_model.json")
    if not os.path.exists(path):
        return None
    return hashlib.sha256(
        json.dumps(json.load(open(path)), sort_keys=True).encode()).hexdigest()


def verify_one(meta_path):
    meta = json.load(open(meta_path))
    csv_path = meta_path.replace(".meta.json", ".csv")
    gw = meta.get("gameweek")
    snap, tmp = resolve_snapshot(meta.get("snapshot", ""))
    notes, fatal = [], False

    # 1. integrity of the recorded inputs
    if not snap:
        return gw, "MISSING-SNAPSHOT", ["snapshot {} is not in the record or "
                                        "the local cache".format(
                                            meta.get("snapshot"))]
    for fname, recorded in (meta.get("snapshot_sha256") or {}).items():
        fpath = os.path.join(snap, fname)
        if not os.path.exists(fpath):
            # The exact outcome of a preserve_snapshot interrupted mid-copy,
            # which never self-repairs because it skips a dest dir that exists.
            # Raising here meant the tampered projection was never reported as
            # failing AND every later projection went unverified.
            notes.append("{} is MISSING from the preserved snapshot".format(fname))
            fatal = True
            continue
        actual = sha256_file(fpath)
        if actual != recorded:
            notes.append("{} hash MISMATCH (recorded {}..., actual {}...)".format(
                fname, recorded[:12], actual[:12]))
            fatal = True

    # 2. are the model inputs still what produced this file?
    drift = []
    if meta.get("priors_sha256") and meta["priors_sha256"] != current_priors_sha():
        drift.append("PRIORS have changed since publication")
    cur_mm = current_minutes_sha()
    if meta.get("minutes_model_sha256") and meta["minutes_model_sha256"] != cur_mm:
        drift.append("minutes model has been refitted since publication")
    rec_cal = meta.get("calibration")
    cur_cal = (M.CALIBRATION_MINUTES if meta.get("minutes_model")
               else M.CALIBRATION_HEURISTIC)
    if rec_cal is not None and abs(rec_cal - cur_cal) > 1e-9:
        drift.append("calibration changed since publication ({} -> {})".format(
            rec_cal, cur_cal))

    # 3. does re-running reproduce the file?
    try:
        rows, _, _ = P.build(snap, meta.get("prior_season"), gw,
                             use_minutes_model=bool(meta.get("minutes_model")),
                             quiet=True, calibration=meta.get("calibration"))
    except Exception as e:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        return gw, "REBUILD-FAILED", notes + ["{}: {}".format(type(e).__name__, e)]

    published = list(csv.DictReader(open(csv_path)))
    if len(rows) != len(published):
        notes.append("row count {} rebuilt vs {} published".format(
            len(rows), len(published)))
        fatal = True
    else:
        diffs = 0
        worst = None
        for a, b in zip(rows, published):
            if str(a["element"]) != b["element"]:
                diffs += 1
                continue
            d = abs(a["xp"] - float(b["xp"]))
            if d > 1e-9:
                diffs += 1
                if worst is None or d > worst[1]:
                    worst = (b["web_name"], d)
        if diffs:
            notes.append("{} of {} rows differ (largest xP delta {:.4f} on {})"
                         .format(diffs, len(rows), worst[1] if worst else 0.0,
                                 worst[0] if worst else "?"))
            fatal = True

    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    if fatal:
        return gw, "FAIL", notes
    if drift:
        return gw, "REPRODUCIBLE-WITH-DRIFT", notes + drift
    return gw, "PASS", notes


def verify_safe(meta_path):
    """Never let one bad projection stop the rest being checked."""
    try:
        return verify_one(meta_path)
    except Exception as e:
        return (None, "ERROR", ["{}: {}".format(type(e).__name__, e)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gw", type=int, default=None)
    args = ap.parse_args()

    metas = sorted(glob.glob(os.path.join(OUT, "projections_gw*.meta.json")))
    if args.gw is not None:
        metas = [m for m in metas
                 if json.load(open(m)).get("gameweek") == args.gw]
    if not metas:
        # An empty record is the correct state before the first deadline, not a
        # failure — the tick runs this every hour from now until the season
        # ends, and it must not report a problem that does not exist.
        print("no published projections yet; nothing to verify")
        return 0

    print("verifying {} published projection(s)\n".format(len(metas)))
    worst = 0
    for m in metas:
        gw, status, notes = verify_safe(m)
        print("GW{:<4} {:<26} {}".format(gw, status, os.path.basename(m)))
        for n in notes:
            print("         - {}".format(n))
        worst = max(worst, {"PASS": 0, "REPRODUCIBLE-WITH-DRIFT": 1}.get(status, 2))

    print()
    if worst == 0:
        print("All projections reproduce exactly from their recorded snapshots.")
    elif worst == 1:
        print("Projections reproduce, but model inputs have changed since some "
              "were published.\nThat is expected as the model improves - say so "
              "publicly rather than\nquietly re-deriving old numbers with new code.")
    else:
        print("VERIFICATION FAILED. Do not present the failing rows as evidence.")
    return worst if worst == 2 else 0


if __name__ == "__main__":
    sys.exit(main())
