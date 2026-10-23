"""Explicit Qwen coordinate boundaries; no unit guessing or partial JSON salvage."""
from __future__ import annotations
import copy
import math

from graph_schema import canonical_graph

ORIGINAL_SPACE = 'original_1000'
CROP_SPACE = 'crop_1000'


def scalar(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('invalid_qwen_coordinate')
    if not 0 <= value <= 1000 or not math.isfinite(value):
        raise ValueError('invalid_qwen_coordinate')
    return value / 1000


def point(value, bounds=(0., 0., 1., 1.)):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('invalid_qwen_point')
    x, y = map(scalar, value)
    a, b, c, d = bounds
    return [a + x * (c-a), b + y * (d-b)]


def box(value, bounds=(0., 0., 1., 1.)):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('invalid_qwen_box')
    a, b = point(value[:2], bounds)
    c, d = point(value[2:], bounds)
    if not a < c or not b < d:
        raise ValueError('invalid_qwen_box')
    return [a, b, c, d]


def route(value, bounds=(0., 0., 1., 1.)):
    if not isinstance(value, list) or not 2 <= len(value) <= 8:
        raise ValueError('invalid_qwen_path')
    return [point(p, bounds) for p in value]


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 48:
        raise ValueError('invalid_qwen_id')
    return value


def attribute(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('invalid_qwen_attribute')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('invalid_qwen_attribute')
    if isinstance(value, str) and len(value) > 80:
        raise ValueError('invalid_qwen_attribute')
    return value


def decode_inventory(response):
    if not isinstance(response, dict) or response.get('coordinate_space') != ORIGINAL_SPACE:
        raise ValueError('qwen_inventory_coordinate_space')
    values = response.get('graphs')
    if not isinstance(values, list) or not 1 <= len(values) <= 8:
        raise ValueError('invalid_qwen_inventory')
    graphs = []
    graph_ids = set()
    node_count = 0
    for raw in values:
        if not isinstance(raw, dict):
            raise ValueError('invalid_qwen_graph')
        gid = identifier(raw.get('id'))
        if gid in graph_ids:
            raise ValueError('duplicate_qwen_graph_id')
        graph_ids.add(gid)
        vertices, edges = raw.get('vertices'), raw.get('edges')
        if not isinstance(vertices, list) or not 1 <= len(vertices) <= 48:
            raise ValueError('invalid_qwen_vertices')
        if not isinstance(edges, list) or len(edges) > 96:
            raise ValueError('invalid_qwen_edges')
        node_count += len(vertices)
        if node_count > 48:
            raise ValueError('qwen_vertex_budget')
        g = {'id': gid, 'name': raw.get('name', gid), 'bbox': box(raw.get('bbox')),
             'node_complete': raw.get('node_complete') is True, 'vertices': [], 'edges': []}
        for key in ('directed', 'weighted', 'multigraph'):
            value = raw.get(key)
            if type(value) is not bool and value != 'unknown':
                raise ValueError('invalid_qwen_graph_type')
            g[key] = value
        ids = set()
        for v in vertices:
            if not isinstance(v, dict):
                raise ValueError('invalid_qwen_vertex')
            vid = identifier(v.get('id'))
            if vid in ids:
                raise ValueError('duplicate_qwen_vertex_id')
            ids.add(vid)
            x, y = point([v.get('x'), v.get('y')])
            g['vertices'].append({'id': vid, 'label': attribute(v.get('label')), 'x': x, 'y': y,
                                  'isolated_confirmed': v.get('isolated_confirmed') is True})
        g['node_review'] = {'source': 'qwen_image_read',
                            'coordinate_space': 'original_image_normalized',
                            'observed_vertices': copy.deepcopy(g['vertices'])}
        edge_ids = set()
        for e in edges:
            if not isinstance(e, dict):
                raise ValueError('invalid_qwen_edge')
            eid = identifier(e.get('id'))
            if eid in edge_ids:
                raise ValueError('duplicate_qwen_edge_id')
            edge_ids.add(eid)
            a, b = identifier(e.get('from')), identifier(e.get('to'))
            if a not in ids or b not in ids:
                raise ValueError('invalid_qwen_endpoint')
            if e.get('direction') not in ('forward', 'undirected', 'unknown'):
                raise ValueError('invalid_qwen_direction')
            path = route(e.get('path'))
            weight, label = attribute(e.get('weight')), attribute(e.get('edge_label'))
            observed = {'source': 'qwen_image_read', 'observation_id': [gid, eid],
                        'observed_from': a, 'observed_to': b,
                        'observed_direction': e['direction'], 'observed_path': copy.deepcopy(path),
                        'observed_weight': weight, 'observed_edge_label': label}
            evidence = [observed]
            if e.get('weight_bbox') is not None:
                evidence.append({'source': 'qwen_attribute_region', 'field': 'weight',
                                 'bbox': box(e['weight_bbox'])})
            g['edges'].append({key: copy.deepcopy(e.get(key)) for key in
                               ('id', 'from', 'to', 'direction', 'style')})
            g['edges'][-1].update(path=path,
                weight=weight, edge_label=label,
                status='pending', evidence=evidence)
        graphs.append(canonical_graph(g))
    return graphs


def crop_bounds(rect, image_size):
    """PIL exclusive right/bottom -> inclusive pixel-center coordinates."""
    width, height = image_size
    if width < 2 or height < 2:
        raise ValueError('qwen_image_too_small')
    left, top, right, bottom = rect
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        raise ValueError('invalid_qwen_crop')
    if right-left < 2 or bottom-top < 2:
        raise ValueError('invalid_qwen_crop')
    return [left/(width-1), top/(height-1), (right-1)/(width-1), (bottom-1)/(height-1)]


def contains(bounds, p):
    a, b, c, d = bounds
    return a <= p[0] <= c and b <= p[1] <= d


def encode_point(p, bounds):
    if not contains(bounds, p):
        raise ValueError('point_outside_qwen_crop')
    a, b, c, d = bounds
    return [round((p[0]-a)/(c-a)*1000, 4), round((p[1]-b)/(d-b)*1000, 4)]
