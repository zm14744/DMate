"""Zero-network Flask fault injection; no original images or model execution."""
from copy import deepcopy
import importlib
import io

from PIL import Image
import pytest
import requests


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv('DMATE_GRAPH_NEXTGEN', '1')
    # These historical worker-health contracts exercise the retained route
    # which actually requests Paddle; semantic default routing is tested apart.
    monkeypatch.setenv('DMATE_GRAPH_PIPELINE', 'evidence-two-pass')
    for key in ('DATABASE_URL', 'POSTGRES_CONNECTION_STRING', 'POSTGRES_URL',
                'PGHOST', 'POSTGRES_HOST', 'DASHSCOPE_API_KEY',
                'DASHSCOPE_VISION_API_KEY', 'DEEPSEEK_API_KEY', 'ZHIPU_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    calls = {'network': 0, 'models': 0, 'legacy_vision': 0, 'legacy_audit': 0}

    def forbidden(name):
        def fail(*args, **kwargs):
            calls[name] += 1
            raise AssertionError('Forbidden in application contract: '+name)
        return fail

    monkeypatch.setattr(requests.sessions.Session, 'send', forbidden('network'))
    import ocr_runtime
    monkeypatch.setattr(ocr_runtime, 'load_models', forbidden('models'))
    module = importlib.import_module('app')
    monkeypatch.setattr(module, 'OCR_AVAILABLE', True)
    monkeypatch.setattr(module, '_ocr_ready', False)
    monkeypatch.setattr(module, '_ocr_status', '未初始化')
    monkeypatch.setattr(module, '_ocr_stages', {})
    monkeypatch.setattr(module, '_check_rate_limit', lambda *args: True)
    monkeypatch.setattr(module, 'analyze_image_structure', forbidden('legacy_vision'))
    monkeypatch.setattr(module, 'verify_graph_image_independently', forbidden('legacy_audit'))
    monkeypatch.setattr(module, 'load_models', forbidden('models'))
    module.app.config.update(TESTING=True)
    yield module, module.app.test_client(), calls
    assert calls == {'network': 0, 'models': 0, 'legacy_vision': 0, 'legacy_audit': 0}


def local_result(text_status='ok', *, layout_status='ok', **extra):
    return {'text': '', 'text_count': 0, 'formula_count': 0, 'review_regions': [],
            'warning': None if text_status == 'ok' else '题目文字未能完整识别',
            'layout': {'status': layout_status, 'regions': []},
            'resource_metrics': [{'stage': 'layout', 'status': layout_status},
                                 {'stage': 'text', 'status': text_status}], **extra}


def graph_result(*, source='paddle', second_review=False):
    return {'text': '', 'visual_text': '合成路由契约样例',
            'graph_structures': [], 'graph_display_data': [],
            'recognition_status': 'complete', 'review': {'required': False, 'reasons': []},
            'diagnostics': {'text_evidence': {'source': source, 'complete': True,
                                             'visual_body_complete': True,
                                             'second_pass_reviewed': second_review}}}


def post_image(client):
    data = io.BytesIO()
    Image.new('RGB', (1, 1), 'white').save(data, 'PNG')
    data.seek(0)
    return client.post('/ocr', data={'image': (data, 'synthetic.png')},
                       content_type='multipart/form-data')


@pytest.mark.parametrize('flag', ['0', '1'])
def test_deployment_identity_exposes_pipeline_selection_without_model_calls(application, monkeypatch, flag):
    _, client, _ = application
    from graph_pipeline_version import active_pipeline_version
    monkeypatch.setenv('DMATE_GRAPH_NEXTGEN', flag)
    for route in ('/health', '/ready'):
        response = client.get(route)
        assert response.status_code == 200
        data = response.get_json()
        assert data['graph_nextgen_enabled'] is (flag == '1')
        assert data['graph_nextgen_version'] == active_pipeline_version()


@pytest.mark.parametrize('status', ['memory_limit', 'memory_admission_rejected', 'timeout',
                                   'worker_failed', 'cache_unavailable', 'unknown'])
def test_returned_text_worker_failure_never_becomes_formula_degradation(application, monkeypatch, status):
    module, client, _ = application
    import ocr_nextgen
    monkeypatch.setattr(module, 'recognize_image', lambda raw: local_result(status))
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', lambda *args, **kwargs: graph_result())
    response = post_image(client)
    assert response.status_code == 200
    body = response.get_json()
    ready = client.get('/ready').get_json()
    assert ready['ocr_available'] is True and ready['ocr_ready'] is False
    assert ready['ocr_stages']['text']['status'] == status
    assert '公式' not in ready['ocr_status']
    assert body['recognition_status'] == 'partial' and body['review']['required'] is True
    assert body['diagnostics']['local_ocr']['text_succeeded'] is False
    assert body['diagnostics']['text_evidence']['complete'] is False
    assert body['review']['reasons'].count('题干文字尚未核对完整。') == 1


def test_successful_blank_text_stage_is_ready_and_layout_failure_has_its_own_state(application, monkeypatch):
    module, client, _ = application
    import ocr_nextgen
    monkeypatch.setattr(module, 'recognize_image', lambda raw: local_result(layout_status='worker_failed'))
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', lambda *args, **kwargs: graph_result())
    body = post_image(client).get_json()
    ready = client.get('/ready').get_json()
    assert ready['ocr_ready'] is True
    assert '版面' in ready['ocr_status'] and '公式' not in ready['ocr_status']
    assert body['recognition_status'] == 'complete'
    assert body['diagnostics']['local_ocr']['stages']['layout']['status'] == 'worker_failed'


@pytest.mark.parametrize('reviewed', [False, True])
def test_independent_visual_text_review_can_replace_failed_local_text(application, monkeypatch, reviewed):
    module, client, _ = application
    import ocr_nextgen
    monkeypatch.setattr(module, 'recognize_image', lambda raw: local_result('memory_limit'))
    original = graph_result(source='original_visual_transcription', second_review=reviewed)
    before = deepcopy(original)
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', lambda *args, **kwargs: original)
    body = post_image(client).get_json()
    assert body['recognition_status'] == ('complete' if reviewed else 'partial')
    assert body['diagnostics']['text_evidence']['complete'] is reviewed
    assert client.get('/ready').get_json()['ocr_ready'] is False
    assert original == before


def test_old_warning_is_not_assumed_to_be_a_formula_failure(application, monkeypatch):
    module, client, _ = application
    import ocr_nextgen
    monkeypatch.setattr(module, 'recognize_image', lambda raw: {'text': '', 'warning': '文字中的数字有冲突。'})
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', lambda *args, **kwargs: graph_result())
    assert post_image(client).status_code == 200
    ready = client.get('/ready').get_json()
    assert ready['ocr_ready'] is True and '公式' not in ready['ocr_status']
    assert ready['ocr_stages']['text']['evidence'] == 'legacy_return'


def test_explicit_formula_failure_is_distinct_from_text_failure(application, monkeypatch):
    module, client, _ = application
    import ocr_nextgen
    result = local_result()
    result['resource_metrics'].append({'stage': 'formula', 'status': 'worker_failed'})
    monkeypatch.setattr(module, 'recognize_image', lambda raw: result)
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', lambda *args, **kwargs: graph_result())
    assert post_image(client).status_code == 200
    ready = client.get('/ready').get_json()
    assert ready['ocr_ready'] is True and ready['ocr_status'] == '已就绪（公式识别降级）'


@pytest.mark.parametrize('consumed', [0, 1, 2])
def test_entered_new_chain_exception_never_restarts_legacy_vision(application, monkeypatch, consumed):
    module, client, _ = application
    import ocr_nextgen
    monkeypatch.setattr(module, 'recognize_image', lambda raw: local_result())
    fake_sent = []

    def broken_new_chain(*args, **kwargs):
        fake_sent.extend(range(consumed))
        raise RuntimeError('injected after synthetic sends')

    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', broken_new_chain)
    response = post_image(client)
    assert response.status_code == 503 and len(fake_sent) == consumed
    body = response.get_json()
    assert body['recognition_status'] == 'failed' and body['review']['required'] is True
    assert body['diagnostics']['legacy_vision_started'] is False


@pytest.mark.parametrize('invalid', [None, {}, [], {'recognition_status': 'unknown'}])
def test_invalid_new_chain_return_does_not_open_a_legacy_budget(application, monkeypatch, invalid):
    module, client, _ = application
    import ocr_nextgen
    monkeypatch.setattr(module, 'recognize_image', lambda raw: local_result())
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', lambda *args, **kwargs: invalid)
    response = post_image(client)
    assert response.status_code == 503
    assert response.get_json()['recognition_status'] == 'failed'
