"""PP-DocLayoutV3 result adapter and evidence-preserving text partition."""
from __future__ import annotations
import math
import re

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



_CAPTION_HEADING = re.compile(
    r"^(?:图\s*[\w①-⑳（）().\-₀-₉]+(?:\s*[-—:：]\s*[^\n，。！？；;]{1,16})?"
    r"|(?:fig(?:ure)?)[.\s\-]*[0-9a-zA-Z]+"
    r"|[（(][A-Za-z0-9]{1,3}[)）]"
    r"|[A-Z][A-Za-z0-9₀-₉'_]{0,9}"
    r"|[^\n，。！？；;]{1,12}(?:示意图|结构图|关系图|图))$",
    re.IGNORECASE,
)
_CAPTION_QUESTION = re.compile(
    r"(?:^|[（(]\s*[1-9]\d*\s*[）)])\s*(?:已知|求|试|设|证明|判断|"
    r"问|计算|讨论|下列|根据|若|请|如图|画出)|"
    r"^(?:已知|求|试|设|证明|判断|问|计算|讨论|下列|根据|若|请|如图|画出)"
)


def _caption_kind(value):
    """Identify a short printed graph caption, not a question sentence.

    Plain custom names are allowed only when extremely close to a figure and
    aligned with its centre; explicit names like G₁ / (a) / 图2 tolerate a
    slightly larger caption gap. Never infer names from isolated text alone.
    """
    name = str(value or "").strip()
    if not name or len(name) > 30 or "\n" in name or _CAPTION_QUESTION.search(name):
        return ""
    if re.search(r"[，。！？?；;]|\b(?:which|find|prove|show|given)\b", name, re.I):
        return ""
    if _CAPTION_HEADING.fullmatch(name):
        return "explicit"
    # Original diagrams may use arbitrary short names rather than "图 1".
    # Still reject full Chinese sentences and formula lines.
    if len(name) <= 12 and not re.search(r"[=+*/∑∫{}]|[：:,]", name):
        return "nearby"
    return ""


def include_figure_captions(text_result, figures):
    """Expand every recognized panel to include its printed caption/alias.

    Coordinates come from the *same original OCR pixel frame*. Assign an
    external title to at most one panel (nearest aligned one) so side-by-side
    figures cannot steal each other's labels. Full problem sentences and
    figure-adjacent instructions are never captured. No Qwen call or graph
    pre-drawing is introduced.

    Returns (new_figures, attached_item_count); never mutates inputs.
    """
    updated = [dict(row) if isinstance(row, dict) else row for row in figures]
    source = text_result.get("text_evidence") or {}
    items = source.get("emitted_body")
    if items is None:
        items = source.get("body")
    size = source.get("image_size")
    if (not isinstance(items, list) or
            not isinstance(size, list) or len(size) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                for v in size)):
        return updated, 0
    width, height = size
    boxes = []
    for figure in updated:
        bbox = figure.get("bbox") if isinstance(figure, dict) else None
        if (not isinstance(bbox, list) or len(bbox) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) or
                    not 0 <= v <= 1 for v in bbox) or
                bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
            boxes.append(None)
        else:
            boxes.append([bbox[0]*width, bbox[1]*height,
                          bbox[2]*width, bbox[3]*height])
    assignments = [[] for _ in updated]
    for item in items:
        if not isinstance(item, dict) or item.get("type") == "formula":
            continue
        caption = str(item.get("content") or "").strip()
        kind = _caption_kind(caption)
        if not kind:
            continue
        box = item.get("box")
        if (not isinstance(box, (list, tuple)) or len(box) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in box) or box[2] <= box[0] or box[3] <= box[1]):
            continue
        x1,y1,x2,y2 = box
        mx, my = (x1+x2)/2, (y1+y2)/2
        candidates = []
        for i, region in enumerate(boxes):
            if not region:
                continue
            a,b,c,d = region
            figure_width, figure_height = c-a, d-b
            # Must be horizontally aligned with its own figure. In a row of
            # diagrams the centre distance determines the caption owner.
            overlap = max(0., min(x2,c)-max(x1,a))
            aligned = overlap / max(1., x2-x1)
            delta_x = abs(mx - (a+c)/2)
            if aligned < .7 or delta_x > figure_width*.55:
                continue
            below = y1 >= d - 1
            above = y2 <= b + 1
            # Caption printed inside the bottom 10% of a padded figure box.
            bottom_band = (b <= my <= d and
                           my >= d - min(figure_height*.13, max(15., height*.035)))
            if below:
                gap = max(0., y1-d)
            elif above and kind == "explicit":
                gap = max(0., b-y2)
            elif bottom_band and kind == "explicit":
                gap = 0.
            else:
                continue
            # Plain names must be almost adjacent; titled figures receive a
            # little more room for captions beneath the figure.
            limit = (max(13., height*.055) if kind == "explicit"
                     else max(8., height*.025))
            if gap > limit:
                continue
            # Do not misattribute names printed INSIDE another panel.
            in_other = False
            for j, other in enumerate(boxes):
                if j == i or not other:
                    continue
                oa,ob,oc,od = other
                if oa <= mx <= oc and ob <= my <= od:
                    in_other = True
                    break
            if in_other:
                continue
            # Below is the standard convention; above is allowed only for a
            # clear "图/figure" name or small panel identifier.
            score = (gap / max(1., height) * 8
                     + delta_x / max(1., figure_width)
                     + (0.13 if above else 0)
                     + (0.16 if kind == "nearby" else 0))
            candidates.append((score, i))
        if candidates:
            _, owner = min(candidates)
            assignments[owner].append((box, caption))
    count = 0
    for i, rows in enumerate(assignments):
        if not rows or not boxes[i]:
            continue
        a,b,c,d = boxes[i]
        # At most two nearby lines; a detached paragraph must not grow a
        # rectangle across an entire next exercise.
        rows.sort(key=lambda row: (abs(row[0][1]-d), len(row[1])))
        chosen = rows[:2]
        # An adjacent printed caption is part of the diagram's actual crop
        # AND its focus rectangle; preserve the original image coordinates.
        for rect, _ in chosen:
            x1,y1,x2,y2 = rect
            a = min(a,x1-2); b = min(b,y1-2)
            c = max(c,x2+2); d = max(d,y2+2)
        updated[i]["bbox"] = [round(max(0.,a/width),6),
                              round(max(0.,b/height),6),
                              round(min(1.,c/width),6),
                              round(min(1.,d/height),6)]
        current = str(updated[i].get("name") or "").strip()
        if not current or re.fullmatch(r"图\s*\d+", current):
            # OCR's printed name is preferred to a generic model placeholder.
            updated[i]["name"] = chosen[0][1][:80]
        count += len(chosen)
    return updated, count


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
