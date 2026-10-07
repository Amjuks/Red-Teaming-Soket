# OWASP LLM10:2025 — ready to run

All seven workload families run through the existing **Loop / soket / sarvam-30b**
connection. Dataset downloads are public and explicitly anonymous: no Hugging Face
token, gated access or extra model API key is needed. The default corpus is
**4,000 prompts: 2,000 Alpaca + 2,000 Instruct-v3**, seed 42. The previously gated
source has been removed, as requested. This changes the original dataset mix.

A working Loop installation/provider connection is still required for live inference.
This does not make an arbitrary hosted model free or credential-free on a new machine.
The current machine is configured; no additional credential setup is required here.
Dataset access is free of authentication, not free of license obligations:
Alpaca is CC-BY-NC-4.0; Instruct-v3 has CC-BY-SA-3.0 and underlying source terms.
Internet is needed for first downloads; the default 4,000-prompt corpus is now cached.

## Run

```bash
cd /home/aman/owasp/llm10
source .venv/bin/activate
python run.py
```

Or run detached, surviving terminal/SSH disconnection:

```bash
cd /home/aman/owasp/llm10
.venv/bin/python background.py start
tail -f logs/latest.log
```

```bash
.venv/bin/python background.py status
.venv/bin/python background.py stop
# Resume the same configuration:
.venv/bin/python background.py start
```

Ctrl+C while following the log stops tail only. The supervisor survives terminal
disconnection, not reboot. In the foreground, Ctrl+C settles in-flight requests and
saves progress. Repeat the same run command to resume.

## Where reports appear

After your run starts:

- **HTML:** /home/aman/owasp/llm10/reports/latest/report.html
- **CSV and raw evidence:** /home/aman/owasp/llm10/results/latest/
- **Progress:** /home/aman/owasp/llm10/results/latest/state.json
- **Background log:** /home/aman/owasp/llm10/logs/latest.log

The latest links are created when execution starts, not by preparation-only.
They refer to the most recently started run for that output root, which can be a
mock if you explicitly run mock configuration there. Check the report's model/mode.
Each run also retains its own fingerprint directory. Starting a new run never
deletes an older one. results/latest.json contains the exact permanent paths.
Alternate configs can have separate output roots; the console prints their locations.

### Evidence files

- requests.csv: one row per actual API attempt, including failures/retries, full
  messages, final response, returned reasoning, usage, latency, HTTP status, finish
  reason, rate-limit information and optional estimated cost.
- conversations.csv: every request/history/output message and returned reasoning.
  Reconstruct using conversation_id, call_id, attempt_id and message_index.
  Usage repeats per message row: do not sum this CSV for billing totals.
- summary.csv: family/level/dataset/task aggregates, matched-baseline amplification,
  planned/successful/skipped/unfinished counts and observed limits.
- call_status.csv: terminal logical-call decisions, including skip reasons.
- results.jsonl: complete attempt outcomes; events.jsonl: authoritative fsynced journal.
- metrics.json, state.json, config.json, identity.json, manifest.json, coverage.json.

Exact strings remain in JSON columns. CSV supports Unicode/multiline cells and
guards spreadsheet formulas with an apostrophe. Empty final answers are not invented;
returned reasoning has its own channel. Success means a successful API response,
not answer correctness or proof of vulnerability. Report files contain unredacted
data and have restricted permissions: keep them local.

Reports update periodically as calls complete (default 60 seconds), and at exit.
Rebuild a stopped run's reports without API calls:

```bash
.venv/bin/python run.py --report-run results/<run_id>
```

## Isolation from LLM02

LLM10 has its own environment, configs, cache, run fingerprints, journal locks,
supervisor, logs, results and reports. Path validation rejects escaping, symlinked
external and overlapping output/cache paths. The separate native bridge does not
replace the LLM02 bridge. No LLM02 process or result is stopped or changed.

**Shared endpoint caveat:** both projects can use the same model server. Separate
directories/processes do not provide dedicated server capacity. Coordinate stress
runs if you need uncontaminated latency/rate-limit measurements. See ISOLATION.md.

## Bounds and interpretation

Default schedule: **21,500 planned calls before retries** across all seven families.
Limits: 25,000 total attempts; 50M prepaid token reservations; max concurrency 8;
input estimate ceiling 8K; requested output ceiling 4K; baseline output cap 512;
8 context turns; 120-second timeout; at most 3 retries. Safety stops can reduce
the executed count. The configured test ceiling is never evidence of unlimited capacity.

Reservation accounting conservatively uses input UTF-8 bytes plus chat overhead
and the requested output maximum, without refunds for unknown/failed attempts.
Missing usage is not zero. Actual usage exceeding reservations stops new dispatch.
This is not a hard billing guarantee against server-side cap violations or unknown
tokenizer/template/pricing behavior; use server-side hard quotas too. Cost caps
require both input/output prices and exclude unmodeled provider charges.

Three consecutive errors or 429s stop a family. Severe latency, long Retry-After,
413 size rejection or global budgets also stop further applicable work. In-flight
calls can finish after a circuit opens. Stops and budget consumption survive restarts.
Long baseline inputs can be safety-skipped and remain visible in the reports.

Input-growth sizes use a labeled UTF-8-bytes/4 estimate, not an exact tokenizer.
Measured usage comes from the provider. TTFT is unavailable through the current Loop
completion API and stays null. Latency includes bridge process overhead.
Length finish reason shows a requested output cap, not proof of a server-wide policy.
Client skips/timeouts/missing measurements do not count as endpoint protection.

Durably completed requests are not repeated after restart. Crash-ambiguous calls
default to UNCERTAIN without resend; uncertain_policy: retry explicitly accepts
possible duplication. Idempotency keys cannot guarantee remote exactly-once execution.
Completed errors/skips are terminal. Config/corpus/implementation/bridge changes
create new run IDs; reporting-only edits do not.

Exit 0 means every planned logical call succeeded. Exit 2 means blocked, failed,
uncertain, safety-limited or unfinished work: consult the report, not just exit code.

## Developer checks

### Fresh full assessment (2026-10-07)

Use `config.full.yaml` for all seven families, 4,000 public prompts and 21,500
scheduled calls. It has fresh output roots `results/full-20261007` and
`reports/full-20261007`, separate from the previous run. Its 350-million
reservation ceiling covers the conservative 277,851,080 first-pass upper bound
for the prepared manifest, with some retry headroom; reservations count input
bytes plus overhead and requested output, not actual provider usage. The 25,000
attempt ceiling and branch safety stops remain in force; not every retry or
level is guaranteed to execute. Never remove safeguards to force completion.

```bash
cd /home/aman/owasp/llm10
.venv/bin/python background.py start --config config.full.yaml
.venv/bin/python background.py status --config config.full.yaml
tail -f logs/latest.log
# Graceful stop:
.venv/bin/python background.py stop --config config.full.yaml
```

Or run in the foreground: `.venv/bin/python run.py --config config.full.yaml`.
No extra endpoint, dataset token or API key needs filling in: existing Loop
configuration resolves soket/sarvam-30b. To quantify financial impact, fill BOTH
pricing rates with actual input/output prices per million tokens and the correct
currency before starting. Otherwise cost is explicitly unassessed. Set max_cost
only with known pricing and an approved budget. Document gateway quotas, service
SLO and collect gateway/model resource logs externally to confirm causality.

HTML: `reports/full-20261007/latest/report.html`; evidence CSVs, JSONL and state:
`results/full-20261007/latest/`. The updated primary report includes actionable
findings automatically. Starting the same config again resumes this full run;
it does not clear previous evidence. At the earlier ~13.5s serial request latency,
21,500 calls can take several days; this is not a short smoke test.

### Interpreting risk, including an ongoing run

From `/home/aman/owasp`, generate a read-only snapshot without model calls:

```bash
llm10/.venv/bin/python -m llm10.report llm10/results/latest
```

Open `llm10/reports/latest/analysis/report.html`. The matching CSVs are under
`llm10/results/latest/analysis/`: `findings.csv` explains observations, possible
impact, remediation, retest and evidence attempt IDs; `control_assessment.csv`
shows coverage and inconclusive families. Join attempt IDs to `requests.csv`
or `conversations.csv` for exact inputs, final answers, reasoning and errors.
Rerun the command to refresh the snapshot while execution continues. It does not
overwrite active execution reports or change the run identity.

A confirmed risk requires reproducible impact and a violation of a declared
server quota or service objective. Large token counts, missing 429s, client
safety stops and provider outages alone do not establish a vulnerability.
Cost without pricing is unknown, not zero. Context baseline comparisons are
not identical-prompt experiments. Correlate provider logs and resource/billing
telemetry before assigning causality or severity. Already-running processes
retain their old report code until restart; the snapshot command uses new code.

```bash
.venv/bin/python run.py --validate-config
.venv/bin/python run.py --prepare-only
.venv/bin/python run.py --config config.mock.yaml
```

Mock and smoke configurations select 12 real public prompts and 36 planned calls.
config.live-validation.yaml is an explicit four-call transport check; config.public.yaml
is an optional smaller 2,500-prompt assessment, not needed to avoid authentication.
The normal config.yaml is already public-only.

To reinstall, create .venv with virtualenv and install requirements.lock. Keep this
environment separate from the parent LLM02 environment. Full implementation/validation
history is in ../plan.md and VALIDATION.md. Full live stress execution is left to you.
