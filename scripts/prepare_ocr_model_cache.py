#!/usr/bin/env python3
"""Prepare official models and same-weight Small ONNX exports at build time.

Download-only API verified against PaddleX release/3.7:
https://github.com/PaddlePaddle/PaddleX/blob/release/3.7/paddlex/inference/utils/official_models.py
No PaddleOCR, LayoutDetection, pipeline, or predictor is instantiated here.
Text exports use pinned Paddle2ONNX with optional graph-folding installers off.
The runtime and this script share ocr_runtime.configure_model_cache.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODEL_NAMES = ('PP-DocLayoutV3', 'PP-OCRv6_small_det', 'PP-OCRv6_small_rec')
TEXT_MODEL_NAMES = MODEL_NAMES[1:]
REQUIRED_FILES = ('inference.json', 'inference.pdiparams', 'inference.yml')
ONNX_REQUIRED_FILES = ('inference.onnx', 'inference.yml', 'dmate-onnx-source.json')
ONNX_OPSET = 17
MANIFEST_NAME = 'dmate-model-manifest.json'
DEFAULT_CACHE_DIR = '/opt/dmate-model-cache'
SCHEMA_VERSION = 2
MODELSCOPE_API = 'https://modelscope.cn/api/v1/models/PaddlePaddle'
DOWNLOAD_ATTEMPTS = 3


class CachePreparationError(RuntimeError):
    pass


class _DownloadDeadline(Exception):
    """A source deadline that PaddleX can catch to try its next model host."""
    pass


def _caused_by_download_deadline(exc):
    current = exc
    visited = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, _DownloadDeadline):
            return True
        visited.add(id(current))
        current = getattr(current, '__cause__', None) or getattr(current, '__context__', None)
    return False


@contextmanager
def _download_deadline(seconds):
    if not hasattr(signal, 'setitimer'):
        raise CachePreparationError('download_deadline_requires_posix')
    def expired(signum, frame):
        # PaddleX catches this exception and advances to another available
        # hoster. Re-arm the deadline so the fallback host also has a limit.
        signal.setitimer(signal.ITIMER_REAL, seconds, 0)
        raise _DownloadDeadline(f'model source exceeded {seconds:g}s')
    previous = signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def configure_build_cache(cache_dir):
    """Set supported cache variables before any PaddleX import; never HOME."""
    from ocr_runtime import configure_model_cache
    root = Path(cache_dir).expanduser().absolute()
    expected = root/'paddlex'
    env = dict(os.environ)
    env['DMATE_MODEL_CACHE_DIR'] = str(root)
    env['PADDLE_PDX_CACHE_HOME'] = str(expected)
    selected = configure_model_cache(env)
    if Path(env['PADDLE_PDX_CACHE_HOME']).resolve() != expected.resolve():
        raise CachePreparationError('configured_cache_fell_back_to_other_directory')
    os.environ['DMATE_MODEL_CACHE_DIR'] = str(root)
    os.environ['PADDLE_PDX_CACHE_HOME'] = str(expected)
    os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'BOS')
    # Let PaddleX probe its candidate model hosts and omit unreachable ones.
    # Disabling this check while preferring BOS can make one unreachable or slow
    # host consume the whole deadline before PaddleX gets to its fallbacks.
    # PaddleX reads this setting as a raw string, so remove it rather than set
    # the text "False" (which would still be truthy).
    os.environ.pop('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', None)
    return expected, selected


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_model(cache_home, name):
    """Verify package completeness and declared identity without inference."""
    import yaml
    if name not in MODEL_NAMES:
        raise CachePreparationError('unexpected_model_name')
    directory = Path(cache_home)/'official_models'/name
    files = {}
    for filename in REQUIRED_FILES:
        path = directory/filename
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                raise CachePreparationError(f'incomplete_model:{name}:{filename}')
            if path.stat().st_size > (1024**3 if filename.endswith('pdiparams') else 64*1024**2):
                raise CachePreparationError(f'model_file_capacity:{name}:{filename}')
            files[filename] = {'size_bytes': path.stat().st_size, 'sha256': _sha256(path)}
        except OSError as exc:
            raise CachePreparationError(f'unreadable_model:{name}:{filename}') from exc
    try:
        inference = json.loads((directory/'inference.json').read_text(encoding='utf-8'))
        config = yaml.safe_load((directory/'inference.yml').read_text(encoding='utf-8'))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise CachePreparationError(f'invalid_model_configuration:{name}') from exc
    if not isinstance(inference, dict) or not inference:
        raise CachePreparationError(f'invalid_inference_program:{name}')
    global_config = config.get('Global') if isinstance(config, dict) else None
    if not isinstance(global_config, dict) or global_config.get('model_name') != name:
        raise CachePreparationError(f'model_identity_mismatch:{name}')
    return {'name': name, 'declared_model_name': global_config['model_name'], 'files': files}


def inspect_onnx_model(cache_home, name, source_record=None, *, directory=None):
    """Check the exported graph, original dictionary/config, and source hashes."""
    import onnx
    if name not in TEXT_MODEL_NAMES:
        raise CachePreparationError('unexpected_onnx_model_name')
    source_record = source_record or inspect_model(cache_home, name)
    directory = Path(directory) if directory is not None else Path(cache_home)/'onnx_models'/name
    files = {}
    for filename in ONNX_REQUIRED_FILES:
        path = directory/filename
        try:
            if not path.is_file() or not 0 < path.stat().st_size <= 64*1024**2:
                raise CachePreparationError(f'incomplete_or_oversized_onnx_model:{name}:{filename}')
            files[filename] = {'size_bytes': path.stat().st_size, 'sha256': _sha256(path)}
        except OSError as exc:
            raise CachePreparationError(f'unreadable_onnx_model:{name}:{filename}') from exc
    try:
        provenance = json.loads((directory/'dmate-onnx-source.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CachePreparationError(f'invalid_onnx_source_record:{name}') from exc
    if (not isinstance(provenance, dict) or provenance.get('schema_version') != 1
            or provenance.get('name') != name or provenance.get('opset_version') != ONNX_OPSET
            or provenance.get('source_files') != source_record['files']
            or provenance.get('onnx_sha256') != files['inference.onnx']['sha256']
            or files['inference.yml'] != source_record['files']['inference.yml']):
        raise CachePreparationError(f'onnx_source_identity_or_hash_mismatch:{name}')
    try:
        graph = onnx.load(str(directory/'inference.onnx'), load_external_data=False)
        if any(tensor.data_location == onnx.TensorProto.EXTERNAL for tensor in graph.graph.initializer):
            raise ValueError('external_model_data_not_supported')
        if [(op.domain, op.version) for op in graph.opset_import] != [('', ONNX_OPSET)]:
            raise ValueError('unexpected_onnx_opset')
        onnx.checker.check_model(graph)
    except Exception as exc:
        raise CachePreparationError(f'invalid_onnx_graph:{name}:{type(exc).__name__}') from exc
    return {'name': name, 'declared_model_name': source_record['declared_model_name'],
            'source_files': source_record['files'], 'files': files, 'opset_version': ONNX_OPSET}


def verify_manifest(cache_home, records=None, *, allow_legacy=False):
    path = Path(cache_home)/MANIFEST_NAME
    try:
        if path.stat().st_size > 64*1024:
            raise CachePreparationError('model_manifest_capacity')
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CachePreparationError('missing_or_invalid_model_manifest') from exc
    records = records if records is not None else [inspect_model(cache_home, name) for name in MODEL_NAMES]
    if (not isinstance(manifest, dict) or manifest.get('schema_version') not in (1, SCHEMA_VERSION)
            or manifest.get('models') != records or manifest.get('inference_initialized') is not False):
        raise CachePreparationError('model_manifest_identity_or_hash_mismatch')
    if manifest['schema_version'] == 1:
        if allow_legacy:
            return manifest
        raise CachePreparationError('model_manifest_upgrade_required_run_prepare')
    exported = [inspect_onnx_model(cache_home, record['name'], record)
                for record in records if record['name'] in TEXT_MODEL_NAMES]
    if manifest.get('onnx_models') != exported:
        raise CachePreparationError('onnx_manifest_identity_or_hash_mismatch')
    return manifest


def _export_onnx_model(cache_home, record, timeout_seconds):
    """Convert in a bounded child, validate a staging directory, then publish."""
    name = record['name']
    source = Path(cache_home)/'official_models'/name
    parent = Path(cache_home)/'onnx_models'
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent/name
    if destination.exists():
        return inspect_onnx_model(cache_home, name, record), False
    with tempfile.TemporaryDirectory(prefix=f'.{name}-', dir=parent) as temporary:
        staging = Path(temporary)/name
        staging.mkdir()
        command = [sys.executable, '-m', 'paddle2onnx.command',
                   '--model_dir', str(source), '--model_filename', 'inference.json',
                   '--params_filename', 'inference.pdiparams',
                   '--save_file', str(staging/'inference.onnx'),
                   '--opset_version', str(ONNX_OPSET), '--enable_auto_update_opset', 'False',
                   '--enable_onnx_checker', 'True', '--optimize_tool', 'None']
        try:
            # Keep converter output out of JSON stdout; no optional optimiser
            # may auto-install or upgrade NumPy inside a production build.
            subprocess.run(command, check=True, stdout=sys.stderr, stderr=sys.stderr,
                           timeout=timeout_seconds)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CachePreparationError(f'onnx_export_failed:{name}:{type(exc).__name__}') from exc
        shutil.copyfile(source/'inference.yml', staging/'inference.yml')
        provenance = {'schema_version': 1, 'name': name, 'source_files': record['files'],
                      'opset_version': ONNX_OPSET, 'onnx_sha256': _sha256(staging/'inference.onnx'),
                      'exporter': 'paddle2onnx', 'exporter_version': metadata.version('paddle2onnx'),
                      'optimize_tool': 'None', 'quantized': False}
        (staging/'dmate-onnx-source.json').write_text(
            json.dumps(provenance, indent=2, sort_keys=True), encoding='utf-8')
        exported = inspect_onnx_model(cache_home, name, record, directory=staging)
        os.replace(staging, destination)
        return exported, True


def _official_manager():
    # Import after the supported cache override is set. This object resolves
    # package downloads; it does not create a model or load parameter tensors.
    from paddlex.inference.utils.official_models import official_models
    return official_models


def _modelscope_files(http, name, timeout_seconds):
    """Read the official publisher's immutable file revisions and SHA256s."""
    import requests
    if name not in MODEL_NAMES:
        raise CachePreparationError('unexpected_model_name')
    last_error = None
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            with _download_deadline(min(timeout_seconds, 60)):
                with http.get(f'{MODELSCOPE_API}/{name}/repo/files',
                              params={'Revision': 'master', 'Recursive': 'true'},
                              stream=True, timeout=(8, 30)) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_content(64 * 1024):
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise CachePreparationError('modelscope_metadata_too_large')
                payload = json.loads(body)
            rows = payload.get('Data', {}).get('Files', [])
            if payload.get('Code') != 200 or not isinstance(rows, list):
                raise ValueError('invalid_modelscope_metadata')
            files = {}
            for row in rows:
                if not isinstance(row, dict) or row.get('Path') not in REQUIRED_FILES:
                    continue
                filename = row['Path']
                maximum = 1024**3 if filename.endswith('pdiparams') else 64 * 1024**2
                if (filename in files or type(row.get('Size')) is not int
                        or not 0 < row['Size'] <= maximum
                        or not re.fullmatch(r'[a-fA-F0-9]{64}', str(row.get('Sha256', '')))
                        or not re.fullmatch(r'[a-fA-F0-9]{40}', str(row.get('Revision', '')))):
                    raise ValueError('invalid_modelscope_file_record')
                files[filename] = {'size': row['Size'], 'sha256': row['Sha256'].lower(),
                                   'revision': row['Revision']}
            if set(files) != set(REQUIRED_FILES):
                raise ValueError('missing_modelscope_required_files')
            return files
        except (requests.RequestException, _DownloadDeadline, ValueError,
                AttributeError, CachePreparationError) as exc:
            last_error = exc
            if isinstance(exc, requests.HTTPError) and exc.response is not None \
                    and exc.response.status_code in (401, 403, 404):
                break
    raise CachePreparationError(f'modelscope_metadata_failed:{name}') from last_error


def _download_modelscope_file(http, name, filename, record, destination, timeout_seconds):
    """Resume only the same immutable file and verify its exact length/hash."""
    import requests
    last_error = None
    expected_size = record['size']
    for attempt in range(DOWNLOAD_ATTEMPTS):
        offset = destination.stat().st_size if destination.exists() else 0
        if offset == expected_size:
            if _sha256(destination) == record['sha256']:
                return
            destination.unlink()
            offset = 0
        elif offset > expected_size:
            destination.unlink()
            offset = 0
        try:
            with _download_deadline(timeout_seconds):
                with http.get(f'{MODELSCOPE_API}/{name}/repo',
                              params={'Revision': record['revision'], 'FilePath': filename},
                              headers={'Range': f'bytes={offset}-', 'Accept-Encoding': 'identity'},
                              stream=True, timeout=(8, 30)) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        span = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',
                                            response.headers.get('Content-Range', ''))
                        if (span is None or int(span[1]) != offset
                                or not offset <= int(span[2]) < expected_size
                                or int(span[3]) != expected_size):
                            raise CachePreparationError('modelscope_invalid_content_range')
                    elif response.status_code == 200:
                        # A server may ignore Range; replace, never append its
                        # complete response to the bytes from the first attempt.
                        offset = 0
                    else:
                        raise CachePreparationError('modelscope_unexpected_file_status')
                    received = offset
                    with destination.open('ab' if offset else 'wb') as target:
                        for chunk in response.iter_content(64 * 1024):
                            received += len(chunk)
                            if received > expected_size:
                                raise CachePreparationError('modelscope_file_capacity')
                            target.write(chunk)
            if destination.stat().st_size != expected_size:
                raise CachePreparationError('modelscope_incomplete_file')
            if _sha256(destination) != record['sha256']:
                destination.unlink()
                raise CachePreparationError('modelscope_file_hash_mismatch')
            return
        except (requests.RequestException, _DownloadDeadline, CachePreparationError) as exc:
            last_error = exc
            print(f'Official ModelScope {name}/{filename}: attempt {attempt + 1}/'
                  f'{DOWNLOAD_ATTEMPTS} failed ({type(exc).__name__}); '
                  'retaining verified-source partial bytes for retry.', file=sys.stderr)
            if isinstance(exc, requests.HTTPError) and exc.response is not None \
                    and exc.response.status_code in (401, 403, 404):
                break
    raise CachePreparationError(f'modelscope_file_download_failed:{name}:{filename}') from last_error


def _download_modelscope_model(cache_home, name, timeout_seconds):
    """Fetch only the three Paddle files, validate in staging, publish once."""
    import requests
    parent = Path(cache_home) / 'official_models'
    parent.mkdir(parents=True, exist_ok=True)
    with requests.Session() as http:
        records = _modelscope_files(http, name, timeout_seconds)
        with tempfile.TemporaryDirectory(prefix=f'.{name}-download-', dir=parent) as temporary:
            staging_home = Path(temporary)
            staging = staging_home / 'official_models' / name
            staging.mkdir(parents=True)
            for filename in REQUIRED_FILES:
                _download_modelscope_file(http, name, filename, records[filename],
                                          staging / filename, timeout_seconds)
            inspect_model(staging_home, name)
            destination = parent / name
            os.replace(staging, destination)
    return destination


def prepare_model_cache(cache_dir=DEFAULT_CACHE_DIR, *, verify_only=False,
                        timeout_seconds=300., manager_factory=None):
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 600:
        raise CachePreparationError('invalid_download_deadline')
    cache_home, selection = configure_build_cache(cache_dir)
    manifest_path = cache_home/MANIFEST_NAME
    if verify_only:
        manifest = verify_manifest(cache_home)
        return {'status': 'verified', 'cache_selection': selection,
                'downloaded_models': [], 'reused_models': list(MODEL_NAMES), 'manifest': manifest}
    # A prior manifest is a content checkpoint: never silently rebaseline a
    # modified/partial package and call the same cached model intact.
    if manifest_path.exists():
        verify_manifest(cache_home, allow_legacy=True)
    manager = None
    records, downloaded, reused = [], [], []
    for name in MODEL_NAMES:
        expected = cache_home/'official_models'/name
        if expected.exists():
            records.append(inspect_model(cache_home, name))
            reused.append(name)
            continue
        if manager_factory is None:
            try:
                # PaddleX's one-second root-domain health check can omit a
                # usable host. Query actual official files and keep progress
                # across bounded retries before using its general fallback.
                _download_modelscope_model(cache_home, name, timeout_seconds)
                records.append(inspect_model(cache_home, name))
                downloaded.append(name)
                continue
            except CachePreparationError as exc:
                print(f'Official ModelScope download unavailable for {name} '
                      f'({exc}); trying PaddleX official sources.', file=sys.stderr)
        try:
            with _download_deadline(timeout_seconds):
                if manager is None:
                    manager = (manager_factory or _official_manager)()
                if name not in manager:
                    raise CachePreparationError(f'installed_paddlex_does_not_support:{name}')
                resolved = Path(manager.get_model_path(name, model_formats=('paddle',)))
        except _DownloadDeadline as exc:
            raise CachePreparationError(f'model_download_deadline:{name}') from exc
        except CachePreparationError:
            raise
        except Exception as exc:
            if _caused_by_download_deadline(exc):
                raise CachePreparationError(f'model_download_deadline_all_sources:{name}') from exc
            raise CachePreparationError(f'model_download_failed:{name}:{type(exc).__name__}') from exc
        if resolved.resolve() != expected.resolve():
            raise CachePreparationError(f'download_resolved_wrong_cache:{name}')
        records.append(inspect_model(cache_home, name))
        downloaded.append(name)
    exports, converted, reused_exports = [], [], []
    for record in records:
        if record['name'] not in TEXT_MODEL_NAMES:
            continue
        exported, created = _export_onnx_model(cache_home, record, timeout_seconds)
        exports.append(exported)
        (converted if created else reused_exports).append(record['name'])
    versions = {}
    for name in ('paddlex', 'paddleocr', 'paddlepaddle', 'paddle2onnx', 'onnx', 'onnxruntime'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    manifest = {'schema_version': SCHEMA_VERSION, 'models': records,
                'onnx_models': exports,
                'package_versions': versions, 'inference_initialized': False,
                'download_api': 'official_modelscope_required_files_then_paddlex_official_models',
                'model_format': 'paddle_and_onnx', 'text_engine': 'onnxruntime',
                'integrity_scope': 'local_file_hashes_and_declared_model_identity_not_publisher_signature'}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=cache_home,
                                         prefix='.dmate-model-manifest-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, manifest_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    verify_manifest(cache_home, records)
    return {'status': 'prepared', 'cache_selection': selection, 'downloaded_models': downloaded,
            'reused_models': reused, 'converted_onnx_models': converted,
            'reused_onnx_models': reused_exports, 'manifest': manifest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', default=os.environ.get('DMATE_MODEL_CACHE_DIR', DEFAULT_CACHE_DIR))
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--download-timeout', type=float, default=300.)
    args = parser.parse_args(argv)
    try:
        result = prepare_model_cache(args.cache_dir, verify_only=args.verify_only,
                                     timeout_seconds=args.download_timeout)
    except (CachePreparationError, OSError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
