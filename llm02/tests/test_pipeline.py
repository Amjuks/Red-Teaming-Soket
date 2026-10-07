import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from llm02.config import load_config
from llm02.report import metrics, write_reports


ROOT = Path(__file__).resolve().parents[1]


def config_file(tmp_path, mode='mock', url='http://localhost:8000/v1', limit=None):
    cfg = yaml.safe_load((ROOT / 'config.mock.yaml').read_text())
    cfg['output'] = {'directory': str(tmp_path / 'results'), 'cache_directory': str(tmp_path / 'data')}
    cfg['model'].update(mode=mode, base_url=url, api_key_env='')
    cfg['execution'].update(concurrency=1, retry_backoff_seconds=0)
    if limit:
        cfg['datasets'] = {'synthetic': {'limit': limit}}
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(cfg))
    return path


def invoke(path, *flags):
    return subprocess.run([sys.executable, str(ROOT / 'run.py'), '--config', str(path), *flags],
                          cwd=ROOT, capture_output=True, text=True, timeout=90)


def test_one_command_resume_and_reproducible_reports(tmp_path):
    path = config_file(tmp_path)
    p = invoke(path)
    assert p.returncode == 0, p.stderr + p.stdout
    latest = json.loads((tmp_path / 'results/latest.json').read_text())
    out = Path(latest['directory'])
    raw_before = (out / 'events.jsonl').read_bytes()
    metrics_before = (out / 'metrics.json').read_bytes()
    m = json.loads(metrics_before)
    assert m['total_tests'] == 44
    assert m['overall']['completed'] == 44
    assert m['overall']['control_denominator'] == 2
    assert m['overall']['false_refusal_rate'] == 0.5
    assert m['overall']['classification_counts']['RECONSTRUCTABLE_LEAK'] >= 7
    assert invoke(path).returncode == 0
    assert (out / 'events.jsonl').read_bytes() == raw_before
    assert (out / 'metrics.json').read_bytes() == metrics_before
    assert invoke(path, '--report-only').returncode == 0
    assert (out / 'metrics.json').read_bytes() == metrics_before
    p = subprocess.run([sys.executable, str(ROOT / 'run.py'), '--report-run', str(out)],
                       cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    assert (out / 'metrics.json').read_bytes() == metrics_before
    report = (out / 'report.html').read_text()
    assert 'SYNTHETIC MOCK DEMONSTRATION' in report
    for case in json.loads((out / 'cases.json').read_text()):
        for secret in case['protected_values']:
            assert secret not in report
            assert secret not in (out / 'summary.csv').read_text()


def test_changed_config_creates_distinct_run(tmp_path):
    path = config_file(tmp_path, limit=2)
    assert invoke(path).returncode == 0
    first = json.loads((tmp_path / 'results/latest.json').read_text())['run_id']
    cfg = yaml.safe_load(path.read_text())
    cfg['generation']['temperature'] = 0.1
    path.write_text(yaml.safe_dump(cfg))
    assert invoke(path).returncode == 0
    second = json.loads((tmp_path / 'results/latest.json').read_text())['run_id']
    assert first != second


@pytest.mark.parametrize('stop_signal', [signal.SIGKILL, signal.SIGINT])
def test_process_kill_and_resume_with_http_endpoint(tmp_path, stop_signal):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(self.headers.get('Idempotency-Key'))
            time.sleep(0.15)
            payload = json.dumps({'choices': [{'message': {'content': 'I cannot disclose private information.'}, 'finish_reason': 'stop'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config_file(tmp_path, mode='openai', url=f'http://127.0.0.1:{server.server_port}/v1', limit=10)
    proc = subprocess.Popen([sys.executable, str(ROOT / 'run.py'), '--config', str(path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=ROOT)
    try:
        deadline = time.monotonic() + 30
        journal = None
        while time.monotonic() < deadline:
            journals = list((tmp_path / 'results').glob('*/events.jsonl'))
            if journals and '"kind": "result"' in journals[0].read_text():
                journal = journals[0]
                break
            if proc.poll() is not None:
                pytest.fail(proc.stderr.read().decode())
            time.sleep(0.01)
        assert journal is not None
        os.kill(proc.pid, stop_signal)
        proc.wait(timeout=10)
        if stop_signal == signal.SIGINT:
            assert (journal.parent / 'report.html').exists()
            assert json.loads((journal.parent / 'state.json').read_text())['status'] == 'interrupted'
        before = [json.loads(x) for x in journal.read_text().splitlines() if x.endswith('}')]
        completed_keys = {e['request_key'] for e in before if e['kind'] == 'response'}
        assert completed_keys
        p = invoke(path)
        assert p.returncode in (0, 2), p.stderr
        events = [json.loads(x) for x in journal.read_text().splitlines()]
        results = [e for e in events if e['kind'] == 'result']
        assert len(results) == 10
        assert len({e['test_id'] for e in results}) == 10
        counts = Counter(requests)
        assert all(counts[k] == 1 for k in completed_keys)
        # record policy also prevents repeating unknown in-flight requests.
        assert all(n == 1 for n in counts.values())
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        server.shutdown()
        server.server_close()


def test_error_and_ungraded_not_in_asr():
    def row(status, grade, classification, expected='must_not_disclose'):
        return {'status': status, 'evaluation': {'grading_status': grade, 'classification': classification, 'refused': False},
                'case': {'expected': expected}}
    from llm02.report import summary
    s = summary([row('ERROR', 'ungraded', None), row('COMPLETED', 'ungraded', None),
                 row('COMPLETED', 'graded', 'FULL_LEAK'), row('COMPLETED', 'graded', 'NO_LEAK')])
    assert s['attack_success_rate'] == 0.5
    assert s['attack_denominator'] == 2
    assert s['ungraded'] == 1
    assert s['errors'] == 1
