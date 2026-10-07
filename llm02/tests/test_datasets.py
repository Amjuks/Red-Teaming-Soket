import json
from pathlib import Path

import pytest

from llm02.config import load_config
from llm02.datasets import (ADAPTERS, adapt_passwordeval, adapt_peep,
                            extracted_values, prepare)


def test_authorized_password_keeps_password_protected():
    row = {'system_prompt': 'policy', 'user_prompt': 'authenticated', 'password': 'SYNTH_PASSWORD',
           'confidential_info': 'Permitted story', 'compliant': True}
    case = adapt_passwordeval(row)
    assert case.expected == 'benign'
    assert case.protected_values == ['SYNTH_PASSWORD']
    assert case.metadata['allowed_values'] == ['Permitted story']
    row['compliant'] = False
    assert len(adapt_passwordeval(row).protected_values) == 2


def test_peep_json_annotation():
    c = adapt_peep({'system_prompt': 's', 'user_prompt': 'p',
                    'confidential_data': '[{"name":"Alice Example"},{"id":"SYNTH_1234"}]'})
    assert c.protected_values == ['Alice Example', 'SYNTH_1234']


def test_extraction():
    assert extracted_values('password=Q7v!kP2#nL8@xS3 connect_timeout=3', 'password') == ['Q7v!kP2#nL8@xS3']
    assert extracted_values('routing 096701695; account 248437931183; amount 3,110.32', 'financial') == ['096701695', '248437931183']


def test_normalization_accounting_and_duplicates(tmp_path):
    path = tmp_path / 'local.jsonl'
    rows = [{'prompt': 'Explain recursion.', 'label': 'benign'},
            {'prompt': 'Explain recursion.', 'label': 'benign'},
            {'prompt': 'unrelated', 'label': 'jailbreak'}, {'label': 'sensitive'}]
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows) + 'broken\n')
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.mock.yaml')
    cfg['datasets'] = {'comparison_dataset': {'path': str(path)}}
    cfg['output']['cache_directory'] = str(tmp_path / 'cache')
    cases, coverage = prepare(cfg)
    s = coverage['datasets']['comparison_dataset']
    assert len(cases) == 1
    assert s['loaded'] == 5
    assert s['accepted'] == 2
    assert s['duplicate'] == 1
    assert s['invalid'] == 2
    assert s['filtered_as_irrelevant'] == 1
    assert len(cases[0].metadata['provenance']) == 2


def test_enabled_missing_dataset_is_error(tmp_path):
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.mock.yaml')
    cfg['datasets'] = {'peep': {'path': str(tmp_path / 'missing.jsonl')}}
    cfg['output']['cache_directory'] = str(tmp_path / 'cache')
    _, coverage = prepare(cfg)
    assert coverage['datasets']['peep']['status'] == 'error'


def test_limit_accounting(tmp_path):
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.mock.yaml')
    cfg['datasets'] = {'synthetic': {'limit': 3}}
    cfg['output']['cache_directory'] = str(tmp_path / 'cache')
    cases, coverage = prepare(cfg)
    s = coverage['datasets']['synthetic']
    assert len(cases) == 3
    assert s['accepted'] == s['limited'] + s['duplicate'] + s['final_test_count']


@pytest.mark.integration
def test_actual_cached_datasets():
    # Explicit opt-in network test; every configured adapter must process real data.
    import os
    if os.environ.get('LLM02_NETWORK_TESTS') != '1':
        pytest.skip('set LLM02_NETWORK_TESTS=1 to validate actual upstream sources')
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.full.yaml')
    cases, coverage = prepare(cfg)
    assert len(coverage['datasets']) == 8
    assert all(c['status'] == 'ready' and c['invalid'] == 0 for c in coverage['datasets'].values())
    assert all(c.id and c.user_prompt for c in cases)
    assert len({c.id for c in cases}) == len(cases)
