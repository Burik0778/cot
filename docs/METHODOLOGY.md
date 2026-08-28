# Methodology

Every number this platform displays is computed by code in `src/`. This document
states how, so that any figure can be traced back to a formula and a source
column. Where a method is an approximation or a judgment call, it says so.

---

## 1. The two dates

Every COT observation carries two dates, and confusing them is the single
easiest way to produce a backtest that looks brilliant and is worthless.

- **`report_date`** — the Tuesday whose open interest the report describes.
- **`availability_date`** — the date a trader could actually have acted on it.

CFTC's own Release Schedule page states that COT reports are released at
3:30 p.m. Eastern, usually Friday, covering the previous Tuesday.

Two sources are used for `availability_date`, and each row records which one:

| `availability_source` | Meaning |
|---|---|
| `cftc_published_schedule` | The exact release date CFTC itself published for 2026. `report_date` → release date is derived programmatically as "the most recent Tuesday strictly before that release date", so holiday-shifted releases are handled correctly without hand-mapping. |
| `derived_rule` | For dates outside the published table: the Friday on or after `report_date + 3 days`, shifted forward one day per US federal holiday encountered. This matches CFTC's stated general pattern but is **not** a published fact, hence the separate tag. |

The federal-holiday check used by the fallback rule covers fixed-date and
fixed-weekday federal holidays only. It is an approximation, and it is only ever
used for `derived_rule` rows.

### The known-wrong window

CFTC suspended COT publication during the October–November 2025 lapse in federal
appropriations and cleared the backlog on a compressed catch-up schedule (CFTC
press releases 9138-25 and 9147-25). Report dates from roughly 2025-09-23 to
2025-12-30 were **not** released on their normal Friday.

The derived rule does not know this. Rather than silently producing a wrong
date, `derive_availability_date()` attaches an explicit warning to every row in
that window. Do not trust precise no-look-ahead backtests spanning it without
substituting the actual release dates from those press releases.

---

## 2. Positioning metrics

All computed from raw `long`, `short`, `open_interest` — never taken
pre-computed from any third party.

```
net       = long − short
net_oi    = net / open_interest
long_oi   = long / open_interest
short_oi  = short / open_interest
chg_{W}w  = value[t] − value[t−W]        (NaN when fewer than W prior observations)
```

**Non-reportables are derived, not reported.** Per CFTC's Explanatory Notes,
non-reportable positions are the residual: total open interest minus total
reportable positions. `cftc_client.py` computes it that way from the same rows
it already fetched.

**Streaks.** `streak_up_weeks[t]` is the number of consecutive weeks ending at
`t` in which `net` strictly increased. A flat week resets both streak counters
to 0 for that row.

---

## 3. Percentile — the current observation is excluded

This is the rule most COT tools get wrong, and it matters most exactly when
positioning is extreme.

For window `W`, `pct_{W}w[t]` ranks `value[t]` against `value[t−W .. t−1]` —
`W` prior observations, **not including `t` itself**. Implemented by rolling a
frame of size `W+1` and slicing the last element off before ranking.

Why it matters: if the current value were included in its own reference
distribution, a genuine new all-time extreme could never reach the 100th (or
0th) percentile, because it would always be compared against itself. A test in
`tests/test_percentile.py` asserts exactly this property.

`NaN` until `W` prior observations exist. No partial-window percentiles.

## 4. Z-score — also excludes the current observation

```
z_{W}w[t] = (value[t] − mean(value[t−W .. t−1])) / std(value[t−W .. t−1])
```

Mean and standard deviation are computed over the window ending at `t−1`
(`shift(1)` before rolling), with `ddof=1` (sample standard deviation). A
zero-variance window yields `NaN`, not a division error.

Windows available for both percentile and z-score: 13, 26, 52, 156, 260 weeks.
Never mixed implicitly — every column carries its window in its name.

---

## 5. Quote convention

A rise in `EURUSD` means EUR strengthened. A rise in `USDJPY` means JPY
**weakened**. Getting this backwards inverts every conclusion for half the
currency universe.

| Currency of interest is the base (rise = currency strengthens) | Currency of interest is the quote (rise = currency weakens) |
|---|---|
| EUR, GBP, AUD, NZD | JPY, CAD, CHF, MXN |

`currency_return()` applies the sign flip explicitly for the second group. Each
FRED series was chosen because its published unit definition already matches the
market convention in `FX_PAIRS` — do not "fix" the sign in one place without
re-checking both definitions together.

---

## 6. Forward returns

Anchored on **`availability_date`**, not `report_date`, because that is when the
information could have been used.

For horizon `H`: the first available close on or after the anchor, to the first
available close on or after `anchor + H weeks`. Never a close *before* the
target date — that would look backwards to fill a gap.

**Maturity awareness.** If `anchor + H weeks` is later than the as-of date, the
return is `None`. It is never 0, never the last known value, never extrapolated.
This propagates correctly through base rates, analog outcomes, event studies and
backtests, all of which `dropna()` on the return column — so an unmatured
observation is counted as "not yet known", not as a flat outcome.

---

## 7. Regime classification

Rules live in `config.settings.REGIME_RULES` as plain
`(column, operator, threshold)` tuples, evaluated **in order**; the first rule
whose every condition holds wins. Ordering is itself part of the method: more
specific rules (Extreme Short) precede more general ones (Bearish Positioning).

Every classification returns the list of conditions that fired, with the actual
values — this is what the UI's **WHY?** expander shows. Nothing is opaque.

A missing or `NaN` input makes a condition false rather than raising, so a
partially-computed row degrades to a less specific regime instead of crashing or
falsely matching.

`Neutral` is the fallback with no conditions, so classification is total.

Compression/expansion is reported as an *additional* flag alongside the main
regime (a market can be Bullish Positioning **and** in Positioning Compression),
based on the ratio of recent to prior positioning volatility.

---

## 8. Divergence

A divergence is flagged when two signed series' `W`-week changes have opposite
signs and **both** exceed a noise floor — so two near-zero wiggles in opposite
directions are not dignified with the label.

Tracked pairs: Asset Managers vs Leveraged Funds, and Leveraged Funds vs Price.

The engine reports facts only: which participants, which direction, over what
window, and magnitude — defined as `min(|change_a|, |change_b|)`, since a
divergence is only as strong as its weaker leg. It draws no conclusion about
what a divergence implies.

---

## 9. Historical analog engine

1. Features are standardized (z-scored) using **only the reference pool**, not
   the query.
2. Distance = weighted Euclidean distance over those standardized features.
3. `distance` is reported directly. This is the honest, always-defensible number.
4. A bounded similarity score is *also* reported:

```
similarity = 100 × exp(−distance / scale)
```

where `scale` is the RMS distance across the reference pool, so the transform
self-calibrates to how spread out that history actually is.

**This score is a presentation-layer heuristic, not a probability.** It is
monotonic in distance and reproducible, which is the most that can be claimed
for it. If you need a defensible number, use `distance`. The brief asked not to
show fake precision (§14); this is the compromise — a documented transform,
reported alongside the raw quantity it comes from.

### Two guards enforced inside the engine

- **Availability.** If the reference pool contains any row with
  `availability_date` after the as-of date, the engine **raises**. It does not
  quietly filter them — that filtering must be visible in the calling code.
- **Label leakage.** Passing any `fwd_return_*` column as a matching feature
  **raises**. Matching analogs partly on their own future outcome is a subtler
  look-ahead than a date violation, and it is blocked at the same level.

Features, weights, window and analog count are all user-adjustable.

---

## 10. Base rate — mandatory, not optional

"68% of similar cases went up" is close to meaningless alone. The platform
always pairs an analog win rate with the **unconditional** win rate over the
same history and horizon, and reports the difference in percentage points.

```
Base rate    = P(return > 0) over all matured observations for that market/horizon
Analog rate  = P(return > 0) over the matched analogs
Edge         = (analog rate − base rate) × 100, in pp
```

---

## 11. Statistical validity

Below `MIN_SAMPLE_SIZE` (default 20), `validity.assess()` returns the string
"Insufficient sample size" **instead of** statistics. The gate is inside the
function rather than left to each caller to remember.

Above it:

- **Bootstrap CI** for the median (2,000 resamples, 2.5/97.5 percentiles, fixed seed)
- **Binomial test** of the analog win rate against the base rate
- **Permutation test** — empirical p-value from resampling same-size draws from
  the unconditional population. This, not a full label shuffle, is the correct
  null for "is this condition-selected subset unusual relative to the population
  it was drawn from".
- **Cohen's d** effect size

Sample-quality labels: <20 insufficient · <30 low confidence · <50 moderate · ≥50 good.

**Multiple testing.** Every backtest and event study logs its condition to
`hypothesis_log`. Past 20 conditions in a session, results carry an explicit
data-snooping warning. Testing 500 conditions and reporting the best one is the
easiest way to fool yourself, and the platform says so on screen.

---

## 12. Deliberate design tradeoffs

- **The derived layer is rebuilt wholesale, not incrementally.** Recomputing
  rolling statistics for ~600 weekly rows per currency is cheap locally, and it
  eliminates an entire class of incremental-recompute bugs. Incrementality lives
  at the *fetch* layer (`refresh_data.py` only requests report dates newer than
  what is stored).
- **Raw is append-only.** `cot_raw` and `price_raw` are deduplicated on
  `(market, participant, report_date, source)` and never overwritten by
  reprocessing. Every rebuild starts from them.
- **Settings are a Python file, not a settings table.** One visible,
  version-controlled, diffable source of truth, rather than two.
- **No ML.** The brief said to use it only if it demonstrably adds
  out-of-sample value over the simple approach (§42). That comparison has not
  been run, so nothing here uses ML. Rule-based, nearest-neighbour and event
  study only.
