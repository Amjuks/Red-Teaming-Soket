from collections import Counter
from pathlib import Path

from llm10.config import load_config,estimate_calls
from llm10.datasets import normalize
from llm10.tests import build_manifest,resize,estimated_tokens


def test_manifest_counts_and_determinism():
    cfg=load_config(Path(__file__).resolve().parents[1]/'llm10/config.smoke.yaml')
    samples=[normalize('instruct_v3',{'prompt':f'Question {i}','source':'competition_math'},i) for i in range(12)]
    m=build_manifest(cfg,samples)
    assert m==build_manifest(cfg,list(reversed(samples)))
    assert Counter(c['family'] for c in m['calls'])==estimate_calls(cfg)['families']
    assert len({c['call_id'] for c in m['calls']})==len(m['calls'])
    context=[c for c in m['calls'] if c['family']=='context_growth']
    assert context[0]['conversation_id']==context[1]['conversation_id']
    assert len(context[1]['context_sample_ids'])==2


def test_resize_unicode_and_provenance():
    for prompt in ('short','हिन्दी '*500):
        out,method=resize(prompt,100)
        assert estimated_tokens(out) in range(99,102)
        assert method!='natural'
    prompt='x'*400
    assert resize(prompt,100)==(prompt,'natural')
