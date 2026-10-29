"""Short, in-memory voice dictation using the requested Qwen Audio ASR model.

DashScope's native synchronous ASR protocol carries a precompiled vocabulary
under parameters.vocabulary_id; the older Qwen3 chat protocol does not.
Audio is never written to disk or retained with chat history by this adapter.
"""
from __future__ import annotations

import base64
import io
import os
import re
import threading
import time
import wave
from urllib.parse import urlsplit, urlunsplit

import requests

DEFAULT_MODEL = 'qwen-audio-3.1-asr-flash'
DEFAULT_VOCABULARY_ID = 'vocab-dmate-60d8d29883164a5a83fdfbb7f21772a9'
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
SAMPLE_RATE = 16000
_ACTIVE = threading.BoundedSemaphore(2)
_HTTP = threading.local()
_NATIVE_PATH = '/api/v1/services/aigc/multimodal-generation/generation'


class VoiceInputError(ValueError):
    def __init__(self, code, message, *, status=400, provider_code=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.provider_code = provider_code


def inspect_wav(raw):
    """Accept the browser's bounded 16 kHz mono PCM16 format, not its suffix."""
    if not isinstance(raw, bytes) or not raw:
        raise VoiceInputError('empty_audio', '没有录到声音，请重新录音。')
    if len(raw) > MAX_AUDIO_BYTES:
        raise VoiceInputError('audio_too_large', '语音文件不能超过10MB。', status=413)
    if raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
        raise VoiceInputError('unsupported_audio', '语音格式无效，请重新录音。')
    try:
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            count = audio.getnframes()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, SAMPLE_RATE, 'NONE'):
                raise VoiceInputError('unsupported_audio', '请使用16kHz单声道PCM语音。')
            seconds = count / SAMPLE_RATE
            if seconds > MAX_AUDIO_SECONDS:
                raise VoiceInputError('audio_too_long', '单次语音最多60秒，请分段输入。', status=413)
            if seconds < .15:
                raise VoiceInputError('audio_too_short', '录音太短，请重新录音。')
            if len(audio.readframes(count)) != count * 2:
                raise VoiceInputError('invalid_audio', '录音文件不完整，请重新录音。')
    except (wave.Error, EOFError, OSError) as exc:
        raise VoiceInputError('invalid_audio', '录音文件无效，请重新录音。') from exc
    return seconds


def _configuration():
    from ai import API_URL
    configured = os.environ.get('DMATE_ASR_API_URL') or API_URL
    parts = urlsplit(configured)
    if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise VoiceInputError('asr_configuration_error', '语音服务地址配置无效。', status=503)
    endpoint = urlunsplit((parts.scheme, parts.netloc, _NATIVE_PATH, '', ''))
    model = (os.environ.get('DMATE_ASR_MODEL') or DEFAULT_MODEL).strip()
    vocabulary = (os.environ.get('DMATE_ASR_VOCABULARY_ID') or DEFAULT_VOCABULARY_ID).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', model) or not re.fullmatch(r'vocab-[A-Za-z0-9_-]{1,160}', vocabulary):
        raise VoiceInputError('asr_configuration_error', '语音模型或词库配置无效。', status=503)
    key = (os.environ.get('DASHSCOPE_API_KEY') or os.environ.get('DASHSCOPE_VISION_API_KEY') or '').strip()
    if not key:
        raise VoiceInputError('asr_not_configured', '语音服务尚未配置，请稍后再试。', status=503)
    return endpoint, model, vocabulary, key


def _http_session():
    """Reuse TLS connections within one worker thread, never across a fork."""
    session = getattr(_HTTP, 'session', None)
    pid = os.getpid()
    if session is not None and getattr(_HTTP, 'pid', None) != pid:
        session.close()
        session = None
    if session is None:
        session = requests.Session()
        # A thread performs one dictation at a time. Do not retain an unbounded
        # pool or replay a POST after a stale connection/ambiguous response.
        session.mount('https://', requests.adapters.HTTPAdapter(
            pool_connections=1, pool_maxsize=1, max_retries=0, pool_block=True))
        _HTTP.session, _HTTP.pid = session, pid
    return session


def _discard_http_session(session):
    if session is not None:
        _HTTP.session = None
        session.close()


def transcribe_voice(raw, *, post=None):
    """One explicit model call, with the user's vocabulary; no silent fallback."""
    started = time.perf_counter()
    seconds = inspect_wav(raw)
    validated = time.perf_counter()
    endpoint, model, vocabulary, key = _configuration()
    if not _ACTIVE.acquire(blocking=False):
        raise VoiceInputError('asr_busy', '语音服务繁忙，请稍后重试。', status=429)
    session = response = None
    try:
        payload = {'model': model, 'input': {'messages': [{'role': 'user', 'content': [{
            'type': 'input_audio', 'input_audio': {'data': 'data:audio/wav;base64,' + base64.b64encode(raw).decode('ascii')}}]}]},
            'parameters': {'format': 'wav', 'sample_rate': str(SAMPLE_RATE), 'vocabulary_id': vocabulary}}
        if post is None:
            session = _http_session()
            # Only the connection is shared between dictations. Authorization
            # is per request, and provider cookies must not cross user requests.
            session.cookies.clear()
            post = session.post
        prepared = time.perf_counter()
        try:
            response = post(endpoint, headers={
                'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'X-DashScope-SSE': 'disable'},
                json=payload, timeout=(8, 50), allow_redirects=False)
        except requests.Timeout as exc:
            _discard_http_session(session)
            raise VoiceInputError('asr_timeout', '语音识别超时，请重试。', status=504) from exc
        except requests.RequestException as exc:
            _discard_http_session(session)
            raise VoiceInputError('asr_connection_failed', '语音服务连接失败，请重试。', status=502) from exc
        received = time.perf_counter()
        try:
            result = response.json()
        except (ValueError, TypeError) as exc:
            raise VoiceInputError('asr_invalid_response', '语音服务返回了无效结果，请重试。', status=502) from exc
        if not isinstance(result, dict):
            raise VoiceInputError('asr_invalid_response', '语音服务返回了无效结果，请重试。', status=502)
        if response.status_code != 200 or result.get('code') not in (None, '', 200, '200') or result.get('error'):
            code = result.get('code')
            if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code):
                code = None
            message = ('语音服务请求过多，请稍后重试。' if response.status_code == 429 else
                       '语音服务鉴权失败，请检查服务配置。' if response.status_code in (401, 403) else
                       '语音模型或词库调用失败，请检查服务配置后重试。')
            raise VoiceInputError('asr_provider_error', message, status=502, provider_code=code)
        if result.get('model') not in (None, model):
            raise VoiceInputError('asr_model_mismatch', '语音服务返回的模型不符，请检查配置。', status=502)
        output = result.get('output')
        text = output.get('text') if isinstance(output, dict) else None
        if not isinstance(text, str) or len(text) > 12000:
            raise VoiceInputError('asr_invalid_response', '语音服务没有返回有效文字，请重试。', status=502)
        text = text.strip()
        parsed = time.perf_counter()
        return {'text': text, 'recognized': bool(text), 'model': model,
                'vocabulary_id': vocabulary, 'audio_seconds': round(seconds, 3),
                # Provider time includes network and model processing, not just
                # inference. No recording, transcript, URL or key is logged.
                'timings_ms': {
                    'validation': round((validated - started) * 1000, 3),
                    'preparation': round((prepared - validated) * 1000, 3),
                    'provider': round((received - prepared) * 1000, 3),
                    'parsing': round((parsed - received) * 1000, 3),
                    'total': round((parsed - started) * 1000, 3)}}
    finally:
        try:
            if response is not None:
                response.close()
            if session is not None:
                session.cookies.clear()
        finally:
            _ACTIVE.release()
