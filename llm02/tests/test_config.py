import copy

from pathlib import Path
import pytest
import yaml

from llm02.config import fingerprint, load_config, validate_endpoint


@pytest.mark.parametrize('section,key,value', [
    ('datasets', 'unknown_source', True), ('execution', 'max_retries', -1),
    ('execution', 'concurrency', 0), ('execution', 'timeout_seconds', float('inf')),
    ('evaluation', 'partial_fraction', 1.1), ('evaluation', 'partial_min_chars', 0),
    ('risk', 'thresholds', {'critical': 1, 'high': 4, 'medium': 2, 'low': 0}),
])
def test_config_rejects_invalid(tmp_path, section, key, value):
    from pathlib import Path
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.mock.yaml').read_text())
    data.setdefault(section, {})[key] = value
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        load_config(path)


def test_endpoint_missing_key(monkeypatch):
    monkeypatch.delenv('LLM02_NONEXISTENT_KEY', raising=False)
    with pytest.raises(ValueError, match='missing credential'):
        validate_endpoint({'mode': 'openai', 'base_url': 'https://example.test/v1', 'model': 'test',
                           'api_key_env': 'LLM02_NONEXISTENT_KEY'})


def test_fingerprint_behavior():
    cfg = load_config(Path(__file__).resolve().parents[1] / 'config.mock.yaml')
    original = fingerprint(cfg, [])
    cfg['output']['directory'] = '/different/location'
    assert fingerprint(cfg, []) == original
    cfg['generation']['temperature'] = 0.3
    assert fingerprint(cfg, []) != original
