#!/usr/bin/env python3
"""Refresh common-format snapshots from saved evidence, with no model calls."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from run_names import register

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', choices=['all', 'llm02', 'llm06', 'llm10'], default='all')
    parser.add_argument('--run-directory', type=Path, help='saved run to export; requires a single benchmark')
    args = parser.parse_args()
    if args.run_directory and args.benchmark == 'all':
        parser.error('--run-directory requires --benchmark llm02, llm06 or llm10')
    for benchmark in (['llm02', 'llm06', 'llm10'] if args.benchmark == 'all' else [args.benchmark]):
        base = ROOT/benchmark
        python = base/'.venv/bin/python'
        interpreter = str(python) if python.exists() else sys.executable
        if args.run_directory:
            directory = args.run_directory.resolve()
        else:
            # Respect each benchmark's configured output root, including LLM02's
            # results/sarvam-30b rather than an old smoke run in results/.
            code = "import json,sys,yaml; c=yaml.safe_load(open(sys.argv[1])); print(json.dumps(c.get('output',{}).get('directory') or c.get('paths',{}).get('results') or c.get('results_dir','results')))"
            configured = json.loads(subprocess.check_output([interpreter, '-c', code, str(base/'config.yaml')], text=True))
            results = Path(configured)
            if not results.is_absolute():
                results = base/results
            pointer = results/('latest-benchmark.json' if benchmark == 'llm06' else 'latest.json')
            if not pointer.exists():
                print(f'{benchmark}: no saved run at {pointer}; skipping.')
                continue
            latest = json.loads(pointer.read_text())
            directory = Path(latest.get('directory') or results/latest['run_id'])
        command = ([interpreter, '-m', 'llm10.report', str(directory)] if benchmark == 'llm10'
                   else [interpreter, str(base/'export_reports.py'), str(directory)])
        result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, file=sys.stderr, end='')
        if benchmark == 'llm02':
            output = Path(next(line.removeprefix('Reports: ') for line in result.stdout.splitlines() if line.startswith('Reports: '))) / 'report.html'
        elif benchmark == 'llm06':
            output = Path(next(line.removeprefix('Report: ') for line in result.stdout.splitlines() if line.startswith('Report: ')))
        else:
            output = Path(next(line.split(': ', 1)[1] for line in result.stdout.splitlines() if line.startswith('Analysis snapshot through journal sequence ')))
        landing = register(ROOT/'runs', output, directory)
        print(f'Readable run: {landing.parent.name}\nOpen: {landing}')
    print(f'All runs: {ROOT / "runs/index.html"}')


if __name__ == '__main__':
    main()
