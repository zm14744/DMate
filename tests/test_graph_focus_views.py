"""Focus views select immutable source pixels, never model-supplied answers."""
import copy

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
