"""Synthetic replay-tool tests; never evidence that a private original was read."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from graph_schema import canonical_graph, display_graph
from graph_first_pass_eval import FRONTEND_CHECKS, prediction_digest
from scripts import verify_graph_first_pass_ui as ui
from scripts.benchmark_graph_first_pass import digest, write_json


def synthetic_prediction():
    graph = canonical_graph({'id': 'one', 'name': '<b>图&[1]</b>', 'bbox': [.1, .1, .9, .9],
        'directed': True, 'weighted': True, 'multigraph': True,
        'complete': False, 'node_complete': True,
        'vertices': [{'id': 'a', 'label': 'v₁', 'x': .2, 'y': .5},
                     {'id': 'b', 'label': '<img src=x onerror=alert(1)>', 'x': .8, 'y': .5}],
        'edges': [{'id': 'loop', 'from': 'a', 'to': 'a', 'direction': 'forward',
                   'weight': 0, 'edge_label': 'loop&[0]', 'style': 'solid', 'status': 'accepted'},
                  {'id': 'parallel_1', 'from': 'a', 'to': 'b', 'direction': 'forward',
                   'weight': 2, 'edge_label': 'alpha', 'style': 'dashed', 'status': 'accepted'},
                  {'id': 'parallel_2', 'from': 'a', 'to': 'b', 'direction': 'forward',
                   'weight': 3, 'edge_label': 'beta', 'style': 'solid', 'status': 'accepted'},
                  {'id': 'unknown', 'from': 'b', 'to': 'a', 'direction': 'unknown',
                   'weight': 4, 'edge_label': None, 'style': 'dotted', 'status': 'pending'}]})
    second = canonical_graph({'id': 'two', 'name': 'G2', 'bbox': [.1, .1, .9, .9],
        'directed': False, 'weighted': False, 'multigraph': False,
        'complete': True, 'node_complete': True,
        'vertices': [{'id': 'alone', 'label': '甲 乙', 'x': .5, 'y': .5, 'isolated_confirmed': True}], 'edges': []})
    return {'text': '求图的边数，并计算 \\(x^2+1\\)。', 'visual_text': 'PRIVATE_SOLVER_ONLY',
            'graph_structures': [graph, second], 'graph_display_data': [display_graph(graph), display_graph(second)],
            'recognition_status': 'partial', 'review': {'required': True, 'reasons': ['题干文字尚未核对完整。']},
            'warning': '题干文字尚未核对完整。',
            'diagnostics': {'text_evidence': {'complete': False}}}


def observation(prediction=None):
    prediction = prediction or synthetic_prediction()
    panels = ui.expected_panels(prediction)
    return {'panels': [{k: p[k] for k in ('heading', 'paragraphs', 'rows')} for p in panels], 'orphanGraphContent': [],
        'questionSemantic': '求图的边数，并计算 x^2+1。', 'expectedQuestion': '求图的边数，并计算 x^2+1。',
        'questionEmpty': False, 'notice': ui.expected_notice(prediction), 'noticeCount': 1,
        'responseUnchanged': True, 'originalSha256': 'a'*64, 'imageWidth': 320, 'imageHeight': 180,
        'imageBackground': 'rgb(255, 255, 255)', 'previewBlob': True, 'imageVisible': True,
        'readonly': True, 'graphDangerousElements': 0, 'graphErrorHandlers': 0,
        'invisibleElements': 0, 'math': [{'tex': 'x^2+1', 'svg': True, 'error': False, 'width': 40, 'height': 20}],
        'dialogWidth': 360, 'viewportWidth': 390}


def checked(observed, prediction=None):
    return {c['name']: c['status'] for c in ui.compare_observation(
        prediction or synthetic_prediction(), observed, {'sha256': 'a'*64}, (320, 180))}


def test_independent_projection_catches_one_edge_swap_with_same_counts():
    prediction = synthetic_prediction()
    assert ui.public_projection_issues(prediction) == []
    prediction['graph_display_data'][0]['edges'][1]['to'] = 'a'
    assert ui.public_projection_issues(prediction) == ['canonical_public_projection_changed']


def test_exact_rendering_contract_checks_every_field_and_panel():
    assert set(checked(observation()).values()) == {'pass'}
    observed = observation()
    observed['panels'].reverse()
    assert checked(observed)['panels'] == 'fail'


def test_unassigned_internal_prose_before_cards_is_not_ignored():
    observed = observation()
    observed['orphanGraphContent'] = ['PRIVATE_SOLVER_ONLY']
    assert checked(observed)['panels'] == 'fail'


@pytest.mark.parametrize('old,new,dimension', [
    ('v_{1} → v_{1}', 'v_{1} → <img src=x onerror=alert(1)>', 'self_loops'),
    (' → ', ' — ', 'directions'),
    ('权值：0', '权值：1', 'weights'),
    ('边名：loop&[0]', '边名：changed', 'edge_labels'),
    ('同端点共 2 条', '同端点共 1 条', 'multiplicity'),
    ('虚线', '点线', 'styles'),
    ('方向未确定', '', 'directions'),
    ('待确认', '', 'edge_instances'),
])
def test_equal_row_counts_do_not_hide_changed_edge_fields(old, new, dimension):
    observed = observation()
    changed = False
    for panel in observed['panels']:
        for index, row in enumerate(panel['rows']):
            if old in row:
                panel['rows'][index] = row.replace(old, new, 1)
                changed = True
                break
        if changed:
            break
    assert changed, 'Synthetic counterexample must really mutate an observed row'
    assert checked(observed)[dimension] == 'fail'


def test_internal_spaces_in_a_literal_label_cannot_disappear():
    observed = observation()
    observed['panels'][1]['paragraphs'] = [text.replace('甲 乙', '甲乙') for text in observed['panels'][1]['paragraphs']]
    assert checked(observed)['vertex_labels'] == 'fail'


@pytest.mark.parametrize('field,value,dimension', [
    ('notice', '', 'status'), ('originalSha256', 'b'*64, 'original_preview'),
    ('imageBackground', 'rgba(0, 0, 0, 0)', 'original_preview'),
    ('questionSemantic', '删去题干', 'text'), ('responseUnchanged', False, 'response_immutable'),
    ('graphDangerousElements', 1, 'no_markup_injection'), ('invisibleElements', 1, 'readonly'),
])
def test_missing_text_status_original_or_visibility_fails(field, value, dimension):
    observed = observation()
    observed[field] = value
    assert checked(observed)[dimension] == 'fail'


def make_frozen_run(folder, snapshot, *, count=1):
    folder.mkdir(parents=True, mode=0o700)
    images, references, ids = [], [], []
    manifest_path = folder.parent/(folder.name+'_manifest.json')
    for index in range(count):
        cid = 'synthetic_'+str(index+1)
        ids.append(cid)
        path = folder.parent/(folder.name+'_'+cid+'.png')
        image = Image.new('RGBA', (320, 180), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.text((15, 15), 'SYNTHETIC RUNNER TEST ONLY', fill='black')
        draw.line((60, 100, 260, 100), fill='black', width=3)
        image.save(path)
        images.append({'id': cid, 'path': str(path), 'sha256': digest(path.read_bytes()), 'width': 320, 'height': 180})
        references.append(None)  # Synthetic rendering does not manufacture gold.
    write_json(manifest_path, {'images': images})
    write_json(folder/'run.json', {'mode': 'local', 'check_only': False, 'kind': 'synthetic_runner_validation', 'fixture_only': True,
        'manifest_sha256': digest(manifest_path.read_bytes()), 'selected_image_ids': ids,
        'original_manifest_count': count, 'source_snapshot': snapshot,
        'policy': {'document_attempts_per_image': 1, 'automatic_retry': False, 'select_best_result': False}})
    write_json(folder/'summary.json', {'full_corpus_selected': True, 'images_requested': count,
        'actual_document_requests': count, 'results': [{'id': cid, 'status': 'not_certified'} for cid in ids]})
    write_json(folder/'references.json', {'evaluation_only': True, 'production_lookup_forbidden': True, 'records': references})
    for index, row in enumerate(images):
        prediction = synthetic_prediction()
        if index:
            prediction.update(text='', graph_structures=[], graph_display_data=[], visual_text='',
                              recognition_status='not_graph', review={'required': False, 'reasons': []}, warning=None,
                              diagnostics={'text_evidence': {'complete': True}})
        case = folder/row['id']
        case.mkdir()
        evidence = {'mode': 'local', 'execution_id': 'synthetic-execution-'+row['id'], 'is_live': False,
            'document_requests': 1, 'source_unchanged': True, 'source_snapshot': snapshot,
            'image_sha256': row['sha256'], 'prediction_sha256': prediction_digest(prediction)}
        write_json(case/'response.json', {'prediction': prediction, 'execution_evidence': evidence})
        write_json(case/'result.json', {'id': row['id'], 'actual_document_requests': 1, 'status': 'not_certified'})
    return manifest_path


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    snapshot = {'git_sha': 'a'*40, 'dirty': True, 'source_tree_sha256': 'b'*64}
    monkeypatch.setattr(ui, 'source_snapshot', lambda: snapshot)
    folder = tmp_path/'private_run'
    manifest = make_frozen_run(folder, snapshot)
    return folder, manifest, snapshot


def test_complete_freeze_loads_without_keys_or_ocr_imports(frozen):
    folder, manifest, _ = frozen
    loaded = ui.load_frozen_run(folder, manifest)
    assert loaded['fixture_only'] is True
    assert ui.originals_unchanged(loaded)


@pytest.mark.parametrize('target,mutate,error', [
    ('run.json', lambda d: d.update(check_only=True), 'preflight'),
    ('run.json', lambda d: d.update(mode='unrecognized_mode'), 'execution mode'),
    ('synthetic_1/response.json', lambda d: d['execution_evidence'].update(mode='http'), 'execution mode differs'),
    ('run.json', lambda d: d.update(selected_image_ids=[]), 'complete manifest'),
    ('summary.json', lambda d: d.update(actual_document_requests=0), 'complete manifest'),
    ('run.json', lambda d: d['source_snapshot'].update(dirty=False), 'Current source differs'),
    ('synthetic_1/response.json', lambda d: d['prediction'].update(text='later replacement'), 'not bound'),
    ('synthetic_1/response.json', lambda d: d['execution_evidence'].update(source_unchanged=False), 'not bound'),
])
def test_unbound_or_incomplete_run_cannot_start_a_browser(frozen, target, mutate, error):
    folder, manifest, _ = frozen
    path = folder/target
    data = ui.read_json(path)
    mutate(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=error):
        ui.load_frozen_run(folder, manifest)


def test_existing_replay_is_not_replaced_or_selected(frozen):
    folder, manifest, _ = frozen
    (folder/'frontend').mkdir()
    with pytest.raises(ValueError, match='already has'):
        ui.load_frozen_run(folder, manifest)


def test_missing_public_cache_never_downloads(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'send', lambda *a, **k: pytest.fail('Network is forbidden'))
    with pytest.raises(ValueError, match='absent'):
        ui._cached_asset('https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.umd.js', tmp_path)
    assert ui._cached_asset('https://unapproved.example/payload.js', tmp_path) is None


@pytest.mark.parametrize('inject_forbidden_request', [False, True])
def test_actual_chromium_replays_only_synthetic_frozen_first_results(monkeypatch, inject_forbidden_request):
    destination = os.environ.get('DMATE_UI_REPLAY_TEST_OUTPUT')
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE')
    cache = os.environ.get('DMATE_BROWSER_CDN_CACHE')
    if not destination or not executable or not cache:
        pytest.skip('Actual replay not run: configure browser, private synthetic output and verified public cache')
    pytest.importorskip('playwright.sync_api')
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'send', lambda *a, **k: pytest.fail('No external HTTP is permitted'))
    folder = Path(destination).resolve()/('blocked_requests' if inject_forbidden_request else 'ordinary')
    assert not folder.exists(), 'Use a new private synthetic run; do not replace observations'
    assert ROOT_NOT_IN(folder)
    if inject_forbidden_request:
        monkeypatch.setattr(ui, 'OBSERVE_JS', ui.OBSERVE_JS.replace(
            "const graph=document.querySelector", "await fetch('/ocr', {method:'POST',body:'SYNTHETIC-BLOCK-PROBE'}).catch(()=>{});\n"
            "await fetch('https://unapproved.invalid/SYNTHETIC-BLOCK-PROBE').catch(()=>{});\n"
            "const graph=document.querySelector", 1))
    manifest = make_frozen_run(folder, ui.source_snapshot(), count=2)
    loaded = ui.load_frozen_run(folder, manifest)
    summary = ui.replay(loaded, Path(executable), Path(cache))
    assert summary['kind'] == 'synthetic_runner_validation' and summary['fixture_only'] is True
    assert summary['certified_passes'] == 0 and summary['status'] != 'pass'
    assert summary['application_status'] == 'not_run' and summary['application_certified_passes'] == 0
    assert summary['execution_scope'] == 'local_pipeline'
    assert summary['frontend_scope'] == 'response_dialog_replay'
    assert summary['frontend_contract_passes'] == (0 if inject_forbidden_request else 2)
    assert summary['ocr_requests'] == (4 if inject_forbidden_request else 0)
    assert summary['external_network_requests'] == summary['frontend_replay_document_requests'] == 0
    assert summary['original_files_unchanged'] is True
    for case in loaded['cases']:
        proof = ui.read_json(case['folder']/'frontend_evidence.json')
        assert proof['status'] == ('fail' if inject_forbidden_request else 'pass'), proof
        assert proof['application_status'] == 'not_run'
        assert proof['certification_scope'] == 'local_pipeline_and_ui_replay'
        assert proof['execution_id'] == case['execution']['execution_id']
        assert proof['source_tree_sha256'] == loaded['source']['source_tree_sha256']
        assert proof['prediction_sha256'] == prediction_digest(case['prediction'])
        assert {c['name'] for c in proof['checks']} == set(FRONTEND_CHECKS)


def ROOT_NOT_IN(path):
    return path != ui.ROOT and ui.ROOT not in path.parents
