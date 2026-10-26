#!/usr/bin/env python3
"""Prepare the three official OCR model packages during image construction.

Download-only API verified against PaddleX release/3.7:
https://github.com/PaddlePaddle/PaddleX/blob/release/3.7/paddlex/inference/utils/official_models.py
No PaddleOCR, LayoutDetection, pipeline, or predictor is instantiated here.
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
import signal
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODEL_NAMES = ('PP-DocLayoutV3', 'PP-OCRv6_small_det', 'PP-OCRv6_small_rec')
REQUIRED_FILES = ('inference.json', 'inference.pdiparams', 'inference.yml')
MANIFEST_NAME = 'dmate-model-manifest.json'
DEFAULT_CACHE_DIR = '/opt/dmate-model-cache'
SCHEMA_VERSION = 1


class CachePreparationError(RuntimeError):
    pass


class _DownloadDeadline(BaseException):
    # Official host fallback catches Exception. A wall deadline must leave the
    # whole API invocation, not be swallowed and followed by another host.
    pass


@contextmanager
def _download_deadline(seconds):
    if not hasattr(signal, 'setitimer'):
        raise CachePreparationError('download_deadline_requires_posix')
    def expired(signum, frame):
        raise _DownloadDeadline()
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
    # This skips host connectivity probes, not certificate verification or
    # downloads. Actual official download failures still fail this build.
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
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


def verify_manifest(cache_home, records=None):
    path = Path(cache_home)/MANIFEST_NAME
    try:
        if path.stat().st_size > 64*1024:
            raise CachePreparationError('model_manifest_capacity')
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CachePreparationError('missing_or_invalid_model_manifest') from exc
    records = records if records is not None else [inspect_model(cache_home, name) for name in MODEL_NAMES]
    if (not isinstance(manifest, dict) or manifest.get('schema_version') != SCHEMA_VERSION
            or manifest.get('models') != records or manifest.get('inference_initialized') is not False):
        raise CachePreparationError('model_manifest_identity_or_hash_mismatch')
    return manifest


def _official_manager():
    # Import after the supported cache override is set. This object resolves
    # package downloads; it does not create a model or load parameter tensors.
    from paddlex.inference.utils.official_models import official_models
    return official_models


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
        verify_manifest(cache_home)
    manager = None
    records, downloaded, reused = [], [], []
    for name in MODEL_NAMES:
        expected = cache_home/'official_models'/name
        if expected.exists():
            records.append(inspect_model(cache_home, name))
            reused.append(name)
            continue
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
            raise CachePreparationError(f'model_download_failed:{name}:{type(exc).__name__}') from exc
        if resolved.resolve() != expected.resolve():
            raise CachePreparationError(f'download_resolved_wrong_cache:{name}')
        records.append(inspect_model(cache_home, name))
        downloaded.append(name)
    versions = {}
    for name in ('paddlex', 'paddleocr', 'paddlepaddle'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    manifest = {'schema_version': SCHEMA_VERSION, 'models': records,
                'package_versions': versions, 'inference_initialized': False,
                'download_api': 'paddlex.inference.utils.official_models.official_models.get_model_path',
                'model_format': 'paddle',
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
            'reused_models': reused, 'manifest': manifest}


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
