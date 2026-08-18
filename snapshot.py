#!/usr/bin/env python3
"""Immutable, timestamped capture of the FPL API.

This is the only script that MUST run on schedule from today. Everything else
can be rebuilt later; data you failed to record before a deadline is gone for
good. Snapshots are write-once and content-hashed so that a projection can
always be traced back to exactly the inputs that existed before kickoff.

Run at minimum: once ~1h before each gameweek deadline, and once after each
gameweek settles. Cron-friendly: `python3 snapshot.py`
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://fantasy.premierleague.com/api"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "snapshots")
UA = "fpl-projections/0.1 (research; contact: you@example.com)"

ENDPOINTS = {
    "bootstrap": "/bootstrap-static/",
    "fixtures": "/fixtures/",
    # Free, open, and almost nobody surfaces it: per-club editorial notes on
    # set-piece duty with a source link to the club's own site.
    "setpiece_notes": "/team/set-piece-notes/",
}


def fetch(path, retries=3):
    url = BASE + path
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def current_state(bootstrap):
    """Return (next_gw_id, next_deadline_iso) so snapshots are labelled by GW."""
    events = bootstrap.get("events", [])
    for e in events:
        if e.get("is_next"):
            return e["id"], e["deadline_time"]
    for e in events:
        if e.get("is_current"):
            return e["id"], e["deadline_time"]
    return None, None


def main():
    taken_at = datetime.now(timezone.utc)
    stamp = taken_at.strftime("%Y%m%dT%H%M%SZ")

    payloads = {}
    for name, path in ENDPOINTS.items():
        payloads[name] = fetch(path)

    bootstrap = json.loads(payloads["bootstrap"])
    gw, deadline = current_state(bootstrap)

    # Settled gameweeks, for reconstructing current-season player state. These
    # are immutable once `data_checked` is true, so capturing them here means a
    # projection can be rebuilt exactly from one snapshot directory.
    for ev in bootstrap.get("events", []):
        if ev.get("finished") and ev.get("data_checked"):
            payloads["live_gw{}".format(ev["id"])] = fetch(
                "/event/{}/live/".format(ev["id"]))

    label = "gw{}".format(gw) if gw is not None else "preseason"
    outdir = os.path.join(ROOT, "{}_{}".format(stamp, label))
    if os.path.exists(outdir):
        print("snapshot dir already exists, refusing to overwrite:", outdir)
        return 1
    os.makedirs(outdir)

    manifest = {
        "taken_at_utc": taken_at.isoformat(),
        "next_gw": gw,
        "next_deadline_utc": deadline,
        "seconds_to_deadline": None,
        "files": {},
    }
    if deadline:
        dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        manifest["seconds_to_deadline"] = int((dl - taken_at).total_seconds())

    for name, raw in payloads.items():
        fname = name + ".json"
        with open(os.path.join(outdir, fname), "wb") as f:
            f.write(raw)
        manifest["files"][fname] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Make the snapshot read-only. Not real immutability, but it turns an
    # accidental overwrite into an error instead of silent corruption.
    for fn in os.listdir(outdir):
        os.chmod(os.path.join(outdir, fn), 0o444)

    hrs = (manifest["seconds_to_deadline"] or 0) / 3600.0
    print("snapshot written: {}".format(outdir))
    print("  next GW: {}  deadline: {}  ({:.1f}h away)".format(gw, deadline, hrs))
    print("  players: {}  teams: {}".format(
        len(bootstrap.get("elements", [])), len(bootstrap.get("teams", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
