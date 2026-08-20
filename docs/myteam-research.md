# My Team page — research and decisions

Date: 2026-08-20. Evidence gathered live against the FPL API on this date.

---

## 1. Import verdict

**Direct browser import is impossible. Do not build it.** The page must import by
paste, not by fetch.

### Evidence

CORS, entry endpoint, with the real site Origin:

```
$ curl -sI -H "Origin: https://blueladd11-commits-tocode.github.io" \
    "https://fantasy.premierleague.com/api/entry/1/"
HTTP/2 200
cross-origin-resource-policy: same-origin
cross-origin-opener-policy: same-origin
allow: GET, HEAD, OPTIONS
content-type: application/json
```

No `access-control-allow-origin`. Not a wrong value — the header is absent
entirely. Same result on `/api/entry/1/event/1/picks/` and on
`/api/bootstrap-static/`. The `OPTIONS` preflight returns 200 with
`allow: GET, HEAD, OPTIONS` and again **no** `access-control-allow-*` headers,
so the preflight fails and the browser never issues the GET. On top of that,
`cross-origin-resource-policy: same-origin` blocks even opaque no-cors reads.

The repo's prior finding holds for the entry endpoints specifically. Confirmed.

### What each endpoint returns

`GET /api/entry/{id}/` — public, no auth. Manager first/last name, region,
`started_event`, `years_active`, `favourite_team`, `summary_overall_points`,
`summary_overall_rank`, `current_event`, and the full `leagues` object
(classic + h2h + cup). ~15 KB. **It does not contain the squad.** Useful only
for confirming "is this the right team?" after an import.

`GET /api/entry/{id}/event/{gw}/picks/` — the squad. Returns
`picks[]` with `element` (player id), `position` (1–11 starters, 12 = bench GK,
13–15 outfield subs in auto-sub priority order), `is_captain`, `is_vice_captain`,
`multiplier` (0 bench, 1 starter, 2 captain, 3 triple captain), plus
`active_chip`, `automatic_subs[]` and `entry_history` (bank, team value,
transfers, hits).

**Availability rule — verified:** picks are `404 {"detail":"Not found."}` until
that gameweek's deadline passes, then public forever. Tested today:

```
$ curl -s -o /dev/null -w "%{http_code}" ".../entry/1/event/1/picks/"   → 404
$ curl -s -o /dev/null -w "%{http_code}" ".../entry/1/event/38/picks/"  → 404
```

### Pre-season is the state you are shipping into

Right now `bootstrap-static` says GW1 `is_next: true`, deadline
**2026-08-21T17:30Z — tomorrow**. `entry/1/` returns `current_event: null`,
`summary_overall_points: null`. **Today, no team on earth has importable picks.**
Every import attempt returns 404 until tomorrow evening.

This is not an edge case to handle later — it is the launch-day state. The page
must open in a usable, manual-build mode and treat import as an enhancement.

### Options, honestly assessed

| Option | Verdict |
|---|---|
| Direct browser fetch | **Impossible.** No CORS, CORP blocks opaque reads. |
| Public CORS proxy | **Rejected.** See below — all four tested are dead. |
| Server-side proxy | Works, but abandons zero-dependency + GitHub Pages. Adds a host, a bill, an uptime problem, and an FPL rate-limit liability keyed to your IP. |
| Build-time fetch | Already how the site works (`tick.yml`, hourly cron). But it only fetches ids you know at build time — it cannot serve an arbitrary visitor's team. |
| **User pastes the JSON** | **Recommended.** |

Public CORS proxies, tested against the real endpoint today:

```
corsproxy.io          403  "Server-side requests are not allowed on your plan"
api.allorigins.win    520  (14.1s)
api.codetabs.com      timeout after 20s
thingproxy.freeboard  connection failure
```

Zero of four work. Beyond reliability: a proxy means every user's team id and
squad passes through an unaccountable third party, which is a privacy claim you
cannot make and a dependency that will break silently on a Sunday.

### Recommendation: the paste flow

The FPL API is public JSON served with `content-type: application/json` — a
browser renders it as text. The user's own browser hitting FPL is *same-origin*,
so no CORS applies. So:

1. User types their team id into a field.
2. Page builds the link and shows it as a real anchor:
   `https://fantasy.premierleague.com/api/entry/{ID}/event/{GW}/picks/`
   (`{GW}` is baked in at build time — you already know the current event).
3. `target="_blank"`, they copy all, paste into a textarea.
4. You `JSON.parse`, map `picks[].element` onto your `byId`, and you have the
   squad, the XI, the bench order and the armband — everything, exactly.

Two taps and a paste. No backend, no proxy, no dependency, nothing leaves the
user's machine. It also degrades honestly: if they paste garbage you say so.

**Fallback that costs nothing:** also accept a paste of the *entry* URL or bare
id and, if picks 404 (pre-season / pre-deadline), say plainly *"FPL has not
published a squad for this team yet — picks go public after the GW{N} deadline
on {date}. Build it by hand below and it will save."*

### How a user finds their team id — one sentence for the UI

> Sign in to fantasy.premierleague.com, open **Pick Team → Gameweek History**,
> and your id is the number in the address bar between `/entry/` and `/history`.

One warning worth a tooltip: **FPL issues a new entry id every season**, so a
returning manager's 2025/26 id will not work. Validate and say so rather than
rendering an empty squad.

---

## 2. Pitch layout

### What the competitors do

FPL itself, Fantasy Football Hub and the team-viewer tools all converge on the
same thing, because the constraint forces it: **one row per position line, rows
stacked GK→DEF→MID→FWD, cards centred and evenly distributed within each row,
bench as a fifth row below a hard visual break.** Nobody uses true pitch
coordinates; nobody staggers wingers forward. Reflow on formation change is
purely "how many cards are in this row" — the row count never changes, which is
why the transition is stable and why you should copy it.

Armbands: a small circular **C** / **V** badge pinned to the shirt graphic,
top-right corner, overlapping the shirt edge. Never a separate row, never text
in the name line — it must be readable at a glance across 11 cards.

Bench separation: FPL uses a distinct background band plus the labels
`1. 2. 3.` for auto-sub priority. That numbering is not decoration — bench
*order* is a real FPL decision. Show it.

### The 375px constraint — do the arithmetic first

375px viewport − 28px page padding = **347px usable**. Worst case is a 5-card
row (5 DEF or 5 MID): `(347 − 4×4px gap) / 5` = **~66px per card**. That is the
hard number. A card is 66px wide. Everything below follows from it.

Vertically, the tightest real device is a 667px iPhone SE. Nav + header + the
summary bar eat ~200px, leaving ~460px for five rows → **~90px per row**, so a
card must be **≤78px tall**. Which permits exactly: shirt, name, **one** stat
line. Not two.

```
375px wide  ·  everything above the fold

┌───────────────────────────────────────────┐
│  [nav]  Projections  Fixtures  My Team    │
├───────────────────────────────────────────┤
│  4-4-2      £99.6m      xP 58.4     ⚙ ⟳  │  <- summary bar, always visible
├───────────────────────────────────────────┤
│                                           │
│                 ┌────┐                    │  GK
│                 │ 👕 │                    │
│                 │Raya│                    │
│                 │ 4.1│                    │
│                 └────┘                    │
│                                           │
│  ┌────┐  ┌────┐  ┌────┐  ┌────┐           │  DEF ×4
│  │ 👕 │  │ 👕 │  │ 👕 │  │ 👕 │           │
│  │Gabr│  │Trip│  │Burn│  │Kerk│           │
│  │ 4.4│  │ 4.0│  │ 3.8│  │ 3.6│           │
│  └────┘  └────┘  └────┘  └────┘           │
│                                           │
│  ┌────┐  ┌────┐  ┌────┐  ┌────┐           │  MID ×4
│  │ 👕Ⓒ│  │ 👕 │  │ 👕Ⓥ│  │ 👕 │           │  <- armband, top-right of shirt
│  │Sala│  │Palm│  │Saka│  │Semen│          │
│  │12.4│  │ 6.1│  │ 5.9│  │ 4.4│           │  <- C shows DOUBLED xP
│  └────┘  └────┘  └────┘  └────┘           │
│                                           │
│      ┌────┐          ┌────┐               │  FWD ×2
│      │ 👕 │          │ 👕 │               │
│      │Hala│          │Isak│               │
│      │ 7.2│          │ 5.8│               │
│      └────┘          └────┘               │
│                                           │
├═══════════════════════════════════════════┤  <- hard rule + tinted band
│ BENCH        1        2        3          │
│  ┌────┐  ┌────┐  ┌────┐  ┌────┐           │
│  │ 👕 │  │ 👕 │  │ 👕 │  │ 👕 │           │
│  │Sels│  │Rice│  │Muñz│  │Wiss│           │
│  │ 3.2│  │ 4.9│  │ 2.8│  │ 3.1│           │
│  └────┘  └────┘  └────┘  └────┘           │
└───────────────────────────────────────────┘
                                    ─── fold ───
```

Implementation: each row is `display:flex; justify-content:center; gap:4px`,
card is `flex:0 0 66px` — actually `flex:0 1 66px; max-width:66px`. Cards then
centre themselves and a 3-card row is automatically narrower than a 5-card row
with no formation-specific CSS. **The formation change is a row's child count
changing, nothing more.** Do not animate positions; a 120ms opacity fade on the
moved card is enough and won't fight the reflow.

At ≥1080px reuse the existing `.layout` breakpoint: pitch left, the current
squad sidebar (transfers, suggestions, issues) right. Below that, the pitch is
full width and the sidebar content stacks underneath.

---

## 3. What goes on a player card — ranked, with cuts

At 66×78px you get a shirt, a name, and one number. Rank accordingly.

**Ship these five:**

1. **Club shirt graphic** — the single highest-value element. It carries club
   identity, so you never need to print the team abbreviation, which buys back
   a whole text line. This is why every competitor uses shirts.
2. **Web name** — 11px, single line, ellipsis. Non-negotiable.
3. **Expected points** — the one number. It is the entire reason this site
   exists; showing anything else in that slot is off-message. Show the
   **captain-doubled** value for the captain.
4. **Captain / vice armband** — Ⓒ / Ⓥ badge overlapping the shirt's top-right.
   Costs zero layout.
5. **Fixture difficulty as the card's border/underline colour** — a 3px colour
   bar keyed to FDR. Zero space, instantly scannable across 15 cards. This is
   the smartest thing the competitors do and the cheapest to copy.

**Cut from the card (move to the tap-through detail sheet):**

- **Price.** It matters when transferring, not when picking a lineup. It lives
  in the summary bar as squad total and in the transfer panel. Cut.
- **Start probability as a number.** Cut the digits — but keep the *signal*:
  dim the card to 55% opacity when `ps < 65`, and show a small warning dot when
  `ps < 40`. You get the information for free and it reads faster than "62%".
- **Fixture opponent text ("BOU (H)").** At 66px this is 3 unreadable
  characters. The FDR colour bar already carries the useful half. Put the
  opponent string in the detail sheet and in the desktop-width card only.
- **Anything else** (xMins, P(10+), form, ownership, xP/£m). All of it is one
  tap away in the detail sheet. None of it survives 66px.

Tapping a card opens a bottom sheet with the full row from the projections
table plus the actions. That is where density is allowed to live.

---

## 4. Interactions

**a. Captain / vice.** Tap card → sheet → "Make captain" / "Make vice". Setting
C on the current V swaps them rather than leaving the team without a vice.
Captain must be a starter; if the user captains a bench player, either refuse
or auto-promote — refuse, and say why. Vice is mandatory; never allow a saved
state with C but no V.

**b. Bench swap.** Tap a player → the app enters *swap mode* and **dims every
player it would be illegal to swap them with**, which is how FPL does it and is
far better than allowing the tap and then showing an error. Rules:

- GK ↔ GK only. Always exactly 1 GK in the XI.
- Outfield swap is legal iff the resulting XI satisfies
  **DEF ≥ 3, MID ≥ 2, FWD ≥ 1**, GK = 1, total 11.
  (Your `SHAPES` constant already encodes exactly this set — see below.)
- Bench-to-bench is always legal and reorders auto-sub priority.

**c. Auto-pick best XI.** A *button*, not a default. It should also set the
captain (highest xP starter) and the vice (second highest), and order the bench
by xP with the reserve GK pinned to slot 12. Confirm before overwriting a
hand-made team.

**d. Projected score.** `sum(XI xP) + captain xP`. **Your current code does not
double the captain** — `xi.tot` in `renderSquad` is a plain sum, so the headline
number is understated by a full captain's xP (~7–12 points, i.e. ~15%). Fix
this when you port it; it is the most visible number on the page.

### What `web.py`'s `bestXI` already does — and doesn't

`web.py:294`. It sorts each position by xP, then brute-forces the `SHAPES`
list, taking the top-N of each position per shape and keeping the highest total.

**Formation legality: it is correct and complete.** `SHAPES` contains all eight
legal FPL formations (3-4-3, 3-5-2, 4-3-3, 4-4-2, 4-5-1, 5-2-3, 5-3-2, 5-4-1).
Nothing legal is missing. One dead entry: `[3,3,4]` requires 4 forwards, which
is impossible under `LIMITS.FWD = 3` — harmless (the `f.length < nf` guard
filters it) but it should go, since it implies a shape the game doesn't allow.

**What it does not do, and what the new page needs:**

- No captain doubling (see above).
- No bench *ordering* — bench is just "whatever is left", unordered. The new
  page needs slots 12–15 with the reserve GK pinned to 12.
- **It recomputes the XI on every render.** That is right for a sidebar
  scratchpad and wrong for a My Team page. On the new page the *user's*
  XI/bench/captain is the persisted state (extend the `fpl.squad` localStorage
  entry from a flat id array to `{picks, captain, vice}` — and version it, given
  the shape-validation bug already documented at `web.py:467`). `bestXI` becomes
  the implementation of the Auto-pick button only.
- It ignores start probability entirely (uses raw `xp`). Given profile-based
  risk already exists in `PROFILES`, Auto-pick should probably respect the
  selected profile's `minStart` — otherwise Auto-pick and the transfer
  suggestions give contradictory advice on the same page.

---

## 5. Top 3 mistakes to avoid

**1. Making import the front door.** Several tools open on a "enter your team
id" gate. You literally cannot honour it today — picks 404 until tomorrow's
deadline, and even after, some users will fumble the paste. The page must open
**already usable** in manual mode, with import as a labelled shortcut. Import
failure must never be a dead end.

**2. Porting desktop information density onto a 66px card.** Hub and the
planners put four or five numbers on a card, and on a phone the result is either
unreadable or a horizontal scroll. Take the discipline: one number on the card,
everything else behind a tap. You already know which number — it is the one the
whole site is about.

**3. Overriding the user's own team.** A "best XI" that silently recomputes
every render tells the user their judgement doesn't count, and it makes the
page's central object — *their* team — not actually theirs. Optimisation is an
action they invoke; the saved state is whatever they last chose. Related and
just as damaging: showing a projected score that quietly disagrees with FPL's
arithmetic (the un-doubled captain) destroys trust in every other number on the
page.
