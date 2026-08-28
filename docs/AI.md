# The AI layer

The brief's requirement (§38) was unambiguous: the quant engine computes, the AI
explains. The AI may not calculate statistics, invent figures, alter computed
values, assert causation, or turn an extreme percentile into a trading signal.

That is enforced structurally, not by instruction.

---

## How it works

`generate_analysis()` takes an `AnalysisInput` — market, regime, the reasons the
regime fired, per-horizon statistics computed by the quant engine, divergences,
contradictions — and interpolates those values into a fixed template.

**There is no code path in it that computes or generates a number.** It cannot
hallucinate a figure because it has no mechanism for producing one. Everything
it prints was handed to it.

This is deliberately a template rather than an LLM call by default: fully
deterministic, fully auditable, zero network dependency, and testable.

---

## The fabrication check

`assert_no_fabricated_numbers()` extracts every numeric token from the generated
text and verifies each traces back to something in the input: horizon labels,
computed statistics, or numbers embedded in the free-text fields the caller
supplied.

`tests/test_ai_analyst.py` runs this on generated output **and** includes a
control test that injects a fake number ("the true win rate is 99.9%") and
asserts the checker catches it — so the test proves the checker works, not just
that it stays quiet.

It is a heuristic guard, not a formal proof. It is a second line of defence
behind the structural one.

---

## Language rules

The output uses evidence-framed language:

- "Historical evidence suggests…"
- "Observed in X of Y cases…"
- "The statistical edge was…"
- "Sample size is…"

And never:

- "Buy EUR" / "Sell GBP"
- "COT predicts price"
- "Price will rise"
- "This proves / guarantees"
- "AI thinks EUR is bullish"

A test asserts the forbidden phrases never appear.

Every analysis closes by stating that it describes a historical statistical
pattern, not a prediction, and that it does not establish causation.

Any horizon whose sample is below the minimum prints "Insufficient sample size —
no directional claim is supported at this horizon" **instead of** its numbers.

---

## Optional LLM polish — documented, not implemented

`polish_with_llm()` exists as a documented extension point and raises
`NotImplementedError`. It is not wired up in this build.

If you implement it, the contract it must respect:

1. Send the generated text **and** the same stats dict.
2. Instruct the model to rephrase for fluency only — it must not introduce,
   alter, or drop any number.
3. Run `assert_no_fabricated_numbers()` on the response.
4. **If that check fails, fall back to the deterministic text unchanged.** Never
   show unverified prose.

API keys via `.env` / environment variables, never in code. Send only the
computed summary, never raw user data (§59).

---

## What the AI layer is for

Structuring what the numbers say, surfacing contradictions between participants
or between positioning and price, and stating plainly when the evidence is too
thin to support a claim.

It is the last layer, and the least authoritative one. The quant engine is the
source of truth.
