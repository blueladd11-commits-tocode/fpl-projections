#!/usr/bin/env python3
"""Rebuild every page. `--local` forces relative navigation.

The nav has to be right in two different places at once. Published artifacts
each live at their own claude.ai URL, so a relative `fixtures.html` there is a
dead link - which is exactly the crash this was written to stop. But absolute
artifact URLs are wrong when browsing the same files from a local server, where
every click would leave the site.

    python3 build.py            # artifact URLs from links.json
    python3 build.py --local    # relative, for the dev server
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = ("web.py", "ticker.py", "setpieces.py", "publish.py")


def main():
    env = dict(os.environ)
    local = "--local" in sys.argv[1:]
    if local:
        env["FPL_LINKS"] = "relative"

    print("building with {} navigation".format("relative" if local else "absolute"))
    failed = 0
    for page in PAGES:
        r = subprocess.run([sys.executable, page], cwd=HERE, env=env,
                           capture_output=True, text=True)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print("  {:<14} {}".format(page, tail[0] if tail else "ok"))
        if r.returncode:
            failed += 1
            for line in tail[1:6]:
                print("      {}".format(line))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
