"""Original-pixel marker crops only; no reference graph, model or network."""
import copy
import json
import math

import pytest
from PIL import Image

from graph_marker_views import (
    CELL_SIDE, MAX_MARKERS, MAX_PIXELS, MAX_SCALE, MAX_SIDE, MAX_TILES,
    build_marker_review_sheet,
)
from image_evidence import decode_document_image


def marker(identity='candidate_z', **changes):
    return {'id': identity, 'x': 500., 'y': 500., 'radius_x': 12., 'radius_y': 16., **changes}


def pattern(size=(243, 157)):
    image = Image.new('RGB', size)
    image.putdata([((x*7+y*11) % 256, (y*13) % 256, (x*17) % 256)
                   for y in range(size[1]) for x in range(size[0])])
    return image


def test_tiles_are_exact_single_source_crop_resize_with_white_padding_and_precise_maps():
    original = pattern()
    candidates = [marker('z'), marker('a', x=975, y=38, radius_x=30)]
    before, before_pixels = copy.deepcopy(candidates), original.tobytes()
    sheet, mappings, diagnostics = build_marker_review_sheet(original, candidates)
    assert sheet.mode == 'RGB' and [m['marker_id'] for m in mappings] == ['z', 'a']
    for candidate, row in zip(candidates, mappings):
        a, b, c, d = row['original_pixel_bbox']
        x, y, right, bottom = row['sheet_pixel_bbox']
        expected = original.crop((a, b, c, d))
        if expected.size != tuple(row['output_size']):
            expected = expected.resize(tuple(row['output_size']), Image.Resampling.LANCZOS)
        assert sheet.crop((x, y, right, bottom)).tobytes() == expected.tobytes()
        assert row['original_center'] == [candidate['x'], candidate['y']]
        assert row['original_center_pixel'] == [candidate['x']/1000*(original.width-1),
                                                candidate['y']/1000*(original.height-1)]
        assert row['original_bbox'] == [a/original.width*1000, b/original.height*1000,
                                        c/original.width*1000, d/original.height*1000]
        assert row['sheet_bbox'] == [x/sheet.width*1000, y/sheet.height*1000,
                                     right/sheet.width*1000, bottom/sheet.height*1000]
        assert row['coordinate_space'] == 'original_1000'
        assert row['sheet_coordinate_space'] == 'sheet_1000'
        assert row['pixel_bbox_convention'] == 'half_open'
        assert sheet.getpixel((row['sheet_cell_pixel_bbox'][0], row['sheet_cell_pixel_bbox'][1])) == (255, 255, 255)
    assert original.tobytes() == before_pixels and candidates == before
    assert diagnostics['source_pixels_only'] and not diagnostics['painted_annotations']
    assert not diagnostics['content_certified']


@pytest.mark.parametrize('count', [1, 2, 3, 5, 9, 23, 63, 64])
def test_adaptive_board_has_explicit_dimension_and_pixel_caps(count):
    sheet, maps, diagnostics = build_marker_review_sheet(pattern((45, 37)),
                                                        [marker('m'+str(i)) for i in range(count)])
    assert len(maps) == count and max(sheet.size) <= MAX_SIDE
    assert sheet.width*sheet.height <= MAX_PIXELS
    assert diagnostics['grid_columns'] == math.ceil(math.sqrt(count))
    assert diagnostics['grid_rows'] == math.ceil(count/diagnostics['grid_columns'])
    assert diagnostics['output_pixels'] == sheet.width*sheet.height
    assert len({tuple(m['sheet_cell_pixel_bbox']) for m in maps}) == count


@pytest.mark.parametrize('size', [(1, 1), (2, 3), (20, 1), (400, 90)])
def test_scale_never_exceeds_six_and_border_candidates_stay_in_source(size):
    source = pattern(size)
    sheet, maps, _ = build_marker_review_sheet(source, [marker(x=0, y=1000)])
    row = maps[0]
    assert all(0 < v <= MAX_SCALE for v in row['scale_xy'])
    assert row['clipped_to_source']
    a, b, c, d = row['original_pixel_bbox']
    assert 0 <= a < c <= size[0] and 0 <= b < d <= size[1]
    assert row['original_center_pixel'] == [0, size[1]-1]
    assert sheet.mode == 'RGB'


def test_transparent_source_composites_to_white_without_changing_source_pixels():
    original = Image.new('RGBA', (35, 29), (0, 0, 0, 0))
    original.putpixel((17, 14), (240, 10, 30, 255))
    before = original.tobytes()
    sheet, mappings, _ = build_marker_review_sheet(original, [marker()])
    row = mappings[0]
    source = decode_document_image(original)
    expected = source.crop(tuple(row['original_pixel_bbox'])).resize(tuple(row['output_size']), Image.Resampling.LANCZOS)
    assert sheet.crop(tuple(row['sheet_pixel_bbox'])).tobytes() == expected.tobytes()
    assert original.tobytes() == before and original.mode == 'RGBA'


def test_capacity_omissions_list_every_unrendered_marker_in_input_order():
    candidates = [marker('m'+str(i)) for i in range(MAX_MARKERS)]
    _, maps, diagnostics = build_marker_review_sheet(pattern((31, 29)), candidates)
    assert [m['marker_id'] for m in maps] == [m['id'] for m in candidates[:MAX_TILES]]
    assert diagnostics['omitted'] == [{'input_index': i, 'marker_id': 'm'+str(i),
                                       'reason': 'tile_capacity_reached'}
                                      for i in range(MAX_TILES, MAX_MARKERS)]
    assert diagnostics['capacity']['tile_limit_reached'] and not diagnostics['complete_candidate_view']
    assert diagnostics['status'] == 'partial'


def test_duplicate_identity_omits_all_instances_and_invalid_rows_do_not_consume_tiles():
    candidates = [marker('same'), marker('same', x=800), None, marker(' '), marker('valid')]
    _, maps, diagnostics = build_marker_review_sheet(pattern(), candidates)
    assert [m['marker_id'] for m in maps] == ['valid']
    assert [m['reason'] for m in diagnostics['omitted']] == [
        'duplicate_marker_id', 'duplicate_marker_id', 'invalid_marker_record', 'invalid_marker_id']
    assert [m['input_index'] for m in diagnostics['omitted']] == [0, 1, 2, 3]


@pytest.mark.parametrize('field,value,reason', [
    ('id', '', 'invalid_marker_id'), ('id', 9, 'invalid_marker_id'),
    ('id', 'a'*129, 'invalid_marker_id'), ('id', 'line\nbreak', 'invalid_marker_id'),
    ('x', float('nan'), 'invalid_marker_center'), ('y', float('inf'), 'invalid_marker_center'),
    ('x', True, 'invalid_marker_center'), ('x', -1, 'invalid_marker_center'),
    ('y', 1001, 'invalid_marker_center'), ('x', '500', 'invalid_marker_center'),
    ('radius_x', 0, 'invalid_marker_radius'), ('radius_y', -2, 'invalid_marker_radius'),
    ('radius_x', False, 'invalid_marker_radius'), ('radius_y', float('nan'), 'invalid_marker_radius'),
    ('radius_x', 1001, 'invalid_marker_radius'), ('radius_y', None, 'invalid_marker_radius'),
])
def test_bad_candidate_values_are_visible_without_nonfinite_metadata(field, value, reason):
    sheet, maps, diagnostics = build_marker_review_sheet(pattern(), [marker(**{field: value})])
    assert sheet is None and not maps and diagnostics['omitted'][0]['reason'] == reason
    assert diagnostics['status'] == 'no_valid_markers'
    json.dumps(diagnostics, allow_nan=False)


def test_missing_marker_radius_is_not_guessed():
    candidate = marker(); candidate.pop('radius_x')
    sheet, maps, diagnostic = build_marker_review_sheet(pattern(), [candidate])
    assert sheet is None and not maps
    assert diagnostic['omitted'][0]['reason'] == 'invalid_marker_radius'


def test_arbitrary_bbox_labels_and_confidence_cannot_change_selected_pixels_or_order():
    original = pattern(); candidates = [marker('low', confidence=0), marker('high', x=800, confidence=1)]
    a, maps_a, diag_a = build_marker_review_sheet(original, candidates)
    changed = copy.deepcopy(candidates)
    changed[0].update(confidence=1, bbox=[0, 0, 1000, 1000], label='expected answer', vertex_count=19)
    changed[1].update(confidence=0, bbox=[990, 990, 1000, 1000])
    b, maps_b, diag_b = build_marker_review_sheet(original, changed)
    assert a.tobytes() == b.tobytes() and maps_a == maps_b and diag_a == diag_b


def test_empty_input_returns_no_sheet_and_does_not_decode_unused_original():
    sheet, maps, diagnostics = build_marker_review_sheet(object(), [])
    assert sheet is None and maps == [] and diagnostics['status'] == 'empty'
    assert diagnostics['rendered_marker_count'] == diagnostics['output_pixels'] == 0


@pytest.mark.parametrize('markers', [None, (), {'candidates': []}])
def test_invalid_container_does_not_guess_wrapper_or_convert_iterator(markers):
    with pytest.raises(ValueError, match='fixed_candidate_list'):
        build_marker_review_sheet(object(), markers)


def test_input_capacity_is_enforced_before_image_decode():
    with pytest.raises(ValueError, match='input_capacity_exceeded'):
        build_marker_review_sheet(object(), [marker() for _ in range(MAX_MARKERS+1)])


def test_deadline_is_checked_before_work_and_between_tiles_and_propagates():
    calls = []
    def deadline():
        calls.append(True)
        if len(calls) == 7:
            raise TimeoutError('test_deadline')
    with pytest.raises(TimeoutError, match='test_deadline'):
        build_marker_review_sheet(pattern(), [marker('a'), marker('b')], check_deadline=deadline)
    assert len(calls) == 7
    def expired():
        raise TimeoutError('already_expired')
    with pytest.raises(TimeoutError, match='already_expired'):
        build_marker_review_sheet(object(), [], check_deadline=expired)
    with pytest.raises(TypeError, match='callable'):
        build_marker_review_sheet(pattern(), [], check_deadline=True)
