# Planner benchmark

Generated 2026-10-05T03:43:50+03:00 from `python eval/benchmark.py` - 6 scenarios on recorded real data (random: 5 seeds each). Means over scenarios.

| planner | hard violations | feasible | travel min | km/hop | cost | within budget | landmarks | pref. fit | TripScore | compute ms |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 4.13 | 0.0 | 883.03 | 5.01 | 2457.33 | 0.7 | 0.67 | 0.54 | 49.0 | 1.65 |
| greedy | 1.67 | 0.333 | 683.33 | 2.5 | 1564.0 | 0.833 | 1.0 | 0.59 | 61.33 | 1.77 |
| ortools | 1.5 | 0.333 | 657.0 | 2.39 | 1561.0 | 0.833 | 1.0 | 0.59 | 61.33 | 66.35 |
| dalili | 0.17 | 0.833 | 694.83 | 2.02 | 1651.83 | 0.833 | 1.0 | 0.59 | 77.5 | 141.63 |
