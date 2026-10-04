# Evaluation report

Real API responses (recorded) - see eval/run_eval.py.

| Metric | Value |
|---|---|
| scenarios_passed | 26/26 |
| requirement_handling | 100.0% |
| constraint_satisfaction_rate | 99.0% |
| schedule_feasibility | 100.0% |
| budget_accuracy | 100.00% |
| tool_selection_accuracy | 85.7% |
| grounded_recommendation_rate | 100.0% |
| reality_violation_rate | 0.00% |
| injected_violation_detection_rate | 100.0% |
| replanning_success_rate | 100.0% |
| preference_satisfaction | 100.0% |
| cost_backed_by_published_prices | 50.0% |
| scheduled_places_with_verified_hours | 85.8% |
| avg_turn_latency_ms (replay) | 563 |
| p95_turn_latency_ms (replay) | 1467 |
| plans_audited | 60 |
| total_runtime_s | 12.1 |
| data | recorded real API responses |
| nlu | rules |

| Result | Category | Scenario | Detail |
|---|---|---|---|
| PASS | requirements | missing budget + dates -> asks only for those |  |
| PASS | requirements | missing destination -> asks where |  |
| PASS | requirements | vague destination is not guessed |  |
| PASS | requirements | multiple travelers scale real fares | flights 992 |
| PASS | requirements | conflicting preferences still yield a valid plan |  |
| PASS | planning | real Rome plan validates; all 8 MCP servers used | total $3,241 |
| PASS | planning | tight hard budget: within budget or flagged | total $2,536 |
| PASS | planning | low walking: every walk <= 1.3 km (ORS distances) | max 0.95 km |
| PASS | planning | relaxed: at most 2 major activities a day | max 4 stops/day |
| PASS | planning | multi-city request handled gracefully (one city) | Rome |
| PASS | planning | no early flights (real schedules) | 08:00, 12:15 |
| PASS | planning | vegetarian: every meal place supports it |  |
| PASS | reality | detect: restaurant closed |  |
| PASS | reality | detect: attraction closed |  |
| PASS | reality | detect: activity no longer listed |  |
| PASS | reality | detect: excessive walking |  |
| PASS | reality | detect: impossible schedule |  |
| PASS | reality | detect: hallucinated place |  |
| PASS | reality | recover: replan avoids a restaurant that closed |  |
| PASS | replanning | replan: fewer museums | Reduced museums from 7 to 5.; Day 6: removed Domus Aurea |
| PASS | replanning | replan: later start | Days now start after 10:00.; Day 2: removed Roman Forum; starts 10:00 instead of 08:30 |
| PASS | replanning | replan: budget cut | Budget set to 2,600 USD.; Hotel: YellowSquare Rome -> Roma Talenti BREME Remote Check-in |
| PASS | replanning | replan: more food | Added more food experiences, coffee and dessert stops. |
| PASS | replanning | replan: more free time | Added more rest and free time.; Total cost +67 USD (now 3,308) |
| PASS | replanning | replan: extend trip (new flights + hotel prices) | Trip is now 9 days (Oct 12 - Oct 20).; Hotel: YellowSquare Rome -> Camping Village Fabulous |
| PASS | replanning | replan: remove a named activity | Removed it and found a replacement.; Day 1: removed Piazza di Siena, Pantheon |
