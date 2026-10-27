"""Independent first-upload/semantic counterexamples; no model or network calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading

import pytest

from scripts import benchmark_graph_first_pass as runner


SHA = 'a' * 64


def graph():
    return {'name': 'G1', 'name_required': True,
            'vertices': [{'id': 'a', 'label': 'v1'}, {'id': 'b', 'label': 'v2'}],
            'edges': [{'from': 'a', 'to': 'b', 'direction': 'forward',
                       'weight': 2, 'edge_label': 'e1', 'style': 'solid', 'color': 'red'},
                      {'from': 'a', 'to': 'b', 'direction': 'forward',
                       'weight': 3, 'edge_label': 'e2', 'style': 'dashed', 'color': 'blue'}],
            'required_attributes': ['style', 'color']}


def example():
    gold = {'id': 'original', 'sha256': SHA, 'annotation_status': 'reviewed',
            'body_text': 'Find the shortest path.', 'graphs': [graph()], 'ambiguities': []}
    prediction = {'text': gold['body_text'], 'graph_structures': deepcopy(gold['graphs']),
                  'recognition_status': 'complete', 'review': {'required': False}}
    return gold, prediction


def assess(gold, prediction):
    return runner.evaluate_visible_semantics(gold, prediction, image_sha256=SHA)


def test_semantics_ignore_geometry_and_internal_ids_but_normalize_only_subscripts():
    gold, prediction = example()
    actual = prediction['graph_structures'][0]
    actual['name'] = 'G_{1}'
    actual['bbox'] = [0, 0, 1, 1]
    actual['vertices'] = [{'id': 'other-2', 'label': 'v₂', 'x': .8, 'y': .1},
                          {'id': 'other-1', 'label': 'v_{1}', 'x': .3, 'y': .9}]
    for edge in actual['edges']:
        edge.update({'from': 'other-1', 'to': 'other-2', 'path': [[0, 0], [1, 1]]})
    actual['edges'][0]['edge_label'] = 'e₁'
    assert assess(gold, prediction)['status'] == 'pass'
    actual['vertices'][0]['label'] = 'V2'
    assert assess(gold, prediction)['graphs_status'] == 'fail'


@pytest.mark.parametrize('field', ['weight', 'edge_label', 'style', 'color'])
def test_parallel_attributes_are_compared_jointly(field):
    gold, prediction = example()
    edges = prediction['graph_structures'][0]['edges']
    edges[0][field], edges[1][field] = edges[1][field], edges[0][field]
    assert assess(gold, prediction)['graphs_status'] == 'fail'


@pytest.mark.parametrize('mutation', ['reverse', 'undirected', 'missing_edge', 'loop', 'duplicate'])
def test_direction_endpoint_loop_and_multiplicity_changes_fail(mutation):
    gold, prediction = example()
    edges = prediction['graph_structures'][0]['edges']
    if mutation in ('reverse', 'undirected'):
        edges[0]['direction'] = mutation
    elif mutation == 'missing_edge':
        edges.pop()
    elif mutation == 'loop':
        edges[0]['to'] = edges[0]['from']
    else:
        edges.append(deepcopy(edges[0]))
    assert assess(gold, prediction)['graphs_status'] == 'fail'


def test_anonymous_and_duplicate_labels_preserve_vertex_inventory_and_isomorphism():
    gold, prediction = example()
    gold['graphs'][0]['vertices'] = [{'id': 'a', 'label': None}, {'id': 'b', 'label': None}]
    actual = prediction['graph_structures'][0]
    actual['vertices'] = [{'id': 'x', 'label': None}, {'id': 'y', 'label': None}]
    for edge in actual['edges']:
        edge.update({'from': 'y', 'to': 'x'})
    assert assess(gold, prediction)['graphs_status'] == 'pass'
    actual['vertices'].append({'id': 'z', 'label': None})
    assert assess(gold, prediction)['graphs_status'] == 'fail'


def test_panel_matching_ignores_order_and_preserves_duplicate_panel_count():
    gold, prediction = example()
    other = deepcopy(gold['graphs'][0])
    other.update(name='G2')
    other['edges'] = other['edges'][:1]
    gold['graphs'].append(other)
    prediction['graph_structures'].insert(0, deepcopy(other))
    assert assess(gold, prediction)['graphs_status'] == 'pass'
    prediction['graph_structures'][1] = deepcopy(other)
    assert assess(gold, prediction)['graphs_status'] == 'fail'


def test_decorative_attributes_and_unprinted_panel_titles_are_explicitly_out_of_scope():
    gold, prediction = example()
    gold['graphs'][0].update(required_attributes=[], name_required=False)
    actual = prediction['graph_structures'][0]
    actual['name'] = 'generated arbitrary panel ID'
    actual['edges'][0].update(style='unknown', color='unknown')
    result = assess(gold, prediction)
    assert result['status'] == 'pass'
    assert result['ungraded_attributes'] == ['color', 'style']


@pytest.mark.parametrize('field', ['weight', 'edge_label', 'direction'])
def test_missing_prediction_attributes_do_not_mean_absent(field):
    gold, prediction = example()
    gold['graphs'][0]['edges'][0].update(weight=None, edge_label=None)
    prediction['graph_structures'][0]['edges'][0].update(weight=None, edge_label=None)
    prediction['graph_structures'][0]['edges'][0].pop(field)
    assert assess(gold, prediction)['graphs_status'] == 'fail'


def test_unreviewed_reference_is_ungraded_and_partial_prediction_stays_separate():
    gold, prediction = example()
    prediction['recognition_status'] = 'partial'
    prediction['review']['required'] = True
    result = assess(gold, prediction)
    assert result['status'] == 'pass' and result['recognition_status'] == 'partial'
    gold['annotation_status'] = 'ambiguous'
    assert assess(gold, prediction)['status'] == 'ungraded'


def test_body_mismatch_and_empty_graph_inventory_are_scored_independently():
    gold, prediction = example()
    gold['graphs'] = prediction['graph_structures'] = []
    assert assess(gold, prediction)['status'] == 'pass'
    prediction['text'] = 'A different question.'
    result = assess(gold, prediction)
    assert result['graphs_status'] == 'pass' and result['text_status'] == 'fail'


@pytest.mark.parametrize('required', [['style'], 'style', ['unknown_field']])
def test_missing_required_reference_attribute_never_becomes_a_scoped_pass(required):
    gold, prediction = example()
    gold['graphs'][0]['required_attributes'] = required
    gold['graphs'][0]['edges'][0].pop('style')
    assert assess(gold, prediction)['status'] == 'ungraded'


def test_public_projection_is_scored_when_present_even_if_internal_graph_is_correct():
    gold, prediction = example()
    prediction['graph_display_data'] = deepcopy(prediction['graph_structures'])
    prediction['graph_display_data'][0]['edges'][0]['to'] = 'a'
    result = assess(gold, prediction)
    assert result['status'] == 'fail'
    assert result['graph_content_source'] == 'graph_display_data'


def test_pi_math_token_spelling_is_equivalent_without_evaluating_expressions():
    gold, prediction = example()
    gold['graphs'][0]['edges'][0]['weight'] = 'π'
    prediction['graph_structures'][0]['edges'][0]['weight'] = r'\(\pi\)'
    assert assess(gold, prediction)['status'] == 'pass'


def test_local_semantic_selection_uses_current_pipeline_without_legacy_ocr_prerun(monkeypatch):
    import ocr_nextgen
    import ocr_runtime
    calls = []
    monkeypatch.setattr(ocr_runtime, 'recognize_image', lambda raw: pytest.fail('Legacy OCR prerun is not selected'))
    def selected(raw, text, **kwargs):
        calls.append(kwargs)
        return {'recognition_status': 'partial', 'diagnostics': {'remote_metrics': []}}
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', selected)
    prediction, evidence = runner.local_recognition(b'private-original', execution_id='first', pipeline='agent-tools')
    assert calls == [{'graph_pipeline': 'agent-tools', 'task_id': 'first'}]
    assert evidence['pipeline_contract'] == 'agent-tools'
    assert evidence['model_send_verification'] == 'pipeline_reported_unverified'


@pytest.fixture
def observed_service(tmp_path, monkeypatch):
    from PIL import Image
    import runtime_source_identity
    image = tmp_path/'source.png'
    Image.new('RGB', (16, 16), 'white').save(image)
    rows = [{'id': 'one', 'path': str(image), 'sha256': runner.digest(image.read_bytes())},
            {'id': 'two', 'path': str(image), 'sha256': runner.digest(image.read_bytes())}]
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'entries': rows}))
    runtime = {'status': 'ok', 'manifest_sha256': SHA, 'scope': 'test-source'}
    monkeypatch.setattr(runtime_source_identity, 'compute_runtime_source', lambda root: (runtime, {}))
    monkeypatch.setattr(runner, 'source_snapshot', lambda: {'git_sha': 'b'*40, 'dirty': False,
                                                         'source_tree_sha256': SHA})
    monkeypatch.setattr(runner, 'inspect_http_service', lambda url: {'runtime_sha256': SHA,
        'runtime_source': runtime, 'pipeline': 'agent-tools', 'pipeline_version': 'test-version'})
    sent = []
    def capture(raw, base_url, filename, timeout, **kwargs):
        sent.append((filename, kwargs['execution_id'], kwargs['pipeline']))
        prediction = {'text': 'first', 'graph_structures': [], 'recognition_status': 'partial',
                      'graph_display_version': 'test-version'}
        body = (json.dumps(prediction)+'\n').encode()
        kwargs['response_path'].write_bytes(body)
        return prediction, {'status': 'completed', 'http_status': 200,
                            'runtime_sha256': SHA, 'raw_response_sha256': runner.digest(body)}
    monkeypatch.setattr(runner, 'http_recognition', capture)
    args = ['--manifest', str(manifest), '--pipeline', 'auto', '--base-url', 'http://127.0.0.1:8081',
            '--source-root', str(tmp_path), '--output', str(tmp_path/'results')]
    return args, sent, tmp_path/'results'


def test_selected_runner_captures_each_original_once_without_gold_and_preserves_first_results(observed_service):
    args, sent, output = observed_service
    assert runner.main(args) == 0
    assert len(sent) == 2 and len({item[1] for item in sent}) == 2
    assert all(item[2] == 'agent-tools' for item in sent)
    summary = json.loads((output/'summary.json').read_text())
    assert summary['recognition_status_counts'] == {'partial': 2}
    assert summary['semantic_status_counts'] == {'ungraded': 2}
    assert summary['application_certified_passes'] == 0
    assert (output/'one'/'first-response.bin').read_bytes().endswith(b'\n')
    with pytest.raises(SystemExit):
        runner.main(args)
    assert len(sent) == 2


def test_server_source_mismatch_prevents_any_upload(observed_service, monkeypatch):
    args, sent, output = observed_service
    monkeypatch.setattr(runner, 'inspect_http_service', lambda url: {
        'runtime_sha256': 'c'*64, 'pipeline': 'agent-tools'})
    with pytest.raises(SystemExit):
        runner.main(args)
    assert sent == []


def test_response_pipeline_version_is_verified_and_mismatch_stops_remaining_uploads(observed_service, monkeypatch):
    args, sent, output = observed_service
    capture = runner.http_recognition
    def wrong_pipeline(*args, **kwargs):
        prediction, evidence = capture(*args, **kwargs)
        prediction['graph_display_version'] = 'wrong-pipeline-version'
        return prediction, evidence
    monkeypatch.setattr(runner, 'http_recognition', wrong_pipeline)
    assert runner.main(args) == 2
    assert len(sent) == 1
    first = json.loads((output/'one'/'result.json').read_text())
    assert first['response_pipeline_verified'] is False
    second = json.loads((output/'two'/'result.json').read_text())
    assert second['reason'] == 'first_response_pipeline_mismatch'


def test_http_raw_error_body_is_kept_exactly_without_retry(tmp_path, monkeypatch):
    import io
    from urllib.error import HTTPError
    from PIL import Image
    image = io.BytesIO()
    Image.new('RGB', (2, 2)).save(image, 'PNG')
    body = b'\xff failed upstream\n'
    class Opener:
        calls = 0
        def open(self, req, timeout):
            self.calls += 1
            raise HTTPError(req.full_url, 503, 'failed', {'X-DMate-Runtime-Sha256': SHA}, io.BytesIO(body))
    opener = Opener()
    monkeypatch.setattr(runner.request, 'build_opener', lambda *args: opener)
    path = tmp_path/'first.bin'
    prediction, evidence = runner.http_recognition(image.getvalue(), 'http://127.0.0.1:8081',
        'test.png', 10, pipeline='agent-tools', response_path=path)
    assert opener.calls == 1 and prediction is None
    assert path.read_bytes() == body
    assert evidence['raw_response_sha256'] == runner.digest(body)
    assert evidence['http_status'] == 503
    with pytest.raises(FileExistsError):
        runner.http_recognition(image.getvalue(), 'http://127.0.0.1:8081', 'test.png', 10, response_path=path)
    assert opener.calls == 1


def test_frozen_capture_can_be_scored_later_without_new_upload_and_detects_tampering(observed_service, monkeypatch):
    args, sent, output = observed_service
    assert runner.main(args) == 0
    manifest = args[args.index('--manifest')+1]
    rows = json.loads(__import__('pathlib').Path(manifest).read_text())['entries']
    gold = output.parent/'gold.json'
    gold.write_text(json.dumps({'images': [{**row, 'annotation_status': 'reviewed',
        'body_text': 'first', 'graphs': [], 'ambiguities': []} for row in rows]}))
    def forbidden(*args, **kwargs):
        pytest.fail('Offline evaluation must not contact any service')
    monkeypatch.setattr(runner, 'http_recognition', forbidden)
    monkeypatch.setattr(runner, 'inspect_http_service', forbidden)
    evaluation = ['--evaluate-run', str(output), '--manifest', manifest, '--annotations', str(gold)]
    assert runner.main(evaluation+['--output', str(output.parent/'scored')]) == 0
    assert len(sent) == 2
    summary = json.loads((output.parent/'scored'/'summary.json').read_text())
    assert summary['semantic_status_counts'] == {'pass': 2}
    assert summary['actual_document_requests'] == summary['model_calls'] == 0
    (output/'one'/'first-response.bin').write_bytes(b'{}')
    assert runner.main(evaluation+['--output', str(output.parent/'tampered')]) == 2


def _four_images(args):
    manifest = Path(args[args.index('--manifest')+1])
    data = json.loads(manifest.read_text())
    data['entries'].extend([{**data['entries'][0], 'id': name} for name in ('three', 'four')])
    manifest.write_text(json.dumps(data))


@pytest.mark.parametrize('jobs', [2, 4])
def test_jobs_overlap_with_unique_first_requests_and_independent_artifacts(observed_service, monkeypatch, jobs):
    args, sent, output = observed_service
    _four_images(args)
    capture, stdout = runner.http_recognition, sys.stdout
    barrier, lock = threading.Barrier(jobs), threading.Lock()
    active = {'count': 0, 'maximum': 0}
    def concurrent(*args, **kwargs):
        assert sys.stdout is stdout, 'HTTP workers must not replace process-global output streams'
        with lock:
            active['count'] += 1
            active['maximum'] = max(active['maximum'], active['count'])
        try:
            barrier.wait(timeout=3)
            return capture(*args, **kwargs)
        finally:
            with lock:
                active['count'] -= 1
    monkeypatch.setattr(runner, 'http_recognition', concurrent)
    assert runner.main(args+['--jobs', str(jobs)]) == 0
    assert active['maximum'] == jobs
    assert len(sent) == len({row[1] for row in sent}) == 4
    summary = json.loads((output/'summary.json').read_text())
    assert [row['id'] for row in summary['results']] == ['one', 'two', 'three', 'four']
    assert summary['actual_document_requests'] == 4
    assert summary['maximum_concurrent_document_requests'] == jobs
    for row in summary['results']:
        folder = output/row['id']
        request_record = json.loads((folder/'request.json').read_text())
        response = json.loads((folder/'response.json').read_text())
        evidence = response['execution_evidence']
        assert request_record['request_id'] == evidence['execution_id']
        assert runner.digest((folder/'first-response.bin').read_bytes()) == evidence['raw_response_sha256']
        assert (folder/'runtime.log').read_text() == ''


def test_parallel_identity_failure_drains_inflight_and_blocks_unsent_images(observed_service, monkeypatch):
    args, sent, output = observed_service
    _four_images(args)
    capture, write_json = runner.http_recognition, runner.write_json
    barrier, first_recorded = threading.Barrier(2), threading.Event()
    def observe_write(path, value):
        write_json(path, value)
        if path == output/'one'/'result.json':
            first_recorded.set()
    def concurrent(raw, base_url, filename, timeout, **kwargs):
        barrier.wait(timeout=3)
        prediction, evidence = capture(raw, base_url, filename, timeout, **kwargs)
        if filename == 'one.png':
            prediction['graph_display_version'] = 'mismatched-version'
        else:
            assert first_recorded.wait(timeout=3)
        return prediction, evidence
    monkeypatch.setattr(runner, 'write_json', observe_write)
    monkeypatch.setattr(runner, 'http_recognition', concurrent)
    assert runner.main(args+['--jobs', '2']) == 2
    assert len(sent) == 2
    summary = json.loads((output/'summary.json').read_text())
    assert [row['capture_status'] for row in summary['results']] == ['fail', 'captured', 'blocked', 'blocked']
    assert summary['actual_document_requests'] == 2
    assert all(row['reason'] == 'first_response_pipeline_mismatch' for row in summary['results'][2:])


def test_transparent_original_bytes_are_uploaded_unchanged_despite_composite_hint(observed_service, monkeypatch):
    from PIL import Image, ImageDraw
    args, sent, output = observed_service
    manifest = Path(args[args.index('--manifest')+1])
    data = json.loads(manifest.read_text())
    original = Path(data['entries'][0]['path'])
    image = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
    ImageDraw.Draw(image).line((1, 1, 14, 14), fill=(0, 0, 0, 255), width=2)
    image.save(original)
    hint = original.with_name('white-composite.png')
    Image.alpha_composite(Image.new('RGBA', image.size, 'white'), image).convert('RGB').save(hint)
    raw = original.read_bytes()
    assert runner.digest(raw) != runner.digest(hint.read_bytes())
    for row in data['entries']:
        row.update(sha256=runner.digest(raw), composition_hint=str(hint))
    manifest.write_text(json.dumps(data))
    capture = runner.http_recognition
    def exact_original(actual, *args, **kwargs):
        assert actual == raw
        return capture(actual, *args, **kwargs)
    monkeypatch.setattr(runner, 'http_recognition', exact_original)
    assert runner.main(args+['--jobs', '2']) == 0
    assert original.read_bytes() == raw
    assert len(sent) == 2
    for name in ('one', 'two'):
        record = json.loads((output/name/'request.json').read_text())
        assert record['image_sha256'] == runner.digest(raw)
        assert record['original_path'] == str(original)


def test_parallel_direct_http_calls_use_distinct_openers(tmp_path, monkeypatch):
    import io
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image
    image = io.BytesIO()
    Image.new('RGB', (2, 2)).save(image, 'PNG')
    instances, barrier = [], threading.Barrier(2)
    class Response:
        status = 200
        headers = {'X-DMate-Runtime-Sha256': SHA}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, size):
            return b'{"graph_display_version":"test-version"}'
    class Opener:
        def open(self, req, timeout):
            barrier.wait(timeout=3)
            return Response()
    def fresh_opener(*args):
        value = Opener()
        instances.append(value)
        return value
    monkeypatch.setattr(runner.request, 'build_opener', fresh_opener)
    def upload(index):
        return runner.http_recognition(image.getvalue(), 'http://127.0.0.1:8081',
            'image.png', 10, execution_id=str(index), response_path=tmp_path/(str(index)+'.bin'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(upload, range(2)))
    assert len(instances) == len({id(value) for value in instances}) == 2
    assert {evidence['execution_id'] for _, evidence in results} == {'0', '1'}


@pytest.mark.parametrize('jobs', ['0', '5'])
def test_concurrency_limit_rejects_unsupported_values_before_requests(observed_service, jobs):
    args, sent, output = observed_service
    with pytest.raises(SystemExit):
        runner.main(args+['--jobs', jobs])
    assert sent == []
