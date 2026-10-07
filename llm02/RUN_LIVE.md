# Live sarvam-30b assessment

## Inspect exact conversations and leaks (CSV)

New `python run.py` processes automatically export detailed CSVs at each report
checkpoint and at exit. They are alongside `report.html` in the run directory.
Existing running processes do not load code changes: use the snapshot command
below to export their evidence without stopping them.

- `successful_attacks.csv`: one row per completed successful attack, including
  system/user prompts, all final answers, returned reasoning, protected values,
  exact JSON conversations/responses, detector evidence, and judge verdict.
- `conversation_turns.csv`: one row per returned target response, with the request
  messages for that turn, separate final-answer/reasoning columns, finish reason,
  and per-turn evaluation. Context/history messages are in `request_messages_json`.
- `leak_evidence.csv`: one row per detector evidence/channel attribution, with the
  protected value, matching output quote when literal, detector method, response
  turn, and full output. Includes leaks on controls and partial/failed cases too;
  inspect `expected` and `status`. Multiple evidence rows do not mean more attacks.
- `test_details.csv`: all completed or failed test records, including ungraded cases.
- `metrics.csv`, `findings.csv`, `coverage.csv`, `configuration.csv`, `failures.csv`,
  `unexecuted.csv`: aggregate statistics, findings/remediation, dataset accounting,
  configuration, errors, and cases not yet recorded as results.
- `summary.csv`: the original compact, redacted index remains available.

`NOT_SENT` means no system message was sent. `EMPTY_FROM_PROVIDER` means the model
returned no final answer; check `returned_reasoning` and `finish_reason`. The
detector grades both returned channels, so reasoning-only exposure is distinct
from a final-answer leak. `unresolved` channel attribution is not a guessed quote;
cross-turn and transformed matches are explicitly labeled. Inputs/protected values
alone are not proof of leakage. PrivAwareBench values are heuristic candidates,
and findings need review in their original context.

Export an isolated point-in-time snapshot of a running OR stopped run (no API calls):

```bash
cd /home/aman/owasp/llm02
.venv/bin/python export_reports.py results/sarvam-30b/559aa614383253ec4780cbc9
```

The command prints the new `csv-snapshots/<timestamp>-<unique>/` folder. Repeat
it for a fresh snapshot; it does not auto-refresh. Only committed results are
included; an in-flight request has no completed test row yet.

To rebuild the main report files of a **stopped** run from saved evidence:

```bash
.venv/bin/python run.py --report-run results/sarvam-30b/559aa614383253ec4780cbc9
```

CSV files contain **unredacted sensitive benchmark content** and are mode 0600.
Do not publish them or serve the results directory publicly. CSV uses UTF-8 with
BOM, quoting and embedded newlines. Formula-like readable cells have a protective
apostrophe; `*_json` columns preserve the exact original strings, including empty
values. Spreadsheet applications may truncate display of cells over their own
limits (Excel: 32,767 characters); the CSV and JSONL files retain full text.
Reporting changes do not alter model requests, original grades or run fingerprints.

Everything is configured in `/home/aman/owasp/llm02`. No new endpoint or API key is
required. The pipeline calls Loop's `loop-app-core` and `loop-ai` libraries through
the compiled `native/loop-bridge` helper. Loop reads its existing provider, endpoint
and credentials from `/home/aman/.loop/agent` (or `LOOP_CODING_AGENT_DIR`).

Target and semantic judge: **soket / sarvam-30b**. Both are explicit in config.yaml;
there is no automatic fallback to a different model. `sarvam-30b` was added to
Loop's existing models.json catalog, preserving the other models and settings.
The original Loop source repository was not modified.

## Run in the foreground

```bash
cd /home/aman/owasp/llm02
source .venv/bin/activate
python run.py
```

Or without activating the environment:

```bash
cd /home/aman/owasp/llm02
.venv/bin/python run.py
```

This is now a **real, full assessment**: 5,697 cases with currently cached datasets
(5,653 cases across eight source adapters plus 44 synthetic controls/disclosure
tests, including seven multi-turn cases). It automatically prepares data, resumes
any matching run, executes remaining target requests, performs semantic judging
where needed, and writes final reports. It runs until cases have terminal results;
errors and unresolved judgments are recorded honestly rather than called passes.

Current limits: three concurrent cases, 120-second request timeout, up to five
retries after the initial attempt, exponential backoff, 2,048 output tokens per
target/judge request. More than 5,697 API requests may be needed because multi-turn
cases, semantic judging, and retries add requests. Actual duration depends on
provider latency and rate limits. The live benchmark has **not** been started for you.

## Run in the background (recommended)

```bash
cd /home/aman/owasp/llm02
.venv/bin/python background.py start
```

This starts a detached supervisor and prints its PID and log path. It survives
terminal/SSH disconnection. It does not require `nohup` or keeping this chat open.
Only one background assessment launched this way can run at a time.

```bash
# Watch the log. Ctrl+C exits tail only; the assessment keeps running.
tail -f /home/aman/owasp/llm02/logs/latest.log

# Check process status and durable assessment counts.
/home/aman/owasp/llm02/.venv/bin/python /home/aman/owasp/llm02/background.py status

# Gracefully stop: settle in-flight work, save progress, write partial reports.
/home/aman/owasp/llm02/.venv/bin/python /home/aman/owasp/llm02/background.py stop

# Resume later with the same configuration.
/home/aman/owasp/llm02/.venv/bin/python /home/aman/owasp/llm02/background.py start
```

A machine reboot or supervisor crash requires running `start` again. The journal
persists progress. Configuration, dataset or implementation changes create a new
run identity; keep them unchanged to resume the same assessment.

## Where to see everything

These stable paths appear when the full run starts:

| Path relative to `/home/aman/owasp/llm02` | Contents |
|---|---|
| `logs/latest.log` | Live stdout/stderr, case progress, startup problems and final exit status |
| `logs/background.json` | Supervisor/assessment PIDs, log path, timestamps, exit code |
| `results/sarvam-30b/latest/state.json` | Total, completed, remaining, percentage, leaks, errors, ungraded count; updated after each case |
| `results/sarvam-30b/latest/report.html` | Human report, findings, severities, dataset coverage and recommendations |
| `results/sarvam-30b/latest/metrics.json` | Metrics, denominators and structured findings |
| `results/sarvam-30b/latest/summary.csv` | Flat per-test results |
| `results/sarvam-30b/latest/raw_results.jsonl` | Full questions, conversations, responses/reasoning, usage, retries, detector evidence and judge results |
| `results/sarvam-30b/latest/events.jsonl` | Authoritative live journal, fsynced after each request/response/result |
| `results/sarvam-30b/latest/failures.jsonl` | Errors and uncertain requests |
| `results/sarvam-30b/latest/coverage.json` | Source URLs, checksums, dataset counts and adaptations |
| `results/sarvam-30b/latest/config.json` | Effective configuration and resolved Loop identity; no credentials |
| `results/sarvam-30b/latest.json` | Pointer to the immutable run-ID directory behind `latest` |

HTML/CSV/JSONL exports are written initially, refreshed roughly every 60 seconds
when a case completes, and finalized at exit. The journal and checkpoint contain
the most recent durable progress between exports. Human reports mask sensitive
evidence; full raw evidence is stored in a directory with restricted permissions.

Open `results/sarvam-30b/latest/report.html` directly in your browser or editor.
No web server is needed. To regenerate a report from a saved run without making
any model requests:

```bash
.venv/bin/python run.py --report-run results/sarvam-30b/latest
```

`status: finished` with `remaining: 0` means all cases reached terminal outcomes.
Check `errors` and `ungraded` too: a finished run may have either. Background exit
code 0 means no execution errors/unexecuted cases; code 2 means errors or unfinished
work, not necessarily detected leaks. Leak findings do not themselves make the
process fail. Grading coverage is shown separately.

## Validated before handoff

- Loop-backed live smoke: seven cases, all completed, no transport errors or
  ungraded outcomes. Responses identify `sarvam-30b`; transport is `loop-ai`.
- Includes a real two-turn conversation and a real semantic-judge verdict.
- Smoke report: `results/sarvam-30b-smoke/latest/report.html`.
- All 5,697 live-default cases prepared successfully without starting the full run.
- Native transport tests verify exact role/message preservation, Loop credentials,
  token usage, no agent tool injection, retries, and no silent model fallback.
- All 55 tests pass, including detached completion, duplicate-start prevention,
  graceful background stop and resume without repeating completed requests.

The same model currently judges ambiguous cases. Treat semantic findings as
model-judged evidence, not an independent ground truth. Dataset adaptations and
known detector limitations remain documented in README.md and VALIDATION.md.
Network/provider failure can still produce errors; bounded retries cannot guarantee
provider availability. A hard-crash request with no durable response defaults to
UNCERTAIN rather than automatically charging for a duplicate request.

## Other commands

```bash
# Small live test only, in a separate output directory.
.venv/bin/python run.py --config config.smoke.yaml

# Zero-cost offline synthetic demonstration (no longer the default).
.venv/bin/python run.py --config config.mock.yaml

# Validate tests, including cached/upstream dataset acquisition.
LLM02_NETWORK_TESTS=1 .venv/bin/python -m pytest -q

# Rebuild the API bridge after intentionally updating Loop's libraries.
cargo build --locked --manifest-path native/loop-bridge/Cargo.toml
```
