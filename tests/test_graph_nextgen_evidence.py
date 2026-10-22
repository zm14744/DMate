"""Evidence regressions; synthetic mechanisms, never original-image accuracy."""
import copy

import numpy as np
import pytest

from graph_line_tracer import _corridor_hits
from graph_relation import recover_relations
from graph_schema import canonical_graph, describe_graphs
from graph_staged import merge_node_reads


def record(edges=(), **values):
    return {'id': 'G', 'name': 'G', 'directed': False, 'weighted': False,
            'multigraph': True, 'node_complete': True, 'vertices': [
                {'id': 'a', 'label': 'A', 'x': .1, 'y': .5},
                {'id': 'b', 'label': 'B', 'x': .9, 'y': .5}],
            'edges': list(edges), **values}


def edge(**values):
    return {'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'undirected',
            'path': [[.1, .5], [.9, .5]], 'weight': None, **values}


def test_outside_curve_corridor_does_not_wrap_or_crash():
    ink = np.ones((297, 481), dtype=bool)
    # Rounding + the two-pixel corridor used to produce row 297.
    actual = _corridor_hits(ink, np.array([20., 20., 20.]),
                            np.array([296.8, -3., 150.]), 0., 1.)
    assert actual.tolist() == [True, False, True]
    assert not _corridor_hits(ink, np.array([-3.]), np.array([20.]), 0., 1.)[0]


def test_one_endpoint_three_close_parallel_observations_keep_three_ids():
    edges = [edge(path=[[.1, .5], [.5, .5 + d], [.9, .5]])
             for d in (-.001, 0., .001)]
    actual = merge_node_reads(record(), [{'vertex': 'a', 'complete': True, 'edges': edges}])
    assert len(actual['edges']) == 3
    assert len({e['id'] for e in actual['edges']}) == 3
    assert actual['node_complete'] is False


def test_reciprocal_parallel_reads_match_each_observation_at_most_once():
    # Same coarse path is not enough to distinguish parallel traces, so keep
    # the ambiguity rather than collapsing a three-edge observation to one.
    triple = [edge(edge_label=f'k{i}') for i in range(3)]
    backward = [dict(e, **{'from': 'b', 'to': 'a'}) for e in triple]
    actual = merge_node_reads(record(), [
        {'vertex': 'a', 'complete': True, 'edges': triple},
        {'vertex': 'b', 'complete': True, 'edges': backward}])
    assert len(actual['edges']) == 3 and actual['node_complete']
    assert all(len(e['evidence']) == 2 for e in actual['edges'])


def test_missing_weight_in_reciprocal_read_does_not_delete_seen_weight():
    actual = merge_node_reads(record(weighted=True), [
        {'vertex': 'a', 'edges': [edge(weight=6)]},
        {'vertex': 'b', 'edges': [edge()]}])
    assert actual['edges'][0]['weight'] == 6


def test_conflicting_weights_are_preserved_as_internal_observations():
    actual = merge_node_reads(record(weighted=True), [
        {'vertex': 'a', 'edges': [edge(weight=6)]},
        {'vertex': 'b', 'edges': [edge(weight=8)]}])
    assert actual['edges'][0]['weight'] is None
    assert {'source': 'attribute_conflict', 'field': 'weight', 'values': [6, 8]} in actual['edges'][0]['evidence']


def test_pixel_arrow_is_visible_to_review_without_becoming_final_direction():
    trace = {'from': 'a', 'to': 'b', 'path': [[.1, .5], [.9, .5]], 'score': .98,
             'arrow_candidate': {'from': 'b', 'to': 'a', 'score': .8, 'candidate_only': True}}
    actual = recover_relations(record([edge(direction='forward')], directed=True), [trace])
    assert actual['edges'][0]['direction'] == 'unknown'
    assert any(v.get('source') == 'arrow_pixels' for v in actual['_candidates'][0]['evidence'])
    assert actual['complete'] is False


def test_arrow_like_ink_cannot_make_an_undirected_edge_unknown():
    trace = {'from': 'a', 'to': 'b', 'path': [[.1, .5], [.9, .5]],
             'score': .98, 'arrow_ambiguous': True}
    actual = recover_relations(record([edge()]), [trace])
    assert actual['edges'][0]['direction'] == 'undirected'


def test_description_uses_each_direction_weight_and_independent_id():
    actual = canonical_graph(record([
        edge(direction='unknown', weight=6),
        edge(id='e2', **{'from': 'b', 'to': 'a', 'direction': 'forward', 'weight': 6})],
        directed=True, weighted=True))
    text = describe_graphs([actual])
    assert 'A?B' in text and 'B→A' in text
    assert 'A→B' not in text
    assert 'e1:' in text and 'e2:' in text and text.count('权值 6') == 2
    assert text.startswith('【图形结构待核对】')


def test_describing_partial_inventory_does_not_invent_isolated_vertices():
    g = canonical_graph(record())
    before = copy.deepcopy(g)
    assert '孤立顶点' not in describe_graphs([g])
    assert g == before


def test_review_batches_cover_fourth_panel_and_scope_edge_ids():
    import io
    import json
    from unittest.mock import patch
    from PIL import Image
    from graph_staged import recognize_staged
    image = io.BytesIO()
    Image.new('RGB', (100, 100), 'white').save(image, format='PNG')
    panels = [record(id=f'G{i}', name=f'G{i}') for i in range(1, 5)]
    review_ids = []
    def ask(prompt, images, budget):
        if 'NODE 阶段' in prompt:
            return {'graphs': panels}
        jobs = json.loads(prompt[prompt.index('{"requests":'):])['requests']
        if 'EDGE 阶段' in prompt:
            return {'reads': [{'graph_id': j['graph']['id'], 'vertex': v,
                               'complete': True, 'edges': [edge()]}
                              for j in jobs for v in j['focus_vertices']]}
        review_ids.extend(j['graph_id'] for j in jobs)
        assert all(j['directed'] is False and j['weighted'] is False for j in jobs)
        return {'graphs': [{'graph_id': j['graph_id'], 'inventory_complete': True,
                            'decisions': [{'id': c['id'], 'visible': True, 'direction': 'undirected'}
                                          for c in j['candidates']]} for j in jobs]}
    with patch('graph_line_tracer.attach_line_evidence', side_effect=lambda raw, result: result):
        actual = recognize_staged(image.getvalue(), call=ask)
    assert review_ids == ['G1', 'G2', 'G3', 'G4']
    assert len(actual['graphs']) == 4
    assert all(g['complete'] for g in actual['graphs'])


def test_dense_multi_panel_reads_use_smaller_batches_within_remote_budget():
    import io
    import json
    from PIL import Image
    from unittest.mock import patch
    from graph_staged import recognize_staged
    image=io.BytesIO();Image.new('RGB',(160,100),'white').save(image,format='PNG')
    panels=[record(id=f'G{i}',vertices=[{'id':f'v{k}','x':k/10,'y':.5}
                                     for k in range(1,7)]) for i in range(1,4)]
    batches=[]
    def ask(prompt,images,budget):
        budget.take()
        if 'NODE 阶段' in prompt:return {'graphs':panels}
        assert 'EDGE 阶段' in prompt
        jobs=json.loads(prompt[prompt.index('{"requests":'):])['requests']
        vertices=[(j['graph']['id'],v) for j in jobs for v in j['focus_vertices']]
        batches.append(vertices)
        return {'reads':[{'graph_id':gid,'vertex':v,'complete':True,'edges':[]} for gid,v in vertices]}
    with patch('graph_line_tracer.attach_line_evidence',side_effect=lambda raw,result:result):
        actual=recognize_staged(image.getvalue(),call=ask)
    assert [len(batch) for batch in batches]==[6,6,6]
    assert len({vertex for batch in batches for vertex in batch})==18
    assert actual['calls_remaining']==3 and not actual['diagnostics']


def test_review_grouping_keeps_every_candidate_identity_without_asserting_multiplicity():
    from graph_staged import _review_job
    candidates=[edge(),edge(id='pixel_1'),edge(id='e2',**{'from':'b','to':'a'})]
    before=copy.deepcopy(candidates)
    job=_review_job(record(directed=True),candidates)
    assert job['endpoint_groups']==[{'vertices':['a','b'],'candidate_ids':['e1','pixel_1','e2']}]
    assert 'multiplicity' not in job['endpoint_groups'][0]
    assert candidates==before and job['directed'] is True


def test_incomplete_json_envelope_never_salvages_a_single_inner_edge():
    from unittest.mock import patch
    from graph_staged import _call, Budget
    from vision_provider import VisionError
    result={'choices':[{'message':{'content':'{"edges":[{"id":"r1","from":"a","to":"b"}'},
                        'finish_reason':'stop'}]}
    with patch('ai.API_KEY','test-only'),patch('ai.VISION_ENABLED',True),patch(
            'ai._request_qwen_completion',return_value=(200,'',result)) as request:
        with pytest.raises(VisionError,match='invalid_output'): _call('Return JSON',[],Budget())
    assert request.call_args.args[0]['response_format']=={'type':'json_object'}


def test_auxiliary_node_id_map_keeps_original_pixels_unchanged():
    from PIL import Image
    from graph_staged import _node_id_context
    image=Image.new('RGB',(160,100),'white')
    pixels=image.tobytes()
    value=_node_id_context(image,[record()])
    assert value.startswith('data:image/jpeg;base64,')
    assert image.tobytes()==pixels


def test_path_to_a_different_vertex_cannot_be_accepted_by_generic_review():
    g=record([edge(path=[[.1,.5],[.5,.1]])])
    actual=recover_relations(g,[],review={'e1':{'visible':True,'direction':'undirected'}})
    assert actual['edges']==[]
    assert actual['relation_audit'][0]['endpoint_mismatch']


def test_coarse_path_coordinates_align_to_fixed_nodes_without_changing_edge():
    value=edge(path=[[.17,.5],[.5,.5],[.83,.5]])
    result=merge_node_reads(record(),[{'vertex':'a','edges':[value]}])
    actual=result['edges'][0]
    assert (actual['from'],actual['to'])==('a','b')
    assert actual['path']==[[.1,.5],[.5,.5],[.9,.5]]
    assert any(e.get('source')=='endpoint_alignment' for e in actual['evidence'])


def test_route_interior_moves_with_coarse_endpoint_alignment():
    value=edge(path=[[.17,.57],[.5,.57],[.83,.57]])
    result=merge_node_reads(record(),[{'vertex':'a','edges':[value]}])
    actual=result['edges'][0]
    assert actual['path'][1]==pytest.approx([.5,.5])
    original=next(e for e in actual['evidence'] if e.get('source')=='endpoint_alignment')
    assert original['observed_path']==value['path']


def test_graph_type_and_edge_direction_conflict_is_not_accepted():
    result=canonical_graph(record([edge(direction='forward',status='accepted')],complete=True))
    assert result['edges'][0]['direction']=='unknown'
    assert result['edges'][0]['status']=='pending' and not result['complete']
    assert any(e.get('source')=='graph_direction_conflict' for e in result['edges'][0]['evidence'])


@pytest.mark.parametrize('invalid_review', [False, True])
def test_marker_inventory_disagreement_requires_visual_node_review(invalid_review):
    import io
    import json
    from PIL import Image
    from unittest.mock import patch
    from graph_staged import recognize_staged
    image=io.BytesIO();Image.new('RGB',(160,100),'white').save(image,format='PNG')
    initial=record(bbox=[0,0,1,1]);node_calls=[]
    def refine(image, graphs, *, candidate_sink=None):
        if candidate_sink is not None:
            candidate_sink.extend([{'x':.1,'y':.5},{'x':.9,'y':.5},{'x':.5,'y':.1}])
        return graphs
    def ask(prompt,images,budget):
        if 'NODE 阶段' in prompt:
            node_calls.append(prompt)
            if len(node_calls)==1:return {'graphs':[initial]}
            payload=json.loads(prompt[prompt.index('{"current_graphs":'):])
            # Pixel candidates do not silently become vertices before review.
            assert len(payload['current_graphs'][0]['vertices'])==2
            revised=copy.deepcopy(initial)
            if invalid_review:revised['id']='wrong_panel'
            else:revised['vertices'].append({'id':'c','label':'C','x':.5,'y':.1})
            return {'graphs':[revised]}
        jobs=json.loads(prompt[prompt.index('{"requests":'):])['requests']
        if 'EDGE 阶段' in prompt:
            return {'reads':[{'graph_id':'G','vertex':v,'complete':True,
                              'edges':[edge()] if v in ('a','b') else []}
                             for j in jobs for v in j['focus_vertices']]}
        return {'graphs':[{'graph_id':'G','inventory_complete':True,
                           'decisions':[{'id':c['id'],'visible':True,'direction':'undirected'}
                                        for j in jobs for c in j['candidates']]}]}
    with patch('graph_staged.refine_node_positions',side_effect=refine),patch(
            'graph_line_tracer.attach_line_evidence',side_effect=lambda raw,result:result):
        actual=recognize_staged(image.getvalue(),call=ask)
    g=actual['graphs'][0]
    assert len(node_calls)==2 and len(g['vertices'])==(2 if invalid_review else 3)
    if invalid_review:
        assert not g['node_complete'] and not g['complete']
        assert g['node_review']['status']=='failed'
        assert 'node_inventory_review_failed' in actual['diagnostics']
    else:
        assert g['node_review']=={'initial_vertex_count':2,'reviewed_vertex_count':3}
        assert 'node_inventory_rechecked' in actual['diagnostics']


def test_single_graph_arrow_conflict_gets_second_focused_visual_review():
    import io
    import json
    from PIL import Image
    from unittest.mock import patch
    from graph_staged import recognize_staged
    image=io.BytesIO();Image.new('RGB',(160,100),'white').save(image,format='PNG')
    g=record(directed=True);calls=[]
    def ask(prompt,images,budget):
        calls.append(prompt)
        if 'NODE 阶段' in prompt:return {'graphs':[g]}
        if 'EDGE 阶段' in prompt:
            return {'reads':[{'graph_id':'G','vertex':v,'complete':True,'edges':[edge(direction='forward')]}
                             for v in ('a','b')]}
        if len(calls)==3:
            return {'decisions':[{'id':'e1','visible':True,'direction':'forward'}],'inventory_complete':True}
        assert len(images)==2 and '局部裁图' in prompt
        return {'decisions':[{'id':'e1','visible':True,'direction':'reverse'}]}
    def trace(raw,result):
        result['line_path_evidence']=[{'id':'G','paths':[
            {'from':'a','to':'b','path':[[.1,.5],[.9,.5]],'score':1.,
             'arrow_candidate':{'from':'b','to':'a','score':.8,'candidate_only':True}}]}]
        return result
    with patch('graph_line_tracer.attach_line_evidence',side_effect=trace):
        actual=recognize_staged(image.getvalue(),call=ask)['graphs'][0]
    assert len(calls)==4
    assert (actual['edges'][0]['from'],actual['edges'][0]['to'])==('b','a')
    assert actual['edges'][0]['status']=='accepted'
