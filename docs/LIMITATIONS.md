# Known limitations

The brief asked for this list (§68) and asked not to be told something works
when it has not been checked (§66). Organised by how much it should worry you.

---

## 1. Never executed against live data

**The single most important item.** No CFTC or FRED request has ever been made
by this code. The build environment blocks outbound network traffic
(`403 host_not_allowed`, confirmed by direct testing).

Consequences:

- Column names in `REQUIRED_COLUMNS` come from CFTC's documented schema, not
  from a live response.
- Contract names in `CFTC_MARKET_NAMES` are unverified against the live dataset.
- FRED CSV parsing is unverified against a real response.
- **No Long/Short/Net/Open Interest figure has ever been compared against an
  official CFTC report.**

Do this first: `python scripts/validate_date.py --market EUR --date 2026-08-18`,
then compare line by line against CFTC's published report. Until you have,
treat correctness of the data layer as unestablished.

## 2. Every demo number is synthetic

All figures in `scripts/run_demo.py` output, `dashboard/`, and this
conversation's examples were computed from generated data. The engineered
positioning→price effect in `synthetic.py` exists to test that the statistics
machinery recovers a known signal. Recovering it says the code works. It says
nothing about FX markets.

## 3. Overlapping observations inflate significance

Weekly observations with multi-week horizons share most of their price path.
Effective sample size is materially below N; every p-value and confidence
interval is optimistic. No Newey-West adjustment or block bootstrap is
implemented. See `docs/STATISTICS.md`.

## 4. The site was never opened in a browser

The site is plain HTML/CSS/JS with no framework. Its JavaScript was executed
under Node.js against a DOM shim with the real generated data, which catches
logic errors — but not visual layout, web-font loading, or responsive
behaviour. Expect to report visual issues on first real viewing.

---

## Not implemented

| Item | Status |
|---|---|
| **PDF research report** (§48, §49) | Not implemented. CSV/JSON/Excel export works; `reportlab` is available if you want to add it. |
| **Machine learning** (§42) | Deliberately absent. The brief said to use ML only with evidence it adds out-of-sample value over the simple approach. That comparison has not been run, so no ML is used. |
| **Settings persistence** (§55) | Settings are read from `config/settings.py` and displayed in the UI, but not editable from the UI. Editing the file and restarting is the supported path — one source of truth rather than two. |
| **Auto-update scheduling** (§36) | `refresh_data.py` is incremental and ready for cron/Task Scheduler, but no scheduler is bundled. |
| **Pre-event horizons in event study** (§22) | Post-event horizons work. Negative horizons return `NaN` unless a matching trailing-return column exists, rather than fabricating a lookback. |
| **`fwd_return_matured_json`** | Column reserved in the schema, not populated. |
| **PostgreSQL** (§35) | SQLite only. Access is centralised in `src/data/db.py`, so migration is contained, but has not been done or tested. |
| **Pair-level analysis for crosses** (§26) | Per-currency analysis (EUR, GBP…) is complete. True cross-pair analysis (EUR/GBP as a joint object with its own analogs) is not — the relative-strength view approximates it. |

---

## Structural limitations

**Backtest realism.** Fixed one unit per signal, no overlapping-position
modelling, no spread/slippage/financing, default zero transaction cost. See
`docs/BACKTESTING.md` for the full table.

**Similarity score is a heuristic.** `100 × exp(−distance / RMS distance)` — a
documented, reproducible, monotonic transform. Not a probability. `distance` is
the defensible number.

**Condition input is not a security boundary.** `pandas.query()` plus a token
blocklist protects against malformed input in a local tool. Do not expose over a
network.

**Availability dates outside 2026 are derived, not published.** Tagged
`derived_rule`, using a documented Friday-plus-holiday rule with an approximate
federal-holiday calendar.

**The Oct–Dec 2025 publication gap is flagged, not corrected.** Rows in that
window carry a warning. Substitute real release dates from CFTC press releases
9138-25 / 9147-25 if you need precision there.

**NZD has no price source.** FRED publishes no standard NZD/USD daily series.
The code raises rather than inventing one. NZD COT analysis works; NZD price and
forward-return features do not.

**Parquet export requires `pyarrow`.** Raises a clear error if absent — never
silently writes a different format.

**Non-reportables are a residual.** Per CFTC's own definition. The trader count
and commercial/non-commercial classification within it are unknown by
construction.

**Contracts can vanish.** CFTC drops a market from the report when fewer than 20
large traders hold reportable positions. The client raises a clear error rather
than treating this as "the currency stopped existing".

---

## Bugs found and fixed during development

Listed because they indicate where the fragile parts are:

1. `isoweekday()`/`weekday()` confusion in the "next Friday" calculation — availability dates were a week off
2. SQLite returns dates as strings; date arithmetic downstream silently broke
3. Streak logic used `cumcount` where `cumsum` was correct
4. Mixed-dtype Series broke `np.sqrt` in the analog engine
5. Classical z-score outlier detection was masked by the very outlier it should catch — replaced with a MAD-based robust modified z-score
6. `features_json` was written but never expanded on read, so the analog engine could not see participant features
7. The AI fabrication checker did not allow numbers from the free-text input fields
8. Its regex treated list numbering ("1.", "2.") as data
9. The signal-recovery check compared a 4-week change against a 1-week-lagged injected effect — a mismatched-variable comparison, not a statistics bug
11. `run_demo.py` used a hardcoded as-of date while the database rebuilds to "today", leaving newer rows in the analog reference pool — the look-ahead guard refused to run, which is exactly the behaviour it exists for
10. The synthetic generator violated the COT accounting identity at extreme net values (reportable positions exceeded open interest, clamping the non-reportable residual to zero) — found by the accounting-identity data-quality check the moment it was added, which is exactly what that check is for

Every one was caught by a test or a real run, not by reading the code.
