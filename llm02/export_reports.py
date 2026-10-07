#!/usr/bin/env python3
"""Export an isolated, read-only snapshot of an active or historical run."""
import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm02.report import write_reports, atomic_text
from llm02.schema import Case


def export_snapshot(directory):
    directory = Path(directory).resolve()
    cfg = json.loads((directory / 'config.json').read_text())
    cases = [Case(**c) for c in json.loads((directory / 'cases.json').read_text())]
    coverage = json.loads((directory / 'coverage.json').read_text())
    rows = {}
    last_seq = -1
    # Bound the read to the file size at open. Never repair/truncate or acquire
    # the runner's writer lock. An incomplete final event is not yet committed.
    with (directory / 'events.jsonl').open('rb') as f:
        remaining = os.fstat(f.fileno()).st_size
        while remaining:
            line = f.readline(remaining)
            remaining -= len(line)
            if not line.endswith(b'\n'):
                break
            event = json.loads(line)
            if event.get('seq') != last_seq + 1:
                raise ValueError('Non-contiguous journal; export aborted without modifying source')
            last_seq = event['seq']
            if event['kind'] == 'result':
                rows[event['test_id']] = event['result']
    root = directory / 'csv-snapshots'
    root.mkdir(mode=0o700, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=root))
    write_reports(output, sorted(rows.values(), key=lambda r: r['test_id']), cases, coverage, cfg, directory.name)
    atomic_text(output / 'snapshot.json', json.dumps({'source_run': str(directory), 'last_seq': last_seq,
                'results': len(rows), 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'note': 'Point-in-time snapshot of committed results; does not update automatically.'}, indent=2))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory')
    args = parser.parse_args()
    try:
        print(f'Reports: {export_snapshot(args.run_directory)}')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'Export failed: {exc}\n')


if __name__ == '__main__':
    main()
