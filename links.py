#!/usr/bin/env python3
"""Where the navigation between pages points.

Relative links (`fixtures.html`) are correct when the four pages sit in one
directory, which is how they are served locally and how they will be hosted.
They are WRONG inside a published Artifact: each page gets its own URL of the
form claude.ai/code/artifact/<uuid>, so `fixtures.html` resolves to
claude.ai/code/artifact/fixtures.html, which does not exist. Clicking a nav tab
in a published artifact was a dead link.

So the mapping is data, not a hardcoded string. `links.json` overrides any page
whose canonical URL differs from the relative default; anything absent falls
back to relative and keeps working for local and hosted use.

    python3 links.py --show
    python3 links.py --set fixtures https://claude.ai/code/artifact/<uuid>
    python3 links.py --clear
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "links.json")

PAGES = (("projections", "Projections"),
         ("myteam", "My team"),
         ("planner", "Planner"),
         ("fixtures", "Fixtures"),
         ("setpieces", "Set pieces"),
         ("scorecard", "Accuracy record"))


def load():
    if not os.path.exists(PATH):
        return {}
    try:
        return json.load(open(PATH))
    except (ValueError, OSError):
        return {}


def href(page):
    """Absolute URL if one is configured, else the relative default.

    Set FPL_LINKS=relative to force relative links regardless of links.json.
    Absolute artifact URLs are correct for the published pages but wrong when
    browsing the same files locally, where every nav click would jump off to
    claude.ai. The build that gets published sets the override; local builds
    and the dev server do not.
    """
    if os.environ.get("FPL_LINKS") == "relative":
        return "{}.html".format(page)
    return load().get(page) or "{}.html".format(page)


def nav(current):
    """The shared navigation bar. `current` is a page key, not a label."""
    out = ['<nav aria-label="Sections">']
    for key, label in PAGES:
        cur = ' aria-current="page"' if key == current else ""
        out.append('<a href="{}"{}>{}</a>'.format(href(key), cur, label))
    out.append("</nav>")
    return "".join(out)


def document(title, body, css):
    """Wrap page content in a real HTML document.

    The builders emit body content because that is what the Artifact publisher
    wants - it supplies its own head. Served standalone, that left every page in
    quirks mode with no title, no charset, and crucially **no viewport meta**:
    a phone used the legacy 980px layout viewport and scaled the whole page to
    38%, rendering 11px table text at about 4px. All the responsive work was
    already there and simply never engaged.

    Set FPL_FRAGMENT=1 to emit body-only content for artifact publishing.
    """
    if os.environ.get("FPL_FRAGMENT") == "1":
        return "<style>{}</style>\n{}".format(css, body)
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,"
            "initial-scale=1\">\n"
            "<title>{}</title>\n<style>{}</style>\n</head>\n<body>\n{}\n"
            "</body>\n</html>\n").format(title, css, body)


CSS = """
nav{display:flex;gap:.1rem;font-family:var(--mono);font-size:.72rem;
  letter-spacing:.06em;text-transform:uppercase;flex-wrap:wrap}
nav a{padding:.4rem .75rem;border:1px solid var(--line);color:var(--ink-2);
  text-decoration:none}
nav a[aria-current="page"]{background:var(--accent);color:var(--ground);
  border-color:var(--accent)}
nav a:hover:not([aria-current]){color:var(--ink);border-color:var(--ink-3)}
nav a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--set", nargs=2, metavar=("PAGE", "URL"))
    ap.add_argument("--clear", action="store_true")
    args = ap.parse_args()

    if args.clear:
        if os.path.exists(PATH):
            os.remove(PATH)
        print("cleared; navigation falls back to relative links")
        return 0

    if args.set:
        page, url = args.set
        valid = [k for k, _ in PAGES]
        if page not in valid:
            raise SystemExit("unknown page {!r}; expected one of {}".format(
                page, ", ".join(valid)))
        cfg = load()
        cfg[page] = url
        json.dump(cfg, open(PATH, "w"), indent=2, sort_keys=True)
        print("{} -> {}".format(page, url))
        return 0

    cfg = load()
    for key, label in PAGES:
        mark = "" if key in cfg else "   (relative default)"
        print("  {:<12} {}{}".format(key, href(key), mark))
    if not cfg:
        print("\nno overrides set; every link is relative")
    return 0


if __name__ == "__main__":
    sys.exit(main())
