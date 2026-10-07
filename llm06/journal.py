"""Single writer, fsynced append records, checksums and torn-tail recovery."""
import fcntl
import json
import os
from datetime import datetime, timezone
from common import canonical, identity, local_path

class Journal:
    def __init__(self,directory):
        self.directory=local_path(directory); self.directory.mkdir(parents=True,exist_ok=True)
        self.lock=(self.directory/'writer.lock').open('a+')
        try: fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close();raise ValueError('run already has an active writer')
        self.path=self.directory/'events.jsonl'
        self.file=self.path.open('a+b'); self.events=[]
        self.file.seek(0); offset=0
        while True:
            line=self.file.readline()
            if not line: break
            if not line.endswith(b'\n'):
                # Preserve forensic tail; only an unterminated final record may be removed.
                (self.directory/'torn-tail.bin').write_bytes(line)
                self.file.seek(offset);self.file.truncate();self.file.flush();os.fsync(self.file.fileno());break
            try: event=json.loads(line)
            except ValueError: self.close();raise ValueError('corrupt complete journal record')
            checksum=event.pop('checksum',None)
            if checksum!=identity(event) or event['seq']!=len(self.events):
                self.close();raise ValueError('journal integrity failure')
            event['checksum']=checksum;self.events.append(event);offset+=len(line)
        self.file.seek(0,2)
    def append(self,kind,**data):
        event={'seq':len(self.events),'time':datetime.now(timezone.utc).isoformat(),'kind':kind,**data}
        event['checksum']=identity(event)
        self.file.write((canonical(event)+'\n').encode());self.file.flush();os.fsync(self.file.fileno())
        self.events.append(event);return event
    def close(self):
        if hasattr(self,'file') and not self.file.closed:self.file.close()
        if not self.lock.closed:self.lock.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
