"""Role boundaries and merge gates, using synthetic records only.

No original corpus, provider, model request, or claim about OCR accuracy.
"""
import copy

import pytest

from graph_agent_roles import (
    RoleProtocolError, attribute_input_view, build_solver_input, connection_graph_view, decode_body_response, decode_page_response,
    decode_review_response, decode_targeted_review, merge_attribute_response,
    merge_body_response, reconcile_role_text, validate_connection_response, extract_rejected_role_issues,
)


def proof(bbox=(100, 200, 900, 900), reason='原图该位置的独立可见笔画'):
    return {'source': 'original', 'bbox': list(bbox), 'reason': reason}


def envelope(role, revision=4):
    return {'role': role, 'base_revision': revision, 'coordinate_space': 'original_1000'}


def graph(gid='G1', *, edges=True):
    return {'id': gid, 'name': gid, 'bbox': [.1, .2, .9, .9],
            'directed': False, 'weighted': False, 'multigraph': False,
            'complete': True, 'node_complete': True, 'inventory_reviewed': True,
            'uncertain_edges': [],
            'vertices': [{'id': 'a', 'label': 'a', 'x': .2, 'y': .5, 'isolated_confirmed': False},
                         {'id': 'b', 'label': 'b', 'x': .8, 'y': .5, 'isolated_confirmed': False}],
            'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'undirected',
                       'path': [[.2, .5], [.5, .4], [.8, .5]], 'style': 'solid',
                       'weight': None, 'edge_label': None, 'color': 'black',
                       'status': 'accepted', 'multiplicity': 1, 'evidence': []}] if edges else []}


def hints(text='求 v₅ 的长度为 3 的回路', bbox=(50, 20, 850, 100)):
    return {'items': [{'id': 't1', 'text': text, **({'bbox': list(bbox)} if bbox else {})}],
            'issues': [], 'local_status': 'completed'}


def body_response(text='求 v₅ 的长度为 3 的回路', *, local=None, role='body', gid=None):
    local = hints(text) if local is None else local
    regions = [{'id': 'paragraph_1', 'role': 'body', 'text': text,
                'bbox': [50, 20, 850, 100], 'source': 'original'}] if text else []
    decisions = []
    for hint in local['items']:
        decisions.append({'id': hint['id'], 'role': role, 'text': text or hint['text'],
                          'graph_id': gid, 'reason': '逐字核对对应原图区域',
                          'evidence': proof(hint.get('bbox', [50, 20, 850, 100]))})
    return {**envelope('body_text'), 'body_text': text, 'body_complete': True,
            'regions': regions, 'text_review': {'text': text, 'complete': True,
                'reason': '逐行复核完整原页', 'regions': decisions}}


def connection_response(graphs, *, candidates=None):
    rows = []
    for g in graphs:
        edges = copy.deepcopy(g['edges'])
        for e in edges:
            e['path'] = [[x*1000, y*1000] for x, y in e['path']]
        rows.append({'id': g['id'], 'node_inventory_confirmed': True, 'inventory_complete': True,
                     'edges': edges, 'retired_edges': [],
                     'reads': [{'vertex': v['id'], 'complete': True,
                                'edge_ids': [e['id'] for e in edges if v['id'] in (e['from'], e['to'])]}
                               for v in g['vertices']],
                     'candidate_verdicts': [[c['id'], c['id'] in {e['id'] for e in edges}]
                                            for c in (candidates or {}).get(g['id'], [])]})
    return {**envelope('connections'), 'panels_complete': True, 'graphs': rows, 'issues': []}


def attribute_response(graphs):
    def local_proof(edge):
        x, y = edge['path'][len(edge['path'])//2]
        return proof([max(0, x*1000-25), max(0, y*1000-25),
                      min(1000, x*1000+25), min(1000, y*1000+25)])
    return {**envelope('attributes'), 'graphs': [
        {'id': g['id'], 'edges': [{'id': e['id'], 'verdict': 'confirmed', 'attributes': {},
                                 'evidence': local_proof(e)}
                                for e in g['edges']]} for g in graphs], 'issues': []}


def review_response(graphs, local=None, text='求 v₅ 的长度为 3 的回路'):
    local = hints(text) if local is None else local
    return {**envelope('structure_review'), 'verdict': 'accept',
            'page_coverage': {'complete': True, 'graph_ids': [g['id'] for g in graphs],
                              'evidence': proof([0, 0, 1000, 1000])},
            'graphs': [{'id': g['id'], 'vertex_ids': [v['id'] for v in g['vertices']],
                        'edge_ids': [e['id'] for e in g['edges']], 'verdict': 'accept',
                        'evidence': proof([v*1000 for v in g['bbox']])} for g in graphs],
            'body_coverage': {'complete': True, 'region_ids': [h['id'] for h in local['items']],
                              'evidence': proof([0, 0, 1000, 1000])},
            'text_review': body_response(text, local=local)['text_review'], 'issues': []}


def issue(iid='issue_1', role='connections', gid='G1'):
    return {'id': iid, 'kind': 'visible_conflict', 'target_role': role, 'graph_id': gid,
            'vertex_ids': [], 'edge_ids': [], 'hint_ids': [],
            'reason': '这里有尚未解释的独立笔画', 'evidence': proof()}


def page_marker_hints():
    return {'version': 'synthetic-original-markers', 'coordinate_space': 'original_1000',
            'source_sha256': 'a'*64, 'proposal_only': True,
            'candidates': [
                {'id': 'marker_left', 'x': 123.456, 'y': 789.012, 'confidence': .95,
                 'evidence_source': 'closed_original_ink_hole'},
                {'id': 'marker_right', 'x': 845.125, 'y': 231.875, 'confidence': .97,
                 'evidence_source': 'original_gradient_and_ink_outline'}],
            'limits': {}}


def page_response(vertices=None):
    return {**envelope('page_vertices'), 'panels_complete': True, 'graphs': [{
        'id': 'G1', 'name': None, 'bbox': [0, 0, 1000, 1000], 'node_complete': True,
        'directed': False, 'weighted': False, 'multigraph': False,
        'vertices': vertices if vertices is not None else [
            {'id': 'a', 'label': 'a', 'marker_id': 'marker_right'},
            {'id': 'b', 'label': None, 'marker_id': 'marker_left'}]}]}


def test_explicit_page_marker_binding_uses_exact_published_position_not_order_or_label():
    from graph_evidence_pipeline import decode_nodes
    pool, response = page_marker_hints(), page_response()
    original_pool, original_response = copy.deepcopy(pool), copy.deepcopy(response)
    decoded = decode_page_response(response, pool, revision=4)
    expected = copy.deepcopy(response)
    expected['graphs'][0]['vertices'][0].update(x=845.125, y=231.875)
    expected['graphs'][0]['vertices'][1].update(x=123.456, y=789.012)
    assert decoded['graphs'] == decode_nodes(expected)
    assert pool == original_pool and response == original_response
    audit = decoded['audit']
    assert audit['source_sha256'] == pool['source_sha256']
    assert audit['position_evidence_only'] is True and audit['vertex_existence_certified'] is False
    assert audit['binding_count'] == 2
    assert audit['bindings'] == [
        {'graph_id': 'G1', 'vertex_id': 'a', 'marker_id': 'marker_right',
         'evidence_source': 'original_gradient_and_ink_outline',
         'candidate_original_1000': [845.125, 231.875],
         'normalized_position': [845.125/1000, 231.875/1000], 'derived_fields': ['x', 'y']},
        {'graph_id': 'G1', 'vertex_id': 'b', 'marker_id': 'marker_left',
         'evidence_source': 'closed_original_ink_hole',
         'candidate_original_1000': [123.456, 789.012],
         'normalized_position': [123.456/1000, 789.012/1000], 'derived_fields': ['x', 'y']}]


def test_explicit_matching_marker_coordinates_are_preserved_not_derived():
    response = page_response([{'id': 'a', 'label': 'a', 'marker_id': 'marker_left',
                              'x': 123.456, 'y': 789.012}])
    before = copy.deepcopy(response)
    result = decode_page_response(response, page_marker_hints(), revision=4)
    assert result['audit']['bindings'][0]['derived_fields'] == []
    assert result['graphs'][0]['vertices'][0]['x'] == 123.456/1000
    assert response == before


@pytest.mark.parametrize('coordinates, code', [
    ({'x': 123.456}, 'partial_page_marker_coordinates'),
    ({'y': 789.012}, 'partial_page_marker_coordinates'),
    ({'x': None, 'y': None}, 'invalid_page_marker_coordinates'),
    ({'x': None, 'y': 789.012}, 'invalid_page_marker_coordinates'),
    ({'x': True, 'y': 789.012}, 'invalid_page_marker_coordinates'),
    ({'x': float('nan'), 'y': 789.012}, 'invalid_page_marker_coordinates'),
    ({'x': 123.456, 'y': 1001}, 'invalid_page_marker_coordinates'),
    ({'x': 123, 'y': 789}, 'page_marker_coordinates_conflict'),
    ({'x': 123.456000001, 'y': 789.012}, 'page_marker_coordinates_conflict'),
    ({'x': .123456, 'y': .789012}, 'page_marker_coordinates_conflict'),
])
def test_marker_binding_never_repairs_explicit_incomplete_or_conflicting_coordinates(coordinates, code):
    response = page_response([{'id': 'a', 'label': None, 'marker_id': 'marker_left', **coordinates}])
    with pytest.raises(RoleProtocolError, match=code) as caught:
        decode_page_response(response, page_marker_hints(), revision=4)
    assert caught.value.audit['graph_id'] == 'G1' and caught.value.audit['vertex_id'] == 'a'
    # The published marker does not overwrite an explicit model coordinate,
    # even when the mismatch is smaller than a pixel or caused by unit errors.
    assert response['graphs'][0]['vertices'][0].keys() == {'id', 'label', 'marker_id', *coordinates}
    if code == 'page_marker_coordinates_conflict':
        assert caught.value.audit['expected'] == {'x': 123.456, 'y': 789.012}
        assert caught.value.audit['actual'] == coordinates


@pytest.mark.parametrize('marker_id, code', [
    (None, 'invalid_page_marker_reference'), ('', 'invalid_page_marker_reference'),
    ('not_given', 'unknown_page_marker_reference'),
])
def test_invalid_or_unknown_page_marker_is_not_inferred_from_coordinates(marker_id, code):
    response = page_response([{'id': 'a', 'marker_id': marker_id, 'x': 123.456, 'y': 789.012}])
    with pytest.raises(RoleProtocolError, match=code):
        decode_page_response(response, page_marker_hints(), revision=4)


@pytest.mark.parametrize('across_graphs', [False, True])
def test_one_marker_cannot_create_two_vertex_identities(across_graphs):
    response = page_response()
    if across_graphs:
        duplicate = copy.deepcopy(response['graphs'][0])
        duplicate['id'] = 'G2'
        duplicate['vertices'] = [{'id': 'other', 'marker_id': 'marker_right'}]
        response['graphs'].append(duplicate)
    else:
        response['graphs'][0]['vertices'][1]['marker_id'] = 'marker_right'
    before = copy.deepcopy(response)
    with pytest.raises(RoleProtocolError, match='duplicate_page_marker_binding') as caught:
        decode_page_response(response, page_marker_hints(), revision=4)
    assert caught.value.audit['marker_id'] == 'marker_right'
    assert caught.value.audit['previous_binding'] == {'graph_id': 'G1', 'vertex_id': 'a'}
    assert response == before


@pytest.mark.parametrize('mutation, code', [
    ('absent', 'page_marker_hints_unavailable'), ('crop_coordinates', 'page_marker_coordinate_contract'),
    ('source_missing', 'page_marker_source_missing'), ('duplicate_id', 'ambiguous_page_marker_candidate'),
    ('invalid_coordinate', 'invalid_page_marker_candidate_coordinates'),
    ('capacity', 'page_marker_candidate_capacity'),
])
def test_explicit_binding_requires_bounded_unambiguous_published_original_candidates(mutation, code):
    from graph_agent_roles import MAX_PAGE_MARKERS
    pool = page_marker_hints()
    if mutation == 'absent': pool = None
    if mutation == 'crop_coordinates': pool['coordinate_space'] = 'crop_1000'
    if mutation == 'source_missing': pool.pop('source_sha256')
    if mutation == 'duplicate_id': pool['candidates'].append(copy.deepcopy(pool['candidates'][0]))
    if mutation == 'invalid_coordinate': pool['candidates'][0]['x'] = float('inf')
    if mutation == 'capacity': pool['candidates'] = [pool['candidates'][0]]*(MAX_PAGE_MARKERS+1)
    with pytest.raises(RoleProtocolError, match=code):
        decode_page_response(page_response(), pool, revision=4)


def test_legacy_page_coordinates_and_types_keep_decode_nodes_behavior_without_pool_matching():
    from graph_evidence_pipeline import decode_nodes
    response = page_response([{'id': 'a', 'label': None, 'x': 123.4, 'y': 789.0}])
    decoded = decode_page_response(response, {'not': 'a usable pool'}, revision=4)
    assert decoded['graphs'] == decode_nodes(response)
    assert decoded['audit']['bindings'] == [] and decoded['audit']['binding_count'] == 0
    missing = page_response([{'id': 'a', 'label': None}])
    with pytest.raises(ValueError, match='invalid_qwen_coordinate'):
        decode_page_response(missing, page_marker_hints(), revision=4)
    response = page_response(); response['graphs'][0]['directed'] = 'true'
    with pytest.raises(ValueError, match='invalid_graph_type'):
        decode_page_response(response, page_marker_hints(), revision=4)


@pytest.mark.parametrize('mutation, code', [
    ('revision', 'stale_or_missing_revision'), ('role', 'wrong_role'), ('coordinates', 'role_coordinate_contract'),
])
def test_page_envelope_precedes_marker_binding(mutation, code):
    response = page_response()
    response[{'revision': 'base_revision', 'role': 'role', 'coordinates': 'coordinate_space'}[mutation]] = {
        'revision': 3, 'role': 'connections', 'coordinates': 'crop_1000'}[mutation]
    with pytest.raises(RoleProtocolError, match=code):
        decode_page_response(response, None, revision=4)


@pytest.mark.parametrize('confidence', [0., 1.])
def test_marker_binding_does_not_infer_vertex_existence_or_complete_candidate_inventory(confidence):
    pool = page_marker_hints()
    pool['candidates'][0]['confidence'] = confidence
    response = page_response([{'id': 'a', 'marker_id': 'marker_left', 'label': None}])
    result = decode_page_response(response, pool, revision=4)
    assert len(result['graphs'][0]['vertices']) == 1, 'Unused marker proposals never manufacture vertices.'
    assert result['audit']['vertex_existence_certified'] is False
    assert result['audit']['position_evidence_only'] is True


@pytest.mark.parametrize('center', [(199.999999, 500), (800.000001, 500),
                                    (500, 299.999999), (500, 700.000001)])
@pytest.mark.parametrize('use_marker', [False, True])
def test_page_vertices_cannot_escape_own_panel_even_with_valid_original_coordinates(center, use_marker):
    pool = page_marker_hints()
    pool['candidates'][0].update(x=center[0], y=center[1])
    vertex = {'id': 'a', 'label': 'a'}
    vertex.update({'marker_id': 'marker_left'} if use_marker else {'x': center[0], 'y': center[1]})
    response = page_response([vertex]); response['graphs'][0]['bbox'] = [200, 300, 800, 700]
    before, pool_before = copy.deepcopy(response), copy.deepcopy(pool)
    with pytest.raises(RoleProtocolError, match='page_vertex_outside_panel') as caught:
        decode_page_response(response, pool, revision=4)
    assert caught.value.audit == {
        'accepted': False, 'issue': 'page_vertex_outside_panel', 'graph_id': 'G1', 'vertex_id': 'a',
        'coordinate_space': 'original_1000', 'center': list(center), 'panel_bbox': [200, 300, 800, 700],
        'marker_id': 'marker_left' if use_marker else None}
    assert response == before and pool == pool_before, 'No clamping, panel expansion, or reassignment.'


def test_page_panel_boundaries_use_full_image_coordinates_and_keep_same_labels_in_distinct_panels():
    response = page_response([{'id': 'a', 'label': 'a', 'x': 100, 'y': 200},
                              {'id': 'b', 'label': 'b', 'x': 400, 'y': 700}])
    response['graphs'][0]['bbox'] = [100, 200, 400, 700]
    second = copy.deepcopy(response['graphs'][0]); second['id'] = 'G2'
    second['bbox'] = [600, 200, 900, 700]
    for v in second['vertices']: v['x'] += 500
    response['graphs'].append(second)
    result = decode_page_response(response, None, revision=4)
    assert [[(v['x'], v['y']) for v in g['vertices']] for g in result['graphs']] == [
        [(.1, .2), (.4, .7)], [(.6, .2), (.9, .7)]]
    response['graphs'][1]['vertices'][0]['x'] = 100
    with pytest.raises(RoleProtocolError, match='page_vertex_outside_panel') as caught:
        decode_page_response(response, None, revision=4)
    assert caught.value.audit['graph_id'] == 'G2', 'Being inside another valid panel cannot authorize membership.'


def test_page_panel_validation_does_not_relax_invalid_full_image_coordinates():
    response = page_response([{'id': 'a', 'x': 1001, 'y': 500}])
    with pytest.raises(ValueError, match='invalid_qwen_coordinate'):
        decode_page_response(response, None, revision=4)


def test_empty_body_can_keep_graph_label_hints_with_unassigned_graph_identity():
    local = hints('q₂', bbox=(450, 380, 480, 420))
    response = body_response('', local=local, role='graph_label', gid=None)
    response['regions'] = [{'id': 'observed_label', 'role': 'graph_label', 'text': 'q₂',
                            'source': 'original', 'bbox': [450, 380, 480, 420]}]
    before = copy.deepcopy(response)
    deferred = decode_body_response(response, hints=local, revision=4)
    assert deferred['body_text'] == ''
    assert deferred['regions'][0]['role'] == 'graph_label'
    assert deferred['body_complete'] is False, 'Unknown panel ownership remains unresolved, not body text.'
    merged = merge_body_response(response, local, [graph()], revision=4)
    assert merged['body_text'] == '' and merged['body_complete'] is True
    assert merged['text_review']['regions'][0]['role'] == 'graph_label'
    assert merged['text_review']['regions'][0]['graph_id'] == 'G1'
    assert response == before


def test_body_hint_role_contradiction_is_not_repaired_from_its_reason_or_null_graph_id():
    local = hints('q₂', bbox=(450, 380, 480, 420))
    response = body_response('', local=local, role='body', gid=None)
    response['regions'] = [{'id': 'observed_label', 'role': 'graph_label', 'text': 'q₂',
                            'source': 'original', 'bbox': [450, 380, 480, 420]}]
    response['text_review']['regions'][0]['reason'] = '这是图内边名，不是正文'
    before = copy.deepcopy(response)
    with pytest.raises(RoleProtocolError, match='body_fragment_not_in_text') as caught:
        merge_body_response(response, local, [graph()], revision=4)
    assert caught.value.audit['hint_id'] == 't1'
    assert response == before


def test_body_keeps_all_independently_located_questions():
    text = '(1) 写出矩阵。\n(2) 写出 v₁ 到 v₃ 的通路。\n(3) 写出 v₅ 的回路。\n(4) 判断有无欧拉通路。'
    local = {'items': [], 'issues': [], 'local_status': 'unavailable'}
    response = body_response(text, local=local)
    response['regions'] = [{'id': 'body_'+str(i), 'role': 'body', 'text': line,
                            'source': 'original', 'bbox': [0, i*40, 950, (i+1)*40]}
                           for i, line in enumerate(text.splitlines(), 1)]
    result = merge_body_response(response, local, [graph()], revision=4)
    assert result['body_text'] == text and result['body_complete']
    assert response['regions'] == result['regions']


@pytest.mark.parametrize('edit', ['omit', 'duplicate', 'unknown'])
def test_body_hint_coverage_is_not_optional(edit):
    response = body_response()
    rows = response['text_review']['regions']
    if edit == 'omit': rows.clear()
    if edit == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    if edit == 'unknown': rows[0]['id'] = 'invented'
    with pytest.raises(RoleProtocolError, match='text_review_regions'):
        merge_body_response(response, hints(), [graph()], revision=4)


def test_parallel_body_does_not_guess_graph_ids_and_binds_unique_hint_panel():
    local = hints('a', [180, 480, 220, 520])
    response = body_response('', local=local, role='graph_label')
    original = copy.deepcopy(response)
    result = merge_body_response(response, local, [graph()], revision=4)
    assert response == original and result['body_complete']
    assert result['text_review']['regions'][0]['graph_id'] == 'G1'
    assert result['audit']['panel_bindings'][0]['source'] == 'unique_hint_panel_overlap'


@pytest.mark.parametrize('ambiguous', [True, False])
def test_graph_label_ambiguous_or_unlocated_remains_uncertain(ambiguous):
    local = hints('a', [180, 480, 220, 520] if ambiguous else None)
    response = body_response('', local=local, role='graph_label')
    graphs = [graph(), graph('G2')] if ambiguous else [graph()]
    result = merge_body_response(response, local, graphs, revision=4)
    assert not result['body_complete']
    assert result['text_review']['regions'][0]['role'] == 'uncertain'


def test_unknown_explicit_graph_label_owner_is_rejected():
    local = hints('a', [180, 480, 220, 520])
    with pytest.raises(RoleProtocolError, match='unknown_text_graph_id'):
        merge_body_response(body_response('', local=local, role='graph_label', gid='invented'),
                            local, [graph()], revision=4)


@pytest.mark.parametrize(('old', 'new'), [
    ('求 v3 的回路', '求 v5 的回路'), ('x²', 'x³'), ('v₃', 'v₅'), ('α<β', 'α>β'),
    ('至少三条边', '至多两条边'), ('判段是否连通', '判断是否连通'),
    ('增加黑边', '减少白边'), ('∃x∈A', '∀x∉A'),
])
def test_every_substantive_hint_change_needs_own_original_pixel_location(old, new):
    local = hints(old)
    response = body_response(new, local=local)
    decision = response['text_review']['regions'][0]
    decision.pop('evidence')
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        merge_body_response(response, local, [graph()], revision=4)
    decision['evidence'] = proof([200, 400, 300, 500])
    with pytest.raises(RoleProtocolError, match='text_evidence_wrong_location'):
        merge_body_response(response, local, [graph()], revision=4)
    decision['evidence'] = proof(local['items'][0]['bbox'])
    assert merge_body_response(response, local, [graph()], revision=4)['body_complete']


def test_equivalent_glyph_change_keeps_existing_content_signature_rule():
    local = hints('求顶奌 v₁')
    response = body_response('求顶点 v₁', local=local)
    response['text_review']['regions'][0].pop('evidence')
    result = merge_body_response(response, local, [graph()], revision=4)
    assert result['body_complete'] and result['body_text'] == '求顶点 v₁'


def test_full_page_proof_cannot_replace_local_changed_hint_proof():
    response = body_response('求 v3 的回路', local=hints())
    response['text_review']['regions'][0]['evidence'] = proof([0, 0, 1000, 1000])
    with pytest.raises(RoleProtocolError, match='text_evidence_wrong_location'):
        merge_body_response(response, hints(), [graph()], revision=4)


def test_located_text_cannot_be_excluded_using_another_label_as_evidence():
    local = hints()
    response = body_response('', local=local, role='noise')
    response['text_review']['regions'][0]['evidence'] = proof([180, 480, 220, 520])
    with pytest.raises(RoleProtocolError, match='text_evidence_wrong_location'):
        merge_body_response(response, local, [graph()], revision=4)


def test_body_must_be_covered_by_real_region_proposals_and_not_silently_emptied():
    response = body_response()
    response['regions'] = []
    with pytest.raises(RoleProtocolError, match='body_regions_do_not_cover_transcription'):
        decode_body_response(response, hints=hints(), revision=4)
    empty_hints = {'items': []}
    response = body_response('', local=empty_hints)
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        decode_body_response(response, hints=empty_hints,
                             previous={'body_text': '已读到的题干'}, revision=4)


def test_uncertain_source_region_not_found_by_ocr_still_blocks_body_completion():
    local = {'items': []}
    response = body_response('', local=local)
    response['regions'] = [{'id': 'blurred_line', 'role': 'uncertain', 'text': '',
                            'bbox': [100, 20, 900, 100], 'source': 'original'}]
    result = merge_body_response(response, local, [graph()], revision=4)
    assert not result['body_complete']
    assert 'uncertain_body_region:blurred_line' in result['issues']


@pytest.mark.parametrize('mutation', ['revision', 'role', 'coordinates'])
def test_role_and_revision_identity_is_checked_before_body_commit(mutation):
    response = body_response()
    response[{'revision': 'base_revision', 'role': 'role', 'coordinates': 'coordinate_space'}[mutation]] = {
        'revision': 3, 'role': 'connections', 'coordinates': 'crop_1000'}[mutation]
    with pytest.raises(RoleProtocolError):
        merge_body_response(response, hints(), [graph()], revision=4)


def test_connection_record_identity_is_independent_of_candidate_name():
    g = graph(); candidate = {**copy.deepcopy(g['edges'][0]), 'id': 'px_1'}
    candidates = {'G1': [candidate]}
    response = connection_response([g], candidates=candidates)
    row = response['graphs'][0]
    row['edges'][0]['candidate_id'] = 'px_1'
    row['candidate_verdicts'] = [['px_1', True]]
    checked = validate_connection_response(response, [g], candidates, revision=4)
    assert checked['graphs'][0]['edges'][0]['id'] == 'e1'
    assert checked['graphs'][0]['edges'][0]['candidate_id'] == 'px_1'


@pytest.mark.parametrize('fit_score', [0., .25, .95])
@pytest.mark.parametrize('stroke_supported', [False, True])
def test_connection_view_scopes_footprints_without_changing_measured_evidence(fit_score, stroke_supported):
    from graph_evidence_pipeline import _proposal_json
    g = graph()
    g['node_geometry_evidence'] = {'a': {
        'footprint_outline': [[190., 500.], [200., 510.], [210., 500.]],
        'footprint_confidence': fit_score, 'footprint_kind': 'uncertain_disk',
        'footprint_source': 'local_ink_fallback',
        'footprint_limits': {'contour_cap_reached': True, 'contours_seen': 64}}}
    candidate = copy.deepcopy(g['edges'][0])
    candidate['pixel_evidence'] = {'coverage': .64, 'supported': stroke_supported,
        'source': 'original_pixel_route', 'reasons': ['retained_measurement']}
    candidate['ports'] = [{'vertex': 'a', 'point': [.21, .5],
                           'footprint_confidence': fit_score,
                           'footprint_source': 'local_ink_fallback'}]
    raw_graph, raw_candidate = copy.deepcopy(g), copy.deepcopy(candidate)
    legacy = _proposal_json(g, [candidate])
    view = connection_graph_view(g, [candidate])
    assert g == raw_graph and candidate == raw_candidate
    assert legacy['vertices'][0]['footprint_confidence'] == fit_score
    assert legacy['candidates'][0]['ports'][0]['footprint_confidence'] == fit_score
    # Every existing coordinate, outline, source and capacity diagnostic stays
    # in the view. Only the semantically misleading fit-score exposure changes.
    expected = copy.deepcopy(legacy)
    expected['vertices'][0].pop('footprint_confidence')
    expected['candidates'][0]['ports'][0].pop('footprint_confidence')
    semantics = view.pop('node_footprint_semantics')
    assert view == expected
    assert semantics['purpose'] == 'endpoint_mask_and_port_estimation'
    assert semantics['vertex_existence_assessment'] == 'not_provided'
    assert view['candidates'][0]['path_reuse_allowed'] is stroke_supported
    # Role-facing copies cannot later mutate the underlying measurement audit.
    view['vertices'][0]['footprint_outline'][0][0] = 999.
    view['vertices'][0]['footprint_limits'].clear()
    assert g == raw_graph and candidate == raw_candidate


def test_incomplete_read_is_rejected_with_same_graph_fixed_vertex_context():
    first, second = graph(), graph('G2')
    second['vertices'][1].update(x=.65, y=.7, label='b₂')
    second['node_geometry_evidence'] = {'b': {'footprint_confidence': .25,
        'footprint_source': 'local_ink_fallback'}}
    response = connection_response([first, second])
    response['graphs'][1]['reads'][1].update(complete=False, edge_ids=[], graph_id='G1',
        x=999, y=999, evidence=proof([900, 900, 999, 999]))
    raw_response, raw_graphs = copy.deepcopy(response), copy.deepcopy([first, second])
    with pytest.raises(RoleProtocolError, match='connection_source_coverage') as caught:
        validate_connection_response(response, [first, second], {}, revision=4)
    audit = caught.value.audit
    assert audit['accepted'] is False
    assert audit['issues'] == ['incomplete_source_read:b']
    assert audit['graph_id'] == 'G2' and audit['vertex_ids'] == ['b']
    assert audit['vertex_context'] == [{'id': 'b', 'label': 'b₂', 'x': 650., 'y': 700.}]
    assert audit['coordinate_space'] == 'original_1000'
    assert audit['location_source'] == 'fixed_inventory'
    assert audit['affected_vertex_count'] == 1 and audit['omitted_vertex_count'] == 0
    assert response == raw_response and [first, second] == raw_graphs


@pytest.mark.parametrize('mutation, expected_ids', [
    ('missing_all', ['a', 'b']), ('missing_one', ['b']), ('duplicate', ['a']),
    ('unknown', []), ('malformed_extra', []),
])
def test_coverage_context_never_invents_vertex_locations(mutation, expected_ids):
    g = graph(); response = connection_response([g]); row = response['graphs'][0]
    if mutation == 'missing_all': row['reads'] = None
    if mutation == 'missing_one': row['reads'].pop()
    if mutation == 'duplicate': row['reads'].append(copy.deepcopy(row['reads'][0]))
    if mutation == 'unknown':
        row['reads'].append({'vertex': 'unknown:incomplete_source_read:a',
                             'complete': False, 'edge_ids': []})
    if mutation == 'malformed_extra': row['reads'].append({'vertex': None, 'x': 200, 'y': 500})
    with pytest.raises(RoleProtocolError, match='connection_source_coverage') as caught:
        validate_connection_response(response, [g], {}, revision=4)
    audit = caught.value.audit
    assert audit['graph_id'] == 'G1'
    assert audit['vertex_ids'] == expected_ids
    assert [v['id'] for v in audit['vertex_context']] == expected_ids
    assert audit['affected_vertex_count'] == len(expected_ids)
    assert audit['omitted_vertex_count'] == 0


def test_coverage_context_cap_reports_omissions_without_relaxing_coverage():
    g = graph(edges=False)
    g['vertices'] = [{'id': 'node:'+str(i), 'label': None, 'x': .2+i*.04, 'y': .5}
                     for i in range(13)]
    response = connection_response([g]); response['graphs'][0]['reads'] = None
    with pytest.raises(RoleProtocolError, match='connection_source_coverage') as caught:
        validate_connection_response(response, [g], {}, revision=4)
    audit = caught.value.audit
    assert audit['issues'] == ['source_coverage_missing']
    assert audit['vertex_ids'] == [v['id'] for v in g['vertices'][:8]]
    assert len(audit['vertex_context']) == 8
    assert audit['affected_vertex_count'] == 13 and audit['omitted_vertex_count'] == 5
    # A colon inside a legitimate ID is part of that ID, not another error.
    response = connection_response([g]); response['graphs'][0]['reads'][10]['complete'] = False
    with pytest.raises(RoleProtocolError, match='connection_source_coverage') as caught:
        validate_connection_response(response, [g], {}, revision=4)
    assert caught.value.audit['vertex_ids'] == ['node:10']


@pytest.mark.parametrize('mutation', ['unknown_endpoint', 'duplicate_id', 'missing_read', 'node_edit', 'body_edit'])
def test_connections_cannot_commit_unknown_identity_incomplete_reads_or_other_roles(mutation):
    g = graph(); response = connection_response([g]); row = response['graphs'][0]
    if mutation == 'unknown_endpoint': row['edges'][0]['to'] = 'c'
    if mutation == 'duplicate_id': row['edges'].append(copy.deepcopy(row['edges'][0]))
    if mutation == 'missing_read': row['reads'].pop()
    if mutation == 'node_edit': row['node_updates'] = [{'id': 'a', 'x': 500, 'y': 500}]
    if mutation == 'body_edit': response['body_text'] = '偷偷改题干'
    with pytest.raises(RoleProtocolError):
        validate_connection_response(response, [g], {}, revision=4)


def test_old_edge_omission_requires_explicit_original_retirement():
    g = graph(); response = connection_response([g]); row = response['graphs'][0]
    row['edges'].clear()
    for read in row['reads']: read['edge_ids'].clear()
    with pytest.raises(RoleProtocolError, match='existing_edge_silently_omitted'):
        validate_connection_response(response, [g], {}, revision=4)
    row['retired_edges'] = [{'id': 'e1', 'reason': '原图确认是节点边框', 'evidence': proof()}]
    assert validate_connection_response(response, [g], {}, revision=4)['graphs'][0]['edges'] == []


@pytest.mark.parametrize('vote', [0, 1, 'true', {}, []])
def test_candidate_verdict_must_be_boolean_or_explicit_unknown(vote):
    g = graph(); candidates = {'G1': [g['edges'][0]]}
    response = connection_response([g], candidates=candidates)
    response['graphs'][0]['candidate_verdicts'] = [['e1', vote]]
    with pytest.raises(RoleProtocolError, match='invalid_candidate_verdict_type'):
        validate_connection_response(response, [g], candidates, revision=4)


def test_explicit_unknown_candidate_is_preserved_for_pixel_gate():
    g = graph(); candidates = {'G1': [g['edges'][0]]}
    response = connection_response([g], candidates=candidates)
    response['graphs'][0]['candidate_verdicts'] = [['e1', None]]
    assert validate_connection_response(response, [g], candidates, revision=4)['graphs'][0][
        'candidate_verdicts'] == [['e1', None]]


def test_connection_issues_are_not_hidden_by_inventory_complete():
    g = graph(); response = connection_response([g]); response['issues'] = [issue(role='page_vertices')]
    checked = validate_connection_response(response, [g], {}, revision=4)
    assert checked['issues'] == response['issues']
    response['issues'][0]['vertex_ids'] = ['invented']
    with pytest.raises(RoleProtocolError, match='unknown_or_duplicate_issue_reference'):
        validate_connection_response(response, [g], {}, revision=4)


def test_attribute_projection_keeps_fixed_ids_full_curve_and_null_as_unverified_draft():
    g = graph()
    g['edges'][0]['id'] = 'internal_42'
    g['edges'][0]['path'] = [[.2+i*.01, .4+(i % 5)*.01] for i in range(61)]
    g['edges'][0]['evidence'] = [{'source': 'private_runtime_audit', 'supported': True}]
    local = hints('q₂', bbox=(450, 380, 480, 420))
    local['items'][0].update(paddle_role='body', score=0.01)
    before = copy.deepcopy((g, local))
    view = attribute_input_view([g], local)
    edge = view['graphs'][0]['edges'][0]
    assert edge['id'] == 'internal_42' and edge['edge_label'] is None and edge['weight'] is None
    assert edge['path'] == [[x*1000, y*1000] for x, y in g['edges'][0]['path']]
    assert len(edge['path']) == 61 and edge['from'] == 'a' and edge['to'] == 'b'
    assert 'evidence' not in edge and 'status' not in edge
    assert view['graphs'][0]['bbox'] == [100, 200, 900, 900]
    assert view['attribute_reading_contract']['flat_attribute_values'] == 'unverified_draft_null_does_not_prove_absence'
    item = view['attribute_text_hints']['items'][0]
    assert item == {'id': 't1', 'text': 'q₂', 'bbox': [450, 380, 480, 420],
                    'candidate_graph_ids': ['G1'], 'paddle_role': 'body',
                    'source': 'local_ocr', 'proposal_only': True}
    assert 'edge_id' not in item and 'weight' not in item, 'No text-to-edge or digit-to-weight inference.'
    view['graphs'][0]['edges'][0]['path'][0][0] = 999
    view['attribute_text_hints']['items'][0]['bbox'][0] = 999
    assert (g, local) == before


def test_attribute_projection_does_not_infer_a_unique_panel_or_edge_from_ocr_category():
    local = hints('12', bbox=(450, 380, 480, 420))
    local['items'][0]['paddle_role'] = 'noise'
    view = attribute_input_view([graph(), graph('G2')], local)
    item = view['attribute_text_hints']['items'][0]
    assert item['candidate_graph_ids'] == ['G1', 'G2']
    assert item['text'] == '12' and item['paddle_role'] == 'noise'
    assert all(e['weight'] is None for g in view['graphs'] for e in g['edges'])


def test_attribute_projection_reports_unusable_or_unlocated_hints_without_inventing_positions():
    local = {'items': [
        {'id': 'unlocated', 'text': 'q₂'},
        {'id': 'outside', 'text': 'heading', 'bbox': [0, 0, 80, 80]},
        {'id': 'invalid', 'text': 'q₃', 'bbox': [450, 380, 450, 420]},
        {'id': 'oversize', 'text': 'q'*513, 'bbox': [450, 380, 480, 420]}],
        'issues': [], 'local_status': 'unavailable'}
    view = attribute_input_view([graph()], local)
    assert view['attribute_text_hints']['items'] == []
    assert view['attribute_text_hints']['local_status'] == 'unavailable'
    assert {r['hint_id']: r['reason'] for r in view['attribute_text_hints']['omissions']} == {
        'unlocated': 'unlocated_or_invalid_original_bbox', 'outside': 'outside_all_panels',
        'invalid': 'unlocated_or_invalid_original_bbox', 'oversize': 'empty_or_excessive_text'}
    assert view['attribute_reading_contract']['missing_hint_does_not_prove_absence'] is True


@pytest.mark.parametrize('bad_path', [[], [[.2, .5], [float('nan'), .5]],
                                    [[.2, .5], [1.001, .5]], [[.2, .5]]*129])
def test_attribute_projection_cannot_sanitize_or_truncate_invalid_geometry(bad_path):
    g = graph(); g['edges'][0]['path'] = bad_path
    with pytest.raises(RoleProtocolError, match='attribute_view_invalid_path'):
        attribute_input_view([g], None)


def test_attribute_projection_is_input_only_and_label_change_still_needs_its_own_pixel_location():
    g = graph(); local = hints('q₂', bbox=(450, 380, 480, 420))
    view = attribute_input_view([g], local)
    assert g['edges'][0]['edge_label'] is None
    response = attribute_response([g])
    item = response['graphs'][0]['edges'][0]
    item.update(attributes={'edge_label': view['attribute_text_hints']['items'][0]['text']},
                evidence=proof([200, 750, 250, 800]))
    with pytest.raises(RoleProtocolError, match='attribute_evidence_wrong_edge'):
        merge_attribute_response([g], response, revision=4)
    item['evidence'] = proof([450, 380, 480, 420])
    updated, audit = merge_attribute_response([g], response, revision=4)
    assert updated[0]['edges'][0]['edge_label'] == 'q₂'
    assert updated[0]['edges'][0]['status'] == 'pending'
    assert audit['requires_pixel_revalidation'] is True and g['edges'][0]['edge_label'] is None


def test_parallel_edge_instances_remain_distinct_through_attributes():
    g = graph(); g['multigraph'] = True
    g['edges'].append({**copy.deepcopy(g['edges'][0]), 'id': 'e2', 'path': [[.2, .5], [.5, .6], [.8, .5]]})
    response = attribute_response([g])
    response['graphs'][0]['edges'][0]['attributes'] = {'edge_label': 'e₁'}
    response['graphs'][0]['edges'][1]['attributes'] = {'edge_label': 'e₂'}
    merged, audit = merge_attribute_response([g], response, revision=4)
    assert [e['id'] for e in merged[0]['edges']] == ['e1', 'e2']
    assert [e['parallel_count'] for e in merged[0]['edges']] == [2, 2]
    assert [e['weight'] for e in merged[0]['edges']] == [None, None]
    assert audit['requires_pixel_revalidation']


def test_reverse_is_atomic_for_edge_identity_endpoints_and_path():
    g = graph(); g['directed'] = True; g['edges'][0]['direction'] = 'forward'
    original = copy.deepcopy(g); response = attribute_response([g])
    response['graphs'][0]['edges'][0]['attributes'] = {'direction': 'reverse'}
    merged, audit = merge_attribute_response([g], response, revision=4)
    e = merged[0]['edges'][0]
    assert g == original and e['id'] == 'e1'
    assert (e['from'], e['to'], e['direction']) == ('b', 'a', 'forward')
    assert e['path'] == list(reversed(original['edges'][0]['path']))
    assert e['status'] == 'pending' and not merged[0]['complete']
    assert audit['requires_pixel_revalidation'] and audit['changes'][0]['edge_id'] == 'e1'


@pytest.mark.parametrize('mutation', ['omit', 'unknown', 'duplicate', 'endpoint', 'path', 'node', 'no_proof', 'wrong_panel'])
def test_attribute_role_is_an_exact_fixed_edge_attribute_proposal(mutation):
    g = graph(); response = attribute_response([g]); row = response['graphs'][0]; item = row['edges'][0]
    if mutation == 'omit': row['edges'].clear()
    if mutation == 'unknown': item['id'] = 'invented'
    if mutation == 'duplicate': row['edges'].append(copy.deepcopy(item))
    if mutation == 'endpoint': item['from'] = 'b'
    if mutation == 'path': item['path'] = [[200, 500], [800, 500]]
    if mutation == 'node': row['vertices'] = []
    if mutation == 'no_proof': item['evidence']['source'] = 'candidate_overlay'
    if mutation == 'wrong_panel': item['evidence'] = proof([0, 0, 50, 50])
    with pytest.raises(RoleProtocolError):
        merge_attribute_response([g], response, revision=4)


def test_failed_later_attribute_does_not_partially_mutate_shared_graphs():
    graphs = [graph('G1'), graph('G2')]; original = copy.deepcopy(graphs)
    response = attribute_response(graphs)
    response['graphs'][0]['edges'][0]['attributes'] = {'weight': 7}
    response['graphs'][1]['edges'][0]['id'] = 'invented'
    with pytest.raises(RoleProtocolError):
        merge_attribute_response(graphs, response, revision=4)
    assert graphs == original


def test_uncertain_attributes_and_model_issues_keep_explicit_routes():
    g = graph(); response = attribute_response([g])
    response['graphs'][0]['edges'][0].update(verdict='uncertain', attributes={'weight': 999})
    response['issues'] = [issue('wrong_panel', 'page_vertices')]
    merged, audit = merge_attribute_response([g], response, revision=4)
    assert merged[0]['edges'][0]['weight'] is None
    assert not merged[0]['complete'] and merged[0]['edges'][0]['status'] == 'pending'
    assert audit['issues'][0]['target_role'] == 'attributes'
    assert audit['issues'][0]['edge_ids'] == ['e1']
    assert audit['issues'][1] == response['issues'][0]


@pytest.mark.parametrize('mutation', ['page', 'vertex', 'edge', 'body', 'bare_complete', 'silent_edit'])
def test_review_requires_explicit_complete_identity_and_body_coverage(mutation):
    graphs = [graph()]; response = review_response(graphs)
    if mutation == 'page': response['page_coverage']['graph_ids'] = []
    if mutation == 'vertex': response['graphs'][0]['vertex_ids'].pop()
    if mutation == 'edge': response['graphs'][0]['edge_ids'] = []
    if mutation == 'body': response['body_coverage']['region_ids'] = []
    if mutation == 'bare_complete': response = {**envelope('structure_review'), 'complete': True}
    if mutation == 'silent_edit': response['graphs'][0]['edges'] = []
    with pytest.raises(RoleProtocolError):
        decode_review_response(response, graphs, body_complete=True, hints=hints(), revision=4)


@pytest.mark.parametrize('blocker', ['pending_edge', 'incomplete_graph', 'unknown_type', 'body_incomplete', 'model_issue'])
def test_model_accept_does_not_override_local_or_explicit_failures(blocker):
    graphs = [graph()]; response = review_response(graphs)
    if blocker == 'pending_edge': graphs[0]['edges'][0]['status'] = 'pending'
    if blocker == 'incomplete_graph': graphs[0]['complete'] = False
    if blocker == 'unknown_type': graphs[0]['directed'] = 'unknown'
    if blocker == 'model_issue': response['issues'] = [issue()]
    result = decode_review_response(response, graphs, body_complete=blocker != 'body_incomplete',
                                    hints=hints(), revision=4)
    assert result['verdict'] == 'needs_review' and result['issues']


def test_machine_conflict_dicts_preserve_identity_route_and_precedence():
    graphs = [graph()]; response = review_response(graphs)
    model_issue = issue('node_error', 'connections')
    response['issues'] = [model_issue]
    machine = {'id': 'node_error', 'kind': 'missing_node', 'target_role': 'page_vertices',
               'graph_id': 'G1', 'vertex_ids': [], 'edge_ids': [], 'hint_ids': [],
               'reason': 'node_inventory_unconfirmed', 'detail': {'stage': 'pixel'}}
    required = [machine, copy.deepcopy(machine), 'body_reconciliation_incomplete']
    original = copy.deepcopy(required)
    result = decode_review_response(response, graphs, body_complete=True, hints=hints(), revision=4,
                                    required_issues=required)
    assert required == original and result['issues'][0] == machine
    assert sum(x['id'] == 'node_error' for x in result['issues']) == 1
    assert result['issues'][1]['target_role'] == 'body_text'
    assert result['verdict'] == 'needs_review'


def test_needs_review_without_any_specific_problem_is_rejected():
    graphs = [graph()]; response = review_response(graphs); response['verdict'] = 'needs_review'
    with pytest.raises(RoleProtocolError, match='review_requires_specific_issue'):
        decode_review_response(response, graphs, body_complete=True, hints=hints(), revision=4)


def test_targeted_resolution_never_directly_edits_shared_state():
    conflict = issue(role='body_text')
    response = {**envelope('structure_review'), 'mode': 'targeted', 'resolutions': [
        {'issue_id': conflict['id'], 'verdict': 'resolved', 'reason': '该位置可读', 'evidence': proof(),
         'proposal': {'target_role': 'body_text', 'instruction': '依据该位置重新完整转录题干'}}]}
    result = decode_targeted_review(response, [conflict], revision=4)
    assert result['requires_role_rerun'] and result['audit']['auto_applied_changes'] == 0
    response['resolutions'][0]['proposal']['target_role'] = 'connections'
    with pytest.raises(RoleProtocolError, match='targeted_authority_violation'):
        decode_targeted_review(response, [conflict], revision=4)


@pytest.mark.parametrize('mutation', ['revision', 'edge', 'weight', 'uncertainty', 'body', 'raw_vote'])
def test_solver_requires_same_reviewed_revision_inventory_and_full_body(mutation):
    graphs = [graph()]; local = hints(); text = local['items'][0]['text']
    review = decode_review_response(review_response(graphs, local, text), graphs,
                                    body_complete=True, hints=local, revision=4)
    assert build_solver_input(graphs, text, review, revision=4)['recognition_review'] == 'accepted'
    revision = 4
    if mutation == 'revision': revision = 5
    if mutation == 'edge': graphs[0]['edges'][0]['to'] = 'a'
    if mutation == 'weight': graphs[0]['edges'][0]['weight'] = 8
    if mutation == 'uncertainty': graphs[0]['uncertain_edges'].append('new_pixel_conflict')
    if mutation == 'body': text = text.replace('v₅', 'v₃')
    if mutation == 'raw_vote': review = {'verdict': 'accept', 'base_revision': 4}
    with pytest.raises(RoleProtocolError, match='solver_'):
        build_solver_input(graphs, text, review, revision=revision)


def observed_body_review():
    local = {'items': [], 'issues': [], 'local_status': 'unavailable'}
    lines = ['(1) 写出矩阵。', '(2) 写出通路。', '(3) 求回路。']
    regions = [{'id': 'body_'+str(i), 'role': 'body', 'text': line,
                'source': 'original', 'bbox': [50, i*40, 950, (i+1)*40]}
               for i, line in enumerate(lines, 1)]
    response = review_response([graph()], local, '\n'.join(lines))
    response['body_coverage']['observed_region_ids'] = [r['id'] for r in regions]
    response['body_region_review'] = [{'id': r['id'], 'role': 'body', 'text': r['text']} for r in regions]
    return response, regions, local


def test_no_paddle_hints_still_requires_each_independently_located_question():
    response, regions, local = observed_body_review()
    accepted = decode_review_response(response, [graph()], body_complete=True,
                                      hints=local, revision=4, body_regions=regions)
    assert accepted['verdict'] == 'accept'
    response['text_review']['text'] = regions[0]['text']
    with pytest.raises(RoleProtocolError, match='body_fragment_not_in_text'):
        decode_review_response(response, [graph()], body_complete=True,
                               hints=local, revision=4, body_regions=regions)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'unknown', 'coverage'])
def test_observed_body_region_identity_coverage_is_exact(mutation):
    response, regions, local = observed_body_review()
    if mutation == 'missing': response['body_region_review'].pop()
    if mutation == 'duplicate': response['body_region_review'].append(copy.deepcopy(response['body_region_review'][0]))
    if mutation == 'unknown': response['body_region_review'][0]['id'] = 'not_observed'
    if mutation == 'coverage': response['body_coverage']['observed_region_ids'].pop()
    with pytest.raises(RoleProtocolError, match='body'):
        decode_review_response(response, [graph()], body_complete=True,
                               hints=local, revision=4, body_regions=regions)


def test_observed_body_rewrite_needs_its_own_original_location():
    response, regions, local = observed_body_review()
    response['text_review']['text'] = response['text_review']['text'].replace('通路', '回路')
    changed = response['body_region_review'][1]
    changed.update(text=changed['text'].replace('通路', '回路'), reason='该位置原文是回路')
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        decode_review_response(response, [graph()], body_complete=True,
                               hints=local, revision=4, body_regions=regions)
    changed['evidence'] = proof(regions[0]['bbox'])
    with pytest.raises(RoleProtocolError, match='text_evidence_wrong_location'):
        decode_review_response(response, [graph()], body_complete=True,
                               hints=local, revision=4, body_regions=regions)
    changed['evidence'] = proof(regions[1]['bbox'])
    assert decode_review_response(response, [graph()], body_complete=True,
        hints=local, revision=4, body_regions=regions)['verdict'] == 'accept'


def test_observed_body_deletion_requires_located_evidence_but_is_not_forbidden():
    response, regions, local = observed_body_review()
    response['text_review']['text'] = '\n'.join(r['text'] for r in regions[:2])
    removed = response['body_region_review'][2]
    removed.update(role='noise', reason='该区域属于透印，不是正面题干')
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        decode_review_response(response, [graph()], body_complete=True,
                               hints=local, revision=4, body_regions=regions)
    removed['evidence'] = proof(regions[2]['bbox'])
    assert decode_review_response(response, [graph()], body_complete=True,
        hints=local, revision=4, body_regions=regions)['verdict'] == 'accept'


def test_unlocated_new_body_sentence_cannot_be_certified_by_a_general_reason():
    response, regions, local = observed_body_review()
    response['text_review']['text'] += '\n(4) 判断是否有向。'
    response['text_review']['reason'] = '重新读过原图'
    with pytest.raises(RoleProtocolError, match='review_body_regions_do_not_cover_text'):
        decode_review_response(response, [graph()], body_complete=True,
                               hints=local, revision=4, body_regions=regions)


@pytest.mark.parametrize('wide', [False, True])
def test_attribute_evidence_far_from_its_edge_is_rejected_even_in_same_panel(wide):
    g = graph(); g['edges'][0]['path'] = [[.2, .7], [.8, .7]]
    response = attribute_response([g])
    row = response['graphs'][0]['edges'][0]
    row.update(attributes={'weight': 9}, evidence=proof([110, 250, 890 if wide else 300, 300]))
    with pytest.raises(RoleProtocolError, match='attribute_evidence_wrong_edge'):
        merge_attribute_response([g], response, revision=4)


def test_small_label_box_beside_ink_and_arrow_box_near_endpoint_are_accepted():
    g = graph(); g['edges'][0]['path'] = [[.2, .5], [.8, .5]]
    response = attribute_response([g]); row = response['graphs'][0]['edges'][0]
    row.update(attributes={'weight': 9}, evidence=proof([480, 455, 520, 475]))
    updated, _ = merge_attribute_response([g], response, revision=4)
    assert updated[0]['edges'][0]['weight'] == 9
    row.update(attributes={'direction': 'reverse'}, evidence=proof([775, 480, 810, 520]))
    updated, _ = merge_attribute_response([g], response, revision=4)
    assert updated[0]['edges'][0]['from'] == 'b'
    assert updated[0]['edges'][0]['path'] == [[.8, .5], [.2, .5]]


def test_attribute_cannot_borrow_a_nearer_parallel_edge_label():
    g = graph(); g['edges'][0]['path'] = [[.2, .5], [.8, .5]]
    g['edges'].append({**copy.deepcopy(g['edges'][0]), 'id': 'e2',
                       'path': [[.2, .53], [.8, .53]]})
    response = attribute_response([g]); row = response['graphs'][0]['edges'][0]
    row.update(attributes={'weight': 9}, evidence=proof([480, 526, 520, 534]))
    with pytest.raises(RoleProtocolError, match='attribute_evidence_belongs_to_other_edge'):
        merge_attribute_response([g], response, revision=4)


def test_whole_panel_box_cannot_authorize_an_attribute_rewrite():
    g = graph(); response = attribute_response([g]); row = response['graphs'][0]['edges'][0]
    row.update(attributes={'weight': 9}, evidence=proof([v*1000 for v in g['bbox']]))
    with pytest.raises(RoleProtocolError, match='attribute_evidence_not_localized'):
        merge_attribute_response([g], response, revision=4)


def test_located_regions_are_the_single_body_source_without_redundant_fields():
    local = {'items': [], 'issues': [], 'local_status': 'unavailable'}
    response = body_response('(1) 求 v₃ 的通路。\n(2) 计算 x²。', local=local)
    response.pop('body_text'); response.pop('text_review')
    original = copy.deepcopy(response)
    result = decode_body_response(response, hints=local, revision=4)
    assert response == original
    assert result['body_complete'] and result['body_text'] == response['regions'][0]['text']
    assert result['text_review']['text'] == result['body_text']
    assert result['text_review']['regions'] == []
    response.pop('body_complete')
    with pytest.raises(RoleProtocolError, match='invalid_body_transcription'):
        decode_body_response(response, hints=local, revision=4)


@pytest.mark.parametrize('markup', [r'求 $v_3$ 并计算 \(x^2\)。', r'求 \[v_{3}\] 并计算 $$x^{2}$$。'])
def test_body_format_equivalence_preserves_raw_region_spelling_and_indices(markup):
    local = hints(markup)
    response = body_response('求 v₃ 并计算 x²。', local=local)
    response['body_text'] = markup
    response['text_review'] = {'text': markup, 'regions': [{'id': 't1', 'role': 'body'}]}
    result = decode_body_response(response, hints=local, revision=4)
    assert result['body_complete'] and result['body_text'] == '求 v₃ 并计算 x²。'
    assert result['text_review']['text'] == result['body_text']
    assert result['text_review']['regions'][0]['text'] == markup
    assert result['audit']['reconciliation']['conflicts'] == []


@pytest.mark.parametrize(('canonical', 'redundant'), [
    ('v₃', 'v3'), ('v₃', 'v₅'), ('v₁₂', 'v_12'), ('x²', 'x2'),
    ('至少三条边', '至多三条边'), ('α≤β', 'α<β'), ('v₃', 'V₃'),
])
def test_substantive_or_ambiguous_format_differences_cannot_be_hidden_in_redundancy(canonical, redundant):
    response = body_response(canonical, local={'items': []})
    response['body_text'] = redundant
    with pytest.raises(RoleProtocolError, match='body_regions_do_not_cover_transcription') as caught:
        decode_body_response(response, hints={'items': []}, revision=4)
    assert caught.value.audit['expected']['region_text'] == canonical
    assert caught.value.audit['actual']['body_text'] == redundant


def test_omitted_hint_text_requires_unique_unchanged_fragment_and_all_hint_ids():
    local = hints('x²')
    response = body_response('计算 x²。', local=local)
    response.pop('body_text')
    response['text_review'] = {'regions': [{'id': 't1', 'role': 'body'}]}
    assert decode_body_response(response, hints=local, revision=4)['body_complete']
    for text in ('计算 x³。', '计算 x²，然后比较 x²。'):
        response['regions'][0]['text'] = text
        with pytest.raises(RoleProtocolError, match='body_fragment_text_not_derivable') as caught:
            decode_body_response(response, hints=local, revision=4)
        assert caught.value.audit['hint_id'] == 't1'
    response['text_review']['regions'] = []
    with pytest.raises(RoleProtocolError, match='text_review_regions_incomplete'):
        decode_body_response(response, hints=local, revision=4)


def test_overlapping_body_fragments_are_not_a_unique_omitted_text_match():
    local = hints('aa')
    response = body_response('aaa', local=local)
    response['text_review']['regions'][0].pop('text')
    with pytest.raises(RoleProtocolError, match='body_fragment_text_not_derivable') as caught:
        decode_body_response(response, hints=local, revision=4)
    assert caught.value.audit['match_count'] == 'multiple'


def test_body_fragment_rejection_keeps_bounded_expected_actual_context():
    local = hints('求 v₅')
    response = body_response('题干' * 1000, local=local)
    response['text_review']['regions'][0]['text'] = '求 v₅'
    with pytest.raises(RoleProtocolError, match='body_fragment_not_in_text') as caught:
        decode_body_response(response, hints=local, revision=4)
    audit = caught.value.audit
    assert audit['hint_id'] == 't1' and audit['actual']['text'] == '求 v₅'
    assert audit['expected_hint']['bbox'] == local['items'][0]['bbox']
    assert len(audit['expected']['body_text']) <= 160
    assert audit['accepted'] is False


def test_raw_previous_body_without_redundancy_cannot_be_silently_deleted():
    local = {'items': []}
    previous = body_response('不能凭空删除的小问', local=local)
    previous.pop('body_text'); previous.pop('text_review')
    response = body_response('', local=local)
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        decode_body_response(response, hints=local, previous=previous, revision=4)


def test_format_reconciliation_keeps_original_output_and_still_flags_real_change():
    first = {'body_text': '求 v₃', 'body_complete': True}
    second = {'text_review': {'text': r'求 $v_3$', 'complete': True,
                             'regions': [{'id': 't1', 'role': 'body', 'text': r'求 \(v_{3}\)'}]}}
    local = hints('求 v₃')
    originals = copy.deepcopy((first, second, local))
    text, complete, audit = reconcile_role_text(first, second, local, [graph()])
    assert complete and text == second['text_review']['text'] and audit['conflicts'] == []
    assert audit['region_decisions'][0]['text'] == second['text_review']['regions'][0]['text']
    assert (first, second, local) == originals
    second['text_review']['text'] = '求 v₅'
    second['text_review']['regions'][0]['text'] = '求 v₅'
    _, complete, audit = reconcile_role_text(first, second, local, [graph()])
    assert not complete and 'unexplained_visual_text_change' in audit['issues']


def test_independent_final_body_review_uses_same_format_gate_without_losing_proof():
    response, regions, local = observed_body_review()
    regions[0]['text'] = '(1) 求 v₃。'
    response['body_region_review'][0]['text'] = r'(1) 求 $v_3$。'
    response['text_review']['text'] = '\n'.join(r['text'] for r in regions)
    checked = decode_review_response(response, [graph()], body_complete=True,
                                     hints=local, body_regions=regions, revision=4)
    assert checked['verdict'] == 'accept'
    response['body_region_review'][0].update(text='(1) 求 v₅。', reason='实际下标不同')
    response['text_review']['text'] = response['text_review']['text'].replace('v₃', 'v₅')
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        decode_review_response(response, [graph()], body_complete=True,
                               hints=local, body_regions=regions, revision=4)


def test_independent_edge_can_omit_a_candidate_binding_without_changing_endpoint_gate():
    g = graph()
    candidate = {**copy.deepcopy(g['edges'][0]), 'id': 'px_1', 'from': 'a', 'to': 'a'}
    proposals = {'G1': [candidate]}
    response = connection_response([g], candidates=proposals)
    result = validate_connection_response(response, [g], proposals, revision=4)
    assert result['graphs'][0]['edges'][0]['id'] == 'e1'
    assert 'candidate_id' not in result['graphs'][0]['edges'][0]
    response['graphs'][0]['edges'][0]['candidate_id'] = 'px_1'
    with pytest.raises(RoleProtocolError, match='changed_candidate_endpoints') as caught:
        validate_connection_response(response, [g], proposals, revision=4)
    audit = caught.value.audit
    assert (audit['graph_id'], audit['edge_id'], audit['candidate_id']) == ('G1', 'e1', 'px_1')
    assert audit['expected'] == {'from': 'a', 'to': 'a'}
    assert audit['actual'] == {'from': 'a', 'to': 'b'}


def test_empty_previous_inventory_cannot_retire_rejected_proposal_or_candidate_id():
    g = graph(edges=False)
    response = connection_response([g])
    response['graphs'][0]['retired_edges'] = [
        {'id': 'uncommitted_edge', 'reason': '上次失败提案中出现', 'evidence': proof()}]
    with pytest.raises(RoleProtocolError, match='unknown_or_duplicate_retired_edge') as caught:
        validate_connection_response(response, [g], {}, revision=4)
    audit = caught.value.audit
    assert audit['graph_id'] == 'G1' and audit['edge_id'] == 'uncommitted_edge'
    assert audit['expected_retirable_ids'] == [] and audit['expected_count'] == 0
    response['graphs'][0].pop('retired_edges')
    assert validate_connection_response(response, [g], {}, revision=4)['graphs'][0]['edges'] == []


def test_unknown_candidate_reference_is_a_role_error_with_targeted_ids():
    g = graph(); response = connection_response([g])
    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
    with pytest.raises(RoleProtocolError, match='unknown_candidate_reference') as caught:
        validate_connection_response(response, [g], {}, revision=4)
    assert caught.value.audit['candidate_id'] == 'unknown_candidate'
    assert caught.value.audit['edge_id'] == 'e1' and caught.value.audit['expected_count'] == 0


@pytest.mark.parametrize('color', [None, True, 3, {}, '', 'x'*33, 'red\nblue'])
def test_connections_reject_invalid_optional_color_with_edge_identity(color):
    g = graph(); response = connection_response([g])
    response['graphs'][0]['edges'][0]['color'] = color
    with pytest.raises(RoleProtocolError, match='invalid_connection_color') as caught:
        validate_connection_response(response, [g], {}, revision=4)
    assert caught.value.audit['graph_id'] == 'G1' and caught.value.audit['edge_id'] == 'e1'


def position_review_response(*, verdict='confirmed', cropped=False):
    g = graph()
    if cropped:
        g['vertices'][0]['x'] = .1004
    response = review_response([g])
    vertex = g['vertices'][0]
    point = [round(vertex['x']*1000), round(vertex['y']*1000)]
    bounds = [100, 485, 118, 515] if cropped else [185, 485, 215, 515]
    response['graphs'][0]['vertex_position_review'] = [
        {'id': 'a', 'position': point, 'verdict': verdict,
         'evidence': proof(bounds, '边界处可见裁切标记，保留该位置；邻近细线不能证明完整圆轮廓')}]
    return g, response, [{'graph_id': 'G1', 'vertex_ids': ['a']}]


def test_visual_position_review_accepts_locally_readable_cropped_marker_without_moving_it():
    g, response, checks = position_review_response(cropped=True)
    g['vertices'][0]['pixel_marker_status'] = 'not_detected'
    original = copy.deepcopy(g)
    checked = decode_review_response(response, [g], body_complete=True, hints=hints(),
                                     revision=4, position_checks=checks)
    assert checked['verdict'] == 'accept' and g == original
    observed = checked['audit']['position_checks'][0]
    assert observed['vertex_id'] == 'a' and observed['verdict'] == 'confirmed'
    assert observed['source'] == 'independent_visual_position_review'
    assert g['vertices'][0]['pixel_marker_status'] == 'not_detected'


@pytest.mark.parametrize(('mutation', 'code'), [
    ('omit', 'vertex_position_review_incomplete'), ('duplicate', 'vertex_position_review_duplicate_id'),
    ('unknown', 'vertex_position_review_unknown_id'), ('other_known', 'vertex_position_review_unknown_id'),
    ('old_coordinate', 'reviewed_position_changed'), ('other_point', 'position_evidence_does_not_contain_vertex'),
    ('whole_page', 'position_evidence_wrong_panel'), ('whole_panel', 'position_evidence_not_localized'),
    ('invalid_verdict', 'invalid_position_review_verdict'),
])
def test_position_review_rejects_false_or_incomplete_coverage(mutation, code):
    g, response, checks = position_review_response()
    rows = response['graphs'][0]['vertex_position_review']; row = rows[0]
    if mutation == 'omit': rows.clear()
    if mutation == 'duplicate': rows.append(copy.deepcopy(row))
    if mutation == 'unknown': row['id'] = 'invented'
    if mutation == 'other_known': row['id'] = 'b'
    if mutation == 'old_coordinate': row['position'][0] -= 1
    if mutation == 'other_point': row['evidence'] = proof([785, 485, 815, 515])
    if mutation == 'whole_page': row['evidence'] = proof([0, 0, 1000, 1000])
    if mutation == 'whole_panel': row['evidence'] = proof([100, 200, 900, 900])
    if mutation == 'invalid_verdict': row['verdict'] = 'looks_ok'
    with pytest.raises(RoleProtocolError, match=code) as caught:
        decode_review_response(response, [g], body_complete=True, hints=hints(),
                               revision=4, position_checks=checks)
    assert caught.value.audit['graph_id'] == 'G1'


@pytest.mark.parametrize('verdict', ['uncertain', 'needs_revision'])
def test_unresolved_position_review_keeps_specific_reason_and_routes_to_page_role(verdict):
    g, response, checks = position_review_response(verdict=verdict)
    original = copy.deepcopy(g)
    checked = decode_review_response(response, [g], body_complete=True, hints=hints(),
                                     revision=4, position_checks=checks)
    assert checked['verdict'] == 'needs_review' and not checked['audit']['accepted'] and g == original
    issue = next(i for i in checked['issues'] if i['kind'] == 'vertex_position_' + verdict)
    assert issue['target_role'] == 'page_vertices' and issue['graph_id'] == 'G1'
    assert issue['vertex_ids'] == ['a'] and issue['id'].startswith('position_review_')
    assert issue['reason'] == response['graphs'][0]['vertex_position_review'][0]['evidence']['reason']
    assert issue['evidence']['bbox'] == [185, 485, 215, 515]


def test_default_review_needs_no_position_rows_and_confirmation_cannot_mask_other_failures():
    g = graph(); response = review_response([g])
    checked = decode_review_response(response, [g], body_complete=True, hints=hints(), revision=4)
    assert checked['verdict'] == 'accept' and checked['audit']['position_checks'] == []
    g, response, checks = position_review_response()
    g['complete'] = False
    checked = decode_review_response(response, [g], body_complete=True, hints=hints(),
                                     revision=4, position_checks=checks)
    assert checked['verdict'] == 'needs_review'


def test_missing_body_source_is_audited_contract_default_without_rewriting_text():
    response = body_response('比较 p 与 q；', local={'items': []})
    response['regions'][0].pop('source')
    original = copy.deepcopy(response)
    result = decode_body_response(response, hints={'items': []}, revision=4)
    assert response == original and result['body_text'] == '比较 p 与 q；'
    assert result['regions'][0]['source'] == 'original'
    assert result['audit']['normalizations'] == [{
        'region_id': 'paragraph_1', 'field': 'source', 'value': 'original',
        'derived_from': 'body_role_original_1000_contract'}]
    assert result['body_complete']


@pytest.mark.parametrize('source', [None, 'ocr', 'crop_reconstruction'])
def test_explicit_wrong_body_source_is_never_normalized(source):
    response = body_response('原文', local={'items': []})
    response['regions'][0]['source'] = source
    with pytest.raises(RoleProtocolError, match='invalid_body_region_source') as caught:
        decode_body_response(response, hints={'items': []}, revision=4)
    assert caught.value.audit['region_id'] == 'paragraph_1'
    assert caught.value.audit['actual']['source'] == source


def test_missing_body_source_does_not_hide_punctuation_conflict_or_invalid_location():
    local = hints('比较 p 与 q：')
    response = body_response('比较 p 与 q；', local=local)
    response['regions'][0].pop('source')
    response['text_review']['regions'][0]['text'] = '比较 p 与 q：'
    with pytest.raises(RoleProtocolError, match='body_fragment_not_in_text') as caught:
        decode_body_response(response, hints=local, revision=4)
    assert caught.value.audit['hint_id'] == 't1'
    response['regions'][0]['bbox'] = [40, 20, 40, 80]
    with pytest.raises(RoleProtocolError, match='body_region_bbox_invalid'):
        decode_body_response(response, hints=local, revision=4)


@pytest.mark.parametrize('bounds', [[520, 380, 480, 420], [480, 420, 520, 380], [520, 420, 480, 380]])
def test_attribute_opposite_corners_normalize_only_rectangle_order_with_audit(bounds):
    g = graph(); response = attribute_response([g])
    row = response['graphs'][0]['edges'][0]
    row.update(attributes={'color': 'blue'}, evidence=proof(bounds))
    original = copy.deepcopy(response)
    updated, audit = merge_attribute_response([g], response, revision=4)
    assert response == original and updated[0]['edges'][0]['path'] == g['edges'][0]['path']
    assert updated[0]['edges'][0]['status'] == 'pending' and audit['requires_pixel_revalidation']
    assert audit['normalizations'] == [{'graph_id': 'G1', 'edge_id': 'e1', 'field': 'evidence.bbox',
        'bbox': [480., 380., 520., 420.], 'kind': 'ordered_opposite_corners', 'original_bbox': bounds}]
    assert audit['changes'][0]['evidence']['bbox_normalization']['original_bbox'] == bounds


@pytest.mark.parametrize('bounds', [[480, 380, 480, 420], [480, 380, 520, 380], [1020, 420, 480, 380]])
def test_attribute_box_normalization_never_pads_or_clamps_invalid_evidence(bounds):
    g = graph(); response = attribute_response([g])
    response['graphs'][0]['edges'][0]['evidence'] = proof(bounds)
    with pytest.raises(RoleProtocolError, match='original_evidence_bbox_invalid') as caught:
        merge_attribute_response([g], response, revision=4)
    assert caught.value.audit['graph_id'] == 'G1' and caught.value.audit['edge_id'] == 'e1'
    assert caught.value.audit['actual'] == bounds


@pytest.mark.parametrize(('bounds', 'code'), [
    ([320, 300, 280, 250], 'attribute_evidence_wrong_edge'),
    ([900, 900, 100, 200], 'attribute_evidence_not_localized'),
])
def test_reordered_box_still_needs_the_same_edge_and_locality(bounds, code):
    g = graph(); response = attribute_response([g])
    response['graphs'][0]['edges'][0].update(attributes={'color': 'blue'}, evidence=proof(bounds))
    with pytest.raises(RoleProtocolError, match=code):
        merge_attribute_response([g], response, revision=4)


def test_connection_graph_type_updates_use_one_explicit_original_evidence_object():
    g = graph()
    for field in ('directed', 'weighted', 'multigraph'):
        g[field] = 'unknown'
    response = connection_response([g]); row = response['graphs'][0]
    row.update(directed=False, weighted=False, multigraph=False,
               type_evidence=proof([900, 900, 100, 200]))
    checked = validate_connection_response(response, [g], {}, revision=4)['graphs'][0]
    assert all(checked[field] is False for field in ('directed', 'weighted', 'multigraph'))
    assert checked['type_evidence']['bbox'] == [100., 200., 900., 900.]
    assert checked['type_evidence']['bbox_normalization']['original_bbox'] == [900, 900, 100, 200]
    row['type_evidence'] = {'directed': proof(), 'weighted': proof(), 'multigraph': proof()}
    with pytest.raises(RoleProtocolError, match='original_evidence_missing') as caught:
        validate_connection_response(response, [g], {}, revision=4)
    assert caught.value.audit['graph_id'] == 'G1'
    assert caught.value.audit['fields'] == ['directed', 'weighted', 'multigraph']


def test_absent_graph_types_remain_compatible_without_inference_from_edge_direction():
    g = graph(); g['directed'] = g['weighted'] = 'unknown'
    response = connection_response([g])
    checked = validate_connection_response(response, [g], {}, revision=4)['graphs'][0]
    assert 'directed' not in checked and 'weighted' not in checked
    assert g['directed'] == g['weighted'] == 'unknown'


def reusable_curved_candidate():
    g = graph()
    candidate = {**copy.deepcopy(g['edges'][0]), 'id': 'curve_1',
        'path': [[.2, .5], [.3, .25], [.6, .2], [.8, .5]],
        'pixel_evidence': {'source': 'original_pixel_route', 'supported': True}}
    proposals = {'G1': [candidate]}
    response = connection_response([g], candidates=proposals)
    row = response['graphs'][0]
    row['edges'][0]['candidate_id'] = 'curve_1'
    row['edges'][0].pop('path')
    row['candidate_verdicts'] = [['curve_1', True]]
    return g, candidate, proposals, response


@pytest.mark.parametrize('reversed_edge', [False, True])
@pytest.mark.parametrize('source', ['original_pixel_route', 'original_pixel_connector_boundaries'])
def test_explicit_pixel_candidate_reuses_every_curve_sample_in_endpoint_order(reversed_edge, source):
    g, candidate, proposals, response = reusable_curved_candidate()
    candidate['pixel_evidence']['source'] = source
    raw = response['graphs'][0]['edges'][0]
    if reversed_edge:
        raw['from'], raw['to'] = raw['to'], raw['from']
    original = copy.deepcopy((g, proposals, response))
    checked = validate_connection_response(response, [g], proposals, revision=4)
    expected = [[x*1000, y*1000] for x, y in candidate['path']]
    if reversed_edge: expected.reverse()
    assert checked['graphs'][0]['edges'][0]['path'] == expected
    assert checked['graphs'][0]['edges'][0]['id'] == 'e1'
    assert checked['protocol_normalizations'] == [{'graph_id': 'G1', 'edge_id': 'e1', 'field': 'path',
        'candidate_id': 'curve_1', 'derived_from': 'validated_original_candidate',
        'reversed': reversed_edge, 'point_count': 4}]
    assert (g, proposals, response) == original


@pytest.mark.parametrize('mutation', ['no_id', 'legacy_only', 'wrong_endpoints', 'unknown_id',
                                      'nonfinite', 'wrong_units', 'unsupported', 'model_proof'])
def test_candidate_path_reuse_requires_explicit_identity_and_valid_original_route(mutation):
    g, candidate, proposals, response = reusable_curved_candidate()
    raw = response['graphs'][0]['edges'][0]
    if mutation == 'no_id': raw.pop('candidate_id')
    if mutation == 'legacy_only':
        raw.pop('candidate_id'); raw['id'] = 'curve_1'
    if mutation == 'wrong_endpoints': candidate['to'] = 'a'
    if mutation == 'unknown_id': raw['candidate_id'] = 'not_in_this_panel'
    if mutation == 'nonfinite': candidate['path'][1][0] = float('nan')
    if mutation == 'wrong_units': candidate['path'][1][0] = 300
    if mutation == 'unsupported': candidate['pixel_evidence']['supported'] = False
    if mutation == 'model_proof':
        raw['pixel_evidence'] = copy.deepcopy(candidate.pop('pixel_evidence'))
    code = {'wrong_endpoints': 'changed_candidate_endpoints', 'unknown_id': 'unknown_candidate_reference',
            'nonfinite': 'invalid_candidate_reuse_path', 'wrong_units': 'invalid_candidate_reuse_path',
            'unsupported': 'candidate_path_not_pixel_validated',
            'model_proof': 'candidate_path_not_pixel_validated'}.get(mutation, 'path_requires_explicit_candidate')
    with pytest.raises(RoleProtocolError, match=code) as caught:
        validate_connection_response(response, [g], proposals, revision=4)
    assert caught.value.audit['graph_id'] == 'G1'


@pytest.mark.parametrize('path', [None, []])
def test_present_invalid_path_is_not_silently_replaced_by_a_candidate(path):
    g, _, proposals, response = reusable_curved_candidate()
    response['graphs'][0]['edges'][0]['path'] = path
    with pytest.raises(RoleProtocolError, match='invalid_connection_path'):
        validate_connection_response(response, [g], proposals, revision=4)


def test_explicit_independent_curve_is_not_changed_by_a_candidate_reference():
    g, _, proposals, response = reusable_curved_candidate()
    path = [[200, 500], [400, 340], [650, 330], [800, 500]]
    response['graphs'][0]['edges'][0]['path'] = path
    checked = validate_connection_response(response, [g], proposals, revision=4)
    assert checked['graphs'][0]['edges'][0]['path'] == path
    assert checked['protocol_normalizations'] == []


def unbound_equivalent_candidate():
    g = graph()
    candidate = {**copy.deepcopy(g['edges'][0]), 'id': 'measured_curve',
                 'pixel_evidence': {'source': 'original_pixel_route', 'supported': True}}
    proposals = {'G1': [candidate]}
    response = connection_response([g], candidates=proposals)
    row = response['graphs'][0]
    row['edges'][0]['path'] = [[200, 500], [350, 450], [500, 400], [650, 450], [800, 500]]
    row['candidate_verdicts'] = [['measured_curve', True]]
    return g, candidate, proposals, response


@pytest.mark.parametrize('source', ['original_pixel_route', 'original_pixel_connector_boundaries'])
@pytest.mark.parametrize('reverse', [False, True])
def test_missing_reference_only_is_normalized_for_unique_same_full_polyline(source, reverse):
    g, candidate, proposals, response = unbound_equivalent_candidate()
    candidate['pixel_evidence']['source'] = source
    raw = response['graphs'][0]['edges'][0]
    raw['path'].insert(2, copy.deepcopy(raw['path'][1]))  # Duplicate sample, not another vertex.
    if reverse:
        raw['from'], raw['to'] = raw['to'], raw['from']
        raw['path'].reverse()
    response['audit'] = {'normalizations': ['model_forgery']}
    original = copy.deepcopy((g, proposals, response))
    checked = validate_connection_response(response, [g], proposals, revision=4)
    edge = checked['graphs'][0]['edges'][0]
    assert edge == {**raw, 'candidate_id': 'measured_curve'}
    assert checked['graphs'][0]['candidate_verdicts'] == [['measured_curve', True]]
    normalization = checked['audit']['normalizations'][0]
    assert checked['audit']['normalizations'] == checked['protocol_normalizations']
    assert normalization['field'] == 'candidate_id' and normalization['edge_id'] == 'e1'
    assert normalization['proof_source'] == source and normalization['reversed'] is reverse
    assert normalization['requires_original_pixel_revalidation'] is True
    assert normalization['maximum_distance_original_1000'] < 1e-6
    assert (g, proposals, response) == original


def test_only_rounding_scale_displacement_is_accepted_for_missing_binding():
    g, candidate, proposals, response = unbound_equivalent_candidate()
    candidate['path'] = [[x + .00049, y + .00049] for x, y in candidate['path']]
    checked = validate_connection_response(response, [g], proposals, revision=4)
    distance = checked['audit']['normalizations'][0]['maximum_distance_original_1000']
    assert .69 < distance < .70
    candidate['path'] = [[x + .00005, y + .00005] for x, y in candidate['path']]
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], proposals, revision=4)


@pytest.mark.parametrize('vote', [False, None])
def test_false_or_unknown_vote_is_never_changed_or_bound_implicitly(vote):
    g, _, proposals, response = unbound_equivalent_candidate()
    response['graphs'][0]['candidate_verdicts'][0][1] = vote
    checked = validate_connection_response(response, [g], proposals, revision=4)
    assert 'candidate_id' not in checked['graphs'][0]['edges'][0]
    assert checked['graphs'][0]['candidate_verdicts'][0][1] is vote
    assert checked['audit']['normalizations'] == []


@pytest.mark.parametrize('mutation', ['unsupported', 'foreign_proof', 'model_proof', 'missing_path',
                                      'nonfinite_path', 'wrong_units', 'too_many_samples', 'explicit_null'])
def test_implicit_binding_needs_caller_owned_supported_original_complete_path(mutation):
    g, candidate, proposals, response = unbound_equivalent_candidate()
    raw = response['graphs'][0]['edges'][0]
    if mutation == 'unsupported': candidate['pixel_evidence']['supported'] = False
    if mutation == 'foreign_proof': candidate['pixel_evidence']['source'] = 'model_inferred'
    if mutation == 'model_proof': raw['pixel_evidence'] = candidate.pop('pixel_evidence')
    if mutation == 'missing_path': candidate.pop('path')
    if mutation == 'nonfinite_path': candidate['path'][1][0] = float('nan')
    if mutation == 'wrong_units': candidate['path'][1][0] = 500
    if mutation == 'too_many_samples': candidate['path'] = [candidate['path'][0]] * 129
    if mutation == 'explicit_null': raw['candidate_id'] = None
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], proposals, revision=4)
    assert 'candidate_id' not in raw or raw['candidate_id'] is None


@pytest.mark.parametrize('mutation', ['chord', 'other_arc', 'backtracking', 'wrong_endpoint'])
def test_implicit_binding_never_turns_same_endpoints_into_curve_equivalence(mutation):
    g, candidate, proposals, response = unbound_equivalent_candidate()
    raw = response['graphs'][0]['edges'][0]
    if mutation == 'chord': raw['path'] = [[200, 500], [800, 500]]
    if mutation == 'other_arc': raw['path'] = [[200, 500], [500, 600], [800, 500]]
    if mutation == 'backtracking':
        raw['path'] = [[200, 500], [500, 400], [200, 500], [500, 400], [800, 500]]
    if mutation == 'wrong_endpoint': candidate['to'] = 'a'
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], proposals, revision=4)


@pytest.mark.parametrize('vote, supported', [(True, True), (False, True), (None, True), (False, False)])
def test_parallel_candidate_ambiguity_is_not_removed_by_vote_or_support_filter(vote, supported):
    g, candidate, proposals, response = unbound_equivalent_candidate()
    parallel = copy.deepcopy(candidate)
    parallel.update(id='parallel_curve', path=[[x, y + .0004] for x, y in candidate['path']])
    parallel['pixel_evidence']['supported'] = supported
    proposals['G1'].append(parallel)
    response['graphs'][0]['candidate_verdicts'].append(['parallel_curve', vote])
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], proposals, revision=4)


def test_two_model_edge_records_cannot_borrow_one_unique_candidate_instance():
    g, _, proposals, response = unbound_equivalent_candidate()
    row = response['graphs'][0]
    duplicate = copy.deepcopy(row['edges'][0]); duplicate['id'] = 'e2'
    row['edges'].append(duplicate)
    for read in row['reads']: read['edge_ids'].append('e2')
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], proposals, revision=4)


def test_different_parallel_arcs_can_each_have_one_unique_geometry_binding():
    g, candidate, proposals, response = unbound_equivalent_candidate()
    parallel = copy.deepcopy(candidate)
    parallel.update(id='lower_curve', path=[[.2, .5], [.5, .6], [.8, .5]])
    proposals['G1'].append(parallel)
    row = response['graphs'][0]
    edge = copy.deepcopy(row['edges'][0]); edge.update(id='e2', path=[[200, 500], [500, 600], [800, 500]])
    row['edges'].append(edge)
    row['candidate_verdicts'].append(['lower_curve', True])
    for read in row['reads']: read['edge_ids'].append('e2')
    checked = validate_connection_response(response, [g], proposals, revision=4)
    assert [e['candidate_id'] for e in checked['graphs'][0]['edges']] == ['measured_curve', 'lower_curve']


@pytest.mark.parametrize('reference', ['not_a_candidate', 'wrong_endpoints'])
def test_explicit_wrong_binding_is_not_replaced_with_the_unique_geometric_match(reference):
    g, candidate, proposals, response = unbound_equivalent_candidate()
    raw = response['graphs'][0]['edges'][0]
    raw['candidate_id'] = reference
    if reference == 'wrong_endpoints':
        wrong = copy.deepcopy(candidate); wrong.update(id=reference, to='a')
        proposals['G1'].append(wrong)
        response['graphs'][0]['candidate_verdicts'].append([reference, True])
    code = 'unknown_candidate_reference' if reference == 'not_a_candidate' else 'changed_candidate_endpoints'
    with pytest.raises(RoleProtocolError, match=code):
        validate_connection_response(response, [g], proposals, revision=4)
    assert raw['candidate_id'] == reference


def test_candidate_capacity_cannot_create_a_false_unique_implicit_reference():
    g, candidate, proposals, response = unbound_equivalent_candidate()
    for index in range(256):
        other = copy.deepcopy(candidate); other['id'] = 'other_'+str(index)
        other['path'] = [[.2, .5], [.5, .8], [.8, .5]]
        proposals['G1'].append(other)
        response['graphs'][0]['candidate_verdicts'].append([other['id'], False])
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], proposals, revision=4)


def test_comparison_capacity_does_not_normalize_using_an_incomplete_uniqueness_search():
    g, candidate, proposals, response = unbound_equivalent_candidate()
    row = response['graphs'][0]
    row['edges'], row['candidate_verdicts'], proposals['G1'] = [], [], []
    for index in range(65):
        eid, cid = 'e'+str(index+1), 'route_'+str(index)
        path = [[.2, .5], [.5, .2 + index * .01], [.8, .5]]
        c = copy.deepcopy(candidate); c.update(id=cid, path=path)
        proposals['G1'].append(c)
        row['edges'].append({**copy.deepcopy(g['edges'][0]), 'id': eid,
                             'path': [[x*1000, y*1000] for x, y in path]})
        row['candidate_verdicts'].append([cid, True])
    for read in row['reads']: read['edge_ids'] = [edge['id'] for edge in row['edges']]
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage') as caught:
        validate_connection_response(response, [g], proposals, revision=4)
    assert caught.value.audit['normalizations'] == []


def test_tiny_segment_after_long_route_cannot_crash_or_prove_implicit_binding():
    g, candidate, proposals, response = unbound_equivalent_candidate()
    candidate['path'] = [[.2, .5], [.8, .5]] * 50 + [[.8000000000000002, .5]]
    response['graphs'][0]['edges'][0]['path'] = [[x*1000, y*1000] for x, y in candidate['path']]
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], proposals, revision=4)


@pytest.mark.parametrize('reverse', [False, True])
def test_unique_closed_loop_requires_the_entire_same_route(reverse):
    g, candidate, proposals, response = unbound_equivalent_candidate()
    g['edges'][0]['to'] = 'a'
    candidate.update(to='a', path=[[.2, .5], [.3, .3], [.1, .3], [.2, .5]])
    row = response['graphs'][0]
    row['edges'][0].update(to='a', path=[[200, 500], [300, 300], [100, 300], [200, 500]])
    row['reads'][1]['edge_ids'] = []
    if reverse: row['edges'][0]['path'].reverse()
    checked = validate_connection_response(response, [g], proposals, revision=4)
    assert checked['graphs'][0]['edges'][0]['candidate_id'] == 'measured_curve'
    assert checked['graphs'][0]['edges'][0]['path'] == row['edges'][0]['path']


def test_implicit_reference_is_only_metadata_and_original_pixels_still_reject_blank_ink():
    from PIL import Image
    from graph_evidence_pipeline import apply_topology
    from image_evidence import analyze_document
    g, _, proposals, response = unbound_equivalent_candidate()
    checked = validate_connection_response(response, [g], proposals, revision=4)
    output, diagnostics = apply_topology(checked, [g], proposals,
        analyze_document(Image.new('RGB', (300, 300), 'white')), panels_complete=True)
    assert checked['graphs'][0]['edges'][0]['candidate_id'] == 'measured_curve'
    assert not output[0]['complete'] and output[0]['edges'][0]['status'] == 'pending'
    assert any('unresolved_edge_evidence:e1' in message for message in diagnostics)


@pytest.mark.parametrize('explicit_path', [False, True])
def test_supported_explicit_candidate_can_supply_both_omitted_endpoints(explicit_path):
    g, candidate, proposals, response = reusable_curved_candidate()
    raw = response['graphs'][0]['edges'][0]
    raw.pop('from'); raw.pop('to')
    if explicit_path:
        raw['path'] = [[200, 500], [410, 270], [800, 500]]
    original = copy.deepcopy((g, proposals, response))
    checked = validate_connection_response(response, [g], proposals, revision=4)
    edge = checked['graphs'][0]['edges'][0]
    assert (edge['from'], edge['to']) == (candidate['from'], candidate['to'])
    assert edge['path'] == (raw['path'] if explicit_path else [[1000*x, 1000*y] for x, y in candidate['path']])
    assert checked['audit']['normalizations'][0] == {
        'graph_id': 'G1', 'edge_id': 'e1', 'field': 'from/to', 'candidate_id': 'curve_1',
        'derived_from': 'validated_original_candidate', 'from': 'a', 'to': 'b',
        'requires_original_pixel_revalidation': True}
    assert (g, proposals, response) == original


@pytest.mark.parametrize('mutation', ['only_from_missing', 'only_to_missing', 'both_null', 'from_null',
                                      'to_null', 'explicit_wrong', 'no_id', 'null_id', 'legacy_id',
                                      'unsupported', 'model_proof', 'nonfinite_path', 'foreign_endpoint'])
def test_endpoint_convenience_does_not_guess_null_partial_or_unsupported_bindings(mutation):
    g, candidate, proposals, response = reusable_curved_candidate()
    raw = response['graphs'][0]['edges'][0]
    raw['path'] = [[200, 500], [500, 400], [800, 500]]
    if mutation == 'only_from_missing': raw.pop('from')
    elif mutation == 'only_to_missing': raw.pop('to')
    elif mutation == 'both_null': raw['from'] = raw['to'] = None
    elif mutation == 'from_null': raw['from'] = None; raw.pop('to')
    elif mutation == 'to_null': raw['to'] = None; raw.pop('from')
    elif mutation == 'explicit_wrong': raw['to'] = 'a'
    else:
        raw.pop('from'); raw.pop('to')
        if mutation == 'no_id': raw.pop('candidate_id')
        if mutation == 'null_id': raw['candidate_id'] = None
        if mutation == 'legacy_id': raw.pop('candidate_id'); raw['id'] = 'curve_1'
        if mutation == 'unsupported': candidate['pixel_evidence']['supported'] = False
        if mutation == 'model_proof': raw['pixel_evidence'] = candidate.pop('pixel_evidence')
        if mutation == 'nonfinite_path': candidate['path'][1][0] = float('nan')
        if mutation == 'foreign_endpoint': candidate['to'] = 'another_panel_vertex'
    with pytest.raises(RoleProtocolError):
        validate_connection_response(response, [g], proposals, revision=4)


def rejected_connection_with_local_position_issue():
    g = graph()
    response = connection_response([g])
    response['graphs'][0]['candidate_verdicts'] = [['unknown_candidate', True]]
    observation = issue('vertex_position_1', role='page_vertices')
    observation.update(kind='missing_vertex_evidence', vertex_ids=['a'],
                       reason='当前冻结位置未见独立标记，请页面角色核对实际原图位置。',
                       evidence=proof([185, 485, 215, 515], '该小框只有背景线，未见节点轮廓'))
    response['issues'] = [observation]
    return g, response


def test_rejected_graph_can_preserve_only_independently_validated_upstream_issue():
    g, response = rejected_connection_with_local_position_issue()
    original = copy.deepcopy((g, response))
    with pytest.raises(RoleProtocolError, match='connection_candidate_coverage'):
        validate_connection_response(response, [g], {}, revision=4)
    kept = extract_rejected_role_issues(response, [g], role='connections', revision=4)
    assert len(kept) == 1 and kept[0]['target_role'] == 'page_vertices'
    assert kept[0]['vertex_ids'] == ['a'] and kept[0]['reason'] == response['issues'][0]['reason']
    assert kept[0]['source_revision'] == 4 and kept[0]['source_role'] == 'connections'
    assert kept[0]['scheduling_only'] is True
    assert 'graphs' not in kept[0] and (g, response) == original
    # Neither the invalid graph body nor an extra edit payload is considered.
    response['graphs'] = [{'id': 'fake_graph', 'vertices': [{'id': 'fake_vertex'}]}]
    response['issues'][0]['graph_edits'] = {'delete_all_vertices': True}
    assert extract_rejected_role_issues(response, [g], role='connections', revision=4) == kept


@pytest.mark.parametrize('mutation', ['stale', 'wrong_role', 'wrong_space', 'unknown_graph', 'fake_vertex',
    'fake_edge', 'uncommitted_edge', 'fake_hint', 'bad_bbox', 'wrong_panel', 'whole_page', 'no_source', 'bad_target'])
def test_rejected_issue_extraction_filters_unsafe_identity_or_evidence(mutation):
    g, response = rejected_connection_with_local_position_issue()
    row = response['issues'][0]
    if mutation == 'stale': response['base_revision'] = 3
    if mutation == 'wrong_role': response['role'] = 'structure_review'
    if mutation == 'wrong_space': response['coordinate_space'] = 'crop_1000'
    if mutation == 'unknown_graph': row['graph_id'] = 'invented'
    if mutation == 'fake_vertex': row['vertex_ids'] = ['invented']
    if mutation in ('fake_edge', 'uncommitted_edge'): row['edge_ids'] = ['draft_only']
    if mutation == 'uncommitted_edge':
        response['graphs'][0]['edges'].append({**copy.deepcopy(g['edges'][0]), 'id': 'draft_only'})
    if mutation == 'fake_hint': row['hint_ids'] = ['unknown_hint']
    if mutation == 'bad_bbox': row['evidence']['bbox'] = [200, 400, 200, 410]
    if mutation == 'wrong_panel': row['evidence']['bbox'] = [20, 20, 40, 40]
    if mutation == 'whole_page': row['evidence']['bbox'] = [0, 0, 1000, 1000]
    if mutation == 'no_source': row['evidence'].pop('source')
    if mutation == 'bad_target': row['target_role'] = 'solver'
    assert extract_rejected_role_issues(response, [g], role='connections', revision=4) == []


def test_rejected_issue_extraction_keeps_valid_sibling_but_rejects_duplicate_identity():
    g, response = rejected_connection_with_local_position_issue()
    valid = copy.deepcopy(response['issues'][0])
    invalid = copy.deepcopy(valid); invalid['id'] = 'bad'; invalid['vertex_ids'] = ['unknown']
    response['issues'].append(invalid)
    assert [i['id'] for i in extract_rejected_role_issues(response, [g], role='connections', revision=4)] == [valid['id']]
    response['issues'].append(copy.deepcopy(valid))
    assert extract_rejected_role_issues(response, [g], role='connections', revision=4) == []


def test_rejected_text_issue_cannot_borrow_known_hint_id_at_another_position():
    g, response = rejected_connection_with_local_position_issue()
    response['role'] = 'structure_review'
    row = response['issues'][0]
    row.update(target_role='body_text', graph_id=None, vertex_ids=[], hint_ids=['t1'],
               evidence=proof([50, 20, 850, 100]))
    assert len(extract_rejected_role_issues(response, [g], role='structure_review', revision=4, hints=hints())) == 1
    row['evidence'] = proof([185, 485, 215, 515])
    assert extract_rejected_role_issues(response, [g], role='structure_review', revision=4, hints=hints()) == []


def test_rejected_issue_extraction_is_closed_for_indeterminate_input_context():
    g, response = rejected_connection_with_local_position_issue()
    assert extract_rejected_role_issues(None, [g], role='connections', revision=4) == []
    assert extract_rejected_role_issues(response, [g], role=[], revision=4) == []
    assert extract_rejected_role_issues(response, [g], role='connections', revision=True) == []
    assert extract_rejected_role_issues(response, [{'id': 'G1'}], role='connections', revision=4) == []
