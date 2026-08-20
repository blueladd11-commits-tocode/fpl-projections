# Transfer & chip planner — research and build specification

Research date: 20 August 2026. Season 2026/27, before the GW1 deadline
(2026-08-21 17:30 UTC).

This is a build spec, not a discussion document. Section 1 is implementable
verbatim. Section 6 is the order to write the code in.

**Scope note.** The planner **consumes** `project.multi_gw_xp()` output via the
`xp_next` column. It must not recompute expected points, and it must not
pre-empt **M5 (the optimiser)** or **M6 (mini-league-aware optimisation)** in the
README milestones. Everything below is deliberately shaped to avoid needing a
solver.

---

## 1. The rules, exactly

Every value below was taken from one of two authoritative places:

- **[A] The live FPL API**, `game_settings` / `chips` / `events` in the
  bootstrap payload of the snapshot at
  `data/snapshots/20260820T005955Z_gw1/bootstrap.json`. This is the game's own
  configuration, not a description of it.
- **[B] The official rules page text**, extracted verbatim from the FPL
  single-page app's compiled bundle
  (`https://fantasy.premierleague.com/assets/Rules-DzLtIY6U.js`). The rules page
  at `https://fantasy.premierleague.com/help/rules` renders client-side and
  returns a 10 KB shell to any fetcher, which is why the bundle is quoted
  instead. The chunk hash will change when FPL redeploys; re-derive it from
  `assets/index-*.js` if these need re-checking.

### 1.1 Squad and budget

| Rule | Value | Source |
|---|---|---|
| Squad size | 15 | `squad_squadsize = 15` [A] |
| Starting XI | 11 | `squad_squadplay = 11` [A] |
| Budget | £100.0m | `squad_total_spend = 1000`, `ui_currency_multiplier = 10` [A] |
| Max players per club | 3 | `squad_team_limit = 3` [A] |
| Position limits | 2 GKP / 5 DEF / 5 MID / 3 FWD | already encoded in `web.py` `LIMITS` |

Prices are integers in tenths of a million throughout the API. **Do all planner
arithmetic in integer tenths and format at the edge.** Floating-point pounds
will produce £0.09999999m banks and a budget check that fails at exactly
£100.0m.

### 1.2 Free transfers

| Rule | Value | Source |
|---|---|---|
| Free transfers before your first deadline | unlimited | "Unlimited transfers can be made at no cost until your first deadline." [B] |
| Free transfers accrued per gameweek | 1 | "After your first deadline you will receive 1 free transfer each Gameweek." [B] |
| Cost of each extra transfer | −4 points | "Each additional transfer you make in the same Gameweek will deduct 4 points from your total score (Classic scoring) and match score (head-to-head scoring) at the start of the next Gameweek." [B] |
| Maximum free transfers storable | **5** | "The maximum number of free transfers you can store in any Gameweek is 5." [B]; `max_extra_free_transfers = 4` (i.e. 1 + 4) [A] |
| Hard cap on transfers in one gameweek | **20** | `transfers_cap = 20` [A]; "At other times you are limited to 20 transfers in any single Gameweek. This rule does not apply when playing a Wildcard or a Free Hit chip." [B] |
| Banked FTs when playing Wildcard or Free Hit | **retained** | "when playing either a Wildcard or your Free Hit chip, any saved free transfers are retained for the following Gameweek. If you had 2 saved free transfers, you will still have 2 saved free transfers the Gameweek after playing the chip." [B] |

**The cap changed from 2 to 5 in 2024/25 and is unchanged for 2026/27.** Fantasy
Football Scout's July 2026 rule-change round-up lists five changes for this
season — live bonus/rank updates, the BPS re-spec, a later gameweek lockdown
(09:00 UK the day after the last match), no AFCON extra transfers, and
percentile ranks — and explicitly leaves free-transfer banking and the chip
structure alone.

#### The accrual recurrence — implement exactly this

```
FT[g0] = 1                      # g0 = first gameweek after your first deadline
carry  = max(0, FT[g] - transfers_made[g])
FT[g+1] = min(5, carry + 1)
```

with, for a gameweek where a **Wildcard or Free Hit** is played:

```
transfers_made[g] := 0          # for FT accounting only
hits[g]           := 0
```

and otherwise:

```
hits[g] = 4 * max(0, transfers_made[g] - FT[g])
```

**Worked check.** 2 FTs going into GW6, Wildcard played in GW6 →
`carry = max(0, 2-0) = 2`, `FT[7] = min(5, 3) = 3`. Fantasy Football Scout:
"if you had two free unused transfers saved after the Gameweek 5 deadline and
Wildcard in Gameweek 6, you would have three transfers to use in Gameweek 7
(two saved and the weekly allotted transfer for Gameweek 7)."

**Where the community reads the wording differently.** FFS also writes "You
*don't* get an extra free transfer in the week you Wildcard," and the official
sentence "you will still have 2 saved free transfers the Gameweek after playing
the chip" reads, taken alone, as 2 → 2 rather than 2 → 3. Both are describing
the same mechanic — the *bank* passes through untouched and the ordinary weekly
+1 then applies — but the phrasing has caused enough confusion that some free
planners get it wrong in both directions. **Put the recurrence in one function,
`ftNext(ft, transfers, chip)`, so a correction is a one-line change**, and add a
line to the page saying which reading is implemented. Verify empirically in
GW7–8 against a real account; that is cheaper than arguing about it.

**Do not model the ceiling as a discard.** Sitting at 5 FTs and making zero
transfers gives `min(5, 5+1) = 5`, not 6. The sixth is lost silently. The
planner should say so out loud — "GW14: 1 FT wasted (already at the 5 cap)" — as
a warning row. No competitor surfaces this and it is a genuine, recurring, free
mistake.

**Phase footnote.** "Any transfer point deductions in the Gameweek before a
phase starts won't be deducted from the phase score." [B] This affects monthly
league standings only, never overall. Out of scope; note it in a footer if
monthly leagues ever matter.

### 1.3 When a −4 hit is worth taking

The bar is not "the incoming player outscores the outgoing by 4 this week." That
framing is everywhere in the community and it is wrong in two directions.

The correct comparison is against **the best alternative use of that transfer**,
over **the horizon the player is held**, with **the free transfer's option value
priced in**:

```
take the hit iff
  sum over g in horizon of  decay^(g-g0) * ( xP_in[g] - xP_out[g] )
  >  4  +  ftValue * (FTs consumed beyond the free allocation)
```

Two numbers make this concrete, both from FPL Review's published solver
defaults, which are the closest thing this market has to a standard:

- **`ft_value` = 1.75 points** — what one banked free transfer is worth.
- **`decay` = 0.85 per gameweek** — future gameweeks discounted 15% each.

So a hit taken for a player held six gameweeks needs roughly
`4 / (1 + 0.85 + 0.72 + 0.61 + 0.52 + 0.44) ≈ 0.94` points per gameweek of edge
to break even — *not* 4 points in week one. Conversely a hit taken on a player
you will move on from in two weeks needs about 2.2 points per gameweek. **Show
the break-even, not a verdict.** The single most useful sentence the planner can
print is: "this −4 needs +0.9 xP per gameweek over 6 GWs to pay; you are
projecting +1.4."

The one place the arithmetic genuinely does collapse to something simpler is a
blank gameweek: replacing a player with no fixture removes a guaranteed 0, so
the 60-minute appearance points alone recover 2 of the 4.

### 1.4 Chips — 2026/27

Confirmed against the API's own `chips` array [A], which is the definitive
answer to "which chips, how many, when":

| id | chip | number | start GW | stop GW | type |
|---|---|---|---|---|---|
| 1 | `wildcard` | 1 | **2** | 19 | transfer |
| 3 | `freehit` | 1 | **2** | 19 | transfer |
| 4 | `bboost` | 1 | **1** | 19 | team |
| 5 | `3xc` | 1 | **1** | 19 | team |
| 2 | `wildcard` | 1 | 20 | 38 | transfer |
| 6 | `freehit` | 1 | 20 | 38 | transfer |
| 7 | `bboost` | 1 | 20 | 38 | team |
| 8 | `3xc` | 1 | 20 | 38 | team |

**Eight chips: two each of Wildcard, Free Hit, Bench Boost, Triple Captain.**
There is no Assistant Manager chip in 2026/27.

Read the `start_event` column carefully, because it contradicts the common
summary "you get four chips from GW1":

- **Wildcard and Free Hit are not available in GW1.** "The first Wildcard will be
  available after the first Gameweek of your season" [B]. Same for Free Hit.
- **Bench Boost and Triple Captain *are* available in GW1.** "The first set of
  these chips will be available from the start of your season" [B].
- The second set becomes available from **GW20**, not GW19.

**Effects, verbatim [B]:**

| Chip | Effect |
|---|---|
| Bench Boost | "The points scored by your bench players in the Gameweek are included in your total." |
| Free Hit | "Make unlimited free transfers for a single Gameweek. At the next deadline your squad is returned to how it was at the start of the Gameweek." |
| Triple Captain | "Your captain points are tripled instead of doubled in the Gameweek." |
| Wildcard | "All transfers (including those already made) in the Gameweek are free of charge." |

**Constraints the planner must enforce:**

1. "Only one chip can be played in a single Gameweek." [B]
2. One of each chip per half. Half boundaries come from `start_event` /
   `stop_event` above — **read them from the snapshot, do not hardcode 19/20**,
   because FPL has moved them before.
3. **"The Free Hit chip cannot be played in consecutive Gameweeks. So, if the
   first chip is played in Gameweek 19, the second Free Hit cannot be made
   active until Gameweek 21."** [B] This is the rule most planners miss. It
   crosses the half boundary — it is not a within-half rule.
4. Wildcard and Free Hit "cannot be cancelled once confirmed" [B]; Bench Boost
   and Triple Captain "can be cancelled before the Gameweek deadline" [B]. UI
   copy only, but it changes how confidently the page should nudge.

**The first-half deadline is the GW19 deadline: 2027-01-02 13:30 UTC** (from
`events[18].deadline_time` in the snapshot; the Premier League's own article
gives "13:30 GMT on Saturday 2 January"). Unused first-half chips expire. The
GW20 deadline is 2027-01-06 18:30 UTC — a four-day turnaround, which is worth a
warning in the UI.

**Free Hit budget semantics.** The Free Hit squad must satisfy the £100m
constraint using the bank plus the selling value of the real squad, and then
*everything reverts* — squad, bank, and prices. A planner that lets a Free Hit
week mutate the running bank is wrong. Model it as a branch: compute the FH week
in isolation, carry the pre-FH state to `g+1` untouched.

### 1.5 Player prices and selling price

Official wording [B]:

> "Player prices change during the season dependent on the popularity of the
> player in the transfer market. Player prices do not change until the season
> starts."

> "If a player's price rises after purchase, you keep half of the increase when
> selling the player, rounded down to the nearest £0.1m as their selling price.
> As an example, if a player was purchased for £7.5m and has increased to £7.8m
> at the point they are to be sold, their selling price would be £7.6m."

And from the FAQ chunk of the same bundle:

> "Prices shown on the transfer page are players' selling prices minus any
> sell-on fee. ... To check the price you paid for a player, please use the list
> view on the transfers page."

`transfers_sell_on_fee = 0.5` and `element_sell_at_purchase_price = false` [A]
confirm the fee is live this season.

**Implement, in integer tenths:**

```js
function sellPrice(purchase, now){          // both in 0.1m units
  if (now <= purchase) return now;          // losses are taken in full
  return purchase + Math.floor((now - purchase) / 2);
}
```

Check against the official example: `75 → 78` gives `75 + floor(3/2) = 76`, i.e.
£7.6m. Correct.

**The consequence a planner must not hide:** a rise of £0.1m banks you nothing,
and a rise of £0.2m banks £0.1m, while a fall of £0.1m costs the full £0.1m.
Price movement is an asymmetric tax on your budget, and a planner that assumes
`sell = now_cost` will over-state the bank on every held player.

**But the planner cannot know your purchase prices.** See §5.2. The v1 default is
`purchase = now_cost` (so `sell = now`), stated on the page as an assumption,
with a per-player override — which is exactly what `web.py`'s transfer sidebar
already says: *"Assumes selling price equals current price."*

**Price-change prediction is out of scope for v1** and this is not a close call.
FPL never publishes the algorithm; the community reverse-engineering (ownership-
scaled net-transfer thresholds, a £0.1m/day cap, a flag that does not always fire
on the first eligible night) is a description, not a model. `out/prices/` is
currently a single month's file — `prices_2026-08.csv.gz`, columns
`ts,element,cost,cost_change_event,cost_change_start,transfers_in_event,
transfers_out_event,selected_by_percent,status` — with **zero observed price
changes**, correctly, because prices are frozen until the season starts. There is
nothing to fit yet. Revisit around GW10.

### 1.6 Deadlines

> "Deadlines are subject to change and will be 90 minutes before the kick-off
> time in the first match of the Gameweek." [B]

> "A deadline will not change within 24 hours of the scheduled time." [B]

Take deadlines from `events[].deadline_time` in the snapshot, never compute them.
They move.

---

## 2. Competitor teardown

### 2.0 A caveat on sources

**Reddit is inaccessible from this environment** — `reddit.com`, `old.reddit.com`
and the JSON API are all blocked at the fetch layer and to the browser tool, by
policy, not by rate limit. The brief asked specifically for r/FantasyPL
complaints and they are not in here. What follows is sourced from app-store and
Trustpilot reviews, published tool reviews, and the vendors' own documentation —
which turns out to be unusually candid in one important case (§2.3). Treat the
complaint list as real but incomplete, and re-run the Reddit sweep by hand
before committing to §4.

### 2.1 Fantasy Football Scout — Transfer Planner + Season Ticker

**What it is.** Two members-only tools. The **Transfer Planner** is a spreadsheet:
player boxes grouped by position, one column per gameweek, dropdown at the top of
each box to change the occupant, tick boxes marking your proposed starting XI, and
an **In / Out summary at the foot of each gameweek column**. `+` and `-` controls
hide and re-show columns. The **Season Ticker** is rows = 20 clubs, columns =
gameweeks for the whole season, red-to-blue difficulty from Scout's own home/away
form ratings, with filters for overall / attack ("teams positioned to score") /
defence ("teams likely to earn clean sheets"), an editable custom-difficulty view,
and a **"Sort by Rotation"** mode that finds complementary fixture pairings.

**What it gets right.**

- **The In/Out block at the foot of each gameweek column** is the single best
  interaction idea in this entire market. It turns a grid of players into a
  ledger of decisions without a separate screen. Steal it.
- **Search-by-anything in the dropdown**: "Typing in the first few letters of a
  player name, or even '4.5' or 'MUN' brings up a relevant shortlist." Typing a
  price or a club code is exactly what someone planning does. Steal it.
- **Sort by Rotation** is a real answer to a real question (which two £4.5m
  keepers pair?) that xP tables cannot express.
- Attack/defence difficulty split — which `ticker.py` already does better,
  because ours is computed from fitted ratings rather than hand-set tiers.

**What is wrong with it.**

- **It is a spreadsheet with a login.** Dropdowns per box means one interaction
  per change with no direct manipulation and no undo.
- **Columns hidden with `+`/`-` is a 2011 answer to horizontal overflow.** On a
  phone you are hiding data to make data fit.
- **Access is revoked when membership lapses** — the documentation says so
  outright: "If your FFS Membership expires, your access to the planner may be
  revoked." Your season's plan is hostage to a subscription. This is the
  strongest argument for our localStorage-only design.
- The documentation is silent on blanks, doubles, selling price and chips, which
  for a *planner* is a conspicuous silence.

### 2.2 Fantasy Football Hub — Ben Crellin's planner, FPL Jossy's planner

**What it is.** Two planners, both Pro/Ultra tier. **Ben Crellin's** is the
famous one: "a full overview of the upcoming fixtures, including potential double
gameweeks and blank gameweeks for the players in your squad," with prices
auto-updating on the sheet. **FPL Jossy's** plans "gameweek by gameweek" with
opponents listed by FDR alongside predicted-points columns.

**What it gets right.** Crellin's planner is the market's reference for *projected*
blanks and doubles — human-maintained forecasts of which fixtures will be
postponed and rearranged, well before FPL's own fixture list reflects them. That
is the actual product, and it is manual labour, not data (see §3.1 and §5.4).

**What is wrong with it.** The complaints are about the wrapper, and they are
severe and recent:

- The app "simply sends you to the website, which feels clunky and outdated on
  mobile, making the app almost unusable for its intended purpose."
- "Persistent login problems, frequent crashes, slow performance."
- 10 April 2026: "Still broke and had no update from support on when it will be
  fixed."
- "Won't load, sign in multiple times won't register signed in, won't load up my
  leagues."

Hub has rebuilt the app natively for 2026/27, so some of this may be fixed. The
lesson stands regardless: **the planning tool people pay most for was, for a
whole season, delivered through a mobile shell that could not reliably log in.**
Our entire delivery mechanism — a static HTML file with no auth and no network —
makes that class of failure structurally impossible. That is a marketing line and
it happens to be true.

### 2.3 FPL Review — Massive Data planner, Transfer Solver, Linear Optimiser

**What it is.** The serious one. Projections to **14 gameweeks**, a
mixed-integer optimiser over the whole horizon, and a planner UI around it: 15
players by position, pitch/list toggle, drag fixtures to reorder, click club
badges to hide teams, modals for switching players / transfers / captaincy /
adjusting transfer prices, lock and ignore flags per player, and chip selectors
for choosing deployment weeks.

**Published solver defaults — the most useful artifact in this whole research
pass**, because they are a calibrated objective function you can copy:

| Setting | Default | Meaning |
|---|---|---|
| Transfer Depth / horizon | 6 | gameweeks considered |
| FT Value | 1.75 | points a saved transfer is worth |
| Time Decay | 0.85 | per-gameweek discount on future xP |
| Bank Value | 0.10 / £1m | points value of cash in hand |
| Sub Weight | 1.00 | weight on bench xP |
| Vice-captain weight | 0.05 | |
| Sub GK / Sub1 / Sub2 / Sub3 weight | 0.03 / 0.30 / 0.10 / 0.03 | probability-of-playing weights on the bench |
| Solve Lines | 3 | alternative plans generated |
| Time limit | 300 s | |

The open-source reference implementation
(`sertalpbilal/FPL-Optimization-Tools`) uses the same shape with slightly
different numbers — `decay_base` 0.9, `ft_value_list {2:2.0, 3:1.6, 4:1.3,
5:1.1}` (declining marginal value of each additional banked transfer — a better
model than a single constant), `itb_value` 0.08, `ft_use_penalty` 0.2,
`bench_weights {0:0.03, 1:0.21, 2:0.06, 3:0.002}`, `hit_cost` 4. It also exposes
`use_wc` / `use_bb` / `use_fh` / `use_tc` as **lists of gameweeks**, and
`booked_transfers` as `[{gw, transfer_in}, {gw, transfer_out}]`. That is the
right data model for a plan and §4.3 adopts it.

**What it gets right.** It is the only tool that treats the plan as an
optimisation problem with an explicit, published, tunable objective. And it is
honest enough to ship the antidote to itself: **Sensitivity Analysis**, which
"runs multiple simulations with controlled noise injected into projections,
xMins and settings, then measures which recommendations remain robust," on the
premise "How confident should I be in this recommendation if my projections are
slightly off?" — concluding "If a move appears in most simulations, it's likely
robust. If it only appears in the regular noiseless solve, it may be marginal
and sensitive to small changes."

**What is wrong with it, and this is the important one.** **The single solver
answer is bad, and FPL Review knows it is bad, which is why sensitivity analysis
exists.** A tool that returns one optimal path from a noisy projection presents
sampling error as a decision. The user reads "GW10: Salah → Saka, +2.3" as a
recommendation when the true statement is "under one draw of the noise, this
edged out four other paths by less than the model's own standard error." Our own
README already says the same thing in different words: the honest range is +0.05
to +0.11 Spearman, not a headline number.

The design consequence is §4.5: **if we ever show a suggested path, show three,
and show what they agree on.**

Secondary problems: drag-to-reorder fixtures and modal stacks are desktop
interactions; and the free tier is metered to 5 gameweeks pre-season, 4 after.

### 2.4 The free tools people actually use

| Tool | Model | Notable |
|---|---|---|
| **LiveFPL Planner** (`plan.livefpl.net`) | free, account optional | One temporary plan savable and loadable from any device, **deleted after 4 days**; free account gets 10 plans kept indefinitely |
| **Premier Fantasy Tools** | free | All 38 gameweeks side by side, per-gameweek notes, chips in the plan summary (`TC`, `WC`), running bank per gameweek |
| **fpl.team / Plan** | freemium | Pitch + sidebar, drag fixtures, modals, solver over "millions of transfer combinations"; **free = first 3 weeks and 2 plans**; paid unlocks all weeks and 10 plans |
| **fplplanner.co.uk** | free | Lineups, captain/vice, transfer plans for all future gameweeks |
| **fplstrat.app** | free | Markets itself as "the only FPL planning tool truly optimised for your phone" — which tells you what the rest of the market is like |
| **FPL Tactics Team Planner** | free, no signup | 6-gameweek path search that explicitly weighs "banking a free transfer, making one move now and another next week, or taking a −4 hit" |
| **Plan FPL** (iOS) | free | Cross-device sync, watchlist, widgets |

**The complaints with names attached:**

- **Plan FPL, verbatim:** *"Buggy and annoying"* — a user tried to substitute a
  defender and ended up with two goalkeepers in the team. A planner that
  produces an illegal squad through its own primary interaction is worse than no
  planner. **Our validator must run on every mutation and refuse the illegal
  state, not report it afterwards** — which is precisely what `web.py`'s
  `toggle()` already does for the 15-man cap, with the comment "Refuse rather
  than accept and then report '-1 more to a full squad.'"
- **Plan FPL, verbatim:** a user *"lost all my planned transfers"* after months
  of use when the app failed to load. This is the same class of failure as this
  repo's own localStorage crash — state that cannot be loaded and cannot be
  reset from inside the app. §4.4 is written around it.
- **Metering the horizon.** fpl.team's free tier shows 3 gameweeks. FPL Review's
  free model shows 4 after GW1. **Three gameweeks is shorter than a single
  decision** — you cannot evaluate a wildcard, a hit, or a rotation pair inside
  it. This is the market's standard dark pattern and we should say so on the
  page, not just avoid it.
- **Plans that expire.** LiveFPL deletes an anonymous plan after 4 days. FFS
  revokes planner access when membership lapses.

### 2.5 What nobody ships

Ranked by how cheap they are for us and how loudly they are missing:

1. **A visible free-transfer ledger.** Every tool tracks FTs internally; none
   shows the accrual as a row you can read across, and none warns "you are at
   the 5 cap and about to waste one."
2. **Chip legality with reasons.** Nobody greys out Free Hit in GW20 after
   playing it in GW19 and says why.
3. **The break-even for a hit**, stated as points-per-gameweek rather than a
   verdict.
4. **An accuracy record attached to the projections the plan is built on.** We
   have `scorecard.html`. Nobody else has one at all. A planner that links each
   xP column to "here is how wrong this model has been" is a category of one.

---

## 3. The hard parts

### 3.1 Blanks and doubles

**How `ticker.py` already models it, and why it is right.** `build_grid()`
returns `{team_id: [[fixture, ...] per gameweek]}` — **a list per gameweek**, with
the comment: *"A list per gameweek, because a team can have two fixtures (a
double) or none (a blank). Every ticker that assumes one fixture per gameweek
quietly misleads people in exactly the weeks that matter most."* `summarise()`
then counts `blanks` (`not col`) and `doubles` (`len(col) > 1`) per team, and the
JS renders a dashed em-dash cell for a blank and stacks two chips vertically for
a double.

`project.gw_fixtures()` uses the same shape, `M.project()` sums over the fixture
list so a DGW xP is the sum of both fixtures with no special case, and
`multi_gw_xp()` returns `0.0` for a blank. `project.build()` explicitly keeps
blanking players in the table rather than dropping them:

> *"BLANK GAMEWEEK. `M.project` returns None with no fixtures, which used to drop
> every player of a blanking team from the table, the squad picker, transfers and
> set pieces — including their horizon, the one number that says 'he blanks now
> but has a great run after'."*

**So the data layer is already correct and the planner inherits it for free.**
Render rules for the calendar:

- **Blank cell**: dashed 1px border, transparent background, em-dash, `xP 0.00`
  greyed. Must be visibly *different from* an empty cell, not merely empty — a
  user must be able to tell "this player blanks" from "this row is unfilled".
- **Double cell**: two stacked fixture chips inside one cell (reuse `.cell` /
  `.fx` from `ticker.py` CSS verbatim), the summed xP once at the bottom.
- **Column header** carries `2×DGW` / `1×BGW` counts for the squad, the same
  badge `ticker.py` already renders per team.
- Row-level summary: "blanks in GW29, 33" as a chip on the player's row.

**The finding that changes the roadmap.** Right now, in the live fixture list,
**every one of the 38 gameweeks has exactly 10 fixtures and there are zero
fixtures with `event: null`.** There are no blanks and no doubles in FPL's data
and there will not be until cup progression forces postponements — realistically
from December onward, with the big ones in the GW28–GW37 range.

Two consequences, both important:

1. **A blank/double feature shipped in August displays nothing.** Do not lead
   with it. Ship the machinery (it is nearly free, given `ticker.py`) but do not
   build the marketing on an empty grid.
2. **The planner must say what it knows.** Print, in the column strip: *"No
   blanks or doubles are currently scheduled. FPL's fixture list only shows
   postponements once they happen; projected blanks and doubles for the spring
   are not in this data."* The failure mode to avoid is a user reading an
   all-10-fixture calendar as "the season is clean."
3. **Ben Crellin's projected-blanks sheet is the competitor's real moat here**,
   and it is human judgement about cup runs, not a data feed. We cannot match it
   in v1 and should not pretend to. §5.4 proposes the cheap version: a manual
   override file.

**One modelling bias to name on the page.** `multi_gw_xp` holds `xmins` constant
per fixture, so a DGW player is projected at two full matches. Real managers
rotate in a Tuesday-Saturday double. **DGW players will be systematically
over-projected**, exactly in the weeks people plan hardest. Say so in the caveat
line next to any DGW cell; do not silently ship it.

### 3.2 Multi-week transfer sequencing

The user's requirement — *"wildcard GW9, two transfers GW10, and see the
cumulative points and budget consequence"* — decomposes into three pieces of
state and one fold.

**State (adopting the FPL-Optimization-Tools shape):**

```js
plan = {
  v: 1,
  base_gw: 9,                                  // meta.gameweek of the projection
  squad: [ elementId × 15 ],                   // the squad at base_gw
  purchase: { elementId: tenths },             // optional overrides, §5.2
  bank: 5,                                     // tenths
  ft: 1,                                       // FTs available at base_gw
  chips: { "9": "wildcard", "12": "3xc" },     // gw -> chip name
  moves: [ { gw: 10, out: 427, in: 351 }, ... ],
  captain: { "9": 351, "10": 351 }             // optional, for TC weeks
}
```

`moves` is a flat list keyed by gameweek, not a per-gameweek squad snapshot.
This matters: a squad snapshot per gameweek is 6× the state, cannot express
"who did I sell to afford this", and desynchronises the moment the underlying
projection is rebuilt.

**The fold — one pure function, and it is the whole engine:**

```
simulate(plan, data) -> [ per-gameweek row ]

for g in base_gw .. base_gw + horizon - 1:
    chip      = plan.chips[g]
    moves     = plan.moves where gw == g
    squad     = apply(squad, moves)                    # validate first
    bank      = bank + sum(sellPrice(out)) - sum(now_cost(in))
    hits      = (chip in WC|FH) ? 0 : 4 * max(0, len(moves) - ft)
    xi        = bestXI(squad, xp_next[g])              # reuse web.bestXI
    xp        = sum(xi.xp)
      + (chip == "bboost") ? sum(bench.xp) : 0
      + (chip == "3xc")    ? captain.xp    : 0         # +1x on top of the +1x for C
    net       = xp - hits
    ft        = ftNext(ft, chip in WC|FH ? 0 : len(moves), chip)
    emit row(g, squad, moves, chip, ft_before, hits, bank, xp, net, cumulative)
```

Complexity: 6 gameweeks × 15 players. It runs in microseconds. **Recompute the
whole fold on every keystroke.** There is no incremental-update problem here and
inventing one is how planners get the wrong bank after an undo.

**Free Hit is the one branch.** In an FH gameweek, `squad` and `bank` for `g+1`
come from the pre-FH state, and the FH squad is validated against
`bank + sum(sellPrice(entire real squad))`. Implement it as: fold normally, then
overwrite `carry` state from the snapshot taken before the FH week. Doing it any
other way produces a plan FPL will reject.

**Validation is per-gameweek, not per-plan.** A move must leave the squad legal
*at that gameweek*: 15 players, 2/5/5/3, ≤3 per club, bank ≥ 0. `web.py`'s
`squadIssues()` already computes exactly this list; lift it unchanged and call
it once per gameweek in the fold. Illegal gameweeks get a red column header and
the row that broke it named.

### 3.3 Should we solve? No. Here is what to build instead.

**Recommendation: do not ship an optimiser in v1, and probably not in v2.**

The constraints make this decision for you, and they are not soft:

- **Pure stdlib Python, no PuLP/HiGHS/CBC.** The README defers MILP to
  **M5, pre-season 2027**, and says the full points distribution
  (**M6**) must land first. Shipping a solver in the planner would front-run two
  milestones with a worse implementation.
- **The page is a static HTML file with vanilla JS.** Any optimisation runs on
  the user's phone, in the main thread, on a page with no build step.
- **Precomputing is impossible.** The search space is conditioned on *the user's
  squad*, which is not known at build time and cannot be fetched (§5.2). You
  cannot ship answers; you can only ship a search.
- **The projections are not precise enough to justify one.** FPL Review ships
  sensitivity analysis to walk back its own solver's confidence, and our README
  is explicit that the honest edge is a range.

**Build this instead — three things, in increasing ambition:**

**(a) Live feedback on the manual plan. This is v1 and it is the product.**
The fold in §3.2 is fast enough to run on every interaction. Every number that
changes — bank, FT, hits, cumulative net xP, legality — updates instantly. That
alone is more than any free tool gives you, because the free tools that do this
meter it to three gameweeks.

**(b) Single-gameweek best-move search, per column. Cheap, and already written.**
`web.py`'s `suggestions()` is a 1-transfer search: for each of 15 owned players,
scan every affordable same-position candidate, rank by horizon gain minus a risk
penalty, dedupe on **both** sides. That is ~15 × 150 = 2,250 evaluations —
instant. Reuse it verbatim, per gameweek column, with the plan's bank and FT
state at that gameweek substituted for the current ones. Keep the existing
`PROFILES` (Safer / Balanced / Bolder) — the comment in `web.py` explains why
that framing works, and it converts "the model is wrong" into "the model is
mis-tuned."

**(c) If and only if (a) and (b) are shipped and used: a bounded beam search.**
Not a solver. A forward beam over the horizon:

- At each gameweek, generate candidate actions: roll (0 transfers), best 1
  transfer, best 2 transfers, take a −4. Prune candidates by position and
  affordability first.
- Keep a beam of the best **K = 8** partial plans by decayed cumulative net xP.
- 6 gameweeks × 8 beam × ~4 actions × 2,250 candidate evaluations ≈ 430k
  evaluations of a function that is an array lookup and an add. That is
  tractable in JS if you **chunk it across `setTimeout(…, 0)` and only run it on
  an explicit button press**, never on load, never on keystroke.
- **Show the top 3 paths, not the top 1**, and show the intersection: "all three
  paths sell Watkins in GW11; only one buys Isak." That is FPL Review's
  sensitivity result delivered for free, as a consequence of the search shape
  rather than as a separate paid feature. This is the single best differentiator
  available and it costs a `Set` intersection.
- Do **not** use a Web Worker via `Blob` URL. The artifact CSP blocks `blob:`
  workers, and the page must survive as a published Artifact.

**What I would not do, explicitly:** a wildcard squad optimiser (picking the
best 15 from scratch). It is the highest-value solve and the one that most needs
a real MILP; a greedy stdlib approximation of it will produce visibly silly
squads and damage trust in the projections that are the actual asset. Leave it
for M5.

---

## 4. Recommended design

### 4.1 Where it lives

New file `planner.py` → `out/planner.html`, following `ticker.py`'s structure
exactly: build a JSON payload, embed it, `CSS = web.CSS + "…"`, `JS = r"""…"""`,
`links.document(...)`, then

```python
problems = web.lint_js(html, ("#grid", "#ledger", "DOMContentLoaded"))
```

and the unchanged-payload short-circuit via `web._payload()`.

Wire-up, all of it required or the page is orphaned:

- `links.PAGES` — add `("planner", "Planner")`. **This rewrites the nav on all
  five existing pages**, so expect a five-file diff on the first build.
- `links.json` — add the published artifact URL once it exists.
- `build.py` `PAGES` — add `"planner.py"`, after `ticker.py` (it depends on the
  same grid).
- `tick.py` — add a `run(["planner.py"], "publish planner")` beside the existing
  `web.py` / `ticker.py` / `setpieces.py` calls.
- `index.py` `CARDS` — add the card.

**Note on neighbours.** `myteam.py` already exists and owns the *pitch* view for
a single gameweek: shape, captain, vice, bench order, sharing `fpl.squad` with
`web.py` plus `fpl.cap` / `fpl.vice` / `fpl.bench`. **Do not duplicate any of
it.** The division of labour is: `myteam.py` = one week, in depth, on a pitch;
`planner.py` = many weeks, in outline, on a grid. The planner links to My Team
for "set the XI for this week" and never renders a pitch.

### 4.2 Layout

**The row is a squad slot, not a player.** This is the one structural decision
that makes it a calendar rather than six stacked squads. Fifteen slots, ordered
GKP1–2, DEF1–5, MID1–5, FWD1–3. A slot is a *timeline*: it holds Raya from GW9,
then Sánchez from GW13. A transfer is rendered as a change of occupant partway
along a row, with a visible boundary marker in the cell where it happens.

Everything else follows from that.

```
┌───────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│           │   GW9    │   GW10   │   GW11   │   GW12   │   GW13   │   GW14   │
│           │ Sat 24/10│ Sat 31/10│ Sat 07/11│ Sat 21/11│ Sat 28/11│ Sat 05/12│
│           │ [ WC ]   │ [  + ]   │ [  + ]   │ [ TC ]   │ [  + ]   │ [  + ]   │
├───────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ Raya  ARS │  bou     │  MUN     │  ful     │  ── BGW  │▓ Sánchez ▓  bre     │
│           │  4.71    │  3.02    │  4.55    │  0.00    │  4.10    │  5.02    │
│ Sels  NFO │  WOL     │  eve     │  CRY     │  liv     │  BHA     │  ars     │
│           │  4.20    │  3.88    │  4.44    │  2.10    │  4.02    │  2.55    │
│ …                                                                            │
├───────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ FT        │  1 → 1   │  1 → 2   │  2 → 1   │  1 → 2   │  2 → 1   │  1 → 2   │
│ Transfers │  WILDCARD│    —     │    1     │    —     │    1     │    —     │
│ Hits      │    0     │    0     │    0     │    0     │    0     │    0     │
│ Bank      │  £0.4m   │  £0.4m   │  £1.1m   │  £1.1m   │  £0.3m   │  £0.3m   │
│ xP        │   62.1   │   58.4   │   61.0   │   55.2   │   59.8   │   57.3   │
│ Net (cum) │   62.1   │  120.5   │  181.5   │  236.7   │  296.5   │  353.8   │
├───────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┤
│ IN  GW11 ▸ Semenyo (£7.4m)      OUT GW11 ▸ Mbeumo (£8.1m, sells £8.0m)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

Component notes:

- **Column header** = gameweek number, deadline date (and a live countdown for
  the next one), a chip slot, and the squad's DGW/BGW badge for that week.
- **Cell** = opponent short name (lowercase = away, matching `ticker.py`'s
  convention and `myteam.py`'s), background coloured by the *position-appropriate*
  difficulty — attacking difficulty for MID/FWD, defensive for GKP/DEF, taken
  straight from `ticker.build_grid`'s `atk`/`dfn` — and the per-gameweek xP from
  `xp_next`. That per-position colour choice is something `ticker.py` computes
  and no competitor does; the planner is the place it finally pays off.
- **A transfer boundary** is a 2px left border on the first cell of the new
  occupant plus the incoming name inline. Not an arrow, not an animation.
- **The ledger** is the bottom six rows and is the reason the page exists.
  `FT 1 → 2` reads "you had 1, you end with 2." Anything that wastes an FT at the
  cap turns amber with a tooltip-free inline note.
- **The In/Out block** is Scout's idea and it goes at the foot, per gameweek,
  showing the selling price actually used.

### 4.3 Interaction model

**Not drag and drop.** State this in the code comments so nobody re-adds it.
Drag-and-drop fails here for four separate reasons: (1) the grid scrolls
horizontally, and touch-drag inside a horizontal scroller is ambiguous — the
browser cannot tell a drag from a pan without a long-press delay that makes every
interaction feel broken; (2) the source and target of a transfer are almost never
both on screen, because the target is a player you do not own yet; (3) it is not
keyboard-operable without building a parallel command path anyway, and the
existing pages are keyboard-friendly; (4) `fpl.team` ships drag-to-reorder and it
is a desktop affordance in a game played on phones.

**Instead: tap a cell → bottom sheet.**

1. **Tap any cell** in the grid → a bottom sheet slides up:
   `position:fixed; left:0; right:0; bottom:0; max-height:80svh` (`svh`, not
   `vh` — iOS Safari's collapsing URL bar makes `vh` overshoot and hides the
   confirm button under the chrome).
2. The sheet header names the slot and the gameweek: *"MID3 · from GW11 ·
   currently Mbeumo (BRE)."*
3. Three actions: **Transfer from GW11**, **Undo the GW11 move** (only if one
   exists), **View in projections** (deep link).
4. **Transfer** swaps the sheet body to a search field, autofocused, with the
   candidate list beneath. Search matches name **or club short code or price** —
   typing `4.5` lists every £4.5m player in that position, typing `MUN` lists
   United's. Steal Scout's behaviour exactly.
5. Each candidate row shows: name, club, price, **the xP delta over the rest of
   the horizon** (the number the decision turns on), `Start %`, and — if
   unaffordable at this gameweek's bank — a greyed row with the shortfall, not a
   hidden row. Showing why something is impossible is better than pretending it
   does not exist.
6. Confirm → fold re-runs → sheet closes → the grid and ledger repaint.

**Chips.** Tap the chip slot in a column header → a sheet listing all eight chips
with their legality *for that gameweek*, illegal ones greyed with the reason
spelled out: *"Free Hit — unavailable, you played Free Hit in GW19 and it cannot
be used in consecutive gameweeks"*; *"Wildcard (2nd) — not available until
GW20"*; *"Bench Boost — already planned for GW12."* Nobody does this and it is
about forty lines of JS.

**Keyboard.** Arrow keys move a cell cursor; `Enter` opens the sheet; `Esc`
closes it; `u` undoes the last move. Consistent with the existing `th` handlers
in `web.py`, which already bind `Enter` and `Space`.

**No confirmations, no modals-over-modals, no toasts.** Every action is
reversible via undo and the ledger shows the consequence immediately.

### 4.4 Persisted state

**One key, versioned:** `fpl.plan.v1`, holding the `plan` object from §3.2.

**Read `fpl.squad` as the seed** when `fpl.plan.v1` is absent, so a squad picked
on the projections page or built on My Team is already there. Do **not** write
back to `fpl.squad` from the planner — the planner's squad is a *hypothetical at
a future gameweek* and overwriting the user's actual squad with a planned one is
a data-loss bug waiting to happen. Offer an explicit "Save GW*n* squad as my
team" button instead.

**How `web.py` guards localStorage today, and why it is the pattern to copy.**
The bug it was written for is documented in the source:

> *"Shape, not just parseability. A stored object rather than an array threw
> 'squad.includes is not a function' on every load thereafter, leaving a page
> that drew its nav, filters and header with zero rows and a counter still
> reading '162 of 468 players' — and no in-app way to recover."*

Current implementation, in both `web.py` and `myteam.py`:

```js
function save(){try{localStorage.setItem("fpl.squad",JSON.stringify(squad));}catch(e){}}
function load(){
  try{
    const raw=JSON.parse(localStorage.getItem("fpl.squad")||"[]");
    squad=Array.isArray(raw)?raw.filter(x=>typeof x==="number"&&byId[x]):[];
  }catch(e){squad=[];}
}
```

Three things are right about it and must be preserved: `setItem` is wrapped
(quota and Safari private mode both throw), the parse is wrapped, and the
**shape** is validated per element rather than trusted. Note it also drops ids
not present in `byId`, which is what makes it survive a rebuilt projection set.

**The planner's state is a graph, not a flat array, so it needs more.** Required
additions:

1. **Version gate.** If `plan.v !== 1`, discard and start fresh with a one-line
   notice. Never migrate silently.
2. **Rebase on `base_gw`.** The projection rebuilds hourly and rolls forward each
   week. If `plan.base_gw !== meta.gameweek`, the stored plan describes gameweeks
   that have passed. Drop moves and chips for gameweeks `< meta.gameweek`, keep
   the rest, set `base_gw = meta.gameweek`, and **say so**: *"GW9 and GW10 have
   passed; those steps were removed from your plan."* Silently keeping them
   produces a plan whose first column is in the past.
3. **Drop unknown elements** — every `squad` id, every `moves[].in/out`, every
   `purchase` key filtered through `byId`. A move referencing a dropped player
   takes the whole move with it, with a count in the notice.
4. **A Reset button that is in the static HTML, not rendered by JS.** This is the
   real lesson of the original crash: the page failed *while rendering*, so a
   JS-rendered reset control would never have appeared. Put
   `<button id="reset">Reset plan</button>` in the body markup emitted by
   Python, and bind it in a `try` block that runs **before** any state load.
5. **Wrap the whole boot in try/catch and degrade to read-only.** If state load
   throws for any reason, render the grid with the empty plan and show a banner
   with the reset button. A planner that shows fixtures and xP with no plan is
   still useful; a blank page is not.

**Not persisted:** scroll position, sheet state, the selected risk profile
(default it to `bal` each load, as `web.py` does), and anything derived. Persist
inputs only; recompute everything else.

**Explicitly not stored anywhere but the device.** No account, no sync, no
server. Say it on the page. Given §2.1 (access revoked on lapsed membership),
§2.4 (LiveFPL's 4-day deletion), and §2.4 (a user who "lost all my planned
transfers"), this is a genuine feature and worth one sentence in the header.

### 4.5 Mobile — concretely, at 375px

The existing pages already do the hard part: `links.document()` emits the
viewport meta (the comment records that its absence once scaled a phone page to
38%), the CSS is `clamp()`-based, `.layout` is single-column below 1080px, and
`.scroll` gives horizontal overflow a container. The planner needs five specific
things on top.

1. **Two views, one toggle.** Reuse the `.seg` segmented control that
   `ticker.py` and `web.py` already style.
   - **Grid** (default ≥700px): the full matrix.
   - **Week** (default <700px): one gameweek, full width, 15 rows of
     `player · opponent · xP`, with the ledger for that week pinned above and
     `‹ GW10 ›` arrows plus horizontal swipe to move between weeks. **The Week
     view is the phone product.** A 15×6 matrix does not fit 375px and no amount
     of cleverness makes it fit; showing one week properly beats showing six
     weeks badly.
2. **Grid on a phone, when chosen, must snap.** `.gridwrap{overflow-x:auto;
   scroll-snap-type:x mandatory; -webkit-overflow-scrolling:touch}` and
   `.gw{scroll-snap-align:start; min-width:4.6rem}`. The first column (player
   name) is `position:sticky; left:0` with a solid `var(--panel)` background —
   sticky columns over a transparent background smear on iOS.
   `min-width:4.6rem` is derived: a 3-letter opponent code at `.7rem` monospace
   plus an xP to 2dp plus padding.
3. **44px minimum touch target on every cell.** The current `.fx` chip in
   `ticker.py` is `.3rem .2rem` padding at `.7rem` font — about 20px tall. That
   is fine for a read-only ticker and too small for a tappable planner cell.
   Two stacked lines (opponent, xP) at `.72rem` with `.34rem` vertical padding
   lands at ~46px.
4. **Kill the `title=` tooltips.** `ticker.py` puts difficulty in
   `title="attacking difficulty 1.02"`, which does nothing on touch — the
   information is simply unavailable to most of the audience. In the planner,
   difficulty is the cell background plus a number revealed in the sheet on tap.
5. **The sheet, not a modal.** `max-height:80svh`, `padding-bottom:
   max(1rem, env(safe-area-inset-bottom))`, the search input at the *top* of the
   sheet so the on-screen keyboard pushes the candidate list rather than the
   input, and `overscroll-behavior:contain` so scrolling the candidate list does
   not scroll the page behind it.

**The deadline-minus-ten-minutes test.** The page must, within one thumb reach
of the top on a 375px screen, answer: how long until the deadline, how many free
transfers do I have, what does the plan say to do this week. Put those three
things in a single sticky strip above the grid. Everything else can be scrolled
to.

### 4.6 Explicitly out of scope for v1

Written down so they do not creep in:

- **Any multi-gameweek optimiser or solver.** §3.3. Deferred behind M5/M6.
- **A wildcard squad builder** (best 15 from scratch). Same reason.
- **Automatic import of your live FPL team.** CORS makes it impossible; §5.2.
  The paste flow in `myteam.py` is the ceiling.
- **Price-change prediction.** §1.5. No data yet.
- **Projected (community-forecast) blanks and doubles.** §5.4. Manual override
  file at best.
- **Mini-league / rank-aware planning.** That is M6 and it needs the full points
  distribution.
- **Bench order and auto-substitution simulation.** `myteam.py` owns bench order;
  simulating auto-subs needs a per-player played/not-played distribution the
  planner does not have. Bench Boost uses the plain bench xP sum, and the page
  says so.
- **Sharing a plan by URL.** Tempting and cheap (base64 of the plan object in the
  hash) but it invites a plan that outlives the projection it was built against.
  Defer until the rebase logic in §4.4 has survived a few real gameweek rollovers.
- **Head-to-head leagues, the FPL Cup, monthly phase scoring.**

---

## 5. Data the repo does not yet produce

### 5.1 Available today, needs plumbing only

| Needed | Where it is | Effort |
|---|---|---|
| Per-gameweek xP for every player | `xp_next` (`";"`-joined, `n_gw` values) in the projections CSV; already parsed into `d.g` by `web.prepare()` | none |
| DGW/BGW correctness in those numbers | `M.project()` sums fixtures; `multi_gw_xp()` emits `0.0` for a blank | none |
| Squad legality, best XI, position limits | `web.py` `LIMITS`, `SHAPES`, `bestXI()`, `squadIssues()` | lift as-is |
| 1-transfer search + risk profiles | `web.py` `suggestions()`, `PROFILES` | lift, parameterise by gameweek |
| Per-team fixture grid with split difficulty | `ticker.build_grid()` → `{team_id: [[(opp, home, atk, dfn), …] per gw]}` | **call it from `planner.py`** |
| Blank/double counts | `ticker.summarise()` | call it |
| Chip windows | `bootstrap["chips"]` — `name`, `start_event`, `stop_event` | new: emit to payload |
| Gameweek deadlines | `bootstrap["events"][].deadline_time` | new: emit to payload |
| Sell-on fee, budget, club limit, transfer cap | `bootstrap["game_settings"]` | new: emit to payload |

**Emit the game settings rather than hardcoding them.** `squad_total_spend`,
`squad_team_limit`, `transfers_sell_on_fee`, `transfers_cap`,
`max_extra_free_transfers` are all in the snapshot. FPL has changed the FT cap
once already this cycle; reading it from the payload means the planner is correct
the morning the rule changes, and `web.py` currently hardcodes `BUDGET=100.0`
and `MAX_PER_CLUB=3` where it should not.

**The planner payload** (one JSON blob, same pattern as `GRID` in `ticker.py`):

```json
{
  "base_gw": 9,
  "gws":      [9, 10, 11, 12, 13, 14],
  "deadlines":["2026-10-24T10:00:00Z", ...],
  "chips":    [{"name":"wildcard","number":1,"start":2,"stop":19}, ...],
  "rules":    {"budget":1000,"club_max":3,"sell_fee":0.5,
               "transfers_cap":20,"max_extra_ft":4},
  "fixtures": {"ARS": [[["bou",true,0.87,1.12]], [], [["MUN",false,1.31,0.94]]]},
  "players":  [{"i":351,"n":"Semenyo","t":"BOU","p":"MID","c":74,
                "g":[5.1,4.4,6.0,3.2,5.5,4.9],"tot":29.1,"ps":91,"e":1}]
}
```

`fixtures` is keyed by team **short code** so it joins to the existing player
payload's `t` field with no extra lookup. Sizes: 20 teams × 6 gameweeks is
trivial; ~470 players × 6 xP values is already what `projections.html` carries.

### 5.2 Genuinely missing: your actual squad, bank, FT count and purchase prices

**The FPL API sends no CORS headers on any endpoint.** Verified against the live
API on 20 Aug 2026: `GET /api/bootstrap-static/` returns no
`Access-Control-Allow-Origin` and sets `cross-origin-resource-policy:
same-origin`. `myteam.py` already documents the same finding, including that four
public CORS proxies were tested and all four are dead or paywalled.

So the planner starts from a **hypothesis**, not from your team, and the four
things it most wants — squad, bank, free-transfer count, purchase prices — have
to come from somewhere else.

`myteam.py` already ships the answer: **open your own picks URL in your own
signed-in browser, copy, paste.** Reuse `applyPicks()` wholesale, including its
error messages (it correctly explains the pre-season 404 rather than blaming the
user).

**But `/entry/{id}/event/{gw}/picks/` is the wrong endpoint for a planner.** It
gives you the 15 and the captain and nothing else. The endpoint that carries what
the planner needs is the authenticated, same-origin **`/api/my-team/{id}/`**,
which returns per-pick `purchase_price` and `selling_price`, plus `transfers`
(bank, value, limit, made) and `chips`. It is unofficial and undocumented —
community-reverse-engineered — so **verify the exact field names against a real
response before writing the parser**; it cannot be checked before the season
starts because it 404s / 401s until then.

Design accordingly:

- **v1 default:** `purchase = now_cost`, so `sell = now`, stated on the page in
  the same words `web.py` already uses.
- **Per-player override:** tap a price in the In/Out block → numeric input for
  what you paid. Stored in `plan.purchase`.
- **Paste path (ship 4):** paste `my-team` JSON → fill `purchase`, `bank`, `ft`
  and the squad in one go. Frame it in the page as *"nothing is transmitted; the
  paste never leaves this tab"*, which is true and is the opposite of every
  competitor's model.

### 5.3 Genuinely missing: a horizon long enough to plan chips in

**This is the one real data gap, and it is a mismatch of timescales.** Transfers
are a 4–8 gameweek decision and `xp_next`'s six gameweeks covers it — the
community's own view is that "six to eight gameweeks is the practical planning
horizon, and beyond eight gameweeks, fixture scheduling makes precise FDR
planning unreliable." But **chips are a half-season decision**: the first set
expires at GW19 and the planner is meant to answer "when do I wildcard."

You cannot answer that with six columns.

**Recommendation: two horizons, two levels of detail.**

- **Player level, 6 gameweeks** — `xp_next` as it stands. The transfer planner.
- **Team level, all remaining gameweeks** — a new, cheap artifact: for each team
  and each gameweek to GW38, the mean attacking and defensive difficulty from
  `ticker.build_grid`, plus fixture count. This is **already computed** by
  `ticker.py`; it is currently truncated to `--gameweeks 8` and thrown away. Emit
  the full 38 into the planner payload.

Then the chip calendar is a **20 × 38 team-difficulty strip** underneath the
6-column player grid, with your squad's club distribution overlaid — enough to
see "my six Arsenal-and-Liverpool players all have a bad GW14–17 run, wildcard
around GW13" without ever claiming a player-level projection that far out. The
page must be explicit that the long strip is *fixtures only, no player
projection*, because conflating the two is exactly the over-precision §2.3
criticises.

Cost: one extra `build_grid` call with `n_gw = 38 - start_gw + 1`, and about 3 KB
of JSON.

### 5.4 Genuinely missing: projected blanks and doubles

FPL's fixture list only shows a blank once a fixture is actually postponed. Ben
Crellin's competitive advantage is forecasting them from cup draws, months ahead.
That is human judgement plus knowledge of the FA Cup and EFL Cup calendars, not a
data feed, and we cannot replicate it in v1.

**Cheapest credible version:** a hand-maintained `data/projected_fixtures.json`,
`[{gw, team, action: "blank"|"double", opponent, home, confidence, note,
source_url}]`, read by `planner.py` if present, rendered in a visually distinct
style (hatched, not solid) and **always labelled as a projection, never merged
into the real grid**. Ship the file format in v1 and leave the file empty. Fill it
from December. If it never gets filled, nothing breaks.

### 5.5 A gap worth naming: no per-gameweek ceiling

`project.build()` computes `p6` / `p10` / `p15` haul probabilities **for the
current gameweek's fixtures only** — `M.points_pmf()` is called once, with
`fixture_ratings`, not per horizon gameweek. So the planner has expected points
for six weeks but **upside for one**.

That matters for exactly one feature: **Triple Captain**, which is an upside
decision, not a mean decision. The README already makes this point — "a keeper can
out-project a midfielder on expectation and still be a hopeless captain, because
his ceiling is structurally capped."

Two options, and the second is right for v1:

1. Extend `multi_gw_xp` to also return a per-gameweek `p10`. Correct, but it is
   `n_gw` extra PMF convolutions per player and it changes the projections CSV
   schema — which is a **record artifact** that `verify.py` reproduces byte for
   byte. Not a change to make casually.
2. **v1: rank Triple Captain weeks by mean xP and say so.** Print the caveat next
   to the TC chip: *"ranked on expected points; ceiling data is only available for
   the current gameweek."* Then extend the column when the points distribution
   work lands for M6, which needs it anyway.

---

## 6. Build order

Each ship is independently useful and independently publishable. Do not start the
next until the previous one is on the live site.

### Ship 1 — the calendar, read-only (target: one sitting)

`planner.py` produces `out/planner.html`: your saved squad (from `fpl.squad`) as
15 rows × 6 gameweek columns, each cell showing opponent, home/away,
position-appropriate difficulty colour, and `xp_next[g]`. Column headers carry
gameweek number and deadline. Blank and double cells render correctly. Week/Grid
toggle. Empty-state that explains how to pick a squad and links to the
projections page.

No transfers, no chips, no ledger.

**Why this first:** it is useful on day one, it is a pure read of data that
already exists, and it flushes out every layout and mobile problem before any
state machine exists. It is also already better than most free tools, because
their xP is unaudited and ours links to `scorecard.html`.

### Ship 2 — transfers and the ledger (this is the product)

`plan` state, the `simulate()` fold, the tap-cell → bottom-sheet transfer flow,
the In/Out block, and the six ledger rows: FT before→after, transfers, hits,
bank, xP, cumulative net. Per-gameweek validation with the offending row named.
Undo. The FT-cap waste warning. `fpl.plan.v1` persistence with the full §4.4
guard, version gate, `base_gw` rebase, and the statically-rendered reset button.

**Everything the user asked for — "wildcard GW9, two transfers GW10, see the
cumulative points and budget consequence" — is satisfied at the end of Ship 2**,
minus the chips themselves.

### Ship 3 — chips

Chip slot per column header, legality computed from the payload's `chips` array
with reasons shown for every illegal option, Bench Boost and Triple Captain
effects in the fold, the Free Hit branch (isolated week, state reverts), the
consecutive-Free-Hit rule, the GW19 expiry warning. The 20 × 38 team-difficulty
strip from §5.3 underneath, for chip timing.

### Ship 4 — real prices and real squads

`sellPrice()` with per-player purchase overrides. The `my-team` paste importer
(after verifying the field names against a live response). Bank and FT count
seeded from the paste. The "nothing leaves this tab" line in the header.

### Ship 5 — suggestions, then paths

First: `web.suggestions()` reused per gameweek column, driven off the plan's bank
and FT at that gameweek, with the existing Safer/Balanced/Bolder profiles.

Then, only if Ship 5a is being used: the bounded beam search from §3.3(c),
behind an explicit button, chunked across `setTimeout`, returning **three** paths
and their intersection.

### Not in the plan

M5 (MILP optimiser) and M6 (mini-league-aware) stay where the README puts them.
The planner is the surface those will eventually plug into, which is another
reason to keep `simulate()` a pure function of `(plan, data)`: when a solver
exists, it produces a `plan` object and the same renderer draws it.

---

## Appendix — sources

**Official / primary**

- FPL rules, verbatim, extracted from the live SPA bundle
  `https://fantasy.premierleague.com/assets/Rules-DzLtIY6U.js` (chunk hash
  changes on redeploy; find the current one in `assets/index-*.js`). Rendered
  page: <https://fantasy.premierleague.com/help/rules>
- FPL API `game_settings`, `chips`, `events`, `phases` — local snapshot
  `data/snapshots/20260820T005955Z_gw1/bootstrap.json`
- FPL API CORS behaviour — verified by request, 20 Aug 2026
- <https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627>
- <https://www.premierleague.com/en/news/4059225> (five banked free transfers,
  retained through chips)

**Rules commentary**

- <https://www.fantasyfootballscout.co.uk/2026/07/20/fpl-2026-27-5-rule-changes-new-features-announced>
- <https://www.fantasyfootballscout.co.uk/2024/10/03/do-i-keep-my-free-transfers-when-i-use-an-fpl-wildcard>
- <https://www.fantasyfootballscout.co.uk/2026/04/24/do-i-keep-my-saved-transfers-when-using-the-free-hit-chip-3>

**Competitors**

- <https://www.fantasyfootballscout.co.uk/transfer-planner>
- <https://www.fantasyfootballscout.co.uk/2025/06/18/how-to-use-the-season-ticker-for-fpl-fixture-planning>
- <https://allaboutfpl.com/2026/08/complete-detailed-review-of-fantasy-football-hub/>
- <https://docs.fplreview.com/the-model/solvers/settings/> (solver defaults table)
- <https://docs.fplreview.com/the-model/solvers/sensitivity-analysis/>
- <https://docs.fplreview.com/the-model/projections/massive-data-model/>
- <https://github.com/sertalpbilal/FPL-Optimization-Tools> and
  <https://raw.githubusercontent.com/sertalpbilal/FPL-Optimization-Tools/main/data/README.md>
- <https://www.premierfantasytools.com/fpl-planner-intro/>
- <https://fpl.team/plan/>, <https://plan.livefpl.net/>,
  <https://fplstrat.app/>, <https://fpltactics.com/team-planner>
- <https://apps.apple.com/gb/app/plan-fpl/id1612990822>

**Not consulted, and it matters**

- **r/FantasyPL.** Reddit is blocked to every fetch path available here. The
  complaints in §2 come from app-store reviews, Trustpilot and published
  reviews. Do the Reddit sweep by hand before finalising §4.
