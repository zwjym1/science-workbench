# clipbench — batch evaluation for clipagent

25 cases, four metrics, a report you can diff between two versions, failure
attribution from the trace, and a judge whose agreement with a human is measured
rather than asserted.

```bash
pip install -e ../agent -e .
clipbench run --workdir /tmp/bench-work --out /tmp/bench-out
python -m unittest discover -s tests          # 65 tests
```

## What a report looks like

```
| metric | value |
| task success rate | 76.0% (19/25) |
| task success rate, ordinary cases | 100.0% (19/19) |
| quality score | not scored (no judge run) |
| latency p50 / p95 | 0.179s / 0.263s |
| prompt tokens (estimate) | 77072 |
| render seconds | 0.016s |
| tool calls / reused artefacts | 105 / 0 |
```

Three deliberate choices in that table:

**Known failures stay in the headline rate.** Six of the 25 cases are supposed
to fail (refusal, out-of-range input). Dropping them would turn 76% into 100%
and hide exactly the adversarial cases the set exists to hold. The second row
says whether the ordinary pipeline works; the first says how the whole set
behaved.

**Quality is `null`, not zero, until a judge has run.** Averaging unscored cases
into a quality mean is the standard way a benchmark flatters itself.

**The model line names what produced the numbers.** With the built-in policy it
reads `scripted-reference-policy (runner mechanics only; not a model measurement)`.
That stand-in derives its tool sequence from the case constraints; it exists to
test the runner, the checks and the reports, and pretending it measures a model
would make the whole table meaningless.

## Cases

`clipbench/cases/core.json` holds 25 cases, each with a task, constraints and an
optional rubric:

| group | ids | what it exercises |
|---|---|---|
| baseline | core-01 | 40 s, 4 shots, cited, rendered |
| boundaries | core-02, 03, 09, 10 | 15 s / 1 shot, 40 shots, 600 s / 8 shots, 15 s / 40 shots |
| asset floors, latency, picture-only | core-05, 06, 07 | at least three licensed candidates, run under 45 s, no narration track |
| science topics | core-08, 13–20, 23, 25 | ordinary briefs across subject matter and lengths |
| known failures | core-04, 11, 12, 21, 22, 24 | no source to cite, duration below 15 s, 41 shots, missing asset, impossible latency, zero shots |

Known failures are marked `known_failure: true` and reported as `XFAIL` rather
than quietly removed. Their runs are still failures in the metrics; the flag is
for the reader, not for the arithmetic.

`core-10` is the case that caught a real renderer bug: 40 shots of 0.375 s at
12 fps is 4.5 frames each, and rounding each clip independently produced
16.7 s for a 15 s brief. Frame counts are now derived from cumulative
boundaries, so drift does not accumulate.

## Constraint checking

Rules only, in `case.py`: duration, shot count, citation coverage, asset floor,
render output re-read through ffprobe, and a latency ceiling. Unknown constraint
keys are a hard error, so a typo like `durration_s` cannot silently become a case
that checks nothing.

## Comparing two versions

```bash
clipbench compare /tmp/v1/results.json /tmp/v2/results.json --out diff.md
```

Per-case regression and fix lists, plus deltas for success rate, quality, latency,
prompt tokens and render seconds. `runner.py` caches each finished case in its own
directory, so an interrupted batch resumes and an unchanged case is not re-run.

## Failure attribution

`clipbench run` also writes `attribution.md`, and `clipbench attribute` can be
run on any earlier result file. It reads the trace and assigns each failure one
of five buckets, with the signal that fired:

| bucket | signal it comes from |
|---|---|
| `environment` | ffmpeg / filesystem / network faults |
| `argument_generation` | the tool rejected the arguments |
| `tool_selection` | the model named a tool that does not exist |
| `context_understanding` | repeated failure right after history compaction |
| `planning` | kept choosing a doomed action, or ran out of steps, or clean tools that missed the constraints |

Two properties worth keeping:

**Passing runs are excluded, not counted as `none`.** A distribution diluted by
successes says nothing about failure modes. The report states how many cases
passed and gives shares out of failures only.

**`unclassified` is a real answer.** When a failure matches no rule it is
reported as such instead of being forced into the nearest bucket. An attribution
layer that always finds a category hides exactly the cases the taxonomy does not
cover yet.

Precedence is fixed: `environment` outranks everything downstream of it, because
a missing ffmpeg explains every error that follows and attributing those to
planning would send you fixing the wrong layer.

## Judge and calibration

The judge prompt is frozen and hashed; the hash is written into every
`results.json` as `judge_prompt_sha`:

```bash
clipbench label-sheet --out labels.csv     # 25 rows, both score columns blank
clipbench calibrate labels.csv --out calibration.md
```

`label-sheet` only creates the sheet. The human column is filled by a person;
the judge column is filled by `judge.LLMJudge` (temperature 0, fixed prompt,
per-dimension scores with weights) or by `judge.RubricJudge` for harness tests.
`calibrate` computes Cohen's kappa, quadratic weighted kappa, mean absolute
error and the disagreements, and refuses to call fewer than ten pairs
meaningful.

`RubricJudge` is deterministic and useful for testing the plumbing; it is not a
measurement of narrative quality. A calibration run that used it would agree
with itself for reasons that have nothing to do with a model, so its scores are
never presented as judge results in a report.

To score finished runs, read the artifacts back from the run directory:

```bash
export JUDGE_BASE_URL=https://api-inference.modelscope.cn/v1
export JUDGE_MODEL=Qwen/Qwen3-32B
export JUDGE_API_KEY=ms-...
clipbench score --results /tmp/bench-out/results.json \
                --workdir /tmp/bench-work --out labels.csv
```

It judges cases that actually produced a script (known-failure cases have
nothing to score), writes the judge column and leaves the human column blank.
`--judge rubric` runs entirely offline and labels its output as a stand-in.

## One case set, several models

```bash
export CLIPAGENT_BASE_URL=https://api-inference.modelscope.cn/v1
export CLIPAGENT_API_KEY=ms-...
clipbench matrix --models Qwen/Qwen3-32B,Qwen/Qwen3-14B,deepseek-ai/DeepSeek-V3,moonshotai/Kimi-K2 \
                 --out /tmp/matrix
```

Each model gets its own work directory, so cached artifacts are never shared
between models and a rerun cannot look cheaper by reusing another model's work.
`matrix.md` lists passed, both success rates, p50/p95, token estimate, render
seconds and error count per model — the same four metrics, one row per model.

Tool calling must work through the endpoint; run one case with `--only` before
spending a day's quota on the full set.

## What is still missing

The rubric has weights (narrative 0.3, accuracy 0.4, density 0.2, constraint
0.1) but they are a starting point, not a calibrated scale: they must be revised
after ten human labels and a real judge run. The four-model comparison needs
API keys, and until it runs the resume must not claim it.

