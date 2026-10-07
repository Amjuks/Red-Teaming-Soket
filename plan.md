# LLM10 final plan and developer handoff

## 2026-10-07: actionable risk analysis completed

Fresh-run setup: gracefully stopped previous foreground LLM10 PID 3911295;
preserved its journal/reports. Added config.full.yaml with all seven families,
fresh dated output roots, 25k attempt cap and 350M conservative reservation cap
(prepared first-pass upper bound 277,851,080). Safety circuits unchanged.
Loop model resolution passed without a new credential. Full assessment is NOT
launched by this setup; user launch/status/report instructions are in README.

Live run `35843fce7793b2816ccd6e12` is ongoing (the older launch status below
is historical). Reporting now separates observed failures, requested output
caps, empty final answers, missing cost data and incomplete coverage from
confirmed vulnerability claims. Added findings.csv/control_assessment.csv with
remediation, retest and joinable attempt evidence IDs. No execution changes or
new inference calls. `python -m llm10.report llm10/results/latest` from workspace
using the LLM10 venv generates an isolated analysis snapshot during a live run.
See llm10/README.md for interpretation and refresh instructions. Next developer:
correlate failures with provider logs/SLO/quotas; do not claim causality from
shared-endpoint latency alone.

Updated 2026-10-05 (Asia/Kolkata). **Implementation finalized and ready for the user
to launch.** Full default preparation verified: 4,000 prompts, 21,500 scheduled
calls before retries. Full stress run has NOT been launched.

Final resumed check: 112 passed / 1 skipped (22.45s), full preparation replay and
Loop model resolution passed. No external dataset credentials needed.

## Overview and final scope

Python + files, no database. OWASP LLM10 resource-consumption testing through the
existing Loop/soket/sarvam-30b connection, all seven families, durable per-attempt
journal, resume, bounded stress controls and full CSV/JSONL/HTML evidence.

The latest user request removes gated sources and new external credential requirements.
Default: **2,000 Alpaca + 2,000 Instruct-v3**, deterministic seed 42. PromptSuite
has been removed from loader/schema/all runnable configs; the original requirement
is superseded, not silently omitted. Downloads explicitly use token=False.
Free anonymous access does not waive dataset licenses or guarantee free hosted
model inference. The existing working Loop connection is reused; no new key needed here.

## Current setup and commands

Everything runs under /home/aman/owasp/llm10 with its own .venv, configs, data,
logs, results, reports, supervisor lock and per-run journal locks. Existing LLM02
code/environment/config/results are not changed or used by this pipeline.

```bash
cd /home/aman/owasp/llm10
source .venv/bin/activate
python run.py

# Alternatively run detached:
python background.py start
tail -f logs/latest.log
python background.py status
python background.py stop
# Resume with same command/configuration:
python background.py start
```

Dataset preparation and validation-only never invoke the model:

```bash
python run.py --prepare-only
python run.py --validate-config
```

The default is already public-only; config.public.yaml is merely an optional smaller
2,500-prompt preset. Mock/smoke presets use 12 prompts; live-validation uses 4 calls.
No default/gated fallback or new key is required.

## Reports and isolation

After execution starts:
- HTML: /home/aman/owasp/llm10/reports/latest/report.html
- All CSV/raw evidence: /home/aman/owasp/llm10/results/latest/
- Progress: /home/aman/owasp/llm10/results/latest/state.json
- Background log: /home/aman/owasp/llm10/logs/latest.log

Each latest symlink resolves to an immutable run-id directory (contents update while
the run executes); earlier runs remain preserved. The report identifies live/mock mode.
Paths are printed and also recorded in results/latest.json. Reports update at exit
and periodically during execution. Full prompts, final responses and returned reasoning
remain available separately; blank final responses are never filled with invented text.

Config paths reject escapes (including symlinks), root-directory targets and overlap.
HF cache environment is process-local to LLM10. The native bridge is a distinct binary,
reusing only Loop settings and dependency build cache, not LLM02 runtime state.
A shared model endpoint still shares capacity; filesystem isolation does not eliminate
cross-run server-load effects. Coordinate stress tests for meaningful latency results.

## Completion checklist

- [x] P0/P1: scope, scaffold, strict configuration, pinned isolated dependencies,
  explicit model resolution and finite safety defaults.
- [x] P2: final anonymous public corpus; 4,000 real prompts prepared, deterministic
  cache/checksum replay, licenses/provenance/overlap recorded; gated adapter removed.
- [x] P3: native Loop telemetry, durable intent/outcome journal, retry/backoff, uncertain
  crash outcomes, writer locks, graceful interruption and no repeat of durable completions.
- [x] P4: baseline, input/output/context growth, repetition, concurrency and expensive
  workloads; deterministic IDs/manifests and complete history reconstruction.
- [x] P5: conservative request/token/cost reservations, progressive groups, persistent
  error/rate/latency circuits, explicit safety skips and restart accounting.
- [x] P6: exact requests/conversation CSVs, grouped summaries, call-status CSV, JSONL,
  metrics, private escaped HTML, report-only regeneration, stable latest links.
- [x] P7: Loop tool-based implementation fix, tests and bounded live validation;
  real SIGINT/SIGKILL resume, background stop/resume, regression and isolation checks.
- [ ] Operator's full live stress assessment — intentionally not started here.
  This is a measurement run, not an unfinished implementation requirement.

## Verification and important limits

Final regression: **112 passed, 1 skipped**; **48 LLM10 tests passed through Loop**.
Default preparation produced manifest data/manifests/d290d580ed0033ce9e35e856.json.
Existing bounded live sarvam-30b validation: 4 HTTP200 responses, two baseline calls
plus a two-turn conversation; resume added no calls. All responses hit a 128-token
validation cap and contained reasoning-only text, preserved in the reports. This
does not establish full stress behavior or answer quality.

Exact commands, counts, native bridge provenance and Loop session evidence are in
llm10/VALIDATION.md. llm10/README.md is the current operator guide.

Input sizes are labeled estimates; provider usage drives measured metrics. TTFT is
unavailable, not fabricated. Client reservations are conservative, not absolute
server-side billing guarantees. Default 25,000 attempts/50M reserved tokens and
branch circuits may stop early. Stops/skips are explicit and do not prove endpoint
protection. Exit 2 can represent a safety-limited run, not a pipeline crash.
Changing config/corpus/code creates a new run; identical configuration resumes.
Do not modify execution code during an operator run and expect its fingerprint unchanged.

## Historical progress (earlier scope)

Rows below retain the earlier history. Gated-source blockers were resolved by the
user's explicit scope change, not by bypassing access controls.

| Date (Asia/Kolkata) | Part | State | Evidence / next action |
|---|---|---|---|
| 2026-10-05 | P0 | Complete | Read spec; inspected setup; archived LLM02 plan; created handoff. No implementation/inference. Next: P1. |
| 2026-10-05 | P1/P2 | In progress | Isolated llm10/.venv, strict configs, pinned dependencies, preparation CLI/adapters and 22 passing configuration/dataset tests. Public-source download in progress. HF check returned GatedRepoError for PromptSuite; user asked to authorize locally. Root LLM02 process found active and left untouched. |
| 2026-10-05 | P1 | Complete | Loop bash test execution verified in session journal; model describe resolved sarvam-30b; CLI/config tests and isolated dependency check pass. See llm10/VALIDATION.md. |
| 2026-10-05 | P2 | Partial | Public 2,500-prompt corpus prepared and cache replay identical; 12-prompt smoke manifest has 36 calls. PromptSuite still gated, no substitute source. |
| 2026-10-05 | P3/P4 | Partial | Added journal and seven-family manifest builder; fixed short-input padding regression; 27 new tests pass, complete regression suite 91 passed/1 skipped. No inference. |
| 2026-10-05 | P3–P6 | Implemented; initial verification | Added separate instrumented Loop bridge, executor, persisted retries, conservative budget reservations, branch stops, exact CSV/JSONL/HTML and isolated background supervisor. First execution suite passed including real SIGINT/SIGKILL resume. P7 checks and bounded live validation in progress. |

| 2026-10-05 | P3–P6 | Complete | 109 regression tests passed/1 skipped. All seven families, retries, SIGINT/SIGKILL resume, safety circuits, exact reports and background stop/resume verified. Loop applied metrics fix and ran tests. |
| 2026-10-05 | P7 | Partial external verification | Loop ran four-call sarvam-30b live check; 4 HTTP200 responses with exact reasoning/usage persisted, resume added no calls. PromptSuite gated access remains; full stress not launched. |
| 2026-10-05 | Final scope | Complete | Removed gated source and credential setup, finalized 4,000 anonymous public prompts, enforced isolation and stable report paths. 112 tests passed/1 skipped; preparation-only verified. Full live run left for user. |

## Next developer / maintenance rule

LLM02 relocation (2026-10-07): its configs, entry scripts, environment, data,
results, tests, operator documentation and native bridge are now under llm02/.
Its former root entry points are removed. Existing run IDs/evidence are preserved;
see llm02/RELOCATION.md. Combined regression command now uses
`llm10/.venv/bin/python -m pytest -q` from the workspace root; LLM02-only tests
use `.venv/bin/python -m pytest -q` from llm02/. LLM10's active run was untouched.

No implementation blocker remains under the revised scope. The user can launch
the default command now. Check live/mock mode, permanent run ID and branch-stop
reasons when interpreting reports. Preserve all previous runs and LLM02 files.

For future changes: update this tracker after each completed part with files,
verification command/result and exact next action. Record failed checks and scope
decisions; never turn unexecuted measurements into completed validation claims.
Keep large transcripts in llm10/VALIDATION.md and user instructions in llm10/README.md.
