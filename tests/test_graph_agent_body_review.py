"""Synthetic protocol cases only; no user images, gold, model or network."""
import copy

import pytest

from graph_agent_body_review import body_review_input_digest, decode_body_review_response
from graph_agent_roles import RoleProtocolError, build_solver_input


def proof(bbox=(40, 30, 880, 100), reason='逐字查看该行本身的原始字形'):
    return {'source': 'original', 'bbox': list(bbox), 'reason': reason}


def panels():
    return [{'id': 'panel_A', 'bbox': [.1, .4, .9, .95], 'complete': False,
             'directed': 'unknown', 'weighted': 'unknown', 'multigraph': 'unknown',
             'vertices': [{'id': 'p', 'x': .2, 'y': .6}, {'id': 'q', 'x': .7, 'y': .6}],
             'edges': []}]


def first(lines=('求集合 A₂ 的元素个数。',)):
    regions = [{'id': 'line_' + str(i), 'text': text, 'role': 'body', 'source': 'original',
                'bbox': [40, 30 + i * 85, 880, 100 + i * 85]}
               for i, text in enumerate(lines)]
    return {'role': 'body_text', 'base_revision': 0, 'role_valid': True,
            'coordinate_space': 'original_1000', 'body_text': '\n'.join(lines),
            'body_complete': True, 'regions': regions, 'issues': []}


def hints(body, *, empty=False):
    return {'items': [] if empty else [{'id': 'ocr_' + str(i), 'text': r['text'],
                                       'bbox': list(r['bbox'])}
                                      for i, r in enumerate(body['regions'])],
            'issues': [], 'local_status': 'unavailable' if empty else 'completed'}


def response(body, local, *, revision=2):
    def decision(r):
        return {'id': r['id'], 'role': r.get('role', 'body'), 'text': r['text'],
                'reason': '逐项查看该位置原始文字', 'evidence': proof(r['bbox'])}
    return {'role': 'body_review', 'base_revision': revision, 'coordinate_space': 'original_1000',
            'body_coverage': {'complete': True, 'region_ids': [r['id'] for r in local['items']],
                              'observed_region_ids': [r['id'] for r in body['regions']],
                              'evidence': proof([0, 0, 1000, 400])},
            'body_region_review': [decision(r) for r in body['regions']],
            'text_review': {'text': body['body_text'], 'complete': True,
                            'reason': '依据每行本身的原图逐字核对',
                            'regions': [decision(r) for r in local['items']]},
            'issues': []}


def decode(raw, body, local, graphs=None):
    return decode_body_review_response(raw, body, hints=local,
                                       graphs=panels() if graphs is None else graphs, revision=2)


def test_independent_body_review_works_without_validated_connections_and_cannot_accept_graphs():
    body = first(); local = hints(body); raw = response(body, local); graph = panels()
    before = copy.deepcopy((body, local, raw, graph))
    result = decode(raw, body, local, graph)
    assert result['body_complete'] and not result['issues'] and not result['model_issues']
    assert result['role'] == 'body_review' and result['body_text'] == body['body_text']
    assert result['regions'] == body['regions']
    assert result['raw_response'] == raw and result['raw_response'] is not raw
    assert (body, local, raw, graph) == before
    assert not any(k in result for k in ('graphs', 'verdict', 'validated', 'reviewed_inventory_sha256'))
    assert result['audit']['scope'] == 'body_only'
    with pytest.raises(RoleProtocolError, match='solver_requires_accepted_review'):
        build_solver_input(graph, result['body_text'], result, revision=2)


@pytest.mark.parametrize('field,value', [('role', 'body_text'), ('base_revision', 1),
                                        ('coordinate_space', 'crop_pixels')])
def test_response_identity_is_not_coerced(field, value):
    body = first(); local = hints(body); raw = response(body, local)
    raw[field] = value
    with pytest.raises(RoleProtocolError):
        decode(raw, body, local)


@pytest.mark.parametrize('field', ['graphs', 'edges', 'vertices', 'page_coverage',
                                  'node_updates', 'verdict', 'body_text'])
def test_body_reviewer_cannot_smuggle_graph_or_alternate_text_fields(field):
    body = first(); local = hints(body); raw = response(body, local)
    raw[field] = []
    with pytest.raises(RoleProtocolError, match='body_review_mutation_forbidden'):
        decode(raw, body, local)


@pytest.mark.parametrize('where', ['hint', 'body'])
@pytest.mark.parametrize('mutation', ['omit', 'duplicate', 'unknown'])
def test_both_id_spaces_have_exact_coverage(where, mutation):
    body = first(('计算 |A|。', '写出 A 的一个元素。')); local = hints(body); raw = response(body, local)
    rows = raw['text_review']['regions'] if where == 'hint' else raw['body_region_review']
    if mutation == 'omit': rows.pop()
    if mutation == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    if mutation == 'unknown': rows[0]['id'] = 'not_in_the_snapshot'
    with pytest.raises(RoleProtocolError, match='(text_review_regions|observed_body_review)'):
        decode(raw, body, local)


@pytest.mark.parametrize('field', ['region_ids', 'observed_region_ids'])
def test_declared_coverage_cannot_hide_a_missing_identity(field):
    body = first(); local = hints(body); raw = response(body, local)
    raw['body_coverage'][field] = []
    with pytest.raises(RoleProtocolError, match='review_(body|observed_body)_regions_coverage'):
        decode(raw, body, local)


@pytest.mark.parametrize('changed', ['求集合 A₄ 的元素个数。', '求集合 A₂ 的子集个数。',
                                    '判断集合 A₂ 不为空。'])
@pytest.mark.parametrize('with_ocr', [False, True])
def test_every_substantive_change_requires_its_original_location(changed, with_ocr):
    body = first(); local = hints(body, empty=not with_ocr); raw = response(body, local)
    raw['text_review']['text'] = changed
    targets = [raw['body_region_review'][0], *raw['text_review']['regions']]
    for row in targets:
        row['text'] = changed
    target = targets[0]
    saved = target.pop('evidence')
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        decode(raw, body, local)
    target['evidence'] = proof([100, 600, 500, 800])
    with pytest.raises(RoleProtocolError, match='text_evidence_wrong_location'):
        decode(raw, body, local)
    target['evidence'] = saved
    result = decode(raw, body, local)
    assert result['body_complete'] and result['body_text'] == changed
    assert result['regions'][0]['text'] == changed
    assert result['regions'][0]['bbox'] == body['regions'][0]['bbox']


def test_correcting_an_ocr_hint_also_requires_the_hint_location():
    body = first(); local = hints(body); local['items'][0]['text'] = '求集合 A₄ 的元素个数。'
    raw = response(body, local)
    row = raw['text_review']['regions'][0]; row['text'] = body['body_text']; row.pop('evidence')
    with pytest.raises(RoleProtocolError, match='original_evidence_missing'):
        decode(raw, body, local)


def test_no_ocr_does_not_allow_dropping_an_independently_located_question():
    body = first(('列出集合 B。', '计算 |B|。', '判断 B 是否为空。'))
    local = hints(body, empty=True); raw = response(body, local)
    raw['text_review']['text'] = body['regions'][0]['text']
    with pytest.raises(RoleProtocolError, match='body_fragment_not_in_text'):
        decode(raw, body, local)
    for row in raw['body_region_review'][1:]:
        row['role'] = 'noise'; row['evidence'] = proof([0, 0, 1000, 1000])
    with pytest.raises(RoleProtocolError, match='text_evidence_wrong_location'):
        decode(raw, body, local)


def test_located_exclusion_is_preserved_in_review_audit_and_raw_response():
    body = first(('请列举 B。', '页脚水印'))
    local = hints(body, empty=True); raw = response(body, local)
    raw['body_region_review'][1]['role'] = 'noise'
    raw['text_review']['text'] = body['regions'][0]['text']
    result = decode(raw, body, local)
    assert result['body_complete'] and result['body_text'] == '请列举 B。'
    assert result['regions'][1]['role'] == 'noise'
    assert result['regions'][1]['text'] == '页脚水印'
    assert result['body_region_review'][1]['evidence']['bbox'] == body['regions'][1]['bbox']
    assert result['raw_response'] == raw


def test_new_unlocated_text_cannot_be_added_even_with_complete_coverage_claim():
    body = first(); local = hints(body, empty=True); raw = response(body, local)
    raw['text_review']['text'] += '\n证明集合有限。'
    with pytest.raises(RoleProtocolError, match='review_body_regions_do_not_cover_text'):
        decode(raw, body, local)


def test_body_fragment_order_is_preserved_instead_of_accepting_response_row_order():
    body = first(('先列举 B。', '再计算 |B|。')); local = hints(body, empty=True); raw = response(body, local)
    raw['body_region_review'].reverse()
    assert decode(raw, body, local)['body_text'] == body['body_text']
    raw['text_review']['text'] = '\n'.join(r['text'] for r in raw['body_region_review'])
    with pytest.raises(RoleProtocolError, match='review_body_regions_do_not_cover_text'):
        decode(raw, body, local)


def test_format_equivalence_does_not_silently_change_the_located_region_text():
    body = first(('计算 x²。',)); local = hints(body); raw = response(body, local)
    raw['text_review']['text'] = '计算 $x^{2}$。'
    result = decode(raw, body, local)
    assert result['body_complete'] and result['body_text'] == '计算 x²。'
    assert result['raw_response']['text_review']['text'] == '计算 $x^{2}$。'
    assert result['audit']['normalizations']


def test_unique_panel_binding_is_audited_and_ambiguity_stays_uncertain():
    body = first(('请检查图形。',))
    body['regions'].append({'id': 'diagram_label', 'role': 'graph_label', 'text': 'p',
                            'bbox': [180, 580, 220, 620], 'source': 'original'})
    local = hints(body); raw = response(body, local)
    raw['text_review']['regions'][1]['role'] = 'graph_label'
    result = decode(raw, body, local)
    assert result['body_complete']
    assert result['regions'][1]['graph_id'] == 'panel_A'
    assert result['text_review']['regions'][1]['graph_id'] == 'panel_A'
    assert {r['entity_type'] for r in result['audit']['panel_bindings']} == {'hint', 'body_region'}
    duplicate = {**panels()[0], 'id': 'panel_B'}
    ambiguous = decode(raw, body, local, panels() + [duplicate])
    assert not ambiguous['body_complete'] and ambiguous['regions'][1]['role'] == 'uncertain'
    assert 'text_graph_ownership_unresolved:diagram_label' in ambiguous['issues']


def test_body_review_can_resolve_prior_uncertainty_without_requiring_prior_complete():
    body = first(); body['body_complete'] = False; body['regions'][0]['role'] = 'uncertain'; body['body_text'] = ''
    local = hints(body, empty=True); raw = response(body, local)
    raw['body_region_review'][0]['role'] = 'body'
    raw['text_review']['text'] = body['regions'][0]['text']
    result = decode(raw, body, local)
    assert result['body_complete'] and result['regions'][0]['role'] == 'body'
    assert result['audit']['reconciliation']['first_body_complete'] is False


def test_remaining_uncertainty_is_a_soft_string_issue_not_body_acceptance():
    body = first(); local = hints(body, empty=True); raw = response(body, local)
    raw['body_region_review'][0]['role'] = 'uncertain'
    raw['text_review'].update(text='', complete=False)
    result = decode(raw, body, local)
    assert not result['body_complete']
    assert all(isinstance(i, str) for i in result['issues'])
    assert 'uncertain_text_region:line_0' in result['issues']


def model_issue():
    return {'id': 'body_problem', 'kind': 'blurred_character', 'target_role': 'body_text',
            'graph_id': None, 'hint_ids': ['ocr_0'], 'body_region_ids': ['line_0'],
            'reason': '该行字形仍有歧义', 'evidence': proof()}


def test_model_issues_have_separate_dict_output_and_prevent_acceptance():
    body = first(); local = hints(body); raw = response(body, local); raw['issues'] = [model_issue()]
    result = decode(raw, body, local)
    assert result['issues'] == ['body_review_issue:body_problem']
    assert not result['body_complete']
    assert result['model_issues'][0]['target_role'] == 'body_text'
    assert result['raw_response']['issues'] == raw['issues']


@pytest.mark.parametrize('mutation', ['target', 'unknown_hint', 'unknown_region', 'duplicate',
                                     'edge', 'wrong_location', 'missing_proof'])
def test_model_issues_cannot_reference_unowned_entities_or_change_graphs(mutation):
    body = first(); local = hints(body); raw = response(body, local); item = model_issue()
    raw['issues'] = [item]
    if mutation == 'target': item['target_role'] = 'connections'
    if mutation == 'unknown_hint': item['hint_ids'] = ['invented']
    if mutation == 'unknown_region': item['body_region_ids'] = ['invented']
    if mutation == 'duplicate': raw['issues'].append(copy.deepcopy(item))
    if mutation == 'edge': item['edge_ids'] = ['new_edge']
    if mutation == 'wrong_location': item['evidence'] = proof([100, 600, 500, 800])
    if mutation == 'missing_proof': item.pop('evidence')
    with pytest.raises(RoleProtocolError):
        decode(raw, body, local)


def test_newly_seen_body_location_is_reported_without_inventing_known_ids():
    body = first(); local = hints(body); raw = response(body, local); item = model_issue()
    item.update(hint_ids=[], body_region_ids=[], kind='unlisted_body_region', evidence=proof([40, 200, 880, 270]))
    raw['issues'] = [item]
    result = decode(raw, body, local)
    assert not result['body_complete'] and len(result['regions']) == 1
    assert result['model_issues'][0]['body_region_ids'] == []


def test_digest_depends_on_body_hints_and_panels_but_not_graph_edges_or_global_revision():
    body = first(); local = hints(body); graph = panels()
    expected = body_review_input_digest(body, local, graph)
    moved = copy.deepcopy(graph)
    moved[0].update(complete=True, directed=True, weighted=False,
                    edges=[{'id': 'unvalidated', 'from': 'p', 'to': 'q', 'weight': 17}])
    moved[0]['vertices'][0]['x'] = .3
    revised = {**body, 'base_revision': 87, 'audit': {'unrelated': 'data'}}
    assert body_review_input_digest(revised, local, moved) == expected
    assert decode(response(body, local), body, local)['body_input_digest'] == expected
    for component in ('body', 'hint', 'panel_id', 'panel_bbox', 'region_bbox'):
        b, h, g = copy.deepcopy((body, local, graph))
        if component == 'body':
            b['body_text'] += '请说明。'; b['regions'][0]['text'] = b['body_text']
        if component == 'hint': h['items'][0]['text'] += '？'
        if component == 'panel_id': g[0]['id'] = 'different_panel'
        if component == 'panel_bbox': g[0]['bbox'][0] = .11
        if component == 'region_bbox': b['regions'][0]['bbox'][0] = 45
        assert body_review_input_digest(b, h, g) != expected


def test_invalid_prior_proposal_is_not_promoted_to_an_independent_review():
    body = first(); local = hints(body); raw = response(body, local); body['role_valid'] = False
    with pytest.raises(RoleProtocolError, match='body_review_requires_valid_transcription'):
        decode(raw, body, local)


def test_nested_graph_mutation_fields_are_not_accepted_in_text_decisions():
    body = first(); local = hints(body); raw = response(body, local)
    raw['body_region_review'][0]['vertices'] = []
    with pytest.raises(RoleProtocolError, match='body_review_mutation_forbidden'):
        decode(raw, body, local)
