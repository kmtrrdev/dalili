# Dalili — Architecture Audit (Phase 1)

Date: 2026-10-05. Scope: the whole repository (backend `travel_agent/`, `frontend/`, `mobile/`, `eval/`, `ml/`, CI).
Method: four parallel read-only audits (orchestration/agents, planning engine, data/MCP/provenance,
API/security/recommender/evaluation), every finding traced to file:line. This document records what exists today,
what is wrong, and which proposed changes were adopted or rejected — and why.

## 1. Architecture map

```
                     ┌──────────── frontend (web) / mobile (Flutter, Shorebird OTA) ────────────┐
                     │  chat · plan cards · map · Trip Book · auth · recommendations            │
                     └───────────────────────────────┬──────────────────────────────────────────┘
                                                     │ REST + SSE (FastAPI, api.py)
                       auth.py (scrypt, hashed session tokens) · store.py/db.py (SQLite | Postgres)
                                                     │
                                 service.py — sessions, what-if settle, mode selection
                                                     │
 ┌────────────────────────────── workflow.py (LangGraph) ──────────────────────────────────────┐
 │ understand ─► (route design) ─► research fan-out ─► collect ─► enrich ─► plan ─► validate   │
 │      │                                                                   ▲          │        │
 │  agents/concierge (ReAct: plan_lookup, nearby, weather, directions,      │     repair ◄┘       │
 │  currency, guide, flights, change_plan, what-if)                         │                    │
 │  nlu.interpret (LLM)  replanner (deterministic edits)       finalize ─► critic ─► re-plan     │
 │  agents/strategist (4 mode strategies)                      narrative (LLM reply, templates)  │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
          │ MCPHub (8 in-memory MCP servers, 900 s result cache)
   flights · hotels · places · activities · maps · weather · currency · knowledge
          │ providers/* ─► net.py (SQLite HTTP cache, replay mode, SerpApi per-turn cap, fetch_page)
   SerpApi (Google Flights/Hotels/Maps/Search) · ORS · Geoapify · Open-Meteo · Wikivoyage · FX · web pages
          │ fallbacks: providers/ai_fallback (labelled "ai_knowledge" / price_type "estimated")

 engine/: planner (joint flight+hotel under budget, day slots, timelines) · optimizer (OR-Tools VRPTW per day,
          greedy fallback) · ranking (scorers) · validators (8 deterministic checks) · repair (knob ladder)
          · scoring (TripScore) · budget · knobs        journey.py: multi-city (chained single-city plans)
 recommender/: NumPy Doc2Vec (PV-DBOW) over 227 Wikivoyage guides + interaction-weighted taste vector
 eval/run_eval.py: 26 replayed end-to-end scenarios, 13 metrics
```

### Responsibility split today

| Concern | Who decides | Kind |
|---|---|---|
| Understanding the message | `nlu.interpret`, concierge agent | LLM (rules parser only in tests/eval) |
| Mode strategies, hotel shortlists, signature experiences | `agents/strategist` | LLM, bounded by code (stretch clamp, shortlist must exist) |
| Flights + hotel choice, day assignment, timelines | `engine/planner` | deterministic |
| Daily stop order with opening windows | `engine/optimizer` | OR-Tools (1 s), greedy fallback |
| Feasibility | `engine/validators` | deterministic |
| Fixes | `engine/repair` → knobs → rebuild | deterministic |
| Expert review | `agents/critic` | LLM proposes; only whitelisted, grounded fixes auto-apply |
| Prices | cascade: Google → official site → web menu → Wikivoyage → AI estimate | mixed, labelled |
| Reply text | `narrative` | LLM from a facts JSON; templates without LLM |

## 2. Findings (selected; full evidence in the audit transcripts)

### Correctness
1. Currency mixing: repair and knob price caps compare raw `.amount` across currencies (repair.py:132-161, planner.py:214/514); missing FX silently becomes 1.0 (budget.py:13, planner.py:115); one missing currency fails the whole FX call and every currency is then treated 1:1 (currency.py:23, research.py:248).
2. Redistribution of activities ignores repair knobs (planner.py:654-670) — repairs can be undone, causing repair loops.
3. The energy validator ignores per-day capacity overrides and mode density (validators.py:192) — "pack more into day 2" triggers an error that repair then reverts.
4. A must-include evening place can be overwritten (planner.py:681-686); activities assigned to a post-midnight arrival day vanish silently (planner.py:430, 1089-1111).
5. Comfort mode orders stops on transit times but schedules them with taxi times (planner.py:721 vs 972).
6. Multi-city: budget shares double-count inner legs (journey.py:263); only the first city's hotel is reality/noise-checked (journey.py:280).
7. TripScore is a fixed weighted sum where hard errors cost a few points — a FAIL plan can outrank a PASS plan (scoring.py:92-98, workflow.py:711).
8. Repair never compares before/after; it can oscillate or make things worse (workflow.py:645-665).
9. Critic auto-fixes write into the user's long-term profile (replanner via service.py:36); each saved trip overwrites the user profile.
10. `Metadata.retrieved_at` is parse time, not fetch time (models.py:65) — cached 30-day-old data looks fresh.
11. A failed return-flight search discards the live outbound results (mcp_servers/flights.py:27-41); Wikivoyage being down fails the whole turn (workflow.py:408); a failed research branch silently reuses the previous trip's research (workflow.py:439).
12. `MCPHub.call` has no timeout (mcp_hub.py:78).

### Provenance / trust
- No UNKNOWN price type; LLM-computed menu meals are labelled `range` (shown as a published price); `hours_verified` defaults to True; outdoor places get 24 h "verified" hours; missing ratings default to 4.0 and AI places get invented review counts.

### Security (no critical issues; strong auth, ownership checks, CSRF origin check)
- HIGH: XSS via Leaflet tooltips with unescaped place names (app.js:485-503, book.js:83-89); no CSP.
- HIGH: no rate limits or message-size caps on chat/suggest/replan/what-if (LLM + SerpApi cost abuse).
- HIGH: `--forwarded-allow-ips "*"` lets clients spoof their IP and bypass the per-IP login limit (Dockerfile:28).
- MEDIUM: `javascript:` URLs not blocked in links; SSRF in `fetch_page` (no DNS/redirect re-check); unbounded recommender inference; information disclosure on /api/health, /api/quota, /api/mcp/tools and raw provider errors in trip JSON; no HSTS.
- LOW: global SSE listener leaks tool-call events across users; process-global SerpApi turn counter; unbounded in-memory caches; prompt-injection framing missing for fetched pages.

### Preferences / personalization
- `LearnedPreference{value, confidence, evidence}` — no timestamps, decay, evidence counts or source type; stated preferences are stored as "learned"; `reduce_density` does not learn while `increase_density` does; `preferred_mode` is learned but unused.
- Doc2Vec powers only "For you"/"similar"; trip-idea suggestions ignore it.

### Evaluation
- `eval/run_eval.py`: 26 replayed scenarios — but the reported run used the rules parser, not the LLM; no ablation, no planner baselines, no variance.

### Hardcoded values
About 120 constants were classified. Most are reasonable **fallbacks** (meal durations, airport processing, detour
factors, default fares) used only when data is missing. The ones that are genuine **travel assumptions** and should
follow the traveller/trip: day capacity by pace, walking limits, hotel distance cut-offs, flight time-of-day
cut-offs, two people per room default, one-size airport time, 4 people per taxi.

## 3. Decisions on the proposed upgrade

Adopted (convinced they add correctness, grounding or measurable value):
- Fix every correctness bug above; security hardening (CSP, escaping, URL allow-list, SSRF, rate limits, disclosure).
- Hierarchical TripScore: feasibility gates quality — a plan with hard violations never outranks a valid one.
- Repair with before/after tracking: a repair that adds violations or loses coverage is rejected.
- Typed constraints in the contract (priority HARD/SOFT/PREFERENCE, source explicit/inferred, evidence) derived
  from what the traveller actually said — "must visit" vs "would like to".
- Provenance: VERIFIED / CALCULATED / ESTIMATED / UNKNOWN applied consistently, true fetch time, budget split by
  provenance class, conflicts kept.
- Long-term preferences with explicit vs inferred separation, evidence counts and time decay.
- Conflict resolution for infeasible budgets: deterministic, ranked relaxation options computed from the research
  already done (cost and impact of each), offered to the traveller — never applied silently.
- Unified what-if (chat and API) showing cost/score/validity/constraint changes for every plan.
- Evaluation: ablation harness and planner benchmark on identical replayed scenarios; human-evaluation endpoint
  with anonymous storage and reproducible statistics.
- Observability: request ids, structured per-turn traces (tool calls, latency, retries, token usage).

Rejected or reduced (not convinced):
- "No constants at all": impossible without data for every fact; instead travel assumptions now follow context
  (pace, walking tolerance, party size, flight type, hotel data) and the remaining fallbacks are named and documented.
- A separate "Digital Twin" layer: `TripState` already is the single structured state every change operates on;
  a second model would duplicate it. It is strengthened instead (constraints, provenance).
- Asking confirmation for every inferred preference: it would make the chat tiring. Inferred assumptions are
  shown in the reply and can be overridden; only plan-changing relaxations require confirmation.
- Plugging Doc2Vec into attraction ranking: it is trained on destination guides, not attractions — the signal would
  be noise. It is used where it fits: destination ideas.
- Numeric "confidence" on every decision: only where evidence exists (price provenance, weather source,
  data completeness). No fabricated scores.

## 4. What was implemented (Phases 2-10)

| Phase | Change | Main files |
|---|---|---|
| 2 Correctness | currency-safe caps and comparisons; FX second source + reported gaps; redistribution respects repairs; requested evenings never overwritten; post-midnight arrivals; stop order and schedule on the same legs; energy checked against each day's agreed capacity; every city's hotel and every leg reality-checked; independent flight directions; Wikivoyage outage no longer fatal; no reuse of other dates' research; MCP timeouts and bounded caches; critic refinement compared on the same strategies | engine/*, net.py, providers/currency.py, research.py, workflow.py, mcp_hub.py |
| 3 Constraints | typed `Constraint` (priority hard/soft/preference/nice-to-have, source explicit/inferred/learned/default, confidence, flexibility, evidence); "must" vs "if there's time" places; stated priorities | constraints.py, models.py, nlu.py, replanner.py |
| 4 Conflicts | infeasibility detection, atomic relaxations priced from existing research, combination search, ranking by experience loss + priority of bent constraints + the traveller's priorities, confirmation required | conflicts.py |
| 5 Trust | verified / calculated / estimated / unknown on every price; budget split by trust with evidence-based confidence; real fetch time and stale flag; price conflicts kept; menu meals labelled calculated | models.py, engine/budget.py, pricing.py, net.py |
| 6 Personalization | preference memory (stated vs inferred, evidence counts, contradiction, half-life decay; only memory saved to the account); hybrid trip ideas (request fit + Doc2Vec taste) | preferences.py, service.py, suggest.py, recommender/engine.py |
| 7 Scoring / critic | hierarchical TripScore (feasible > requirements > preferences > quality; no hard violation above 49); weights follow the plan and the traveller's priorities (also in the flight+hotel objective); multi-objective critic acceptance | engine/scoring.py, engine/planner.py, workflow.py |
| 8 What-if / repair | one comparison for chat and API (every plan, validity, requirements, constraint changes, incremental vs full replanning); repair before/after tracking with automatic revert | whatif.py, service.py, workflow.py |
| 9 Evaluation | planner benchmark, ablation A-F, human-evaluation endpoint + statistics, data-quality gate, freshness and unverifiable-dietary checks | eval/*, evaluation.py, data_quality.py, engine/validators.py |
| 10 Security / ops | CSP with script hashes, HSTS, escaped tooltips, http(s)-only links, SSRF-safe fetch, rate limits, size caps, unforgeable client IP, operator-only details, prompt-injection framing, turn-scoped events; request ids, structured logs, per-turn tokens/cost/tools | api.py, security.py, net.py, telemetry.py, models.py |

## 5. Tests added

test_correctness, test_preferences, test_constraints, test_scoring, test_whatif_repair, test_security,
test_human_eval, test_data_quality, test_benchmark, plus SSRF/provenance cases in test_net and affinity/blending in
test_recommender. Suite: 212 passed, 2 skipped (offline, replayed real data).

## 6. Evaluation

See `eval/EVALUATION.md` (all numbers from real runs): Dalili had 0 hard violations in 6/6 benchmark scenarios vs
1.5-4 for baselines and 2.3 for the LLM planner; the ablation shows MCP data is what grounds the plan and the
optimizer + validators are what make it feasible (C: 18.7 violations -> E: 1.2 -> F: 0).

## 7. Remaining limitations

- Multi-city legs are chosen city by city. Legs are on fixed dates and independent, so this is cost-optimal for
  the legs; it is not a joint optimisation of legs with each city's hotel/time trade-offs.
- Confidence is evidence-based but not calibrated against outcomes (no ground truth for estimated prices).
- No accessibility or age data model: the planner cannot reason about mobility needs or children yet.
- Dietary checks are verifiable only for vegetarian/vegan (what providers tag); others are flagged, not checked.
- Rate limits are per process (in memory); multiple replicas each enforce their own window.
- Benchmark/ablation: 6 scenarios in 2 cities; human evaluation has no ratings yet.
- In AI-fallback mode (live search down), estimated places carry estimated review counts that influence ranking.

## 8. Future research directions

Calibrating price confidence on published-vs-estimated pairs; joint multi-city optimisation (legs + stays) as one
model; learning the TripScore weights from human ratings (the endpoint stores both); counterfactual explanations
("you would get X if the budget were Y") from the conflict search; larger recorded benchmark across regions.

## 9. Assumptions and defaults still in the code

Configurable fallbacks (documented where defined): budget buffer 5% (`TRAVEL_AGENT_BUDGET_BUFFER`), preference
threshold 0.5 / half-life 180 days, MCP timeout 150 s, rate limits (`DALILI_*`), LLM prices for the cost estimate.
Travel fallbacks used only when data is missing: meal durations and windows, airport processing times, detour
factors and default fares, assumed opening hours by place type, 2 travellers per room when rooms are not stated,
category price levels. Strategy defaults when no model is available (`strategist.DEFAULTS`). Conflict-ranking and
hybrid-recommender weights are ranking heuristics (documented in conflicts.py / suggest.py), applied to computed
quantities.
