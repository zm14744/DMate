import copy

import networkx as nx
import pytest

import graph_panel_discrepancies as panels


def graph(identifier='G1', *, bbox=None, name=None):
    value = {'id': identifier, 'name': name or identifier,
        'vertices': [{'id': 'a', 'label': 'a'}, {'id': 'b', 'label': 'b'}, {'id': 'c', 'label': None}],
        'edges': [{'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 2},
                  {'from': 'b', 'to': 'c', 'direction': 'undirected', 'weight': None}]}
    if bbox is not None:
        value['bbox'] = bbox
    return value


def layout(count=1):
    return {'panels': [{'id': f'p{i}', 'bbox': [i*1000/count, 100, (i+1)*1000/count, 900]}
                       for i in range(count)]}


def test_missing_locations_and_same_content_form_a_document_reread_target():
    draft = {'graphs': [graph(), graph('G2')]}
    before = copy.deepcopy(draft)
    result = panels.compare_panel_discrepancies(draft, layout())
    issue, = result['issues']
    assert issue['scope'] == 'document' and issue['field'] == 'graphs'
    assert issue['kind'] == 'possible_duplicate_panel'
    assert issue['graph_ids'] == ['G1', 'G2']
    assert issue['crop_candidate_count'] == 1
    assert issue['proposal_only'] and not issue['image_accuracy_certified']
    assert draft == before
    assert not result['evidence']['graph_count_certified']


def test_separate_original_locations_preserve_real_independent_isomorphic_graphs():
    draft = {'graphs': [graph(bbox=[20, 100, 450, 900]), graph('G2', bbox=[550, 100, 980, 900])]}
    assert panels.compare_panel_discrepancies(draft, layout())['issues'] == []


@pytest.mark.parametrize('names', [('(a)', '(b)'), ('甲图', '乙图'), ('左图', '右图')])
def test_distinct_visible_captions_preserve_independent_same_content(names):
    draft = {'graphs': [graph(name=names[0]), graph('G2', name=names[1])]}
    assert panels.compare_panel_discrepancies(draft, layout())['issues'] == []


def test_explicitly_visible_numeric_captions_are_not_default_generated_names():
    first, second = graph(), graph('G2')
    first['visible_caption'], second['visible_caption'] = 'G1', 'G2'
    assert panels.compare_panel_discrepancies({'graphs': [first, second]}, layout())['issues'] == []


def test_full_page_placeholders_are_not_independent_location_evidence():
    draft = {'graphs': [graph(bbox=[0, 0, 1000, 1000]), graph('G2', bbox=[0, 0, 1000, 1000])]}
    assert panels.compare_panel_discrepancies(draft, layout(2))['issues'] == []
    assert panels.compare_panel_discrepancies(draft, layout(1))['issues']


def test_overlapping_actual_locations_supply_evidence_even_when_crop_counts_match():
    draft = {'graphs': [graph(bbox=[30, 100, 450, 900]), graph('G2', bbox=[35, 110, 455, 905])]}
    result = panels.compare_panel_discrepancies(draft, layout(2))
    assert result['issues'][0]['suspected_pairs'][0]['reason'] == 'overlapping_original_locations'


def test_disjoint_declared_cv_panels_can_disambiguate_without_model_bbox():
    first, second = graph(), graph('G2')
    first['layout_panel_ids'], second['layout_panel_ids'] = ['p0'], ['p1']
    assert panels.compare_panel_discrepancies({'graphs': [first, second]}, layout(2))['issues'] == []


def converted(source, identifier):
    return {'id': identifier, 'name': identifier,
        'vertices': [{'id': str(v), 'label': None} for v in source],
        'edges': [{'from': str(a), 'to': str(b), 'direction': 'undirected'} for a, b in source.edges()]}


def test_complete_graph_and_complete_bipartite_graph_are_not_duplicates():
    draft = {'graphs': [converted(nx.complete_graph(5), 'G1'), converted(nx.complete_bipartite_graph(3, 3), 'G2')]}
    assert panels.compare_panel_discrepancies(draft, layout())['issues'] == []


def test_same_degree_profile_is_not_a_proof_of_same_connections():
    cycle = nx.cycle_graph(6)
    triangles = nx.disjoint_union(nx.complete_graph(3), nx.complete_graph(3))
    draft = {'graphs': [converted(cycle, 'G1'), converted(triangles, 'G2')]}
    assert panels.compare_panel_discrepancies(draft, layout())['issues'] == []


def test_internal_node_ids_do_not_hide_a_repeated_visible_graph():
    first, second = graph(), graph('G2')
    for vertex in second['vertices']:
        vertex['id'] = 'new_' + vertex['id']
    for edge in second['edges']:
        edge['from'], edge['to'] = 'new_' + edge['from'], 'new_' + edge['to']
    assert panels.compare_panel_discrepancies({'graphs': [first, second]}, layout())['issues']


@pytest.mark.parametrize('change', ['weight', 'direction', 'multiplicity', 'label', 'edge_label', 'self_loop'])
def test_semantic_differences_are_not_merged_into_same_content(change):
    first, second = graph(), graph('G2')
    if change == 'label':
        second['vertices'][0]['label'] = 'A'
    elif change == 'self_loop':
        second['edges'][0]['to'] = 'a'
    else:
        second['edges'][0][change] = {'weight': 3, 'direction': 'undirected',
                                     'multiplicity': 2, 'edge_label': 'e1'}[change]
    assert panels.compare_panel_discrepancies({'graphs': [first, second]}, layout())['issues'] == []


def test_missing_cv_results_do_not_manufacture_a_count_mismatch():
    assert panels.compare_panel_discrepancies({'graphs': [graph(), graph('G2')]}, {})['issues'] == []


def test_crop_undersegmentation_alone_does_not_require_deleting_real_graphs():
    first, second = graph(), graph('G2')
    second['edges'].append({'from': 'a', 'to': 'c', 'direction': 'undirected'})
    assert panels.compare_panel_discrepancies({'graphs': [first, second]}, layout())['issues'] == []


def test_bounded_comparison_abstains_without_certifying_a_count(monkeypatch):
    monkeypatch.setattr(panels, 'MAX_COMPARE_SECONDS', 0)
    result = panels.compare_panel_discrepancies({'graphs': [graph(), graph('G2')]}, layout())
    assert result['issues'] == []
    assert result['evidence']['comparison_limit_reached'] is True
    assert result['evidence']['graph_count_certified'] is False
