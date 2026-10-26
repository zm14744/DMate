"""Pixel grounding regressions; generated diagrams are not original accuracy."""
import copy
import math

import cv2
import numpy as np
from PIL import Image
import pytest

from graph_marker_grounding import ground_nodes, marker_proposals


def graph(size, points, *, bounds=None):
    return {'id': 'any-panel', 'name': 'arbitrary name', 'bbox': bounds or [0, 0, 1, 1],
            'vertices': [{'id': name, 'label': name+' literal', 'x': x/(size[0]-1), 'y': y/(size[1]-1),
                          'isolated_confirmed': False} for name, x, y in points], 'edges': []}


def connected_diagram(radius=4, scale=1, filled=False):
    size = (480*scale, 320*scale)
    array = np.full((size[1], size[0], 3), 255, np.uint8)
    centers = [(90, 65), (350, 65), (350, 165), (90, 165), (350, 270)]
    for a, b in ((0, 1), (0, 2), (0, 3), (1, 2), (2, 3), (2, 4)):
        cv2.line(array, tuple(v*scale for v in centers[a]), tuple(v*scale for v in centers[b]),
                 (0, 0, 0), max(1, 2*scale))
    for x, y in centers:
        center = (x*scale, y*scale)
        cv2.circle(array, center, radius*scale, (0, 0, 0) if filled else (255, 255, 255), -1)
        if not filled:
            cv2.circle(array, center, radius*scale, (0, 0, 0), max(1, scale))
    shifts = [(-26, -26), (0, -26), (0, -7), (-32, -13), (0, -30)]
    inventory = graph(size, [(str(i), (x+dx)*scale, (y+dy)*scale)
                      for i, ((x, y), (dx, dy)) in enumerate(zip(centers, shifts))])
    return Image.fromarray(array), inventory, [(x*scale, y*scale) for x, y in centers]


@pytest.mark.parametrize('radius,scale', [(3, 1), (4, 1), (8, 1), (4, 3)])
def test_label_displacement_is_grounded_by_small_independent_holes(radius, scale):
    image, inventory, centers = connected_diagram(radius, scale)
    before = copy.deepcopy(inventory)
    output = ground_nodes(image, [inventory])[0]
    assert inventory == before
    assert output['marker_grounding']['grounded_vertices'] == 5
    for old, actual, expected in zip(before['vertices'], output['vertices'], centers):
        assert actual['id'] == old['id'] and actual['label'] == old['label']
        assert actual['isolated_confirmed'] == old['isolated_confirmed']
        position = (actual['x']*(image.width-1), actual['y']*(image.height-1))
        assert math.dist(position, expected) < 2*scale
    assert any(e['shift_work_pixels'] > 16 for e in output['node_position_evidence'])
    assert all(e['pixel_evidence']['source'] == 'closed_original_ink_hole'
               for e in output['node_position_evidence'])


def test_filled_markers_must_be_wider_than_their_own_strokes():
    image, inventory, centers = connected_diagram(radius=7, filled=True)
    actual = ground_nodes(image, [inventory])[0]
    assert actual['marker_grounding']['grounded_vertices'] == 5
    for vertex, expected in zip(actual['vertices'], centers):
        assert math.dist((vertex['x']*(image.width-1), vertex['y']*(image.height-1)), expected) < 2
    assert all(e['pixel_evidence']['distinct_from_stroke_thickness']
               for e in actual['node_position_evidence'])


def test_plain_crossing_and_small_line_thickening_cannot_attract_vertex():
    array = np.full((240, 360, 3), 255, np.uint8)
    cv2.line(array, (100, 30), (100, 210), (0, 0, 0), 4)
    cv2.line(array, (30, 120), (170, 120), (0, 0, 0), 4)
    cv2.circle(array, (100, 180), 3, (0, 0, 0), -1)
    inventory = graph((360, 240), [('intersection', 87, 115), ('ink_bulge', 87, 176)])
    before = copy.deepcopy(inventory)
    actual = ground_nodes(Image.fromarray(array), [inventory])[0]
    assert actual['vertices'] == before['vertices']
    assert actual['marker_grounding']['grounded_vertices'] == 0


def test_equal_markers_and_duplicate_inventory_positions_are_not_tiebroken():
    image = np.full((160, 300, 3), 255, np.uint8)
    cv2.line(image, (120, 80), (180, 80), (0, 0, 0), 2)
    for center in ((120, 80), (180, 80)):
        cv2.circle(image, center, 5, (255, 255, 255), -1)
        cv2.circle(image, center, 5, (0, 0, 0), 1)
    one = graph((300, 160), [('ambiguous', 150, 80)])
    assert ground_nodes(Image.fromarray(image), [one])[0]['vertices'] == one['vertices']
    duplicate = graph((300, 160), [('a', 120, 80), ('b', 120, 80)])
    actual = ground_nodes(Image.fromarray(image), [duplicate])[0]
    assert actual['vertices'] == duplicate['vertices']
    assert actual['marker_grounding']['grounded_vertices'] == 0
    assert actual['marker_grounding']['position_gate']['hard_blocking'] is True
    assert {row['classification'] for row in actual['marker_grounding']['untrusted_vertices']} == {
        'shared_marker_identity'}


def test_overlapping_panel_ownership_is_not_guessed():
    image, inventory, _ = connected_diagram()
    other = copy.deepcopy(inventory)
    other['id'] = 'second'
    actual = ground_nodes(image, [inventory, other])
    assert [g['vertices'] for g in actual] == [inventory['vertices'], other['vertices']]
    assert all(g['marker_grounding']['grounded_vertices'] == 0 for g in actual)


def test_unmarked_isolated_vertices_and_invalid_locations_are_retained():
    blank = Image.new('RGB', (300, 160), 'white')
    inventory = graph(blank.size, [('isolate', 70, 80), ('unknown', 220, 80)])
    inventory['vertices'][0]['isolated_confirmed'] = True
    inventory['vertices'][1]['x'] = None
    actual = ground_nodes(blank, [inventory])[0]
    assert actual['vertices'] == inventory['vertices']
    assert actual['marker_grounding']['grounded_vertices'] == 0
    assert {r['reason'] for r in actual['marker_grounding']['retained_vertices']} == {
        'no_reliable_local_marker', 'invalid_position'}
    gate = actual['marker_grounding']['position_gate']
    assert gate['hard_blocking'] is True
    assert gate['hard_conflicts'] == [{'kind': 'invalid_position', 'vertex_ids': ['unknown'],
                                     'reason': 'coordinate_missing_nonfinite_or_out_of_bounds'}]
    assert gate['unobserved_vertices'] == ['isolate']


def test_far_isolated_text_circle_is_not_used_as_a_connected_marker():
    image = np.full((180, 320, 3), 255, np.uint8)
    cv2.circle(image, (150, 80), 5, (0, 0, 0), 1)
    inventory = graph((320, 180), [('printed_letter_location', 130, 80)])
    actual = ground_nodes(Image.fromarray(image), [inventory])[0]
    assert actual['vertices'] == inventory['vertices']


def test_foreign_or_model_modified_proposals_are_rejected():
    image, inventory, _ = connected_diagram()
    pool = marker_proposals(image)
    assert ground_nodes(image, [inventory], pool)[0]['marker_grounding']['grounded_vertices'] == 5
    changed = copy.deepcopy(pool)
    changed['items'][0]['x'] += .1
    with pytest.raises(ValueError, match='do_not_match_original_pixels'):
        ground_nodes(image, [inventory], changed)
    with pytest.raises(ValueError, match='do_not_match_original_pixels'):
        ground_nodes(Image.new('RGB', image.size, 'white'), [inventory], pool)


def test_candidate_capacity_is_not_a_false_uniqueness_proof(monkeypatch):
    import graph_marker_grounding as module
    image, inventory, _ = connected_diagram()
    monkeypatch.setattr(module, 'MAX_MARKERS', 2)
    actual = ground_nodes(image, [inventory])[0]
    assert actual['vertices'] == inventory['vertices']
    assert actual['marker_grounding']['reason'] == 'marker_candidate_budget_exceeded'
    assert actual['marker_grounding']['position_gate']['hard_blocking'] is False
    assert actual['marker_grounding']['position_gate']['visual_review_required'] is True


def test_transparent_and_dark_backgrounds_use_the_existing_original_decoder():
    image, inventory, _ = connected_diagram()
    array = np.asarray(image)
    rgba = np.dstack([array, np.where(np.all(array == 255, axis=2), 0, 255).astype(np.uint8)])
    transparent = ground_nodes(Image.fromarray(rgba), [inventory])[0]
    dark = ground_nodes(Image.fromarray(255-array), [inventory])[0]
    assert transparent['marker_grounding']['grounded_vertices'] == 5
    assert dark['marker_grounding']['grounded_vertices'] == 5


@pytest.mark.parametrize('offset', [(0, 0), (-20, -15)])
def test_numbered_large_coloured_nodes_do_not_snap_to_glyphs_or_ports(offset):
    size = (640, 320)
    image = np.full((size[1], size[0], 3), 255, np.uint8)
    centers = [(75, 75), (310, 75), (195, 245), (535, 245)]
    for a, b in ((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)):
        cv2.line(image, centers[a], centers[b], (50, 50, 50), 1)
    for i, center in enumerate(centers):
        cv2.circle(image, center, 34, (250, 210, 210), -1)
        cv2.circle(image, center, 34, (175, 110, 110), 2)
        cv2.putText(image, str(i+2), (center[0]-9, center[1]+9),
                    cv2.FONT_HERSHEY_SIMPLEX, .85, (0, 0, 0), 2)
    # A tiny round junction at a port must not attract the centre of the
    # large numbered node even though the junction has real ink support.
    cv2.line(image, (310, 108), (340, 160), (0, 0, 0), 1)
    cv2.circle(image, (310, 108), 4, (255, 255, 255), -1)
    cv2.circle(image, (310, 108), 4, (0, 0, 0), 1)
    inventory = graph(size, [(str(i), x+offset[0], y+offset[1])
                            for i, (x, y) in enumerate(centers)])
    actual = ground_nodes(Image.fromarray(image), [inventory])[0]
    for vertex, expected in zip(actual['vertices'], centers):
        if offset == (0, 0) or any(e['vertex'] == vertex['id'] for e in actual['node_position_evidence']):
            assert math.dist((vertex['x']*(size[0]-1), vertex['y']*(size[1]-1)), expected) < 4


def test_a_compact_dot_inside_a_larger_loop_is_not_removed_as_a_numeral():
    image = np.full((240, 360, 3), 255, np.uint8)
    cv2.circle(image, (180, 120), 40, (0, 0, 0), 2)
    cv2.circle(image, (180, 120), 5, (0, 0, 0), -1)
    pool = marker_proposals(Image.fromarray(image))
    assert any(p['kind'] == 'filled' and p['radius_pixels'] < 10
               and math.dist((p['x']*359, p['y']*239), (180, 120)) < 2 for p in pool['items'])


def test_large_outline_capacity_also_abstains(monkeypatch):
    import graph_marker_grounding as module
    image = np.full((220, 350, 3), 255, np.uint8)
    cv2.circle(image, (100, 110), 32, (0, 0, 0), 2, lineType=cv2.LINE_AA)
    cv2.circle(image, (250, 110), 32, (0, 0, 0), 2, lineType=cv2.LINE_AA)
    inventory = graph((350, 220), [('one', 100, 110), ('two', 250, 110)])
    monkeypatch.setattr(module, 'MAX_OUTLINE_HYPOTHESES', 1)
    actual = ground_nodes(Image.fromarray(image), [inventory])[0]
    assert actual['vertices'] == inventory['vertices']
    assert actual['marker_grounding']['reason'] == 'marker_candidate_budget_exceeded'


def test_outline_refinement_capacity_does_not_supply_false_uniqueness(monkeypatch):
    import graph_node_geometry
    image = np.full((220, 350, 3), 255, np.uint8)
    cv2.circle(image, (100, 110), 32, (0, 0, 0), 2, lineType=cv2.LINE_AA)
    inventory = graph((350, 220), [('one', 90, 100)])
    monkeypatch.setattr(graph_node_geometry, 'MAX_CONTOUR_PROPOSALS', 0)
    actual = ground_nodes(Image.fromarray(image), [inventory])[0]
    assert actual['vertices'] == inventory['vertices']
    assert actual['marker_grounding']['reason'] == 'marker_candidate_budget_exceeded'
    assert actual['marker_grounding']['limits']['outline_refinement_limit_reached'] is True


def test_dense_body_text_does_not_supply_imaginary_large_round_nodes():
    image, inventory, centers = connected_diagram()
    page = np.full((500, 480, 3), 255, np.uint8)
    page[:320] = np.asarray(image)
    for y in range(347, 495, 22):
        cv2.putText(page, '1234 body text (v1,v2) 010101 535353', (16, y),
                    cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 1, lineType=cv2.LINE_AA)
    for vertex in inventory['vertices']:
        vertex['y'] *= 319/499
    actual = ground_nodes(Image.fromarray(page), [inventory])[0]
    assert actual['marker_grounding']['grounded_vertices'] == 5
    for vertex, expected in zip(actual['vertices'], centers):
        assert math.dist((vertex['x']*479, vertex['y']*499), expected) < 2


def compressed_model_inventory(scale=1):
    """One displaced label sits nearer another node than its own marker.

    The original-pixel centres and the model's observations are separate;
    nothing in the production call receives an edge or a target position.
    """
    size = (520*scale, 360*scale)
    image = np.full((size[1], size[0], 3), 255, np.uint8)
    centers = [(100, 80), (385, 80), (385, 180), (110, 180), (387, 252)]
    for a, b in ((0, 1), (0, 2), (0, 3), (1, 2), (2, 3), (2, 4)):
        cv2.line(image, tuple(value*scale for value in centers[a]),
                 tuple(value*scale for value in centers[b]), (0, 0, 0), 2*scale)
    for x, y in centers:
        cv2.circle(image, (x*scale, y*scale), 4*scale, (255, 255, 255), -1)
        cv2.circle(image, (x*scale, y*scale), 4*scale, (0, 0, 0), scale)
    observed = [(75, 59), (382, 56), (384, 173), (82, 168), (355, 201)]
    inventory = graph(size, [(str(i), x*scale, y*scale) for i, (x, y) in enumerate(observed)])
    inventory['node_complete'] = False
    return Image.fromarray(image), inventory, [(x*scale, y*scale) for x, y in centers]


@pytest.mark.parametrize('scale', [1, 2])
def test_unique_remaining_marker_recovers_compressed_model_search_without_larger_radius(scale):
    image, inventory, centers = compressed_model_inventory(scale)
    before = copy.deepcopy(inventory)
    actual = ground_nodes(image, [inventory])[0]
    assert inventory == before
    assert actual['node_complete'] is False
    assert actual['edges'] == []
    assert [v['id'] for v in actual['vertices']] == [v['id'] for v in inventory['vertices']]
    evidence = next(e for e in actual['node_position_evidence'] if e['vertex'] == '4')
    assert evidence['assignment']['method'] == 'unique_remaining_component'
    assert evidence['assignment']['reserved_local_anchors'] == 4
    assert evidence['shift_work_pixels'] > evidence['assignment']['local_search_radius_work_pixels']
    assert evidence['shift_work_pixels'] <= evidence['assignment']['absolute_search_radius_work_pixels']
    for vertex, expected in zip(actual['vertices'], centers):
        assert math.dist((vertex['x']*(image.width-1), vertex['y']*(image.height-1)), expected) < 2*scale
    audit = actual['marker_grounding']
    assert audit['assignment_summary']['local_assignments'] == 4
    assert audit['assignment_summary']['global_unique_assignments'] == 1
    assert audit['untrusted_vertices'] == []
    assert audit['review_required'] is False


def test_two_remaining_strong_markers_are_not_resolved_by_nearest_distance():
    image, inventory, centers = compressed_model_inventory()
    array = np.asarray(image).copy()
    cv2.line(array, (330, 247), (260, 310), (0, 0, 0), 2)
    cv2.circle(array, (330, 247), 4, (255, 255, 255), -1)
    cv2.circle(array, (330, 247), 4, (0, 0, 0), 1)
    actual = ground_nodes(Image.fromarray(array), [inventory])[0]
    assert actual['vertices'][4] == inventory['vertices'][4]
    audit = actual['marker_grounding']
    assert audit['grounded_vertices'] == 4
    assert audit['review_required'] is True
    untrusted = next(row for row in audit['untrusted_vertices'] if row['vertex'] == '4')
    assert untrusted['reason'] == 'global_assignment_not_unique'
    assert len(untrusted['broad_candidate_ids']) == 2
    assert len([m for m in audit['unbound_strong_markers'] if m['review_relevant']]) == 2
    assert untrusted['nearest_strong_marker']['already_bound'] is True
    assert actual['node_complete'] is False
    assert audit['position_gate']['hard_blocking'] is False
    assert audit['position_gate']['ambiguous_vertices'] == ['4']


def test_remaining_marker_outside_original_absolute_bound_is_reported_without_moving():
    image, inventory, centers = compressed_model_inventory()
    inventory['vertices'][4].update(x=330/(image.width-1), y=195/(image.height-1))
    actual = ground_nodes(image, [inventory])[0]
    assert actual['vertices'][4] == inventory['vertices'][4]
    audit = actual['marker_grounding']
    assert audit['review_required'] is True
    untrusted = next(row for row in audit['untrusted_vertices'] if row['vertex'] == '4')
    assert untrusted['broad_candidate_ids'] == []
    assert untrusted['nearest_strong_marker']['distance_work_pixels'] > 50
    assert any(m['review_relevant'] and math.dist(m['work_point'], centers[4]) < 2
               for m in audit['unbound_strong_markers'])


def test_duplicate_model_identities_cannot_use_global_elimination_to_steal_a_marker():
    image, inventory, _ = compressed_model_inventory()
    inventory['vertices'][4].update(x=inventory['vertices'][2]['x'], y=inventory['vertices'][2]['y'])
    actual = ground_nodes(image, [inventory])[0]
    assert actual['vertices'][2] == inventory['vertices'][2]
    assert actual['vertices'][4] == inventory['vertices'][4]
    audit = actual['marker_grounding']
    assert audit['review_required'] is True
    assert audit['assignment_summary']['global_unique_assignments'] == 0
    assert {r['vertex'] for r in audit['untrusted_vertices']} == {'2', '4'}


def test_extra_connected_marker_requests_inventory_review_without_adding_a_node():
    image, inventory, centers = compressed_model_inventory()
    inventory['vertices'].pop()
    actual = ground_nodes(image, [inventory])[0]
    assert len(actual['vertices']) == 4
    audit = actual['marker_grounding']
    assert audit['grounded_vertices'] == 4
    assert audit['untrusted_vertices'] == []
    assert audit['status'] == 'partial' and audit['review_required'] is True
    assert any(m['review_relevant'] and math.dist(m['work_point'], centers[4]) < 2
               for m in audit['unbound_strong_markers'])


def test_far_isolated_text_hole_is_visible_in_diagnostics_but_not_a_new_node_claim():
    image = np.full((180, 320, 3), 255, np.uint8)
    cv2.circle(image, (150, 80), 5, (0, 0, 0), 2)
    inventory = graph((320, 180), [])
    actual = ground_nodes(Image.fromarray(image), [inventory])[0]
    audit = actual['marker_grounding']
    assert audit['unbound_strong_markers']
    assert all(not row['review_relevant'] for row in audit['unbound_strong_markers'])
    assert audit['review_required'] is False
    assert actual['vertices'] == []


@pytest.mark.parametrize('choices,expected,status', [
    ({0: [0, 1], 1: [1]}, {0: 0, 1: 1}, 'unique'),
    ({0: [0, 1], 1: [0, 1]}, {}, 'global_assignment_not_unique'),
    ({0: [0, 1]}, {}, 'global_assignment_not_unique'),
    ({0: [0], 1: [0]}, {}, 'global_assignment_incomplete'),
    ({0: [0], 1: [0], 2: [0, 1, 2]}, {}, 'global_assignment_incomplete'),
])
def test_remaining_assignment_requires_a_unique_complete_component(choices, expected, status):
    from graph_marker_grounding import _unique_remaining_assignments
    relations = {ni: [(float(mi+1), mi) for mi in markers] for ni, markers in choices.items()}
    selected, rejected, components = _unique_remaining_assignments(relations)
    assert {ni: mi for ni, (mi, _) in selected.items()} == expected
    assert all(c['status'] == status for c in components)
    assert not rejected if expected else set(rejected) == set(choices)


@pytest.mark.parametrize('character,font,scale', [
    ('4', cv2.FONT_HERSHEY_SIMPLEX, 2.),
    ('2', cv2.FONT_HERSHEY_DUPLEX, 1.5),
    ('5', cv2.FONT_HERSHEY_DUPLEX, 2.),
])
def test_round_digit_junction_on_a_line_is_not_a_filled_node(character, font, scale):
    image = np.full((180, 320, 3), 255, np.uint8)
    cv2.line(image, (30, 90), (270, 90), (0, 0, 0), 1)
    cv2.putText(image, character, (140, 100), font, scale, (0, 0, 0), 3, lineType=cv2.LINE_AA)
    # A genuine filled disk in the same image must survive this shape check.
    cv2.line(image, (70, 65), (30, 150), (0, 0, 0), 2)
    cv2.circle(image, (70, 65), 6, (0, 0, 0), -1)
    pool = marker_proposals(Image.fromarray(image))
    strong_filled = [m for m in pool['items'] if m['kind'] == 'filled' and m['confidence'] >= .84]
    assert not any(130 < m['x']*319 < 190 for m in strong_filled)
    assert any(math.dist((m['x']*319, m['y']*179), (70, 65)) < 2 for m in strong_filled)
    assert all(m['evidence']['solid_inner_disk_fraction'] >= .94 for m in strong_filled)


@pytest.mark.parametrize('radius', [4, 5, 7])
def test_wider_filled_disk_check_keeps_real_small_markers(radius):
    image, _, _ = connected_diagram(radius=radius, filled=True)
    pool = marker_proposals(image)
    assert any(m['kind'] == 'filled' and m['confidence'] >= .84
               and math.dist((m['x']*479, m['y']*319), (350, 65)) < 2 for m in pool['items'])


def test_strong_complete_original_rim_can_resolve_low_aggregate_geometry_confidence(monkeypatch):
    import graph_marker_grounding as module
    image = np.full((210, 360, 3), 255, np.uint8)
    cv2.circle(image, (300, 55), 34, (0, 0, 0), 2, lineType=cv2.LINE_AA)
    original = module.estimate_marker_geometry

    def lower_aggregate(*args, **kwargs):
        geometry = original(*args, **kwargs)
        if geometry.get('kind') == 'hollow_marker':
            geometry['confidence'] = .79
        return geometry

    monkeypatch.setattr(module, 'estimate_marker_geometry', lower_aggregate)
    pool = marker_proposals(Image.fromarray(image))
    candidate = next(m for m in pool['items'] if m['radius_pixels'] > 25
                     and math.dist((m['x']*359, m['y']*209), (300, 55)) < 3)
    assert candidate['evidence']['acceptance'] == 'independent_complete_rim_consensus'
    assert candidate['evidence']['original_gradient_rim_support'] >= .95
    assert candidate['evidence']['geometry']['boundary_visible_fraction'] >= .99


def test_partial_rim_cannot_borrow_an_aggregate_score_to_become_a_complete_marker(monkeypatch):
    import graph_marker_grounding as module
    image = np.full((210, 360, 3), 255, np.uint8)
    cv2.ellipse(image, (300, 55), (34, 34), 0, 0, 180, (0, 0, 0), 2, lineType=cv2.LINE_AA)
    # A seed is only a hypothesis. Missing original-gradient sectors reject it
    # before any downstream fit can promote the absent half circumference.
    monkeypatch.setattr(cv2, 'HoughCircles', lambda *args, **kwargs: np.asarray([[[300., 55., 34.]]], np.float32))
    assert not module._large_outlines(module._document(Image.fromarray(image)))[0]


def test_small_ring_touching_an_outer_node_is_advisory_not_a_competing_anchor():
    image = np.full((270, 380, 3), 255, np.uint8)
    cv2.circle(image, (180, 100), 36, (0, 0, 0), 2, lineType=cv2.LINE_AA)
    cv2.line(image, (180, 142), (170, 220), (0, 0, 0), 2)
    cv2.circle(image, (180, 142), 5, (255, 255, 255), -1)
    cv2.circle(image, (180, 142), 5, (0, 0, 0), 1)
    # A separate, genuinely small ring remains an ordinary candidate.
    cv2.line(image, (280, 140), (300, 220), (0, 0, 0), 2)
    cv2.circle(image, (280, 140), 5, (255, 255, 255), -1)
    cv2.circle(image, (280, 140), 5, (0, 0, 0), 1)
    im = Image.fromarray(image)
    pool = marker_proposals(im)
    touching = [m for m in pool['items'] if m['radius_pixels'] < 10
                and math.dist((m['x']*379, m['y']*269), (180, 142)) < 3]
    assert touching and all(m.get('advisory_only') and m['confidence'] < .84 for m in touching)
    assert any(m['confidence'] >= .84 and not m.get('advisory_only')
               and math.dist((m['x']*379, m['y']*269), (280, 140)) < 3 for m in pool['items'])
    inventory = graph(im.size, [('large', 180, 119), ('separate_small', 280, 140)])
    actual = ground_nodes(im, [inventory])[0]
    vertex = actual['vertices'][0]
    assert math.dist((vertex['x']*379, vertex['y']*269), (180, 100)) < 3


def test_correct_clipped_marker_is_visual_advice_not_a_hard_connection_veto():
    image = np.full((180, 300, 3), 255, np.uint8)
    cv2.line(image, (100, 90), (295, 90), (0, 0, 0), 1)
    cv2.circle(image, (295, 90), 25, (255, 255, 255), -1)
    cv2.circle(image, (295, 90), 25, (0, 0, 0), 2)
    inventory = graph((300, 180), [('clipped', 295, 90)])
    inventory['node_complete'] = True
    actual = ground_nodes(Image.fromarray(image), [inventory])[0]
    assert actual['vertices'] == inventory['vertices']
    assert actual['node_complete'] is True
    audit = actual['marker_grounding']
    assert audit['review_required'] is True
    assert audit['position_gate']['hard_blocking'] is False
    assert audit['position_gate']['unobserved_vertices'] == ['clipped']
    assert audit['untrusted_vertices'][0]['classification'] == 'pixel_unobserved'
    assert audit['untrusted_vertices'][0]['blocks_connections'] is False


def test_large_outline_without_measured_ports_is_an_inventory_review_hint():
    image = np.full((200, 320, 3), 255, np.uint8)
    cv2.circle(image, (160, 100), 35, (0, 0, 0), 2, lineType=cv2.LINE_AA)
    actual = ground_nodes(Image.fromarray(image), [graph((320, 200), [])])[0]
    audit = actual['marker_grounding']
    assert any(not m['connected_stroke'] and m['review_relevant'] for m in audit['unbound_strong_markers'])
    assert audit['review_required'] is True
    assert audit['position_gate']['hard_blocking'] is False
    assert actual['vertices'] == []
