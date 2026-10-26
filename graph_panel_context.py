"""Panel ownership and bounded review crops in original-image coordinates.

A connected component is not a mathematical graph. Layout boxes are hints,
not permission to split disconnected graphs or discard isolated vertices.
"""
from __future__ import annotations

import math
from PIL import Image, ImageDraw


def intersection_over_union(a, b):
    overlap = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(
        0., min(a[3], b[3])-max(a[1], b[1]))
    area = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1])-overlap
    return overlap / max(area, 1e-12)


def layout_hints(regions):
    """Keep layout context, without treating table cells as graph panels."""
    hints = []
    for row in (regions or [])[:128]:
        if not isinstance(row, dict):
            continue
        box = row.get('bbox')
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                       or not math.isfinite(x) or not 0 <= x <= 1 for x in box)
                or not box[0] < box[2] or not box[1] < box[3]):
            continue
        if row.get('role') not in ('figure', 'caption', 'text', 'formula', 'table'):
            continue
        hints.append({'id': str(row.get('id', ''))[:48], 'role': row['role'],
                      'label': str(row.get('label', ''))[:48],
                      'bbox': [round(x*1000, 2) for x in box]})
    return hints


def panel_issues(graphs):
    """Report overlapping ownership; never repair it by splitting components."""
    issues = []
    for i, graph in enumerate(graphs):
        a, b, c, d = graph['bbox']
        for v in graph['vertices']:
            if not a-.015 <= v['x'] <= c+.015 or not b-.015 <= v['y'] <= d+.015:
                issues.append(f"vertex_outside_panel:{graph['id']}:{v['id']}")
        for other in graphs[:i]:
            if intersection_over_union(graph['bbox'], other['bbox']) > .80:
                issues.append(f"overlapping_panel_inventory:{other['id']}:{graph['id']}")
            shared = any(math.dist((a['x'], a['y']), (b['x'], b['y'])) < .004
                         for a in graph['vertices'] for b in other['vertices'])
            if shared:
                issues.append(f"vertex_assigned_to_multiple_panels:{other['id']}:{graph['id']}")
    return issues


def review_sheet(original, graphs, *, normalized=None, side=2200):
    """Include EVERY panel in one bounded image, plus explicit crop transforms.

    The other vision input is always the original full image. Enhancements are
    labelled as auxiliary; returned paths must use original_1000 coordinates.
    No annotation is drawn over an edge or an arrowhead in the crop itself.
    """
    if not graphs or len(graphs) > 16:
        raise ValueError('invalid_panel_review_inventory')
    side = max(512, min(2200, int(side)))
    count = len(graphs)
    cols = min(3, max(1, math.ceil(math.sqrt(count))))
    rows = math.ceil(count/cols)
    cell_w = side//cols
    # A single tall panel can use the full review height. A fixed 700px
    # ceiling erased the benefit of cropping full-resolution photographs.
    aspects = [(g['bbox'][2]-g['bbox'][0])*original.width /
               max(1., (g['bbox'][3]-g['bbox'][1])*original.height) for g in graphs]
    desired_height = max((cell_w-16)/max(.05, ratio)+42 for ratio in aspects)
    cell_h = min(side//rows, math.ceil(desired_height))
    cell_h = max(120, cell_h)
    sheet = Image.new('RGB', (cell_w*cols, cell_h*rows), 'white')
    draw = ImageDraw.Draw(sheet)
    tiles = []
    width, height = original.size
    source = normalized if normalized is not None else original
    sw, sh = source.size
    for index, graph in enumerate(graphs):
        left, top, right, bottom = graph['bbox']
        # Keep generous original context; exterior parallel arcs can lie
        # beyond the rectangle spanned by node centres.
        pad_x, pad_y = max(.015, (right-left)*.12), max(.015, (bottom-top)*.12)
        bounds = [max(0., left-pad_x), max(0., top-pad_y),
                  min(1., right+pad_x), min(1., bottom+pad_y)]
        rect = (max(0, math.floor(bounds[0]*(sw-1))),
                max(0, math.floor(bounds[1]*(sh-1))),
                min(sw, math.ceil(bounds[2]*(sw-1))+1),
                min(sh, math.ceil(bounds[3]*(sh-1))+1))
        crop = source.crop(rect).convert('RGB')
        factor=min(3., (cell_w-16)/crop.width, (cell_h-42)/crop.height)
        crop=crop.resize((max(1,round(crop.width*factor)),max(1,round(crop.height*factor))),
                         Image.Resampling.LANCZOS)
        x, y = index % cols * cell_w, index // cols * cell_h
        px, py = x+(cell_w-crop.width)//2, y+34+(cell_h-42-crop.height)//2
        sheet.paste(crop, (px, py))
        # ASCII identifiers are an internal mapping, not invented image labels.
        kind = 'auxiliary view' if normalized is not None else 'original crop'
        heading = f"Panel {index+1}: original coordinates; {kind}"
        draw.text((x+6, y+6), heading, fill='black')
        draw.rectangle((x, y, x+cell_w-1, y+cell_h-1), outline='#aaaaaa')
        tiles.append({'panel_number': index+1, 'graph_id': graph['id'],
                      'original_bbox': [round(v*1000, 3) for v in bounds],
                      'sheet_bbox': [px, py, px+crop.width, py+crop.height],
                      'original_image_size': [width, height],
                      'auxiliary': normalized is not None})
    return sheet, tiles
