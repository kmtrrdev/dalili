# Ablation study

Generated 2026-10-05T04:46:06+03:00 from `python eval/ablation.py` with gpt-5-mini on 6 scenarios (recorded real data). Means over scenarios.

| config | ungrounded | hard violations | feasible | budget error | grounded items | pref. fit | landmarks | TripScore | latency ms | LLM calls | tokens | LLM cost $ | failed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A. LLM only | 0.84 | 6.67 | 0.0 | 1.01 | 0.16 | 0.66 | 0.63 | 49.0 | 24862.52 | 1.0 | 4268.67 | 0.01 | 0 |
| B. LLM + retrieval | 0.8 | 6.83 | 0.0 | 0.8 | 0.2 | 0.64 | 0.73 | 49.0 | 23908.6 | 1.0 | 5133.0 | 0.01 | 0 |
| C. LLM + MCP | 0.18 | 18.67 | 0.0 | 0.15 | 0.82 | 0.6 | 0.9 | 48.67 | 31286.72 | 1.0 | 15768.33 | 0.01 | 0 |
| D. LLM + MCP + validation | 0.16 | 13.5 | 0.0 | 0.1 | 0.84 | 0.62 | 1.0 | 49.0 | 62016.6 | 2.0 | 35067.33 | 0.02 | 0 |
| E. LLM + MCP + optimizer | None | 1.17 | 0.167 | 0.0 | 1.0 | 0.59 | 0.93 | 55.0 | 11587.1 | 1.0 | 9272.33 | 0.0 | 0 |
| F. Full Dalili | 0.0 | 0.0 | 1.0 | 0.0 | 0.96 | 0.59 | 1.0 | 81.33 | 93.43 | 0.0 | 0.0 | 0.0 | 0 |
