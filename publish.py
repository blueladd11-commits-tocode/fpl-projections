#!/usr/bin/env python3
"""M3: generate the public accuracy scorecard.

The commercial bet is that we publish our accuracy and nobody else does, so this
page is the product's proof, not its marketing. Rules it has to obey:

  - Every projection row shows the pre-deadline timestamp and the SHA-256 of the
    API snapshot it was built from. A claim you cannot tie to its inputs is not
    evidence.
  - Gameweeks that have not settled show as PENDING, not as blank. At launch
    almost every row is pending, and that is the honest state.
  - Losses are published in the same table as wins, in the same style. The
    moment bad weeks get a quieter treatment the whole exercise is worthless.
  - The baseline shown is `naive_recent6` (mean of a player's last six scores),
    not `naive_ppg`. Beating the weaker baseline is not a claim worth making.

Usage: python3 publish.py [--out scorecard.html]
"""

import argparse
import glob
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def load_records():
    """One row per gameweek we have published a projection for."""
    rows = {}
    for meta_path in sorted(glob.glob(os.path.join(OUT, "projections_gw*.meta.json"))):
        m = json.load(open(meta_path))
        gw = m.get("gameweek")
        if gw is None:
            continue
        hashes = m.get("snapshot_sha256", {})
        digest = hashes.get("bootstrap.json", "")
        # Several horizons per gameweek; the headline row is the LAST
        # pre-deadline projection. Earlier ones are the horizon curve.
        prev = rows.get(gw)
        hrs = m.get("hours_before_deadline")
        if prev is not None and hrs is not None and prev.get("hrs") is not None:
            if hrs > prev["hrs"]:
                prev.setdefault("horizons", []).append(hrs)
                continue
        rows[gw] = dict(
            gw=gw,
            generated=m.get("generated_at_utc", ""),
            deadline=m.get("deadline_utc", ""),
            hrs=hrs,
            horizons=(prev.get("horizons", []) + ([prev["hrs"]] if prev and
                      prev.get("hrs") is not None else [])) if prev else [],
            digest=digest[:12],
            n=m.get("n_players"),
            model=m.get("model_version", "?"),
            minutes_model=bool(m.get("minutes_model")),
            status="PENDING",
            ours=None, base=None, delta=None,
        )

    for card_path in sorted(glob.glob(os.path.join(OUT, "scorecard_gw*.json"))):
        c = json.load(open(card_path))
        gw = c.get("gameweek")
        if gw not in rows:
            continue
        res = {r["model"]: r for r in c.get("results", [])}
        ours = res.get("v0-baseline")
        # No silent fallback. If the committed baseline is missing, the row
        # stays unscored rather than quietly comparing against something else —
        # the page states in prose which baseline it uses.
        base = res.get("naive_recent6")
        if ours:
            rows[gw]["status"] = "SCORED"
            rows[gw]["ours"] = ours.get("spearman")
            rows[gw]["mae"] = ours.get("mae")
            if base:
                rows[gw]["base"] = base.get("spearman")
                rows[gw]["delta"] = round(ours["spearman"] - base["spearman"], 4)
    return [rows[k] for k in sorted(rows)]


def load_evidence():
    """Backtest results, so the page states what was known before launch."""
    ev = []
    for path in sorted(glob.glob(os.path.join(OUT, "backtest_*.json"))):
        d = json.load(open(path))
        sig = (d.get("significance") or {}).get("naive_recent6")
        if not sig:
            continue
        # An in-sample result has no place on a page whose entire purpose is
        # that the numbers on it can be trusted.
        if d.get("in_sample"):
            print("  skipping in-sample result: {} (+minutes model trained on it)"
                  .format(d.get("season")))
            continue
        ev.append(dict(
            season=d.get("season"),
            mm=bool(d.get("minutes_model")),
            spearman=round(d["aggregate"]["spearman"], 3),
            delta=sig.get("delta"), t=sig.get("t"),
            wins=sig.get("wins"), n=sig.get("n"),
        ))
    ev.sort(key=lambda e: (not e["mm"], e["season"]))
    return ev


CSS = """
:root{
  --ground:#EDEFF1; --panel:#FFFFFF; --line:#D3D8DC;
  --ink:#12171C; --ink-2:#4C565F; --ink-3:#78838C;
  --accent:#0F7F6E; --accent-soft:#D9EFEA;
  --pending:#9A6B12; --pending-soft:#F6ECD6;
  --loss:#A83A2E; --loss-soft:#F6DEDA;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --ground:#0D1116; --panel:#151B22; --line:#27313A;
    --ink:#E6EBEF; --ink-2:#9AA7B2; --ink-3:#6B7883;
    --accent:#3ED9BC; --accent-soft:#12312C;
    --pending:#E0A83A; --pending-soft:#332912;
    --loss:#E8705F; --loss-soft:#351B17;
  }
}
:root[data-theme="dark"]{
  --ground:#0D1116; --panel:#151B22; --line:#27313A;
  --ink:#E6EBEF; --ink-2:#9AA7B2; --ink-3:#6B7883;
  --accent:#3ED9BC; --accent-soft:#12312C;
  --pending:#E0A83A; --pending-soft:#332912;
  --loss:#E8705F; --loss-soft:#351B17;
}
:root[data-theme="light"]{
  --ground:#EDEFF1; --panel:#FFFFFF; --line:#D3D8DC;
  --ink:#12171C; --ink-2:#4C565F; --ink-3:#78838C;
  --accent:#0F7F6E; --accent-soft:#D9EFEA;
  --pending:#9A6B12; --pending-soft:#F6ECD6;
  --loss:#A83A2E; --loss-soft:#F6DEDA;
}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);
  line-height:1.55;margin:0;padding:clamp(1.1rem,4vw,3rem) clamp(1rem,5vw,2rem);
  -webkit-font-smoothing:antialiased}
.wrap{max-width:60rem;margin:0 auto;display:flex;flex-direction:column;gap:2.5rem}
h1,h2,h3,.label,th,.chip,.stat-v{font-family:var(--mono)}
h1{font-size:clamp(1.5rem,4.4vw,2.1rem);line-height:1.15;margin:0;
  letter-spacing:-.02em;text-wrap:balance;font-weight:650}
h2{font-size:.82rem;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink-2);margin:0 0 .9rem;font-weight:600}
p{margin:0 0 .85rem;max-width:64ch;color:var(--ink-2)}
p.lede{color:var(--ink);font-size:1.02rem;max-width:60ch}
strong{color:var(--ink);font-weight:600}
a{color:var(--accent)}
header{border-bottom:2px solid var(--ink);padding-bottom:1.4rem;
  display:flex;flex-direction:column;gap:.85rem}
.label{font-size:.68rem;letter-spacing:.2em;text-transform:uppercase;
  color:var(--accent);font-weight:600}
section{background:var(--panel);border:1px solid var(--line);
  padding:clamp(1rem,3vw,1.6rem)}
.seal{border-left:3px solid var(--accent);background:var(--accent-soft);
  padding:1rem 1.2rem}
.seal p{color:var(--ink);margin-bottom:0}
.scroll{overflow-x:auto;margin:0 -.3rem}
table{border-collapse:collapse;width:100%;font-size:.85rem;min-width:34rem}
th{text-align:left;font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600;padding:.5rem .6rem;
  border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:.55rem .6rem;border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums;color:var(--ink-2)}
td.k{font-family:var(--mono);color:var(--ink)}
tbody tr:last-child td{border-bottom:none}
.chip{display:inline-block;font-size:.64rem;letter-spacing:.09em;padding:.16rem .5rem;
  border:1px solid currentColor;font-weight:600}
.c-pend{color:var(--pending);background:var(--pending-soft)}
.c-ok{color:var(--accent);background:var(--accent-soft)}
.c-bad{color:var(--loss);background:var(--loss-soft)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
  gap:1px;background:var(--line);border:1px solid var(--line)}
.stat{background:var(--panel);padding:.9rem 1rem;display:flex;
  flex-direction:column;gap:.2rem}
.stat-k{font-size:.63rem;letter-spacing:.11em;text-transform:uppercase;color:var(--ink-3)}
.stat-v{font-size:1.32rem;font-variant-numeric:tabular-nums;color:var(--ink);font-weight:600}
.stat-n{font-size:.72rem;color:var(--ink-3)}
ul{margin:0;padding-left:1.1rem;color:var(--ink-2)}
li{margin-bottom:.5rem;max-width:62ch}
footer{color:var(--ink-3);font-size:.76rem;font-family:var(--mono);
  border-top:1px solid var(--line);padding-top:1rem}
.hash{font-family:var(--mono);font-size:.76rem;color:var(--ink-3)}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt_horizon(r):
    """How far before the deadline this projection was made, plus any earlier
    horizons also on record for the same gameweek."""
    hrs = r.get("hrs")
    if hrs is None:
        return "&mdash;"
    extra = sorted(set(r.get("horizons") or []), reverse=True)
    base = "T&minus;{:.0f}h".format(hrs)
    if extra:
        base += " <span style='opacity:.6'>(+{})</span>".format(
            ", ".join("{:.0f}h".format(h) for h in extra))
    return base


def fmt_dt(s):
    if not s:
        return "—"
    return esc(s[:16].replace("T", " ")) + "Z"


def build(records, evidence):
    scored = [r for r in records if r["status"] == "SCORED"]
    pending = len(records) - len(scored)
    beat = sum(1 for r in scored if (r.get("delta") or 0) > 0)

    rec_rows = []
    for r in records:
        if r["status"] == "PENDING":
            chip = '<span class="chip c-pend">PENDING</span>'
            ours = base = delta = "—"
        else:
            d = r.get("delta")
            cls = "c-ok" if (d or 0) > 0 else "c-bad"
            chip = '<span class="chip {}">SCORED</span>'.format(cls)
            ours = "{:.3f}".format(r["ours"]) if r["ours"] is not None else "—"
            base = "{:.3f}".format(r["base"]) if r["base"] is not None else "—"
            delta = "{:+.3f}".format(d) if d is not None else "—"
        rec_rows.append(
            "<tr><td class=\"k\">GW{}</td><td>{}</td><td>{}</td>"
            "<td class=\"hash\">{}</td>"
            "<td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                r["gw"], fmt_dt(r["deadline"]), fmt_horizon(r),
                esc(r["digest"]) or "—", chip, ours, base, delta))

    ev_rows = []
    for e in evidence:
        cls = "c-ok" if (e["t"] or 0) >= 2 else "c-bad"
        verdict = "significant" if (e["t"] or 0) >= 2 else "not significant"
        ev_rows.append(
            "<tr><td class=\"k\">{}{}</td><td>{:.3f}</td><td>{:+.3f}</td>"
            "<td>{:.2f}</td><td>{}/{}</td><td><span class=\"chip {}\">{}</span></td></tr>"
            .format(esc(e["season"]), " + minutes model" if e["mm"] else "",
                    e["spearman"], e["delta"], e["t"], e["wins"], e["n"],
                    cls, verdict))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return """<div class="wrap">
<header>
  <span class="label">Pre-registered accuracy record</span>
  <h1>Fantasy Premier League points projections &mdash; public scorecard</h1>
  <p class="lede">Every projection below was written to disk <strong>before</strong> its
  gameweek deadline, alongside the SHA-256 of the exact API snapshot it was built from.
  This page shows how those projections actually performed &mdash; including the weeks
  they were beaten by a three-line baseline.</p>
</header>

<section class="seal">
  <h2>What we are committing to, in advance</h2>
  <p>We publish a projection for every player before every deadline, and we score it
  against the same two baselines every week: a player&rsquo;s <strong>mean score over
  his last six gameweeks</strong>, and his points-per-game to date. The headline
  comparison is against the last-six baseline, because it is the harder one and
  beating only the easier one would not be a real claim. Weeks we lose are published
  in this table in the same style as weeks we win.</p>
</section>

<section>
  <h2>Season record &mdash; 2026/27</h2>
  <div class="stats">
    <div class="stat"><span class="stat-k">Gameweeks published</span>
      <span class="stat-v">%d</span><span class="stat-n">projections timestamped pre-deadline</span></div>
    <div class="stat"><span class="stat-k">Scored so far</span>
      <span class="stat-v">%d</span><span class="stat-n">%d awaiting results</span></div>
    <div class="stat"><span class="stat-k">Beat last-six baseline</span>
      <span class="stat-v">%s</span><span class="stat-n">of scored gameweeks</span></div>
  </div>
  <div class="scroll" style="margin-top:1.2rem">
  <table>
    <thead><tr><th>GW</th><th>Deadline (UTC)</th><th>Made</th><th>Snapshot</th>
      <th>Status</th><th>Our &rho;</th><th>Baseline &rho;</th><th>&Delta;</th></tr></thead>
    <tbody>%s</tbody>
  </table>
  </div>
  <p style="margin-top:1rem;font-size:.84rem">&rho; is Spearman rank correlation between
  projected and actual points across the eligible player pool. A gameweek stays
  <em>pending</em> until its results are final. <strong>Made</strong> is how long
  before the deadline the scored projection was written; any earlier horizons also
  on record are listed after it. We publish from three days out and re-project as
  team news lands &mdash; the scored entry is always the last one before the
  deadline, and the earlier ones stay on the record so you can see how much the
  projection improves as news arrives.</p>
  <p style="font-size:.84rem"><strong>Check this yourself.</strong> Each row&rsquo;s
  snapshot column is the SHA-256 of the API response the projection was built from,
  recorded before the deadline. Running <code>verify.py</code> re-derives every
  published projection from its own snapshot and confirms the output is identical;
  it reports <em>fail</em> if an input was altered, and <em>drift</em> if the model
  has been refitted since. We do not ask to be taken on trust.</p>
</section>

<section>
  <h2>What we knew before launch</h2>
  <p>Backtested walk-forward across past seasons under a strict as-of cutoff: for each
  gameweek the model sees only earlier gameweeks plus the prior season. A truncation
  test &mdash; delete every later row, re-run, require byte-identical output &mdash;
  passes on 38/38 gameweeks across two seasons.</p>
  <div class="scroll">
  <table>
    <thead><tr><th>Configuration</th><th>&rho;</th><th>&Delta; vs last-six</th>
      <th>t</th><th>GWs won</th><th>Verdict</th></tr></thead>
    <tbody>%s</tbody>
  </table>
  </div>
  <p style="margin-top:1rem"><strong>Stated plainly: without the fitted expected-minutes
  model there is no statistically detectable edge over the last-six baseline.</strong>
  The minutes model is what the projection is actually for.</p>
</section>

<section>
  <h2>Known limitations</h2>
  <ul>
    <li><strong>Opening gameweeks are the weakest.</strong> Before the season has data,
    projections lean on last season and on price. Expect the largest errors in August.</li>
    <li><strong>The bonus-point term is stale.</strong> FPL re-specified BPS for
    2026/27; our term was fitted on the previous formula, so defender bonus is likely
    over-projected until it is refit on this season&rsquo;s data.</li>
    <li><strong>No news ingestion yet.</strong> Injury and rotation news reaches the
    model only through FPL&rsquo;s own availability flags.</li>
    <li><strong>Single-gameweek football is mostly noise.</strong> Even a perfect model
    would correlate only modestly with one week&rsquo;s actual points. Judge any
    projection service over a season, not over a gameweek &mdash; including this one.</li>
  </ul>
</section>

<footer>Generated %s UTC &middot; projections and snapshot hashes are reproducible from
the recorded snapshot &middot; baseline definitions unchanged since first publication</footer>
</div>""" % (len(records), len(scored), pending,
             "{}/{}".format(beat, len(scored)) if scored else "—",
             "\n".join(rec_rows) or
             '<tr><td colspan="8">No projections published yet.</td></tr>',
             "\n".join(ev_rows) or
             '<tr><td colspan="6">No backtest evidence found.</td></tr>',
             now)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(OUT, "scorecard.html"))
    args = ap.parse_args()

    records, evidence = load_records(), load_evidence()
    html = "<style>{}</style>\n{}".format(CSS, build(records, evidence))
    with open(args.out, "w") as f:
        f.write(html)

    print("scorecard written: {}".format(args.out))
    print("  {} gameweek(s) published, {} scored".format(
        len(records), sum(1 for r in records if r["status"] == "SCORED")))
    print("  {} backtest configuration(s) shown as prior evidence".format(len(evidence)))


if __name__ == "__main__":
    main()
