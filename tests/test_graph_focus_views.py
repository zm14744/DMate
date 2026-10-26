"""Focus views select immutable source pixels, never model-supplied answers."""
import copy
import hashlib

import numpy as np
import pytest
from PIL import Image

from graph_focus_views import build_focused_views, MAX_SIDE, MAX_TOTAL_PIXELS, MAX_VIEW_PIXELS


def issue(identity='i1', **values):
    return {'id': identity, 'graph_id': None, 'hint_ids': [], 'edge_ids': [], 'vertex_ids': [], **values}


def graph():
    return {'id': 'G1', 'bbox': [0., 0., 1., 1.], 'vertices': [
        {'id': 'a', 'x': .2, 'y': .2}, {'id': 'b', 'x': .2, 'y': .6},
        {'id': 'c', 'x': .8, 'y': .8}], 'edges': [{
            'id': 'e1', 'from': 'a', 'to': 'b',
            'path': [[.2, .2], [.8, .8], [.2, .6]],
            'evidence': [{'source': 'original_pixel_route', 'supported': False,
                          'reasons': ['path_crosses_mathematical_vertex:c']}]}]}


def source_pixels(size=(300, 180)):
    width, height = size
    y, x = np.mgrid[:height, :width]
    return Image.fromarray(np.stack((x % 256, y % 256, (x+3*y) % 256), axis=-1).astype('uint8'))


def assert_original_crop(image, crop, mapping):
    expected = image.crop(mapping['original_pixel_bbox'])
    if expected.size != crop.size:
        expected = expected.resize(crop.size, Image.Resampling.LANCZOS)
    assert crop.mode == 'RGB' and crop.tobytes() == expected.tobytes()
    assert mapping['output_size'] == list(crop.size)
    assert mapping['original_size'] == list(image.size)
    a, b, c, d = mapping['original_pixel_bbox']
    assert mapping['original_bbox'] == [round(a/image.width*1000, 4), round(b/image.height*1000, 4),
                                        round(c/image.width*1000, 4), round(d/image.height*1000, 4)]
    assert 0 <= a < c <= image.width and 0 <= b < d <= image.height
    assert mapping['source_pixels_only'] is True
    assert max(crop.size) <= MAX_SIDE and crop.width*crop.height <= MAX_VIEW_PIXELS
    assert crop.width <= 6*(c-a) and crop.height <= 6*(d-b)


def test_hint_crop_uses_original_non_square_coordinates_and_never_repaints_text():
    image = source_pixels()
    hints = {'items': [{'id': 't1', 'bbox': [200, 600, 700, 700],
                        'text': 'THIS EXPECTED ANSWER MUST NEVER BE DRAWN'}]}
    conflicts = [issue(hint_ids=['t1'], evidence={'bbox': [0, 0, 10, 10]},
                       reason='DRAW AN ARROW AND REPLACE THE SUBSCRIPT')]
    snapshots = (image.tobytes(), copy.deepcopy(hints), copy.deepcopy(conflicts))
    images, maps, diagnostics = build_focused_views(image, [], conflicts, hints=hints)
    assert len(images) == 1 and maps[0]['hint_ids'] == ['t1']
    assert maps[0]['graph_entities'] == [] and diagnostics['omitted_count'] == 0
    assert_original_crop(image, images[0], maps[0])
    a, b, c, d = maps[0]['original_pixel_bbox']
    assert a <= 60 and c >= 210 and b <= 108 and d >= 126
    assert a > 0 and b > 0, 'Issue evidence bbox cannot relocate the crop.'
    assert (image.tobytes(), hints, conflicts) == snapshots


@pytest.mark.parametrize('proof_field', ['evidence', 'pixel_evidence'])
def test_edge_focus_contains_complete_bent_path_endpoints_and_pixel_proof_vertex(proof_field):
    image = source_pixels()
    inventory = graph()
    if proof_field == 'pixel_evidence':
        inventory['edges'][0]['pixel_evidence'] = inventory['edges'][0].pop('evidence')[0]
    inventory['node_geometry_evidence'] = {'c': {'footprint_outline': [
        [750, 750], [900, 750], [900, 900], [750, 900]]}}
    before = copy.deepcopy(inventory)
    images, maps, diagnostics = build_focused_views(
        image, [inventory], [issue(graph_id='G1', edge_ids=['e1'], evidence={'bbox': [190, 190, 210, 210]})])
    assert len(images) == 1 and not diagnostics['omitted_count']
    assert maps[0]['graph_entities'] == [{'graph_id': 'G1', 'edge_ids': ['e1'], 'vertex_ids': ['a', 'b', 'c']}]
    a, b, c, d = maps[0]['original_pixel_bbox']
    for x, y in inventory['edges'][0]['path']+[[.9, .9]]:
        assert a <= x*(image.width-1) < c and b <= y*(image.height-1) < d
    assert_original_crop(image, images[0], maps[0])
    assert inventory == before


@pytest.mark.parametrize('conflict', [
    issue(hint_ids=['missing']), issue(graph_id='G1', edge_ids=['missing']),
    issue(graph_id='G1', vertex_ids=['missing']), issue(graph_id='other', edge_ids=['e1']),
    issue(kind='uncertain_text_region:t1'), issue(graph_id='G1')])
def test_unknown_ids_or_prose_cannot_authorize_an_arbitrary_bbox(conflict):
    conflict['evidence'] = {'source': 'original', 'bbox': [0, 0, 1000, 1000]}
    hints = {'items': [{'id': 't1', 'bbox': [200, 600, 700, 700]}]}
    images, maps, diagnostics = build_focused_views(source_pixels(), [graph()], [conflict], hints=hints)
    assert not images and not maps
    assert diagnostics['omitted_count'] > 0


@pytest.mark.parametrize('box', [[0, 0, 0, 100], [-1, 0, 10, 10], [800, 900, 200, 100],
                               [0, 0, 1001, 100], [0, 0, float('nan'), 100]])
def test_invalid_authoritative_hint_bounds_abstain(box):
    images, maps, diagnostics = build_focused_views(source_pixels(), [], [issue(hint_ids=['t1'])],
        hints={'items': [{'id': 't1', 'bbox': box}]})
    assert not images and not maps
    assert diagnostics['omitted'][0]['reason'] == 'unknown_ambiguous_or_unlocated_hint'


def test_duplicate_hint_identity_is_ambiguous_even_when_one_box_is_valid():
    hints = {'items': [{'id': 't1', 'bbox': [100, 100, 200, 200]},
                       {'id': 't1', 'bbox': [700, 700, 800, 800]}]}
    images, maps, diagnostics = build_focused_views(source_pixels(), [], [issue(hint_ids=['t1'])], hints=hints)
    assert not images and not maps
    assert diagnostics['invalid_records']['ambiguous_hint_ids'] == 1


def test_duplicate_graph_or_edge_identity_cannot_choose_a_region():
    first, second = graph(), graph()
    images, _, diagnostics = build_focused_views(source_pixels(), [first, second],
                                                [issue(graph_id='G1', edge_ids=['e1'])])
    assert not images and diagnostics['invalid_records']['ambiguous_graph_ids'] == 1
    first['edges'].append(copy.deepcopy(first['edges'][0]))
    images, _, diagnostics = build_focused_views(source_pixels(), [first],
                                                [issue(graph_id='G1', edge_ids=['e1'])])
    assert not images and diagnostics['invalid_records']['ambiguous_edge_ids'] == 1


def test_overlapping_hints_share_one_source_crop_and_keep_all_related_ids():
    hints = {'items': [{'id': 't1', 'bbox': [100, 600, 700, 700]},
                       {'id': 't2', 'bbox': [105, 605, 705, 705]}]}
    image = source_pixels()
    images, maps, diagnostics = build_focused_views(image, [],
        [issue('first', hint_ids=['t1']), issue('second', hint_ids=['t2'])], hints=hints)
    assert len(images) == 1 and diagnostics['resolved_target_count'] == 2
    assert maps[0]['hint_ids'] == ['t1', 't2'] and maps[0]['issue_ids'] == ['first', 'second']
    assert_original_crop(image, images[0], maps[0])


def test_view_count_and_pixel_budget_have_explicit_omissions():
    image = Image.new('RGB', (2000, 2000), 'white')
    hints = {'items': [{'id': f't{i}', 'bbox': box} for i, box in enumerate([
        [50, 50, 150, 150], [850, 50, 950, 150], [50, 850, 150, 950], [850, 850, 950, 950]])]}
    conflicts = [issue(f'i{i}', hint_ids=[f't{i}']) for i in range(4)]
    images, maps, diagnostics = build_focused_views(image, [], conflicts, hints=hints)
    assert len(images) == 3 and diagnostics['capacity']['view_limit_reached'] is True
    assert diagnostics['capacity']['resampling_size_limited'] is True
    assert diagnostics['omitted_count'] == 1 and diagnostics['omitted'][0]['entity_id'] == 't3'
    assert diagnostics['output_pixels'] == sum(i.width*i.height for i in images) <= MAX_TOTAL_PIXELS
    for crop, mapping in zip(images, maps):
        assert_original_crop(image, crop, mapping)


def test_long_text_crop_stays_within_side_limit_without_multiple_resizing(monkeypatch):
    image = source_pixels((3200, 200))
    resized, original_resize = [], Image.Image.resize
    def record(self, *args, **kwargs):
        resized.append(self.size)
        return original_resize(self, *args, **kwargs)
    monkeypatch.setattr(Image.Image, 'resize', record)
    images, maps, _ = build_focused_views(image, [], [issue(hint_ids=['t1'])],
        hints={'items': [{'id': 't1', 'bbox': [50, 400, 950, 600]}]})
    assert len(images) == 1 and images[0].width == MAX_SIDE
    a, b, c, d = maps[0]['original_pixel_bbox']
    assert resized == [(c-a, d-b)], 'One resize directly from the source crop.'


def test_vertex_ids_are_scoped_to_the_named_graph():
    one, two = graph(), graph()
    two['id'] = 'G2'
    two['vertices'][0].update(x=.9, y=.1)
    images, maps, _ = build_focused_views(source_pixels(), [one, two],
                                         [issue(graph_id='G2', vertex_ids=['a'])])
    assert len(images) == 1 and maps[0]['graph_entities'] == [
        {'graph_id': 'G2', 'edge_ids': [], 'vertex_ids': ['a']}]
    assert maps[0]['original_pixel_bbox'][0] > 200


def test_transparency_uses_the_shared_white_background_decode():
    image = Image.new('RGBA', (100, 80), (0, 0, 0, 0))
    images, _, _ = build_focused_views(image, [], [issue(hint_ids=['t1'])],
        hints={'items': [{'id': 't1', 'bbox': [100, 100, 900, 900]}]})
    assert images[0].mode == 'RGB' and images[0].getextrema() == ((255, 255),)*3


def test_fixed_edge_with_invalid_path_cannot_fall_back_to_issue_bbox():
    inventory = graph()
    inventory['edges'][0]['path'] = [[.2, .2], [1.1, .5]]
    images, _, diagnostics = build_focused_views(source_pixels(), [inventory],
        [issue(graph_id='G1', edge_ids=['e1'], evidence={'bbox': [0, 0, 1000, 1000]})])
    assert not images and diagnostics['omitted'][0]['reason'] == 'unknown_ambiguous_or_invalid_edge_path'


def test_deadline_is_checked_before_image_generation():
    def deadline():
        raise TimeoutError('cancelled source crop')
    with pytest.raises(TimeoutError):
        build_focused_views(source_pixels(), [graph()], [issue(graph_id='G1', edge_ids=['e1'])],
                            check_deadline=deadline)


def test_body_region_crop_uses_fixed_original_pixels_and_never_issue_bbox_or_text():
    image = source_pixels((400, 240))
    regions = [{'id': 'line_1', 'role': 'body', 'source': 'original',
                'bbox': [300, 550, 800, 650], 'text': 'WRONG TRANSCRIPTION MUST NOT BE RENDERED'}]
    conflicts = [issue(body_region_ids=['line_1'], bbox=[0, 0, 5, 5],
        evidence={'source': 'original', 'bbox': [0, 0, 5, 5]},
        reason='AN EXPECTED ANSWER MUST NOT SELECT OR ALTER SOURCE PIXELS')]
    before = (image.tobytes(), copy.deepcopy(regions), copy.deepcopy(conflicts))
    images, maps, diagnostics = build_focused_views(image, [], conflicts, body_regions=regions)
    assert len(images) == 1 and diagnostics['omitted_count'] == 0
    mapping = maps[0]
    assert mapping['body_region_ids'] == ['line_1'] and mapping['hint_ids'] == []
    assert mapping['targets'] == [{'issue_id': 'i1', 'entity_type': 'body_region',
                                   'body_region_id': 'line_1'}]
    assert_original_crop(image, images[0], mapping)
    left, top, right, bottom = mapping['original_pixel_bbox']
    assert 0 < left <= 120 and right >= 320 and 0 < top <= 132 and bottom >= 156
    expected = image.crop(mapping['original_pixel_bbox']).resize(images[0].size, Image.Resampling.LANCZOS)
    assert hashlib.sha256(images[0].tobytes()).hexdigest() == hashlib.sha256(expected.tobytes()).hexdigest()
    assert (image.tobytes(), regions, conflicts) == before
    regions[0]['text'] = 'A DIFFERENT OCR ANSWER'
    repeated, repeated_maps, _ = build_focused_views(image, [], conflicts, body_regions=regions)
    assert repeated[0].tobytes() == images[0].tobytes() and repeated_maps == maps


def test_body_and_hint_identity_namespaces_are_independent_even_with_same_id():
    image = source_pixels((500, 500))
    hints = {'items': [{'id': 'shared', 'bbox': [100, 100, 250, 150]}]}
    regions = [{'id': 'shared', 'source': 'original', 'bbox': [700, 800, 900, 850]}]
    images, maps, _ = build_focused_views(image, [],
        [issue(hint_ids=['shared'], body_region_ids=['shared'])], hints=hints, body_regions=regions)
    assert len(images) == 2
    assert maps[0]['hint_ids'] == ['shared'] and maps[0]['body_region_ids'] == []
    assert maps[1]['hint_ids'] == [] and maps[1]['body_region_ids'] == ['shared']
    assert maps[0]['targets'][0]['entity_type'] == 'hint'
    assert maps[1]['targets'][0]['entity_type'] == 'body_region'
    assert maps[0]['original_pixel_bbox'][3] < maps[1]['original_pixel_bbox'][1]
    for crop, mapping in zip(images, maps):
        assert_original_crop(image, crop, mapping)
    # An OCR hint with this ID never grants access to a body-region crop.
    images, _, diagnostics = build_focused_views(image, [], [issue(body_region_ids=['shared'])],
        hints=hints, body_regions=[])
    assert not images
    assert diagnostics['omitted'][0]['reason'] == 'unknown_or_ambiguous_body_region'


def test_overlapping_body_regions_and_hints_merge_without_losing_namespace_or_ids():
    image = source_pixels()
    regions = [{'id': rid, 'source': 'original', 'bbox': [100, 600, 700, 700]}
               for rid in ('line_1', 'line_2')]
    hints = {'items': [{'id': 'line_1', 'bbox': [105, 605, 705, 705]}]}
    images, maps, diagnostics = build_focused_views(image, [],
        [issue(body_region_ids=['line_1', 'line_2'], hint_ids=['line_1'])],
        hints=hints, body_regions=regions)
    assert len(images) == 1 and diagnostics['resolved_target_count'] == 3
    assert maps[0]['body_region_ids'] == ['line_1', 'line_2'] and maps[0]['hint_ids'] == ['line_1']
    assert [t['entity_type'] for t in maps[0]['targets']] == ['hint', 'body_region', 'body_region']
    assert_original_crop(image, images[0], maps[0])


@pytest.mark.parametrize('region, reason', [
    ({'id': 'line_1', 'bbox': [100, 100, 300, 200]}, 'body_region_source_not_original'),
    ({'id': 'line_1', 'source': 'ocr', 'bbox': [100, 100, 300, 200]}, 'body_region_source_not_original'),
    ({'id': 'line_1', 'source': 'original', 'bbox': [300, 100, 100, 200]}, 'invalid_body_region_bounds'),
    ({'id': 'line_1', 'source': 'original', 'bbox': [0, 0, 1001, 200]}, 'invalid_body_region_bounds'),
    ({'id': 'line_1', 'source': 'original', 'bbox': [0, 0, float('nan'), 200]}, 'invalid_body_region_bounds'),
])
def test_invalid_body_region_source_or_bounds_never_falls_back_to_issue_evidence(region, reason):
    images, maps, diagnostics = build_focused_views(source_pixels(), [],
        [issue(body_region_ids=['line_1'], evidence={'source': 'original', 'bbox': [100, 100, 300, 200]})],
        body_regions=[region])
    assert not images and not maps
    assert diagnostics['omitted'][0] == {'issue_id': 'i1', 'reason': reason,
                                        'entity_type': 'body_region', 'entity_id': 'line_1'}


def test_duplicate_body_region_identity_is_ambiguous_and_duplicate_references_are_visible():
    region = {'id': 'line_1', 'source': 'original', 'bbox': [100, 100, 300, 200]}
    images, _, diagnostics = build_focused_views(source_pixels(), [], [issue(body_region_ids=['line_1'])],
        body_regions=[region, {**region, 'bbox': [700, 700, 900, 800]}])
    assert not images
    assert diagnostics['invalid_records']['ambiguous_body_region_ids'] == 1
    assert diagnostics['omitted'][0]['reason'] == 'unknown_or_ambiguous_body_region'
    images, maps, diagnostics = build_focused_views(source_pixels(), [],
        [issue(body_region_ids=['line_1', 'line_1'])], body_regions=[region])
    assert len(images) == 1 and maps[0]['body_region_ids'] == ['line_1']
    assert diagnostics['omitted'][0]['reason'] == 'duplicate_reference_id'


def test_body_region_inventory_over_capacity_cannot_select_a_truncated_prefix():
    from graph_focus_views import MAX_BODY_REGIONS
    regions = [{'id': f'line_{i}', 'source': 'original', 'bbox': [100, 100, 300, 200]}
               for i in range(MAX_BODY_REGIONS)]
    # The duplicate after the cap must not let the first location win.
    regions.append({**regions[0], 'bbox': [700, 700, 900, 800]})
    images, maps, diagnostics = build_focused_views(source_pixels(), [],
        [issue(body_region_ids=['line_0'])], body_regions=regions)
    assert not images and not maps
    assert diagnostics['capacity']['body_region_limit_reached'] is True
    assert diagnostics['omitted'][0]['reason'] == 'body_region_inventory_capacity_reached'
    assert diagnostics['requested_body_region_count'] == MAX_BODY_REGIONS+1


def test_body_reference_over_capacity_is_reported_and_cannot_pick_unbounded_locations():
    from graph_focus_views import MAX_REFERENCES
    images, maps, diagnostics = build_focused_views(source_pixels(), [],
        [issue(body_region_ids=[f'absent_{i}' for i in range(MAX_REFERENCES+1)])], body_regions=[])
    assert not images and not maps
    assert diagnostics['capacity']['reference_limit_reached'] is True
    assert diagnostics['omitted'][0]['reason'] == 'reference_capacity_reached'
    assert diagnostics['omitted_records_truncated'] is True


def test_body_view_capacity_and_size_limits_retain_omitted_body_identity():
    image = Image.new('RGB', (2000, 2000), 'white')
    regions = [{'id': f'line_{i}', 'source': 'original', 'bbox': bounds}
               for i, bounds in enumerate(([50, 50, 150, 150], [850, 50, 950, 150],
                                           [50, 850, 150, 950], [850, 850, 950, 950]))]
    images, maps, diagnostics = build_focused_views(image, [],
        [issue(body_region_ids=[r['id'] for r in regions])], body_regions=regions)
    assert len(images) == 3 and diagnostics['capacity']['view_limit_reached']
    assert diagnostics['omitted'] == [{'issue_id': 'i1', 'reason': 'view_capacity_reached',
                                       'entity_type': 'body_region', 'entity_id': 'line_3'}]
    assert sum(c.width*c.height for c in images) <= MAX_TOTAL_PIXELS
    for crop, mapping in zip(images, maps):
        assert_original_crop(image, crop, mapping)


def test_no_body_region_argument_preserves_legacy_mapping_and_diagnostics_shape():
    image = source_pixels()
    hints = {'items': [{'id': 't1', 'bbox': [200, 600, 700, 700]}]}
    conflicts = [issue(hint_ids=['t1'])]
    legacy, legacy_maps, legacy_diagnostics = build_focused_views(image, [], conflicts, hints=hints)
    explicit, explicit_maps, explicit_diagnostics = build_focused_views(
        image, [], conflicts, hints=hints, body_regions=None)
    assert legacy[0].tobytes() == explicit[0].tobytes()
    assert legacy_maps == explicit_maps and legacy_diagnostics == explicit_diagnostics
    assert 'body_region_ids' not in legacy_maps[0] and 'targets' not in legacy_maps[0]
    assert 'requested_body_region_count' not in legacy_diagnostics
    assert 'max_body_regions' not in legacy_diagnostics['limits']


def marker(identity='m1', **values):
    return {'id': identity, 'x': 750., 'y': 300., 'radius_x': 20., 'radius_y': 100., **values}


def test_marker_crop_uses_measured_center_and_both_original_axes_without_confirming_a_vertex():
    image = source_pixels((600, 200))
    markers = [marker(label='DO NOT DRAW', confidence=1., kind='solid')]
    conflicts = [issue(marker_ids=['m1'], bbox=[0, 0, 5, 5],
        evidence={'source': 'original', 'bbox': [0, 0, 5, 5]},
        reason='REPLACE THIS CIRCLE WITH AN EXPECTED VERTEX')]
    before = (image.tobytes(), copy.deepcopy(markers), copy.deepcopy(conflicts))
    images, maps, diagnostics = build_focused_views(image, [], conflicts, markers=markers)
    assert len(images) == 1 and diagnostics['omitted_count'] == 0
    mapping = maps[0]
    assert mapping['marker_ids'] == ['m1']
    assert mapping['graph_entities'] == [] and mapping['hint_ids'] == []
    assert mapping['targets'] == [{'issue_id': 'i1', 'entity_type': 'marker', 'marker_id': 'm1'}]
    assert_original_crop(image, images[0], mapping)
    left, top, right, bottom = mapping['original_pixel_bbox']
    assert 350 < left <= .73*599 and right > .77*599
    assert 0 < top <= .2*199 and bottom > .4*199
    assert (image.tobytes(), markers, conflicts) == before
    markers[0].update(label='DIFFERENT ANSWER', confidence=0., kind='unknown')
    repeated, maps_again, _ = build_focused_views(image, [], conflicts, markers=markers)
    assert repeated[0].tobytes() == images[0].tobytes() and maps_again == maps


def test_marker_hint_body_and_vertex_identity_namespaces_cannot_select_each_other():
    image = source_pixels((1000, 1000))
    hints = {'items': [{'id': 'shared', 'bbox': [50, 50, 200, 90]}]}
    bodies = [{'id': 'shared', 'source': 'original', 'bbox': [50, 800, 200, 850]}]
    markers = [marker('shared', x=850, y=300, radius_x=12, radius_y=12)]
    conflicts = [issue(hint_ids=['shared'], body_region_ids=['shared'], marker_ids=['shared'])]
    images, maps, diagnostics = build_focused_views(image, [], conflicts,
        hints=hints, body_regions=bodies, markers=markers)
    assert len(images) == 3 and diagnostics['omitted_count'] == 0
    assert [m['targets'][0]['entity_type'] for m in maps] == ['hint', 'body_region', 'marker']
    assert maps[0]['marker_ids'] == maps[1]['marker_ids'] == []
    assert maps[2]['hint_ids'] == maps[2]['body_region_ids'] == []
    for crop, mapping in zip(images, maps):
        assert_original_crop(image, crop, mapping)
    # A same-named OCR/body/graph entity grants no marker reference, and vice versa.
    images, _, diagnostics = build_focused_views(image, [graph()], [issue(marker_ids=['shared'])],
        hints=hints, body_regions=bodies, markers=[])
    assert not images and diagnostics['omitted'][0]['reason'] == 'unknown_or_ambiguous_marker'
    images, _, diagnostics = build_focused_views(image, [graph()],
        [issue(graph_id='G1', vertex_ids=['shared'])], markers=markers)
    assert not images and diagnostics['omitted'][0]['reason'] == 'unknown_ambiguous_or_unlocated_vertex'


@pytest.mark.parametrize('values', [
    {'x': -1}, {'y': 1001}, {'radius_x': 0}, {'radius_y': -2},
    {'radius_x': float('inf')}, {'y': float('nan')}, {'radius_y': True},
    {'x': '750'}, {'radius_x': None},
])
def test_invalid_measured_marker_does_not_fall_back_to_issue_coordinates(values):
    images, maps, diagnostics = build_focused_views(source_pixels(), [],
        [issue(marker_ids=['m1'], x=750, y=300, radius_x=20, radius_y=100,
               evidence={'source': 'original', 'bbox': [500, 200, 900, 500]})],
        markers=[marker(**values)])
    assert not images and not maps
    assert diagnostics['omitted'][0] == {'issue_id': 'i1', 'reason': 'invalid_marker_geometry',
                                        'entity_type': 'marker', 'entity_id': 'm1'}


def test_marker_duplicate_id_is_ambiguous_and_duplicate_reference_is_reported():
    images, _, diagnostics = build_focused_views(source_pixels(), [], [issue(marker_ids=['m1'])],
        markers=[marker(), marker(x=100)])
    assert not images and diagnostics['invalid_records']['ambiguous_marker_ids'] == 1
    assert diagnostics['omitted'][0]['reason'] == 'unknown_or_ambiguous_marker'
    images, maps, diagnostics = build_focused_views(source_pixels(), [],
        [issue(marker_ids=['m1', 'm1'])], markers=[marker()])
    assert len(images) == 1 and maps[0]['marker_ids'] == ['m1']
    assert diagnostics['omitted'][0] == {'issue_id': 'i1', 'reason': 'duplicate_reference_id',
                                        'entity_type': 'marker_ids', 'entity_id': 'm1'}


def test_over_capacity_marker_inventory_does_not_infer_uniqueness_from_its_prefix():
    from graph_focus_views import MAX_MARKERS
    markers = [marker(f'm{i}') for i in range(MAX_MARKERS)]
    markers.append(marker('m0', x=100))
    images, maps, diagnostics = build_focused_views(source_pixels(), [], [issue(marker_ids=['m0'])],
        markers=markers)
    assert not images and not maps and diagnostics['capacity']['marker_limit_reached'] is True
    assert diagnostics['requested_marker_count'] == MAX_MARKERS+1
    assert diagnostics['omitted'][0]['reason'] == 'marker_inventory_capacity_reached'


def test_marker_reference_errors_and_capacity_are_explicit():
    from graph_focus_views import MAX_REFERENCES
    images, maps, diagnostics = build_focused_views(source_pixels(), [],
        [issue(marker_ids=[None]+[f'absent_{i}' for i in range(MAX_REFERENCES)])], markers=[])
    assert not images and not maps and diagnostics['capacity']['reference_limit_reached'] is True
    assert diagnostics['omitted'][0]['reason'] == 'reference_capacity_reached'
    assert diagnostics['omitted'][1]['reason'] == 'invalid_reference_id'
    assert diagnostics['omitted_records_truncated'] is True


def test_overlapping_marker_and_body_share_source_pixels_but_keep_both_namespaces():
    image = source_pixels()
    markers = [marker(x=400, y=650, radius_x=100, radius_y=40)]
    bodies = [{'id': 'line_1', 'source': 'original', 'bbox': [300, 610, 500, 690]}]
    images, maps, diagnostics = build_focused_views(image, [],
        [issue(marker_ids=['m1'], body_region_ids=['line_1'])], markers=markers, body_regions=bodies)
    assert len(images) == 1 and diagnostics['resolved_target_count'] == 2
    assert maps[0]['marker_ids'] == ['m1'] and maps[0]['body_region_ids'] == ['line_1']
    assert [t['entity_type'] for t in maps[0]['targets']] == ['body_region', 'marker']
    assert_original_crop(image, images[0], maps[0])


def test_marker_views_respect_existing_three_crop_and_pixel_budgets_with_named_omission():
    image = Image.new('RGB', (2000, 2000), 'white')
    markers = [marker(f'm{i}', x=x, y=y, radius_x=40, radius_y=40)
               for i, (x, y) in enumerate(((100, 100), (900, 100), (100, 900), (900, 900)))]
    images, maps, diagnostics = build_focused_views(image, [],
        [issue(marker_ids=[m['id'] for m in markers])], markers=markers)
    assert len(images) == 3 and diagnostics['capacity']['view_limit_reached'] is True
    assert diagnostics['omitted'] == [{'issue_id': 'i1', 'reason': 'view_capacity_reached',
                                       'entity_type': 'marker', 'entity_id': 'm3'}]
    assert sum(c.width*c.height for c in images) <= MAX_TOTAL_PIXELS
    for crop, mapping in zip(images, maps):
        assert_original_crop(image, crop, mapping)


def test_no_marker_argument_preserves_body_aware_and_legacy_outputs():
    image = source_pixels()
    body = [{'id': 'line_1', 'source': 'original', 'bbox': [300, 610, 500, 690]}]
    conflicts = [issue(body_region_ids=['line_1'])]
    images, maps, diagnostics = build_focused_views(image, [], conflicts, body_regions=body)
    explicit, explicit_maps, explicit_diagnostics = build_focused_views(
        image, [], conflicts, body_regions=body, markers=None)
    assert images[0].tobytes() == explicit[0].tobytes()
    assert maps == explicit_maps and diagnostics == explicit_diagnostics
    assert 'marker_ids' not in maps[0] and 'requested_marker_count' not in diagnostics
    assert 'max_markers' not in diagnostics['limits']
