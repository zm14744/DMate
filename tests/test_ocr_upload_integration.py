"""Actual upload integration; synthetic boundaries do not certify model accuracy.

The optional Chromium test starts a new isolated Flask process and uses its real
file input and /ocr route. Required environment: DMATE_BROWSER_EXECUTABLE,
DMATE_BROWSER_CDN_CACHE, DMATE_UPLOAD_INTEGRATION_OUTPUT (a new private directory).
Missing browser configuration is an explicit skip, never an integration pass.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from scripts.verify_ocr_application_upload import (CASES, EXPECTED_BOUNDARY_CALLS, ROOT, SENTINEL,
    browser_uploads, clean_child_environment, digest, health_observation, local_service,
    multipart_observation, private_directory, run, summarize, synthetic_image, wait_file,
    write_bytes, write_json)


def test_child_environment_cannot_inherit_production_or_proxy_settings(tmp_path):
    contaminated = dict(PATH='/usr/bin', LANG='C.UTF-8', HOME='/production/account',
        DATABASE_URL='production-database', PGHOST='db.invalid', SMTP_PASSWORD='private',
        AUTH_SECRET_KEY='private', SECRET_KEY='private', DEEPSEEK_API_KEY='private',
        DASHSCOPE_API_KEY='private', HTTP_PROXY='http://proxy.invalid',
        PYTHONPATH='/untrusted', DMATE_GRAPH_NEXTGEN='0', TRUSTED_PROXY_CIDRS='0.0.0.0/0')
    isolated = clean_child_environment(tmp_path, contaminated)
    assert not set(isolated) & {'HOME', 'DATABASE_URL', 'PGHOST', 'SMTP_PASSWORD',
                               'AUTH_SECRET_KEY', 'SECRET_KEY', 'HTTP_PROXY', 'PYTHONPATH'}
    assert isolated['DMATE_GRAPH_NEXTGEN'] == '1'
    assert isolated['DASHSCOPE_API_KEY'] == isolated['DEEPSEEK_API_KEY'] == SENTINEL
    assert isolated['TRUSTED_PROXY_CIDRS'] == '' and isolated['TMPDIR'] == str(tmp_path)
    assert contaminated['DASHSCOPE_API_KEY'] == 'private'


@pytest.mark.parametrize('value', [
    'https://production.invalid', 'http://localhost:5000', 'http://0.0.0.0:5000',
    'http://127.0.0.1:5000/ocr', 'http://user:password@127.0.0.1:5000',
    'http://127.0.0.1', 'http://127.0.0.1:5000?target=production',
])
def test_only_explicit_literal_loopback_test_service_is_accepted(value):
    with pytest.raises(ValueError):
        local_service(value)


def test_existing_observations_and_repository_are_not_output_destinations(tmp_path):
    with pytest.raises(ValueError):
        private_directory(ROOT/'private-upload-report')
    existing = private_directory(tmp_path/'frozen')
    (existing/'first_response.bin').write_bytes(b'failed first response')
    with pytest.raises(FileExistsError):
        private_directory(existing)
    assert (existing/'first_response.bin').read_bytes() == b'failed first response'


def test_multipart_binding_checks_file_bytes_and_exact_request_id():
    import hashlib
    raw = (b'--boundary\r\nContent-Disposition: form-data; name="image"; filename="x.png"\r\n'
           b'Content-Type: image/png\r\n\r\n\x00original\xff\r\n--boundary\r\n'
           b'Content-Disposition: form-data; name="request_id"\r\n\r\nocr-123\r\n--boundary--\r\n')
    observed = multipart_observation(raw, 'multipart/form-data; boundary=boundary')
    assert observed == {'request_id': 'ocr-123', 'image_bytes': 10,
                        'image_sha256': hashlib.sha256(b'\x00original\xff').hexdigest()}
    with pytest.raises(ValueError):
        multipart_observation(raw.replace(b'name="request_id"', b'name="missing"'),
                              'multipart/form-data; boundary=boundary')


def _summary_fixture():
    source = {'git_sha': 'synthetic-snapshot', 'source_tree_sha256': 'tree', 'dirty': False}
    cases, requests, events = [], [], []
    for cid in CASES:
        request = {'path': '/ocr', 'request_id': cid, 'image_sha256': 'original'}
        cases.append({'id': cid, 'image_sha256': 'original', 'contract_status': 'pass',
                      'requests': [request], 'http_responses': [{'response_sha256': 'first'}]})
        requests.append({**request, 'case': cid, 'response_sha256': 'first',
                         'http_status': 200, 'cancelled': cid == 'cancel_local'})
        for provider, count in zip(('qwen', 'deepseek'), EXPECTED_BOUNDARY_CALLS[cid]):
            events.extend({'case': cid, 'kind': 'injected_model_boundary', 'provider': provider}
                          for _ in range(count))
    network = {'external_requests_blocked': [], 'cached_assets': [], 'external_network_sends': 0}
    server = {'guards': [], 'actual_model_sends': {'qwen': 0, 'deepseek': 0},
              'requests': requests, 'events': events, 'initial_health': {
                  '/health': {'http_status': 200}, '/ready': {'body': {'ocr_ready': False}}}}
    return cases, network, server, source


def test_synthetic_contract_pass_never_becomes_application_accuracy_certificate():
    cases, network, server, source = _summary_fixture()
    actual = summarize('synthetic', cases, network, server, source, source)
    assert actual['application_contract_status'] == 'pass'
    assert actual['status'] == actual['application_status'] == 'not_certified'
    assert actual['fixture_only'] is True
    assert actual['recognition_accuracy_test'] is False
    assert actual['application_certified_passes'] == actual['first_pass_certified_images'] == 0
    assert actual['actual_model_sends'] == {'qwen': 0, 'deepseek': 0}


@pytest.mark.parametrize('mutation,problem', [
    ('database', 'child_isolation_missing_or_violated'),
    ('first_response', 'normal:first_http_response_not_bound'),
    ('original', 'normal:original_upload_not_bound'),
    ('cancel', 'cancel_during_local_worker_entered_model'),
    ('source', 'source_changed_during_observation'),
    ('inventory', 'missing_or_changed_case_inventory'),
])
def test_caught_exceptions_changed_bytes_and_cancelled_model_calls_cannot_pass(mutation, problem):
    cases, network, server, source = _summary_fixture()
    current = deepcopy(source)
    if mutation == 'database':
        server['guards'].append({'kind': 'database_connect'})
    elif mutation == 'first_response':
        server['requests'][0]['response_sha256'] = 'replacement'
    elif mutation == 'original':
        server['requests'][0]['image_sha256'] = 'downsampled'
    elif mutation == 'cancel':
        server['events'].append({'case': 'cancel_local', 'kind': 'injected_model_boundary'})
    elif mutation == 'source':
        current['source_tree_sha256'] = 'different'
    elif mutation == 'inventory':
        cases.pop()
    actual = summarize('synthetic', cases, network, server, source, current)
    assert actual['status'] == actual['application_contract_status'] == 'fail'
    assert problem in actual['problems']
    assert actual['application_certified_passes'] == 0


def test_observed_http_does_not_invent_server_send_or_source_proof():
    cases, network, _, source = _summary_fixture()
    actual = summarize('observed-http', cases[:1], network, None, source, source)
    assert actual['actual_model_sends'] is None and actual['fixture_only'] is False
    assert actual['model_send_verification'] == 'unverified_server_metrics_only'
    assert actual['status'] == 'not_certified' and actual['application_certified_passes'] == 0
    with pytest.raises(ValueError, match='Unknown harness mode'):
        summarize('trust-me', cases, network, None, source, source)


def test_actual_chromium_file_input_through_real_isolated_flask_route():
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE')
    cache = os.environ.get('DMATE_BROWSER_CDN_CACHE')
    output = os.environ.get('DMATE_UPLOAD_INTEGRATION_OUTPUT')
    if not executable or not cache or not output:
        pytest.skip('Actual upload not run: set Chromium, verified cache and a new private output directory')
    pytest.importorskip('playwright.sync_api')
    summary = run('synthetic', output, executable, cache)
    assert summary['application_contract_status'] == 'pass', summary['problems']
    assert summary['status'] == 'not_certified'
    assert summary['application_certified_passes'] == 0 and summary['fixture_only'] is True
    assert summary['document_requests'] == len(CASES) == summary['contract_cases_passed']
    assert summary['actual_model_sends'] == {'qwen': 0, 'deepseek': 0}
    server = json.loads((Path(output)/'server_evidence.json').read_text())
    assert server['guards'] == []
    assert server['initial_health']['/ready']['body']['ocr_ready'] is False
    for case in summary['cases']:
        boundary_calls = [e for e in server['events']
                          if e['kind'] == 'injected_model_boundary' and e['case'] == case['id']]
        expected = {'normal': (2, 1), 'memory_limit': (2, 1), 'vision_failure': (1, 0),
                    'cancel_local': (0, 0), 'duplicate_selection': (2, 1)}[case['id']]
        assert tuple(sum(e['provider'] == p for e in boundary_calls) for p in ('qwen', 'deepseek')) == expected
        assert all(item['status'] == 'pass' for item in case['checks'])
        if case['id'] == 'cancel_local':
            response = next(r for r in server['requests'] if r['case'] == 'cancel_local' and r['path'] == '/ocr')
            body = json.loads((Path(output)/'isolated_server'/response['response_file']).read_text())
            assert body == {'cancelled': True}
        else:
            first = case['http_responses'][0]
            assert first['http_status'] == 200
            assert first['body']['diagnostics']['local_ocr']['available'] is True
            assert 'text' in first['body']['diagnostics']['local_ocr']['stages']


def _serve_semantic_fixture(folder):
    """Real app/provider/tool adapters; worker fixtures, no model or external sends."""
    import socket
    import smtplib
    import requests
    from flask import request
    from werkzeug.serving import make_server, WSGIRequestHandler

    folder = Path(folder)
    expected = clean_child_environment(folder)
    expected.pop('DMATE_GRAPH_PIPELINE')
    if ({k: v for k, v in os.environ.items() if k != 'LC_CTYPE'} != expected):
        raise ValueError('Semantic fixture must have a clean default-pipeline environment')
    ledger = {'fixture_only': True, 'actual_model_sends': {'qwen': 0, 'glm': 0, 'deepseek': 0},
              'guards': [], 'boundary_calls': [], 'requests': [], 'worker_events': []}

    def forbidden(name):
        def fail(*args, **kwargs):
            ledger['guards'].append(name)
            raise RuntimeError('semantic_fixture_forbidden_'+name)
        return fail

    requests.sessions.Session.send = forbidden('http_send')
    socket.socket.connect = forbidden('socket_connect')
    socket.socket.connect_ex = forbidden('socket_connect_ex')
    smtplib.SMTP = forbidden('smtp')
    smtplib.SMTP_SSL = forbidden('smtp_ssl')
    try:
        import psycopg
        psycopg.connect = forbidden('database_connect')
    except ImportError:
        pass
    import ocr_runtime
    for name in ('load_models', 'recognize_image'):
        setattr(ocr_runtime, name, forbidden(name))
    import pytest
    from test_graph_semantic_pipeline import install_semantic_worker_fixtures
    worker_patch = pytest.MonkeyPatch()
    install_semantic_worker_fixtures(worker_patch, ledger['worker_events'], lock_root=folder)
    import app as application
    import ai
    if application.AUTH_CONFIGURED or application.TRUSTED_PROXY_CIDRS:
        raise ValueError('Semantic fixture unexpectedly configured production accounts')
    for name in ('recognize_graphs', 'analyze_image_structure', 'verify_graph_image_independently'):
        setattr(application, name, forbidden(name))

    def qwen(payload, headers, **kwargs):
        content = payload['messages'][0]['content']
        prompt = next(row['text'] for row in content if row['type'] == 'text')
        task = json.loads(prompt.rsplit('\n', 1)[1])
        role = task['role']
        ledger['boundary_calls'].append({'provider': 'qwen', 'role': role,
            'review_mode': task.get('review_mode'),
            'local_text_hint_count': len(task.get('local_ocr_candidates', [])),
            'layout_candidates_received': bool(task.get('local_layout_candidates'))})
        # This answers only synthetic_image(); the real provider and LangGraph
        # still parse, normalize, review and serialize their own response.
        document = {'body_text': 'Count the edges.', 'graphs': [{'id': 'G1',
            'vertices': [{'id': 'a', 'label': 'a'}, {'id': 'b', 'label': 'b'}],
            'edges': [{'from': 'a', 'to': 'b', 'direction': 'undirected'}]}], 'uncertainties': []}
        if role == 'semantic_extract':
            for graph in document['graphs']:
                graph['edges'] = []
        elif role == 'semantic_edges':
            from test_agent_upload_route import source_reply
            document = source_reply(document, task['task'])
        elif role == 'semantic_review' and task.get('review_mode') == 'read_only':
            document = {'issues': []}
        elif role == 'semantic_body':
            document = {'body_text': document['body_text'], 'uncertainties': []}
        elif role != 'semantic_review':
            raise AssertionError('Unexpected role in successful semantic upload: '+role)
        return 200, {}, {'model': 'qwen3-vl-plus', 'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(document)}}]}

    def deepseek(*args, **kwargs):
        ledger['boundary_calls'].append({'provider': 'deepseek'})
        return {'ok': True, 'content': '{"edits":[]}',
                'choice': {'finish_reason': 'stop'}, 'model': 'deepseek-flash'}

    ai._request_qwen_completion = qwen
    ai._request_text_completion = deepseek

    @application.app.after_request
    def observe(response):
        record = {'path': request.path, 'method': request.method, 'http_status': response.status_code}
        if request.path == '/ocr':
            image = request.files['image']
            image.stream.seek(0)
            raw, body = image.read(), response.get_data()
            write_bytes(folder/'first_response.bin', body)
            record.update(image_sha256=digest(raw), response_sha256=digest(body),
                          request_id=request.form['request_id'])
        ledger['requests'].append(record)
        return response

    class QuietHandler(WSGIRequestHandler):
        def log_request(self, *args, **kwargs):
            pass

    server = make_server('127.0.0.1', 0, application.app, threaded=True, request_handler=QuietHandler)
    write_json(folder/'server.json', {'url': 'http://127.0.0.1:'+str(server.server_port)})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while not (folder/'stop').exists():
            time.sleep(.05)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        write_json(folder/'server_evidence.json', ledger)


def test_actual_chromium_default_semantic_route_runs_local_tool_boundaries_without_models():
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE')
    cache = os.environ.get('DMATE_BROWSER_CDN_CACHE')
    base = os.environ.get('DMATE_UPLOAD_INTEGRATION_OUTPUT')
    if not executable or not cache or not base:
        pytest.skip('Semantic browser upload not run: set Chromium, verified cache and private output')
    pytest.importorskip('playwright.sync_api')
    output = private_directory(Path(base)/'semantic_default')
    folder = output/'isolated_server'
    folder.mkdir(mode=0o700)
    environment = clean_child_environment(folder)
    environment.pop('DMATE_GRAPH_PIPELINE')  # Exercise the actual default.
    command = [sys.executable, '-c',
               'import sys; sys.path.insert(0,"tests"); '
               'from test_ocr_upload_integration import _serve_semantic_fixture; '
               '_serve_semantic_fixture(sys.argv[1])', str(folder)]
    with (folder/'process.log').open('xb') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=log)
        try:
            service = wait_file(folder/'server.json', timeout=30)['url']
            initial = health_observation(service)
            write_json(output/'initial_health.json', initial)
            row = synthetic_image(output/'synthetic_transparent.png')
            cases, network = browser_uploads(service, [('semantic_default', row)], output, executable, cache)
        finally:
            (folder/'stop').touch()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
    server = wait_file(folder/'server_evidence.json', timeout=2)
    case = cases[0]
    response = case['http_responses'][0]
    submitted = [entry for entry in server['requests'] if entry['path'] == '/ocr']
    initial_ready = initial['/ready']['body']
    ready = case['health_after']['/ready']['body']
    report = {'fixture_only': True, 'status': 'not_certified',
              'actual_model_sends': server['actual_model_sends'],
              'case': case, 'network': network, 'initial_ready': initial_ready, 'ready': ready,
              'recognition_accuracy_test': False}
    write_json(output/'summary.json', report)
    assert case['contract_status'] == 'pass', case
    assert server['guards'] == []
    assert server['actual_model_sends'] == {'qwen': 0, 'glm': 0, 'deepseek': 0}
    assert network['external_requests_blocked'] == [] and network['external_network_sends'] == 0
    assert len(submitted) == 1
    assert submitted[0]['image_sha256'] == row['sha256']
    assert submitted[0]['request_id'] == case['browser_uploads'][0]['request_id']
    assert submitted[0]['response_sha256'] == response['response_sha256']
    assert response['body']['recognition_status'] == 'complete' and case['dialog_calls'] == 1
    assert response['body']['diagnostics']['semantic_workflow']['reviewed'] is True
    assert [entry['role'] for entry in server['boundary_calls'] if entry['provider'] == 'qwen'] == [
        'semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_body']
    assert next(row for row in server['boundary_calls']
                if row.get('role') == 'semantic_review')['review_mode'] == 'read_only'
    assert server['boundary_calls'][0]['local_text_hint_count'] > 0
    assert server['boundary_calls'][0]['layout_candidates_received']
    assert [row['stage'] for row in server['worker_events']
            if row['kind'] == 'injected_worker'] == ['layout', 'text']
    assert all(row['fixture_only'] for row in server['worker_events'])
    assert initial_ready['recognition_mode'] == ready['recognition_mode'] == 'semantic_visual'
    assert initial_ready['recognition_ready'] is False and ready['recognition_ready'] is True
    assert ready['ocr_ready'] is True and ready['local_ocr_required'] is False
    assert ready['ocr_stages']['text']['status'] == 'ok'
    assert ready['ocr_stages']['text']['model_inference_completed'] is True
    assert ready['ocr_stages']['semantic']['status'] == 'complete'
    assert all(entry['path'] not in ('/init_ocr', '/chat') for entry in server['requests'])
