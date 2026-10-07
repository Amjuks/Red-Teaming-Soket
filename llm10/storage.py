"""Single-writer, fsync-per-event attempt journal; no model calls here."""
import fcntl
import json
import os
from pathlib import Path
import time

from .files import write_json


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = (self.directory / '.lock').open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError('Another process owns this run') from None
        try:
            self.path = self.directory / 'events.jsonl'
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            self.file = os.fdopen(fd, 'r+b', buffering=0)
            self.events = []
            while True:
                start = self.file.tell()
                line = self.file.readline()
                if not line:
                    break
                if not line.endswith(b'\n'):
                    tail = self.directory / f'torn-tail-{time.time_ns()}.bin'
                    fd = os.open(tail, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'wb') as f:
                        f.write(line); f.flush(); os.fsync(f.fileno())
                    self.file.truncate(start); self.file.seek(start)
                    os.fsync(self.file.fileno())
                    break
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get('seq') != len(self.events):
                        raise ValueError('sequence')
                except ValueError:
                    raise RuntimeError(f'Journal corruption at byte {start}; source preserved') from None
                self.events.append(event)
        except BaseException:
            if hasattr(self, 'file'): self.file.close()
            self.lock.close()
            raise

    def append(self, kind, **data):
        if {'seq','timestamp','kind'} & data.keys():
            raise ValueError('reserved event fields')
        event = {**data, 'seq': len(self.events), 'timestamp': time.time(), 'kind': kind}
        raw = (json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n').encode()
        view = memoryview(raw)
        while view:
            n = self.file.write(view)
            if not n: raise OSError('Journal write failed')
            view = view[n:]
        os.fsync(self.file.fileno())
        committed = json.loads(raw)
        self.events.append(committed)
        return committed

    def attempts(self):
        return {e['attempt_id']: e for e in self.events if e['kind'] == 'attempt_finished'}

    def unresolved(self):
        finished = self.attempts()
        return [e for e in self.events if e['kind'] == 'attempt_started' and e['attempt_id'] not in finished]

    def completed_calls(self):
        return {e['call_id']: e for e in self.events if e['kind'] == 'call_finished'}

    def checkpoint(self, **state):
        write_json(self.directory / 'state.json', {**state, 'last_seq': len(self.events)-1,
                                                 'updated_at': time.time()})

    def close(self):
        self.file.close()
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
