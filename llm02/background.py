#!/usr/bin/env python3
"""Detached assessment supervisor: start, status, stop. No shell quoting required."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm02.config import load_config
from llm02.datasets import atomic_json

ROOT = Path(__file__).resolve().parent


def process_birth(pid):
    try:
        # Field 22, after pid and the parenthesized process name.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, PermissionError, IndexError):
        return None


def active(state):
    return bool(state.get('status') == 'running' and state.get('pid') and state.get('process_birth') and
                process_birth(state['pid']) == state['process_birth'])


def start(config_path, logs):
    logs.mkdir(parents=True, exist_ok=True)
    lock = (logs / 'background.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError('a background assessment is already running; use status or stop')
    stamp = datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d-%H%M%S')
    log_path = logs / f'sarvam-30b-{stamp}-{time.time_ns() % 1000000:06d}.log'
    with log_path.open('ab', buffering=0) as output:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_worker',
                    '--config', str(config_path), '--logs', str(logs), '--lock-fd', str(lock.fileno()),
                    '--log-file', str(log_path)], cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(lock.fileno(),))
    lock.close()  # Inherited descriptor keeps the lock until the worker exits.
    link = logs / 'latest.log'
    if link.is_symlink() or not link.exists():
        tmp = logs / f'.latest-{os.getpid()}'
        tmp.symlink_to(log_path.name)
        os.replace(tmp, link)
    # Wait briefly for the supervisor's durable state, not for assessment completion.
    for _ in range(100):
        state_path = logs / 'background.json'
        if state_path.exists() and json.loads(state_path.read_text()).get('pid') == child.pid:
            break
        if child.poll() is not None:
            raise RuntimeError(f'background startup failed; inspect {log_path}')
        time.sleep(0.02)
    print(f'Started in background. Supervisor PID: {child.pid}\nLog: {log_path}\n'
          f'Follow: tail -f {logs / "latest.log"}\nStatus: .venv/bin/python background.py status')


def worker(args):
    state_path = args.logs / 'background.json'
    state = {'pid': os.getpid(), 'process_birth': process_birth(os.getpid()), 'config': str(args.config),
             'log': str(args.log_file), 'started_at': time.time(), 'status': 'running'}
    atomic_json(state_path, state)
    stopping = False
    child = None
    def stop(signum, _):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        child = subprocess.Popen([sys.executable, '-u', str(ROOT / 'run.py'), '--config', str(args.config)], cwd=ROOT)
        if stopping:
            child.send_signal(signal.SIGTERM)
        state['assessment_pid'] = child.pid
        atomic_json(state_path, state)
        code = child.wait()
        state.update(status='stopped' if stopping else ('finished' if code == 0 else 'finished_with_errors'),
                     exit_code=code, finished_at=time.time())
        atomic_json(state_path, state)
        print(f'Background assessment {state["status"]}; exit code {code}.', flush=True)
        return code
    finally:
        os.close(args.lock_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop', '_worker'])
    parser.add_argument('--config', type=Path, default=ROOT / 'config.yaml')
    parser.add_argument('--logs', type=Path, default=ROOT / 'logs')
    parser.add_argument('--lock-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--log-file', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.config, args.logs = args.config.resolve(), args.logs.resolve()
    if args.action == '_worker':
        return worker(args)
    if args.action == 'start':
        load_config(args.config)  # Validate before detaching.
        start(args.config, args.logs)
        return 0
    state_path = args.logs / 'background.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args.action == 'stop':
        if not active(state):
            print('No active background assessment.')
            return 0
        os.kill(state['pid'], signal.SIGTERM)
        print('Graceful stop requested. In-flight requests may take up to their timeout/retry budget to settle.')
        return 0
    print(json.dumps({**state, 'process_alive': active(state)}, indent=2))
    config_path = Path(state.get('config', args.config))
    cfg = load_config(config_path)
    latest_path = Path(cfg['output']['directory']) / 'latest.json'
    if latest_path.exists():
        location = json.loads(latest_path.read_text())
        print(f'Report: {location["report"]}')
        checkpoint = Path(location['directory']) / 'state.json'
        if checkpoint.exists():
            from run_names import run_name
            progress = json.loads(checkpoint.read_text())
            saved_config = Path(location['directory']) / 'config.json'
            model = json.loads(saved_config.read_text())['model'] if saved_config.exists() else cfg['model']
            name = run_name('llm02', model, location.get('run_id', Path(location['directory']).name),
                            progress['total'], 'test')
            print(f'Run name: {name}')
            print(checkpoint.read_text())
    else:
        print('No run checkpoint yet; dataset preparation may still be running.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as exc:
        print(f'Background runner: {exc}', file=sys.stderr)
        sys.exit(2)
