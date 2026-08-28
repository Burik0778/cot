# Statistics

What each statistic means here, how it is computed, and — more importantly —
what it does not tell you.

---

## Sample size gating

| N | Label | Behaviour |
|---|---|---|
| < 20 | Insufficient sample size | `assess()` returns the label **instead of** statistics. No CI, no p-values, no directional claim. |
| 20–29 | Low confidence | Statistics shown, labelled |
| 30–49 | Moderate | Statistics shown, labelled |
| ≥ 50 | Good | Statistics shown, labelled |

The gate lives inside `validity.assess()`, not in each caller, so it cannot be
forgotten at a call site.

---

## Outcome statistics

For a set of forward returns at a given horizon:

N · win rate · mean · median · P25 · P75 · best · worst · standard deviation
(ddof=1) · mean MFE · mean MAE.

### MFE / MAE are path-based or absent

Maximum Favourable and Maximum Adverse Excursion are computed from the **daily
price path** between anchor and horizon end — the best and worst cumulative
return reached at any point along the way.

An "excursion" computed from two endpoint prices is not an excursion; it is just
the return wearing a different name. When a daily path is unavailable,
`mfe_mean` and `mae_mean` are `None`. They are never approximated from endpoints.

---

## Base rate

Always reported next to any conditional result:

```
Base rate  = P(return > 0) across all matured observations for that market/horizon
Analog rate= P(return > 0) across the matched analogs
Edge (pp)  = (analog rate − base rate) × 100
```

A 68% win rate against a 66% base rate is noise wearing a nice number. The edge
column is the one to read.

---

## Bootstrap confidence interval

2,000 resamples with replacement, 2.5th/97.5th percentiles of the resampled
**median**, fixed seed (42) for reproducibility.

The median rather than the mean, because forward-return distributions are
fat-tailed and a single 2008-style week can drag a mean anywhere.

What it tells you: how much the median would wobble under resampling of *this*
sample. What it does not tell you: whether this sample is representative of the
future. A tight CI on 40 overlapping observations from one regime is still 40
observations from one regime.

---

## Binomial test

Two-sided p-value that the observed win count differs from what the base rate
would produce under a binomial null. Verified in tests against `scipy.stats.binomtest`.

---

## Permutation test

Empirical two-sided p-value comparing the analog sample's mean against the
distribution of means from same-size random draws from the unconditional
population.

This resampling null — rather than a full label shuffle — is the right one here,
because the analog set is a condition-selected *subset* of the population, not a
fixed-size partition of it. The question being asked is "is this subset unusual
relative to the population it came from".

---

## Effect size

Cohen's d between the analog returns and the unconditional population, pooled
standard deviation. Included because a p-value tells you whether an effect is
distinguishable from zero, not whether it is large enough to care about.

---

## Overlapping observations — the caveat that matters most

**Weekly observations with multi-week forward horizons overlap heavily.** An
8-week forward return computed every week means consecutive observations share
7 of 8 weeks of price action.

Consequences:

- Effective sample size is materially smaller than N suggests.
- Every p-value and confidence interval here is **optimistic** — they assume
  more independence than exists.
- Neighbouring analogs are frequently near-duplicates of each other. Forty
  analogs clustered in two historical episodes are closer to two observations
  than forty.

This is not corrected for. Newey-West style adjustment or block bootstrapping
would be the standard remedies, and neither is implemented. Read every p-value
in this platform with that discount applied, and give more weight to the
walk-forward fold consistency than to any single significance number.

---

## Multiple testing

Every backtest and event study logs its condition. Past 20 conditions in a
session, an explicit data-snooping warning appears alongside results.

At a 5% threshold, testing 20 independent nonsense conditions produces roughly
one "significant" result by construction. The count is displayed on screen so
you can see how deep into that territory you are.

No formal correction (Bonferroni, Benjamini-Hochberg) is applied, because the
conditions users test are neither independent nor pre-registered, which is
exactly the situation where those corrections mislead. The honest tool here is
the warning plus out-of-sample confirmation.

---

## What none of this establishes

- **Not causation.** Positioning extremes and subsequent returns co-occurring
  says nothing about mechanism. Both may respond to a third factor.
- **Not stationarity.** Market structure changes. A 2015–2019 relationship may
  simply not exist now, and no in-sample statistic can tell you that.
- **Not tradability.** Nothing here accounts for slippage on illiquid days,
  financing, position sizing, or the fact that acting on a signal changes it.
