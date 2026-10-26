"""Bounded original-pixel contact sheet for caller-owned marker proposals.

No annotation is painted on the sheet. Identities and coordinate transforms
are JSON metadata outside the image; a marker proposal never establishes a
mathematical vertex. Input order, including capacity omissions, is stable.
"""
from __future__ import annotations

import math
from collections import Counter

from PIL import Image

from image_evidence import decode_document_image


VERSION = '2026-10-26-marker-original-views-v1'
MAX_MARKERS = 256
MAX_TILES = 64
MAX_SIDE = 1600
MAX_PIXELS = 2_000_000
MAX_SCALE = 6.
CELL_SIDE = 176
CELL_PADDING = 8
MIN_CONTEXT_RADIUS = 20.
CONTEXT_PADDING = 12.
RADIUS_MULTIPLIER = 3.


def _identifier(value):
    return (type(value) is str and 0 < len(value) <= 128
            and value.isprintable() and value == value.strip()
            and not any(c.isspace() for c in value))


def _finite(value, *, positive=False):
    return (type(value) in (int, float)
            and (0 < value <= 1000 if positive else 0 <= value <= 1000)
            and math.isfinite(value))


def build_marker_review_sheet(original, markers, *, check_deadline=None):
    """Return ``(RGB sheet or None, mappings, diagnostics)`` without edits.

    ``markers`` is the fixed CPU projection list, with unique ``id`` and
    ``x/y/radius_x/radius_y`` in original_1000. Arbitrary bbox fields, labels,
    confidence, and proposed edges cannot select pixels or reorder candidates.
    Centres and radii use source pixel-centre spans (width-1, height-1), as in
    the marker projection. Half-open crop rectangles map using width/height
    extents. Both pixel rectangles are retained to avoid rounding ambiguity.

    Invalid entries and all instances of duplicate identities are visibly
    omitted. A malformed container or a list over MAX_MARKERS raises before
    allocating image output. Deadline callbacks are cooperative and propagate
    their exceptions; this helper does not claim to interrupt a running resize.
    """
    if check_deadline is not None and not callable(check_deadline):
        raise TypeError('marker_view_deadline_must_be_callable')
    check = check_deadline or (lambda: None)
    check()
    if not isinstance(markers, list):
        raise ValueError('marker_views_require_fixed_candidate_list')
    if len(markers) > MAX_MARKERS:
        raise ValueError('marker_view_input_capacity_exceeded')
    counts = Counter(row['id'] for row in markers
                     if isinstance(row, dict) and _identifier(row.get('id')))
    selected, omitted = [], []
    for index, row in enumerate(markers):
        check()
        identity = row.get('id') if isinstance(row, dict) else None
        if not isinstance(row, dict):
            reason = 'invalid_marker_record'
        elif not _identifier(identity):
            reason = 'invalid_marker_id'
        elif counts[identity] != 1:
            reason = 'duplicate_marker_id'
        elif not all(_finite(row.get(k)) for k in ('x', 'y')):
            reason = 'invalid_marker_center'
        elif not all(_finite(row.get(k), positive=True) for k in ('radius_x', 'radius_y')):
            reason = 'invalid_marker_radius'
        elif len(selected) >= MAX_TILES:
            reason = 'tile_capacity_reached'
        else:
            selected.append({key: row[key] for key in ('id', 'x', 'y', 'radius_x', 'radius_y')})
            continue
        omitted.append({'input_index': index,
                        'marker_id': identity if _identifier(identity) else None,
                        'reason': reason})

    diagnostics = {
        'version': VERSION, 'proposal_only': True, 'source_pixels_only': True,
        'content_certified': False, 'requested_marker_count': len(markers),
        'rendered_marker_count': len(selected),
        'complete_candidate_view': not omitted,
        'omitted': omitted, 'omitted_count': len(omitted),
        'capacity': {'tile_limit_reached': any(x['reason'] == 'tile_capacity_reached' for x in omitted)},
        'limits': {'max_markers': MAX_MARKERS, 'max_tiles': MAX_TILES,
                   'max_side': MAX_SIDE, 'max_pixels': MAX_PIXELS,
                   'max_scale': MAX_SCALE, 'cell_side': CELL_SIDE},
        'ordering': 'candidate_input_order', 'painted_annotations': False,
        'sheet_size': None, 'output_pixels': 0,
    }
    if not selected:
        diagnostics['status'] = 'empty' if not markers else 'no_valid_markers'
        return None, [], diagnostics

    check()
    source = decode_document_image(original)
    check()
    width, height = source.size
    columns = math.ceil(math.sqrt(len(selected)))
    rows = math.ceil(len(selected)/columns)
    sheet_size = (columns*CELL_SIDE, rows*CELL_SIDE)
    if max(sheet_size) > MAX_SIDE or sheet_size[0]*sheet_size[1] > MAX_PIXELS:
        raise ValueError('marker_view_board_capacity_exceeded')
    sheet = Image.new('RGB', sheet_size, 'white')
    content_side = CELL_SIDE-2*CELL_PADDING
    mappings = []
    for index, marker in enumerate(selected):
        check()
        x = marker['x']/1000*max(width-1, 0)
        y = marker['y']/1000*max(height-1, 0)
        rx = marker['radius_x']/1000*max(width-1, 0)
        ry = marker['radius_y']/1000*max(height-1, 0)
        extent_x = max(MIN_CONTEXT_RADIUS, RADIUS_MULTIPLIER*rx+CONTEXT_PADDING)
        extent_y = max(MIN_CONTEXT_RADIUS, RADIUS_MULTIPLIER*ry+CONTEXT_PADDING)
        requested = (math.floor(x-extent_x), math.floor(y-extent_y),
                     math.ceil(x+extent_x+1), math.ceil(y+extent_y+1))
        left, top = max(0, requested[0]), max(0, requested[1])
        right, bottom = min(width, requested[2]), min(height, requested[3])
        crop_width, crop_height = right-left, bottom-top
        scale = min(MAX_SCALE, content_side/crop_width, content_side/crop_height)
        output_size = (max(1, math.floor(crop_width*scale)),
                       max(1, math.floor(crop_height*scale)))
        crop = source.crop((left, top, right, bottom))
        if crop.size != output_size:
            crop = crop.resize(output_size, Image.Resampling.LANCZOS)
        check()
        cell_left = (index % columns)*CELL_SIDE
        cell_top = (index // columns)*CELL_SIDE
        paste_left = cell_left+(CELL_SIDE-output_size[0])//2
        paste_top = cell_top+(CELL_SIDE-output_size[1])//2
        paste_right, paste_bottom = paste_left+output_size[0], paste_top+output_size[1]
        sheet.paste(crop, (paste_left, paste_top))
        mappings.append({
            'tile_number': index+1, 'marker_id': marker['id'],
            'coordinate_space': 'original_1000',
            'original_center': [marker['x'], marker['y']],
            'original_center_pixel': [x, y],
            'original_center_convention': 'pixel_centres_width_minus_one_height_minus_one',
            'original_bbox': [left/width*1000, top/height*1000,
                              right/width*1000, bottom/height*1000],
            'original_pixel_bbox': [left, top, right, bottom],
            'original_size': [width, height],
            'sheet_coordinate_space': 'sheet_1000',
            'sheet_bbox': [paste_left/sheet.width*1000, paste_top/sheet.height*1000,
                           paste_right/sheet.width*1000, paste_bottom/sheet.height*1000],
            'sheet_pixel_bbox': [paste_left, paste_top, paste_right, paste_bottom],
            'sheet_cell_pixel_bbox': [cell_left, cell_top, cell_left+CELL_SIDE, cell_top+CELL_SIDE],
            'pixel_bbox_convention': 'half_open',
            'output_size': list(output_size),
            'scale_xy': [output_size[0]/crop_width, output_size[1]/crop_height],
            'nominal_scale': scale,
            'clipped_to_source': (left, top, right, bottom) != requested,
            'source_pixels_only': True, 'proposal_only': True,
        })
    check()
    diagnostics.update(status='partial' if omitted else 'ok',
                       sheet_size=list(sheet.size), output_pixels=sheet.width*sheet.height,
                       grid_columns=columns, grid_rows=rows)
    return sheet, mappings, diagnostics
