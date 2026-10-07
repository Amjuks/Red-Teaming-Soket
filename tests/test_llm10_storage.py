import json
import subprocess
import sys

import pytest

from llm10.storage import Journal


def test_replay_lock_and_copy(tmp_path):
    with Journal(tmp_path) as j:
        with pytest.raises(RuntimeError): Journal(tmp_path)
        messages=[{'role':'user','content':'exact'}]
        j.append('attempt_started',attempt_id='a',call_id='c',messages=messages)
        messages[0]['content']='changed'
        assert j.events[0]['messages'][0]['content']=='exact'
        assert len(j.unresolved())==1
        j.append('attempt_finished',attempt_id='a',call_id='c',content='done')
        j.append('call_finished',call_id='c',status='success')
        assert not j.unresolved()
    with Journal(tmp_path) as j:
        assert j.completed_calls()['c']['status']=='success'
        assert j.path.stat().st_mode & 0o777==0o600


def test_torn_tail_preserved_and_interior_rejected(tmp_path):
    with Journal(tmp_path) as j: j.append('test')
    p=tmp_path/'events.jsonl'
    with p.open('ab') as f: f.write(b'{torn')
    with Journal(tmp_path) as j: assert len(j.events)==1
    assert next(tmp_path.glob('torn-tail-*')).read_bytes()==b'{torn'
    p.write_bytes(b'{invalid}\n')
    with pytest.raises(RuntimeError,match='corruption'): Journal(tmp_path)
    assert p.read_bytes()==b'{invalid}\n'


def test_process_exit_preserves_committed_intent(tmp_path):
    code='from llm10.storage import Journal; import os; j=Journal('+repr(str(tmp_path))+'); j.append("attempt_started",attempt_id="a",call_id="c"); os._exit(9)'
    assert subprocess.run([sys.executable,'-c',code]).returncode==9
    with Journal(tmp_path) as j: assert len(j.unresolved())==1
