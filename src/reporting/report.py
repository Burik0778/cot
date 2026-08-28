"""
src/reporting/report.py

Spec section 49: GENERATE REPORT. Assembles a complete research report from
values the quant engine already computed. Like the AI layer, this module
never computes a statistic itself -- it formats what it is given, so a
report can never disagree with the analysis it came from.

Formats: Markdown and self-contained HTML. PDF is NOT implemented in this
build (see docs/LIMITATIONS.md) -- `reportlab` is available if you want to
add it, but shipping a half-working PDF path would be worse than saying
plainly that it isn't here.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional
import html


@dataclass
class ReportInput:
    market: str
    pair_symbol: str
    report_date: str
    availability_date: str
    availability_source: str
    is_synthetic: bool
    regime: str
    regime_reasons: list[str]
    participant_rows: list[dict]      # [{participant, net, net_oi, pct_52w, z_52w, chg_4w}, ...]
    price_close: Optional[float]
    price_changes: dict               # {"4w": .., "8w": .., "12w": ..}
    n_analogs: int
    top_analogs: list[dict]           # [{report_date, similarity_score, distance}, ...]
    horizon_stats: dict               # {h: {n, win_rate, median_return, base_rate, edge_pp, sample_quality, ...}}
    divergences: list[str]
    contradictions: list[str]
    ai_analysis: str
    hypotheses_tested: Optional[int] = None


def _pct(x, digits=1):
    return "N/A" if x is None else f"{x*100:.{digits}f}%"


def _num(x, digits=3):
    return "N/A" if x is None else f"{x:,.{digits}f}"


def build_markdown(data: ReportInput) -> str:
    L = []
    L.append(f"# COT Research Report — {data.pair_symbol}")
    L.append("")
    if data.is_synthetic:
        L.append("> **DEMO / SYNTHETIC DATA.** Every figure below was computed from generated "
                 "test data, not real market information. Do not use or share this as analysis.")
        L.append("")
    L.append(f"- **Market:** {data.market} ({data.pair_symbol})")
    L.append(f"- **Report date (Tuesday positioning):** {data.report_date}")
    L.append(f"- **Availability date (when actionable):** {data.availability_date} "
             f"_(source: {data.availability_source})_")
    L.append(f"- **Generated:** {date.today().isoformat()}")
    L.append("")

    L.append("## Current state")
    L.append("")
    L.append(f"**Regime: {data.regime}**")
    L.append("")
    L.append("Conditions that fired:")
    for r in data.regime_reasons:
        L.append(f"- {r}")
    L.append("")

    L.append("### Price")
    L.append("")
    L.append(f"- Close: {_num(data.price_close, 4)}")
    for k in ("4w", "8w", "12w"):
        L.append(f"- {k.upper()} change: {_pct(data.price_changes.get(k), 2)}")
    L.append("")

    L.append("### Participant positioning")
    L.append("")
    L.append("| Participant | Net | Net/OI | 52W %ile | 52W Z | 4W change |")
    L.append("|---|---|---|---|---|---|")
    for row in data.participant_rows:
        L.append(f"| {row.get('participant')} | {_num(row.get('net'), 0)} | {_pct(row.get('net_oi'))} | "
                 f"{_num(row.get('pct_52w'), 1)} | {_num(row.get('z_52w'), 2)} | {_num(row.get('chg_4w'), 0)} |")
    L.append("")

    if data.divergences:
        L.append("### Divergences observed")
        L.append("")
        for d in data.divergences:
            L.append(f"- {d}")
        L.append("")

    L.append("## Historical analogs")
    L.append("")
    L.append(f"Analogs found: **{data.n_analogs}**")
    L.append("")
    if data.top_analogs:
        L.append("| Date | Similarity score | Distance |")
        L.append("|---|---|---|")
        for a in data.top_analogs:
            L.append(f"| {a.get('report_date')} | {_num(a.get('similarity_score'), 1)} | {_num(a.get('distance'), 3)} |")
        L.append("")
        L.append("_Similarity score is a documented bounded transform of standardized distance "
                 "(see docs/METHODOLOGY.md). It is not a probability._")
        L.append("")

    L.append("## Outcomes vs base rate")
    L.append("")
    L.append("| Horizon | N | Win rate | Median return | Base rate | Edge (pp) | Sample quality |")
    L.append("|---|---|---|---|---|---|---|")
    for h in sorted(data.horizon_stats.keys()):
        s = data.horizon_stats[h]
        if s.get("sample_quality") == "Insufficient sample size":
            L.append(f"| {h}W | {s.get('n')} | — | — | — | — | Insufficient sample size |")
            continue
        edge = s.get("edge_pp")
        L.append(f"| {h}W | {s.get('n')} | {_pct(s.get('win_rate'))} | {_pct(s.get('median_return'), 2)} | "
                 f"{_pct(s.get('base_rate'))} | {'N/A' if edge is None else f'{edge:+.1f}'} | {s.get('sample_quality')} |")
    L.append("")

    L.append("## Statistical validity")
    L.append("")
    for h in sorted(data.horizon_stats.keys()):
        s = data.horizon_stats[h]
        ci = s.get("bootstrap_ci_median")
        bits = []
        if ci:
            bits.append(f"bootstrap 95% CI for median: [{ci[0]*100:.2f}%, {ci[1]*100:.2f}%]")
        if s.get("binomial_p_value") is not None:
            bits.append(f"binomial p={s['binomial_p_value']:.3f}")
        if s.get("permutation_p_value") is not None:
            bits.append(f"permutation p={s['permutation_p_value']:.3f}")
        if s.get("cohens_d") is not None:
            bits.append(f"Cohen's d={s['cohens_d']:.2f}")
        if bits:
            L.append(f"- **{h}W:** " + " · ".join(bits))
    L.append("")
    L.append("> Weekly observations with multi-week horizons overlap heavily, so effective sample "
             "size is smaller than N and every p-value above is optimistic. See docs/STATISTICS.md.")
    L.append("")
    if data.hypotheses_tested and data.hypotheses_tested > 20:
        L.append(f"> **Potential multiple-testing bias:** {data.hypotheses_tested} conditions have been "
                 f"tested in this session. Some will look significant by chance alone.")
        L.append("")

    L.append("## Risks and contradictions")
    L.append("")
    if data.contradictions:
        for c in data.contradictions:
            L.append(f"- {c}")
    else:
        L.append("- None flagged by the rules currently configured.")
    L.append("")

    L.append("## Interpretation")
    L.append("")
    L.append("```")
    L.append(data.ai_analysis)
    L.append("```")
    L.append("")

    L.append("---")
    L.append("")
    L.append("**This report describes a historical statistical pattern. It is not a price "
             "prediction, not a trading signal, and does not establish causation. Past "
             "positioning patterns are not guaranteed to repeat.**")
    return "\n".join(L)


def build_html(data: ReportInput) -> str:
    """Self-contained HTML, no external assets, readable in any browser."""
    md = build_markdown(data)
    body_lines = []
    in_table = False
    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if not in_table:
                body_lines.append("<table>")
                in_table = True
            tag = "th" if len(body_lines) and body_lines[-1] == "<table>" else "td"
            body_lines.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            body_lines.append("</table>")
            in_table = False
        if stripped.startswith("# "):
            body_lines.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            body_lines.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            body_lines.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("> "):
            body_lines.append(f"<blockquote>{html.escape(stripped[2:])}</blockquote>")
        elif stripped.startswith("- "):
            body_lines.append(f"<li>{html.escape(stripped[2:])}</li>")
        elif stripped == "```":
            body_lines.append("<pre>" if "<pre>" not in "".join(body_lines[-40:]) else "</pre>")
        elif stripped:
            body_lines.append(f"<p>{html.escape(stripped)}</p>")
    if in_table:
        body_lines.append("</table>")

    style = """body{max-width:860px;margin:40px auto;padding:0 20px;background:#0b0e14;color:#e6e9ef;
font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif}
h1{font-size:22px}h2{font-size:16px;color:#8b93a3;text-transform:uppercase;letter-spacing:.04em;margin-top:28px}
h3{font-size:14px}table{width:100%;border-collapse:collapse;margin:12px 0;background:#141922;border:1px solid #232a37}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid #232a37;font-size:13px}
th{color:#8b93a3;font-weight:500}blockquote{border-left:3px solid #d8a13a;margin:12px 0;padding:6px 14px;color:#c9a86a;background:#1a1710}
pre{background:#141922;border:1px solid #232a37;padding:14px;overflow-x:auto;white-space:pre-wrap;font-size:12px}
li{margin:3px 0}"""
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>COT Research Report — {html.escape(data.pair_symbol)}</title>"
            f"<style>{style}</style></head><body>{''.join(body_lines)}</body></html>")
