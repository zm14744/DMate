import copy
import hashlib
from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image

from graph_agent_runtime import AgentBudget, AgentCancelled
from graph_semantic_geometry import prepare_semantic_geometry
from graph_visual_inventory import measure_visual_inventory, compare_visual_inventory


def picture(*, colour=(50, 100, 190), extra_radius=None, isolated=False):
    image = np.full((340, 460, 3), 255, dtype=np.uint8)
    centers = [(90, 110), (230, 110), (370, 110), (90, 250), (230, 250), (370, 250)]
    links = [(0, 1), (1, 2), (0, 3), (3, 4), (4, 5)]
    if isolated:
        links = links[:-1]
    for first, second in links:
        cv2.line(image, centers[first], centers[second], (0, 130, 0), 3)
    for center in centers:
        cv2.circle(image, center, 13, colour, -1, cv2.LINE_AA)
    if extra_radius is not None:
        cv2.circle(image, (230, 180), extra_radius, colour, -1, cv2.LINE_AA)
    data = BytesIO()
    Image.fromarray(image).save(data, format='PNG')
    return data.getvalue()


def measured(raw, *, layout=None):
    budget = AgentBudget(seconds=30, calls=0)
    geometry = prepare_semantic_geometry(raw, budget=budget)
    layout = layout or {'panels': [{'id': 'panel_1', 'bbox': [0, 0, 1000, 1000]}]}
    evidence = measure_visual_inventory(geometry, layout, budget=budget)
    return evidence, geometry


def draft(count, *, gid='G1', bbox=None):
    graph = {'id': gid, 'vertices': [{'id': str(i), 'label': None} for i in range(count)], 'edges': []}
    if bbox is not None:
        graph['bbox'] = bbox
    return {'graphs': [graph]}


def test_actual_colour_pixels_supply_a_reread_target_without_replacing_graph():
    evidence, _ = measured(picture())
    panel = evidence['panels'][0]
    assert panel['candidate_count'] == 6
    assert panel['comparison_eligible'] is True
    assert panel['complete_vertex_inventory_certified'] is False
    before = draft(7)
    saved = copy.deepcopy(before)
    result = compare_visual_inventory(before, evidence)
    assert before == saved
    issue, = result['issues']
    assert issue['kind'] == 'visual_marker_count_conflict'
    assert issue['candidate_count'] == 6 and issue['reported_count'] == 7
    assert issue['proposal_only'] is True and issue['image_accuracy_certified'] is False
    assert all(row['proof']['morphology_used'] is False for row in panel['markers'])


def test_isolated_circle_is_retained_alongside_connected_markers():
    evidence, _ = measured(picture(isolated=True))
    assert evidence['panels'][0]['candidate_count'] == 6
    assert evidence['panels'][0]['comparison_eligible'] is True
    assert any(not row['connected_stroke'] for row in evidence['panels'][0]['markers'])


@pytest.mark.parametrize('colour', [(20, 20, 20), (200, 200, 200)])
def test_black_white_or_low_saturation_is_not_a_complete_count_claim(colour):
    evidence, _ = measured(picture(colour=colour))
    assert compare_visual_inventory(draft(9), evidence)['issues'] == []


def test_no_largest_size_group_is_selected_to_force_count_agreement():
    evidence, _ = measured(picture(extra_radius=6))
    assert evidence['panels'][0]['candidate_count'] == 7
    assert evidence['panels'][0]['comparison_eligible'] is False
    assert compare_visual_inventory(draft(6), evidence)['issues'] == []


@pytest.mark.parametrize('shape', ['triangle', 'square', 'ring'])
def test_glyph_or_arrow_seed_needs_independent_original_shape_support(shape):
    image = np.array(Image.open(BytesIO(picture())).convert('RGB'))
    colour = (50, 100, 190)
    if shape == 'triangle':
        cv2.fillConvexPoly(image, np.array([[230, 162], [213, 191], [247, 191]]), colour)
    elif shape == 'square':
        cv2.rectangle(image, (217, 167), (243, 193), colour, -1)
    else:
        cv2.circle(image, (230, 180), 13, colour, 3)
    raw = BytesIO()
    Image.fromarray(image).save(raw, format='PNG')
    budget = AgentBudget(seconds=30, calls=0)
    geometry = prepare_semantic_geometry(raw.getvalue(), budget=budget)
    geometry['document']._semantic_geometry_cache['pool']['items'].append({
        'id': 'untrusted_shape_seed', 'x': 230/459, 'y': 180/339,
        'radius_pixels': 13, 'confidence': 1., 'connected_stroke': True})
    evidence = measure_visual_inventory(geometry,
        {'panels': [{'id': 'p', 'bbox': [0, 0, 1000, 1000]}]}, budget=budget)
    assert evidence['panels'][0]['candidate_count'] == 6
    assert evidence['panels'][0]['comparison_eligible'] is True
    assert 'untrusted_shape_seed' not in [m['id'] for m in evidence['panels'][0]['markers']]


def test_clipped_candidate_context_does_not_certify_the_remaining_count():
    _, geometry = measured(picture())
    geometry['document']._semantic_geometry_cache['pool']['items'].append({
        'id': 'clipped_seed', 'x': .01, 'y': .5,
        'radius_pixels': 13, 'confidence': 1., 'connected_stroke': True})
    evidence = measure_visual_inventory(geometry,
        {'panels': [{'id': 'p', 'bbox': [0, 0, 1000, 1000]}]},
        budget=AgentBudget(seconds=30, calls=0))
    assert evidence['panels'][0]['candidate_count'] == 6
    assert not evidence['panels'][0]['comparison_eligible']
    assert compare_visual_inventory(draft(7), evidence)['issues'] == []


def test_rechecking_final_draft_preserves_conflict_until_count_changes():
    evidence, _ = measured(picture())
    initial = draft(7)
    assert compare_visual_inventory(initial, evidence)['issues']
    initial['uncertainties'] = []
    initial['review_explanation'] = 'Everything was checked.'
    assert compare_visual_inventory(initial, evidence)['issues']
    assert compare_visual_inventory(draft(6), evidence)['issues'] == []
    assert evidence['panels'][0]['complete_vertex_inventory_certified'] is False


def test_unavailable_or_wrong_source_bound_document_abstains():
    budget = AgentBudget(seconds=30, calls=0)
    assert measure_visual_inventory({}, {}, budget=budget)['status'] == 'unavailable'
    raw = picture()
    geometry = prepare_semantic_geometry(raw, budget=budget)
    geometry['source_sha256'] = hashlib.sha256(b'another image').hexdigest()
    evidence = measure_visual_inventory(geometry, {}, budget=budget)
    assert evidence['status'] == 'unavailable' and evidence['panels'] == []


def test_candidate_caps_disable_count_comparison():
    evidence, geometry = measured(picture())
    geometry['document']._semantic_geometry_cache['pool']['limits']['marker_limit_reached'] = True
    capped = measure_visual_inventory(geometry, {'panels': [{'id': 'p', 'bbox': [0, 0, 1000, 1000]}]},
                                      budget=AgentBudget(seconds=30, calls=0))
    assert capped['panels'][0]['candidate_count'] == 6
    assert not capped['panels'][0]['comparison_eligible']
    assert compare_visual_inventory(draft(7), capped)['issues'] == []


def test_multiple_graphs_cannot_share_a_whole_page_placeholder_panel():
    evidence, _ = measured(picture())
    graph = draft(7, bbox=[0, 0, 1000, 1000])['graphs'][0]
    other = copy.deepcopy(graph)
    other['id'] = 'G2'
    assert compare_visual_inventory({'graphs': [graph, other]}, evidence)['issues'] == []


def test_unique_graph_panel_assignment_scopes_the_discrepancy():
    evidence, _ = measured(picture())
    first = evidence['panels'][0]
    first['bbox'] = [0, 0, 450, 1000]
    other = copy.deepcopy(first)
    other.update(region_id='panel_2', bbox=[550, 0, 1000, 1000])
    evidence['panels'].append(other)
    graphs = [draft(7, gid='G1', bbox=first['bbox'])['graphs'][0],
              draft(6, gid='G2', bbox=other['bbox'])['graphs'][0]]
    issues = compare_visual_inventory({'graphs': graphs}, evidence)['issues']
    assert [row['graph_id'] for row in issues] == ['G1']


def test_cancellation_propagates_before_any_pixel_measurement():
    budget = AgentBudget(seconds=30, calls=0, cancelled=lambda: True)
    with pytest.raises(AgentCancelled):
        measure_visual_inventory({}, {}, budget=budget)
