"""Local paths, canonical identities, strict configuration and atomic artifacts."""
import hashlib
import json
import os
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)

def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()[:24]

def local_path(value):
    p = (ROOT / value).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('all writable paths must remain under llm06')
    return p

def atomic_json(path, value):
    path = local_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as f:
        f.write(canonical(value) + '\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def obj(properties, required=None):
    return {'type':'object', 'properties':properties, 'required':list(properties) if required is None else required, 'additionalProperties':False}

S = {'type':'string', 'minLength':1}
POS = {'type':'integer', 'minimum':1}
CLIENT = obj({'transport':{'const':'loop'}, 'model':S, 'provider':S,
              'max_tokens':POS, 'timeout_seconds':POS})
CONFIG = obj({'version':{'const':1}, 'target':CLIENT, 'judge':{'anyOf':[CLIENT,{'type':'null'}]},
    'domains':{'type':'array','items':{'enum':['files','email','contacts','calendar','finance','social','users','web','messaging','healthcare','security','infrastructure','commerce','travel','workplace','communications','software','specialized_operations']},'uniqueItems':True},
    'unique_tasks':{'type':'boolean'},
    'splits':{'type':'array','items':{'enum':['core','augmented']},'minItems':1,'uniqueItems':True},
    'report_interval':{'type':'integer','minimum':1},
    'categories':{'type':'array','items':S,'uniqueItems':True},
    'sample_limit':POS, 'seed':{'type':'integer'}, 'max_turns':POS, 'action_budget':POS,
    'retries':{'type':'integer','minimum':0,'maximum':5}, 'concurrency':{'const':1},
    'variants':{'type':'array','items':{'enum':['least','broad']},'uniqueItems':True,'minItems':1},
    'dataset':{'const':'agent-safety-bench'}, 'revision':{'type':'string','pattern':'^[a-f0-9]{40}$'},
    'results_dir':S, 'reports_dir':S}, ['version','target','judge','sample_limit','seed','max_turns','action_budget','retries','concurrency','variants','dataset','revision','results_dir','reports_dir'])

def load_config(path='config.yaml'):
    c = yaml.safe_load(local_path(path).read_text())
    Draft202012Validator(CONFIG).validate(c)
    for key in ('results_dir','reports_dir'): local_path(c[key])
    return c
