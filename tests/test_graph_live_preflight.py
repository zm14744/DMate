"""Real OCR preparation must not claim ready with an absent stage."""
import pytest

from scripts import benchmark_graph_first_pass as runner


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'synthetic-key-never-sent')
    monkeypatch.delenv('DASHSCOPE_VISION_API_KEY', raising=False)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'synthetic-key-never-sent')
    monkeypatch.setenv('VISION_ANALYSIS_ENABLED', '1')
    monkeypatch.setattr(runner.importlib.util, 'find_spec', lambda name: object())


@pytest.mark.parametrize(('missing', 'expected'), [
    ('DASHSCOPE_API_KEY', 'qwen_key_present'),
    ('DEEPSEEK_API_KEY', 'deepseek_key_present'),
])
def test_either_missing_provider_blocks_live_preflight(configured, monkeypatch, missing, expected):
    monkeypatch.delenv(missing)
    result = runner.preflight([], {}, 'local')
    assert result['status'] == 'blocked'
    assert result['blocking_credentials'] == [expected]
    assert result['api_calls_made'] == 0


@pytest.mark.parametrize('missing', ['paddle', 'paddleocr'])
def test_missing_local_ocr_dependency_blocks_live_preflight(configured, monkeypatch, missing):
    monkeypatch.setattr(runner.importlib.util, 'find_spec', lambda name: None if name == missing else object())
    result = runner.preflight([], {}, 'local')
    assert result['status'] == 'blocked'
    assert result['blocking_dependencies'] == [missing]
    assert result['api_calls_made'] == 0


def test_disabled_vision_is_not_ready_despite_both_keys(configured, monkeypatch):
    monkeypatch.setenv('VISION_ANALYSIS_ENABLED', 'off')
    result = runner.preflight([], {}, 'local')
    assert result['status'] == 'blocked'
    assert result['blocking_configuration'] == ['VISION_ANALYSIS_ENABLED']


def test_complete_local_configuration_is_ready_without_sending(configured):
    result = runner.preflight([], {}, 'local')
    assert result['status'] == 'ready'
    assert result['blocking_dependencies'] == result['blocking_credentials'] == result['blocking_configuration'] == []
    assert result['api_calls_made'] == 0


def test_http_preflight_does_not_infer_remote_credentials_from_local_env(configured, monkeypatch):
    monkeypatch.delenv('DASHSCOPE_API_KEY')
    monkeypatch.delenv('DEEPSEEK_API_KEY')
    monkeypatch.setattr(runner.importlib.util, 'find_spec', lambda name: None)
    result = runner.preflight([], {}, 'http')
    assert result['status'] == 'ready'
    assert result['blocking_credentials'] == result['blocking_dependencies'] == []
    assert result['notes'] == ['HTTP credentials/source identity belong to the local server and are not established by this preflight']
    assert result['api_calls_made'] == 0
