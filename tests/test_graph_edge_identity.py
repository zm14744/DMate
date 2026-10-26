"""Edge-record IDs are independent of measured-candidate IDs.

Invented pixels exercise the receiving contract only. No corpus, gold graph,
model request or real-image recognition claim is involved.
"""
from __future__ import annotations

import copy
from io import BytesIO
import json

from PIL import Image, ImageDraw
import pytest

import graph_evidence_pipeline as pipeline
from graph_stroke_checks import StrokeEvidence
from image_evidence import analyze_document


STRAIGHT = [(60, 200), (340, 200)]


def scene(paths=None, extra_vertices=()):
    image = Image.new('RGB', (401, 401), 'white')
    draw = ImageDraw.Draw(image)
    for path in paths or [STRAIGHT]:
        draw.line(path, fill='black', width=3)
    points = [('a', 60, 200), ('b', 340, 200), *extra_vertices]
    for _, x, y in points:
        draw.ellipse((x-5, y-5, x+5, y+5), fill='black')
    inventory = {'coordinate_space': 'original_1000', 'graphs': [{
        'id': 'G', 'name': 'G', 'bbox': [0, 0, 1000, 1000],
        'directed': False, 'weighted': False, 'multigraph': False,
        'node_complete': True, 'vertices': [
            {'id': vid, 'label': vid, 'x': x*2.5, 'y': y*2.5}
            for vid, x, y in points]}]}
    return analyze_document(image), pipeline.decode_nodes(inventory)


def edge(eid, path=None, **fields):
    return {'id': eid, 'from': 'a', 'to': 'b', 'direction': 'undirected',
            'style': 'solid', 'path': [[x*2.5, y*2.5] for x, y in path or STRAIGHT],
            **fields}


def measured(document, graphs, cid='px_1', path=None):
    item = edge(cid, path)
    item['path'] = [[x/1000, y/1000] for x, y in item['path']]
    item['pixel_evidence'] = StrokeEvidence(document).inspect(item, graphs[0])
    assert item['pixel_evidence']['supported']
    return item


def apply(document, graphs, edges, candidates=(), verdicts=None):
    reads = [{'vertex': v['id'], 'complete': True, 'edge_ids': [
        e.get('id') for e in edges if isinstance(e, dict)
        and v['id'] in (e.get('from'), e.get('to'))]}
        for v in graphs[0]['vertices']]
    response = {'coordinate_space': 'original_1000', 'panels_complete': True,
                'graphs': [{'id': 'G', 'node_inventory_confirmed': True,
                            'inventory_complete': True, 'edges': copy.deepcopy(edges),
                            'reads': reads, 'candidate_verdicts': verdicts or []}]}
    return pipeline.apply_topology(response, graphs, {'G': list(candidates)}, document,
                                   panels_complete=True)[0][0]


@pytest.mark.parametrize('eid', ['e1', 'printed-edge', '边甲', 'new_legacy'])
def test_new_record_has_no_required_prefix_but_still_needs_pixels(eid):
    document, graphs = scene()
    result = apply(document, graphs, [edge(eid, edge_label='e₁')])
    assert result['complete']
    assert [(e['id'], e['status'], e['edge_label']) for e in result['edges']] == [
        (eid, 'accepted', 'e₁')]
    assert result['coverage_audit']['rejected_edges'] == []


def test_unprefixed_white_detour_is_retained_pending_without_forged_metadata():
    document, graphs = scene()
    raw = edge('e1', [(60, 200), (120, 80), (280, 80), (340, 200)],
               connector_evidence={'kind': 'outlined_arrow', 'valid': True})
    result = apply(document, graphs, [raw])
    assert len(result['edges']) == 1
    assert result['edges'][0]['status'] == 'pending'
    assert not result['complete']
    proof = next(e for e in result['edges'][0]['evidence'] if e['source'] == 'original_pixel_route')
    assert not proof['supported']
    assert 'connector_instance' not in proof
    assert result['coverage_audit']['rejected_edges'] == []


def test_explicit_candidate_reference_keeps_output_id_and_source_reads():
    document, graphs = scene()
    candidate = measured(document, graphs)
    result = apply(document, graphs, [edge('e1', candidate_id='px_1')],
                   [candidate], [['px_1', True]])
    assert result['complete']
    assert result['edges'][0]['id'] == 'e1'
    audit = result['coverage_audit']
    assert audit['candidate_bindings'] == {'e1': 'px_1'}
    assert [r['edge_ids'] for r in audit['reads']] == [['e1'], ['e1']]
    assert audit['candidate_inventory'][0]['pixel_evidence']['supported']
    assert audit['candidate_inventory'][0]['path'] == [[150., 500.], [850., 500.]]


def test_legacy_exact_candidate_id_still_binds():
    document, graphs = scene()
    candidate = measured(document, graphs)
    result = apply(document, graphs, [edge('px_1')], [candidate], [['px_1', True]])
    assert result['complete']
    assert result['coverage_audit']['candidate_bindings'] == {'px_1': 'px_1'}


def test_panel_transfer_keeps_original_candidate_provenance_with_output_alias():
    document, graphs = scene()
    candidate = measured(document, graphs)
    transferred = pipeline.transfer_id('G', 'px_1')
    fresh = {'id': 'panel_new_1', 'name': 'G', 'bbox': [0, 0, 1000, 1000],
             'directed': False, 'weighted': False, 'multigraph': False, 'node_complete': True,
             'vertices': [{'id': name, 'label': name, 'x': v['x']*1000, 'y': v['y']*1000,
                           'source': ['G', v['id']]}
                          for name, v in zip(('u', 'v'), graphs[0]['vertices'])]}
    response = {'coordinate_space': 'original_1000', 'panels_complete': True,
                'panel_revision': {'reason': 'Recheck the panel and retain both observed endpoints.',
                                   'replaces': ['G'], 'graphs': [fresh]},
                'graphs': [{'id': fresh['id'], 'node_inventory_confirmed': True,
                            'inventory_complete': True,
                            'edges': [edge('e1', candidate_id=transferred, **{'from': 'u', 'to': 'v'})],
                            'reads': [{'vertex': vid, 'complete': True, 'edge_ids': ['e1']}
                                      for vid in ('u', 'v')],
                            'candidate_verdicts': [[transferred, True]]}]}
    result = pipeline.apply_topology(response, graphs, {'G': [candidate]}, document,
                                      panels_complete=True)[0][0]
    assert result['complete']
    assert result['edges'][0]['id'] == 'e1'
    assert result['coverage_audit']['candidate_bindings'] == {'e1': transferred}
    provenance = next(e for e in result['edges'][0]['evidence'] if e['source'] == 'panel_candidate_transfer')
    assert provenance['original_candidate'] == ['G', 'px_1']


def test_visible_candidate_vote_does_not_invent_a_binding_for_another_id():
    document, graphs = scene()
    candidate = measured(document, graphs)
    result = apply(document, graphs, [edge('e1')], [candidate], [['px_1', True]])
    assert len(result['edges']) == 1
    assert not result['complete']
    assert 'candidate_verdict_edge_mismatch:px_1' in result['uncertain_edges']
    assert result['coverage_audit']['candidate_bindings'] == {}


def test_one_edge_reported_at_three_vertices_stays_incomplete_after_id_fix():
    document, graphs = scene(extra_vertices=[('c', 200, 80)])
    response = {'coordinate_space': 'original_1000', 'panels_complete': True,
                'graphs': [{'id': 'G', 'node_inventory_confirmed': True, 'inventory_complete': True,
                            'edges': [edge('e1')], 'candidate_verdicts': [],
                            'reads': [{'vertex': vid, 'complete': True, 'edge_ids': ['e1']}
                                      for vid in ('a', 'b', 'c')]}]}
    result = pipeline.apply_topology(response, graphs, {'G': []}, document,
                                      panels_complete=True)[0][0]
    assert len(result['edges']) == 1
    assert result['edges'][0]['status'] == 'accepted'
    assert not result['complete']
    assert 'incomplete_source_read:c' in result['uncertain_edges']
    assert result['coverage_audit']['reads'][2]['edge_ids'] == ['e1']


@pytest.mark.parametrize('record,reason', [
    (edge('e1', candidate_id='px_missing'), 'unknown_candidate_reference'),
    (edge('px_1', candidate_id='px_2'), 'conflicting_candidate_reference'),
    (edge('e1', candidate_id='px_1', to='c'), 'changed_candidate_endpoint_identity'),
])
def test_bad_candidate_reference_is_rejected_with_identifiable_audit(record, reason):
    document, graphs = scene(extra_vertices=[('c', 200, 80)])
    candidates = [measured(document, graphs, cid) for cid in ('px_1', 'px_2')]
    result = apply(document, graphs, [record], candidates, [['px_1', False], ['px_2', False]])
    assert not result['complete']
    assert result['edges'] == []
    rejected = result['coverage_audit']['rejected_edges']
    assert len(rejected) == 1
    assert rejected[0]['id'] == record['id']
    assert rejected[0]['from'] == record['from']
    assert rejected[0]['to'] == record['to']
    assert rejected[0]['reason'] == reason
    assert rejected[0]['path'] == record['path']


def test_one_candidate_cannot_be_claimed_by_two_record_ids():
    document, graphs = scene()
    candidate = measured(document, graphs)
    result = apply(document, graphs, [edge('e1', candidate_id='px_1'),
                                     edge('e2', candidate_id='px_1')],
                   [candidate], [['px_1', True]])
    assert not result['complete']
    assert [e['id'] for e in result['edges']] == ['e1']
    assert result['coverage_audit']['rejected_edges'][0]['reason'] == 'duplicate_candidate_reference'


def test_new_record_spelling_cannot_duplicate_one_visible_stroke():
    document, graphs = scene()
    result = apply(document, graphs, [edge('e1'), edge('e2')])
    assert len(result['edges']) == 2
    assert all(e['status'] == 'pending' for e in result['edges'])
    assert not result['complete']
    assert 'duplicate_ink_identities:e2' in result['uncertain_edges']


def test_same_endpoint_parallel_strokes_keep_distinct_candidate_references():
    paths = [[(60, 200), (120, 140), (280, 140), (340, 200)],
             [(60, 200), (120, 260), (280, 260), (340, 200)]]
    document, graphs = scene(paths)
    candidates = [measured(document, graphs, 'px_'+str(i+1), path)
                  for i, path in enumerate(paths)]
    records = [edge('e'+str(i+1), path, candidate_id='px_'+str(i+1))
               for i, path in enumerate(paths)]
    result = apply(document, graphs, records, candidates, [['px_1', True], ['px_2', True]])
    assert result['complete']
    assert result['multigraph']
    assert [(e['id'], e['status']) for e in result['edges']] == [('e1', 'accepted'), ('e2', 'accepted')]


def test_reference_to_supported_candidate_cannot_rescue_unrelated_white_route():
    document, graphs = scene()
    candidate = measured(document, graphs)
    result = apply(document, graphs, [edge('e1', [(60, 200), (120, 80), (280, 80), (340, 200)],
                                          candidate_id='px_1')], [candidate], [['px_1', True]])
    assert not result['complete']
    assert len(result['edges']) == 1
    assert result['edges'][0]['status'] == 'pending'


def test_rejected_records_remain_distinct_and_diagnostic_paths_are_bounded():
    document, graphs = scene()
    overlong = edge('bad_route', path=[(60+i, 200) for i in range(129)])
    nonfinite = edge('not_finite')
    nonfinite['path'][0][0] = float('nan')
    result = apply(document, graphs, [overlong, nonfinite, None])
    rejected = result['coverage_audit']['rejected_edges']
    assert len(rejected) == 3
    assert [r['index'] for r in rejected] == [0, 1, 2]
    assert rejected[0]['id'] == 'bad_route'
    assert rejected[0]['reason'] == 'invalid_edge_path'
    assert rejected[0]['path_point_count'] == 129
    assert rejected[0]['path_sampled'] is True
    assert len(rejected[0]['path']) == 16
    assert rejected[0]['path'][0] == overlong['path'][0]
    assert rejected[0]['path'][-1] == overlong['path'][-1]
    assert rejected[1]['reason'] == 'invalid_qwen_coordinate'
    assert rejected[2]['invalid_type'] == 'NoneType'
    json.dumps(result['coverage_audit'], allow_nan=False)


def test_first_grounding_keeps_raw_coordinates_and_never_rewrites_second_update(monkeypatch):
    document, graphs = scene()
    first_graph = copy.deepcopy(graphs[0])
    first_graph['bbox'] = [0, 0, 1000, 1000]
    for vertex in first_graph['vertices']:
        vertex['x'] *= 1000
        vertex['y'] *= 1000
    first_graph['vertices'][0]['x'] = 187.5  # The first visual response chose x=75px.
    first = {'coordinate_space': 'original_1000', 'panels_complete': True,
             'body_text': '', 'body_complete': True, 'graphs': [first_graph]}
    second = {'coordinate_space': 'original_1000', 'panels_complete': True,
              'text_review': {'text': '', 'complete': True, 'regions': []},
              'graphs': [{'id': 'G', 'node_inventory_confirmed': True, 'inventory_complete': True,
                          'node_updates': [{'id': 'a', 'x': 151.25, 'y': 500}],
                          'edges': [edge('e1', [(60.5, 200), (340, 200)])],
                          'reads': [{'vertex': vid, 'complete': True, 'edge_ids': ['e1']}
                                    for vid in ('a', 'b')],
                          'candidate_verdicts': []}]}
    grounded_calls = []

    def grounding_boundary(observed, inventory):
        assert observed.original.size == (401, 401)
        grounded_calls.append(copy.deepcopy(inventory))
        result = copy.deepcopy(inventory)
        result[0]['vertices'][0]['x'] = .15  # Deterministic CPU boundary, independent of the model update.
        result[0]['marker_grounding'] = {'status': 'grounded', 'grounded_vertices': 2,
                                         'retained_vertices': [], 'position_evidence_only': True}
        result[0]['node_position_evidence'] = [{'vertex': 'a', 'node_position': [.1875, .5],
                                               'pixel_position': [.15, .5]}]
        return result

    class VisualBoundary:
        name, model, retries = 'qwen', 'qwen3-vl-plus', 0

        def __init__(self):
            self.calls = []

        def __call__(self, prompt, images, budget):
            budget.take()
            self.calls.append({'prompt': prompt, 'images': images})
            return copy.deepcopy((first, second)[len(self.calls)-1])

    monkeypatch.setattr(pipeline, 'ground_nodes', grounding_boundary)
    monkeypatch.setattr(pipeline, 'collect_candidates', lambda doc, gs: ({'G': []}, []))
    stream = BytesIO()
    document.original.save(stream, format='PNG')
    visual = VisualBoundary()
    result = pipeline.recognize_evidence(stream.getvalue(), provider=visual)
    assert len(grounded_calls) == 1
    assert len(visual.calls) == 2
    request = json.loads(visual.calls[1]['prompt'].rsplit('\n', 1)[1])
    assert request['graphs'][0]['vertices'][0]['x'] == 150
    assert request['graphs'][0]['node_position_review']['position_evidence_only'] is True
    assert 'text_review_tiles' in request
    final = result['graphs'][0]
    assert final['complete']
    assert final['vertices'][0]['x'] == .15125  # The second visual correction wins.
    assert final['node_review']['observed_vertices'][0]['x'] == .1875
    assert final['node_position_evidence'][0]['pixel_position'] == [.15, .5]
    assert final['coverage_audit']['first_pass_marker_grounding']['status'] == 'grounded'
    assert result['pipeline_version'] == '2026-10-26-evidence-two-pass-v3'
