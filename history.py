#!/usr/bin/env python3
"""Download historical gameweek data from the vaastav/Fantasy-Premier-League mirror.

Ten complete seasons (2016-17 onward) of per-player, per-gameweek FPL data.
This is the backtest foundation: it is what lets you claim an accuracy record
rather than assert one.

Usage:
    python3 history.py                 # default: last two seasons
    python3 history.py 2024-25 2025-26
"""

import os
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history")
UA = "fpl-projections/0.1"

# merged_gw is the per-player-per-gameweek spine; players_raw carries the
# season-level fields (position, team, season totals) needed to join on.
FILES = ["gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv"]

DEFAULT_SEASONS = ["2024-25", "2025-26"]


def get(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def main(seasons):
    for season in seasons:
        outdir = os.path.join(DEST, season)
        os.makedirs(outdir, exist_ok=True)
        for rel in FILES:
            url = "{}/{}/{}".format(RAW, season, rel)
            dest = os.path.join(outdir, os.path.basename(rel))
            if os.path.exists(dest):
                print("  skip (exists): {}/{}".format(season, os.path.basename(rel)))
                continue
            try:
                n = get(url, dest)
                print("  {}/{}  {:,} bytes".format(season, os.path.basename(rel), n))
            except Exception as e:
                print("  MISS {}/{}: {}".format(season, os.path.basename(rel), e))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:] or DEFAULT_SEASONS
    print("downloading seasons:", ", ".join(args))
    sys.exit(main(args))
