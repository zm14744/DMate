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

import pytest

from scripts.verify_ocr_application_upload import (CASES, EXPECTED_BOUNDARY_CALLS, ROOT, SENTINEL,
    clean_child_environment, local_service, multipart_observation, private_directory,
    run, summarize)


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
