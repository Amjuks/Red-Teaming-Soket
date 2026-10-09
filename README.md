# OWASP LLM benchmarks

Three local tools test different model risks through your existing Loop connection.
No additional model API keys are needed on this configured machine.

| Benchmark | What it tests | Default scale | Guide |
| --- | --- | --- | --- |
| LLM02 | Disclosure of protected information | About 5,697 cases with cached sources | [Get started](llm02/README.md) |
| LLM06 | Tool use beyond granted permissions | 2,000 tasks × 2 variants = 4,000 tests | [Get started](llm06/README.md) |
| LLM10 | Resource consumption and endpoint limits | 4,000 prompts → 21,500 planned calls | [Get started](llm10/README.md) |

Each benchmark has its own virtual environment, configuration and saved results.
Model latency, retries and multi-turn conversations affect runtime; large runs can
take many hours or days. LLM10 includes explicit workload and budget limits.

## Setup and run

The environments on this machine are already installed. For a fresh setup, follow
the benchmark's guide above. You need Python 3.10+, Rust/Cargo for the Loop bridge,
and an existing Loop model connection. First-time dataset preparation needs internet.

For example, start LLM06 and check its progress:

```bash
cd /home/aman/owasp/llm06
.venv/bin/python run.py --background
.venv/bin/python run.py --status
```

LLM02 and LLM10 use `background.py start`, `background.py status`, and
`background.py stop`. The individual guides include exact commands and small-run
options. Repeating the same run configuration resumes saved work.

## Open reports with readable run names

Export the latest saved runs and build a single index, without making model calls
or interrupting any runner:

```bash
cd /home/aman/owasp
python3 export_reports.py
```

Open **[runs/index.html](runs/index.html)**. Select a name, then **Open report**.
You can also open the original evidence folder from that run's page.

Names look like `llm06-sarvam-30b-4000-tests-b0cf3bf0`: benchmark, model, test/call
count and a short identity suffix. Mock runs include `mock`. The suffix prevents
similar runs from being confused. Full IDs and original directories remain intact
for reliable resume and evidence links. Names appear in the report and in
`report.json` as `run.name`; the permanent identity remains `run.id`.

The index contains snapshots you have exported. They do not refresh themselves:
run the export command again for current results. Already-running processes keep
their loaded report code; exporting displays the new format without a restart.

```bash
# Refresh one benchmark, using its config.yaml output directory:
python3 export_reports.py --benchmark llm06

# Include a historical run or a run made with a different output directory:
python3 export_reports.py --benchmark llm10 --run-directory llm10/results/full-20261007/latest
```

## Read and analyze a report

1. Check the run name, model, and progress. Review errors and pending work first.
2. Read coverage and limitations before interpreting findings.
3. Open benchmark details for category breakdowns and individual evidence.
4. Use Downloads for CSV analysis or JSON processing.

All three share the same overview and [JSON schema](report.schema.json), version
`1.1.0`. Their original detailed report sections and exports remain available.

| Common field | Contents |
| --- | --- |
| `benchmark`, `run` | Benchmark, readable name, permanent ID, model, execution state |
| `progress` | Unit plus planned, completed, errored, skipped and pending counts |
| `coverage` | Original source coverage and accounting |
| `metrics` | All benchmark-specific metrics with their original denominators |
| `findings` | Common fields and evidence IDs, plus full native `details` |
| `limitations` | What the assessment does and does not establish |
| `artifacts` | Available exports, with paths relative to the report |

Counts reconcile as `planned = completed + errored + skipped + pending`.
LLM02 counts tests, LLM06 counts scenario/permission pairs, and LLM10 counts logical
workload calls; retries are separate attempts. `partial` describes unfinished work,
not process liveness. `finished` does not mean every test passed or was graded.
Unknown values remain `null`. Scores, finding counts and severity are not directly
comparable across different benchmarks.

Evidence exports can contain sensitive prompts, responses and protected values;
keep them local. LLM02's HTML omits raw protected content. Generated data, reports,
logs and the readable run index are excluded from Git.
