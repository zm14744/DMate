"""CPU text-engine settings shared by isolated OCR workers and cache tools.

This module imports no inference library. Models are prepared at build/setup
time; a request never converts weights or silently changes execution engines.
"""
import os
from pathlib import Path

TEXT_DET_MODEL = 'PP-OCRv6_small_det'
TEXT_REC_MODEL = 'PP-OCRv6_small_rec'
TEXT_MODELS = (TEXT_DET_MODEL, TEXT_REC_MODEL)
DEFAULT_TEXT_ENGINE = 'onnxruntime'
TEXT_ENGINE_ENV = 'DMATE_TEXT_OCR_ENGINE'


def selected_text_engine(env=None):
    env = os.environ if env is None else env
    engine = env.get(TEXT_ENGINE_ENV, DEFAULT_TEXT_ENGINE)
    if engine not in ('onnxruntime', 'paddle_static'):
        raise ValueError('unsupported_text_ocr_engine')
    return engine


def text_model_options(env=None):
    """Return explicit local model paths and the measured two-thread settings."""
    from ocr_runtime import ModelCacheError, configure_model_cache
    env = os.environ if env is None else env
    engine = selected_text_engine(env)
    configure_model_cache(env)
    cache_home = Path(env['PADDLE_PDX_CACHE_HOME'])
    if engine == 'onnxruntime':
        model_root = cache_home / 'onnx_models'
        required = ('inference.onnx', 'inference.yml')
    else:
        model_root = cache_home / 'official_models'
        required = ('inference.json', 'inference.pdiparams', 'inference.yml')
    for name in TEXT_MODELS:
        for filename in required:
            path = model_root / name / filename
            try:
                if not path.is_file() or path.stat().st_size <= 0:
                    raise ModelCacheError('text_model_cache_unprepared')
            except OSError as exc:
                raise ModelCacheError('text_model_cache_unreadable') from exc
    options = {
        'text_detection_model_name': TEXT_DET_MODEL,
        'text_detection_model_dir': str(model_root / TEXT_DET_MODEL),
        'text_recognition_model_name': TEXT_REC_MODEL,
        'text_recognition_model_dir': str(model_root / TEXT_REC_MODEL),
        'use_doc_orientation_classify': False,
        'use_doc_unwarping': False,
        'use_textline_orientation': False,
        'text_recognition_batch_size': 1,
        'text_det_limit_side_len': 1600,
        'text_det_limit_type': 'max',
        'device': 'cpu',
        'enable_mkldnn': False,
        'cpu_threads': 2,
        'engine': engine,
    }
    if engine == 'onnxruntime':
        options['engine_config'] = {
            'providers': ['CPUExecutionProvider'],
            'intra_op_num_threads': 2,
            'inter_op_num_threads': 1,
            'execution_mode': 'sequential',
        }
    return options
