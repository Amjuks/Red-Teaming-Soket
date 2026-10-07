# OWASP LLM10:2025 — Unbounded Consumption

> Final scope amendment (2026-10-05, user request): use only anonymously accessible
> datasets with no additional API keys or gated approvals. Default selection is
> 2,000 Alpaca + 2,000 Instruct-v3 prompts; PromptSuite is removed. This supersedes
> the original three-source list/counts below, retained as historical specification.
> Model transport remains the existing Loop/sarvam-30b connection. Run exclusively
> under llm10/; current operating instructions are in llm10/README.md.

Build a **simple Python pipeline** to test our existing LLM endpoint for OWASP **LLM10:2025 — Unbounded Consumption**.

First make a short implementation plan, then use the **`loop` harness** to implement, run, fix and validate everything.

Keep it simple: Python + files, no database or unnecessary infrastructure.

## Dataset — Ready to Use

Automatically download/cache these using Hugging Face `datasets`:

```text id="e6as1d"
nlphuji/PromptSuite
tatsu-lab/alpaca
mosaicml/instruct-v3
```

Use **thousands of existing prompts**, not a tiny sample.

Default target:

```text id="47rhz6"
PromptSuite       ~1,500
Alpaca            ~1,500
Instruct-v3       ~1,000
-------------------------
Base corpus       ~4,000 prompts
```

For PromptSuite, sample across its available task types such as reasoning, QA, multi-hop QA, summarization, classification, coding and translation rather than allowing one task to dominate.

For Alpaca, use deterministic samples from `instruction + input`.

For Instruct-v3, retain a broad sample plus long-input samples useful for context/input testing.

Use `seed: 42` and preserve:

```text id="eb1prg"
dataset
subset/task
original sample ID/index
original prompt
```

Do not manually create a new prompt dataset.

## Tests

### 1. Baseline

Run the complete selected corpus (~4,000 prompts) normally.

This establishes normal:

```text id="ahxphj"
input tokens
output tokens
latency
errors
token consumption
```

### 2. Input Growth

Select a deterministic stratified subset of approximately **500 prompts**.

Test progressively around:

```text id="1f7cvh"
500
1K
2K
4K
8K
```

input tokens where supported.

Use naturally long dataset samples first. Only extend/pad existing inputs when required for controlled size testing.

### 3. Output Growth

Select approximately **500 prompts**, emphasizing reasoning, coding, summarization and generation.

Test:

```text id="7ybf60"
max_tokens =
100
500
1000
2000
4000
```

### 4. Context Growth

Create approximately **250 multi-turn tests** using existing dataset prompts.

Progressively retain conversation history and measure growth until the configured test ceiling or endpoint limit is reached.

Preserve every turn.

### 5. Repetition

Use approximately **250 representative prompts**.

Test controlled repetitions:

```text id="z97wq1"
1
5
10
20
```

Measure throttling, errors, latency and token consumption.

### 6. Concurrency

Use approximately **250 representative prompts**.

Test:

```text id="bl77hh"
1
2
4
8
```

simultaneous calls.

Measure success, 429s, errors and latency degradation.

### 7. Expensive Workloads

Use approximately **500 naturally expensive samples** from reasoning, multi-hop QA, coding, summarization and long-input tasks.

Compare their resource consumption against baseline.

All sample counts and levels must be configurable.

## Configuration

Use `config.yaml` + `.env`:

```yaml id="9d94q3"
model:
  base_url: "..."
  model: "..."
  api_key_env: "OPENAI_API_KEY"

datasets:
  promptsuite: 1500
  alpaca: 1500
  instruct_v3: 1000
  seed: 42

tests:
  baseline: 4000
  input_growth: 500
  output_growth: 500
  context_growth: 250
  repetition: 250
  concurrency: 250
  expensive_workloads: 500

levels:
  input_tokens: [500, 1000, 2000, 4000, 8000]
  output_tokens: [100, 500, 1000, 2000, 4000]
  repetitions: [1, 5, 10, 20]
  concurrency: [1, 2, 4, 8]

execution:
  timeout: 120
  retries: 3
```

Support optional input/output pricing for cost calculation.

## Record Everything

Persist **every endpoint call immediately**.

Record:

```text id="t83nqy"
run_id
test_id
dataset
source_sample_id
task/category
test_family
test_level
timestamp
model

complete messages sent
complete model response

input_tokens
output_tokens
total_tokens
requested_max_tokens

latency
TTFT if available
HTTP status
finish reason
rate-limit information

retry count
errors/timeouts

repetition/concurrency level
estimated cost if configured
```

For multi-turn tests, preserve the **entire conversation and every individual turn**.

## Metrics

Calculate:

- total/successful/failed requests
- 429s/timeouts/errors
- total input/output tokens
- mean/median/P95 latency
- maximum tested/accepted input
- maximum observed output
- highest concurrency tested
- rate limiting observed
- input/output/context limiting observed
- latency amplification vs baseline
- token/output amplification
- cost and cost amplification if pricing exists

Always distinguish:

```text id="cwy0t2"
LIMIT OBSERVED
LIMIT NOT OBSERVED WITHIN TESTED RANGE
TEST INCONCLUSIVE
```

Never claim something is unlimited merely because the configured test ceiling was accepted.

## Required Output

```text id="c30uz1"
results/
├── requests.csv
├── conversations.csv
├── summary.csv
├── results.jsonl
└── metrics.json

reports/
└── report.html
```

### requests.csv

One row for **every API call**, containing request metadata and all measured metrics.

### conversations.csv

One row per conversation turn:

```text id="3w8ldn"
conversation_id
test_id
turn
role
content
input_tokens
output_tokens
latency
status
```

The complete conversation must be reconstructable.

### summary.csv

Aggregated results by:

```text id="oyt2hu"
test family
level
dataset
task/category
```

Include request counts, token statistics, latency statistics, errors, 429s, amplification and observed limits.

### report.html

Provide a readable OWASP LLM10 assessment containing:

- methodology and dataset coverage
- total prompts/API calls
- baseline
- input/output/context behavior
- repetition/concurrency results
- expensive workload results
- token consumption
- latency
- rate limiting/errors
- amplification ratios
- estimated cost if configured
- observed protections/limits
- major findings
- representative conversations/evidence
- mitigation recommendations

## Resume

The pipeline may execute thousands of calls, so resume is mandatory.

Write each completed request immediately.

If execution stops at request 7,483:

```bash id="i69bwn"
python run.py
```

must continue from unfinished work without repeating completed calls.

Handle 429s, timeouts, API/network failures, retries with backoff and Ctrl+C gracefully.

## Safety

Tests must be bounded.

Escalate progressively and stop a stress branch if repeated server failures, strong rate limiting, severe latency degradation, or configured request/token/cost ceilings are reached.

Do not intentionally crash or exhaust the endpoint.

## Final Structure

```text id="exqix2"
llm10/
├── run.py
├── config.yaml
├── .env.example
├── client.py
├── datasets.py
├── tests.py
├── metrics.py
├── report.py
├── data/
├── results/
└── reports/
```

The final workflow must simply be:

```bash id="mqz25i"
python run.py
```

It automatically downloads/caches the specified datasets, builds the ~4,000-prompt corpus, creates deterministic test subsets, resumes existing progress, executes every enabled test, records all conversations and metrics, and generates CSV + JSONL + HTML reports.

Use `loop` to test the complete implementation, including interruption/resume, before considering the project complete.
