# Planner benchmark

Generated 2026-10-05T04:32:28+03:00 from `python eval/benchmark.py` - 6 scenarios on recorded real data (random: 5 seeds each). Means over scenarios.

| planner | hard violations | feasible | travel min | km/hop | cost | within budget | landmarks | pref. fit | TripScore | compute ms |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 4.03 | 0.033 | 916.07 | 5.31 | 1876.17 | 0.767 | 0.69 | 0.54 | 50.0 | 1.84 |
| greedy | 1.67 | 0.333 | 683.33 | 2.5 | 1559.5 | 0.833 | 1.0 | 0.59 | 61.33 | 2.22 |
| ortools | 1.5 | 0.333 | 657.0 | 2.39 | 1556.67 | 0.833 | 1.0 | 0.59 | 61.33 | 62.62 |
| dalili | 0.0 | 1.0 | 694.83 | 2.02 | 1647.0 | 1.0 | 1.0 | 0.59 | 81.33 | 86.53 |
