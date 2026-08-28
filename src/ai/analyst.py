"""
src/ai/analyst.py

Spec sections 38-41, 60-61: the AI layer explains, structures, and flags
contradictions -- it NEVER computes statistics itself and NEVER emits a
number that wasn't handed to it by the quant engine. This is enforced
structurally here, not just by instruction: `generate_analysis` only
interpolates values out of the `stats` dict it receives into a fixed
template. It has no code path that computes or invents a figure.

Language discipline (spec sections 60-61): output uses hedged, evidence-
framed language ("Historical evidence suggests...", "Observed in X of Y
cases...") and never a directive ("BUY EUR"), never "COT predicts price",
never states correlation as causation.

Optional LLM polish (spec section 55 "AI provider"): `generate_analysis`
produces the deterministic, fully-auditable text below by default (zero
network dependency, fully testable). `polish_with_llm()` is a separate,
clearly optional function that would send this SAME text plus the SAME
stats dict to an LLM (e.g. Anthropic's Claude API -- see AI.md) asking it
to rephrase without changing any figure; it is not wired up or exercised
in this build (see AI.md for why, and for the exact prompt contract a
polish call must respect: never introduce a number absent from `stats`).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class AnalysisInput:
    market: str
    regime: str
    regime_reasons: list[str]
    horizon_stats: dict          # {horizon_weeks: {"n":..,"win_rate":..,"median_return":..,"base_rate":..,"edge_pp":..,"sample_quality":..}}
    contradictions: list[str] = field(default_factory=list)
    divergences: list[str] = field(default_factory=list)


def _fmt_pct(x) -> str:
    return "N/A" if x is None else f"{x*100:.1f}%"


def _fmt_pp(x) -> str:
    return "N/A" if x is None else f"{x:+.1f}pp"


def generate_analysis(data: AnalysisInput) -> str:
    lines = []
    lines.append("CURRENT STATE")
    lines.append(f"{data.market} COT regime: {data.regime}")
    lines.append("")
    lines.append("WHY:")
    for i, reason in enumerate(data.regime_reasons, 1):
        lines.append(f"{i}. {reason}")
    lines.append("")
    lines.append("HISTORICAL EVIDENCE")
    for h in sorted(data.horizon_stats.keys()):
        s = data.horizon_stats[h]
        lines.append(f"")
        lines.append(f"{h}W (N={s.get('n')}, sample quality: {s.get('sample_quality', 'unknown')}):")
        if s.get("sample_quality") == "Insufficient sample size":
            lines.append("  Insufficient sample size -- no directional claim is supported at this horizon.")
            continue
        lines.append(f"  Win rate observed in similar cases: {_fmt_pct(s.get('win_rate'))}")
        lines.append(f"  Median return in similar cases: {_fmt_pct(s.get('median_return'))}")
        lines.append(f"  Unconditional base rate over the same history: {_fmt_pct(s.get('base_rate'))}")
        lines.append(f"  Difference from base rate: {_fmt_pp(s.get('edge_pp'))}")

    if data.divergences:
        lines.append("")
        lines.append("DIVERGENCES OBSERVED")
        for d in data.divergences:
            lines.append(f"- {d}")

    lines.append("")
    lines.append("RISKS / CONTRADICTIONS")
    if data.contradictions:
        for c in data.contradictions:
            lines.append(f"- {c}")
    else:
        lines.append("- None flagged by the rules currently configured.")

    lines.append("")
    lines.append("CONCLUSION")
    lines.append(
        "This is a description of a historical statistical pattern, not a price "
        "prediction and not a trading signal. Historical evidence suggests the "
        "listed differences from base rate; it does not establish that the "
        "current positioning CAUSES any particular price outcome, and past "
        "patterns are not guaranteed to repeat."
    )
    return "\n".join(lines)


_NUMBER_RE = re.compile(r"-?\d+\.\d+|-?\d+")


def assert_no_fabricated_numbers(analysis_text: str, data: AnalysisInput) -> list[str]:
    """
    Defense-in-depth self-check (used in tests and optionally at call time):
    extracts every numeric token from the generated text and verifies each
    one traces back to something in `data`. Returns a list of numbers that
    could NOT be traced (empty list == clean). This is a heuristic guard,
    not a formal proof -- see METHODOLOGY.md for that caveat.
    """
    allowed_numbers = set()
    for h, s in data.horizon_stats.items():
        allowed_numbers.add(str(h))
        for key in ("n", "win_rate", "median_return", "base_rate", "edge_pp"):
            v = s.get(key)
            if v is None:
                continue
            if key in ("win_rate", "median_return", "base_rate"):
                allowed_numbers.add(f"{v*100:.1f}")
            elif key == "edge_pp":
                allowed_numbers.add(f"{v:+.1f}".lstrip("+"))
                allowed_numbers.add(f"{v:.1f}")
            else:
                allowed_numbers.add(str(v))

    # regime_reasons / contradictions / divergences are free-text fields
    # supplied directly in `data` (not computed by this module) -- any
    # numbers embedded in them (e.g. "(actual: 8)") are legitimately part
    # of the input the AI was given, so they belong in the allow-list too.
    for free_text in (data.regime_reasons, data.contradictions, data.divergences):
        for line in free_text:
            allowed_numbers.update(_NUMBER_RE.findall(line))

    found_numbers = set(_NUMBER_RE.findall(analysis_text))
    untraceable = [n for n in found_numbers if n not in allowed_numbers and n not in ("1", "2", "3", "4", "5", "6", "7", "8", "9")]
    return untraceable


def polish_with_llm(analysis_text: str, data: AnalysisInput) -> str:
    """
    NOT wired up / not exercised in this build -- see AI.md. Documented
    contract for a future implementation: call an LLM with `analysis_text`
    and the SAME `data` dict, instructing it to rephrase for fluency only,
    with an explicit instruction that it must not introduce, alter, or drop
    any number, and validate the response with
    `assert_no_fabricated_numbers` before showing it to the user -- if that
    check fails, fall back to `analysis_text` unchanged rather than show
    unverified prose.
    """
    raise NotImplementedError(
        "LLM polish is an optional, documented extension point (see AI.md) -- "
        "not implemented in this build. generate_analysis() output is used as-is."
    )
