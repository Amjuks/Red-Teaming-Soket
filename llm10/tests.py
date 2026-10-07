"""Deterministic workload manifests from existing dataset prompts.

Input size uses an explicitly approximate UTF-8-bytes/4 estimate until a target
tokenizer is configured. This is NOT an endpoint context-window measurement.
"""
import math

from .datasets import stratified
from .files import digest

EXPENSIVE = {'reasoning', 'multi_hop_qa', 'coding', 'summarization'}


def estimated_tokens(text):
    return max(1, math.ceil(len(text.encode('utf-8')) / 4))


def resize(prompt, target):
    """Keep natural size near target; otherwise controlled repeat or prefix trim."""
    before = estimated_tokens(prompt)
    if target * .9 <= before <= target * 1.1:
        return prompt, 'natural'
    if before < target:
        block = (prompt + '\n\n').encode('utf-8')
        value = (block * math.ceil(target * 4 / len(block)))[:target*4].decode('utf-8', errors='ignore')
        return value, 'repeat_original_prompt_then_trim_utf8_prefix'
    return prompt.encode()[:target*4].decode('utf-8', errors='ignore'), 'trim_original_utf8_prefix'


def build_manifest(cfg, samples):
    seed, counts, levels = cfg['datasets']['seed'], cfg['tests'], cfg['levels']
    if len(samples) != counts['baseline']:
        raise ValueError('baseline requires the entire selected corpus')
    ordered = sorted(samples, key=lambda r:r['sample_id'])
    selected, calls = {}, []
    for family in counts:
        pool = ordered
        if family in ('output_growth', 'expensive_workloads'):
            preferred = [s for s in ordered if s['task'] in EXPENSIVE]
            preferred_ids = {s['sample_id'] for s in preferred}
            # Naturally long general/QA samples supplement demanding task labels.
            others = sorted([s for s in ordered if s['sample_id'] not in preferred_ids],
                            key=lambda s:(-len(s['prompt']),s['sample_id']))
            pool = preferred + others[:max(0, counts[family]-len(preferred))]
        selected[family] = stratified(pool, counts[family], seed)
    def add(family, level, sample, turn=1, repetition=1, prompt=None, transform='none', context_ids=None):
        key = [family, level, sample['sample_id'], turn, repetition]
        call_id = digest(key)[:24]
        conversation_id = digest([family, level if family != 'context_growth' else 'history', sample['sample_id'],
                                  repetition if family == 'repetition' else 1])[:24]
        text = sample['prompt'] if prompt is None else prompt
        calls.append({'call_id': call_id, 'test_id': digest([family,sample['sample_id']])[:24],
                      'conversation_id':conversation_id, 'turn':turn,
                      'family':family, 'level':level, 'sample_id':sample['sample_id'],
                      'dataset':sample['dataset'], 'task':sample['task'],
                      'source_sample_id':sample['source_sample_id'], 'prompt':text,
                      'transformation':transform, 'estimated_input_tokens':estimated_tokens(text),
                      'input_measurement':'utf8_bytes_div_4_estimate_excludes_chat_template',
                      'requested_max_tokens':level if family=='output_growth' else cfg['execution']['baseline_max_tokens'],
                      'concurrency':level if family=='concurrency' else 1, 'repetition':repetition,
                      'context_sample_ids':context_ids or [],
                      'selection_reason':'task_label_or_natural_length' if family in ('output_growth','expensive_workloads') else 'seeded_task_stratification'})
    for s in selected['baseline']: add('baseline',1,s)
    for target in levels['input_tokens']:
        # Same stratified subset per level, sorted closest to natural target first.
        for s in sorted(selected['input_growth'],key=lambda s:(abs(estimated_tokens(s['prompt'])-target),s['sample_id'])):
            prompt, transform = resize(s['prompt'],target)
            add('input_growth',target,s,prompt=prompt,transform=transform)
    for target in levels['output_tokens']:
        for s in selected['output_growth']: add('output_growth',target,s)
    for i,s in enumerate(selected['context_growth']):
        history_ids=[]
        for turn in range(1,cfg['execution']['context_turns']+1):
            item=s if turn==1 else ordered[(i+turn-2)%len(ordered)]
            history_ids.append(item['sample_id'])
            add('context_growth',turn,s,turn=turn,prompt=item['prompt'],context_ids=list(history_ids))
    for count in levels['repetitions']:
        for s in selected['repetition']:
            for repeat in range(1,count+1): add('repetition',count,s,repetition=repeat)
    for count in levels['concurrency']:
        for s in selected['concurrency']: add('concurrency',count,s)
    for s in selected['expensive_workloads']: add('expensive_workloads',1,s)
    return {'schema_version':1, 'calls':calls, 'samples':ordered,
            'selection_ids':{k:[s['sample_id'] for s in v] for k,v in selected.items()},
            'limitations':['Input sizes are estimates, not model-tokenizer measurements.',
                          'Context history is assembled from actual durable responses at execution time.',
                          'Natural long inputs may exceed safety ceilings and must be explicitly skipped by executor.']}
