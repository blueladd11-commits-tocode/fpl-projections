#!/usr/bin/env python3
"""The words the site uses, in one place.

Every page had grown its own vocabulary, and the vocabulary was the one a
statistician would pick: xP, 6GW, P(10+), xP/£m, xMins, and on the scorecard a
column headed with a bare Greek rho. Each of those is precise and each of them
makes a normal person feel like they opened the wrong website.

The rule this file encodes:

    Keep the words FANTASY FOOTBALL already uses. Kill the words STATISTICS
    uses.

Those are not the same thing, and the difference is the whole point. "Bank",
"free transfer", "wildcard", "bench boost", "taking a hit" are the game's own
vocabulary - every manager knows them, and replacing them with something
plainer would be patronising and less clear, not more. "Spearman", "xP",
"P(10+)", "T-72h" are ours, they were never explained, and nobody outside the
model needs them.

The numbers do not change. Only what we call them. Where a precise term is load
bearing - the accuracy record has to survive a sceptic reading it closely - the
plain word is the label and the exact term is kept alongside it as the
supporting detail, rather than the other way round.
"""

# Table headers. (label, sub) - the sub is the small line under a heading that
# says what the number means in one breath, and it is not optional: a heading
# reading "Points" with no sub is friendlier than "xP" but no more informative.
HEAD = {
    "n":   ("Player", ""),
    "t":   ("Club", ""),
    "p":   ("Position", ""),
    "c":   ("Price", ""),
    "xp":  ("Points", "this week"),
    "tot": ("Next {n}", "total over {n} weeks"),
    "h10": ("Big week", "chance of 10+ points"),
    "ppm": ("Value", "points per £1m"),
    "ps":  ("Starting", "chance he starts"),
    "m":   ("Minutes", "expected to play"),
}

POS = {"GKP": "Goalkeeper", "DEF": "Defender",
       "MID": "Midfielder", "FWD": "Forward"}

# Short forms for places with genuinely no room - a 60px calendar cell. Even
# here they are the words a match programme would use, not ours.
POS_SHORT = {"GKP": "Keeper", "DEF": "Def", "MID": "Mid", "FWD": "Fwd"}

# Squad slots. "GKP1" is a database key wearing a label's clothes.
SLOT = {"GKP": "Keeper", "DEF": "Defender", "MID": "Midfielder", "FWD": "Forward"}


def slot_label(pos, n):
    """Keeper 1, Defender 3 - the way a person would say it out loud."""
    return "{} {}".format(SLOT.get(pos, pos), n)


def horizon(hours):
    """T-72h is a filename convention, not something to show anyone.

    Rounded deliberately: "3 days before the deadline" is what the reader needs
    to judge how much team news we could have had, and it is honest at that
    resolution. The exact hour count stays in the record and in the tooltip.
    """
    if hours is None:
        return "before the deadline"
    h = float(hours)
    if h >= 48:
        return "{:.0f} days before the deadline".format(round(h / 24.0))
    if h >= 20:
        return "a day before the deadline"
    if h >= 3:
        return "{:.0f} hours before the deadline".format(round(h))
    if h >= 1:
        return "{:.0f} hours before the deadline".format(round(h))
    return "minutes before the deadline"


def horizon_short(hours):
    """The same thing where a table cell has to hold it."""
    if hours is None:
        return "—"
    h = float(hours)
    if h >= 48:
        return "{:.0f} days early".format(round(h / 24.0))
    if h >= 20:
        return "1 day early"
    return "{:.0f}h early".format(round(h))


# Fixture difficulty. "atk"/"dfn" are variable names that reached the screen.
DIFFICULTY = {
    "atk": ("Good for attackers", "how much the opponent concedes"),
    "dfn": ("Good for defenders", "how little the opponent scores"),
}

# Double and blank gameweeks. Both are FPL vocabulary, but only just - a new
# manager meets "BGW" long before anyone explains it.
FIXTURE = {
    "dgw": ("Two games", "plays twice this week"),
    "bgw": ("No game", "does not play this week"),
}

# The accuracy record. This is the page a sceptic reads hardest, so the plain
# word leads and the exact statistic is kept as the supporting line rather than
# dropped - removing it would make the claim weaker, not friendlier.
ACCURACY = {
    "rho": ("How well we ranked players",
            "Spearman rank correlation, -1 to 1, higher is better"),
    "ours": ("Us", ""),
    "base": ("Simple guess", ""),
    "delta": ("We won by", "our score minus the simple guess"),
    "baseline": ("simple guess",
                 "a player's average over his last six gameweeks"),
    "snapshot": ("Data fingerprint",
                 "SHA-256 of the exact data file the projection came from, so "
                 "anyone can check we did not change it afterwards"),
}

# Shown once, near the first table that uses these numbers. Ordered by how
# early a reader meets the term, not alphabetically.
GLOSSARY = (
    ("PS Rating",
     "Our one-number verdict on a player, out of 100. It blends what he should "
     "score this week, how his next six weeks look, how explosive he is for the "
     "points he is projected, and what he costs - then docks him if we are not "
     "confident he starts. It is scored against his own position, so a "
     "defender on 85 and a forward on 85 are both near the top of their trade."),
    ("Points",
     "How many points we expect this player to score this week. A 6.0 means "
     "we think six is his most likely return, not that he is guaranteed it."),
    ("Big week",
     "The chance he scores 10 or more. Two players can expect the same points "
     "while one is far more likely to explode - that is the player you "
     "captain."),
    ("Value",
     "Points per £1m of price. Useful when money is tight, misleading on "
     "its own: the cheapest points in the game will not win you a mini-league."),
    ("Starting",
     "The chance he is in the eleven when the whistle goes. Everything else on "
     "this page is worthless if he is on the bench, which is why it is here."),
    ("Minutes",
     "How long we expect him on the pitch."),
    ("Why are these smaller than other sites' numbers?",
     "Because ours are calibrated: when we say four points, reality pays "
     "about four. Last season exactly one player in the league sustained "
     "more than 6.3 points a week - a site showing you several players at "
     "7 is describing the player's best day, not his average one. The "
     "accuracy record page shows the receipts."),
)


def glossary_html(css_class="gloss"):
    """A plain-language panel, collapsed, near the first table that needs it."""
    items = "".join(
        "<div><dt>{}</dt><dd>{}</dd></div>".format(t, d) for t, d in GLOSSARY)
    return ('<details class="{}"><summary>What do these numbers mean?</summary>'
            '<dl>{}</dl></details>'.format(css_class, items))


CSS = """
.gloss{border:1px solid var(--line);background:var(--panel);margin:0 0 1rem;
  border-radius:3px}
.gloss summary{cursor:pointer;padding:.6rem .85rem;font-size:.86rem;
  color:var(--ink);list-style:none;display:flex;align-items:center;gap:.45rem}
.gloss summary::-webkit-details-marker{display:none}
.gloss summary:before{content:"?";display:inline-flex;align-items:center;
  justify-content:center;width:1.15rem;height:1.15rem;border-radius:50%;
  background:var(--accent-soft);color:var(--accent);font-size:.72rem;
  font-weight:700;flex:none}
.gloss summary:hover{color:var(--accent)}
.gloss[open] summary{border-bottom:1px solid var(--line)}
.gloss dl{margin:0;padding:.7rem .85rem .85rem;display:grid;gap:.6rem}
.gloss dt{font-weight:650;color:var(--ink);font-size:.86rem;margin-bottom:.12rem}
.gloss dd{margin:0;color:var(--ink-2);font-size:.84rem;line-height:1.5;
  max-width:62ch}
/* The small line under a column heading. Without it a friendly heading is just
   a vaguer version of the jargon it replaced. */
th .arw{font-weight:400;color:var(--accent)}
th .sub{display:block;font-weight:400;font-size:.62rem;color:var(--ink-3);
  letter-spacing:0;text-transform:none;margin-top:.1rem;white-space:nowrap}
"""
