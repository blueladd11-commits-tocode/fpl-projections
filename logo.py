#!/usr/bin/env python3
"""The Proper Score identity: one glyph, one wordmark, one favicon.

The name comes from *proper scoring rule* — a scoring rule a forecaster cannot
game by lying about their own confidence. The product's whole claim is that it
publishes the grade including the weeks it loses, so the identity has exactly
one job: not to overclaim.

**The glyph is a signed pair.** A baseline rule, one bar above it and one bar
below it, identical in width, length and colour. It is symmetric under a 180°
rotation, which is the point: the mark renders the same either way round and
cannot express a win without simultaneously expressing a loss. It is the visual
form of the sentence `publish.py` already implements — losses rendered
identically to wins. A tick, an arrow, a trophy or a rising chart would all
assert the one thing this brand refuses to assert.

Everything is drawn on a 16-unit grid with integer coordinates, so at 16px the
three shapes land on exact device pixels and stay crisp. That constraint drove
the design rather than decorating it: the mark was drawn at 16px first and only
then checked large.

The wordmark is live text in the site's own generic monospace stack. No font
file is fetched, and every fallback in the stack is a plain grotesque, so it
degrades to something deliberate rather than to something broken. Both words
carry the same weight — emphasising "Proper" would turn a technical term into a
boast.

    import logo
    logo.mark(24)                  # glyph alone
    logo.wordmark(24)              # glyph + name
    logo.wordmark(96)              # glyph + name + descriptor line
    logo.favicon().uri             # data: URI for <link rel="icon">
    logo.CSS                       # the (small) stylesheet the above needs

    python3 logo.py                # writes out/logo_preview.html

Contains no football, no shield, no crown, no lion, no pitch marking and no
colour in the region of #37003C. That is a legal constraint, not a taste one.
"""

import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# ---------------------------------------------------------------------------
# The glyph
# ---------------------------------------------------------------------------

# Three axis-aligned rectangles on a 16x16 grid, as one path (smaller than
# three <rect> elements, and one fill to theme):
#
#   M0 7h16v2H0z    the baseline — the naive model everything is scored against
#   M2 1h4v6H2z     a bar above it
#   M10 9h4v6h-4z   the same bar below it, rotated 180° about the centre
#
# Bars are 4u wide and 6u long; the rule is 2u thick and full-bleed. Both bars
# stop 1u short of the edge so the glyph reads as a measurement rather than as a
# letterform — at 5u wide and flush to the edges it starts to look like a "Z".
PATH = "M0 7h16v2H0zM2 1h4v6H2zM10 9h4v6h-4z"

# The name, and the descriptor it is locked to. The descriptor is not
# decoration: the naming strategy is a distinctive brand half plus a
# boringly legible product half, and the second half ships everywhere the first
# does until the name is known.
NAME = "Proper Score"
DESCRIPTOR = "FPL projections, on the record"

# Below this the descriptor renders under ~8px and stops being readable. An
# illegible line of type is worse than no line, so the lockup drops it rather
# than shipping decoration that pretends to be information.
DESCRIPTOR_MIN = 32

# Favicon colours are baked, not inherited: a favicon is rasterised outside the
# page, so currentColor resolves to black and the icon disappears on a dark tab
# strip. These are the site's own accent in each theme (var(--accent)), which is
# nowhere near Premier League purple. The light value is the default so that a
# browser ignoring the media query still gets something visible on both.
FAVICON_LIGHT = "#0F7F6E"
FAVICON_DARK = "#3ED9BC"


def mark(size=24, label=None, cls=""):
    """The glyph alone, as inline SVG.

    `label` gives the mark an accessible name for standalone use; omitted, it
    is hidden from assistive technology, which is correct next to the wordmark
    where the text already says it.
    """
    a = ('role="img" aria-label="{}"'.format(label) if label
         else 'aria-hidden="true"')
    return ('<svg class="ps-mark{c}" viewBox="0 0 16 16" width="{s}" '
            'height="{s}" fill="currentColor" {a}><path d="{p}"/></svg>'
            ).format(s=size, a=a, p=PATH, c=(" " + cls if cls else ""))


def wordmark(size=24, descriptor=None, href=None):
    """Glyph plus name, as inline SVG inside a little HTML lockup.

    `size` is the glyph's edge in px; the name is set from it, so one number
    scales the whole thing. `descriptor` defaults to showing the locked
    descriptor line only where it can actually be read (see DESCRIPTOR_MIN).
    `href` wraps the lockup in a link, for the site header.
    """
    if descriptor is None:
        descriptor = size >= DESCRIPTOR_MIN
    tag, attrs = ("a", ' href="{}"'.format(href)) if href else ("span", "")
    desc = ('<span class="ps-desc">{}</span>'.format(DESCRIPTOR)
            if descriptor else "")
    return ('<{t} class="ps-logo" style="--ps:{s}px"{a}>{m}'
            '<span class="ps-text"><span class="ps-name">{n}</span>{d}</span>'
            '</{t}>').format(t=tag, a=attrs, s=size, m=mark(size),
                             n=NAME, d=desc)


Favicon = collections.namedtuple("Favicon", "svg uri link")


def favicon():
    """The favicon SVG, its data: URI, and a ready-made <link> tag.

    Returned together because they are one artifact in three shapes and it is
    easy to hand-roll the URI wrongly — an unescaped '#' silently truncates it
    at the first colour, which fails as a blank tab icon rather than an error.
    """
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
           '<style>path{fill:%s}'
           '@media(prefers-color-scheme:dark){path{fill:%s}}</style>'
           '<path d="%s"/></svg>' % (FAVICON_LIGHT, FAVICON_DARK, PATH))
    uri = "data:image/svg+xml," + _urlish(svg)
    return Favicon(svg, uri, '<link rel="icon" href="{}">'.format(uri))


def _urlish(s):
    """Percent-encode just what a data: URI in an HTML attribute cannot carry.

    Deliberately not urllib.parse.quote: that escapes far more than necessary
    and triples the length of a string that gets inlined into every page.
    """
    for a, b in (("%", "%25"), ("#", "%23"), ("<", "%3C"), (">", "%3E"),
                 ('"', "%22"), ("{", "%7B"), ("}", "%7D"), ("&", "%26"),
                 ("'", "%27"), (" ", "%20"), ("\n", "")):
        s = s.replace(a, b)
    return s


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

# Every colour is a site variable with a fallback, so this drops into a page
# that already defines the theme and still works in one that does not. The
# mark itself takes currentColor and needs no rule at all.
CSS = """
.ps-logo{display:inline-flex;align-items:center;
  gap:calc(var(--ps,24px)*.40);text-decoration:none;color:inherit}
.ps-logo .ps-mark{display:block;flex:none;color:var(--ink,currentColor)}
.ps-text{display:flex;flex-direction:column;justify-content:center;
  gap:calc(var(--ps,24px)*.09)}
.ps-name{font-family:var(--mono,ui-monospace,"SF Mono",Menlo,monospace);
  font-weight:650;font-size:calc(var(--ps,24px)*.86);letter-spacing:-.02em;
  line-height:1;white-space:nowrap;color:var(--ink,currentColor)}
.ps-desc{font-family:var(--mono,ui-monospace,"SF Mono",Menlo,monospace);
  font-weight:400;font-size:calc(var(--ps,24px)*.29);letter-spacing:.02em;
  line-height:1;white-space:nowrap;color:var(--ink-3,#5E6873)}
a.ps-logo:hover .ps-mark{color:var(--accent,#0F7F6E)}
a.ps-logo:focus-visible{outline:2px solid var(--accent,#0F7F6E);
  outline-offset:3px}
"""

# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

# A local copy of the site's theme tokens rather than `import web`. The preview
# must render even while web.py is mid-edit, and a logo module that imports the
# page builder to draw itself is backwards.
TOKENS = """
:root{--ground:#EDEFF1;--panel:#FFFFFF;--line:#D3D8DC;--ink:#12171C;
  --ink-2:#454F58;--ink-3:#5E6873;--accent:#0F7F6E;--accent-soft:#D9EFEA;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,
    sans-serif;}
.dark{--ground:#0D1116;--panel:#151B22;--line:#27313A;--ink:#E6EBEF;
  --ink-2:#A9B5BF;--ink-3:#8A97A2;--accent:#3ED9BC;--accent-soft:#12312C;}
*{box-sizing:border-box}
body{margin:0;font-family:var(--sans);line-height:1.5}
.ground{background:var(--ground);color:var(--ink);padding:1.6rem;min-width:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;align-items:start}
@media (max-width:70rem){.grid2{grid-template-columns:1fr}}
h2{font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);font-weight:400;
  margin:0 0 1rem;padding-bottom:.5rem;border-bottom:1px solid var(--line)}
h2+p{margin-top:-.6rem}
.note{font-size:.78rem;color:var(--ink-3);max-width:60ch;margin:0 0 1.2rem}
.row{display:flex;align-items:flex-end;gap:1.6rem;flex-wrap:wrap;
  margin-bottom:1.6rem}
.spec{display:flex;flex-direction:column;align-items:flex-start;gap:.4rem}
.cap{font-family:var(--mono);font-size:.56rem;letter-spacing:.08em;
  color:var(--ink-3);text-transform:uppercase}
.mag{image-rendering:pixelated;border:1px solid var(--line);display:block}
nav{display:flex;gap:.1rem;font-family:var(--mono);font-size:.72rem;
  letter-spacing:.06em;text-transform:uppercase;flex-wrap:wrap}
nav a{padding:.4rem .75rem;border:1px solid var(--line);color:var(--ink-2);
  text-decoration:none}
nav a[aria-current="page"]{background:var(--accent);color:var(--ground);
  border-color:var(--accent)}
.hdr{display:flex;flex-direction:column;gap:1rem;background:var(--panel);
  border:1px solid var(--line);padding:1.1rem}
.hdr h1{font-family:var(--mono);font-size:1.35rem;margin:0;
  letter-spacing:-.02em;font-weight:650}
.hdr .sub{color:var(--ink-2);font-size:.86rem;margin:.3rem 0 0;max-width:66ch}
.hdr .top{display:flex;align-items:center;justify-content:space-between;
  gap:1rem;border-bottom:1px solid var(--line);padding-bottom:.9rem;
  flex-wrap:wrap}
.tab{display:inline-flex;align-items:center;gap:.5rem;background:var(--panel);
  border:1px solid var(--line);border-bottom:0;padding:.45rem .8rem;
  border-radius:6px 6px 0 0;font-size:.76rem;color:var(--ink-2);max-width:15rem}
.tabstrip{background:var(--line);padding:.5rem .5rem 0;display:flex;gap:.3rem}
.tab img{width:16px;height:16px;flex:0 0 16px}
.tab span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
code{font-family:var(--mono);font-size:.7rem;color:var(--ink-2);
  word-break:break-all}
.card{background:var(--panel);border:1px solid var(--line);padding:1.1rem;
  margin-bottom:1.2rem;overflow-x:auto}
"""

_NAV = ("Projections", "My team", "Planner", "Fixtures", "Set pieces",
        "Accuracy record")


def _panel(dark):
    """One column of the preview, at a single ground colour."""
    fav = favicon()

    def specs(kind):
        # The 96px wordmark is ~1100px wide and cannot share a column with its
        # opposite ground, so it gets a full-width band of its own below.
        out = []
        for s in ((16, 24, 48, 96) if kind == "mark" else (16, 24, 48)):
            art = mark(s, label=NAME) if kind == "mark" else wordmark(s)
            out.append('<div class="spec">{}<span class="cap">{}px</span>'
                       "</div>".format(art, s))
        return "".join(out)

    # Two magnifications of the ink mark, plus one of the favicon in its own
    # baked accent — the favicon is the case that cannot inherit anything and
    # so is the one most likely to be wrong.
    mags = "".join(
        '<div class="spec"><canvas class="mag" width="{w}" height="{w}" '
        'data-mag="{z}" data-dark="{d}" data-fill="{f}"></canvas>'
        '<span class="cap">{cap}</span></div>'.format(
            w=16 * z, z=z, d=int(dark), f=f, cap=cap)
        for z, f, cap in ((6, "", "16px &times;6"),
                          (10, "", "16px &times;10"),
                          (10, FAVICON_DARK if dark else FAVICON_LIGHT,
                           "favicon 16px &times;10")))

    tabs = "".join(
        '<div class="tab"><img src="{}" alt=""><span>{}</span></div>'.format(
            fav.uri, t) for t in ("Proper Score — FPL projections",
                                  "Accuracy record", "Gameweek 1"))

    return """<section class="ground{cls}">
<h2>{ground} ground</h2>

<div class="card">
<h2>the mark</h2>
<p class="note">A baseline, a bar above it and the same bar below it. Rotate the
whole thing 180&deg; and nothing changes &mdash; which is the argument: it shows
a loss exactly as readily as a win.</p>
<div class="row">{marks}</div>
</div>

<div class="card">
<h2>true 16px, magnified</h2>
<p class="note">Rasterised at 16&times;16 and blown up nearest-neighbour. This is
the pixel grid the tab icon and the header actually get &mdash; not a scaled
vector.</p>
<div class="row">{mags}</div>
</div>

<div class="card">
<h2>the wordmark</h2>
<p class="note">Both words at one weight. The descriptor line appears only at
{dmin}px and above, where it is still readable; below that it would be
sub-8px decoration pretending to be information.</p>
<div class="row">{words}</div>
</div>

<div class="card">
<h2>site header</h2>
<div class="hdr">
  <div class="top">{hdrlogo}<nav>{nav}</nav></div>
  <div>
    <h1>Gameweek 1 projections</h1>
    <p class="sub">Deadline 2026-08-21 17:30 UTC &middot; built 2h before the
    deadline &middot; snapshot <code>4f2ab91c07de</code>.</p>
  </div>
</div>
</div>

<div class="card">
<h2>favicon at 16px</h2>
<div class="tabstrip">{tabs}</div>
<p class="note" style="margin-top:1rem">Colour is baked, not inherited &mdash; a
favicon renders outside the page, so <code>currentColor</code> would come out
black and vanish on a dark tab strip. The SVG carries its own
<code>prefers-color-scheme</code> switch and falls back to the light-theme
accent.</p>
<p class="note"><code>{uri}</code></p>
</div>
</section>""".format(
        cls=" dark" if dark else "",
        ground="dark" if dark else "light",
        marks=specs("mark"), words=specs("word"), mags=mags,
        dmin=DESCRIPTOR_MIN,
        hdrlogo=wordmark(24, href="index.html"),
        nav="".join('<a href="#"{}>{}</a>'.format(
            ' aria-current="page"' if i == 0 else "", n)
            for i, n in enumerate(_NAV)),
        tabs=tabs, uri=fav.uri)


def _band():
    """The 96px lockup, full width, on each ground in turn."""
    rows = "".join(
        '<section class="ground{c}"><h2>the lockup at 96px &mdash; {g} '
        'ground</h2><div class="row">{w}</div></section>'.format(
            c=" dark" if d else "", g="dark" if d else "light",
            w=wordmark(96)) for d in (False, True))
    return rows


_MAG_JS = """
document.querySelectorAll('canvas[data-mag]').forEach(function(cv){
  var z=+cv.dataset.mag, dark=cv.dataset.dark==='1';
  var col=cv.dataset.fill||(dark?'#E6EBEF':'#12171C');
  var bg=dark?'#0D1116':'#EDEFF1';
  var s='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '+
        'width="16" height="16" fill="'+col+'"><path d="%s"/></svg>';
  var img=new Image();
  img.onload=function(){
    var o=document.createElement('canvas');o.width=16;o.height=16;
    var oc=o.getContext('2d');oc.fillStyle=bg;oc.fillRect(0,0,16,16);
    oc.drawImage(img,0,0,16,16);
    var c=cv.getContext('2d');c.imageSmoothingEnabled=false;
    c.drawImage(o,0,0,16*z,16*z);
  };
  img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(s);
});
"""


def preview():
    """The whole identity at every size, on both grounds, in context."""
    return ("""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Proper Score — logo</title>
{fav}
<style>{tokens}{css}</style></head><body>
<div class="grid2">{light}{dark}</div>{band}
<script>{js}</script>
</body></html>
""").format(fav=favicon().link, tokens=TOKENS, css=CSS,
            light=_panel(False), dark=_panel(True), band=_band(),
            js=_MAG_JS % PATH)


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    path = os.path.join(OUT, "logo_preview.html")
    with open(path, "w") as f:
        f.write(preview())
    m = mark(24)
    print("logo preview: {}".format(path))
    print("mark markup:  {} bytes (budget 1536)".format(len(m.encode())))
    print("favicon URI:  {} bytes".format(len(favicon().uri.encode())))
    print("CSS:          {} bytes".format(len(CSS.encode())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
