"""Recover bounded marker/route evidence from a single coarse visual inventory.

No graph templates, labels from references, or remote requests are used here.
"""
from __future__ import annotations
import copy
import math
from collections import defaultdict

import networkx as nx

from graph_staged import refine_node_positions


def anchor_inventory(image, graphs, *, refiner=refine_node_positions):
    """Use exact marker counts and a separated global assignment, or abstain.

    Model bounds are not measurements: excluding a real circle using those
    bounds caused the observed all-but-one partial anchoring failure.
    """
    probe = copy.deepcopy(graphs)
    for g in probe:
        g.pop('bbox', None)
    markers = []
    refiner(image, probe, partial=True, candidate_sink=markers)
    nodes = [v for g in graphs for v in g['vertices']]
    if len(markers) != len(nodes) or len(nodes) > 48:
        return refiner(image, graphs, partial=True)
    assignment = nx.Graph()
    for i, v in enumerate(nodes):
        for j, p in enumerate(markers):
            distance = math.hypot(v['x']-p['x'], v['y']-p['y'])
            if distance <= .28:
                assignment.add_edge(('v', i), ('p', j), weight=distance)
    best = nx.min_weight_matching(assignment)
    if len(best) != len(nodes):
        return refiner(image, graphs, partial=True)
    cost = sum(assignment[a][b]['weight'] for a, b in best)
    # A near-equivalent full matching is unresolved, not a license to relabel
    # two actual markers. Check the runner-up without factorial enumeration.
    for a, b in best:
        weight = assignment[a][b]['weight']
        assignment.remove_edge(a, b)
        other = nx.min_weight_matching(assignment)
        ambiguous = len(other) == len(nodes) and sum(assignment[u][v]['weight'] for u, v in other)-cost < .015
        assignment.add_edge(a, b, weight=weight)
        if ambiguous:
            return refiner(image, graphs, partial=True)
    selected = {}
    for a, b in best:
        if a[0] == 'p':
            a, b = b, a
        selected[a[1]] = markers[b[1]]
    offset = 0
    for g in graphs:
        observations = []
        old_positions = {v['id']: [v['x'], v['y']] for v in g['vertices']}
        for i, v in enumerate(g['vertices'], offset):
            p = selected[i]
            observations.append({'source': 'circular_pixel_marker_global_unique', 'vertex': v['id'],
                'node_position': [v['x'], v['y']], 'pixel_position': [p['x'], p['y']],
                'exact_inventory_count': True, 'alternative_cost_margin_min': .015})
            v['x'], v['y'] = p['x'], p['y']
        offset += len(g['vertices'])
        g['node_position_evidence'] = observations
        g['node_review']['position_alignment'] = 'exact_inventory_global_unique'
        positions = {v['id']: [v['x'], v['y']] for v in g['vertices']}
        for e in g['edges']:
            path = e['path']
            a, b = old_positions[e['from']], old_positions[e['to']]
            if math.dist(path[0], a)+math.dist(path[-1], b) > math.dist(path[0], b)+math.dist(path[-1], a):
                a, b = b, a
                u, v = positions[e['to']], positions[e['from']]
            else:
                u, v = positions[e['from']], positions[e['to']]
            lengths = [math.dist(x, y) for x, y in zip(path, path[1:])]
            total = sum(lengths)
            advance = 0.
            shifted = []
            for k, p in enumerate(path):
                t = advance/total if total else k/max(1, len(path)-1)
                shifted.append([p[c]+(1-t)*(u[c]-a[c])+t*(v[c]-b[c]) for c in (0, 1)])
                if k < len(lengths):
                    advance += lengths[k]
            # This is a proposal for pixel matching, not new ink evidence.
            if all(0 <= coordinate <= 1 for p in shifted for coordinate in p):
                e['path'] = shifted
                e['evidence'].append({'source': 'marker_frame_rebase', 'observed_path': copy.deepcopy(path)})
        width, height = image.size
        points = list(positions.values())
        nearest = [min((math.hypot((x-a)*(width-1), (y-b)*(height-1))
                        for j, (a, b) in enumerate(points) if i != j), default=80.)
                   for i, (x, y) in enumerate(points)]
        margin = max(34, min(120, sorted(nearest)[len(nearest)//2]*.62))
        a, b, c, d = g['bbox']
        g['bbox'] = [max(0., min(a, min(p[0] for p in points)-margin/(width-1))),
                     max(0., min(b, min(p[1] for p in points)-margin/(height-1))),
                     min(1., max(c, max(p[0] for p in points)+margin/(width-1))),
                     min(1., max(d, max(p[1] for p in points)+margin/(height-1)))]
    return graphs


def bind_measured_routes(graph, traces, ink):
    """Keep identities; bind only unweighted, unlabeled instances to real ink.

    Never transfer a weight between different paths of a parallel pair. The
    original model path remains in qwen_image_read evidence.
    """
    from graph_glm_adapter import _ink_support
    from graph_relation import route_overlap, _intermediate_nodes
    by_pair, measured = defaultdict(list), defaultdict(list)
    nodes = {v['id']: [v['x'], v['y']] for v in graph['vertices']}
    for e in graph['edges']:
        if _intermediate_nodes(e['path'], e, graph['vertices']):
            continue
        by_pair[tuple(sorted((e['from'], e['to'])))].append(e)
    for trace in traces:
        path = copy.deepcopy(trace['path'])
        a, b = nodes[trace['from']], nodes[trace['to']]
        if math.dist(path[0], a)+math.dist(path[-1], b) > math.dist(path[0], b)+math.dist(path[-1], a):
            a, b = b, a
        path = [a]+path+[b]
        proof = _ink_support(path, ink, trace.get('style'), source='qwen')
        if proof is not None and not _intermediate_nodes(path, trace, graph['vertices']):
            measured[tuple(sorted((trace['from'], trace['to'])))].append((trace, path, proof))
    for pair, edges in by_pair.items():
        choices = measured.get(pair, [])
        if len(edges) > len(choices) or not choices:
            continue
        if len(edges) != 1 and any(e['weight'] is not None or e['edge_label'] for e in edges):
            continue
        matches = nx.Graph()
        for i, e in enumerate(edges):
            for j, (_, path, _) in enumerate(choices):
                matches.add_edge(('e', i), ('t', j), weight=-route_overlap(e['path'], path, tolerance=.04))
        for a, b in nx.min_weight_matching(matches):
            if a[0] == 't':
                a, b = b, a
            e = edges[a[1]]
            trace, path, proof = choices[b[1]]
            e['path'] = copy.deepcopy(path)
            if e['style'] == 'unknown' and trace.get('style') in ('solid', 'dashed', 'dotted'):
                e['style'] = trace['style']
            e['evidence'].append({'source': 'measured_route_binding', 'method': trace.get('method'), **proof})
    return graph
