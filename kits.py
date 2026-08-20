#!/usr/bin/env python3
"""Club home-shirt icons, as one inline SVG sprite.

A table of 460 rows identified only by a three-letter code makes you read every
row. A shirt is pre-attentive: you find your Newcastle players by colour before
you have read a single word. That is the whole justification, and it only holds
if the shirts are recognisable at the size a table row actually gives them --
about 14px. Anything that does not survive 14px is bytes spent on nothing.

Two decisions follow from that constraint.

FIRST: the shirts are specs, not drawings. Twenty hand-cut SVG blobs would be
twenty things to get wrong and twenty things to re-cut when a club changes
manufacturer. A Kit is a base colour, a sleeve colour, a pattern and a trim;
one renderer turns that into markup. Adding next season's promoted side is one
line.

SECOND: the sprite is emitted once and referenced, never repeated. The
projections page draws its rows from JS, so the `<use>` markup appears once in a
template string rather than 460 times in the source -- but a server-rendered
pitch view inlines one per player, and at 86 bytes a reference against ~290
bytes of shirt that is 39KB instead of 131KB.

Colour fidelity is deliberately subordinate to distinguishability. Where this
season's actual shirt would collide with another club's at 14px, the club's
established home identity wins, because that is what a reader is matching
against anyway. Every such deviation is recorded in CONF below.

    import kits
    html = kits.sprite() + ... + kits.shirt("MCI")

Usage: python3 kits.py   ->  writes out/kits_preview.html
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# --- geometry --------------------------------------------------------------
# One silhouette, 24x24, shared by every shirt. Body occupies x 6..18; the
# sleeves reach out to x 2 and x 22. Coordinates are terse on purpose: this
# string is emitted three times in the sprite defs and every byte is real.
BODY = ("M9 3.2 12 5.8 15 3.2 18.8 4.3 22 7.8 19 11.8 18 10.8 18 21 6 21 "
        "6 10.8 5 11.8 2 7.8 5.2 4.3Z")

# Full-height bands, clipped to the silhouette. Clipping rather than tracing
# means a stripe follows the shoulder and cuff for free, and the same band
# geometry works for the sleeve overlay and the cuff trim.
SLEEVES = "M0 0h6v24H0zM18 0h6v24h-6z"
SIDES = "M6.5 0h1.5v24h-1.5zM16 0h1.5v24h-1.5z"

# Cuff and collar are drawn fat and then clipped, because trim is what carries
# the three-way blue split (Chelsea plain, Everton yellow, Ipswich white) and a
# 1.6-unit stroke lost that fight at 14px -- 1.6 units is under a device pixel
# there, so it antialiased to nothing and Everton read as Chelsea.
CUFFS = "M0 0h4v24H0zM20 0h4v24h-4z"
# A V band straddling the neckline. The clip removes the half above it, which
# leaves a collar that follows the neck exactly and costs no extra geometry.
COLLAR = "M8 1.6 12 6.2 16 1.6 16 4.4 12 9 8 4.4Z"

# The outline is the single most important line in this file. A near-black kit
# on the near-black page background, and a white kit on the light one, are both
# invisible without it. currentColor rather than var(--ink-3) directly, because
# a `use` shadow tree reliably inherits `color` in every engine, whereas custom
# properties crossing into shadow content is the newer and shakier guarantee --
# .kit sets color from the token instead. non-scaling-stroke keeps it one
# device pixel at 14px and at 28px; the numeric stroke-width is the fallback
# for engines that ignore it.
OUTLINE = ('fill="none" stroke="currentColor" stroke-width="1.4" '
           'stroke-linejoin="round" vector-effect="non-scaling-stroke"')

# Safari before 12.1 resolves only xlink:href. Emitting both takes a reference
# from 64 to 86 bytes, which is free here because the projections table builds
# its rows in JS -- the string appears once, not 460 times. Set False if a
# caller ever server-renders enough shirts for the 22 bytes to matter.
XLINK = True

# Band layouts, snapped to half units. Not computed from a period: "M1 0h2v24h
# -2z" is 13 bytes where the arithmetically even "M1.2 0h2.4v24h-2.4z" is 19,
# which across the striped clubs is ~400 bytes spent placing an edge a third of
# a device pixel more accurately than a 14px raster can resolve.
LAYOUT = {
    2: [(8, 2), (14, 2)],
    4: [(1.5, 3.5), (7.5, 3.5), (13.5, 3.5), (19.5, 3.5)],
    5: [(1, 2), (6, 2), (11, 2), (16, 2), (21, 2)],
    6: [(1, 2), (5, 2), (9, 2), (13, 2), (17, 2), (21, 2)],
}


def _bands(n, y=False):
    """n bands across the 24-unit box, clipped later to the silhouette.

    Stripe COUNT is load-bearing, not decorative: Brentford and Sunderland are
    both red-and-white vertical stripes, and four wide bands against six narrow
    ones is half of what separates them at 14px. Tone is the other half.
    """
    fmt = "M0 {0}h24v{1}H0z" if y else "M{0} 0h{1}v24h-{1}z"
    return "".join(fmt.format(a, w) for a, w in LAYOUT[n])


def _ref(name, extra=""):
    """A `<use>` of a shared def. Every shirt is assembled from these."""
    x = ' xlink:href="#{}"'.format(name) if XLINK else ""
    return '<use href="#{}"{}{}/>'.format(name, x, extra)


# --- the kits --------------------------------------------------------------
# (base, sleeve, pattern, pattern_colour, n, trim)
#   sleeve  -- None means the sleeve is the base colour
#   pattern -- "solid" | "stripes" | "hoops" | "halves" | "sash" | "side"
#   trim    -- collar and cuffs; None means no trim drawn
#
# "halves" is currently unused. It stays because it is two lines and because
# the Championship play-offs are one Blackburn or Sheffield Wednesday away
# from needing it.
#
# A "pinstripe" pattern was specified and cut. At 14px a 0.5-unit line is a
# third of a device pixel: it antialiases into a flat wash that reads as a
# slightly lighter base colour, which is a shade collision rather than a
# pattern. Brighton's actual 26/27 shirt is pinstriped and is drawn striped
# here for exactly that reason.
KITS = {
    "ARS": ("#EF0107", "#FFFFFF", "solid",   None,      0, "#FFFFFF"),
    "AVL": ("#670E36", "#95BFE5", "solid",   None,      0, "#95BFE5"),
    "BOU": ("#D31C24", None,      "stripes", "#141414", 5, "#141414"),
    "BRE": ("#EF1C13", None,      "stripes", "#FFFFFF", 4, "#EFC75E"),
    "BHA": ("#0057B8", None,      "stripes", "#FFFFFF", 5, "#FFFFFF"),
    "CHE": ("#1A4FA8", None,      "solid",   None,      0, "#FFFFFF"),
    "COV": ("#6CACE4", None,      "stripes", "#FFFFFF", 5, "#16215B"),
    "CRY": ("#FFFFFF", None,      "sash",    "#C4122E", 0, "#1B458F"),
    "EVE": ("#003399", None,      "solid",   None,      0, "#F2D200"),
    "FUL": ("#FFFFFF", "#141414", "solid",   None,      0, "#CC0000"),
    "HUL": ("#F5A623", None,      "stripes", "#141414", 5, "#FFFFFF"),
    "IPS": ("#2B57A6", None,      "side",    "#FFFFFF", 0, "#FFFFFF"),
    "LEE": ("#FFFFFF", None,      "hoops",   "#1D428A", 2, "#F5C518"),
    "LIV": ("#A00D26", None,      "solid",   None,      0, "#FFFFFF"),
    "MCI": ("#6CABDD", None,      "solid",   None,      0, "#FFFFFF"),
    "MUN": ("#CE2818", None,      "solid",   None,      0, "#141414"),
    "NEW": ("#141414", None,      "stripes", "#FFFFFF", 5, "#FFFFFF"),
    "NFO": ("#EE3A32", None,      "solid",   None,      0, "#FFFFFF"),
    "SUN": ("#C41230", None,      "stripes", "#FFFFFF", 6, "#141414"),
    "TOT": ("#FFFFFF", None,      "solid",   None,      0, "#132257"),
}

# Confidence in the 2026/27 home shirt, checked against club and kit-press
# reveals in August 2026. "identity" means the real shirt was confirmed and
# deliberately not drawn -- see the note on each.
CONF = {
    "ARS": "confirmed  red body, white raglan sleeves, burgundy accents",
    "AVL": "identity   26/27 is genuinely all-claret with sky trim only -- "
           "adidas dropped the blue sleeves and Villa fans noticed. Drawn "
           "with the sleeves anyway: a claret rectangle is a dark red "
           "rectangle at 14px, and the sleeves are the whole silhouette",
    "BOU": "identity   26/27 reads as red with gold detail; red/black stripes "
           "are the club's standing home look and the only thing that keeps "
           "them off Man Utd's square",
    "BRE": "confirmed  red/white stripes, honey-yellow collar and cuffs (Joma, "
           "worn 26/27 and 27/28)",
    "BHA": "identity   26/27 is royal blue with a white PINSTRIPE (1983 FA Cup "
           "tribute); drawn as full stripes because pinstripe dies at 14px",
    "CHE": "confirmed  royal blue, white trim",
    "COV": "confirmed  Hummel broke from solid sky blue to sky/white vertical "
           "stripes with navy pinstriping",
    "CRY": "confirmed  the Macron sash returns -- white body, red and blue "
           "diagonal, 1976 tribute",
    "EVE": "confirmed  royal blue with yellow accents, first since 21/22; the "
           "yellow is what separates it from Chelsea",
    "FUL": "confirmed  white body, black upper-sleeve panels and three "
           "stripes, red inner collar trim",
    "HUL": "confirmed  amber/black stripes, white polo collar (Oxen, 1978-79 "
           "tribute)",
    "IPS": "medium     blue with a white side stripe per the 26/27 reveal; the "
           "side bands are also what stop it reading as Chelsea",
    "LEE": "confirmed  white with blue and yellow horizontal lines; drawn as "
           "two blue hoops, which is the readable form of the same idea",
    "LIV": "confirmed  red, Candy 1989-91 rebuild, white trim; drawn deeper "
           "than the brand hex to hold the red ladder apart",
    "MCI": "confirmed  sky blue with a fade, white trim",
    "MUN": "confirmed  red with black collar and accents",
    "NEW": "confirmed  black and white stripes with blue accents",
    "NFO": "medium     26/27 is a darker red with a tonal pattern; drawn at "
           "the bright end of the red ladder on purpose, see NOTES",
    "SUN": "confirmed  red/white stripes, buttoned collar, 1937 FA Cup "
           "tribute (Hummel); drawn crimson rather than its brighter brand "
           "red to separate it from Brentford",
    "TOT": "confirmed  white with a faint tonal pattern, navy trim",
}

# Pairs a reader could plausibly confuse. The preview renders each of these
# shoulder to shoulder at 14px, because "distinguishable" is only meaningful
# side by side -- every shirt looks fine on its own. Anyone changing a colour
# above should look at that block before and after.
PAIRS = [("LIV", "NFO"), ("LIV", "MUN"), ("MUN", "NFO"), ("BRE", "SUN"),
         ("BRE", "BOU"), ("CHE", "EVE"), ("CHE", "IPS"), ("EVE", "IPS"),
         ("MCI", "COV"), ("BHA", "COV"), ("TOT", "FUL"), ("TOT", "LEE"),
         ("TOT", "CRY"), ("FUL", "LEE"), ("NEW", "HUL"), ("ARS", "MUN")]

NOTES = """
LIV/MUN/NFO Three solid reds, and the hardest problem in the set: in real life
            these ARE three similar shirts. Resolved as a lightness ladder --
            Liverpool #A00D26 deep, United #CE2818 mid, Forest #EE3A32 bright
            -- with United additionally carrying black collar and cuffs where
            the other two carry white. Lightness survives a 14px raster; hue
            does not. Do not "correct" any of these three towards its official
            brand hex without re-running the preview: the official values sit
            within a few percent of each other and the set collapses.
BRE vs SUN  Both red/white vertical stripes. Separated three ways: stripe
            count (4 wide vs 6 narrow), tone (Brentford orange-red, Sunderland
            crimson) and trim (honey vs black). Any one of those alone was not
            enough.
MCI vs COV  Near-identical sky blue, deliberately -- they really are the same
            colour. Coventry is striped; City is not.
CHE/EVE/IPS Three blues. Everton carries yellow trim, Ipswich white side
            bands, Chelsea nothing. The trim IS the signal here, so a future
            edit that drops trim to save bytes breaks this trio first.
TOT/FUL/LEE/CRY  Four white shirts. Spurs is plain with navy trim, Fulham has
            black sleeves, Leeds two blue hoops, Palace the sash. All four
            depend on the outline stroke to have any silhouette at all on the
            light theme -- see OUTLINE.
"""

FALLBACK = "kit-XXX"     # neutral shirt for a club not in KITS


def _symbol(short, kit):
    base, sleeve, pattern, pcol, n, trim = kit
    # Clip once for the whole group rather than per path: every band below is
    # a full-height rectangle that only becomes shirt-shaped by being clipped.
    out = ['<symbol id="kit-{}" viewBox="0 0 24 24"><g clip-path="url(#kc)">'
           .format(short), _ref("ks", ' fill="{}"'.format(base))]
    if pattern in ("stripes", "hoops"):
        out.append('<path d="{}" fill="{}"/>'.format(
            _bands(n, y=(pattern == "hoops")), pcol))
    elif pattern == "halves":
        out.append('<path d="M12 0h12v24H12z" fill="{}"/>'.format(pcol))
    elif pattern == "side":
        out.append('<path d="{}" fill="{}"/>'.format(SIDES, pcol))
    elif pattern == "sash":
        # Two parallel diagonals, deliberately overshooting the viewBox because
        # the clip decides where they stop.
        out.append('<path d="M-2 1 3 1 26 23 21 23Z" fill="{}"/>'
                   '<path d="M3 1 8 1 31 23 26 23Z" fill="{}"/>'
                   .format(pcol, trim))
    if sleeve:
        out.append(_ref("kv", ' fill="{}"'.format(sleeve)))
    # Trim is skipped only where it would be invisible, and cuff and collar
    # are judged separately: the cuff lands on the SLEEVE and the collar on the
    # BODY. Testing both against the sleeve cost Aston Villa its sky-blue
    # collar, which is the one piece of contrast a claret shirt has.
    if trim and pattern != "sash":
        # A contrasting sleeve already IS the contrast, so it gets no cuff. The
        # cuff band covers half the sleeve's width, and Fulham's red cuffs ate
        # enough of its black sleeves that the shirt read as plain white and
        # collided with Spurs. Only the collar, which lands on the body, is
        # drawn for a club with sleeves of its own.
        if not sleeve and trim != base:
            out.append(_ref("kf", ' fill="{}"'.format(trim)))
        if trim != base:
            out.append(_ref("kt", ' fill="{}"'.format(trim)))
    out.append("</g>")
    out.append(_ref("ko"))
    out.append("</symbol>")
    return "".join(out)


def sprite():
    """The once-per-page sprite. Emit it before the first shirt reference."""
    # Not display:none. Hiding a sprite that way has historically stopped `use`
    # from resolving into it; a zero-box absolutely positioned element is the
    # form that has always worked.
    #
    # Everything constant across the twenty shirts lives here and is referenced:
    # the silhouette, its outline, the sleeve and cuff bands, the collar. A
    # symbol then carries only what makes that club different, which is what
    # holds a shirt under 300 bytes.
    out = ['<svg class="kit-sprite" aria-hidden="true" focusable="false">'
           '<defs><path id="ks" d="{d}"/><path id="ko" d="{d}" {o}/>'
           '<clipPath id="kc"><path d="{d}"/></clipPath>'
           '<path id="kv" d="{v}"/><path id="kf" d="{f}"/>'
           '<path id="kt" d="{t}"/></defs>'
           .format(d=BODY, o=OUTLINE, v=SLEEVES, f=CUFFS, t=COLLAR)]
    for short in sorted(KITS):
        out.append(_symbol(short, KITS[short]))
    # An unknown club must degrade to a plain shirt, not to a missing glyph or
    # a traceback. Promotion happens every May and this module will be stale.
    out.append('<symbol id="{}" viewBox="0 0 24 24">{}{}</symbol>'.format(
        FALLBACK, _ref("ks", ' fill="none"'), _ref("ko")))
    out.append("</svg>")
    return "".join(out)


def shirt(team_short, label=None):
    """`<use>` reference for one club -- 63 bytes, or 85 with the xlink form.

    Decorative by default: in the projections table the club code sits in the
    very next cell, so announcing it again is noise to a screen reader. Pass
    `label` where the shirt is the only identifier, as on a pitch view.
    """
    key = team_short if team_short in KITS else "XXX"
    x = ' xlink:href="#kit-{}"'.format(key) if XLINK else ""
    if label:
        head = '<svg class="kit" role="img"><title>{}</title>'.format(label)
    else:
        head = '<svg class="kit" aria-hidden="true">'
    return '{}<use href="#kit-{}"{}/></svg>'.format(head, key, x)


CSS = """
.kit{width:1.15em;height:1.15em;display:inline-block;vertical-align:-.22em;
  color:var(--ink-3);flex:none;margin-right:.34em}
.kit-sprite{position:absolute;width:0;height:0;overflow:hidden}
.pitch .kit{width:28px;height:28px;vertical-align:middle;margin:0}
"""


# --- preview ---------------------------------------------------------------
# Palette copied from web.py rather than imported. The point of this page is to
# prove the shirts survive both themes; it must keep working while web.py is
# being edited, and a preview that cannot run is a check that never happens.
_LIGHT = "--ground:#EDEFF1;--panel:#FFFFFF;--line:#D3D8DC;--ink:#12171C;--ink-3:#5E6873"
_DARK = "--ground:#0D1116;--panel:#151B22;--line:#27313A;--ink:#E6EBEF;--ink-3:#8A97A2"

_PREVIEW_CSS = """
*{box-sizing:border-box}
body{margin:0;padding:1.5rem;background:#20262c;font-family:-apple-system,
  BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.pane{padding:1.2rem;margin-bottom:1.2rem;background:var(--ground);
  color:var(--ink);border:1px solid var(--line)}
.pane.l{""" + _LIGHT + """}
.pane.d{""" + _DARK + """}
h2{font-family:ui-monospace,Menlo,monospace;font-size:.72rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 .9rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(9.5rem,1fr));
  gap:.5rem}
.cell{background:var(--panel);border:1px solid var(--line);padding:.5rem .4rem;
  text-align:center}
.cell .row{display:flex;align-items:center;justify-content:center;gap:.5rem;
  min-height:66px}
.cell b{display:block;font-family:ui-monospace,Menlo,monospace;font-size:.66rem;
  letter-spacing:.08em;color:var(--ink-3);margin-top:.3rem}
.s14{font-size:12.2px}   /* 1.15em of 12.2px == 14px */
.s18{font-size:15.7px}
.s28{font-size:24.3px}
.s64{font-size:55.7px}
table{border-collapse:collapse;width:100%;font-size:.86rem;background:var(--panel)}
td{padding:.45rem .6rem;border-bottom:1px solid var(--line);color:var(--ink);
  white-space:nowrap}
td.n{font-weight:600}
.pairs{display:grid;grid-template-columns:repeat(auto-fill,minmax(5.4rem,1fr));
  gap:.3rem}
.pairs div{background:var(--panel);border:1px solid var(--line);padding:.35rem;
  text-align:center}
.pairs span{font-size:12.2px;display:block}
.pairs b{display:block;font-family:ui-monospace,Menlo,monospace;font-size:.6rem;
  color:var(--ink-3);letter-spacing:.06em}
.mini{display:flex;flex-wrap:wrap;gap:.15rem;font-size:12.2px;
  background:var(--panel);border:1px solid var(--line);padding:.5rem}
"""

_NAMES = {"ARS": "Arsenal", "AVL": "Aston Villa", "BOU": "Bournemouth",
          "BRE": "Brentford", "BHA": "Brighton", "CHE": "Chelsea",
          "COV": "Coventry", "CRY": "Crystal Palace", "EVE": "Everton",
          "FUL": "Fulham", "HUL": "Hull City", "IPS": "Ipswich",
          "LEE": "Leeds", "LIV": "Liverpool", "MCI": "Man City",
          "MUN": "Man Utd", "NEW": "Newcastle", "NFO": "Nott'm Forest",
          "SUN": "Sunderland", "TOT": "Spurs"}


def _preview():
    shorts = sorted(KITS)
    cells = "".join(
        '<div class="cell"><div class="row">'
        '<span class="s14">{a}</span><span class="s18">{b}</span>'
        '<span class="s28">{c}</span><span class="s64">{d}</span>'
        '</div><b>{s}</b></div>'.format(
            a=shirt(s), b=shirt(s), c=shirt(s), d=shirt(s), s=s)
        for s in shorts)
    # The 14px row on its own, with nothing next to it for scale -- this is the
    # comparison that actually matters and the grid above flatters it.
    mini = '<div class="mini">' + "".join(shirt(s) for s in shorts) + "</div>"
    pairs = '<div class="pairs">' + "".join(
        '<div><span>{}{}</span><b>{} {}</b></div>'.format(
            shirt(a), shirt(b), a, b) for a, b in PAIRS) + "</div>"
    rows = "".join(
        '<tr><td class="n">{k}Player {s}</td><td>{s}</td><td>4.2</td></tr>'
        .format(k=shirt(s, _NAMES[s]), s=s) for s in shorts)
    pane = ('<h2>{t} &middot; 14 / 18 / 28 / 64px</h2><div class="grid">{c}</div>'
            '<h2 style="margin-top:1.1rem">all 20 at 14px, adjacent</h2>{m}'
            '<h2 style="margin-top:1.1rem">confusable pairs at 14px</h2>{p}'
            '<h2 style="margin-top:1.1rem">in a table row</h2>'
            '<table>{r}</table>')
    body = ('<div class="pane d">' + pane.format(t="dark", c=cells, m=mini,
                                                 p=pairs, r=rows) + "</div>"
            '<div class="pane l">' + pane.format(t="light", c=cells, m=mini,
                                                 p=pairs, r=rows) + "</div>")
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Kit sprite preview</title><style>{}{}</style></head><body>'
            '{}\n{}\n</body></html>\n').format(_PREVIEW_CSS, CSS, sprite(), body)


def main():
    sp, ref = sprite(), len(shirt("MCI"))
    # Measure the shared defs rather than carrying a constant that goes stale
    # the first time the silhouette changes.
    defs = len(sp[:sp.index("<symbol")]) + len("</svg>")
    per = (len(sp) - defs) / float(len(KITS) + 1)
    print("sprite      {} bytes  ({} defs + {} symbols at {:.0f} each)".format(
        len(sp), defs, len(KITS) + 1, per))
    global XLINK
    XLINK, plain = False, None
    try:
        plain = len(shirt("MCI"))
    finally:
        XLINK = True
    print("reference   {} bytes  ({} with XLINK=False)".format(ref, plain))
    print("page cost   {:.1f}KB once, plus {} bytes per server-rendered shirt"
          .format((len(sp) + len(CSS)) / 1024.0, ref))
    print("            {} JS-built rows add {} bytes, not {:.1f}KB".format(
        460, ref, ref * 460 / 1024.0))
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    path = os.path.join(OUT, "kits_preview.html")
    with open(path, "w") as f:
        f.write(_preview())
    print("preview: {}".format(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
