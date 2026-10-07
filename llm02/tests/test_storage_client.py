import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from llm02.client import Endpoint, RequestFailed, retry_after
from llm02.storage import RunStore

MODEL = {'mode': 'openai', 'model': 'test', 'base_url': 'http://test/v1', 'api_key_env': ''}
EXEC = {'timeout_seconds': 1, 'max_retries': 3, 'retry_backoff_seconds': 0, 'max_backoff_seconds': 1, 'uncertain_policy': 'record'}


def test_torn_tail_and_exclusive_lock(tmp_path):
    with RunStore(tmp_path) as store:
        store.append('result', test_id='one', result={'status': 'COMPLETED'})
        with pytest.raises(RuntimeError, match='another process'):
            RunStore(tmp_path)
    with (tmp_path / 'events.jsonl').open('ab') as f:
        f.write(b'{"partial":')
    with RunStore(tmp_path) as store:
        assert len(store.events) == 1
        store.append('check')
    assert list(tmp_path.glob('torn-tail-*.bin'))
    assert len((tmp_path / 'events.jsonl').read_text().splitlines()) == 2


def test_middle_corruption_never_silently_discarded(tmp_path):
    (tmp_path / 'events.jsonl').write_text('broken\n')
    with pytest.raises(RuntimeError, match='corruption'):
        RunStore(tmp_path)


def test_retry_malformed_timeout_rate_limit_and_cached_replay(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '0'})
        if len(calls) == 2:
            raise httpx.ReadTimeout('simulated')
        if len(calls) == 3:
            return httpx.Response(200, json={'choices': []})
        return httpx.Response(200, json={'choices': [{'message': {'content': 'safe'}, 'finish_reason': 'stop'}], 'usage': {'total_tokens': 3}})
    async def exercise():
        with RunStore(tmp_path) as store:
            endpoint = Endpoint(MODEL, EXEC, {}, store, httpx.MockTransport(handler))
            a = await endpoint.request([{'role': 'user', 'content': 'test'}], 'same-key')
            b = await endpoint.request([{'role': 'user', 'content': 'test'}], 'same-key')
            assert a == b
            assert len(calls) == 4
            assert len({c.headers['Idempotency-Key'] for c in calls}) == 1
            await endpoint.close()
    asyncio.run(exercise())


def test_permanent_401_and_retry_budget_survive_restart(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(401)
    async def exercise():
        for _ in range(2):
            with RunStore(tmp_path) as store:
                endpoint = Endpoint(MODEL, EXEC, {}, store, httpx.MockTransport(handler))
                with pytest.raises(RequestFailed, match='401'):
                    await endpoint.request([], 'key')
                await endpoint.close()
    asyncio.run(exercise())
    assert len(calls) == 1


def test_server_error_budget_is_bounded_across_restarts(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503)
    async def exercise():
        for _ in range(2):
            with RunStore(tmp_path) as store:
                endpoint = Endpoint(MODEL, EXEC, {}, store, httpx.MockTransport(handler))
                with pytest.raises(RequestFailed):
                    await endpoint.request([], 'key')
                await endpoint.close()
    asyncio.run(exercise())
    assert len(calls) == 4


def test_ambiguous_inflight_is_not_repeated(tmp_path):
    with RunStore(tmp_path) as store:
        store.append('request_start', request_key='key', attempt=0)
    async def exercise():
        with RunStore(tmp_path) as store:
            endpoint = Endpoint(MODEL, EXEC, {}, store, httpx.MockTransport(lambda r: pytest.fail('duplicate request')))
            with pytest.raises(RequestFailed) as exc:
                await endpoint.request([], 'key')
            assert exc.value.status == 'UNCERTAIN'
            await endpoint.close()
    asyncio.run(exercise())


def test_actual_process_crash_preserves_completed_response(tmp_path):
    code = '''
import os,sys
from pathlib import Path
from llm02.storage import RunStore
s=RunStore(Path(sys.argv[1]))
s.append('request_start',request_key='done',attempt=0)
s.append('response',request_key='done',response={'content':'durable','latency_seconds':0})
os._exit(99)
'''
    p = subprocess.run([sys.executable, '-c', code, str(tmp_path)])
    assert p.returncode == 99
    async def exercise():
        with RunStore(tmp_path) as store:
            endpoint = Endpoint(MODEL, EXEC, {}, store, httpx.MockTransport(lambda r: pytest.fail('replayed completed request')))
            assert (await endpoint.request([], 'done'))['content'] == 'durable'
            await endpoint.close()
    asyncio.run(exercise())


def test_retry_after():
    assert retry_after('3') == 3
    assert retry_after('nonsense') == 0
    assert retry_after('Wed, 21 Oct 2015 07:28:00 GMT') == 0


def test_journal_snapshot_does_not_mutate_with_conversation(tmp_path):
    messages = [{'role': 'user', 'content': 'first'}]
    with RunStore(tmp_path) as store:
        store.append('request_start', request_key='key', messages=messages)
        messages.append({'role': 'assistant', 'content': 'response'})
        assert len(store.events[0]['messages']) == 1
        assert store.events[0] == json.loads((tmp_path / 'events.jsonl').read_text())
