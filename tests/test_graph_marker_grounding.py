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
