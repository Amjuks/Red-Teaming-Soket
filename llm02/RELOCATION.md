# LLM02 relocation — 2026-10-07

All LLM02 entry scripts, YAML configs, requirements, Python environment, dataset
cache, existing results, tests, operator documentation and native bridge now live
under `/home/aman/owasp/llm02/`.

```bash
cd /home/aman/owasp/llm02
.venv/bin/python run.py
.venv/bin/python background.py start
.venv/bin/python background.py status
.venv/bin/python background.py stop
```

Reports: `results/sarvam-30b/latest/report.html` and full evidence CSVs in that same
directory. Logs: `logs/latest.log`. Dataset cache: `data/`.

```bash
.venv/bin/python export_reports.py results/sarvam-30b/latest
.venv/bin/python run.py --report-run results/sarvam-30b/latest
.venv/bin/python -m pytest -q
```

Old absolute paths recorded in immutable event journals describe the original
execution and remain unchanged. Operational latest.json pointers are relocated.
relocation_identity.json maps verified relocation-only source changes to original
hashes so default run IDs remain stable. Later changes to benchmark implementation
still create different fingerprints. Report-only rebuilding uses saved evidence.

Loop's own source/configuration remains installed separately under /home/aman/loop
and /home/aman/.loop. LLM02 owns its native bridge source and binary; LLM10's active
binary/build cache was left at its existing location to preserve the running process.
