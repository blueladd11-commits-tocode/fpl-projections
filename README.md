# fpl-projections

An FPL projection engine built around one commercial bet: **we publish our
accuracy, and nobody else does.**

Zero dependencies, stdlib Python 3.9+. Run everything with `python3 <script>`.

---

## The one thing that is time-critical

**GW1 2026/27 deadline: 2026-08-21 17:30 UTC.**

Snapshots must start now. Projections are only evidence if they were recorded
*before* kickoff, and data you failed to capture is unrecoverable. The public
mirror's copy of FPL's own expected points is captured *after* each gameweek and
is unusable as a benchmark (see *The benchmark* below) — so no clean record of
anyone's pre-deadline predictions exists, for any season, and none can be
reconstructed. That is precisely why owning one going forward is worth
something. Get `snapshot.py` on a cron today; everything else can follow.

**Runs on GitHub Actions** (`.github/workflows/tick.yml`), hourly. That is the
single writer of the record — do NOT also run `tick.py` from a local cron, or
two machines produce two diverging records and only one of them gets committed.

Running it in CI rather than on a laptop is the point: GitHub's schedulers are
always awake, and a projection missed because a machine was asleep is a
permanent hole. GitHub does delay scheduled runs under load, sometimes by 10+
minutes, which is exactly why `tick.py` works in horizon *bands* rather than at
exact times — a late run still lands in the right band, and a double run is a
no-op.

Each run that changes the record commits and pushes it. **The push is the
external timestamp**: a commit landing on GitHub before a deadline is
third-party evidence that the projection predates it, which is materially
stronger than a timestamp we write into our own JSON.

**Locally,** `tick.py` decides what to do from state, not from the clock —
FPL deadlines move week to week. Each hour it snapshots, projects once per
**horizon band** (T−72h, T−24h, T−6h, T−2h), scores any settled gameweek that
has a projection but no scorecard, republishes if anything moved, and verifies
the record still reproduces. Every step is guarded by "has this already been
done", so a double run is harmless and a missed hour is recoverable.

### Why horizons, not one shot

The first design took a single projection inside a 6h window. That was wrong,
and it conflated two different artifacts:

- **The product** is a page people consult all week. Scout, Hub and Pundit all
  publish days ahead and update as team news lands, because that is what the
  thing is *for*. Pundit states it outright: table ready 3+ days before the
  deadline, changing through the week as news and odds move.
- **The record** is the accuracy evidence, and needs a frozen pre-deadline
  capture.

Publishing at several horizons serves both, and is strictly more informative
than one number — it shows **how much the projection improves as news arrives**,
which nobody in this market publishes. The scored entry is the last projection
before the deadline; the earlier horizons stay on the record beside it.

It also removes the single point of failure that made the earlier design
fragile. A laptop asleep at T−2h still has T−6h, T−24h and T−72h in the record.
`tick.py` only reports a permanent hole if a deadline passes with **no**
projection at **any** horizon.

---

## The two pages

`site.py` builds **the product** — what the model thinks right now, for every
player. `publish.py` builds **the scorecard** — what we committed to before each
deadline and how it did. They are different artifacts with different jobs, and
conflating them was a mistake worth not repeating: for a long stretch this repo
had a rigorous accuracy record and nothing anyone could actually use.

```bash
python3 site.py --open        # the projections table
python3 preview.py --open     # the scorecard, with simulated results
```

`site.py` works whether or not the record has entries. Before the first deadline
it computes projections from the latest snapshot and says so on the page —
"computed just now, not yet the committed pre-deadline projection" — because
showing a live number as if it were a committed one would undermine the whole
point of having a record.

## Repository layout

- `out/` **is the record** and is committed: projections, their provenance
  metadata, weekly scorecards, backtest evidence, and gzipped copies of the
  exact API snapshots each projection was built from.
- `data/` is a working cache and is gitignored. `data/history/` is
  re-downloadable (24 MB); `data/snapshots/` accumulates one capture per hour,
  which is ~13 GB a year. Only the snapshots that actually produced a
  projection are preserved into `out/snapshots/`, gzipped — about 10x smaller,
  putting a full season's evidence at roughly 20 MB.

## Files

| file | does | status |
|---|---|---|
| `snapshot.py` | Immutable, content-hashed capture of the FPL API. Write-once, read-only, SHA-256 manifest. | working |
| `history.py` | Pulls the `vaastav/Fantasy-Premier-League` mirror — 10 complete seasons, the backtest foundation. | working |
| `model.py` | **All** scoring math. Pure functions, no I/O and no clock, which is what makes the as-of cutoff enforceable. Shared by the live and backtest paths so they cannot drift. | working, calibrated |
| `walk.py` | The one implementation of "what did we know before gameweek g". Shared by `backtest.py` and `minutes.py`. Outcomes namespaced `.actual_*` so using one as a feature is a visible mistake. | working |
| `minutes.py` | Fitted P(start) model + its own eval (Brier / logloss / AUC / calibration). **The one component carrying a real edge.** | working |
| `project.py` | Live path: latest snapshot → projections CSV + provenance metadata. | working |
| `backtest.py` | Walk-forward harness with strict as-of cutoff, plus the three naive baselines. | working |
| `priors.py` | Fits the per-90 positional priors from history. `--write` rewrites the block in `model.py`. | working |
| `site.py` | **The product page.** Every player's projection, sortable and filterable, self-contained HTML. Falls back to computing live when the record is empty. | working |
| `preview.py` | Renders the scorecard with simulated results, so the design can be reviewed before real ones exist. Never touches the record. | working |
| `publish.py` | Generates the public scorecard page from the projection metadata, weekly scorecards and backtest evidence. Refuses to display in-sample results. | working |
| `tick.py` | **The only thing that needs to be scheduled.** Idempotent hourly job: snapshot, project inside the deadline window, score settled gameweeks, publish, verify. | working, installed |
| `verify.py` | Re-derives every published projection from its recorded snapshot and proves it matches. PASS / REPRODUCIBLE-WITH-DRIFT / FAIL. | working |
| `score.py` | Weekly scorecard. MAE / RMSE / Spearman / top-N, against naive baselines and the pre-deadline `ep_next` we recorded ourselves. Unit-tested metrics. | working; end-to-end runs once GW1 settles |

```bash
python3 snapshot.py                              # capture (first, and often)
python3 history.py 2023-24 2024-25 2025-26       # backtest data
python3 project.py --top 30                      # produce GW projections
python3 priors.py --write                         # refit per-90 priors
python3 minutes.py                               # fit P(start), production recipe
python3 backtest.py --season 2025-26 --prior 2024-25 --minutes-model
python3 score.py --selftest                      # verify metric implementations
python3 score.py --projections 'out/projections_gw1_*.csv'   # after GW1 settles
python3 publish.py                               # regenerate out/scorecard.html
```

**Weekly cadence is automated by `tick.py`.** The individual steps, if you need
to run one by hand:

```bash
python3 snapshot.py && python3 project.py        # before a deadline
python3 score.py --projections 'out/projections_gw<N>_*.csv' && python3 publish.py
python3 verify.py                                # confirm the record still holds
```

`project.py` **exits non-zero and writes nothing** if preflight fails — a
projection is permanent once published, so the failure to design against is not
"we published nothing", it is "we published something wrong". It refuses when
the deadline has already passed, when the snapshot is over 24h old, when the
snapshot's gameweek disagrees with the one being projected, when the minutes
model is missing or off the production recipe, and when the output distribution
is implausible. `--force` exists and should never be used on anything that will
be published.

---

## Known state — backtested

Walk-forward, strict as-of cutoff, calibrated, on a **fixed evaluation
population** (≥3 prior matches and ≥45 minutes per match — see `eligible()` in
`backtest.py` for why this must not depend on the model under test):

**Read the paired t, not the table.** Averaging per-gameweek metrics makes a
0.005 edge and a 0.11 edge look alike. `backtest.py` now always prints a paired
test over the 38 gameweeks and flags anything under t=2, because the single most
important fact about this model is invisible in the means:

| configuration | Spearman | vs `naive_recent6` | t | GWs won |
|---|---|---|---|---|
| **v0 + minutes model, 2025-26** | 0.462 | **+0.111** | **7.57** | 35/38 |
| **v0 + minutes model, 2024-25** | 0.441 | **+0.053** | **5.17** | 31/38 |
| v0 alone, 2025-26 | 0.364 | +0.013 | 1.21 | 23/38 |
| v0 alone, 2024-25 | 0.392 | +0.004 | 0.44 | 21/38 |
| v0 alone, 2023-24 | 0.403 | +0.009 | 0.88 | **19/38** |

**Without the fitted minutes model there is no statistically detectable edge over
a three-line baseline** — averaging a player's last six scores. All three
v0-alone seasons sit under t=2 and win barely half the gameweeks. The +0.09 to +0.11 margin over
`naive_ppg` is real but it is beating the wrong baseline; `naive_ppg` is a
strawman and quoting it alone would be dishonest.

With the minutes model the edge is real and replicates on two seasons the model
never saw (trained 2023-24+2024-25 → tested 2025-26; trained 2022-23+2023-24 →
tested 2024-25). The honest range is **+0.05 to +0.11 Spearman**, not a single
headline number, and the smaller figure is the one to plan against.

**Commercially this is the finding that matters: the minutes model is not an
improvement to the product, it is the product.** Everything else in the pipeline
roughly ties a baseline anyone can write in an afternoon.

**Judge on RMSE and Spearman, not MAE.** Calibration to mean-unbiasedness raises
MAE (FPL points are right-skewed, so MAE rewards under-prediction) while
improving RMSE and bias. Unbiased means are non-negotiable downstream: the
optimiser sums xP over 11–15 players and a systematic shortfall compounds.

### The GW1 cliff — the fitted minutes model is gated

The fitted model is **worse than the heuristic before a player has any
current-season match**, which is exactly the gameweek the product launches in.
Out-of-sample on 2025-26 GW1:

| | Brier | AUC |
|---|---|---|
| v0 heuristic | **0.1705** | **0.8012** |
| general fitted model | 0.1873 | 0.7271 |
| GW1-dedicated model (tried, rejected) | 0.1908 | 0.7535 |

Two causes, one fixed and one not. The fixable half was encoding missing values
as a `-1` sentinel: a linear model reads that as a real quantity, and since
`last_mins90` carries the largest weight, every GW1 player picked up the same
large spurious contribution — starts were over-predicted by 21%. Explicit
missing-indicators fixed the level (1.208 → 1.086) but not the ranking.

The unfixable half is that every within-season feature is empty in GW1 and those
rows are ~2% of training data, so the fitted weights simply do not describe that
regime. A dedicated cold-start model trained only on GW1 rows also lost. Last
season's start rate — all the heuristic uses — is genuinely the better estimator
there.

So `minutes.p_start()` **gates**: heuristic until a player has a current-season
match, fitted model after. Both the live and backtest paths call that one
function. Gated performance out-of-sample: GW1 Brier 0.1705 / AUC 0.801,
GW2-3 0.0741 / 0.958, GW4+ 0.0791 / 0.947.

Watch for this shape elsewhere: an aggregate metric that looks strong can hide a
regime where the model is worse than what it replaced, and the regime that
matters commercially is rarely the one with the most rows.

### The record starts empty, on purpose

`out/archive/` holds projections generated during development, up to 149h before
their deadline. They are **not** part of the record and must never be scored.
The committed method is that a projection is built shortly before its deadline,
because team news lands in the final hours; scoring a six-day-early projection
would both understate the model and misrepresent the method. They are archived
rather than deleted — deleting things from a directory whose purpose is an
auditable record is a habit worth not starting.

So the scorecard currently reads "no projections published yet". That is the
correct state. The record begins when `tick.py` crosses the T−72h horizon for
GW1 — 18 August, 17:30 UTC.

### Making the record checkable

Two guards, because the public accuracy record is the product and it cannot be
retracted once published:

**Preflight.** `project.py` refuses to write rather than warn. The check that
matters most is the deadline: a projection written after kickoff is not a
prediction, and one bad row poisons the whole record's credibility.

**Verification.** `verify.py` re-derives every published projection from its own
recorded snapshot and compares byte for byte, checking three separate things —
that the snapshot files still hash to what was recorded (catches tampering or
corruption), that the fitted minutes model and priors still hash to what
produced the file, and that re-running yields the identical CSV. A projection
that reproduces but whose inputs have since been refitted reports
**REPRODUCIBLE-WITH-DRIFT**, not PASS, because the honest statement is "this was
correct when published, and today's code no longer reproduces it".

Both failure modes are tested, not assumed: corrupting a recorded hash produces
FAIL, and perturbing the priors produces DRIFT. `project.build()` was extracted
specifically so verification runs the shipping code rather than a copy of it.

### Review findings — four shipping bugs fixed

A review pass over the working tree, after the audit. All four were in the
*production* path, not the backtest — which is exactly where they hide, because
the backtest is the thing everyone stares at.

1. **The fitted minutes model never ran in production.** `project.py` loaded only
   the prior season and passed `recent_starts=[]` unconditionally;
   `minutes.p_start()` gates on precisely that, so it always took the cold-start
   branch. From GW2 onward the live product would have shipped the *v0 alone*
   configuration — the one with **no significant edge over a three-line
   baseline** — while the README advertised +0.11 Spearman. Fixed:
   `project.load_current_season()` folds settled gameweeks from
   `event/<gw>/live/` (now captured by `snapshot.py`) through the *same*
   `walk.fold_stats()` the backtest uses, so the two cannot compute aggregates
   differently. Verified against a synthetic payload: a live `stats` dict and a
   `merged_gw` CSV row produce byte-identical aggregates.
2. **The public scorecard would have shown the wrong baseline.** `publish.py`
   looked for a `naive_recent6` result that `score.py` never emitted, then
   silently fell through to *price-only* — while the page states in prose that
   the baseline is the last-six mean. Price-only backtests ~0.12 against
   last-six's ~0.35, so every published delta would have flattered us by roughly
   0.23. Fixed at the root: `project.py` now writes the `naive_recent6` column,
   `score.py` scores it, and `publish.py` has no fallback — a missing baseline
   leaves the row unscored rather than quietly substituting another.
3. **`score.py` still filtered on the model's own `p_start`** — the exact
   population-selection defect removed from `backtest.py`, left sitting in the
   file that produces the *published* numbers. Now uses an `eligible` column
   computed by `project.py` from history alone, mirroring `backtest.eligible()`.
4. **`priors.py --write` had a self-referential fallback** to the values it was
   about to overwrite. Documented; harmless today because the affected keys are
   genuinely zero.

### Audit findings — leakage clean, five defects fixed

An independent audit ran a **truncation test**: for each gameweek g, delete every
row with `GW > g` and re-run; if the as-of cutoff holds, gameweek g's output must
be byte-identical. **38/38 gameweeks × 2 seasons, zero mismatches.** That covers
team ratings, player aggregates, form deques, the prior seed, `team_rank`,
`days_rest` and the project-then-fold ordering. The cutoff genuinely holds. Price
was also cleared: partialling out prior-gameweek points leaves +0.043 residual
correlation, consistent with real pre-deadline signal, versus +0.27 for a
knowingly post-hoc measure.

Fixed since:

1. **`Context.agg` aliased live mutable state.** It handed out a reference into
   `Walker.agg`, which `_fold` mutates in place. Both consumers happened to read
   inside the generator loop, so results were correct — but `list(w.gameweeks())`
   would silently have given every gameweek the *end-of-season* aggregate
   (GW1 Salah: `mins=4168` materialised vs `mins=2024` streamed). Now copied.
2. **`defensive_contribution` was silently zero in the prior-season seed.** The
   column doesn't exist before 2025-26, so `fnum()` returned 0.0 while `per90()`
   still divided by those seeded minutes — deflating dc/90 by ~37% for returning
   full-timers while new players got an unbiased rate, in the one season where
   DefCon scores. Now imputed at the positional prior.
3. **`topn_hit` was not tie-safe.** FPL points are small integers so the top-N
   boundary is nearly always tied (GW10 2025-26: 9 players clear, 6 tied for one
   slot). Naive slicing broke ties by list order, giving a ±0.05 arbitrary swing
   on a metric reported to 2dp. Now gives fractional credit for tied boundaries
   and is permutation-invariant, with a shuffle test in `score.py --selftest`.
4. **`CALIBRATION` was fitted on the two seasons it was reported on**, and was a
   single constant serving two paths that sit at different levels — so the live
   product, which runs the minutes model, was being served a constant fitted for
   the heuristic. Now split and refit out-of-sample:
   `CALIBRATION_HEURISTIC = 1.125`, `CALIBRATION_MINUTES = 1.178`. Residual bias
   0.968 / 1.046. Neither affects Spearman (verified bit-identical across
   0.80–1.20), so this never touched the headline claim.
5. **Cross-season name join loses 8.8% of returning players** (47 of 534 in
   2025-26). The mirror renames players between seasons (`robert lynch sanchez`
   / `robert sanchez`), and `norm_name` strips combining marks via NFKD, which
   does nothing for `ø ł ı đ` — so `jørgen strand larsen` and `łukasz fabianski`
   fail. Zero false merges. **Still open**; worth ~+0.006 Spearman. Fix is to
   join on the stable FPL `code` in `players_raw.csv` rather than on the name.

Deliberate simplifications, in rough order of how much they cost:

1. **BPS was re-specified for 2026/27 and the bonus term is stale.** Core scoring
   is unchanged, but CBI now earns 1 BPS per 3 actions (was per 2), being tackled
   is no longer −1, and keeper saves were restructured. The change was explicitly
   designed to shift bonus away from CBI-heavy defenders toward keepers,
   full-backs and attackers. Our BPS priors and the `(bps*m90 - 20)/12` transform
   were fitted on the old formula, so **expect defender bonus over-projected and
   GK/attacker bonus under-projected until this is refit on 2026/27 data.**
2. **Bonus is a linear map off a BPS rate**, not a within-match BPS ranking
   model. Worth roughly 0.3 pts/GW on premium players.
3. **Fixture strength** pre-season falls back to FPL's coarse 1–5 tier, because
   the granular `strength_attack_*` / `strength_defence_*` fields are all zero
   until the season starts.
4. **No distribution**, only mean and a rough sd. The full points distribution is
   what makes captaincy, chip timing and mini-league-aware optimisation possible.
   Required before M6; build it before the optimiser, not after.
5. **DefCon threshold-crossing is modelled as Poisson**, but real defensive
   action counts are overdispersed. Unverified modelling choice, flagged.
6. **New signings and promoted players** fall back to a price-derived prior.
   Where the model will be most visibly wrong in August.

### Scoring rules — verified

Checked against `game_config.scoring` in a live 2026/27 snapshot (note: it is
`game_config`, **not** `game_settings`) plus the official rules. Goals, clean
sheets, assists, DefCon thresholds and points, saves, and the goals-conceded
penalty are all confirmed correct. Four implementation bugs were found and fixed:

- **Cards and penalty events were missing entirely** (yellow −1, red −3, own goal
  −2, penalty miss −2, penalty save +5). Omitting them over-projected defenders
  by ~0.21 pts/90 and midfielders ~0.19 — concentrated in exactly the
  high-DefCon defenders the model is built to surface.
- **`floor()` was modelled as division.** FPL pays on *completed* groups: one
  goal conceded costs nothing, two cost 1. `lam/2` over-penalised GK/DEF by
  ~0.235 pts per fixture; `saves/3` over-credited keepers by ~0.33. Now uses
  `e_floor_div()`, an exact Poisson sum.
- **Appearance points contradicted the model's own 60-minute gate** — every
  starter was credited 2 points while the clean-sheet term assumed only 88%
  reach 60 minutes.
- **DefCon prior for defenders was 9.5/90** against an observed median of 7.72.
  The threshold is 10 and the Poisson tail is steep there, so this materially
  over-credited low-minutes defenders.

**When you fix a scoring term, re-run `--calibrate`.** The global constant
absorbs whatever systematic error remains beneath it, so a correct rule fix
applied without recalibrating makes projections worse, not better. Fixing these
four moved the required constant from 1.064 to 1.159.

---

## The benchmark: do NOT use FPL's `xP` from the mirror

The obvious benchmark — FPL's own expected-points column in the historical
mirror — is **contaminated and unusable**. Two independent proofs.

**1. The mechanism, from the scraper source.** `global_scraper.py` assigns
`xPoint['xP'] = e['ep_this']` from `bootstrap-static` at run time and files it
under whichever event has `is_current == True`. `is_current` stays true for
gameweek N from its deadline until the *next* deadline — i.e. straight through
and after N's matches. The repo's own commit timestamps confirm the runs are
post-match ("Add gw1 data" 2025-08-20; GW1 was played 15–17 August). So the
value stored against gameweek N was captured **after** gameweek N.

**2. Horizon asymmetry.** Restrict to players with 60+ minutes (removing the
easy, legitimate "will he play" signal) and control for trailing-3 form,
trailing minutes, price and position:

| partial correlation | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| `xP`(t) vs points(**t**) | **+0.667** | **+0.652** | **+0.684** |
| `xP`(t) vs points(**t+1**) | +0.025 | +0.064 | +0.019 |
| trailing-3 form vs points(t) — honest reference | 0.134 | 0.126 | 0.082 |
| `bps` — a known same-gameweek leak, for calibration | +0.768 | +0.812 | +0.842 |

The same variable against the same target one week later has essentially zero
skill. Among starters, single-gameweek FPL points are near-noise and the honest
ceiling is ~0.10; `xP`'s +0.02–0.06 at t+1 is what genuine ex-ante skill looks
like. Nothing ex-ante reaches 0.65 at horizon zero, and 0.67 sits right next to
the known-contaminated `bps`. Because the identical variable and identical
controls appear in both rows, "the controls miss fixture difficulty" cannot
rescue it.

Independently reproduced with plain Spearman and no controls at all, restricted
to 60+ minute performances — a check that shares no code with the table above:

| | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| `xP`(t) vs points(t) | 0.501 | 0.480 | 0.478 |
| `xP`(t) vs points(t+1) | 0.165 | 0.171 | 0.045 |

Same shape, 3× to 10× asymmetry. No ex-ante model degrades like that from one
week to the next; a post-hoc one does exactly this.

The leak is *partial* because it flows through FPL's `form` field (a 30-day
rolling mean), so the gameweek's own result is only one match in the window.
That is why plenty of high-`xP`/low-return rows still exist.

**One usable consequence:** `xP` is poison as a *benchmark* but sound as a
*feature* if lagged — `xP` from gameweek t−1 was knowable before gameweek t's
deadline. It carries FPL's own model output for free. Worth trying in the
minutes model and the rate model. Coverage is good in 2023-24 (37/38) and
2024-25 (35/38), poor in 2025-26 (11/38).

### Evidence that does NOT support this — recorded so it isn't re-derived

The first pass justified this conclusion with four things, three of which are
worthless. Kept here because they are the natural things to reach for:

- ~~`spearman(xP, minutes) = 0.612`~~ — only reproducible under an undisclosed
  `xP > 0` filter, and unremarkable anyway: the trivially honest predictor "he
  played last week" scores **0.79**. A high correlation with realised minutes is
  what *persistence* looks like, not what leakage looks like.
- ~~mean `xP` 1.05 for 0-minute players vs 3.31 for 60+~~ — same hidden filter,
  and bucketing by the *previous* gameweek's minutes reproduces the gradient
  almost exactly (0.10 / 1.37 / 3.38). Fully explained by information available
  before the deadline.
- ~~Calafiori GW2: `xP` 14.0 → 13 points~~ — real, but weak: he scored 13 in
  GW1, so a form-chasing ex-ante model spikes there too. Counter-examples are
  systematic — of rows with `xP >= 8`, the share returning ≤2 points is 25.4%
  (2023-24), 21.9% (2024-25), 9.8% (2025-26). Post-hoc copying would essentially
  never do that.
- **"only 11 of 38 gameweeks"** — true for 2025-26, but it is a *coverage* bug,
  not contamination, and it does not generalise: 2023-24 has 37/38 and 2024-25
  has 35/38. `collector.py` writes `xP = 0.0` whenever the per-gameweek file is
  missing, and the repo skipped scraper runs.

The repo's README now carries a caveat saying much the same thing. Treat it as
weak corroboration only: it was added in a docs-only PR by an outside
contributor, and the "full analysis" it cites does not exist at the given URL.
It may well be the same claim circulating rather than a second witness.

**Consequence: a legitimate benchmark can only be built forward, from our own
pre-deadline snapshots.** `snapshot.py` captures `ep_next` before each deadline;
after a season we will have the first clean, timestamped record of FPL's own
model. Nobody else has this, because it cannot be reconstructed. This is the
strongest argument for starting snapshots before GW1 and the reason the
scorecard is a defensible asset rather than a marketing line.

Until then, the honest bar is the naive baselines in the table above.

---

## Milestones

**M1 — Backtest harness. DONE.** `model.py` holds the shared scoring code so the
backtest exercises exactly what ships; `backtest.py` walks a season with a strict
as-of cutoff. Two seasons validated, global calibration fitted, rules-by-season
handled (defensive contribution is 2025/26+). Findings above.

**M2 — Expected minutes model. DONE (v1).** `minutes.py` fits a logistic
regression on P(start) — pure stdlib SGD, ~7s to train. Trained on 2023-24 +
2024-25, evaluated on 2025-26 out-of-sample:

| | Brier | logloss | AUC |
|---|---|---|---|
| fitted model | **0.0817** | **0.2720** | **0.945** |
| v0 heuristic | 0.1014 | 0.4742 | 0.920 |
| constant base rate | 0.2025 | 0.5949 | 0.500 |

Well calibrated across the range (mildly under-confident at 0.3–0.6). Dominant
features: minutes in the last match, then competition for the shirt
(`team_rank`), then recent start rate. Price barely matters once you have
history — it is a cold-start feature only.

Still to do here: `days_rest` is weak because the mirror has no midweek
European/cup fixtures, so congestion is invisible; and the model cannot see
injury news at all (M4).

**A methodology trap worth remembering.** The first measurement of this model
showed projection Spearman *falling* (0.242 → 0.200). That was an artifact: the
eval population was filtered on the model's own P(start), so a sharper model
excluded the easy non-starters and was then judged on a harder residual. With a
model-independent population the same change is worth **+0.102 Spearman**. Never
let the thing under test choose its own test set.

**M3 — Public scorecard. DONE (v1), awaiting real results.** `publish.py` emits
`out/scorecard.html`: every published gameweek with its pre-deadline timestamp
and snapshot SHA-256, PENDING until settled, losses rendered identically to
wins, and the prior evidence table filtered to out-of-sample runs only. Still
to wire up: hosting, and an email capture. Original spec —
updated every gameweek, showing rolling RMSE and Spearman for us against the
naive baselines and against the `ep_next` **we recorded pre-deadline ourselves**
— never the mirror's contaminated copy. Every row carries its pre-deadline
timestamp and snapshot hash. Publish the bad weeks. The mechanism *is* the
marketing.

**M4 — News → minutes pipeline (from ~GW6).** The one genuinely LLM-shaped
problem here: press conferences, club statements and beat reporting into
structured `{player_id, p_start_delta, confidence, source, timestamp}`. Extract →
resolve entity → classify → propose delta → human review above a confidence
threshold. A pipeline with tool calls, not an agent swarm. This is what Scout
does with humans and where automation buys genuine speed.

**M5 — Optimiser (pre-season 2027).** MILP over budget, formation, transfer hits
and a multi-gameweek horizon. HiGHS or CBC. Read `sertalpbilal/FPL-Optimization-Tools`
first — it is the open reference implementation.

**M2c — Minutes-model training recipe. DONE.** Two most recent completed
seasons, and no more. Out-of-sample on 2025-26: one season 0.459, **two 0.462**,
three 0.443, four 0.429. Older seasons describe a different game (no defensive
contribution before 2025-26, a different BPS formula, different rotation norms),
so recency beats volume. The shipping model had been trained on all four — the
worst option. `minutes.PRODUCTION_TRAIN` now pins it.

**M2b — Cross-season join. DONE.** Both paths now key on the stable FPL `code`
(`walk.player_key()` / `project.element_key()`) instead of normalised names, and
`norm_name` — now a fallback only — folds `ø ł đ ı` which NFKD leaves untouched.
2025-26 + minutes model: 0.453 -> **0.459** Spearman.

**M6 — Mini-league-aware optimisation (the paid differentiator).** Optimise rank
against *specific rivals*, not raw expected points. Requires the full points
distribution (simplification 4 above), which must therefore be built before M5,
not after. Every competitor's marketing promises "win your mini-league"; none of
them actually solve that problem.

---

## Commercial notes

- **Launch paid in July 2027, not this season.** FPL acquisition is violently
  seasonal and the 2026/27 window has essentially closed. Run this season free
  and public to build the track record and the list; sell against eleven months
  of receipts when the market is actually buying.
- **Data licensing.** The FPL API now exposes xG, xA, xGC, set-piece order and
  defensive contribution for free — much of what competitors charge for. Do not
  brand third-party data ("Opta") without a contract; Stats Perform enforces, and
  both incumbents license it. Buy a mid-tier feed (Sportmonks, API-Football) for
  lineups and injuries when M4 starts.
- **Naming.** "Premier League" and "Fantasy Premier League" are trademarks.
- **The moat is audience, not accuracy.** A better model with no distribution
  loses to a worse model with a podcast. Weekly public projections are the
  distribution engine: inherently shareable, citable by creators, and SEO in a
  category where it compounds.
