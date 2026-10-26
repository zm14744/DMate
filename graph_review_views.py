"""Compact original-pixel graph and question crops for the second vision pass.

The full original is still image one. This auxiliary sheet never paints OCR
text or an expected answer onto the image. Its coordinate maps always point
back to original pixels; resizing is solely for readable small print.
"""
from __future__ import annotations

import math
from statistics import median

from PIL import Image, ImageDraw

MAX_TEXT_BLOCKS = 32
MAX_REVIEW_PIXELS = 2_400_000


def _bounds(value, scale=1.):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        return None
    a, b, c, d = (v/scale for v in value)
    return (a, b, c, d) if 0 <= a < c <= 1 and 0 <= b < d <= 1 else None


def _overlap(a, b):
    return max(0., min(a[2], b[2])-max(a[0], b[0])) * max(
        0., min(a[3], b[3])-max(a[1], b[1]))


def _text_blocks(hints, graphs, size):
    width, height = size
    panels = [box for g in graphs if (box := _bounds(g.get('bbox'))) is not None]
    selected, omitted = [], []
    for hint in (hints or {}).get('items', [])[:128]:
        box = _bounds(hint.get('bbox'), 1000.)
        if box is None:
            continue
        area = (box[2]-box[0])*(box[3]-box[1])
        in_panel = any(_overlap(box, panel)/area >= .5 for panel in panels)
        # Explicit body boxes remain visible even when a proposed graph frame
        # is too large. Other graph labels already occur in the graph crops.
        if hint.get('paddle_role') != 'body' and in_panel:
            continue
        rect = [box[0]*width, box[1]*height, box[2]*width, box[3]*height]
        selected.append({'bbox': rect, 'hint_ids': [hint['id']],
                         'line_heights': [rect[3]-rect[1]]})
    selected.sort(key=lambda item: (item['bbox'][1], item['bbox'][0]))
    # Combine overlapping OCR alternatives and adjacent lines from the same
    # physical text block. This preserves original order and small subscripts.
    changed = True
    while changed:
        changed = False
        for i, left in enumerate(selected):
            a = left['bbox']
            for j in range(i+1, len(selected)):
                right = selected[j]
                b = right['bbox']
                line = median(left['line_heights']+right['line_heights'])
                x_overlap = max(0., min(a[2], b[2])-max(a[0], b[0]))
                y_overlap = max(0., min(a[3], b[3])-max(a[1], b[1]))
                x_gap = max(0., max(a[0], b[0])-min(a[2], b[2]))
                y_gap = max(0., max(a[1], b[1])-min(a[3], b[3]))
                same_line = y_overlap >= .5*min(a[3]-a[1], b[3]-b[1]) and x_gap <= line
                consecutive = x_overlap >= .45*min(a[2]-a[0], b[2]-b[0]) and y_gap <= .8*line
                if same_line or consecutive:
                    left['bbox'] = [min(a[0], b[0]), min(a[1], b[1]),
                                    max(a[2], b[2]), max(a[3], b[3])]
                    left['hint_ids'].extend(right['hint_ids'])
                    left['line_heights'].extend(right['line_heights'])
                    selected.pop(j)
                    changed = True
                    break
            if changed:
                break
    selected.sort(key=lambda item: (item['bbox'][1], item['bbox'][0]))
    for block in selected[MAX_TEXT_BLOCKS:]:
        omitted.extend(block['hint_ids'])
    return selected[:MAX_TEXT_BLOCKS], omitted


def _rect(bounds, size, padding):
    width, height = size
    left, top, right, bottom = bounds
    px, py = padding
    return (max(0, math.floor(left-px)), max(0, math.floor(top-py)),
            min(width, math.ceil(right+px)), min(height, math.ceil(bottom+py)))


def _layout(items, width):
    x = y = row_height = 0
    positions = []
    for item in items:
        desired_w, desired_h = item['desired_size']
        factor = min(1., (width-16)/desired_w)
        w, h = max(1, round(desired_w*factor)), max(1, round(desired_h*factor))
        outer_w, outer_h = w+16, h+30
        if x and x+outer_w > width:
            y += row_height
            x, row_height = 0, 0
        positions.append((x, y, w, h))
        x += outer_w
        row_height = max(row_height, outer_h)
    used_width = max(x+w+16 for x, _, w, _ in positions)
    return positions, used_width, y+row_height


def build_review_sheet(original, graphs, *, hints=None, side=2200):
    """Return sheet, graph maps, text maps and explicit capacity observations."""
    if not graphs or len(graphs) > 16:
        raise ValueError('invalid_panel_review_inventory')
    side = max(512, min(2200, int(side)))
    width, height = original.size
    items = []
    for index, graph in enumerate(graphs):
        bounds = _bounds(graph.get('bbox'))
        if bounds is None:
            raise ValueError('invalid_panel_review_bounds')
        a, b, c, d = bounds
        rect = _rect((a*width, b*height, c*width, d*height), original.size,
                     (max(.015, (c-a)*.12)*width, max(.015, (d-b)*.12)*height))
        w, h = rect[2]-rect[0], rect[3]-rect[1]
        factor = min(3., 1400/max(w, h))
        items.append({'kind': 'graph', 'graph_id': graph['id'], 'panel_number': index+1,
                      'rect': rect, 'desired_size': (round(w*factor), round(h*factor)),
                      'heading': f'Panel {index+1}: original crop'})
    blocks, omitted = _text_blocks(hints, graphs, original.size)
    for index, block in enumerate(blocks):
        line_height = median(block['line_heights'])
        pad = max(2., line_height*.3)
        rect = _rect(block['bbox'], original.size, (pad, pad))
        w, h = rect[2]-rect[0], rect[3]-rect[1]
        factor = min(4., max(1., 64/max(line_height, 1.)), 1800/max(w, h))
        items.append({'kind': 'text', 'hint_ids': block['hint_ids'], 'rect': rect,
                      'desired_size': (round(w*factor), round(h*factor)),
                      'heading': f'Text crop {index+1}: original pixels; '+','.join(block['hint_ids'][:12])})
    plans = []
    for trial_width in sorted({min(side, value) for value in (512, 768, 1024, 1280, 1600, 1920, 2200)}):
        positions, w, h = _layout(items, trial_width)
        scale = min(1., side/w, side/h, math.sqrt(MAX_REVIEW_PIXELS/(w*h)))
        # A narrow sheet can shrink a wide text line before global fitting;
        # account for that loss instead of rewarding nominally small layouts.
        detail = min(scale*position[2]/max(1, item['desired_size'][0])
                     for item, position in zip(items, positions))
        plans.append((detail, -w*h, scale, positions, w, h))
    _, _, scale, positions, w, h = max(plans, key=lambda plan: plan[:2])
    sheet = Image.new('RGB', (max(1, math.floor(w*scale)), max(1, math.floor(h*scale))), 'white')
    draw = ImageDraw.Draw(sheet)
    panel_tiles, text_tiles = [], []
    for item, (x, y, iw, ih) in zip(items, positions):
        # Resample directly from the original exactly once, after layout.
        px, py = round((x+8)*scale), round((y+24)*scale)
        cw = max(1, min(sheet.width-px, round(iw*scale)))
        ch = max(1, min(sheet.height-py, round(ih*scale)))
        crop = original.crop(item['rect']).convert('RGB').resize((cw, ch), Image.Resampling.LANCZOS)
        sheet.paste(crop, (px, py))
        draw.text((round((x+5)*scale), round((y+4)*scale)), item['heading'], fill='black')
        a, b, c, d = item['rect']
        tile = {'original_bbox': [round(a/width*1000, 3), round(b/height*1000, 3),
                                  round(c/width*1000, 3), round(d/height*1000, 3)],
                'original_pixel_bbox': list(item['rect']),
                'sheet_bbox': [px, py, px+cw, py+ch],
                'original_image_size': [width, height], 'auxiliary': False}
        if item['kind'] == 'graph':
            tile.update(graph_id=item['graph_id'], panel_number=item['panel_number'])
            panel_tiles.append(tile)
        else:
            tile.update(hint_ids=item['hint_ids'], text_crop_number=len(text_tiles)+1)
            text_tiles.append(tile)
    notes = ['text_review_crop_capacity_limited:'+','.join(omitted)] if omitted else []
    return sheet, panel_tiles, text_tiles, notes
