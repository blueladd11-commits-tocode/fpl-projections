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
import time
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


def main(seasons, refresh=False):
    for season in seasons:
        outdir = os.path.join(DEST, season)
        os.makedirs(outdir, exist_ok=True)
        for rel in FILES:
            url = "{}/{}/{}".format(RAW, season, rel)
            dest = os.path.join(outdir, os.path.basename(rel))
            # An in-progress season's files keep growing, so "exists" is not
            # "current". Re-fetch anything older than a day.
            if os.path.exists(dest) and not refresh:
                age_h = (time.time() - os.path.getmtime(dest)) / 3600.0
                if age_h < 24:
                    print("  skip (fresh): {}/{}".format(
                        season, os.path.basename(rel)))
                    continue
            try:
                n = get(url, dest)
                print("  {}/{}  {:,} bytes".format(season, os.path.basename(rel), n))
            except Exception as e:
                print("  MISS {}/{}: {}".format(season, os.path.basename(rel), e))
    return 0


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if a != "--refresh"]
    refresh = "--refresh" in sys.argv[1:]
    seasons = argv or DEFAULT_SEASONS
    print("downloading seasons:", ", ".join(seasons))
    sys.exit(main(seasons, refresh))
