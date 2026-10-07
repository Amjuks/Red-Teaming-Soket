import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_detached_background_runs_to_completion(tmp_path):
    cfg = yaml.safe_load((ROOT / 'config.mock.yaml').read_text())
    cfg['output'] = {'directory': str(tmp_path / 'results'), 'cache_directory': str(tmp_path / 'data')}
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(cfg))
    logs = tmp_path / 'logs'
    command = [sys.executable, str(ROOT / 'background.py')]
    result = subprocess.run(command + ['start', '--config', str(path), '--logs', str(logs)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = json.loads((logs / 'background.json').read_text())
        if state['status'] != 'running':
            break
        time.sleep(0.05)
    assert state['status'] == 'finished', (logs / 'latest.log').read_text()
    assert state['exit_code'] == 0
    assert (tmp_path / 'results/latest/report.html').is_file()
    checkpoint = json.loads((tmp_path / 'results/latest/state.json').read_text())
    assert checkpoint['completed'] == 44
    assert checkpoint['remaining'] == 0
    result = subprocess.run(command + ['status', '--config', str(path), '--logs', str(logs)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
    assert '"completed": 44' in result.stdout


def test_background_duplicate_guard_stop_and_resume(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []
    started = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            seen.append(self.headers['Idempotency-Key'])
            started.set()
            time.sleep(0.4)
            body = json.dumps({'choices': [{'message': {'content': 'I cannot disclose private information.'}, 'finish_reason': 'stop'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg = yaml.safe_load((ROOT / 'config.mock.yaml').read_text())
    cfg['model'].update(mode='openai', base_url=f'http://127.0.0.1:{server.server_port}/v1')
    cfg['execution']['concurrency'] = 1
    cfg['datasets'] = {'synthetic': {'limit': 6}}
    cfg['output'] = {'directory': str(tmp_path / 'results'), 'cache_directory': str(tmp_path / 'data')}
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(cfg))
    logs = tmp_path / 'logs'
    def invoke(action):
        return subprocess.run([sys.executable, str(ROOT / 'background.py'), action,
                               '--config', str(path), '--logs', str(logs)], capture_output=True, text=True, timeout=15)
    def wait_finished():
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = json.loads((logs / 'background.json').read_text())
            if state['status'] != 'running':
                return state
            time.sleep(0.05)
        raise AssertionError('background did not finish')
    try:
        assert invoke('start').returncode == 0
        assert started.wait(timeout=10)
        duplicate = invoke('start')
        assert duplicate.returncode == 2
        assert 'already running' in duplicate.stderr
        assert invoke('stop').returncode == 0
        assert wait_finished()['status'] == 'stopped'
        state = json.loads((tmp_path / 'results/latest/state.json').read_text())
        assert state['status'] == 'interrupted'
        assert state['remaining'] > 0
        assert invoke('start').returncode == 0
        assert wait_finished()['status'] == 'finished'
        state = json.loads((tmp_path / 'results/latest/state.json').read_text())
        assert state['completed'] == 6
        assert len(seen) == len(set(seen))
    finally:
        invoke('stop')
        server.shutdown()
        server.server_close()
