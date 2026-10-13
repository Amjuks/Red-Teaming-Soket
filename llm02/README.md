# LLM02 — Sensitive Information Disclosure

Tests whether a model reveals protected information in its answers or returned
reasoning. It covers single-turn and multi-turn attacks, benign controls, local
detectors and an optional semantic judge. Reports include findings, exact evidence,
errors and ungraded results.

The default uses **Loop / soket / sarvam-30b**, including the semantic judge.
This machine already has the connection; no additional API key is needed.
The cached default selection is about **5,697 cases**: eight source adapters plus
44 controlled synthetic cases. Preparation reports the actual selected count.

## Setup

Skip installation if `.venv` already works. For a fresh environment:

```bash
cd /home/aman/owasp/llm02
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
```

Use Python 3.10+ and an existing Loop installation at `/home/aman/loop` with its
provider configured. Rust/Cargo is needed to build the bridge; the runner builds
it when absent. If `venv` is unavailable, use `virtualenv .venv`.

## Run, monitor and resume

```bash
cd /home/aman/owasp/llm02
.venv/bin/python background.py start
.venv/bin/python background.py status
tail -f logs/latest.log
```

Stop gracefully with `.venv/bin/python background.py stop`. Repeat `start` with
the same configuration to resume. Closing the terminal does not stop the job;
Ctrl+C while following a log stops only `tail`. A reboot requires starting again.
For foreground execution, use `.venv/bin/python run.py` and Ctrl+C to stop.

Completed results are reused. Terminal errors are not automatically retested.
Changing configuration, data or execution code creates a different run identity.
Crash-ambiguous requests are recorded rather than silently resent by default.

## Other things you can do

```bash
# Prepare datasets without model calls:
.venv/bin/python run.py --prepare-only

# Small live check:
.venv/bin/python run.py --config config.smoke.yaml

# Offline model demonstration (not a real-model assessment):
.venv/bin/python run.py --config config.mock.yaml

# Rebuild a stopped run from saved evidence:
.venv/bin/python run.py --report-run results/sarvam-30b/latest
```

Edit `config.yaml` to choose the model, enabled datasets, per-dataset limits,
concurrency, retries, output tokens and semantic judge. A dataset can be `false`,
`true`, or `{enabled: true, limit: 10}`. Use `--config PATH` for another configuration.
The sources are PrivAwareBench, PasswordEval, PEEP, ConfAIde, DecodingTrust,
PrivacyLens, Comparison Dataset and ALERT. These are local adaptations; coverage
records source URLs, checksums, exclusions and transformations. They do not claim
the original benchmark protocols or scores.

## Open reports

From the workspace root, refresh a snapshot without interrupting a run:

```bash
cd /home/aman/owasp
python3 export_reports.py --benchmark llm02
```

Open **[the complete LLM02 Markdown assessment](../runs/llm02/report.md)**.
This is the actual report, not a landing page. It uses the same sections and
[structured schema](../report.schema.json) as the other risks. The adjacent
`report.json` contains normalized metrics, coverage, findings and all native details.
Re-export to refresh the same files; snapshots no longer accumulate.

Start with errors and ungraded counts, then inspect disclosure findings and
category breakdowns. Attack Success Rate uses **graded attack cases only**.
`NO_LEAK` means no disclosure was detected, not proof of privacy. The same-model
judge is not independent verification; inspect important findings manually.
PrivAwareBench extraction is heuristic and contextual cases can remain ungraded.

| File | What to look for |
| --- | --- |
| `report.md`, `report.json` | Human report and common machine-readable report |
| `successful_attacks.csv` | Completed attacks with detected disclosures |
| `leak_evidence.csv` | Protected value, detector, response channel and evidence |
| `conversation_turns.csv` | Exact requests, answers and returned reasoning by turn |
| `test_details.csv` | All recorded test outcomes, including ungraded cases |
| `findings.csv`, `metrics.json` | Findings, remediation, denominators and breakdowns |
| `failures.csv`, `unexecuted.csv` | Errors and missing coverage |
| `events.jsonl`, `raw_results.jsonl` | Original durable evidence and full results |

Join evidence using `test_id`. A missing final answer can still have returned
reasoning; both channels are inspected. Multiple evidence rows are not multiple
successful attacks. Markdown omits raw protected values; CSV/JSONL evidence is sensitive.
See the [shared report guide](../README.md#one-schema-for-all-risks) for the schema.

## Developer checks

From `/home/aman/owasp`, run `llm02/.venv/bin/python -m pytest -q`.
Source acquisition integration tests are opt-in with `LLM02_NETWORK_TESTS=1`.
The [workspace guide](../README.md) covers report refresh and latest-only retention.

## Failure-only investigation

Open [failed_instances.csv](../runs/llm02/failed_instances.csv) for recorded
failures only. The first columns explain the problem and expected/observed behavior;
full conversations, returned reasoning, evaluations and evidence follow. Execution,
security, output, task and assessment failures are explicitly distinguished.
Missing measurements carry reasons; non-applicable ratio columns are labeled.
See the [shared investigation guide](../README.md#investigate-failures-and-missing-measurements)
for inclusion rules and column meanings. Refresh using the workspace exporter.

For a quick, small sample, open the [preview CSV](../runs/llm02/failed_instances.preview.csv).
Generate it independently with `python3 preview_reports.py --benchmark llm02`
from the workspace root. Defaults to at most 20 complete rows and 1 MB, sampled
across the file and different case categories. Full reports remain unchanged.
