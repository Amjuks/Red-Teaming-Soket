import asyncio
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from llm02.client import Endpoint, RequestFailed
from llm02.config import load_config
from llm02.loop_transport import DEFAULT_BRIDGE, prepare_loop
from llm02.runner import parse_judge
from llm02.storage import RunStore


@pytest.fixture
def loop_provider(tmp_path):
    if not DEFAULT_BRIDGE.exists():
        pytest.skip('build the native bridge to test actual Loop transport')
    captured = []
    mode = {'status': 200}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            captured.append({'body': request, 'key': self.headers.get('Authorization'),
                             'idempotency': self.headers.get('Idempotency-Key')})
            if mode['status'] != 200:
                self.send_response(mode['status'])
                self.send_header('Retry-After', '0')
                self.end_headers()
                self.wfile.write(b'{"error":"test failure"}')
                return
            events = [
                {'id': 'local-test', 'model': 'sarvam-30b', 'choices': [{'index': 0, 'delta': {'content': 'BRIDGE_OK'}, 'finish_reason': None}]},
                {'id': 'local-test', 'model': 'sarvam-30b', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                 'usage': {'prompt_tokens': 11, 'completion_tokens': 3, 'total_tokens': 14}}]
            body = ''.join('data: ' + json.dumps(x) + '\n\n' for x in events) + 'data: [DONE]\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body.encode())))
            self.end_headers()
            self.wfile.write(body.encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    agent = tmp_path / 'agent'
    agent.mkdir()
    (agent / 'settings.json').write_text(json.dumps({'defaultProvider': 'local', 'defaultModel': 'sarvam-30b'}))
    (agent / 'models.json').write_text(json.dumps({'providers': [{'id': 'local',
        'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'apiKeyEnv': ['LOOP_TEST_UNUSED'],
        'models': ['sarvam-30b']}]}))
    (agent / 'auth.json').write_text(json.dumps({'providers': {'local': {'type': 'apiKey', 'key': 'synthetic-local-auth'}}}))
    model = {'mode': 'loop', 'provider': 'local', 'model': 'sarvam-30b', 'agent_directory': str(agent)}
    prepare_loop(model)
    try:
        yield model, captured, mode
    finally:
        server.shutdown()
        server.server_close()


def test_native_loop_preserves_transcript_credentials_and_usage(loop_provider, tmp_path):
    model, captured, _ = loop_provider
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.mock.yaml')
    turns = [{'role': 'system', 'content': 'ONLY this benchmark policy.'},
             {'role': 'user', 'content': 'First question'}, {'role': 'assistant', 'content': 'Earlier answer'},
             {'role': 'user', 'content': 'Next question'}]
    async def exercise():
        with RunStore(tmp_path / 'run') as store:
            endpoint = Endpoint(model, cfg['execution'], {'temperature': 0, 'max_tokens': 77}, store)
            first = await endpoint.request(turns, 'stable-key')
            second = await endpoint.request(turns, 'stable-key')
            assert first == second
            assert first['content'] == 'BRIDGE_OK'
            assert first['raw']['model'] == 'sarvam-30b'
            assert first['usage']['totalTokens'] == 14
            await endpoint.close()
    asyncio.run(exercise())
    assert len(captured) == 1
    assert captured[0]['body']['messages'] == turns
    assert not captured[0]['body'].get('tools')
    assert captured[0]['body']['model'] == 'sarvam-30b'
    assert captured[0]['body']['max_tokens'] == 77
    assert captured[0]['key'] == 'Bearer synthetic-local-auth'
    assert captured[0]['idempotency'] == 'stable-key'
    assert 'synthetic-local-auth' not in json.dumps(model)


def test_native_loop_errors_are_bounded_and_permanent(loop_provider, tmp_path):
    model, captured, mode = loop_provider
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.mock.yaml')
    cfg['execution'].update(max_retries=1, retry_backoff_seconds=0)
    async def exercise():
        with RunStore(tmp_path / 'run') as store:
            endpoint = Endpoint(model, cfg['execution'], cfg['generation'], store)
            mode['status'] = 429
            with pytest.raises(RequestFailed, match='429'):
                await endpoint.request([{'role': 'user', 'content': 'test'}], 'limited')
            assert len(captured) == 2
            mode['status'] = 401
            for _ in range(2):
                with pytest.raises(RequestFailed, match='401'):
                    await endpoint.request([{'role': 'user', 'content': 'test'}], 'denied')
            assert len(captured) == 3
            await endpoint.close()
    asyncio.run(exercise())


def test_no_silent_model_fallback(loop_provider):
    model, captured, _ = loop_provider
    model['model'] = 'missing-model'
    with pytest.raises(ValueError, match='not registered'):
        prepare_loop(model)
    assert captured == []


def test_judge_accepts_fenced_json_but_not_arbitrary_prose():
    assert parse_judge('```json\n{"verdict":"UNKNOWN"}\n```')['verdict'] == 'UNKNOWN'
    with pytest.raises(ValueError):
        parse_judge('maybe {"verdict":"NO_LEAK"}')
