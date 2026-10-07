import copy
from pathlib import Path
import subprocess

import pytest
import yaml

from llm10.config import validate, load_config, estimate_calls

ROOT = Path(__file__).resolve().parents[1]


def base():
    return yaml.safe_load((ROOT / 'llm10/config.yaml').read_text())


def test_default_and_smoke():
    cfg = load_config(ROOT / 'llm10/config.yaml')
    assert estimate_calls(cfg)['planned_calls_before_retries'] == 21500
    assert cfg['model']['model'] == 'sarvam-30b'
    assert Path(cfg['paths']['results']) == ROOT / 'llm10/results'
    for name in ('config.smoke.yaml', 'config.mock.yaml'):
        c = load_config(ROOT / 'llm10' / name)
        assert estimate_calls(c)['planned_calls_before_retries'] <= c['safety']['max_requests']


@pytest.mark.parametrize('section,key,value', [
    ('datasets','seed',True), ('datasets','alpaca',-1), ('tests','baseline',4001),
    ('execution','timeout',float('inf')), ('execution','retries',False),
    ('safety','max_tokens',float('nan')), ('safety','max_requests',0),
    ('levels','concurrency',[2,1]), ('levels','input_tokens',[500,500]),
    ('levels','output_tokens',[9000]), ('pricing','input_per_million',1),
    ('safety','max_cost',10), ('paths','results',''), ('model','mode','http'),
])
def test_invalid(section,key,value):
    c=base(); c[section][key]=value
    with pytest.raises(ValueError): validate(c)


def test_price_pair_and_strict_keys():
    c=base(); c['pricing'].update(input_per_million=1,output_per_million=2)
    c['safety']['max_cost']=10
    assert validate(c)==c
    c['execution']['typo']=1
    with pytest.raises(ValueError): validate(c)


def test_paths_relative_to_config_and_no_mutation(tmp_path):
    c=base(); before=copy.deepcopy(c)
    validate(c); assert c==before
    path=tmp_path/'config.yaml'; path.write_text(yaml.safe_dump(c))
    assert load_config(path)['paths']['data']==str(tmp_path/'data')
    c['paths']['reports']='results'; path.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError): load_config(path)


def test_script_does_not_shadow_hf_datasets():
    p=subprocess.run([str(ROOT/'llm10/.venv/bin/python'),str(ROOT/'llm10/run.py'),'--validate-config'],
                     cwd=ROOT/'llm10',capture_output=True,text=True,timeout=10)
    assert p.returncode==0,p.stderr
    assert '21500' in p.stdout


def test_reject_gated_source_and_escape(tmp_path):
    c=base(); c['datasets']['promptsuite']=0
    with pytest.raises(ValueError):validate(c)
    c=base(); c['paths']['results']='../llm02/results'
    p=tmp_path/'config.yaml';p.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError,match='isolate'):load_config(p)
    c=base();c['paths']['reports']='results/reports';p.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError,match='overlap'):load_config(p)


def test_reject_symlink_escape(tmp_path):
    outside=tmp_path/'outside';outside.mkdir()
    local=tmp_path/'llm10';local.mkdir()
    (local/'results').symlink_to(outside,target_is_directory=True)
    p=local/'config.yaml';p.write_text(yaml.safe_dump(base()))
    with pytest.raises(ValueError,match='isolate'):load_config(p)
