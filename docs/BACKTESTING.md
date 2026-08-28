# Backtesting

The brief was explicit that research and an actual trading strategy are
different things (§43). This engine does research. Read the simplifications
before you read any performance number it produces.

---

## What it does

1. Evaluates a user condition against `market_states`.
2. Splits matched signals into **matured** (forward return known) and **still
   open** (horizon has not elapsed). Both counts are displayed.
3. Applies direction (`long_currency` / `short_currency`) and a per-trade
   transaction cost in basis points.
4. Computes performance metrics on matured trades only.
5. Splits the matured trades into chronological walk-forward folds.
6. Logs the condition to the multiple-testing counter.

---

## Conditions

Conditions use `pandas.DataFrame.query()` syntax:

```
leveraged_funds_pct_52w < 10 and asset_manager_net_oi > 0.20 and leveraged_funds_chg_4w > 0
```

`query()` is used rather than `eval()` because it only understands column names,
comparisons and boolean logic — not arbitrary statements, attribute access or
function calls. A short token blocklist is layered on top.

**Scope of that restriction, honestly:** this is protection against obviously
malformed input in a local, single-user research tool. It is not a security
boundary against a determined attacker who already has the same privileges as
the process. Do not expose this over a network as-is.

An unknown column or malformed expression raises with the original pandas error
— it never returns a silently-empty mask that would read as "no historical
occurrences".

---

## Performance metrics

Win rate · average win · average loss · expectancy · profit factor · Sharpe ·
Sortino · max drawdown · Calmar · trade count · average holding period.

Sharpe and Sortino are annualised by `√(52 / holding_period_weeks)`, which
treats each trade as an independent period sampled at the holding frequency.
Given overlapping trades (below), **these are optimistic**.

The equity curve compounds trades in chronological entry order.

---

## Simplifications — every one of these matters

| Simplification | Consequence |
|---|---|
| **Fixed one unit per signal.** No volatility scaling, no risk-based sizing. | Position sizing is often the largest driver of real strategy performance. None of it is modelled. |
| **Overlapping positions not modelled.** The equity curve compounds sequentially even when signals fire inside each other's holding windows. | Real capital cannot be deployed this way. Drawdown and Sharpe are both distorted. |
| **Transaction costs are a flat user-supplied bps figure, defaulting to 0.** | Default 0 means the headline numbers are frictionless. Set a realistic figure before believing anything. |
| **No spread or slippage data wired in.** | Real spreads widen exactly when signals cluster (event risk). |
| **No financing / carry / rollover.** | Materially wrong for multi-week FX horizons, especially high-differential pairs like MXN. |
| **Entry at the availability-date close.** | Assumes execution at a specific close following a 3:30pm ET Friday release. |
| **No parameter optimisation, therefore no optimisation bias — but also no tuning.** | Walk-forward here checks *stability*, not out-of-sample performance of a tuned rule. |

---

## Walk-forward

Matured trades are split into K chronological folds (default 4), and per-fold
N, win rate and mean return are reported.

This is deliberately **not** an optimisation walk-forward — the platform does
not auto-tune thresholds, so there is nothing to re-fit per fold. It answers a
narrower, honest question: is the edge spread across the whole history, or
concentrated in one early period?

An explicit warning fires when fold 1 has a positive mean return and the final
fold does not — the classic in-sample-good, recent-bad pattern.

Fewer than `5 × folds` matured trades produces a "too few trades to split"
message rather than meaningless folds.

---

## Overfitting protection

- Sample-size gating (< 20 → no claims)
- Multiple-testing counter and warning past 20 conditions
- Walk-forward fold consistency check
- Analog engine refuses forward-return columns as matching features
- Analog engine refuses reference pools containing future-availability rows

---

## How to read a good-looking result

A strong-looking backtest here means: *this condition, on this history, with
these simplifications, would have produced these numbers.* It does not mean the
condition works.

Before taking any result seriously:

1. Set a realistic transaction cost. Re-run.
2. Check the walk-forward folds. If the edge lives in one fold, it is probably an episode, not an effect.
3. Check N against the **overlapping-observations** caveat in `docs/STATISTICS.md` — 40 weekly observations at an 8-week horizon are nowhere near 40 independent trials.
4. Check how many conditions you have already tested this session.
5. Check the base-rate comparison, not the raw win rate.
