"""Build-cache integrity and download-only contracts; no network or inference."""
import builtins
import copy
import json
import os
from pathlib import Path
import time

import pytest
import requests

from scripts import prepare_ocr_model_cache as module


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, 'send', lambda *a, **k: pytest.fail('network forbidden'))
    # Track these keys even when code intentionally configures its own build
    # process; pytest restores the parent environment after each case.
    for key in ('DMATE_MODEL_CACHE_DIR', 'PADDLE_PDX_CACHE_HOME', 'PADDLE_PDX_MODEL_SOURCE',
                'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'):
        if key in os.environ: monkeypatch.setenv(key, os.environ[key])
        else: monkeypatch.delenv(key, raising=False)


def make_package(cache_home, name):
    folder = Path(cache_home)/'official_models'/name
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'inference.json').write_text(json.dumps({'program': {'synthetic': True}}))
    (folder/'inference.pdiparams').write_bytes(b'synthetic-test-parameters-not-a-real-model')
    (folder/'inference.yml').write_text('Global:\n  model_name: '+name+'\n')
    return folder


class OfficialApiDouble:
    def __init__(self, cache_home):
        self.cache_home = Path(cache_home)
        self.calls = []

    def __contains__(self, name):
        return name in module.MODEL_NAMES

    def get_model_path(self, name, *, model_formats):
        assert model_formats == ('paddle',)
        self.calls.append(name)
        return make_package(self.cache_home, name)


def test_cold_cache_uses_exact_three_official_names_in_correct_runtime_directory(tmp_path):
    home_before = os.environ.get('HOME')
    manager = OfficialApiDouble(tmp_path/'paddlex')
    factory_calls = []
    def factory():
        factory_calls.append(True)
        assert os.environ['PADDLE_PDX_CACHE_HOME'] == str(tmp_path/'paddlex')
        assert os.environ['DMATE_MODEL_CACHE_DIR'] == str(tmp_path)
        return manager
    result = module.prepare_model_cache(tmp_path, manager_factory=factory)
    assert factory_calls == [True]
    assert manager.calls == ['PP-DocLayoutV3', 'PP-OCRv6_small_det', 'PP-OCRv6_small_rec']
    assert result['downloaded_models'] == list(module.MODEL_NAMES) and not result['reused_models']
    assert result['manifest']['inference_initialized'] is False
    assert os.environ.get('HOME') == home_before
    checked = module.verify_manifest(tmp_path/'paddlex')
    assert checked == result['manifest']
    assert all(len(model['files']) == 3 for model in checked['models'])


def test_complete_cached_models_do_not_import_manager_or_redownload(tmp_path):
    for name in module.MODEL_NAMES: make_package(tmp_path/'paddlex', name)
    def forbidden(): raise AssertionError('warm cache must not contact model manager')
    first = module.prepare_model_cache(tmp_path, manager_factory=forbidden)
    second = module.prepare_model_cache(tmp_path, verify_only=True, manager_factory=forbidden)
    assert first['downloaded_models'] == second['downloaded_models'] == []
    assert second['status'] == 'verified'
    assert first['manifest'] == second['manifest']


def test_existing_other_cache_override_cannot_steal_docker_weights(monkeypatch, tmp_path):
    monkeypatch.setenv('PADDLE_PDX_CACHE_HOME', str(tmp_path/'wrong'))
    home, _ = module.configure_build_cache(tmp_path/'desired')
    assert home == tmp_path/'desired'/'paddlex'
    assert os.environ['PADDLE_PDX_CACHE_HOME'] == str(home)
    assert not (tmp_path/'wrong').exists()


def test_cache_fallback_to_temporary_storage_fails_build(monkeypatch, tmp_path):
    def fallback(env):
        env['PADDLE_PDX_CACHE_HOME'] = str(tmp_path/'unrelated')
        return {'source': 'temporary', 'fallback': True, 'status': 'ready'}
    monkeypatch.setattr('ocr_runtime.configure_model_cache', fallback)
    with pytest.raises(module.CachePreparationError, match='fell_back'):
        module.configure_build_cache(tmp_path/'wanted')


@pytest.mark.parametrize('filename', module.REQUIRED_FILES)
@pytest.mark.parametrize('damage', ['missing', 'empty'])
def test_partial_existing_package_fails_without_silent_download_or_manifest(tmp_path, filename, damage):
    folder = make_package(tmp_path/'paddlex', module.MODEL_NAMES[0])
    if damage == 'missing': (folder/filename).unlink()
    else: (folder/filename).write_bytes(b'')
    def forbidden(): raise AssertionError('partial cache must not be accepted as complete')
    with pytest.raises(module.CachePreparationError, match='incomplete_model'):
        module.prepare_model_cache(tmp_path, manager_factory=forbidden)
    assert not (tmp_path/'paddlex'/module.MANIFEST_NAME).exists()


def test_model_configuration_name_is_checked_not_just_directory(tmp_path):
    folder = make_package(tmp_path/'paddlex', module.MODEL_NAMES[0])
    (folder/'inference.yml').write_text('Global:\n  model_name: PP-OCRv6_small_rec\n')
    with pytest.raises(module.CachePreparationError, match='model_identity_mismatch'):
        module.inspect_model(tmp_path/'paddlex', module.MODEL_NAMES[0])


def test_invalid_inference_program_is_not_completed_cache(tmp_path):
    folder = make_package(tmp_path/'paddlex', module.MODEL_NAMES[0])
    (folder/'inference.json').write_text('not JSON')
    with pytest.raises(module.CachePreparationError, match='invalid_model_configuration'):
        module.inspect_model(tmp_path/'paddlex', module.MODEL_NAMES[0])


def test_existing_identity_manifest_detects_weight_changes_without_rebaselining(tmp_path):
    manager = OfficialApiDouble(tmp_path/'paddlex')
    original = module.prepare_model_cache(tmp_path, manager_factory=lambda: manager)
    manifest_file = tmp_path/'paddlex'/module.MANIFEST_NAME
    manifest_bytes = manifest_file.read_bytes()
    (tmp_path/'paddlex'/'official_models'/module.MODEL_NAMES[1]/'inference.pdiparams').write_bytes(b'changed')
    with pytest.raises(module.CachePreparationError, match='manifest_identity_or_hash_mismatch'):
        module.prepare_model_cache(tmp_path, manager_factory=lambda: manager)
    assert manifest_file.read_bytes() == manifest_bytes
    assert len(manager.calls) == 3
    assert original['manifest']['inference_initialized'] is False


def test_unknown_model_and_wrong_api_destination_are_rejected(tmp_path):
    with pytest.raises(module.CachePreparationError, match='unexpected_model_name'):
        module.inspect_model(tmp_path/'paddlex', 'PP-FormulaNet_plus-S')
    class Wrong(OfficialApiDouble):
        def get_model_path(self, name, **kwargs):
            return make_package(tmp_path/'wrong', name)
    with pytest.raises(module.CachePreparationError, match='download_resolved_wrong_cache'):
        module.prepare_model_cache(tmp_path, manager_factory=lambda: Wrong(tmp_path/'paddlex'))


def test_no_inference_model_or_pipeline_imports_are_needed(monkeypatch, tmp_path):
    original_import = builtins.__import__
    def forbid_inference(name, *args, **kwargs):
        if name in ('ocr', 'paddleocr', 'paddle') or name.startswith(('paddleocr.', 'paddle.')):
            raise AssertionError('inference import not permitted by build adapter')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', forbid_inference)
    result = module.prepare_model_cache(tmp_path, manager_factory=lambda: OfficialApiDouble(tmp_path/'paddlex'))
    assert result['status'] == 'prepared'


def test_wall_deadline_escapes_official_exception_fallback(tmp_path):
    fallbacks = []
    class Slow(OfficialApiDouble):
        def get_model_path(self, name, **kwargs):
            try: time.sleep(.2)
            except Exception: fallbacks.append(True)
            return make_package(self.cache_home, name)
    with pytest.raises(module.CachePreparationError, match='model_download_deadline'):
        module.prepare_model_cache(tmp_path, timeout_seconds=.01,
                                   manager_factory=lambda: Slow(tmp_path/'paddlex'))
    assert not fallbacks
    assert not (tmp_path/'paddlex'/module.MANIFEST_NAME).exists()


def test_cli_failure_returns_nonzero_without_success_json(monkeypatch, tmp_path, capsys):
    def failed(*a, **k): raise module.CachePreparationError('model_download_failed:fixture')
    monkeypatch.setattr(module, 'prepare_model_cache', failed)
    assert module.main(['--cache-dir', str(tmp_path)]) == 1
    streams = capsys.readouterr()
    assert not streams.out and json.loads(streams.err)['status'] == 'failed'


def test_docker_cache_layer_is_before_full_sources_and_cannot_ignore_failure():
    docker = (Path(__file__).resolve().parents[1]/'Dockerfile').read_text()
    assert 'DMATE_MODEL_CACHE_DIR=/opt/dmate-model-cache' in docker
    preparation = docker.index('RUN python scripts/prepare_ocr_model_cache.py')
    assert 'COPY ocr_runtime.py image_upload_limits.py ./' in docker[:preparation]
    assert docker.index('COPY scripts/prepare_ocr_model_cache.py') < preparation < docker.index('COPY . .')
    assert 'python scripts/prepare_ocr_model_cache.py --verify-only' in docker
    assert '|| true' not in docker
