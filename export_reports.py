#!/usr/bin/env python3
"""Refresh the latest complete Markdown assessment per risk, with no model calls."""
import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import sys
from run_names import register

ROOT=Path(__file__).resolve().parent


def latest_run(base):
    # Compare original journals across output roots, never report-export timestamps.
    journals=[p for p in (base/'results').rglob('events.jsonl')
              if re.fullmatch(r'[a-f0-9]{24}',p.parent.name)]
    return max(journals,key=lambda p:p.stat().st_mtime_ns).parent if journals else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark',choices=['all','llm02','llm06','llm10'],default='all')
    parser.add_argument('--run-directory',type=Path,help='explicit saved run; requires one benchmark')
    parser.add_argument('--prune-history',action='store_true',help='delete older raw runs after successful export; refuses active writers')
    args=parser.parse_args()
    if args.run_directory and args.benchmark=='all':parser.error('--run-directory requires one benchmark')
    (ROOT/'runs').mkdir(exist_ok=True)
    with (ROOT/'runs/.export.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for benchmark in (['llm02','llm06','llm10'] if args.benchmark=='all' else [args.benchmark]):
            base=ROOT/benchmark
            directory=args.run_directory.resolve() if args.run_directory else latest_run(base)
            if directory is None:
                print(f'{benchmark}: no saved run; skipping.');continue
            python=base/'.venv/bin/python'
            interpreter=str(python) if python.exists() else sys.executable
            command=([interpreter,'-m','llm10.report',str(directory)] if benchmark=='llm10'
                     else [interpreter,str(base/'export_reports.py'),str(directory)])
            result=subprocess.run(command,cwd=ROOT,check=True,capture_output=True,text=True)
            if benchmark=='llm02':output=directory/'analysis/report.md'
            elif benchmark=='llm06':output=directory/'analysis/reports'/directory.name/'report.md'
            else:
                output=Path(next(line.split(': ',1)[1] for line in result.stdout.splitlines() if line.startswith('Analysis snapshot through journal sequence ')))
            report=register(ROOT/'runs',output,directory)
            print(report)
            if args.prune_history:
                from retention import prune_history
                prune_history(base,directory,report)


if __name__=='__main__':main()
