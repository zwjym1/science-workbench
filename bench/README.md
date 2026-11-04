# clipbench — batch evaluation for clipagent

Eight cases, four metrics, a report you can diff between two versions.

```bash
pip install -e ../agent -e .
clipbench run --workdir /tmp/bench-work --out /tmp/bench-out
python -m unittest discover -s tests          # 22 tests
```

## What a report looks like

```
| metric | value |
| task success rate | 87.5% (7/8) |
| quality score | not scored (no rubric) |
| latency p50 / p95 | 0.883s / 0.943s |
| prompt tokens (estimate) | 27623 |
| render seconds | 0.37s |
| tool calls / reused artefacts | 40 / 0 |
```

Two deliberate choices in that table:

**Quality is `null`, not zero, when no rubric exists.** Averaging unscored cases
into a quality mean is the standard way a benchmark flatters itself. The report
says "not scored (no rubric)" until a rubric exists and a judge has scored it.

**The model line names what produced the numbers.** With the built-in policy it
reads `scripted-reference-policy (runner mechanics only; not a model measurement)`.
That stand-in derives its tool sequence from the case constraints, so it always
passes by construction; it exists to test the runner, the checks and the reports,
and pretending otherwise would make the whole table meaningless.

## Cases

`clipbench/cases/core.json` holds eight cases, each with a task, constraints and
an optional rubric:

| id | what it exercises |
|---|---|
| core-01 | baseline: 40 s, 4 shots, cited, rendered |
| core-02 | lower bound: 15 s, one shot |
| core-03 | upper bound: 40 shots |
| core-04 | known failure: no source, so the script tool must refuse |
| core-05 | asset floor: at least three licensed candidates |
| core-06 | latency budget: whole run under 45 s |
| core-07 | picture only, no narration track |
| core-08 | a rubric skeleton, to show the shape |

`core-04` is marked `known_failure: true`. It is expected to fail and is reported
as `XFAIL` rather than quietly removed — a benchmark that only contains cases it
passes measures nothing.

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

## What is still missing

Rubric scoring is the next milestone. Until a human has labelled ten cases and a
judge has been calibrated against those labels, `quality` stays null and the
"LLM-as-a-Judge" claim stays unearned.
