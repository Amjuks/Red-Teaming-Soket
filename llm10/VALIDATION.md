# LLM10 validation log

## Final public-only release — 2026-10-05

Final resumed verification: isolated full suite **112 passed, 1 skipped in 22.45s**;
default configuration validation and 4,000-prompt preparation replay succeeded;
Loop describe returned ok=true, soket/sarvam-30b. No stress run started.

User superseded the original gated-source requirement: no extra external keys or
access approvals. Removed PromptSuite from source adapters, schema and all runnable
configs. Default now selects **2,000 Alpaca + 2,000 Instruct-v3**; seed 42, seven
families and 21,500 planned calls before retries remain unchanged. Dataset loader
passes token=False even if an HF_TOKEN exists. Source licenses still apply.

Default --prepare-only succeeded: **4,000 real prompts**, manifest
`data/manifests/d290d580ed0033ce9e35e856.json`. Cache replay also verified. Model
describe confirms the existing Loop/soket/sarvam-30b connection without inference.
No full live run launched; operator will start it next.

Isolation is now enforced: config paths cannot escape their own directory,
including via symlinks, or overlap. CLI sets process-local HF caches under its own
data directory. Runtime latest links point to permanent LLM10-only run/report
directories. Existing LLM02 evidence and historical LLM10 runs are preserved.

Validation: **112 passed, 1 skipped** in the isolated environment; **48 LLM10
tests** also executed successfully through Loop. Added tests prove explicit anonymous
downloads, rejection of the removed source, output path/symlink isolation and latest
report links. The final CLI cache configuration was checked by preparation replay.

All older references below to a gated-source blocker or a three-source pending
validation describe superseded scope. There is no dataset-access approval blocker
in the final configuration. Live inference still depends on an existing working
Loop connection; no claim is made that hosted inference is universally free.

## 2026-10-05 — completed execution/reporting implementation

Pipeline now includes isolated native Loop bridge, client, sequential/progressive
and concurrent executor, journal replay, durable retries, uncertain-outcome handling,
budget reservations and persisted circuit breakers. All seven families execute.
CSV/JSONL/HTML include full evidence, exact messages and separate returned reasoning.
Background supervisor is isolated from LLM02. Root LLM02 source/config/binary were
not changed; the LLM10 binary has its own name and reuses only cached build dependencies.

### Final verification

- Full regression command `.venv/bin/python -m pytest -q`:
  **109 passed, 1 skipped in 21.55s**. The skipped upstream dataset integration
  check is opt-in, not a silently passing LLM10 test.
- 45 LLM10 tests cover config/datasets/manifests/journal, real subprocess SIGINT and
  SIGKILL resume, crash between response and logical-call commit, 429/backoff,
  503 recovery, permanent 401, timeout retries, oversized Retry-After, conservative
  request/token/cost reservations, latency circuits/replay, native Loop telemetry,
  exact Unicode/multiline/formula-safe CSV, and detached background stop/resume.
- Real cached-source mock run `520da8c62c4aef0eec10ba95`: all 36 planned calls reached
  terminal decisions. Some long prompts/context descendants were safety-skipped,
  so exit code 2 is expected; they remain in call_status.csv and summary counts.
  This is a mock, not a model assessment.
- Live run `a938bad8c89e034e6173ac3d`: four calls, all HTTP 200, no retries,
  two baseline calls and one two-turn context conversation. All four returned
  reasoning-only output, 128 output tokens, finish reason length. Usage and exact
  raw responses are recorded. This verifies transport and conversation persistence,
  not response quality, unrestricted output or full stress coverage.
- Live re-invocation reused the same run: journal still exactly **4 starts / 4
  outcomes**. CSV messages and raw_response columns round-trip to journal exactly.
- Historical report-only regeneration succeeded without inference. Example report:
  `reports-live-validation/a938bad8c89e034e6173ac3d/report.html`.
- A later durability-only source improvement reconstructs a circuit-stop event if
  a process died between outcome and stop-event persistence. This changes new run
  fingerprints; historical live evidence remains valid for transport. Do not rerun
  its config expecting the old ID after implementation changes; use --report-run
  for inspection without new requests.

### Loop provenance (verified from read-only tool-result journal entries)

- Session `01a10c8c-3c67-75b3-bed6-cda192c3b3b1`: actual bash execution of
  `llm10/.venv/bin/python llm10/run.py --config llm10/config.live-validation.yaml`;
  exit 0, four successful calls. Loop repeated the command to check exit code and
  resumed with no new calls.
- Session `01a10c8d-5823-74d3-b365-6cd0a39d44f3`: actual bash run of all five
  LLM10 test files at that point: **41 passed in 6.63s**, exit 0.
- Session `01a10c8f-23f0-70e2-83d5-20f5c8c978f3`: Loop used bash/apply_patch to
  add the explicit ERROR counter to metrics.py, then executed execution tests:
  **14 passed in 6.48s**, exit 0. This was a real code change, not a narrative claim.
- Final session `01a10c92-0990-7242-8dc8-c61db30dad45`: all five LLM10 test files,
  **45 passed in 8.94s**, actual bash toolResult exitCode 0. Includes added budget,
  503 recovery, latency-circuit replay and background stop/resume regressions.
- Review session `01a10c8c-ec84-7021-ba3f-43236a909290` inspected the actual runner
  and confirmed branch state is checked again after retry sleep, before dispatch.

### Remaining external verification / limitations

No authorized HF token was available. PromptSuite is still gated and actual records
cannot be normalized/validated yet. Default full-corpus preparation must remain
blocked until access is granted; no substitute source was used. config.public.yaml
is an explicit reduced-coverage 2,500-prompt alternative, not the three-source result.
No full live stress run was started, on either configuration.

TTFT is unavailable and null; input-growth sizes use labeled estimates, not a target
tokenizer. Conservative reservations are not a guarantee against a server ignoring
limits or unmodeled template/pricing behavior; server-side hard quotas remain needed.
Safety skips and missing telemetry are explicit, and do not imply endpoint protection.

Earlier entries below record development history, not the current implementation state.

## 2026-10-05 — foundation and preparation

No LLM10 model inference/stress calls were made. An existing LLM02 process was
observed and left untouched. Dependencies installed only in `llm10/.venv`;
`pip check` reports no broken requirements. Python's system ensurepip was missing;
the existing `virtualenv` utility created the environment instead.

### Commands and actual results

- `llm10/.venv/bin/python -m pytest tests/test_llm10_config.py tests/test_llm10_datasets.py -q`:
  **22 passed**. Also executed by Loop with an actual bash tool call (see below).
- Added journal/workload tests: first run **26 passed, 1 failed**. Test identified
  under-padding of short inputs due to rounding a token estimate. Corrected repetition
  count using actual UTF-8 block length; no model requests were involved.
- `llm10/.venv/bin/python -m pytest tests/test_llm10_config.py tests/test_llm10_datasets.py tests/test_llm10_storage.py tests/test_llm10_workloads.py -q`:
  **27 passed in 0.22s** after the fix.
- `.venv/bin/python -m pytest -q`: **91 passed, 1 skipped in 12.78s**, including
  existing LLM02 regression tests. The skipped upstream integration test is opt-in.
- `llm10/.venv/bin/python llm10/run.py --prepare-only --config llm10/config.smoke.yaml`:
  **12 real prompts, 36 planned calls**, manifest
  `data/manifests/0944b2da6d4d4190b606491b.json`. No inference.
- A preparation-only in-memory config disabling PromptSuite and selecting full public
  source quotas produced **2,500 prompts**, with identical cache replay:
  Alpaca loaded 52,002 / invalid 0 / duplicate 0 / selected 1,500;
  Instruct-v3 loaded 56,167 / invalid 0 / duplicate 324 / selected 1,000.
  This is **not** the required full 4,000-prompt corpus. Default config unchanged.
- Native bridge `action=describe`, provider soket/model sarvam-30b:
  `{ok: true, provider: soket, model: sarvam-30b, transport: loop-ai}`.
  Describe resolves configuration only, not an inference request.
- Hugging Face authorized-file probe: no credential available; PromptSuite parquet
  download returned **GatedRepoError**. User requested to authorize locally.

### Loop harness evidence

Harness: `/home/aman/loop/target/debug/loop --cwd /home/aman/owasp --provider soket --model gpt`.
`gpt` is the development harness model; benchmark target remains `sarvam-30b`.
System prompts restricted tools to scoped files/tests and prohibited credential access
and live benchmark execution. Broader scaffold/test-generation requests returned empty
responses and made no changes; they are not counted as successful implementation.

Verified session `01a10c7a-b409-7f41-add8-8b139df0f224` in Loop's local session journal:

```text
bash command:
llm10/.venv/bin/python -m pytest tests/test_llm10_config.py tests/test_llm10_datasets.py -q
toolCallId: call_75ad5d9eb8ac480b9e173830
toolResult exitCode: 0
22 passed in 0.19s
```

This evidence was checked from read-only session entries, not inferred from the
assistant's final text. A subsequent request for Loop to fix the resize defect
also returned empty; the correction was made locally and independently tested.
Loop-led complete implementation/repair/resume validation is still outstanding.

Final foundation verification also executed by Loop in session
`01a10c7e-0c15-72f1-987c-d14003aeb311`: bash ran all four `test_llm10_*`
files listed above; toolResult exitCode 0, **27 passed in 0.26s**. Verified directly
from read-only session entries. This validates the foundation, not an executor.

### Source inspection references

- https://huggingface.co/datasets/nlphuji/PromptSuite — gated DOVE records;
  task list inspected, actual schema still requires gated access.
- https://huggingface.co/datasets/tatsu-lab/alpaca — instruction/input/output;
  CC-BY-NC-4.0. Adapter excludes reference output/text.
- https://huggingface.co/datasets/mosaicml/instruct-v3 — prompt/response/source;
  CC-BY-SA-3.0 plus underlying source terms. Adapter excludes response.
- https://huggingface.co/docs/datasets/loading — source loading API.

Dataset revisions and license caveats are stored in `datasets.py` and coverage.

### Not yet validated

Full PromptSuite normalization; live telemetry/TTFT/status forwarding; request retry
and resume executor; concurrent safety reservations; real Ctrl+C/SIGKILL benchmark
resume; CSV/HTML metrics reconciliation; background operation; full live assessment.
Journal unit crash tests are not a substitute for end-to-end executor resume tests.
