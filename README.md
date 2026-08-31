<!-- TEST_COUNT_START -->
**258 automated tests.** Run `python -m pytest` or `python -m unittest discover -s tests`.
<!-- TEST_COUNT_END -->

# COT Research Platform

A research system for Commitments of Traders (CFTC TFF Futures Only) positioning
in FX. It describes the **current state** of positioning, finds **historical
analogs** of that state, and reports **what happened next relative to a base
rate** — with explicit sample-size and statistical-validity gating.

It is not a price predictor and it does not emit trading signals. See
`docs/AI.md` and `docs/METHODOLOGY.md` for exactly what it does and does not
claim.

---

## Read this first: what was actually verified

This section exists because the project brief asked for it (§68) and because it
is the only honest way to hand over software. Everything below is a statement
about what was *executed*, not what was *written*.

### Verified by running it

| Area | How it was verified |
|---|---|
| Automated tests | `python -m pytest` (или `python -m unittest discover -s tests`) — счётчик в шапке README обновляется скриптом `scripts/count_tests.py`, не вручную |
| Percentile / z-score exclude the current observation | Hand-computed examples in `tests/test_percentile.py`, plus a test proving a new all-time-high can reach exactly the 100th percentile (impossible if self-inclusion were happening) |
| No look-ahead in analogs | `tests/test_analog_engine.py` — engine *raises* if the reference pool contains rows with `availability_date` after the as-of date, and *raises* if a `fwd_return_*` column is passed as a matching feature (label leakage) |
| Forward returns are maturity-aware | Unmatured horizons return `None`, never 0 or a guess (`tests/test_quote_convention_and_returns.py`) |
| Quote convention (USD base vs quote) | Every currency's sign direction asserted explicitly |
| Full pipeline end-to-end | 8 currencies × 5 participants × 2015–2026 (607 weekly market states for EUR) built from raw → processed → market_states |
| Analog engine on real data | `scripts/run_demo.py` produced EUR and GBP analyses with computed N, win rate, base rate, edge, and per-horizon sample quality |
| AI layer cannot fabricate numbers | `tests/test_ai_analyst.py` extracts every numeric token from generated text and traces each back to the input stats; includes a control test that *injects* a fake number and confirms the checker catches it |
| Statistical machinery recovers a known effect | `synthetic.py` injects a small, documented positioning→price effect; the demo script recovers it (EUR +0.036%, GBP +0.030% mean 1W return vs unconditional) |
| Standalone HTML dashboard | Executed under Node.js v22 with a DOM shim against the real exported data — rendered 8 scanner rows, charts, currency switching, and column sorting without throwing |
| Static site render | The site's JavaScript was executed under Node.js v22 against a DOM shim with the real generated data: 3 range strips, 8 analog cards, 8 currency cards rendered, and no `NaN`/`undefined` reached the output |

### NOT verified — do not assume these work until you check

| Area | Status |
|---|---|
| **Live CFTC API call** | **Never executed.** The build sandbox blocks all outbound network traffic (`403 host_not_allowed` from its egress proxy, confirmed by direct `curl`). `src/data/cftc_client.py` is real code written against the documented Socrata API, but its first live run will be on your machine. |
| **Live FRED price fetch** | **Never executed**, same reason. |
| **Validation against official CFTC numbers (§52)** | **Not done.** This is the single most important thing you must do first — see "First run" below. Long/Short/Net/OI have never been compared against a real CFTC report. |
| **The site in a real browser** | Never opened in an actual browser. The JS logic was executed under Node and the HTML/CSS is hand-written, but visual layout, fonts loading, and responsive behaviour are unverified. |
| **Plotly charts rendering** | Never rendered; `plotly` is not installed in the sandbox. |
| **NZD price data** | FRED publishes no standard NZD/USD daily series. The code raises a clear error instead of inventing a series id. NZD COT analysis works; NZD price/return features do not, until you wire a source. |
| **Parquet export** | `pyarrow` not installed in the sandbox; the code path raises a clear error rather than silently writing a different format. |
| **PDF report generation** | Not implemented in this build (see `docs/LIMITATIONS.md`). |
| **All numbers in the demo output** | Computed from **synthetic data**. They are a test of the machinery, not a finding about real FX markets. |

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.11+ recommended (developed and tested on 3.12).

## First run

**Option A — try the platform immediately, with synthetic data:**

```bash
python scripts/init_db.py --synthetic
python scripts/run_demo.py
python scripts/build_site.py
```

Every screen will show a red **DEMO MODE** banner. Nothing here is real market data.

**Option B — real data (do this properly):**

```bash
python scripts/init_db.py --live --currencies EUR GBP
python scripts/validate_date.py --market EUR --date 2026-08-18
```

Then **stop and actually compare** the printed Long/Short/Net/Open Interest
against the official CFTC report for that date, at
<https://publicreporting.cftc.gov/> or the historical viewable reports at
<https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/index.htm>.

If anything differs, do not proceed — check `REQUIRED_COLUMNS` and
`PARTICIPANT_COLUMN_MAP` in `src/data/cftc_client.py` against the live dataset's
current column names, and write down what differed in `docs/LIMITATIONS.md`.

Then:

```bash
python scripts/build_site.py
```

Ongoing updates (incremental — only fetches report dates newer than what you have):

```bash
python scripts/refresh_data.py --currencies EUR GBP
```

## Rebuilding the site

```bash
python scripts/export_dashboard_json.py
python -c "
from pathlib import Path
Path('dashboard/index.html').write_text(
    Path('dashboard/index_template.html').read_text().replace(
        '__DASHBOARD_DATA__', Path('dashboard/dashboard_data.json').read_text()))
"
```

Then open `dashboard/index.html` in any browser. It is fully self-contained (no
CDN, no server) and renders a snapshot — it does not recompute anything
client-side — all statistics are computed in Python by `build_site.py`.

## Running the tests

```bash
python -m unittest discover -s tests -v
```

Uses Python's built-in `unittest` deliberately, so the test suite runs with zero
extra dependencies.

## Architecture

```
config/settings.py      Every threshold, window, weight, contract name, and quote
                        convention — one visible file, no hidden defaults

src/data/               availability.py   report_date vs availability_date (no look-ahead)
                        cftc_client.py    CFTC Socrata TFF Futures Only
                        price_client.py   FRED FX series
                        synthetic.py      clearly-tagged demo data
                        db.py             SQLite (raw append-only, derived rebuildable)
                        data_quality.py   gaps, dupes, outliers, freshness, schema drift
                        export.py         CSV / JSON / Excel / Parquet

src/cot/                metrics.py        Net, Net/OI, changes, streaks
                        percentile.py     rolling percentile & z-score, current excluded
                        regimes.py        ordered, visible rule engine
                        divergence.py     participant-vs-participant, participant-vs-price
                        regime_history.py every past occurrence of a regime + outcomes

src/price/              quote_convention.py  USD-base vs USD-quote sign handling
                        returns.py           maturity-aware forward returns

src/analogs/            similarity.py     weighted standardized distance + similarity score
                        outcomes.py       N, win rate, percentiles, path-based MFE/MAE
                        baserate.py       the mandatory unconditional comparison
                        validity.py       bootstrap CI, binomial, permutation, effect size

src/events/             event_study.py    condition → outcomes across horizons
src/backtest/           conditions.py, engine.py, metrics.py, walkforward.py
src/ai/                 analyst.py        explains computed numbers; cannot invent one
src/scanner/            scanner.py        cross-currency overview
src/pipeline.py         raw → processed → market_states

site/                   Static site: template.html + generated index.html
dashboard/              standalone HTML/JS snapshot
scripts/                init_db, refresh_data, validate_date, run_demo, build_site
tests/                  автотесты (число — см. шапку README)
docs/                   METHODOLOGY, DATA_SOURCES, STATISTICS, BACKTESTING, AI, LIMITATIONS
```

## The core discipline

Every output separates:

- **Fact** — Leveraged Funds are −57,716 net.
- **Statistical observation** — that is the 4th percentile of the last 5 years.
- **Interpretation** — positioning is historically extreme.
- **Hypothesis** — extreme shorts plus improving momentum *may* precede a reversal.
- **Trading idea** — never generated automatically.

The system says "observed in X of Y cases" and "the statistical edge was", never
"buy EUR" and never "COT predicts price".
