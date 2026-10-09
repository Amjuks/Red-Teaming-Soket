#!/usr/bin/env python3
"""Export an isolated report snapshot without touching the runner's journal."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

from common import identity
from report import build


def export_snapshot(directory):
    directory = Path(directory).resolve()
    # Read only bytes present at open; incomplete writes are not committed events.
    events = []
    with (directory/'events.jsonl').open('rb') as stream:
        remaining = os.fstat(stream.fileno()).st_size
        while remaining:
            line = stream.readline(remaining)
            remaining -= len(line)
            if not line.endswith(b'\n'):
                break
            event = json.loads(line)
            checksum = event.pop('checksum', None)
            if event['seq'] != len(events) or checksum != identity(event):
                raise ValueError('Journal integrity failure; snapshot aborted')
            event['checksum'] = checksum
            events.append(event)
    root = directory/'report-snapshots'
    root.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(dir=root))
    # Use an isolated export directory and report root, never the live output paths.
    _, report = build(SimpleNamespace(events=events, directory=output), output/'reports')
    (output/'snapshot.json').write_text(json.dumps({'source_run':str(directory),
        'last_seq':events[-1]['seq'], 'note':'Point-in-time snapshot; does not refresh automatically.'}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory')
    args = parser.parse_args()
    print('Report:', export_snapshot(args.run_directory))
