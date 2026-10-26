"""Synthetic RGB observations; no user images, gold or remote model calls."""
import copy
import json

import pytest

from graph_semantic_attributes import reconcile_edge_colors


SOURCE = 'a' * 64


def document(*, edge_id=True):
    edge = {'from': 'p', 'to': 'q', 'color': 'red', 'direction': 'forward',
            'weight': -3, 'edge_label': 'f₂', 'style': 'dashed', 'path': []}
    if edge_id:
        edge['id'] = 'edge-A'
    return {'body_text': '保留完整题干与第二小问。', 'uncertainties': ['unchanged'],
            'graphs': [{'id': 'panel-A', 'name': '(a)', 'vertices': [
                {'id': 'p', 'label': 'P'}, {'id': 'q', 'label': 'q'}], 'edges': [edge]}]}


def candidate(*, color=(0, 0, 255), name='sknw:panel-A:route', reverse=False):
    left, right = ('q', 'p') if reverse else ('p', 'q')
    return {'instance_id': name, 'source': 'sknw', 'from': left, 'to': right,
            'unmapped': False, 'coordinate_space': 'original_1000',
            'path_hint': [[100, 200], [450, 200], [800, 200]],
            'endpoints': [{'vertex_id': v, 'marker_id': 'marker-' + v,
                           'association': 'unique_close_marker'} for v in (left, right)],
            'color_measurement': {'status': 'measured', 'source': 'unmodified_working_rgb',
                                  'sample_count': 200,
                                  'colors': [{'rgb': list(color), 'fraction': .96},
                                             {'rgb': [230, 230, 230], 'fraction': .04}]}}


def geometry(*rows):
    return {'source_sha256': SOURCE, 'graphs': [{'graph_id': 'panel-A',
                                                'candidates': list(rows or [candidate()])}],
            'issues': []}


def only_edge(result):
    return result['graphs'][0]['edges'][0]


def test_clear_original_color_changes_only_color_without_edge_id_and_without_mutation():
    draft, local = document(edge_id=False), geometry(candidate(reverse=True))
    before_draft, before_local = copy.deepcopy(draft), copy.deepcopy(local)
    revised, audit = reconcile_edge_colors(draft, local)
    assert draft == before_draft and local == before_local
    expected = copy.deepcopy(draft)
    only_edge(expected)['color'] = 'blue'
    assert revised == expected
    assert audit['changed_edges'] == 1 and audit['changes'][0]['edge_id'] is None
    assert audit['changes'][0]['edge_index'] == 0
    assert audit['source_sha256'] == SOURCE
    assert audit['acceptance_required'] is False
    assert audit['graph_content_certified'] is False
    json.dumps(audit, allow_nan=False)


def test_two_hue_buckets_of_one_color_are_combined_not_treated_as_conflicting_colors():
    row = candidate()
    row['color_measurement']['colors'] = [
        {'rgb': [8, 1, 249], 'fraction': .79},
        {'rgb': [2, 10, 238], 'fraction': .15},
        {'rgb': [225, 226, 248], 'fraction': .06}]
    revised, audit = reconcile_edge_colors(document(), geometry(row))
    assert only_edge(revised)['color'] == 'blue'
    assert audit['changes'][0]['evidence'][0]['dominant_fraction'] == .94


@pytest.mark.parametrize('rgb,name', [((255, 0, 0), 'red'), ((0, 0, 255), 'blue'),
    ((0, 128, 0), 'green'), ((255, 255, 0), 'yellow'),
    ((255, 128, 0), 'orange'), ((128, 0, 255), 'purple')])
def test_supported_clear_hues_use_existing_semantic_color_vocabulary(rgb, name):
    draft = document()
    only_edge(draft)['color'] = 'unknown'
    revised, _ = reconcile_edge_colors(draft, geometry(candidate(color=rgb)))
    assert only_edge(revised)['color'] == name


@pytest.mark.parametrize('rgb', [(0, 0, 0), (55, 55, 55), (255, 255, 255),
    (230, 226, 250), (10, 10, 70), (0, 255, 255), (255, 0, 255), (255, 65, 0)])
def test_black_grey_pastel_dim_and_ambiguous_hues_abstain(rgb):
    draft = document()
    revised, audit = reconcile_edge_colors(draft, geometry(candidate(color=rgb)))
    assert revised == draft and audit['changed_edges'] == 0


def test_existing_color_alias_is_consistent_without_needless_rewrite():
    draft = document()
    only_edge(draft)['color'] = '蓝色'
    revised, audit = reconcile_edge_colors(draft, geometry())
    assert revised == draft
    assert audit['decisions'][0]['status'] == 'consistent'


@pytest.mark.parametrize('fraction', [.3, .07])
def test_competing_saturated_color_is_not_voted_away(fraction):
    row = candidate()
    row['color_measurement']['colors'] = [
        {'rgb': [0, 0, 255], 'fraction': 1 - fraction},
        {'rgb': [255, 0, 0], 'fraction': fraction}]
    draft = document()
    revised, audit = reconcile_edge_colors(draft, geometry(row))
    assert revised == draft
    assert audit['decisions'][0]['evidence'][0]['reason'] == 'mixed_or_ambiguous_hue'


def test_all_associated_paths_must_be_conclusive_and_unanimous():
    blue, other = candidate(), candidate(name='opencv:panel-A:other')
    other['source'] = 'opencv'
    revised, audit = reconcile_edge_colors(document(), geometry(blue, other))
    assert only_edge(revised)['color'] == 'blue' and audit['changed_edges'] == 1
    other['color_measurement']['colors'][0]['rgb'] = [255, 0, 0]
    draft = document()
    revised, audit = reconcile_edge_colors(draft, geometry(blue, other))
    assert revised == draft and audit['decisions'][0]['reason'] == 'associated_paths_disagree'
    other['color_measurement']['status'] = 'unmeasured'
    revised, audit = reconcile_edge_colors(draft, geometry(blue, other))
    assert revised == draft and audit['decisions'][0]['reason'] == 'associated_path_not_conclusive'


@pytest.mark.parametrize('other_rgb', [(255, 0, 0), (0, 0, 255)])
def test_unbound_parallel_instances_remain_unchanged_even_if_observed_paths_agree(other_rgb):
    draft = document()
    second = copy.deepcopy(only_edge(draft))
    second.update(id='edge-B', color='green', direction='reverse')
    draft['graphs'][0]['edges'].append(second)
    revised, audit = reconcile_edge_colors(draft, geometry(candidate(),
        candidate(name='sknw:panel-A:other', color=other_rgb)))
    assert revised == draft
    assert {d['reason'] for d in audit['decisions']} == {'parallel_instance_not_uniquely_bound'}


@pytest.mark.parametrize('field', ['multiplicity', 'parallel_count'])
def test_compact_parallel_representation_is_not_colored_as_one_instance(field):
    draft = document()
    only_edge(draft)[field] = 2
    revised, audit = reconcile_edge_colors(draft, geometry())
    assert revised == draft and audit['changed_edges'] == 0


def test_single_loop_can_be_corrected_without_changing_loop_topology():
    draft, row = document(), candidate()
    only_edge(draft)['to'] = 'p'
    row['to'] = 'p'
    row['endpoints'][1] = copy.deepcopy(row['endpoints'][0])
    row['path_hint'] = [[100, 200], [150, 100], [200, 200], [100, 200]]
    revised, audit = reconcile_edge_colors(draft, geometry(row))
    assert only_edge(revised)['from'] == only_edge(revised)['to'] == 'p'
    assert only_edge(revised)['color'] == 'blue' and audit['changed_edges'] == 1


@pytest.mark.parametrize('change', [
    lambda r: r.update(unmapped=True),
    lambda r: r.update(source='model'),
    lambda r: r.update(path_hint=[]),
    lambda r: r.update(coordinate_space='crop_1000'),
    lambda r: r['endpoints'][0].update(association='unmapped_draft_position_only'),
    lambda r: r['endpoints'][0].update(vertex_id='q'),
    lambda r: r['endpoints'][0].pop('marker_id'),
    lambda r: r['color_measurement'].update(source='normalized_rgb'),
    lambda r: r['color_measurement'].update(sample_count=63),
    lambda r: r['color_measurement'].update(sample_count=True),
    lambda r: r['color_measurement'].update(sample_count=2049),
    lambda r: r['color_measurement']['colors'][0].update(fraction=float('nan')),
    lambda r: r['color_measurement']['colors'][0].update(fraction=1.1),
    lambda r: r['color_measurement']['colors'][0].update(fraction=.8),
    lambda r: r['color_measurement']['colors'][0].update(rgb=[0, 0, 300]),
])
def test_invalid_or_weak_local_evidence_never_changes_document(change):
    row, draft = candidate(), document()
    change(row)
    revised, audit = reconcile_edge_colors(draft, geometry(row))
    assert revised == draft and audit['changed_edges'] == 0
    json.dumps(audit, allow_nan=False)


def test_no_candidate_is_an_abstention_and_never_creates_or_deletes_an_edge():
    draft = document()
    local = geometry()
    local['graphs'][0]['candidates'] = []
    revised, audit = reconcile_edge_colors(draft, local)
    assert revised == draft
    assert audit['decisions'][0]['reason'] == 'no_associated_path'
    assert audit['absence_is_not_negative_evidence'] is True


def test_panel_identity_is_not_guessed_from_matching_endpoints():
    draft, local = document(), geometry()
    local['graphs'][0]['graph_id'] = 'other-panel'
    revised, audit = reconcile_edge_colors(draft, local)
    assert revised == draft and audit['changed_edges'] == 0


def test_duplicate_candidate_or_marker_identity_cannot_prove_unique_association():
    first, second = candidate(), candidate()
    draft = document()
    revised, audit = reconcile_edge_colors(draft, geometry(first, second))
    assert revised == draft and audit['changed_edges'] == 0
    second['instance_id'] = 'opencv:panel-A:other'
    second['endpoints'][0]['marker_id'] = 'different-marker-for-p'
    revised, audit = reconcile_edge_colors(draft, geometry(first, second))
    assert revised == draft
    assert all(e['reason'] == 'conflicting_marker_associations'
               for e in audit['decisions'][0]['evidence'])


def test_shared_marker_in_different_panels_is_not_unique():
    draft, local = document(), geometry()
    other_graph = copy.deepcopy(draft['graphs'][0])
    other_graph['id'] = 'panel-B'
    draft['graphs'].append(other_graph)
    other_local = copy.deepcopy(local['graphs'][0])
    other_local['graph_id'] = 'panel-B'
    other_local['candidates'][0]['instance_id'] = 'sknw:panel-B:route'
    local['graphs'].append(other_local)
    revised, audit = reconcile_edge_colors(draft, local)
    assert revised == draft and audit['changed_edges'] == 0


def test_explicit_source_mismatch_and_truncated_candidate_scope_abstain():
    draft, local = document(), geometry()
    draft['source_sha256'] = 'b' * 64
    revised, audit = reconcile_edge_colors(draft, local)
    assert revised == draft and audit['reason'] == 'source_identity_mismatch'
    draft.pop('source_sha256')
    local['issues'] = [{'code': 'geometry_candidate_capacity'}]
    revised, audit = reconcile_edge_colors(draft, local)
    assert revised == draft and audit['reason'] == 'candidate_inventory_truncated'


def test_cancellation_propagates_instead_of_becoming_weak_evidence():
    class Cancelled:
        source_sha256 = SOURCE
        def check(self):
            raise TimeoutError('cancelled')
    with pytest.raises(TimeoutError, match='cancelled'):
        reconcile_edge_colors(document(), geometry(), budget=Cancelled())


def test_only_one_panel_changes_and_existing_unknown_edges_do_not_gain_answers():
    draft = document()
    other = copy.deepcopy(draft['graphs'][0])
    other['id'] = 'panel-B'
    draft['graphs'].append(other)
    revised, audit = reconcile_edge_colors(draft, geometry())
    assert only_edge(revised)['color'] == 'blue'
    assert revised['graphs'][1] == draft['graphs'][1]
    assert audit['changed_edges'] == 1


def test_idempotent_color_reconciliation_does_not_accumulate_changes():
    first, first_audit = reconcile_edge_colors(document(), geometry())
    second, second_audit = reconcile_edge_colors(first, geometry())
    assert first == second and first_audit['changed_edges'] == 1
    assert second_audit['changed_edges'] == 0
