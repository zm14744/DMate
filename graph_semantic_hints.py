"""Role-scoped reading suggestions, never OCR-derived graph assertions.

Paddle evidence remains unchanged in the caller's diagnostic record. This module
only projects a small, non-authoritative model input. A review of an existing
inventory must not reinterpret OCR's missing/misread labels as missing vertices.
Raw concatenated OCR is deliberately not a fallback for body text: its upstream
``body`` partition can itself contain only misread node labels.
"""
from __future__ import annotations

from collections import Counter
import copy
import math
import re
import unicodedata


VERSION = '2026-10-27-role-scoped-ocr-hints-v1'
_RELATION_CLAUSE = re.compile(r'连接|相连|邻接|邻居|连向|指向|\b(?:connect(?:ed|s|ing)?|adjacent|neighbou?rs?)\b', re.I)
_POINTS = frozenset({'.', '·', '•', '●', '∙', '。', '○', '◯', '◦'})
_ROUND = _POINTS | {'O', 'o', '0', '〇'}
_PROSE = re.compile(
    r'求|证明|判断|判定|计算|写出|画出|给出|下[图列述]|是否|已知|说明|找出|'
    r'(?:设|令|给定)\s*(?=[A-Za-z(（\u3400-\u9fff])|'
    r'图例|表示|代表|权值|权重|生成树|最短路|最大流|哈密顿|欧拉|同构|连通度|度数|'
    r'(?:红|蓝|绿|黑|黄|紫|灰|橙)(?:色)?(?:的)?(?:边|线|弧)|(?:虚|实|点划)线|'
    r'[?？]|\b(?:given|let|suppose|assume|find|prove|show|determine|calculate|which|whether|legend|'
    r'dashed|dotted|solid|represents?|denotes?)\b', re.IGNORECASE)
_WORDS = re.compile(r'[A-Za-z]{2,}')
_CJK = re.compile(r'[\u3400-\u9fff]')
_ATOMIC = re.compile(r'^[\w√±+−./\\{}()\[\]_^′\u2032\u2080-\u209f-]{1,16}$')
_NOTICE = ('本地OCR仅供定位和对照原图，不是已确认题干或标签；漏读、大小写、'
           '数字和圆点误读都可能发生。候选缺失不代表顶点或边缺失，'
           '不能据此推翻原图、固定节点清单或确认未读内容。')


def spatial_position_hint(value):
    """A location hint must not smuggle unperformed edge readings downstream."""
    if not isinstance(value, str):
        return value
    return _RELATION_CLAUSE.split(value, maxsplit=1)[0].rstrip(' ,，;；:：、')


def project_connection_hints(graphs):
    """Keep real tracing proposals without presenting rejected arrow guesses.

    The raw measurement remains in diagnostic geometry. A tentative arrow wing
    detector is not a direction proposal until that detector's own test passed.
    Accepted measurements remain candidates for visual checking, never proof.
    """
    result = copy.deepcopy(graphs)
    rows = result if isinstance(result, list) else [result]
    for graph in rows:
        if not isinstance(graph, dict):
            continue
        for candidate in graph.get('candidates', []):
            if not isinstance(candidate, dict):
                continue
            arrow = candidate.get('arrow_measurement')
            if isinstance(arrow, dict) and arrow.get('confirmed') is not True:
                candidate.pop('arrow_measurement', None)
    return result


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _box(value):
    if (isinstance(value, (list, tuple)) and len(value) == 4
            and all(_number(x) and 0 <= x <= 1000 for x in value)
            and value[0] < value[2] and value[1] < value[3]):
        return list(map(float, value))
    return None


def _intersection(a, b):
    return max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))


def _area(box):
    return (box[2]-box[0])*(box[3]-box[1])


def _same_detection(a, b):
    # Equal strings at different vertices/panels remain distinct. Case and
    # symbol substitutions are not normalized into a falsely agreed reading.
    if a['text'] != b['text'] or not a['bbox'] or not b['bbox']:
        return False
    aa, ba = _area(a['bbox']), _area(b['bbox'])
    return (min(aa, ba) >= .5*max(aa, ba)
            and _intersection(a['bbox'], b['bbox']) >= .8*min(aa, ba))


def _prose(text):
    compact = re.sub(r'\s+', '', text)
    if _PROSE.search(text):
        return True
    # Isolated a/V4/e5/√3/O items are not a question just because Paddle put
    # them in its body partition. Full sentences and readable prose remain.
    if len(_CJK.findall(text)) >= 4:
        return True
    words = _WORDS.findall(text)
    return len(words) >= 3 and not _ATOMIC.fullmatch(compact)


def _marker_glyph(row, markers):
    token, box = row['text'], row['bbox']
    if token in _POINTS:
        return True
    if token not in _ROUND or box is None:
        return False
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        point = marker.get('position')
        confidence = marker.get('confidence')
        if (not isinstance(point, (list, tuple)) or len(point) != 2
                or not all(_number(x) for x in point)
                or not _number(confidence) or confidence < .7):
            continue
        rx, ry = marker.get('radius_x'), marker.get('radius_y')
        if not all(_number(x) and x > 0 for x in (rx, ry)):
            continue
        # Require a glyph covering the marker's outline, not merely its center.
        # A real O/0 printed INSIDE a large hollow node has a much smaller box
        # and must remain available as text. When size evidence is inconclusive,
        # keep the candidate; geometry cannot certify that it is a false label.
        if (box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]
                and 1.5*rx <= box[2]-box[0] <= 4*rx
                and 1.5*ry <= box[3]-box[1] <= 4*ry):
            return True
    return False


def _near_body(row, anchor, regions):
    a, b = row['bbox'], anchor['bbox']
    if a is None or b is None:
        return False
    ah, bh = a[3]-a[1], b[3]-b[1]
    vertical_overlap = max(0., min(a[3], b[3])-max(a[1], b[1]))
    horizontal_gap = max(0., a[0]-b[2], b[0]-a[2])
    if vertical_overlap >= .6*min(ah, bh) and horizontal_gap <= 2*max(ah, bh):
        return True
    for region in regions:
        # A shared, local body window can retain a separate formula line.
        # A whole-page layout proposal cannot turn all graph labels into body.
        if (_area(region) <= 200_000
                and _intersection(a, region) >= .8*_area(a)
                and _intersection(b, region) >= .8*_area(b)
                and abs((a[1]+a[3]-b[1]-b[3])/2) <= 3*max(ah, bh)):
            return True
    return False


def _mode(role):
    if not isinstance(role, str) or not role:
        raise ValueError('hint_role_required')
    if role in ('inventory', 'semantic_extract'):
        return 'inventory'
    if role in ('sources', 'source', 'edge_reading') or role.startswith('semantic_edges'):
        return 'source'
    if role == 'body' or role.startswith('semantic_body'):
        return 'body'
    return 'topology_review'


def project_ocr_hints(text_result, *, role, graph=None, body_regions=(),
                      marker_candidates=(), max_items=96, max_characters=8000):
    """Return ``candidates``, safe ``body_text_hint``, ``policy`` and ``audit``.

    Pass candidates/policy to the model; keep audit in diagnostics. Topology and
    body reviewers receive only located prose and adjacent body expressions.
    Inventory/source readers may also receive graph-label candidates, with no
    implied completeness, voting or authority. No input object is modified.
    """
    if (type(max_items) is not int or not 0 <= max_items <= 256
            or type(max_characters) is not int or not 0 <= max_characters <= 24_000):
        raise ValueError('invalid_hint_capacity')
    mode = _mode(role)
    source = text_result.get('text_hints', []) if isinstance(text_result, dict) else []
    source = source if isinstance(source, list) else []
    markers = marker_candidates if isinstance(marker_candidates, (list, tuple)) else ()
    graph_box = _box(graph.get('bbox')) if isinstance(graph, dict) else None
    regions = [_box(row.get('bbox')) for row in body_regions
               if isinstance(row, dict)] if isinstance(body_regions, (list, tuple)) else []
    regions = [box for box in regions if box is not None]
    omitted, rows, duplicates = Counter(), [], []
    for index, original in enumerate(source):
        if not isinstance(original, dict) or not isinstance(original.get('text'), str):
            omitted['invalid_candidate'] += 1
            continue
        text = unicodedata.normalize('NFC', original['text']).strip()
        if not text:
            omitted['empty_candidate'] += 1
            continue
        box = (_box(original.get('bbox'))
               if original.get('coordinate_space') == 'original_1000' else None)
        if graph_box is not None and box is not None and not _intersection(graph_box, box):
            omitted['outside_graph_window'] += 1
            continue
        hint_id = original.get('id')
        row = {'id': hint_id if isinstance(hint_id, str) else f'ocr_hint_{index+1}',
               'text': text, 'bbox': box, 'coordinate_space': 'original_1000',
               'role_hint': original.get('role_hint'), 'status': 'candidate',
               'source': 'paddleocr_small_text', 'authoritative': False,
               'must_verify_from_original': True}
        if _marker_glyph(row, markers):
            omitted['point_or_round_marker_candidate'] += 1
            continue
        same = next((old for old in rows if _same_detection(row, old)), None)
        if same is not None:
            omitted['overlapping_duplicate'] += 1
            duplicates.append({'kept_id': same['id'], 'omitted_id': row['id']})
            continue
        rows.append(row)

    # Explicit graph labels never become body hints. A misplaced body category
    # is insufficient too: it needs actual prose or located prose context.
    anchors = [row for row in rows if row['bbox'] is not None
               and row['role_hint'] != 'graph_label' and _prose(row['text'])]
    body_ids = {row['id'] for row in anchors}
    body_ids.update(row['id'] for row in rows
                    if row['bbox'] is not None and row['role_hint'] != 'graph_label'
                    and any(_near_body(row, anchor, regions) for anchor in anchors))
    candidates, chars = [], 0
    for row in rows:
        body = row['id'] in body_ids
        if mode in ('topology_review', 'body') and not body:
            omitted['not_located_body_or_legend'] += 1
            continue
        if len(candidates) >= max_items or chars+len(row['text']) > max_characters:
            omitted['capacity'] += 1
            continue
        # Do not expose Paddle's mistaken ``body`` category next to a single
        # node glyph again. Its original category remains in raw diagnostics.
        row['role_hint'] = 'body_or_legend_candidate' if body else 'graph_text_candidate'
        row['usage'] = 'body_or_legend_reading_candidate' if body else 'graph_text_reading_candidate'
        candidates.append(row)
        chars += len(row['text'])
    body_parts = [row['text'] for row in candidates if row['id'] in body_ids]
    return {'candidates': candidates,
            'body_text_hint': (_NOTICE+'\n'+'\n'.join(body_parts)) if body_parts else '',
            'policy': {'version': VERSION, 'mode': mode, 'authoritative': False,
                       'notice': _NOTICE, 'original_pixels_are_authority': True,
                       'not_a_vertex_or_edge_inventory': True,
                       'absence_is_not_missing_content': True,
                       'cannot_override_visual_labels': True,
                       'graph_label_ocr_excluded': mode in ('topology_review', 'body')},
            'audit': {'version': VERSION, 'role': role, 'mode': mode,
                      'input_items': len(source), 'supplied_items': len(candidates),
                      'supplied_characters': chars, 'omitted_counts': dict(omitted),
                      'overlapping_duplicates': duplicates,
                      'raw_ocr_unchanged': True}}
