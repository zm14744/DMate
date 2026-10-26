"""Role boundaries and merge gates, using synthetic records only.

No original corpus, provider, model request, or claim about OCR accuracy.
"""
import copy

import pytest

from graph_agent_roles import (
    RoleProtocolError, build_solver_input, decode_body_response,
    decode_review_response, decode_targeted_review, merge_attribute_response,
    merge_body_response, validate_connection_response,
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
