# OWASP LLM assessments

Three benchmarks use the existing Loop model connection. No extra model API keys
are needed on this configured machine.

| Risk | Purpose | Default workload | Setup and commands |
| --- | --- | --- | --- |
| LLM02 | Sensitive information disclosure | About 5,697 cases | [Guide](llm02/README.md) |
| LLM06 | Tool use beyond permissions | 2,000 tasks × 2 variants | [Guide](llm06/README.md) |
| LLM10 | Resource consumption and endpoint limits | 21,500 planned calls | [Guide](llm10/README.md) |

## Read the actual assessments

Each link opens the complete Markdown assessment, with the same sections and
schema. There are no HTML reports or intermediate landing pages.

- [LLM02 report](runs/llm02/report.md)
- [LLM06 report](runs/llm06/report.md)
- [LLM10 report](runs/llm10/report.md)

Each report contains Summary, Run configuration, Execution progress, Assessment,
Metrics, Coverage, Breakdowns, Findings, Limitations, and Evidence and exports.
Findings include observation, impact, recommendation, retest and evidence IDs.
Open these files directly in your editor's Markdown preview.

## Setup and execution

Environments on this machine are installed. For a fresh setup, follow the risk's
guide: Python 3.10+, its own virtual environment, Rust/Cargo, and an existing Loop
connection are required. Dataset preparation needs internet on first use.

```bash
# LLM06 example:
cd /home/aman/owasp/llm06
.venv/bin/python run.py --background
.venv/bin/python run.py --status
.venv/bin/python run.py --stop
```

LLM02 and LLM10 use `.venv/bin/python background.py start`, `status`, and `stop`.
LLM06's target and judge use the same registered model by default. LLM02 has its
own disclosure judge; LLM10 assesses measured consumption without a model judge.
See each guide for small checks, selection, bounds, stop and resume behavior.

## Refresh reports without model calls

```bash
cd /home/aman/owasp
python3 export_reports.py
# Or refresh just one:
python3 export_reports.py --benchmark llm06
```

The exporter selects the latest original journal across each risk's result roots,
including LLM10's separate full-run directory. It overwrites the same Markdown and
JSON report for that risk; it does not accumulate dated report copies. Exporting
reads saved evidence without restarting a runner. Reports are snapshots: refresh
them for current results, and use the status command to check process liveness.

To remove older raw runs as well, after successfully exporting the retained run:

```bash
python3 export_reports.py --prune-history
```

Pruning refuses to proceed if any journal in that risk has an active writer. It
keeps the latest run's original journal, configuration, inputs and full evidence.
Old runs and old report snapshots are deleted. Source code and dataset caches
are retained. `--run-directory PATH --benchmark llm06` can select an explicit
saved run instead of the automatic latest selection.

## One schema for all risks

[report.schema.json](report.schema.json), version **2.1.0**, defines every report.
The Markdown and JSON are generated from the same normalized data. The adjacent
`runs/llmXX/report.json` is for scripts; the Markdown is the actual human assessment.

| Field | Same meaning across all risks |
| --- | --- |
| `benchmark`, `run` | Risk, readable name, permanent ID, model, execution state |
| `configuration` | Saved run settings |
| `progress` | Unit, planned, completed, errored, skipped and pending counts |
| `assessment` | Verdict, assessed/unassessed population, judge |
| `metrics` | Records with name, value, unit, numerator, denominator, population |
| `coverage` | Source records with counts and full provenance details |
| `breakdowns` | Dimension/group records using the same metric structure |
| `findings` | ID, status, severity, observation, impact, recommendation, retest, evidence |
| `limitations` | What the assessment cannot establish |
| `artifacts` | Evidence files, with paths relative to report.json |
| `extensions` | Lossless original benchmark metrics and coverage |

Progress reconciles as `planned = completed + errored + skipped + pending`.
LLM02 counts tests, LLM06 counts scenario/permission pairs, and LLM10 counts logical
calls; attempts and retries are explicitly identified. `partial` is unfinished
work, not process liveness. Unknown values remain `null`; they are never passes.
Shared structure does not make different risk scores directly comparable.

Use `test_id` for LLM02/LLM06 evidence and `attempt_id`/`call_id` for LLM10. Reports
link to complete CSV/JSONL evidence. LLM06 distinguishes deterministic violations
from model-judge assessments. LLM02's Markdown omits raw protected content; full
exports retain it. Keep sensitive evidence local.

Readable names such as `llm06-sarvam-30b-4000-tests-d3db6f72` remain inside reports.
Stable `runs/llmXX/report.md` paths always hold the latest assessment. Original IDs
and retained evidence paths are preserved. Generated artifacts are ignored by Git.

## Investigate failures and missing measurements

Each assessment has a **failed_instances.csv** next to its Markdown report:

- [LLM02 failed instances](runs/llm02/failed_instances.csv)
- [LLM06 failed instances](runs/llm06/failed_instances.csv)
- [LLM10 failed instances](runs/llm10/failed_instances.csv)

All three use identical columns. Start with `failure_types`, `what_went_wrong`,
`expected_behavior`, `observed_behavior` and `assessment_basis`. Then inspect
`conversation`, `returned_reasoning`, exact `conversation_json`/`responses_json`,
tool events, judge evidence, evaluation and source data. JSON fields preserve the
full recorded strings; nothing is shortened to fit a spreadsheet display limit.
Only provider-returned reasoning is available; absent reasoning is labeled.

A row is one test (LLM02/LLM06) or logical call (LLM10), with retries included.
Types distinguish security failures, explicit task failures, execution errors,
empty-answer output failures and failed/unresolved assessments. An assessment
failure means the evaluator could not decide; it is not a finding of insecurity.
LLM10 errors that later recovered have `recovered=true`. Unstarted and client-skipped
work is excluded because there is no failed model outcome to inspect. A header-only
CSV means no qualifying failures were recorded. Failure types can overlap in one row.

The shared schema is now **2.1.0**. Missing metric values have `missing_reasons`;
severity has `severity_reason`. Non-fractional metrics explicitly mark numerator
and denominator as not applicable. Nulls are preserved in JSON with explanations,
not replaced by fabricated values. Source-native data in `extensions`, raw JSON
and evidence columns stays unchanged. Refresh with `python3 export_reports.py`.

## Small previews that open quickly

Generate previews independently, without model calls or changing any full report:

```bash
cd /home/aman/owasp
python3 preview_reports.py
# One risk, or a different size (always strictly below 5 MB):
python3 preview_reports.py --benchmark llm06 --rows 15 --max-bytes 750000
```

- [LLM02 preview CSV](runs/llm02/failed_instances.preview.csv)
- [LLM06 preview CSV](runs/llm06/failed_instances.preview.csv)
- [LLM10 preview CSV](runs/llm10/failed_instances.preview.csv)

Defaults: up to **20 complete instances, at most 1,000,000 bytes per CSV**.
The hard maximum is 4,999,999 bytes, including the header and UTF-8 BOM.
The preview retains the full CSV columns and exact recorded cells; conversations
and reasoning are not truncated. Rows that cannot fit are omitted and counted.

Sampling spreads across five equal record-count regions of the entire failure
CSV and prefers different failure types, source datasets, categories and statuses.
It is deterministic (`--seed 6` by default) and retains the original row order.
This is a varied illustration, not an estimate of failure frequency or a claim to
cover every dataset case. Available space may limit diversity and row count.

Each adjacent `failed_instances.preview.json` records the original row numbers,
covered regions/labels, byte size, oversized-row count and source content hash.
Previews are separate snapshots: rerun this command after refreshing full reports.
The command streams the source, leaves it unchanged, and only replaces its own
preview files. Use `--input PATH_TO_CSV` to preview an explicit failure CSV.
