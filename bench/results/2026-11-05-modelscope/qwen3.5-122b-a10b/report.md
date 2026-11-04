# Evaluation report — Qwen/Qwen3.5-122B-A10B

- model: `Qwen/Qwen3.5-122B-A10B`  
- cases: 25  
- generated: 2026-11-04T16:32:49+00:00

## Summary

| metric | value |
|---|---|
| task success rate | 36.0% (9/25) |
| task success rate, ordinary cases | 42.1% (9/19) |
| quality score | not scored (no judge run) |
| latency p50 / p95 | 12.304s / 44.973s |
| latency mean | 14.002s |
| prompt tokens (estimate) | 63837 |
| render seconds | 26.739s |
| tool calls / reused artefacts | 78 / 0 |

## Cases

| case | status | passed | latency | failed checks |
|---|---|---|---|---|
| core-01 | ok | fail | 15.745s | render |
| core-02 | ok | fail | 7.737s | render |
| core-03 | ok | pass | 45.397s | — |
| core-04 | ok | expected failure | 6.235s | shots, must_cite |
| core-05 | ok | pass | 12.304s | — |
| core-06 | ok | fail | 15.126s | duration_s |
| core-07 | ok | pass | 14.646s | — |
| core-08 | ok | fail | 15.882s | render |
| core-09 | ok | pass | 22.446s | — |
| core-10 | ok | pass | 44.973s | — |
| core-11 | ok | expected failure | 12.208s | duration_s, shots |
| core-12 | ok | expected failure | 29.242s | shots |
| core-13 | failed | fail | 5.162s | duration_s, shots, render |
| core-14 | failed | fail | 6.346s | duration_s, shots, render |
| core-15 | failed | fail | 11.428s | — |
| core-16 | failed | fail | 2.901s | duration_s, shots, must_cite, render |
| core-17 | ok | pass | 20.44s | — |
| core-18 | failed | fail | 3.521s | duration_s, shots, must_cite, render |
| core-19 | ok | pass | 15.266s | — |
| core-20 | ok | pass | 12.118s | — |
| core-21 | ok | pass | 18.15s | — |
| core-22 | failed | expected failure | 12.413s | max_latency_s |
| core-23 | failed | fail | 0.137s | duration_s, shots, must_cite, min_assets, render |
| core-24 | failed | expected failure | 0.11s | duration_s, must_cite |
| core-25 | failed | fail | 0.116s | duration_s, shots, must_cite, min_assets, render |

> Token counts are character-based estimates; quality stays empty until a judge has scored the run.
