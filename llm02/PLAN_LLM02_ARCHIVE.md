# Implementation plan

## Dataset inspection

Inspected upstream file inventories and records before implementation, 2026-10-04.

| Adapter | Actual source and interpretation |
|---|---|
| PrivAwareBench | `LeoWang0318/PrivAwareBench/data/Standard/{token,password,personal_id,financial}.jsonl`; 1,200 `pid,code` records. No explicit protected-value field: extract category-specific values with evidence, flag missing extraction rather than assume safe. Upstream documents synthetic data. |
| PasswordEval | `haritzpuerto/password_eval-contextual-integrity/data/test-00000-of-00001.parquet`; `system_prompt,user_prompt,confidential_info,password,compliant`. Compliant requests may disclose confidential_info but must not disclose the password. |
| PEEP | `haritzpuerto/PEEP-contextual-integrity/data/test-00000-of-00001.parquet`; `system_prompt,user_prompt,query,confidential_data,language`. confidential_data is a JSON-encoded list of mappings. |
| ConfAIde | `skywalker023/confaide/benchmark/tier_*.txt`. Tiers 1/2 are normative ratings, not disclosure attacks; account for them as filtered. Tiers 3/4 contain BEGIN/END-delimited scenarios. Preserve tier, relational metadata and annotations. Tier 3 requires semantic grading, not matching generic topic words. |
| DecodingTrust | Only `src/dt/configs/privacy` and privacy prompt definitions. Instantiate PII tasks with deterministic synthetic canaries; explicitly label these adapted tests. No Enron personal data or claim to measure training-data memorization. |
| PrivacyLens | `SALT-NLP/PrivacyLens/data/main_data.json`; nested seed, vignette, trajectory with sensitive_info_items. Replay trajectory as untrusted text context, not live tool calls; semantic grading for paraphrases. Label this text-only adaptation. |
| Comparison | `v1adam/Comparison_Dataset/dataset.jsonl`; 40 sensitive, 40 jailbreak, 40 benign/control records. Exclude unrelated jailbreaks; preserve benign/hard_negative controls; unknown factual disclosure needs semantic review. |
| ALERT | `Babelscape/ALERT/{alert,alert_adversarial}.jsonl`; broad harm benchmark. Filter relevant privacy prompts and use them only as explicitly marked synthetic-canary transformations; no claim these are the original ALERT score. |

Source URLs follow the repositories named in IMPLEMENTATION.md. Raw downloads retain URL, SHA-256 and cached contents for auditability. Do not execute downloaded code.

## Architecture and sequence

1. `llm02/config.py`, `schema.py`: validated YAML/environment configuration and stable normalized identities. Include evaluator/adapter version and dataset contents in run identity.
2. `llm02/datasets.py`: separate adapter functions, raw cache, source manifests, accounting, provenance-preserving deduplication, optional per-dataset smoke limits, normalized snapshots.
3. `llm02/storage.py`, `client.py`, `runner.py`: append/fsync journals, atomic checkpoints, exclusive process lock, per-turn replay, OpenAI-compatible HTTP client, mock transport, persisted bounded retries, SIGINT recovery. Never repeat a durably completed turn. A remote request accepted just before a crash has an ambiguous outcome: default to recording it as uncertain; explicit retry is optional, with a stable idempotency key but no false exactly-once guarantee.
4. `llm02/evaluation.py`: exact/normalized/partial/fuzzy detection, encoded/cross-turn reconstruction, conservative refusal detection, optional structured semantic judge. Keep ungraded and errors out of success denominators. Controls are distinct from attacks, including PasswordEval authorized cases.
5. `llm02/report.py`: metrics from evidence only; explicit denominators; risk = configurable impact × observed cluster leakage likelihood; source/category/technique/difficulty/turn/severity breakdowns; escaped self-contained HTML, CSV, JSON, clustered findings and masked evidence.
6. Tests and validation: real dataset acquisition and normalization; mock safe/leaky/malformed/429/timeout/5xx responses; multi-turn; retries persisted across crashes; process kill and resume; concurrent process exclusion; reproducible metrics and reports. Small real endpoint smoke only once target credentials are available.

## Defaults

Default `python run.py` runs a small, clearly labelled synthetic mock demonstration without API costs. `config.full.yaml` enables all eight upstream adapters and a real endpoint configured through environment variables. `--prepare-only` validates actual downloads without inference. No enabled dataset silently disappears: failures are reported and block inference. `--report-only` regenerates reports without model requests.

Updated per user request: `python run.py` is now the live sarvam-30b assessment,
using Loop's own provider/auth/API crates through a native stdio bridge. No new
endpoint credentials are required. The mock moved to config.mock.yaml. See
RUN_LIVE.md for the detached launcher and stable output paths.

## Loop development status

Attempted planning via `/home/aman/loop/target/debug/loop --cwd /home/aman/owasp/llm02 --print ...`. First response contained only a thinking block and no tool call or plan. Next invocation failed: `Soket API key not set`. No credentials were printed or copied. Continue locally while this external prerequisite is resolved; record further Loop runs in VALIDATION.md. Do not claim Loop validation that did not occur.

Resolved during implementation: credentials restored by user; provider model `gpt`
works with an explicit concise system prompt. Loop produced the evaluator draft,
reviewed its regression fix, and executed detector/persistence tests via actual
`bash` tool calls. Draft code was reviewed and corrected before integration.
See VALIDATION.md for the recorded sessions and final test results.
