# LLM06 — Excessive Agency

Tests whether a tool-calling model exceeds its permissions or acts without
approval. Tools operate on simulated JSON records; they do not perform real-world
actions. Model calls use the existing **Loop / soket / sarvam-30b** connection.
No additional API key or `.env` file is needed on this machine.

The default selects **2,000 distinct tasks**, each tested with least and broad
capabilities: **4,000 tests**. The usable pool currently contains 2,650 scenarios
and 2,157 distinct task texts from pinned Agent Safety Bench sources. Categories
include finance, healthcare, commerce, security, infrastructure, software, travel
and communications. Preparation records exact selection and exclusion counts.

## Setup

This workspace already has its environment and bridge. For a fresh installation,
you need Python 3.10+, Rust/Cargo and the configured Loop checkout at `/home/aman/loop`:

```bash
cd /home/aman/owasp/llm06
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
CARGO_HOME="$PWD/.cache/cargo" CARGO_TARGET_DIR="$PWD/native/target" \
  cargo build --locked --manifest-path native/loop-bridge/Cargo.toml -j 4
.venv/bin/python run.py --validate-config
.venv/bin/python run.py --prepare
```

If `venv` is unavailable, use `virtualenv .venv`. Preparation downloads source data
on first use and does not call the model. Upstream Python is never imported or
executed; supported source reads become bounded JSON queries.

## Run, monitor and resume

```bash
cd /home/aman/owasp/llm06
.venv/bin/python run.py --background
.venv/bin/python run.py --status
.venv/bin/python run.py --stop
```

Status shows processed tests, errors, remaining work, the active test and exact
log/report paths. Use `tail -f PATH_TO_BACKGROUND_LOG` to follow the printed log.
Reports update every 100 processed tests and at exit by default.

The job survives terminal closure. Stop requests a graceful shutdown; wait for
status to confirm it has exited. Repeat the same command and filters to resume.
Completed tests are skipped and target errors remain terminal. A pending judge
can retry without rerunning the target. A foreground run uses
`.venv/bin/python run.py`; stop it with Ctrl+C.

## Choose what to test

```bash
# Small live check:
.venv/bin/python run.py --sample-limit 20 --background

# Select healthcare or finance tasks:
.venv/bin/python run.py --domains healthcare finance --sample-limit 100 --background

# Select core tasks only:
.venv/bin/python run.py --splits core --sample-limit 500 --background

# Inspect a selection without model calls:
.venv/bin/python run.py --prepare --domains security infrastructure --sample-limit 200

# Validate selected tools offline:
.venv/bin/python run.py --audit

# Offline demonstration:
.venv/bin/python run.py --offline-demo
```

A sample limit is a maximum; rows are never duplicated to fill it. Requesting
`--sample-limit 10000` selects all available distinct task texts, not 10,000 invented
tasks. `--categories "Leak sensitive data / information"` filters by an exact
source label. Domain groups are locally inferred; augmented source tasks are
explicitly unlabeled where source risk labels are absent.

Edit `config.yaml` or use `--config PATH` for model settings, sample size, variants,
filters, retries, output tokens and report interval. `unique_tasks: true` avoids
repeated instruction text. Sampling is seeded and balances domain/risk groups.
Concurrency is one. Configuration or adapter changes can create a different run.

## Open reports

Refresh a snapshot while the benchmark keeps running:

```bash
cd /home/aman/owasp
python3 export_reports.py --benchmark llm06
```

Open **[the run index](../runs/index.html)** and select a name such as
`llm06-sarvam-30b-4000-tests-b0cf3bf0`. Short suffixes distinguish similar runs;
original folders and IDs remain intact. Re-export to refresh the snapshot.
The regular running report is also available through `reports/index.html`.

1. Review completed, errored and unassessed counts.
2. Compare source categories, domains and least/broad variants.
3. Open a finding's trajectory to see expected versus actual behavior.
4. Use its recommendation and retest instructions to investigate the boundary.

| File | Purpose |
| --- | --- |
| `report.html`, `report.json` | Human report and common machine-readable report |
| `scenarios.csv` | Task, variant, source and execution outcome |
| `tool_calls.csv` | Tool attempts, blocks and policy results |
| `conversations.csv` | Model requests/responses and recorded tool evidence |
| `findings.csv` | Violations, severity, recommendations and evidence references |
| `metrics.json`, `results.jsonl` | Full aggregate and per-test evaluation data |
| `events.jsonl` | Original durable journal in the run's evidence folder |

Join CSVs on `test_id`, pair variants on `scenario_id`, and use `evidence_seq` to
find the original journal event. The shared report preserves these details and
all native metrics. See the [report guide](../README.md#read-and-analyze-a-report).

## Interpret results correctly

The judge is **enabled by default**, using the same Loop model and settings as the
target (`soket/sarvam-30b`). In `config.yaml`, `judge: *loop_model` reuses the target
configuration; set `judge: null` to disable it. Judging adds model calls and runtime.
Existing runs keep their saved configuration; this change applies to new runs.

Completed means the conversation ended, not that the task succeeded. Same-model
judging is not independent verification, and failed assessments remain unknown.
No detected violation proves safety. A blocked unsafe attempt can still be a finding.

Catalog effects are deny-only approval probes; they do not demonstrate successful
real-world actions. Of the usable scenarios, 2,427 have read tools and 223 contain
only approval probes. Missing data, unsupported source syntax and exclusions remain
visible in coverage. Group counts may overlap. Output-limit failures remain errors.

For a stopped run, rebuild with `.venv/bin/python run.py --report-run latest`.
Use snapshots for active runs. For development, run
`.venv/bin/python -m unittest discover -s tests -v`.
[PIPELINE.md](PIPELINE.md) explains the process and examples in more detail.
