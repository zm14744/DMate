"""Review identity and completeness regressions, not image accuracy claims."""
import copy
import io
import json
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from graph_staged import recognize_staged
from graph_relation import recover_relations


def run_review(decisions, *, pixel_only=False):
    image = Image.new('RGB', (600, 400), 'white')
    ImageDraw.Draw(image).line([(60, 200), (540, 200)], fill='black', width=3)
    data = io.BytesIO()
    image.save(data, format='PNG')
    route = [[.1, .5], [.9, .5]]
    calls = []

    def ask(prompt, images, budget):
        budget.take()
        calls.append(prompt)
        if 'NODE 阶段' in prompt:
            return {'graphs': [{'id': 'G', 'directed': False, 'weighted': False,
                'multigraph': False, 'node_complete': True,
                'vertices': [{'id': 'a', 'x': .1, 'y': .5},
                             {'id': 'b', 'x': .9, 'y': .5}]}]}
        if 'EDGE 阶段' in prompt:
            edges = [] if pixel_only else [{'id': 'r', 'graph_id': 'G',
                'from': 'a', 'to': 'b', 'path': route, 'direction': 'undirected'}]
            return {'edges': edges, 'reads': [{'graph_id': 'G', 'vertex': v,
                'complete': True, 'edge_ids': [] if pixel_only else ['r']}
                for v in ('a', 'b')]}
        jobs = json.loads(prompt[prompt.index('{"requests":'):])['requests']
        assert {e['id'] for e in jobs[0]['candidates']} == {
            'pixel_1' if pixel_only else 'e1'}
        return {'graphs': [{'graph_id': 'G', 'inventory_complete': True,
                            'decisions': copy.deepcopy(decisions)}]}

    def traced(raw, result):
        # A measured trace stops short of the node; review can supply the
        # independently ink-checked full path, keeping the same candidate ID.
        path = [[.2, .5], [.8, .5]] if pixel_only else route
        result['line_path_evidence'] = [{'id': 'G', 'paths': [{'from': 'a',
            'to': 'b', 'path': path, 'score': 1., 'method': 'test_trace'}]}]
        return result

    with patch('graph_staged.refine_node_positions', side_effect=lambda image, g, **kw: g), \
         patch('graph_line_tracer.attach_line_evidence', side_effect=traced):
        result = recognize_staged(data.getvalue(), call=ask)
    assert len(calls) == 3
    return result['graphs'][0]


def test_review_can_correct_a_pixel_only_candidate_without_losing_its_id():
    actual = run_review([{'id': 'pixel_1', 'visible': True,
        'direction': 'undirected', 'style': 'solid',
        'path': [[.1, .5], [.9, .5]]}], pixel_only=True)
    assert len(actual['edges']) == 1
    edge = actual['edges'][0]
    assert (edge['id'], edge['from'], edge['to']) == ('pixel_1', 'a', 'b')
    assert edge['status'] == 'accepted'
    assert edge['path'] == [[.1, .5], [.9, .5]]
    assert any(e.get('source') == 'qwen_review_route_verified' for e in edge['evidence'])


@pytest.mark.parametrize('decisions', [
    [{'id': 'e1'}],
    [{'id': 'e1', 'visible': None}],
    [{'id': 'e1', 'visible': 1, 'direction': 'undirected'}],
    [{'id': 'e1', 'visible': True}],
    [{'id': 'e1', 'visible': True, 'direction': 'sideways'}],
    [{'id': 'e1', 'visible': False},
     {'id': 'e1', 'visible': True, 'direction': 'undirected'}],
    [{'id': 'e1', 'visible': True, 'direction': 'undirected'},
     {'id': 'foreign', 'visible': False}],
])
def test_an_id_without_one_valid_explicit_decision_cannot_certify_inventory(decisions):
    actual = run_review(decisions)
    assert not actual['inventory_reviewed']
    assert not actual['complete']


def test_valid_review_can_still_confirm_the_full_inventory():
    actual = run_review([{'id': 'e1', 'visible': True, 'direction': 'undirected'}])
    assert actual['inventory_reviewed'] and actual['complete']


def test_frozen_pixel_candidate_keeps_its_confidence_and_arrow_conflict():
    graph = {'id': 'G', 'directed': True, 'weighted': False, 'multigraph': False,
        'vertices': [{'id': 'a', 'x': .1, 'y': .5}, {'id': 'b', 'x': .9, 'y': .5}],
        'edges': []}
    trace = {'from': 'a', 'to': 'b', 'path': [[.1, .5], [.9, .5]], 'score': 1.,
             'arrow_candidate': {'from': 'b', 'to': 'a', 'score': .9}}
    initial = recover_relations(graph, [trace])
    graph['edges'] = initial['_candidates']
    evidence = initial['_candidate_evidence']
    pending = recover_relations(graph, [], candidate_evidence=evidence)
    assert pending['edges'][0]['status'] == 'pending'
    assert pending['relation_audit'][0]['score'] == initial['relation_audit'][0]['score']
    conflict = recover_relations(graph, [], candidate_evidence=evidence,
        review={'pixel_1': {'visible': True, 'direction': 'forward'}})
    assert conflict['edges'][0]['direction'] == 'unknown'
    resolved = recover_relations(graph, [], candidate_evidence=evidence,
        review={'pixel_1': {'visible': True, 'direction': 'reverse'}})
    assert (resolved['edges'][0]['from'], resolved['edges'][0]['to']) == ('b', 'a')
    assert resolved['edges'][0]['status'] == 'accepted'


@pytest.mark.parametrize('confirm_arc', [False, True])
@pytest.mark.parametrize('path_kind', ['short', 'measured', 'unverified'])
def test_spare_review_checks_all_parallel_ids_against_original_ink(confirm_arc, path_kind):
    straight = [[.1, .5], [.9, .5]]
    arc = [[.1, .5], [.5, .2], [.9, .5]]
    image = Image.new('RGB', (600, 400), 'white')
    for route in (straight, arc):
        ImageDraw.Draw(image).line([(round(x*599), round(y*399)) for x,y in route],
                                  fill='black', width=3)
    data = io.BytesIO(); image.save(data, format='PNG')
    calls = []

    def ask(prompt, images, budget):
        budget.take(); calls.append(prompt)
        if 'NODE 阶段' in prompt:
            return {'graphs': [{'id': 'G', 'directed': False, 'weighted': False,
                'multigraph': True, 'node_complete': True,
                'vertices': [{'id': 'a', 'x': .1, 'y': .5}, {'id': 'b', 'x': .9, 'y': .5}]}]}
        if 'EDGE 阶段' in prompt:
            return {'edges': [{'id': 'r', 'graph_id': 'G', 'from': 'a', 'to': 'b',
                'path': straight, 'direction': 'undirected'}],
                'reads': [{'graph_id': 'G', 'vertex': v, 'complete': True,
                           'edge_ids': ['r']} for v in ('a', 'b')]}
        if len(calls) == 3:
            return {'graphs': [{'graph_id': 'G', 'inventory_complete': False,
                'decisions': [{'id': 'e1', 'visible': True, 'direction': 'undirected'},
                              {'id': 'pixel_1', 'visible': False}]}]}
        assert len(calls) == 4 and len(images) == 2
        payload = json.loads(prompt[prompt.index('{"graph_id":'):])
        assert {e['id'] for e in payload['candidates']} == {'e1', 'pixel_1'}
        assert all((e['from'], e['to']) == ('a', 'b') for e in payload['candidates'])
        reviewed_arc = arc
        if path_kind == 'measured':
            reviewed_arc = [[a[0]+(b[0]-a[0])*i/5, a[1]+(b[1]-a[1])*i/5]
                            for a,b in zip(arc,arc[1:]) for i in range(5)] + [arc[-1]]
        elif path_kind == 'unverified':
            reviewed_arc = [[.1, .5], [.5, .8], [.9, .5]]
        return {'decisions': [{'id': 'e1', 'visible': True, 'direction': 'undirected',
                              'path': straight, 'style': 'solid'},
                             {'id': 'pixel_1', 'visible': confirm_arc,
                              'direction': 'undirected', 'path': reviewed_arc, 'style': 'solid'}]}

    def traced(raw, result):
        result['line_path_evidence'] = [{'id': 'G', 'paths': [{'from': 'a', 'to': 'b',
            'path': arc, 'score': .95, 'method': 'test_arc'}]}]
        return result

    with patch('graph_staged.refine_node_positions', side_effect=lambda image, g, **kw: g), \
         patch('graph_line_tracer.attach_line_evidence', side_effect=traced):
        result = recognize_staged(data.getvalue(), call=ask)
    assert len(calls) == 4 and result['calls_remaining'] == 3
    assert 'focused_stroke_review' in result['diagnostics']
    graph = result['graphs'][0]
    accepted_arc = confirm_arc and path_kind != 'unverified'
    assert {e['id'] for e in graph['edges']} == ({'e1', 'pixel_1'} if accepted_arc else {'e1'})
    assert all(e['status'] == 'accepted' for e in graph['edges'])
    assert not graph['complete']  # Local pair review cannot certify the whole graph.
