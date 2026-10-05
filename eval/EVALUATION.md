# Dalili - Evaluation

All numbers below come from runs of the scripts in this folder on **recorded real API responses**
(`tests/fixtures/http_cache.sqlite`, replayed offline), so every configuration sees exactly the same flights,
hotels, places, opening hours, prices and travel times. Model-based configurations used **gpt-5-mini** (Azure).
Generated 2026-10-05. Re-run: `python eval/run_eval.py`, `python eval/benchmark.py [--llm]`, `python eval/ablation.py`.

Scenarios (benchmark and ablation): Rome 7 days and Istanbul 7 days, each as asked, with a faster pace, and with a
budget cut to 55% - 6 scenarios. Small by design (each costs real data to record); results are means over them.

## 1. Scenario suite (`run_eval.py`, 26 end-to-end scenarios, 60 plans audited)

| Metric | Value |
|---|---|
| scenarios passed | 26/26 |
| constraint satisfaction (hard checks on every plan) | 99.2% |
| schedule feasibility | 100% |
| budget accuracy (recomputed vs reported) | 100% |
| tool selection accuracy | 85.7% |
| grounded recommendations | 98.3% |
| reality violations | 0% |
| injected-violation detection | 100% |
| replanning success | 100% |
| cost backed by published prices | 62.7% |
| scheduled places with verified hours | 90.4% |

Understanding in this suite uses the offline keyword parser (no model), so it measures the planning stack, not the
language model.

## 2. Planner benchmark (`benchmark.py --llm`)

Same activities per day for every planner (from the traveller's pace); same validators and scorer.

| planner | hard violations | feasible | travel min | km / hop | cost | within budget | landmarks | pref. fit | TripScore | compute ms |
|---|---|---|---|---|---|---|---|---|---|---|
| random (5 seeds) | 4.03 | 3% | 916 | 5.31 | 1876 | 77% | 0.69 | 0.54 | 50.0 | 2 |
| greedy | 1.67 | 33% | 683 | 2.50 | 1560 | 83% | 1.00 | 0.59 | 61.3 | 2 |
| OR-Tools (greedy choice + optimizer) | 1.50 | 33% | 657 | 2.39 | 1557 | 83% | 1.00 | 0.59 | 61.3 | 63 |
| LLM (picks from candidates) | 2.33 | 0% | 738 | 4.38 | 1568 | 83% | 0.97 | 0.59 | 49.0 | 12,101 |
| **Dalili** | **0.00** | **100%** | 695 | **2.02** | 1647 | **100%** | 1.00 | 0.59 | **81.3** | 87 |

Reading: ordering alone (OR-Tools) shortens travel but cannot fix choices made without opening hours or the budget
in mind; the LLM picks reasonable places but scatters them (km/hop 4.38) and breaks opening hours (7 of its 14
violations) and schedules; Dalili is the only one
with no hard violations in every scenario, the shortest hops, and every plan within budget - at a slightly higher
cost (it fits its days fully) and ~0.1 s of compute (vs ~12 s for the LLM planner). The LLM row varies between runs
(an earlier run of the same command gave 1.00 violations and 17% feasible); the table shows the run saved in
`benchmark_results.json`.

## 3. Ablation (`ablation.py`)

| config | ungrounded items¹ | hard violations | feasible | budget error² | grounded items | landmarks | TripScore | latency ms | LLM calls | tokens | LLM cost $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A. LLM only | 0.84 | 6.67 | 0% | (1.01) | 0.16 | 0.63 | 49.0 | 24,863 | 1 | 4,269 | 0.01 |
| B. LLM + retrieval | 0.80 | 6.83 | 0% | (0.80) | 0.20 | 0.73 | 49.0 | 23,909 | 1 | 5,133 | 0.01 |
| C. LLM + MCP | 0.18 | 18.67 | 0% | 0.15 | 0.82 | 0.90 | 48.7 | 31,287 | 1 | 15,768 | 0.01 |
| D. C + validation feedback | 0.16 | 13.50 | 0% | 0.10 | 0.84 | 1.00 | 49.0 | 62,017 | 2 | 35,067 | 0.02 |
| E. LLM + MCP + optimizer | - | 1.17 | 17% | 0.00 | 1.00 | 0.93 | 55.0 | 11,587 | 1 | 9,272 | 0.00 |
| **F. Full Dalili** | **0.00** | **0.00** | **100%** | **0.00** | 0.96³ | **1.00** | **81.3** | **93** | 0 | 0 | 0.00 |

¹ Share of named itinerary items that match no researched place. It includes generic entries ("a classic Roman
trattoria", "relax at the hotel"), so for A/B it measures *untraceable to real data* rather than strict hallucination.
² |claimed total - real total of the same plan| / real total. For A/B the hotel and flights cannot be matched to real
offers, so the real total is incomplete - their value is shown in brackets and should not be compared.
³ The remainder are breakfasts at the hotel (included in the room rate): tied to the grounded hotel, not to a separate place.

What each component contributes (from the table):
- **MCP data (A/B -> C):** grounding rises from 16-20% to 82%, budget error falls to 15% - real facts, but the model
  still schedules badly (most violations are schedule overlaps and opening hours; plus preference errors such as
  non-vegetarian restaurants).
- **Validation feedback (C -> D):** one revision round with the validators' findings cuts violations by 28% at twice
  the tokens and latency - still never feasible. A model told what is wrong still does not reliably fix it.
- **Optimizer (C -> E):** letting OR-Tools order and time the days removes most violations (18.7 -> 1.2) - timing
  is a constraint problem, not a language problem.
- **Full Dalili (F):** deterministic planning + validation + repair: no violations in any scenario, every plan
  grounded and costed, over 100x faster than the model configurations, no model cost for planning.

## 4. Human evaluation

`POST /api/evaluations` (the "Rate this plan" button) stores anonymous 1-5 ratings on relevance, personalization,
trust, explanations, itinerary, usability, confidence and overall, together with the rated plan's measured metrics.
`GET /api/evaluations/summary` (operator) gives per-variant means with 95% CIs, Welch differences between variants and
the TripScore-vs-overall correlation. **No human ratings have been collected yet** - this needs real users.

## 5. Not measured (honest gaps)

- Confidence calibration against ground truth: there is no ground truth for prices the system estimates; the price
  confidence is evidence-based (share of verified/calculated/estimated/unknown cost) but not yet calibrated.
- Language understanding with the model on the scenario suite (it uses the offline parser for reproducibility).
- Scale: 6 benchmark scenarios in 2 cities; more cities need more recorded data.
