"""PP-DocLayoutV3 result adapter and evidence-preserving text partition."""
from __future__ import annotations
import math

FIGURES={'image','chart','table'}
FORMULAS={'display_formula','inline_formula'}
NOISE={'number','header','footer','header_image','footer_image','footnote','vision_footnote','formula_number'}
CAPTIONS={'figure_title'}


def normalize_layout(results,width,height):
    regions=[]
    for result in results:
        data=result.json if hasattr(result,'json') else result
        if isinstance(data,str):
            import json
            data=json.loads(data)
        data=data.get('res',data)
        for box in data.get('boxes',[])[:128]:
            try:
                score=float(box['score']); xy=[float(v) for v in box['coordinate']]
                if len(xy)!=4 or not all(math.isfinite(v) for v in xy) or score<.45: continue
                x1,y1,x2,y2=xy
                if x2<=x1 or y2<=y1: continue
                bbox=[max(0.,min(1.,x1/width)),max(0.,min(1.,y1/height)),
                      max(0.,min(1.,x2/width)),max(0.,min(1.,y2/height))]
                label=str(box.get('label','unknown'))
                role='figure' if label in FIGURES else 'formula' if label in FORMULAS else (
                     'noise' if label in NOISE else 'caption' if label in CAPTIONS else 'text')
                regions.append({'id':f'r{len(regions)+1}','bbox':bbox,'label':label,'role':role,'score':score})
            except (KeyError,TypeError,ValueError,OverflowError): continue
    return regions[:128]


def partition_text(items,regions,width,height):
    """Separate graph labels without deleting them from the internal evidence.

    Only strong (> .70) overlap removes a line. Border/overlap ambiguity remains
    explicit, never silently treated as body text. Caption/page labels stay out.
    """
    body=[]; labels=[]; noise=[]; uncertain=[]
    for item in items:
        box=item.get('box') or []
        if len(box)!=4: uncertain.append(item); continue
        x1,y1,x2,y2=box; area=max(1.,(x2-x1)*(y2-y1))
        overlaps=[]
        for region in regions:
            a,b,c,d=region['bbox']; a*=width; c*=width; b*=height; d*=height
            overlap=max(0,min(x2,c)-max(x1,a))*max(0,min(y2,d)-max(y1,b))/area
            if overlap>=.5: overlaps.append((overlap,region))
        excluded=[r for ratio,r in overlaps if r['role'] in ('figure','caption','noise') and r['score']>=.70]
        if excluded:
            target=labels if any(r['role']=='figure' for r in excluded) else noise
            target.append({**item,'region_ids':[r['id'] for r in excluded]})
        elif any(r['role'] in ('figure','caption','noise') for _,r in overlaps): uncertain.append(item)
        else: body.append(item)
    return {'body':body,'graph_labels':labels,'noise':noise,'uncertain':uncertain}



def _question_reading_order(items):
    """Same line grouping as Small OCR, without loading PaddleOCR a second time."""
    rows = sorted(items, key=lambda row: (
        (row['box'][1] + row['box'][3]) / 2, row['box'][0]))
    if not rows:
        return []
    avg_height = sum(max(1., row['box'][3] - row['box'][1]) for row in rows) / len(rows)
    threshold = max(8., avg_height * .55)
    lines = []
    for item in rows:
        centre = (item['box'][1] + item['box'][3]) / 2
        for line in lines:
            if abs(centre - line['cy']) <= threshold:
                line['rows'].append(item)
                line['cy'] = sum((r['box'][1] + r['box'][3]) / 2
                                 for r in line['rows']) / len(line['rows'])
                break
        else:
            lines.append({'cy': centre, 'rows': [item]})
    ordered = []
    for line in sorted(lines, key=lambda entry: entry['cy']):
        ordered.extend(sorted(line['rows'], key=lambda row: row['box'][0]))
    return ordered


def _question_markdown(items, image_width):
    """Preserve the OCR worker's text/formula formatting without OCR imports."""
    lines = []
    for item in _question_reading_order(items):
        content = str(item.get('content') or '').strip()
        if not content:
            continue
        if item.get('type') == 'formula':
            width = item['box'][2] - item['box'][0]
            if (width >= image_width * .45 or
                    '\\begin{' in content or '\\\\' in content):
                content = '$$\n' + content + '\n$$'
            else:
                content = '$' + content + '$'
        lines.append(content)
    return '\n'.join(lines).strip()


def separate_diagram_labels(text_result, figures):
    """Use OCR pixel boxes and VERIFIED figure regions to separate text.

    The figures only supply segmentation bounds, never predicted node/edge
    text. Exclude a box only when its centre AND most of its pixels are inside
    a diagram. Question sentences near a border stay in the question.
    Missing evidence is never handled by guessing from repeated label strings.
    Returns (question_text, kept_count, removed_count, evidence_available).
    """
    original = str(text_result.get('front_text') or text_result.get('text') or '').strip()
    source = text_result.get('text_evidence') or {}
    items = source.get('emitted_body')
    if items is None:
        # Compatibility with OCR workers that predate emitted_body evidence.
        items = source.get('body')
    size = source.get('image_size')
    if (not isinstance(items, list) or not isinstance(size, list)
            or len(size) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                   for v in size)):
        return original, text_result.get('text_count') or 0, 0, False

    width, height = size
    regions = []
    for figure in figures:
        box = figure.get('bbox') if isinstance(figure, dict) else None
        if (not isinstance(box, list) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or
                       not 0 <= v <= 1 for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            continue
        regions.append((box[0]*width, box[1]*height,
                        box[2]*width, box[3]*height))
    if not regions:
        return original, len(items), 0, True

    kept, excluded = [], []
    for item in items:
        if not isinstance(item, dict):
            continue
        box = item.get('box')
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in box)
                or box[2] <= box[0] or box[3] <= box[1]):
            # No geometry means no credible reason to call it a graph label.
            kept.append(item)
            continue
        x1, y1, x2, y2 = box
        area = (x2-x1)*(y2-y1)
        cx, cy = (x1+x2)/2, (y1+y2)/2
        within_figure = False
        for a,b,c,d in regions:
            # A line straddling the edge of a figure may be a legitimate
            # question sentence; refuse to discard it without strong overlap.
            overlap = max(0., min(x2,c)-max(x1,a))*max(0., min(y2,d)-max(y1,b))
            if a <= cx <= c and b <= cy <= d and overlap / area >= .78:
                within_figure = True
                break
        (excluded if within_figure else kept).append(item)

    # If nothing belongs to a graph, keep the worker's exact original text.
    if not excluded:
        return original, len(kept), 0, True
    valid = [row for row in kept
             if isinstance(row.get('box'), (list, tuple))
             and len(row['box']) == 4
             and all(type(v) in (int, float) and math.isfinite(v) for v in row['box'])]
    return _question_markdown(valid, width), len(valid), len(excluded), True
