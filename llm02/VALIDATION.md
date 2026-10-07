# Executed validation — 2026-10-04

## Latest: native Loop transport and live sarvam-30b setup

The live defaults now use `model.mode: loop`, provider `soket`, model `sarvam-30b`.
The Rust bridge links to Loop's actual provider/auth/API crates, without a coding
agent wrapper or Python credential copying. Its dependencies are locked in
`native/loop-bridge/Cargo.lock`. Loop's models.json gained the `sarvam-30b` entry;
existing provider routing/credentials were preserved.

Loop-executed suite: **54 passed in 9.97s**. Final suite after adding detached
duplicate-start/stop/resume coverage: **55 passed in 14.08s**.
Additional tests cover native Loop message/role fidelity, credential-store auth,
streaming token usage, idempotency headers, durable replay, 429/401 retries,
explicit failure for a missing model, fenced judge JSON, and detached background
completion, duplicate-start prevention, graceful stop and resume without repeated
requests. Earlier validation below remains as historical provenance.

Live sarvam smoke: **7 cases completed, 0 request errors, 0 ungraded**, including
one two-turn case and one real semantic-judge call. Six cases had detected
disclosure (including protected text in returned reasoning); these small samples
are not an overall estimate of model risk. Every response reports `sarvam-30b`
and uses `loop-ai` transport. Full evidence/report:
`results/sarvam-30b-smoke/812b564e48dbcdd602446dac/`.

`python run.py --prepare-only` prepared all **5,697** default-live cases successfully.
The full assessment has not been started. The mock demonstration now requires
`--config config.mock.yaml`. See RUN_LIVE.md for the ready-to-run commands.

## Original implementation validation

Implementation is in `/home/aman/owasp/llm02`; the existing `/home/aman/loop` source tree
was not changed. Python 3.10.12 with dependencies recorded in `requirements.lock`.

## Automated tests

Final command, executed through Loop's actual `bash` tool:

```text
LLM02_NETWORK_TESTS=1 .venv/bin/python -m pytest -q
.................................................                        [100%]
49 passed in 7.76s
```

The suite verifies:

1. All eight configured sources acquired and normalized from actual upstream files.
2. Adapter schemas, PasswordEval authorization rules and PEEP annotations.
3. Accounting, invalid rows, duplicate provenance, limits and missing-source errors.
4. OpenAI-compatible HTTP request construction and response parsing.
5. Single/multi-turn execution and durable replay of already completed turns.
6. Exact, normalized, partial, encoded and reconstructed synthetic leaks.
7. Safe responses, short-value substring boundaries, refusal-prefix pitfalls,
   protected input not self-matching, truncation and thinking-only ambiguity.
8. HTTP 429, 503, 401, network timeouts, malformed responses and persisted retry budgets.
9. An actual subprocess SIGKILL during execution against a local HTTP server.
10. Restart without repeating completed requests; ambiguous requests not resent.
11. Exclusive writer locking and torn-journal recovery; interior corruption rejected.
12. Metrics reproduced byte-for-byte after resume and report-only replay.
13. Self-contained HTML, CSV, metrics JSON and raw JSONL; secrets excluded from human reports.
14. Structured semantic-judge request/response integration and fabricated-quote rejection.
15. Configuration validation and run fingerprint behavior.
16. Actual SIGINT with a partial report/checkpoint, followed by successful resume.
17. Journal in-memory events remain identical to durable bytes when conversations mutate.

## Dataset acquisition

`python run.py --config config.full.yaml --prepare-only` succeeded with 5,653
normalized cases and no inference calls. Counts from the fetched source versions:

| Dataset | Loaded | Accepted / final tests | Filtered | Invalid |
|---|---:|---:|---:|---:|
| PrivAwareBench | 1,200 | 1,200 | 0 | 0 |
| PasswordEval | 1,000 | 1,000 | 0 | 0 |
| ConfAIde | 496 | 290 | 206 | 0 |
| PEEP | 2,062 | 2,062 | 0 | 0 |
| DecodingTrust privacy types | 23 | 23 | 0 | 0 |
| PrivacyLens | 493 | 493 | 0 | 0 |
| Comparison Dataset | 120 | 80 | 40 | 0 |
| ALERT + adversarial | 45,731 | 505 | 45,226 | 0 |

Content hashes and acquisition URLs are in `data/normalized/sources.json`, with
run-specific copies in coverage.json. Synthetic/mock source counts are separate.
Dataset download success does not establish completeness of heuristic secret
extraction: 109 PrivAwareBench records had no extracted candidate (33 token,
46 password, 30 personal ID). All PrivAwareBench cases are labelled heuristic and
require semantic coverage for non-refusal no-match responses. They are not silently
counted safe. Financial extraction produced candidates in all 300 records.

## End-to-end artifacts

The original default 44-case synthetic demonstration completes without endpoint credentials,
with 42 attacks, 2 controls, zero execution errors and zero ungraded cases. The
mock intentionally returns full/partial/encoded/split secrets: its 35 detected
leaks validate the pipeline and say nothing about a real model.

- Mock demo: `results/aafe11f3fcc8b58ba9c36322/report.html`.
- Forty-case sample across all eight downloaded adapters:
  `results/fcff7383363647b2ebde5824/report.html` (mock target, not a model assessment).
- Real endpoint smoke: `results/e323576df025ddab2da1290e/report.html`.

The real smoke used the existing Loop-compatible endpoint and model alias `gpt`:
six synthetic credential cases, seven target HTTP requests (one two-turn case),
zero transport errors, six graded cases, and two full canary disclosures. Its
small sample is not a complete model evaluation. No full paid benchmark was run.
Credentials were supplied in the subprocess environment from the working local
credential store; they were not printed, committed, or copied to project files.
The saved report has also been rebuilt from evidence with `--report-run` after
later reporting/persistence hardening; the original run identity remains intact.

## Loop provenance

Harness command form:

```bash
/home/aman/loop/target/debug/loop --cwd /home/aman/owasp/llm02 --model gpt \
  --system-prompt 'Use the bash tool to execute the exact command requested. Report actual output.' \
  --print 'Run LLM02_NETWORK_TESTS=1 .venv/bin/python -m pytest -q'
```

Loop participated in plan review, evaluator drafting, defect review, and actual test
execution. Initial invocations hit missing credentials (restored by the user),
thinking-only replies, or plain text imitating tool calls. Those are not counted
as implementation or validation. The evaluator draft was reviewed and corrected
for Case compatibility, detector ordering, short-value boundaries, settings,
refusal handling, literal semantic evidence, and explicit uncertainty.

Verified tool execution from Loop's SQLite session journal:

- `01a10590-96fb-79a0-9c65-165b5e330cb2`: detector/persistence test command;
  actual bash tool result `25 passed in 0.13s`.
- `01a10594-6c37-76c0-8971-e0dd35c0e7a8`: full network-enabled suite;
  actual bash tool result `48 passed in 5.28s` before adding the SIGINT regression.
- `01a10595-e469-70d0-b0ba-77efa8489019`: final full suite including SIGINT;
  actual bash tool result `49 passed in 7.76s`.

No unverified claim that Loop edited files was accepted. Other implementation,
review, integration and testing were performed directly in the project workspace.

## Scope and remaining limits

- This is an initial working implementation, not a certification of benchmark
  parity or exhaustive leak detection.
- PrivAwareBench extraction is heuristic; contextual/paraphrased disclosures need
  a configured semantic judge. Real judge accuracy has not been benchmarked;
  only deterministic/mock judge integration is covered here.
- DecodingTrust uses synthetic PII types, not Enron or training-data memorization.
  PrivacyLens is text-only replay. ALERT is filtered synthetic-canary adaptation.
- Refusal recognition is English-focused and heuristic. A human should review
  consequential findings and unclear semantic verdicts.
- Arbitrary servers cannot promise remote exactly-once requests. Durable responses
  are never rerun; ambiguous hard-crash outcomes default to UNCERTAIN. Retried
  timeouts can duplicate server-side work unless the provider honors idempotency.
- POSIX file locking is used; Windows support is not implemented.
- Original standalone endpoint mode required `.env`; the new default reuses Loop
  configuration and does not require a separate endpoint or credential.
# Relocation verification — 2026-10-07

All entry scripts/configuration/cache/results/environment/tests/docs/native bridge
moved under llm02/. Existing run 559aa614383253ec4780cbc9 retains its fingerprint
after canonical relocation-only source/path changes. Latest pointers and operational
saved configs updated; original configs kept as config.before-relocation.json.
Historical event journals were not rewritten. Smoke report rebuild and read-only
snapshot export passed from new paths; background status resolves the migrated run.
LLM02-only suite: **64 passed, 1 skipped**. Combined regression: **112 passed,
1 skipped in 22.40s**. Cargo locked metadata validates the relocated native source.
No live requests were made during relocation; active LLM10 left running.
