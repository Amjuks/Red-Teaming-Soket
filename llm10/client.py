"""Data-only Loop transport; credentials never enter Python or reports."""
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'native/loop-bridge/target/debug/owasp-llm10-loop-bridge'


def resolve(model):
    if model['mode'] == 'mock':
        return {'transport': 'mock', 'model': model['model']}
    if not BRIDGE.exists():
        subprocess.run(['cargo','build','--locked','--manifest-path',str(ROOT/'native/llm10-loop-bridge/Cargo.toml'),
                        '--target-dir',str(ROOT/'native/loop-bridge/target')], check=True, timeout=900)
    result = subprocess.run([str(BRIDGE)], input=json.dumps({'action':'describe', **model}),
                            text=True, capture_output=True, timeout=30, check=True)
    data = json.loads(result.stdout)
    if not data.get('ok'): raise ValueError(data.get('error', 'Loop resolution failed'))
    return {**data, 'bridge_sha256':hashlib.sha256(BRIDGE.read_bytes()).hexdigest()}


async def complete(model, messages, max_tokens, key, timeout):
    if model['mode'] == 'mock':
        await asyncio.sleep(.005)
        content = 'Mock response: request received.'
        return {'ok':True,'response':{'content':content,'reasoning':'','status_code':200,
                'usage':{'input':sum(len(m['content'].encode())//4+1 for m in messages),'output':8},
                'finish_reason':'stop','rate_limits':{},'ttft_seconds':None,'transport':'mock'}}
    payload = {**model,'messages':messages,'generation':{'max_tokens':max_tokens,'temperature':0},
               'request_key':key,'timeout_seconds':timeout}
    process = await asyncio.create_subprocess_exec(str(BRIDGE), stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out,_ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout+5)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None: process.kill()
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError): raise
        return {'ok':False,'error':'timeout','retryable':True,'status_code':None}
    try:
        data = json.loads(out)
        if not isinstance(data,dict) or not isinstance(data.get('ok'),bool): raise ValueError()
        if data['ok']:
            r = data['response']
            if not isinstance(r.get('content'),str) or not isinstance(r.get('reasoning',''),str): raise ValueError()
        return data
    except (ValueError, KeyError, TypeError):
        return {'ok':False,'error':'malformed_bridge_response','retryable':True,
                'raw_stdout':out.decode(errors='replace'),'status_code':None}
