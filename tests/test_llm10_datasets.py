import json
from pathlib import Path

import pytest

from llm10.config import load_config
from llm10.datasets import normalize, prepare, stratified, select

ROOT=Path(__file__).resolve().parents[1]


def test_alpaca_does_not_include_answer():
    r=normalize('alpaca',{'instruction':'Question','input':'Context','output':'secret answer'},7)
    assert r['prompt']=='Question\n\nContext'
    assert 'answer' not in r['prompt']
    assert r['source_index']==7


def test_instruct_and_removed_gated_source():
    r=normalize('instruct_v3',{'prompt':'Read this','response':'answer','source':'qasper'},0)
    assert r['task']=='qa' and r['prompt']=='Read this'
    with pytest.raises(ValueError): normalize('promptsuite',{'instance':{'raw_input':'unrendered'}},0)


def rows():
    return [normalize('instruct_v3',{'prompt':str(i)+' text '*i,'source':['qasper','spider','competition_math'][i%3]},i) for i in range(30)]


def test_stratification_and_long_selection():
    r=rows()
    assert stratified(r,12,42)==stratified(list(reversed(r)),12,42)
    chosen=select(r,12,42,'instruct_v3')
    assert len({x['sample_id'] for x in chosen})==12
    assert set(x['source_index'] for x in chosen[-3:])=={27,28,29}
    with pytest.raises(ValueError): stratified(r,31,42)


def test_cache_integrity_and_blocked_source(tmp_path):
    cfg=load_config(ROOT/'llm10/config.smoke.yaml'); cfg['paths']['data']=str(tmp_path)
    def loader(source,cache):
        for i in range(10):
            yield 'train',i,({'instruction':str(i),'input':''} if source=='alpaca' else {'prompt':str(i),'source':'qasper'})
    a,c=prepare(cfg,loader)
    assert len(a)==12 and c['_selection']['cross_source_duplicate_prompts']>=0
    assert prepare(cfg,lambda *a: pytest.fail('cache missed'))==(a,c)
    p=next((tmp_path/'normalized').glob('*.json')); v=json.loads(p.read_text())
    v['samples'][0]['prompt']='tampered'; p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='integrity'): prepare(cfg,loader)
    cfg['paths']['data']=str(tmp_path/'blocked')
    def broken(*args): raise PermissionError('secret token must not be printed')
    with pytest.raises(RuntimeError,match='blocked'): prepare(cfg,broken)
    assert 'secret token' not in (tmp_path/'blocked/coverage.json').read_text()


def test_hf_downloads_explicitly_anonymous(monkeypatch,tmp_path):
    datasets = pytest.importorskip('datasets')
    from llm10.datasets import source_rows
    calls=[]
    def load(*args,**kwargs):calls.append(kwargs);return [{'instruction':'test','input':''}]
    monkeypatch.setattr(datasets,'load_dataset',load)
    monkeypatch.setenv('HF_TOKEN','must-not-be-used')
    assert len(list(source_rows('alpaca',tmp_path)))==1
    assert calls[0]['token'] is False
