"""Bind a real worker response to source bytes without reading credentials."""
import importlib
import shutil

import pytest

from runtime_source_identity import REQUIRED, compute_runtime_source, configured_recognition_budget


def fixture_tree(root):
    for relative in REQUIRED:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('source '+relative, encoding='utf-8')
    return root


def test_identity_independent_of_location_and_metadata(tmp_path):
    first = fixture_tree(tmp_path/'first')
    second = tmp_path/'second'
    shutil.copytree(first, second)
    assert compute_runtime_source(first) == compute_runtime_source(second)
    assert compute_runtime_source(first)[0]['status'] == 'ok'


@pytest.mark.parametrize('relative', ('app.py', 'knowledge_graph.json', 'static/script.js',
                                     'templates/index.html', 'requirements-agents.txt', 'new_worker.py'))
def test_changed_or_added_runtime_source_changes_identity(tmp_path, relative):
    root = fixture_tree(tmp_path/'root')
    before = compute_runtime_source(root)[0]['manifest_sha256']
    (root/relative).write_text('changed', encoding='utf-8')
    assert compute_runtime_source(root)[0]['manifest_sha256'] != before


def test_generated_assets_credentials_and_cache_are_not_in_scope(tmp_path):
    root = fixture_tree(tmp_path/'root')
    before = compute_runtime_source(root)
    for relative in ('static/icons/generated.svg', 'static/icons/icon.png',
                     '.env', 'uploads/private.png', '__pycache__/app.pyc'):
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('not-source', encoding='utf-8')
    assert compute_runtime_source(root) == before


def test_missing_file_and_symlink_fail_closed(tmp_path):
    root = fixture_tree(tmp_path/'root')
    target = root/'knowledge_graph.json'
    content = target.read_bytes()
    target.unlink()
    public, manifest = compute_runtime_source(root)
    assert public['status'] == 'unavailable'
    assert public['manifest_sha256'] is None
    assert public['file_count'] == 0
    assert manifest is None
    elsewhere = tmp_path/'outside.json'
    elsewhere.write_bytes(content)
    target.symlink_to(elsewhere)
    assert compute_runtime_source(root)[0]['status'] == 'unavailable'


def test_budget_uses_effective_bounded_configuration(monkeypatch):
    monkeypatch.setenv('DMATE_GRAPH_PIPELINE', 'evidence-two-pass')
    monkeypatch.setenv('DMATE_AGENT_SECONDS', '180')
    monkeypatch.setenv('DMATE_AGENT_MAX_CALLS', '12')
    monkeypatch.setenv('DMATE_AGENT_CALL_SECONDS', '50')
    actual = configured_recognition_budget()
    assert actual == {'seconds': 180, 'total_remote_calls': 12, 'per_call_seconds': 50,
                      'remote_concurrency': 2, 'network_recoveries': 2, 'json_recoveries': 1,
                      'recoveries_share_total_budget': True}


def test_health_and_actual_ocr_error_share_startup_snapshot(monkeypatch):
    monkeypatch.setenv('DMATE_GRAPH_NEXTGEN', '1')
    app_module = importlib.import_module('app')
    monkeypatch.setattr(app_module, '_check_rate_limit', lambda *args, **kwargs: True)
    client = app_module.app.test_client()
    identity = app_module._RUNTIME_SOURCE
    assert identity['status'] == 'ok'
    for route in ('/health', '/ready'):
        response = client.get(route)
        assert response.get_json()['runtime_source'] == identity
        assert response.headers['X-DMate-Runtime-Sha256'] == identity['manifest_sha256']
        assert response.get_json()['recognition_budget'] == configured_recognition_budget()
    # A request without an image is rejected before any OCR or model call.
    rejected = client.post('/ocr')
    assert rejected.status_code == 400
    assert rejected.headers['X-DMate-Runtime-Sha256'] == identity['manifest_sha256']
    assert 'app.py' not in client.get('/health').get_data(as_text=True)
