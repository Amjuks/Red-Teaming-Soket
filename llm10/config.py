"""Strict settings validation; loading never makes inference requests."""
from __future__ import annotations

import copy
import math
from pathlib import Path

import yaml
from dotenv import load_dotenv

FAMILIES = ('baseline', 'input_growth', 'output_growth', 'context_growth',
            'repetition', 'concurrency', 'expensive_workloads')
SOURCES = ('alpaca', 'instruct_v3')


def number(value, name, minimum=0, integer=False):
    types = (int,) if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, types) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be a finite {"integer" if integer else "number"} >= {minimum}')
    return value


def validate(cfg):
    cfg = copy.deepcopy(cfg)
    sections = {'model', 'datasets', 'tests', 'levels', 'execution', 'safety', 'pricing', 'paths'}
    if not isinstance(cfg, dict) or set(cfg) != sections:
        raise ValueError(f'configuration must contain exactly {sorted(sections)}')
    for key in sections:
        if not isinstance(cfg[key], dict):
            raise ValueError(f'{key} must be a mapping')
    model = cfg['model']
    if set(model) != {'mode', 'provider', 'model'}:
        raise ValueError('model requires only mode, provider, model; credentials are resolved by Loop')
    if model['mode'] not in ('loop', 'mock'):
        raise ValueError('model.mode must be loop or mock')
    if any(not isinstance(model[k], str) or not model[k].strip() for k in ('provider', 'model')):
        raise ValueError('model provider/name must be nonempty strings')
    required = {
        'datasets': set(SOURCES) | {'seed'}, 'tests': set(FAMILIES),
        'levels': {'input_tokens', 'output_tokens', 'repetitions', 'concurrency'},
        'execution': {'timeout', 'retries', 'retry_backoff_seconds', 'max_backoff_seconds',
                      'uncertain_policy', 'report_interval_seconds', 'baseline_max_tokens',
                      'context_turns', 'context_input_ceiling'},
        'safety': {'max_requests', 'max_tokens', 'max_cost', 'max_concurrency',
                   'max_input_tokens', 'max_output_tokens', 'consecutive_failures',
                   'consecutive_rate_limits', 'latency_multiplier', 'latency_min_seconds', 'cooldown_seconds'},
        'pricing': {'input_per_million', 'output_per_million', 'currency'},
        'paths': {'data', 'results', 'reports'},
    }
    for section, keys in required.items():
        if set(cfg[section]) != keys:
            raise ValueError(f'{section} requires exactly {sorted(keys)}')
    for section in ('datasets', 'tests'):
        for key, value in cfg[section].items():
            number(value, f'{section}.{key}', integer=True)
    corpus = sum(cfg['datasets'][s] for s in SOURCES)
    if not corpus or cfg['tests']['baseline'] != corpus:
        raise ValueError('baseline must equal the entire nonempty selected corpus')
    if any(n > corpus for n in cfg['tests'].values()):
        raise ValueError('test subset counts cannot exceed selected corpus size')
    for key, levels in cfg['levels'].items():
        if not isinstance(levels, list) or not levels:
            raise ValueError(f'levels.{key} must be a nonempty list')
        for v in levels:
            number(v, f'levels.{key}', 1, True)
        if sorted(set(levels)) != levels:
            raise ValueError(f'levels.{key} must be strictly increasing')
    ex = cfg['execution']
    for key in ('timeout', 'report_interval_seconds', 'baseline_max_tokens', 'context_turns', 'context_input_ceiling'):
        number(ex[key], f'execution.{key}', 1, True)
    number(ex['retries'], 'execution.retries', integer=True)
    for key in ('retry_backoff_seconds', 'max_backoff_seconds'):
        number(ex[key], f'execution.{key}', 0.01)
    if ex['max_backoff_seconds'] < ex['retry_backoff_seconds']:
        raise ValueError('max_backoff_seconds must be >= retry_backoff_seconds')
    if ex['uncertain_policy'] not in ('record', 'retry'):
        raise ValueError('execution.uncertain_policy must be record or retry')
    safety = cfg['safety']
    for key in ('max_requests', 'max_tokens', 'max_concurrency', 'max_input_tokens',
                'max_output_tokens', 'consecutive_failures', 'consecutive_rate_limits'):
        number(safety[key], f'safety.{key}', 1, True)
    for key in ('latency_multiplier', 'latency_min_seconds', 'cooldown_seconds'):
        number(safety[key], f'safety.{key}', 0.01)
    if safety['latency_multiplier'] <= 1:
        raise ValueError('safety.latency_multiplier must exceed 1')
    for dimension in ('input_tokens', 'output_tokens', 'concurrency'):
        if max(cfg['levels'][dimension]) > safety['max_' + dimension]:
            raise ValueError(f'levels.{dimension} exceeds safety ceiling')
    if ex['baseline_max_tokens'] > safety['max_output_tokens'] or ex['context_input_ceiling'] > safety['max_input_tokens']:
        raise ValueError('execution token caps exceed safety ceilings')
    prices = cfg['pricing']
    pair = [prices[k] for k in ('input_per_million', 'output_per_million')]
    if (pair[0] is None) != (pair[1] is None):
        raise ValueError('configure both input/output prices, or neither')
    for p in pair:
        if p is not None:
            number(p, 'pricing per million')
    if not isinstance(prices['currency'], str) or not prices['currency'].strip():
        raise ValueError('pricing.currency must be nonempty')
    if safety['max_cost'] is not None:
        number(safety['max_cost'], 'safety.max_cost', 0.000001)
        if pair[0] is None:
            raise ValueError('cost ceiling requires both input/output prices')
    for key, value in cfg['paths'].items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'paths.{key} must be nonempty')
    return cfg


def load_config(path):
    path = Path(path).resolve()
    load_dotenv(path.parent / '.env', override=False)
    cfg = validate(yaml.safe_load(path.read_text()))
    cfg['paths'] = {k: str((path.parent / v).resolve()) for k, v in cfg['paths'].items()}
    if len(set(cfg['paths'].values())) != 3:
        raise ValueError('data/results/reports directories must be distinct')
    for value in cfg['paths'].values():
        target = Path(value)
        if target == path.parent or not target.is_relative_to(path.parent):
            raise ValueError('data/results/reports must stay inside the configuration directory to isolate this run')
    targets = [Path(v) for v in cfg['paths'].values()]
    if any(a.is_relative_to(b) for a in targets for b in targets if a != b):
        raise ValueError('data/results/reports must not overlap')
    return cfg


def estimate_calls(cfg):
    n, levels = cfg['tests'], cfg['levels']
    families = {'baseline': n['baseline'], 'input_growth': n['input_growth'] * len(levels['input_tokens']),
                'output_growth': n['output_growth'] * len(levels['output_tokens']),
                'context_growth': n['context_growth'] * cfg['execution']['context_turns'],
                'repetition': n['repetition'] * sum(levels['repetitions']),
                'concurrency': n['concurrency'] * len(levels['concurrency']),
                'expensive_workloads': n['expensive_workloads']}
    calls = sum(families.values())
    return {'families': families, 'planned_calls_before_retries': calls,
            'theoretical_calls_with_retries': calls * (cfg['execution']['retries'] + 1),
            'request_safety_ceiling': cfg['safety']['max_requests'],
            'note': 'Independent repetition levels; each concurrency level runs the complete subset. Safety stops may reduce actual calls.'}
