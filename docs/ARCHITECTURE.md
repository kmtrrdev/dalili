# Dalili - Architecture (after the upgrade)

Principle: **the LLM reasons, interprets and explains; deterministic code guarantees; optimisation allocates;
tools supply real-world facts; retrieval grounds knowledge; the recommender personalises; validators verify; the
critic improves without overriding.** No model output is the final authority on anything code can check.

```
 traveller (web / mobile)
      |  REST + SSE  (request id, rate limits, CSP/HSTS, size caps)                       api.py, security.py
      v
 service.py ── preference memory (stated vs inferred, evidence, decay)                     preferences.py
      |        what-if impact (every plan, constraints, incremental vs full)              whatif.py
      v
 workflow.py (LangGraph)
  understand ──> nlu / concierge agent (LLM: intent, requirements incl. must vs wish, priorities)
      |            replanner.apply_requirements (deterministic edits, evidence per field)
      v
  contract  ──> TripContract + typed Constraints (priority / source / confidence / evidence)  constraints.py
      v
  research  ──> MCP hub (8 servers, timeouts, bounded cache) -> providers -> net.py
      |           (SSRF-safe fetch, true fetch time + stale flag, FX with fallback source)
      |         data_quality.check (coordinates, duplicates, outlier prices)
      |         pricing cascade: Google -> official site -> web menu -> Wikivoyage -> AI estimate (labelled)
      v
  plan      ──> strategist (LLM: per-mode strategy, hotel shortlists per city, signature experiences)
      |         planner (deterministic): joint flights+hotel objective weighted by mode AND traveller priorities,
      |         day assignment, OR-Tools VRPTW per day, timelines              engine/planner.py, optimizer.py
      v
  validate  ──> 9 deterministic checks: budget, schedule, distance, opening hours, preferences (incl. unverifiable
      |         dietary), energy (vs agreed capacity), weather, reality (every hotel/leg), freshness
      v
  repair    ──> knob ladder (currency-safe) ; before/after accountability: a repair that adds problems is reverted
      v
  finalize  ──> hierarchical TripScore (feasible > requirements > preferences > quality) ; conflicts.analyze:
      |         infeasible requirements -> ranked, priced relaxations (offered, never applied)   conflicts.py
      v
  critic    ──> LLM review -> only whitelisted, grounded fixes (never learned as the traveller's taste) ->
      |         multi-objective acceptance (no new violations, requirements/preferences not worse, no lost icons)
      v
  respond   ──> narrative (LLM, from a facts JSON: trust split, conflicts, constraints, plan comparison)
                telemetry: per-turn model calls/tokens/cost, tool calls, live searches, latency    telemetry.py

 recommender/  fine-tuned MiniLM taste (trips, likes, searches, decay) -> "For you" + hybrid trip ideas (suggest.py)
 evaluation    eval/run_eval.py (scenarios) · eval/benchmark.py (planners) · eval/ablation.py (A-F)
               human ratings: /api/evaluations (anonymous, CI + Welch summary)                 evaluation.py
```

## Where each kind of logic lives

| Kind | Used for |
|---|---|
| LLM | understanding messages (intent, requirements, must vs wish, priorities), mode strategies and hotel shortlists, critique, explanations, menu-price reading from quoted sources |
| Deterministic | contract and constraints, all money math and FX, feasibility, validation, repair, scoring, conflict search, provenance |
| Optimisation | joint flight+hotel choice under the budget; per-day routing with opening windows (OR-Tools) |
| Retrieval | Wikivoyage guide sections (tips, tariffs, local prices), concierge answers |
| MCP tools | every real-world fact: flights, hotels, places, hours, prices, routes, weather, FX |
| Recommender | long-term taste for destinations and trip ideas |
| User confirmation | any relaxation of a requirement (budget, dates, hotel class), what-if application |
