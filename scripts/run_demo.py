"""
scripts/run_demo.py

Produces a REAL end-to-end run of the full engine against the synthetic
demo dataset (data/cot_research.db, built by scripts/init_db.py --synthetic).
Everything printed here is computed, not hand-written -- this is the basis
for the "Example analysis: EUR/USD" and "Example analysis: GBP/USD"
deliverables (spec section 68, items 8-9) and for the "signal recovery"
sanity check described in src/data/synthetic.py's docstring.

EVERYTHING in this output describes SYNTHETIC data (source=synthetic_demo)
and must never be read as a statement about real FX markets.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from src.data.db import Database
from src.pipeline import expand_features_json
from src.analogs.similarity import fit, find_analogs
from src.analogs.outcomes import summarize_returns
from src.analogs.baserate import compare_to_base_rate
from src.analogs.validity import assess
from src.ai.analyst import AnalysisInput, generate_analysis, assert_no_fabricated_numbers

HORIZONS = [4, 8, 12]
FEATURES = settings.DEFAULT_ANALOG_FEATURES


def analyze_currency(db: Database, currency: str, as_of: date | None = None) -> dict:
    states = db.read_market_states(currency)
    states = expand_features_json(states)
    states = states.dropna(subset=list(FEATURES.keys())).reset_index(drop=True)
    if states.empty:
        return {"currency": currency, "error": "no rows with complete features"}

    current = states.iloc[-1]
    pool = states.iloc[:-1]  # never match the current row against itself

    # The as-of date must come from the observation being analyzed, not from a
    # hardcoded constant: the database is rebuilt up to "today", so a fixed
    # date leaves rows in the pool that are newer than it, and the analog
    # engine (correctly) refuses to proceed. Caught by that guard on a clean
    # rebuild -- see README.
    as_of = as_of or current["availability_date"]

    fitted = fit(pool, FEATURES)
    analogs = find_analogs(fitted, current, as_of_date=as_of, max_analogs=settings.DEFAULT_MAX_ANALOGS)

    analog_indices = [a.index for a in analogs]
    analog_rows = states.loc[analog_indices]

    horizon_stats = {}
    for h in HORIZONS:
        col = f"fwd_return_{h}w"
        cmp = compare_to_base_rate(analog_rows[col], states, h, col)
        validity = assess(analog_rows[col], states[col], base_rate=cmp.base_rate.win_rate,
                           hypotheses_tested_this_session=1)
        horizon_stats[h] = {
            "n": cmp.analog_rate.n,
            "win_rate": cmp.analog_rate.win_rate,
            "median_return": cmp.analog_rate.median_return,
            "base_rate": cmp.base_rate.win_rate,
            "edge_pp": cmp.win_rate_diff_pp,
            "sample_quality": cmp.analog_rate.sample_quality,
            "bootstrap_ci_median": validity.bootstrap_ci_median,
            "binomial_p_value": validity.binomial_p_value,
            "permutation_p_value": validity.permutation_p_value,
            "cohens_d": validity.effect_size_cohens_d,
        }

    ai_input = AnalysisInput(
        market=currency,
        regime=current["regime"],
        regime_reasons=json.loads(current["regime_reasons"]) if isinstance(current["regime_reasons"], str) else current["regime_reasons"],
        horizon_stats={h: {k: v for k, v in s.items() if k in ("n", "win_rate", "median_return", "base_rate", "edge_pp", "sample_quality")} for h, s in horizon_stats.items()},
        divergences=json.loads(current["divergence_flags"]) if isinstance(current["divergence_flags"], str) else [],
    )
    analysis_text = generate_analysis(ai_input)
    untraceable = assert_no_fabricated_numbers(analysis_text, ai_input)

    return {
        "currency": currency,
        "as_of_report_date": str(current["report_date"]),
        "current_regime": current["regime"],
        "n_analogs_found": len(analogs),
        "top_3_analogs": [
            {"report_date": a.report_date, "distance": round(a.distance, 4), "similarity_score": round(a.similarity_score, 1)}
            for a in analogs[:3]
        ],
        "horizon_stats": horizon_stats,
        "ai_analysis_text": analysis_text,
        "ai_untraceable_numbers": untraceable,
    }


def main():
    db = Database(settings.DB_PATH)
    results = {}
    for currency in ["EUR", "GBP"]:
        print("=" * 70)
        print(f"EXAMPLE ANALYSIS: {currency} (SYNTHETIC DEMO DATA -- not real market data)")
        print("=" * 70)
        result = analyze_currency(db, currency)
        results[currency] = result
        print(f"As-of report date: {result.get('as_of_report_date')}")
        print(f"Current regime: {result.get('current_regime')}")
        print(f"Analogs found: {result.get('n_analogs_found')}")
        print("Top 3 analogs:", result.get("top_3_analogs"))
        print()
        print(result.get("ai_analysis_text"))
        print()
        print("AI untraceable numbers (should be empty):", result.get("ai_untraceable_numbers"))
        print()

    print("=" * 70)
    print("SIGNAL-RECOVERY SANITY CHECK (synthetic.py injected a known, small")
    print("positioning->price effect -- this checks whether the statistics")
    print("machinery actually recovers it; this is a check on the CODE, not")
    print("a finding about real markets)")
    print("=" * 70)
    for currency in ["EUR", "GBP"]:
        states = db.read_market_states(currency)
        states = expand_features_json(states)
        from src.backtest.conditions import evaluate_condition
        # Faithful proxy for the injected mechanism: synthetic.py drives
        # week-i's price return from the leveraged-funds net_oi change one
        # week EARLIER (a single-week lag) -- so the matching check here
        # uses horizon=1 and the 1-week (not 4-week) positioning change, to
        # actually test the mechanism that was built, rather than a
        # differently-aggregated proxy for it.
        mask = evaluate_condition(states, "leveraged_funds_chg_1w > 0")
        matured = states[mask].dropna(subset=["fwd_return_1w"])
        base_matured = states.dropna(subset=["fwd_return_1w"])
        if len(matured) >= settings.MIN_SAMPLE_SIZE:
            edge = matured["fwd_return_1w"].mean() - base_matured["fwd_return_1w"].mean()
            print(f"{currency}: mean 1W return when leveraged-fund net_oi rose the prior week vs unconditional mean: "
                  f"{edge:+.4%} (N={len(matured)}) -- positive is consistent with the injected effect.")
        else:
            print(f"{currency}: insufficient matured sample to check.")

    out_path = Path(__file__).resolve().parents[1] / "data" / "processed" / "demo_run_output.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print()
    print(f"Full structured output written to {out_path}")

    # Generate a real research report (spec section 49) from the EUR run --
    # exercising src/reporting/report.py against computed values rather than
    # leaving it as an untested module.
    from src.reporting.report import ReportInput, build_markdown, build_html
    from config.settings import FX_PAIRS

    eur = results["EUR"]
    states = expand_features_json(db.read_market_states("EUR"))
    current = states.sort_values("report_date").iloc[-1]
    participant_rows = [{
        "participant": settings.PARTICIPANT_LABELS[p],
        "net": current.get(f"{p}_net"), "net_oi": current.get(f"{p}_net_oi"),
        "pct_52w": current.get(f"{p}_pct_52w"), "z_52w": current.get(f"{p}_z_52w"),
        "chg_4w": current.get(f"{p}_chg_4w"),
    } for p in settings.PARTICIPANTS]

    report_input = ReportInput(
        market="EUR", pair_symbol=FX_PAIRS["EUR"].symbol,
        report_date=str(current["report_date"]), availability_date=str(current["availability_date"]),
        availability_source="see cot_raw.availability_source", is_synthetic=True,
        regime=eur["current_regime"],
        regime_reasons=json.loads(current["regime_reasons"]) if isinstance(current["regime_reasons"], str) else [],
        participant_rows=participant_rows,
        price_close=current.get("price_close"),
        price_changes={"4w": current.get("price_chg_4w"), "8w": current.get("price_chg_8w"), "12w": current.get("price_chg_12w")},
        n_analogs=eur["n_analogs_found"],
        top_analogs=[{"report_date": a["report_date"], "similarity_score": a["similarity_score"], "distance": a["distance"]}
                     for a in eur["top_3_analogs"]],
        horizon_stats=eur["horizon_stats"],
        divergences=json.loads(current["divergence_flags"]) if isinstance(current["divergence_flags"], str) else [],
        contradictions=[],
        ai_analysis=eur["ai_analysis_text"],
    )
    reports_dir = Path(__file__).resolve().parents[1] / "data" / "processed"
    (reports_dir / "EUR_research_report.md").write_text(build_markdown(report_input))
    (reports_dir / "EUR_research_report.html").write_text(build_html(report_input))
    print(f"Research report written to {reports_dir / 'EUR_research_report.md'} (and .html)")


if __name__ == "__main__":
    main()
