#!/usr/bin/env python3
"""Accumulate the price and ownership time series. Start this before anything else.

FPL never publishes its price-change algorithm. It is driven by net transfers
against a hidden, ownership-scaled threshold, and the only way to model it is to
watch: sample every player's price and transfer counters hourly, and regress the
observed `cost_change_event` on the flow that preceded it.

That makes it the one genuinely unbuyable asset in this market. Nobody can sell
you a history you did not record, and every hour not collected is gone.

Which is why this file exists. `snapshot.py` was already capturing everything
hourly — but into `data/`, which is gitignored, so every snapshot taken by the
scheduled CI job was discarded when the runner terminated. Months of the most
valuable free dataset in FPL were being thrown away one hour at a time.

This writes a compact committed extract instead: one row per player per sample,
appended to a gzipped monthly CSV under out/prices/. About 40 KB a day
compressed, ~12 MB for a season, versus 1.5 MB per snapshot if we kept them all.

Usage: python3 prices.py            # append a sample from the latest snapshot
       python3 prices.py --report   # what the series can already tell us
"""

import argparse
import csv
import fcntl
import glob
import gzip
import io
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PRICEDIR = os.path.join(HERE, "out", "prices")

FIELDS = ("ts", "element", "cost", "cost_change_event", "cost_change_start",
          "transfers_in_event", "transfers_out_event", "selected_by_percent",
          "status")


def sample_from(snapdir):
    """One row per player: everything that moves a price, and nothing else."""
    with open(os.path.join(snapdir, "bootstrap.json")) as f:
        b = json.load(f)
    with open(os.path.join(snapdir, "manifest.json")) as f:
        ts = json.load(f)["taken_at_utc"]
    rows = []
    for el in b["elements"]:
        rows.append(dict(
            ts=ts[:19],
            element=el["id"],
            cost=el["now_cost"],
            cost_change_event=el.get("cost_change_event", 0),
            cost_change_start=el.get("cost_change_start", 0),
            transfers_in_event=el.get("transfers_in_event", 0),
            transfers_out_event=el.get("transfers_out_event", 0),
            selected_by_percent=el.get("selected_by_percent", "0"),
            status=el.get("status", "a"),
        ))
    return ts, rows


def path_for(ts):
    return os.path.join(PRICEDIR, "prices_{}.csv.gz".format(ts[:7]))


def read_existing(path):
    """Current contents, or "" if absent. Never raises on a damaged file.

    A gzip truncated mid-write - CI cancellation, runner eviction - raises
    EOFError on every subsequent read, which killed collection permanently and
    only showed up as `price sample: exit 1` in the tick log. Quarantine the
    damaged file and carry on: losing one month beats losing every month after.
    """
    if not os.path.exists(path):
        return ""
    try:
        with gzip.open(path, "rt") as f:
            return f.read()
    except (EOFError, OSError, UnicodeDecodeError) as e:
        bad = path + ".corrupt-{}".format(
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        os.rename(path, bad)
        print("WARNING: {} was unreadable ({}); moved to {} and starting a "
              "fresh file".format(os.path.basename(path), type(e).__name__,
                                  os.path.basename(bad)))
        return ""


def already_have(text, ts):
    """One sample per clock hour, whatever the tick cadence.

    This used to key on the exact second, which made it idempotent against a
    job running twice but not against a job running OFTEN. The tick now fires
    every 15 minutes so that the tightest projection horizon - a two-hour
    window - cannot be missed when GitHub delays a scheduled run, and at that
    cadence a per-second key quadruples the series: 599 rows a sample, a whole
    gzip rewritten into git history every time, about 59MB a season instead of
    15MB.

    Prices move once a day, around 01:30 UTC. Hourly resolution is already
    generous, so the hour is the right key and the extra ticks cost nothing.
    """
    hour = ts[:13]
    return text.startswith(hour) or ("\n" + hour) in text


def append(ts, rows):
    os.makedirs(PRICEDIR, exist_ok=True)
    path = path_for(ts)

    # Exclusive lock for the whole read-modify-write. A local run and the
    # scheduled CI job can overlap, and without this one sample is silently
    # dropped while BOTH processes report success - measured at 5/5 runs.
    lock = path + ".lock"
    with open(lock, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX)
        except OSError:
            pass  # lockless filesystem: proceed rather than lose the sample

        prev = read_existing(path)
        if already_have(prev, ts):
            return path, 0

        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=FIELDS)
        # Header keyed on CONTENT, not on file existence: a 0-byte file left by
        # a crash is "existing" but has no header, which silently ate the first
        # data row as column names on every later read.
        if not prev.strip():
            w.writeheader()
        w.writerows(rows)

        # Write to a temp file and rename. os.replace is atomic on POSIX, so a
        # reader either sees the old complete file or the new one, never a
        # half-written gzip.
        tmp = path + ".tmp"
        with gzip.open(tmp, "wt") as f:
            f.write(prev + buf.getvalue())
        os.replace(tmp, path)
    return path, len(rows)


def load_all():
    rows = []
    for p in sorted(glob.glob(os.path.join(PRICEDIR, "prices_*.csv.gz"))):
        text = read_existing(p)
        if text.strip():
            rows.extend(list(csv.DictReader(io.StringIO(text))))
    return rows


def report():
    rows = load_all()
    if not rows:
        print("no price history yet - run `python3 prices.py` to start")
        return 0
    stamps = sorted(set(r["ts"] for r in rows))
    print("price history: {:,} rows, {} samples".format(len(rows), len(stamps)))
    print("  from {}  to {}".format(stamps[0], stamps[-1]))

    # Actual observed price changes across the series.
    by_el = {}
    for r in rows:
        by_el.setdefault(r["element"], []).append(r)
    moves = []
    for el, rs in by_el.items():
        rs.sort(key=lambda r: r["ts"])
        for a, b in zip(rs, rs[1:]):
            if a["cost"] != b["cost"]:
                moves.append((b["ts"], el, int(a["cost"]), int(b["cost"]),
                              int(b["transfers_in_event"]) -
                              int(b["transfers_out_event"])))
    print("  observed price changes: {}".format(len(moves)))
    for ts, el, a, b, net in moves[:8]:
        print("    {}  element {:>4}  {:.1f} -> {:.1f}  net transfers {:+,}".format(
            ts, el, a / 10.0, b / 10.0, net))
    if not moves:
        print("    none yet - prices are frozen until the season starts, which is")
        print("    exactly why the collection has to be running before it does")
    size = sum(os.path.getsize(p)
               for p in glob.glob(os.path.join(PRICEDIR, "prices_*.csv.gz")))
    print("  on disk: {:.0f} KB compressed".format(size / 1024.0))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.report:
        return report()

    snaps = sorted(glob.glob(os.path.join(HERE, "data", "snapshots", "*")))
    if not snaps:
        raise SystemExit("no snapshots - run snapshot.py first")
    ts, rows = sample_from(snaps[-1])
    path, n = append(ts, rows)
    if n:
        print("price sample {}: {} players -> {}".format(
            ts, n, os.path.relpath(path, HERE)))
    else:
        print("price sample {}: already recorded".format(ts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
