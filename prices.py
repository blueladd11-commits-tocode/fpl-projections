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


def already_have(path, ts):
    """Idempotent: the hourly job may run twice, and must not double-count."""
    if not os.path.exists(path):
        return False
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith(ts[:19] + ","):
                return True
    return False


def append(ts, rows):
    os.makedirs(PRICEDIR, exist_ok=True)
    path = path_for(ts)
    if already_have(path, ts):
        return path, 0
    new = not os.path.exists(path)
    # Read-modify-write: gzip append produces a multi-member file that most
    # readers handle, but not all, and this stays small enough not to care.
    prev = ""
    if not new:
        with gzip.open(path, "rt") as f:
            prev = f.read()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    if new:
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "wt") as f:
        f.write(prev + buf.getvalue())
    return path, len(rows)


def load_all():
    rows = []
    for p in sorted(glob.glob(os.path.join(PRICEDIR, "prices_*.csv.gz"))):
        with gzip.open(p, "rt") as f:
            rows.extend(list(csv.DictReader(f)))
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
