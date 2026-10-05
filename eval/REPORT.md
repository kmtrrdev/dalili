# Evaluation report

Real API responses (recorded) - see eval/run_eval.py.

| Metric | Value |
|---|---|
| scenarios_passed | 26/26 |
| requirement_handling | 100.0% |
| constraint_satisfaction_rate | 99.2% |
| schedule_feasibility | 100.0% |
| budget_accuracy | 100.00% |
| tool_selection_accuracy | 85.7% |
| grounded_recommendation_rate | 98.3% |
| reality_violation_rate | 0.00% |
| injected_violation_detection_rate | 100.0% |
| replanning_success_rate | 100.0% |
| preference_satisfaction | 100.0% |
| cost_backed_by_published_prices | 62.7% |
| scheduled_places_with_verified_hours | 90.4% |
| avg_turn_latency_ms (replay) | 716 |
| p95_turn_latency_ms (replay) | 1229 |
| plans_audited | 60 |
| total_runtime_s | 16.3 |
| data | recorded real API responses |
| nlu | rules |

| Result | Category | Scenario | Detail |
|---|---|---|---|
| PASS | requirements | missing budget + dates -> asks only for those |  |
| PASS | requirements | missing destination -> asks where |  |
| PASS | requirements | vague destination is not guessed |  |
| PASS | requirements | multiple travelers scale real fares | flights 976 |
| PASS | requirements | conflicting preferences still yield a valid plan |  |
| PASS | planning | real Rome plan validates; all 8 MCP servers used | total $2,869 |
| PASS | planning | tight hard budget: within budget or flagged | total $2,200 |
| PASS | planning | low walking: every walk <= 1.3 km (ORS distances) | max 1.00 km |
| PASS | planning | relaxed: at most 2 major activities a day | max 3 stops/day |
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
| PASS | replanning | replan: fewer museums | Reduced museums from 7 to 5.; Day 6: removed Trajan's Column |
| PASS | replanning | replan: later start | Days now start after 10:00.; Day 2: starts 10:00 instead of 08:30 |
| PASS | replanning | replan: budget cut | Budget set to 2,600 USD.; Hotel: Roma Scout Center -> Seven Hills Camping & Village |
| PASS | replanning | replan: more food | Added more food experiences, coffee and dessert stops. |
| PASS | replanning | replan: more free time | Added more rest and free time.; Day 3: removed Vatican Museums |
| PASS | replanning | replan: extend trip (new flights + hotel prices) | Trip is now 9 days (Oct 12 - Oct 20).; Hotel: Roma Scout Center -> YellowSquare Rome |
| PASS | replanning | replan: remove a named activity | Removed it and found a replacement.; Day 2: removed Colosseum; added National Museum of the Palazzo di Venezia |
