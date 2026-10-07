"""Pinned HF sources, explicit coverage and deterministic prompt selection.

Import this as llm10.datasets, never as top-level datasets (the HF dependency).
"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import random

from .files import digest, write_json

SPECS = {
    'alpaca': {'repo': 'tatsu-lab/alpaca', 'revision': 'dce01c9b08f87459cf36a430d809084718273017',
               'license': 'CC-BY-NC-4.0'},
    'instruct_v3': {'repo': 'mosaicml/instruct-v3', 'revision': 'd53c69fd0fa37d65a232811cec0a990c1ec3ec8f',
                    'license': 'CC-BY-SA-3.0 and underlying source terms'},
}
ADAPTER_VERSION = 3


def category(name):
    name = name.lower()
    for words, label in [(['gsm8k', 'math', 'gpqa'], 'reasoning'),
                         (['musique'], 'multi_hop_qa'), (['humaneval', 'spider'], 'coding'),
                         (['cnn', 'summ', 'dialogsum'], 'summarization'),
                         (['wmt', 'translation'], 'translation'),
                         (['sst', 'sentiment'], 'classification'),
                         (['mmlu', 'squad', 'duorc', 'qasper', 'quality'], 'qa')]:
        if any(word in name for word in words):
            return label
    return 'general_instruction'


def normalize(source, row, index, source_file='train'):
    subset = source_file
    original_id = index
    if source == 'alpaca':
        instruction, context = row.get('instruction'), row.get('input', '')
        if not isinstance(instruction, str) or not isinstance(context, str):
            raise ValueError('Alpaca instruction/input must be strings')
        prompt = instruction + ('\n\n' + context if context else '')
        original = {'instruction': instruction, 'input': context}
        task = 'general_instruction'  # Do not invent source task annotations.
    elif source == 'instruct_v3':
        prompt = row.get('prompt')
        subset = str(row.get('source') or 'unknown')
        task = category(subset)
        original = prompt
    else:
        raise ValueError('Unsupported source; only anonymous public datasets are enabled')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('prompt must be nonempty text')
    identity = {'dataset': source, 'revision': SPECS[source]['revision'], 'file': source_file,
                'index': index, 'prompt': prompt}
    return {'sample_id': digest(identity)[:24], 'dataset': source, 'repository': SPECS[source]['repo'],
            'revision': SPECS[source]['revision'], 'source_file': source_file,
            'source_sample_id': original_id, 'source_index': index, 'subset': subset,
            'task': task, 'task_label_method': 'unlabeled' if source == 'alpaca' else 'source_name_mapping',
            'original_prompt': original, 'prompt': prompt, 'prompt_sha256': digest(prompt)}


def stratified(rows, count, seed, group='task'):
    if count > len(rows):
        raise ValueError(f'requested {count} prompts but only {len(rows)} usable unique prompts')
    rng = random.Random(seed)
    buckets = defaultdict(list)
    for row in sorted(rows, key=lambda r: r['sample_id']):
        buckets[row[group]].append(row)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    selected = []
    keys = sorted(buckets)
    while len(selected) < count:
        for key in keys:
            if buckets[key] and len(selected) < count:
                selected.append(buckets[key].pop())
    return selected


def select(rows, count, seed, source):
    if source != 'instruct_v3':
        return stratified(rows, count, seed)
    # 25% longest samples, 75% source-balanced, all from original records.
    long_count = count // 4
    long_rows = sorted(rows, key=lambda r: (-len(r['prompt']), r['sample_id']))[:long_count]
    ids = {r['sample_id'] for r in long_rows}
    broad = stratified([r for r in rows if r['sample_id'] not in ids], count-long_count, seed, 'subset')
    return broad + long_rows


def source_rows(source, cache):
    from datasets import load_dataset
    spec = SPECS[source]
    data = load_dataset(spec['repo'], revision=spec['revision'], split='train',
                        cache_dir=str(cache), token=False)
    for i, row in enumerate(data):
        yield 'train', i, row


def prepare(cfg, loader=source_rows):
    directory = Path(cfg['paths']['data'])
    selection = {'version': ADAPTER_VERSION, 'sources': SPECS, 'selection': cfg['datasets']}
    key = digest(selection)[:24]
    snapshot = directory / 'normalized' / (key + '.json')
    if snapshot.exists():
        saved = json.loads(snapshot.read_text())
        if digest(saved['samples']) != saved['samples_sha256'] or saved['selection'] != selection:
            raise ValueError('normalized corpus integrity check failed')
        return saved['samples'], saved['coverage']
    samples, coverage, errors = [], {}, []
    for source, spec in SPECS.items():
        wanted = cfg['datasets'][source]
        counts = {'requested': wanted, 'loaded': 0, 'invalid': 0, 'duplicate': 0,
                  'usable': 0, 'selected': 0, 'status': 'disabled' if not wanted else 'pending', **spec}
        coverage[source] = counts
        if not wanted:
            continue
        try:
            rows, seen = [], set()
            for filename, i, row in loader(source, directory / 'huggingface'):
                counts['loaded'] += 1
                try:
                    item = normalize(source, row, i, filename)
                except (ValueError, TypeError, KeyError):
                    counts['invalid'] += 1
                    continue
                if item['prompt_sha256'] in seen:
                    counts['duplicate'] += 1
                    continue
                seen.add(item['prompt_sha256'])
                rows.append(item)
            counts['usable'] = len(rows)
            chosen = select(rows, wanted, cfg['datasets']['seed'], source)
            samples.extend(chosen)
            counts.update(status='ready', selected=len(chosen), tasks=dict(Counter(r['task'] for r in chosen)),
                          subsets=dict(Counter(r['subset'] for r in chosen)))
        except Exception as exc:
            # Do not include request URLs/headers/tokens in user-facing diagnostics.
            counts.update(status='blocked', error_type=type(exc).__name__)
            errors.append(source)
    write_json(directory / 'coverage.json', coverage)
    if errors:
        raise RuntimeError('Dataset preparation blocked: ' + ', '.join(errors) +
                           '. See data/coverage.json; check network/cache availability. No credentials are required. No inference started.')
    # Cross-source overlap is retained with explicit counts rather than silently
    # reducing the requested per-source corpus or losing original provenance.
    coverage['_selection'] = {'cross_source_duplicate_prompts': len(samples)-len({r['prompt_sha256'] for r in samples}),
                              'policy': 'Deduplicate within each source; retain and report cross-source overlap.'}
    write_json(snapshot, {'selection': selection, 'samples': samples, 'samples_sha256': digest(samples), 'coverage': coverage})
    write_json(directory / 'coverage.json', coverage)
    return samples, coverage
