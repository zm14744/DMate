"""Native Qwen Audio ASR and precompiled vocabulary, without paid model calls."""
import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import socket
import threading
from types import SimpleNamespace
import wave
from unittest.mock import Mock

import pytest
import requests

import voice_input as voice
from test_ocr_application_contract import application


def wav(seconds=1, *, channels=1, width=2, rate=16000):
    result = io.BytesIO()
    with wave.open(result, 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(b'\0' * int(seconds * rate) * channels * width)
    return result.getvalue()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'synthetic-test-key')
    monkeypatch.delenv('DMATE_ASR_MODEL', raising=False)
    monkeypatch.delenv('DMATE_ASR_VOCABULARY_ID', raising=False)
    monkeypatch.setenv('DMATE_ASR_API_URL', 'https://workspace.example/compatible-mode/v1/chat/completions')
    monkeypatch.setattr(voice, '_HTTP', threading.local())
    yield
    session = getattr(voice._HTTP, 'session', None)
    if session is not None:
        session.close()


def reply(payload=None, status=200):
    return Mock(status_code=status, json=Mock(return_value=payload if payload is not None else {
        'output': {'text': '求顶点A到B的最短路径。'}, 'request_id': 'synthetic-remote-id'}))


def test_one_native_request_contains_exact_requested_model_vocabulary_and_audio(configured):
    raw = wav()
    post = Mock(return_value=reply())
    result = voice.transcribe_voice(raw, post=post)
    post.assert_called_once()
    endpoint = post.call_args.args[0]
    arguments = post.call_args.kwargs
    assert endpoint == 'https://workspace.example/api/v1/services/aigc/multimodal-generation/generation'
    assert arguments['headers']['X-DashScope-SSE'] == 'disable'
    assert arguments['headers']['Authorization'] == 'Bearer synthetic-test-key'
    payload = arguments['json']
    assert payload['model'] == 'qwen-audio-3.1-asr-flash'
    assert payload['parameters'] == {'format': 'wav', 'sample_rate': '16000',
        'vocabulary_id': 'vocab-dmate-60d8d29883164a5a83fdfbb7f21772a9'}
    encoded = payload['input']['messages'][0]['content'][0]['input_audio']['data']
    assert base64.b64decode(encoded.split(',', 1)[1]) == raw
    assert arguments['allow_redirects'] is False
    assert arguments['timeout'] == (8, 50)
    timings = result.pop('timings_ms')
    assert set(timings) == {'validation', 'preparation', 'provider', 'parsing', 'total'}
    assert all(isinstance(value, (int, float)) and value >= 0 for value in timings.values())
    assert timings['total'] == pytest.approx(sum(timings[key] for key in timings if key != 'total'), abs=.005)
    assert result == {'text': '求顶点A到B的最短路径。', 'recognized': True,
        'model': voice.DEFAULT_MODEL, 'vocabulary_id': voice.DEFAULT_VOCABULARY_ID, 'audio_seconds': 1.0}


def test_phase_timings_separate_local_preparation_from_provider_round_trip(configured, monkeypatch):
    monkeypatch.setattr(voice, 'time', SimpleNamespace(perf_counter=Mock(
        side_effect=[1, 1.002, 1.005, 1.045, 1.046])))
    result = voice.transcribe_voice(wav(), post=Mock(return_value=reply()))
    assert result['timings_ms'] == {'validation': 2, 'preparation': 3, 'provider': 40,
                                   'parsing': 1, 'total': 46}


@pytest.fixture
def local_asr(configured, monkeypatch):
    """A local HTTP/1.1 server measures actual socket reuse, never paid ASR."""
    records = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            records.append({'body': json.loads(body), 'headers': dict(self.headers),
                            'connection': self.client_address})
            if self.server.drop_next:
                self.server.drop_next = False
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            payload = json.dumps({'output': {'text': '离散数学'}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Set-Cookie', 'provider_session=must-not-cross-users')
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.drop_next = False
    runner = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    runner.start()
    monkeypatch.setattr(voice, '_configuration', lambda: (
        f'http://127.0.0.1:{server.server_port}/asr', voice.DEFAULT_MODEL,
        voice.DEFAULT_VOCABULARY_ID, 'synthetic-test-key'))
    # The production Session keeps trust_env for the managed proxy/CA setup;
    # this loopback fixture deliberately bypasses external network proxies.
    session_factory = requests.Session

    def local_session():
        session = session_factory()
        session.trust_env = False
        return session

    monkeypatch.setattr(voice.requests, 'Session', local_session)
    yield server, records
    voice._discard_http_session(getattr(voice._HTTP, 'session', None))
    server.shutdown()
    server.server_close()
    runner.join(timeout=2)


def test_repeated_dictation_reuses_connection_without_changing_audio_or_user_headers(local_asr, monkeypatch):
    server, records = local_asr
    raw = wav()
    first = voice.transcribe_voice(raw)
    monkeypatch.setattr(voice, '_configuration', lambda: (
        f'http://127.0.0.1:{server.server_port}/asr', voice.DEFAULT_MODEL,
        voice.DEFAULT_VOCABULARY_ID, 'synthetic-next-key'))
    second = voice.transcribe_voice(raw)
    assert first['text'] == second['text'] == '离散数学'
    assert len(records) == 2
    assert records[0]['connection'] == records[1]['connection']
    assert records[0]['body'] == records[1]['body']
    payload = records[0]['body']
    assert payload['model'] == 'qwen-audio-3.1-asr-flash'
    assert payload['parameters'] == {'format': 'wav', 'sample_rate': '16000',
        'vocabulary_id': 'vocab-dmate-60d8d29883164a5a83fdfbb7f21772a9'}
    assert base64.b64decode(payload['input']['messages'][0]['content'][0]['input_audio']['data'].split(',', 1)[1]) == raw
    assert records[0]['headers']['Authorization'] == 'Bearer synthetic-test-key'
    assert records[1]['headers']['Authorization'] == 'Bearer synthetic-next-key'
    assert all('Cookie' not in item['headers'] for item in records)
    assert not voice._http_session().cookies


def test_dropped_response_does_not_replay_post_and_next_dictation_gets_new_connection(local_asr):
    server, records = local_asr
    server.drop_next = True
    with pytest.raises(voice.VoiceInputError, match='连接失败') as found:
        voice.transcribe_voice(wav())
    assert found.value.code == 'asr_connection_failed'
    assert len(records) == 1
    assert voice._HTTP.session is None
    assert voice.transcribe_voice(wav())['recognized'] is True
    assert len(records) == 2
    assert records[0]['connection'] != records[1]['connection']


def test_sessions_are_thread_local_and_https_pool_never_retries(configured):
    barrier = threading.Barrier(2)

    def worker():
        session = voice._http_session()
        try:
            barrier.wait(timeout=2)
            assert voice._http_session() is session
            adapter = session.get_adapter('https://example.invalid/asr')
            assert adapter.max_retries.total == 0
            assert adapter._pool_connections == adapter._pool_maxsize == 1
            assert adapter._pool_block is True
            assert session.trust_env is True
            return session
        finally:
            voice._discard_http_session(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _index: worker(), range(2)))
    assert first is not second


def test_forked_worker_discards_inherited_connection_pool(configured):
    inherited = voice._http_session()
    inherited.close = Mock(wraps=inherited.close)
    voice._HTTP.pid = -1
    current = voice._http_session()
    assert current is not inherited
    inherited.close.assert_called_once()
    assert voice._http_session() is current


def test_explicit_service_configuration_is_used_without_fallback(configured, monkeypatch):
    monkeypatch.setenv('DMATE_ASR_MODEL', 'qwen-audio-3.1-asr-flash-pinned')
    monkeypatch.setenv('DMATE_ASR_VOCABULARY_ID', 'vocab-configured-one')
    post = Mock(return_value=reply())
    result = voice.transcribe_voice(wav(), post=post)
    assert result['model'] == 'qwen-audio-3.1-asr-flash-pinned'
    assert result['vocabulary_id'] == 'vocab-configured-one'
    assert post.call_count == 1


@pytest.mark.parametrize('raw,code', [(b'', 'empty_audio'), (b'not-a-wave-file', 'unsupported_audio'),
    (wav(.05), 'audio_too_short'), (wav(60.01), 'audio_too_long'),
    (wav(channels=2), 'unsupported_audio'), (wav(width=1), 'unsupported_audio'),
    (wav(rate=48000), 'unsupported_audio'), (wav()[:-15], 'invalid_audio'),
    (b'x' * (voice.MAX_AUDIO_BYTES + 1), 'audio_too_large')])
def test_invalid_recording_is_rejected_before_provider(configured, raw, code):
    post = Mock()
    with pytest.raises(voice.VoiceInputError) as found:
        voice.transcribe_voice(raw, post=post)
    assert found.value.code == code
    post.assert_not_called()


@pytest.mark.parametrize('response,code', [
    (reply({'code': 'InvalidVocabularyId', 'message': 'private provider detail'}, 400), 'asr_provider_error'),
    (reply({'error': {'message': 'private provider detail'}}, 401), 'asr_provider_error'),
    (reply({'output': {'text': 'text'}}, 302), 'asr_provider_error'),
    (reply({'output': {'text': None}}), 'asr_invalid_response'),
    (reply({'output': {'text': 'x' * 12001}}), 'asr_invalid_response'),
    (reply({'output': {'text': 'text'}, 'model': 'some-other-model'}), 'asr_model_mismatch'),
    (reply([]), 'asr_invalid_response'),
])
def test_remote_error_never_becomes_empty_success_or_model_fallback(configured, response, code):
    post = Mock(return_value=response)
    with pytest.raises(voice.VoiceInputError) as found:
        voice.transcribe_voice(wav(), post=post)
    assert found.value.code == code
    assert 'private provider detail' not in found.value.message
    assert post.call_count == 1


@pytest.mark.parametrize('failure,code', [(requests.Timeout(), 'asr_timeout'),
                                         (requests.ConnectionError(), 'asr_connection_failed')])
def test_network_fault_releases_shared_capacity_without_retry(configured, failure, code):
    post = Mock(side_effect=failure)
    with pytest.raises(voice.VoiceInputError) as found:
        voice.transcribe_voice(wav(), post=post)
    assert found.value.code == code
    assert post.call_count == 1
    assert voice.transcribe_voice(wav(), post=Mock(return_value=reply()))['recognized'] is True


def test_blank_transcript_is_explicit_not_recognized(configured):
    result = voice.transcribe_voice(wav(), post=Mock(return_value=reply({'output': {'text': '   '}})))
    assert result['text'] == '' and result['recognized'] is False


def test_busy_shared_capacity_rejects_before_network(configured):
    post = Mock()
    assert voice._ACTIVE.acquire(blocking=False)
    assert voice._ACTIVE.acquire(blocking=False)
    try:
        with pytest.raises(voice.VoiceInputError) as found:
            voice.transcribe_voice(wav(), post=post)
        assert found.value.code == 'asr_busy' and found.value.status == 429
        post.assert_not_called()
    finally:
        voice._ACTIVE.release()
        voice._ACTIVE.release()


def test_voice_uses_a_separate_bounded_existing_rate_limit_bucket(monkeypatch):
    from collections import defaultdict, deque
    import app as module
    monkeypatch.setattr(module, '_request_history', defaultdict(deque))
    monkeypatch.setattr(module, 'RATE_LIMIT_OCR', 2)
    with module.app.test_request_context('/voice/transcribe'):
        assert module._check_rate_limit('synthetic-ip', 'voice') is True
        assert module._check_rate_limit('synthetic-ip', 'voice') is True
        assert module._check_rate_limit('synthetic-ip', 'voice') is False
        assert module._check_rate_limit('synthetic-ip', 'ocr') is True


def test_missing_key_is_reported_before_network(monkeypatch):
    monkeypatch.delenv('DASHSCOPE_API_KEY', raising=False)
    monkeypatch.delenv('DASHSCOPE_VISION_API_KEY', raising=False)
    post = Mock()
    with pytest.raises(voice.VoiceInputError) as found:
        voice.transcribe_voice(wav(), post=post)
    assert found.value.code == 'asr_not_configured'
    post.assert_not_called()


def test_flask_voice_endpoint_returns_only_dictation_and_disables_caching(application, monkeypatch):
    _, client, _ = application
    captured = []
    monkeypatch.setattr(voice, 'transcribe_voice', lambda raw: captured.append(raw) or {'text': '测试语音', 'recognized': True})
    raw = wav()
    result = client.post('/voice/transcribe', data={'audio': (io.BytesIO(raw), 'recording.wav')})
    assert result.status_code == 200 and result.get_json()['text'] == '测试语音'
    assert result.get_json()['ok'] is True
    assert result.headers['Cache-Control'] == 'no-store'
    assert captured == [raw]
    assert client.post('/voice/transcribe', data={}).status_code == 400


def test_flask_voice_endpoint_keeps_error_status_and_safe_provider_code(application, monkeypatch):
    _, client, _ = application
    def fail(raw):
        raise voice.VoiceInputError('asr_provider_error', '语音模型或词库调用失败。', status=502,
                                    provider_code='InvalidVocabularyId')
    monkeypatch.setattr(voice, 'transcribe_voice', fail)
    result = client.post('/voice/transcribe', data={'audio': (io.BytesIO(wav()), 'recording.wav')})
    assert result.status_code == 502
    assert result.get_json()['ok'] is False
    assert result.get_json()['provider_code'] == 'InvalidVocabularyId'
    assert result.headers['Cache-Control'] == 'no-store'
