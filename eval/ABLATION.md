# Ablation study

Generated 2026-10-05T04:29:46+03:00 from `python eval/ablation.py` with gpt-5-mini on 6 scenarios (recorded real data). Means over scenarios.

| config | ungrounded | hard violations | feasible | budget error | grounded items | pref. fit | landmarks | TripScore | latency ms | LLM calls | tokens | LLM cost $ | failed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A. LLM only | 1.0 | 8.67 | 0.0 | 1.1 | 0.0 | None | 0.0 | 49.0 | 23210.95 | 1.0 | 4128.17 | 0.01 | 0 |
| B. LLM + retrieval | 1.0 | 7.83 | 0.0 | 0.96 | 0.0 | None | 0.0 | 49.0 | 24748.77 | 1.0 | 5170.17 | 0.01 | 0 |
| C. LLM + MCP | 0.15 | 16.83 | 0.0 | 0.15 | 0.85 | 1.0 | 0.8 | 49.0 | 29735.55 | 1.0 | 15981.33 | 0.01 | 0 |
| D. LLM + MCP + validation | 0.15 | 15.0 | 0.0 | 0.18 | 0.85 | 1.0 | 0.87 | 49.0 | 56982.92 | 2.0 | 34800.67 | 0.02 | 0 |
| E. LLM + MCP + optimizer | None | 0.83 | 0.167 | 0.0 | 1.0 | 1.0 | 0.97 | 54.5 | 12967.6 | 1.0 | 9945.83 | 0.01 | 0 |
| F. Full Dalili | 0.0 | 0.0 | 1.0 | 0.0 | 0.95 | 1.0 | 1.0 | 82.0 | 124.65 | 0.0 | 0.0 | 0.0 | 0 |
