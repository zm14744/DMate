"""Source observations and stable vertex references, separate from topology.

This module never adds vertices/edges or infers a mathematical graph family.
Display numbers are local to one graph and never become printed labels.
"""
from __future__ import annotations

import math

DESCRIPTION_LIMIT = 800
POSITION_LIMIT = 160
_CIRCLES = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'


def _text(value, limit):
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= limit else ''


def _number(index):
    return _CIRCLES[index - 1] if index <= len(_CIRCLES) else '未命名' + str(index)


def prepare_graph_presentation(graph):
    """Fill missing references once, preserving existing IDs and valid numbers."""
    vertices = graph.get('vertices', [])
    for vertex in vertices:
        if vertex.get('label') is not None and str(vertex['label']).strip():
            vertex['label'] = str(vertex['label'])
    used = {str(v['label']) for v in vertices if v.get('label') is not None and str(v['label']).strip()}
    # Reserve all existing numbers before assigning any missing ones.
    existing = set()
    for vertex in vertices:
        if vertex.get('label') is not None and str(vertex['label']).strip():
            continue
        display = _text(vertex.get('display_label'), 16)
        if display and display not in used and display not in existing:
            vertex['display_label'] = display
            existing.add(display)
        else:
            vertex.pop('display_label', None)
    used.update(existing)
    next_number = graph.get('anon_next', 1)
    if type(next_number) is not int or not 1 <= next_number <= 10000:
        next_number = 1
    for name in used:
        if len(name) == 1 and name in _CIRCLES:
            next_number = max(next_number, _CIRCLES.index(name) + 2)
        elif name.startswith('未命名') and name[3:].isdigit():
            next_number = max(next_number, int(name[3:]) + 1)
    for vertex in sorted(vertices, key=lambda v: str(v['id'])):
        if vertex.get('label') is None or not str(vertex['label']).strip():
            vertex['label'] = None
            if not vertex.get('display_label'):
                while _number(next_number) in used:
                    next_number += 1
                vertex['display_label'] = _number(next_number)
                used.add(vertex['display_label'])
                next_number += 1
    graph['anon_next'] = min(10000, next_number)
    located = [v for v in vertices if all(type(v.get(k)) in (int, float) and
               math.isfinite(v[k]) and 0 <= v[k] <= 1 for k in ('x', 'y'))]
    if located:
        xs, ys = [v['x'] for v in located], [v['y'] for v in located]
        for vertex in located:
            if _text(vertex.get('position_description'), POSITION_LIMIT):
                continue
            x = (vertex['x'] - min(xs)) / (max(xs) - min(xs)) if max(xs) > min(xs) else .5
            y = (vertex['y'] - min(ys)) / (max(ys) - min(ys)) if max(ys) > min(ys) else .5
            horizontal = '左' if x < 1/3 else '右' if x > 2/3 else ''
            vertical = '上' if y < 1/3 else '下' if y > 2/3 else ''
            vertex['position_description'] = '图内' + (horizontal + vertical + '方' if horizontal or vertical else '中部')
    description = _text(graph.get('visual_description'), DESCRIPTION_LIMIT)
    if description:
        graph['visual_description'] = description
    elif located:
        areas = list(dict.fromkeys(v['position_description'] for v in located))
        graph['visual_description'] = '按已记录位置，顶点分布于' + '、'.join(areas) + '；具体轮廓、曲线和交叉形态未提供。'
    return graph


def reference_notes(graph):
    """Text uses the same references as the document and read-only UI."""
    lines = []
    if graph.get('visual_description'):
        lines.append('原图外观（识别描述）：' + graph['visual_description'])
    anonymous = [v for v in graph['vertices'] if not v.get('label') and v.get('display_label')]
    if anonymous:
        lines.append('无名顶点以临时编号引用（仅在本图内有效，不是原图标签）：' +
                     '、'.join(v['display_label'] for v in anonymous) + '。')
    positions = [str(v.get('label') or v.get('display_label') or v['id']) + '：' + v['position_description']
                 for v in graph['vertices'] if v.get('position_description')]
    if positions:
        lines.append('顶点位置：' + '；'.join(positions) + '。')
    return '\n'.join(lines)
