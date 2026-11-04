# Evaluation report — Qwen/Qwen3.5-27B

- model: `Qwen/Qwen3.5-27B`  
- cases: 25  
- generated: 2026-11-04T16:26:58+00:00

## Summary

| metric | value |
|---|---|
| task success rate | 76.0% (19/25) |
| task success rate, ordinary cases | 94.7% (19/19) |
| quality score | not scored (no judge run) |
| latency p50 / p95 | 30.391s / 87.592s |
| latency mean | 35.073s |
| prompt tokens (estimate) | 101626 |
| render seconds | 96.513s |
| tool calls / reused artefacts | 114 / 0 |

## Cases

| case | status | passed | latency | failed checks |
|---|---|---|---|---|
| core-01 | ok | pass | 36.208s | — |
| core-02 | ok | pass | 30.025s | — |
| core-03 | ok | pass | 76.018s | — |
| core-04 | ok | expected failure | 14.919s | shots, must_cite |
| core-05 | ok | pass | 24.316s | — |
| core-06 | ok | pass | 35.293s | — |
| core-07 | ok | pass | 25.734s | — |
| core-08 | ok | pass | 27.693s | — |
| core-09 | ok | pass | 35.397s | — |
| core-10 | ok | pass | 87.592s | — |
| core-11 | ok | expected failure | 29.887s | duration_s, shots |
| core-12 | ok | expected failure | 102.188s | shots |
| core-13 | ok | pass | 27.047s | — |
| core-14 | ok | pass | 24.608s | — |
| core-15 | ok | pass | 30.708s | — |
| core-16 | ok | pass | 30.391s | — |
| core-17 | ok | pass | 36.039s | — |
| core-18 | ok | pass | 33.666s | — |
| core-19 | failed | fail | 21.429s | duration_s, shots, must_cite, render |
| core-20 | ok | pass | 12.822s | — |
| core-21 | ok | pass | 30.755s | — |
| core-22 | ok | expected failure | 28.79s | max_latency_s |
| core-23 | ok | pass | 32.133s | — |
| core-24 | ok | expected failure | 10.642s | duration_s, must_cite |
| core-25 | ok | pass | 32.516s | — |

> Token counts are character-based estimates; quality stays empty until a judge has scored the run.
