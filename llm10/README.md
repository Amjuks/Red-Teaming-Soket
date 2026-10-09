# LLM10 — Unbounded Consumption

Measures model resource consumption and endpoint behavior across seven workload
families: baseline, input growth, output growth, context growth, repetition,
concurrency and expensive workloads. It records usage, latency, failures, observed
limits and control coverage under explicit client budgets.

The default uses **Loop / soket / sarvam-30b** and 4,000 public prompts: 2,000 Alpaca
and 2,000 Instruct-v3. These produce **21,500 planned calls before retries**. Existing
Loop configuration supplies the model connection; no additional model API key or
dataset token is needed here. First downloads require internet. Source license
terms still apply: Alpaca is CC-BY-NC-4.0; Instruct-v3 includes CC-BY-SA-3.0 and
underlying source terms.

## Setup

The environment on this machine is installed. For a fresh setup, use Python 3.10+,
Rust/Cargo and the existing configured Loop checkout at `/home/aman/loop`:

```bash
cd /home/aman/owasp/llm10
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python run.py --validate-config
.venv/bin/python run.py --prepare-only
```

If `venv` is unavailable, use `virtualenv .venv`. Preparation downloads and caches
source data without model calls. The runner builds its Loop bridge when needed.

## Run, monitor and resume

```bash
cd /home/aman/owasp/llm10
.venv/bin/python background.py start
.venv/bin/python background.py status
tail -f logs/latest.log
.venv/bin/python background.py stop
```

Repeat `start` with the same configuration to resume. The detached job survives
terminal closure, but requires restarting after a reboot. Ctrl+C while following
the log stops only `tail`. For foreground execution, use `.venv/bin/python run.py`.

Reports update periodically (default 60 seconds) and at exit. Saved calls are not
repeated. Completed errors/skips remain terminal, and ambiguous crash outcomes are
not automatically resent. Configuration, corpus or execution changes create a new
run identity. Large runs may take days, depending on provider throughput.

## Other things you can do

```bash
# Small live workload:
.venv/bin/python run.py --config config.smoke.yaml

# Mock model demonstration:
.venv/bin/python run.py --config config.mock.yaml

# Larger reservation budget with its own output directories:
.venv/bin/python background.py start --config config.full.yaml
.venv/bin/python background.py status --config config.full.yaml
.venv/bin/python background.py stop --config config.full.yaml

# Rebuild reports for a stopped run without model calls:
.venv/bin/python run.py --report-run results/latest
```

Edit `config.yaml` to choose dataset counts, workload sizes, levels, model, timeout,
retries and safety budgets. Default ceilings include 25,000 attempts, 50 million
reserved tokens and concurrency 8. Client stops can reduce executed coverage.
`config.full.yaml` uses a 350-million reservation ceiling and separate
`results/full-20261007` and `reports/full-20261007` roots. It retains attempt limits
and failure stops. Reservations are conservative estimates, not actual billed usage.

Prices default to unknown. Supply actual input and output prices to estimate cost.
Use server-side quotas for hard enforcement; client budgets are not a billing
guarantee. Simultaneous benchmarks sharing the endpoint can affect latency results.

## Open reports

From the workspace root, refresh the default run without interrupting execution:

```bash
cd /home/aman/owasp
python3 export_reports.py --benchmark llm10

# For the separate full configuration:
python3 export_reports.py --benchmark llm10 --run-directory llm10/results/full-20261007/latest
```

Open **[the run index](../runs/index.html)** and choose a readable name such as
`llm10-sarvam-30b-21500-calls-abcdefgh`. Names retain a short suffix; original folders
and permanent IDs remain intact. Re-export to refresh snapshots. The regular
running report is at `reports/latest/report.html` for the default output root.

Start with successful, skipped and unfinished calls, then read security
interpretation, control coverage, workload comparisons and representative evidence.

| File | What it contains |
| --- | --- |
| `report.html`, `report.json` | Human report and common machine-readable report |
| `requests.csv` | Each API attempt, messages, answers, usage, latency and errors |
| `conversations.csv` | Messages and returned reasoning, with join identifiers |
| `summary.csv` | Family/level/dataset aggregates and matched-baseline amplification |
| `call_status.csv` | Terminal logical-call decisions and skip reasons |
| `findings.csv`, `control_assessment.csv` | Observations, interpretation, retests and coverage |
| `metrics.json`, `results.jsonl` | Complete aggregates and attempt outcomes |
| `events.jsonl` | Original journal in the run's evidence folder |

Join evidence with `call_id`, `attempt_id`, `conversation_id` and `message_index`.
Usage repeats on message rows: **do not sum conversations.csv for billing**.
Reports contain full, unredacted evidence and should remain local.
See the [shared report guide](../README.md#read-and-analyze-a-report).

## Interpret results correctly

High consumption alone is not a confirmed vulnerability. Confirmation requires
repeatable impact and violation of a declared server policy or service objective.
Missing 429s do not prove no rate limit; client skips do not prove server protection.
A length finish reason reflects a requested output cap, not necessarily a server cap.

Unknown usage, cost and time-to-first-token remain unknown, not zero. API success
does not establish answer correctness. Context comparisons use changing history;
shared endpoint activity can confound timing. Review provider/resource logs for
causality. Exit code 2 can mean failed, skipped, safety-limited or unfinished work;
consult the report rather than the exit code alone.

For developer checks, run `llm10/.venv/bin/python -m pytest tests/test_llm10_*.py`
from `/home/aman/owasp`. [VALIDATION.md](VALIDATION.md) records earlier checks.
