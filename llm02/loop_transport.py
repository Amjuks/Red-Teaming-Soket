"""Use Loop's Rust provider implementation; Python never reads its credentials."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_BRIDGE = ROOT / 'native/loop-bridge/target/debug/owasp-loop-bridge'


class LoopFailure(Exception):
    def __init__(self, message, retryable=False, retry_after=None, detail=None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.detail = detail


def bridge_path(model):
    return Path(model.get('bridge_binary', DEFAULT_BRIDGE)).resolve()


def bridge_environment(model):
    env = os.environ.copy()
    if model.get('agent_directory'):
        env['LOOP_CODING_AGENT_DIR'] = model['agent_directory']
    return env


def prepare_loop(model):
    """Resolve identity before computing run ID. Builds the local bridge if absent."""
    path = bridge_path(model)
    if not path.is_file():
        if path != DEFAULT_BRIDGE.resolve():
            raise ValueError(f'Loop bridge not found: {path}')
        print('Building the Loop API bridge (first run only)...', flush=True)
        try:
            subprocess.run(['cargo', 'build', '--locked', '--manifest-path', str(ROOT / 'native/loop-bridge/Cargo.toml')],
                           cwd=ROOT, check=True, timeout=900)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('Loop bridge build failed; see build output above') from exc
    payload = {'action': 'describe', 'provider': model.get('provider'), 'model': model.get('model')}
    try:
        result = subprocess.run([str(path)], input=json.dumps(payload), text=True, capture_output=True,
                                env=bridge_environment(model), timeout=20, check=True)
        description = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError('cannot resolve the configured Loop provider/model') from exc
    if not description.get('ok'):
        raise ValueError(description.get('error', 'Loop provider configuration failed'))
    model.update(model=description['model'], provider=description['provider'], bridge_binary=str(path))
    # Persist public routing identity and implementation identity, never credential files.
    model['loop_identity'] = {k: description[k] for k in ('provider', 'model', 'api', 'base_url', 'agent_dir', 'transport')}
    model['bridge_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return description


async def complete(model, messages, generation, request_key, timeout_seconds):
    payload = {'provider': model.get('provider'), 'model': model['model'], 'messages': messages,
               'generation': generation, 'request_key': request_key, 'timeout_seconds': int(timeout_seconds)}
    try:
        process = await asyncio.create_subprocess_exec(str(bridge_path(model)),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=bridge_environment(model))
    except OSError as exc:
        raise LoopFailure('cannot start Loop bridge') from exc
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout_seconds + 5)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise LoopFailure('Loop request timed out', retryable=True) from exc
    if process.returncode:
        raise LoopFailure('Loop bridge exited unexpectedly', retryable=True)
    try:
        result = json.loads(stdout)
        if not result['ok']:
            raise LoopFailure(result.get('error', 'Loop request failed'),
                              retryable=bool(result.get('retryable')), retry_after=result.get('retry_after'),
                              detail=result.get('detail'))
        response = result['response']
        if not isinstance(response['content'], str) or not isinstance(response.get('reasoning', ''), str):
            raise ValueError('invalid text')
        return response
    except (ValueError, KeyError, TypeError) as exc:
        raise LoopFailure('malformed Loop bridge response', retryable=True) from exc
