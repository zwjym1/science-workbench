# clipagent — ReAct harness for a short science-explainer pipeline

Five tools, one loop, a complete trace of every run. Written by hand rather than
assembled from a framework, and shipped next to an equivalent LangChain version
so the trade-off is inspectable instead of asserted.

```bash
pip install -e .
clipagent demo --workdir /tmp/clipagent-demo
```

The demo drives the whole pipeline with a scripted model, so it runs without a
key. Output on a clean machine:

```
status: ok, steps: 6
  search_assets: status=ok
  write_script: status=ok
  make_storyboard: status=ok
  synthesize_tts: status=unavailable (no speech engine configured)
  render_and_check: status=ok   # h264, 320x180, 40.000s
```

Run the same command again and the second run reports `attempts: 0, reused: 5` —
every artefact was found by content address and nothing was recomputed.

## The loop

`plan → act → observe → re-plan`, in `clipagent/loop.py`:

1. Compact history against a token ceiling (`budget.py`).
2. Ask the model for one decision, passing the five tool schemas.
3. Either finish, or execute exactly one tool.
4. Append the result — or the failure — to the history and go to 1.

Two details that matter more than they look:

**A failure is input, not a retry.** When a tool rejects its arguments or throws,
the error text becomes an observation and the next turn sees it. The re-plan is
the model choosing differently in response to evidence. Blindly retrying the same
call three times is what a naive loop does, and it is why such loops burn tokens
on a step that cannot succeed.

**Steps are content-addressed.** `ArtifactStore` keys artefacts on
`sha256(tool, canonical args)`. Re-running a run whose later steps failed reuses
the earlier work and marks it `reused: true` in the trace, so a before/after cost
comparison is not quietly flattered by rediscovering the same script.

In-step retries do exist, capped at `max_attempts`, but only as a guard against
transient environment faults (a busy ffmpeg, a locked file). Argument errors are
not retried — they cannot fix themselves.

## The tools

| tool | does | refuses |
|---|---|---|
| `search_assets` | look up source assets with licence and provenance | empty query; limit outside 1–20 |
| `write_script` | one citation id per sentence | a script with no citation at all |
| `make_storyboard` | timed shots, seconds summing to the requested duration | empty sentences; >40 shots |
| `synthesize_tts` | a playable WAV whose length matches the storyboard | claims speech it did not synthesise |
| `render_and_check` | renders, then verifies duration and resolution from ffprobe | reports `unavailable` if ffmpeg is missing |

`synthesize_tts` returns `status: unavailable` because no speech engine is
configured. It still writes a silent track of the right length: the duration and
timing are real, the voice is not, and the status says so. A pipeline that
returned a plausible-looking audio file here would be lying about the one thing
this harness is supposed to protect — whether the output actually exists.

## Comparison with the LangChain version

`clipagent/langchain_agent.py` builds the same five tools as `StructuredTool`s
and an `AgentExecutor` over a tool-calling agent. `parity_report()` compares the
two registries; the test suite fails if they drift.

| | hand-written loop | LangChain |
|---|---|---|
| dependencies | none | `langchain`, `langchain-core`, plus their trees |
| trace | one JSONL per run, written as it happens | callback handlers, assembled separately |
| re-plan on failure | explicit, visible in the trace | framework-dependent, tuned by config |
| swapping models | implement one method | adapter ecosystem |
| reading the control flow | one file | several packages |

The parity test caught a real defect while this was being written: wrapping the
tool functions with `**kwargs` made the framework advertise a single parameter
named `kwargs`, so a model would never have learned the real argument names. That
is the reason the check compares parameter surfaces and not just tool names.

## Retrieval without training anything

`clipagent/rag.py` answers "which source supports this sentence" without an
embedding service. Documents are tokenised into CJK bigrams (whole words for
Latin text), scored by BM25 (k1=1.5, b=0.75), combined with a hashed feature
vector (512 dimensions, blake2b sign trick, cosine) and a phrase-containment
bonus, then filtered by `MIN_COSINE`. Every hit carries its source id.

The method string returned with results says what it is: a lexical/feature
baseline, not a trained embedding. It is cheap, offline and inspectable; it is
not a claim to beat a real embedding model. `assert_cited()` checks that each
citation id exists in the corpus — it proves the source is real, not that the
source supports the sentence. 17 tests cover tokenisation, ranking, the
single-character query edge case, hash collisions below the cosine floor, and
citation enforcement.

## What this is not

No fine-tuning, no multi-agent delegation. The judge and the benchmark live in
`bench/`; this module only has to make a run reproducible, inspectable and cheap
to repeat.
