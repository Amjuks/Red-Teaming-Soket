"""One writer, fsync-per-event journal. Checkpoints are derived, never authoritative."""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

from .datasets import atomic_json


class RunStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = (directory / '.lock').open('a+')
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise RuntimeError(f'another process owns {directory}') from None
        self.path = directory / 'events.jsonl'
        try:
            self.events = self._recover()
            self.file = self.path.open('ab', buffering=0)
            os.chmod(self.path, 0o600)
        except BaseException:
            self._lock.close()
            raise

    def _recover(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        with self.path.open('rb+') as f:
            while True:
                start = f.tell()
                line = f.readline()
                if not line:
                    break
                if not line.endswith(b'\n'):
                    # Preserve the torn suffix for forensics, then truncate just that tail.
                    tail = self.directory / f'torn-tail-{time.time_ns()}.bin'
                    tail.write_bytes(line)
                    os.chmod(tail, 0o600)
                    f.seek(start)
                    f.truncate()
                    f.flush()
                    os.fsync(f.fileno())
                    break
                try:
                    event = json.loads(line)
                    if event.get('seq') != len(events):
                        raise ValueError('non-contiguous sequence')
                    events.append(event)
                except (ValueError, AttributeError):
                    raise RuntimeError(f'journal corruption before tail at byte {start}; preserved for inspection') from None
        return events

    def append(self, kind: str, **data) -> dict:
        event = {'seq': len(self.events), 'timestamp': time.time(), 'kind': kind, **data}
        payload = (json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n').encode()
        # A crash partway through writes leaves only a recoverable unterminated tail.
        view = memoryview(payload)
        while view:
            n = self.file.write(view)
            if not n:
                raise OSError('journal write failed')
            view = view[n:]
        os.fsync(self.file.fileno())
        # Callers continue mutating conversation lists after a turn. Keep the
        # in-memory replay identical to the bytes durably committed above.
        committed = json.loads(payload)
        self.events.append(committed)
        return committed

    def results(self) -> dict[str, dict]:
        return {e['test_id']: e['result'] for e in self.events if e['kind'] == 'result'}

    def request_events(self, key: str) -> list[dict]:
        return [e for e in self.events if e.get('request_key') == key]

    def checkpoint(self, total: int, status: str):
        rows = list(self.results().values())
        leaks = sum(r.get('evaluation', {}).get('classification') in
                    ('FULL_LEAK', 'PARTIAL_LEAK', 'SEMANTIC_LEAK', 'RECONSTRUCTABLE_LEAK') for r in rows)
        errors = sum(r.get('status') != 'COMPLETED' for r in rows)
        ungraded = sum(r.get('status') == 'COMPLETED' and r.get('evaluation', {}).get('grading_status') != 'graded' for r in rows)
        atomic_json(self.directory / 'state.json', {'total': total, 'completed': len(rows),
                    'remaining': total - len(rows), 'progress_percent': round(100 * len(rows) / total, 2) if total else 0,
                    'leaks': leaks, 'errors': errors, 'ungraded': ungraded,
                    'last_seq': len(self.events) - 1, 'status': status, 'updated_at': time.time()})

    def close(self):
        self.file.close()
        fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
        self._lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
