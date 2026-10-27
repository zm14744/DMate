"""Rebind a scoped edge rereading to unchanged, explicitly labelled vertices.

This is reference repair, not image recognition. Only a complete bijection of
unique, exact printed labels can explain a reader's renamed internal IDs. No
edge, coordinate, path, degree, expected answer or graph isomorphism is used to
choose that bijection. The caller still decides whether the edge field may be
changed and performs the ordinary semantic validation afterwards.
"""
from __future__ import annotations

import copy

from graph_semantic_schema import MAX_EDGES, MAX_VERTICES


def _exact_id(value):
    # The adapter trims IDs. Do not let that later transformation collapse two
    # otherwise distinct raw references after a successful mapping here.
    return (isinstance(value, str) and bool(value)
            and value == value.strip() and len(value) <= 64)


def _vertex_inventory(graph):
    vertices = graph.get('vertices')
    if not isinstance(vertices, list) or not vertices:
        return None, 'vertex_inventory_missing'
    if len(vertices) > MAX_VERTICES:
        return None, 'vertex_capacity_exceeded'
    by_id, by_label = {}, {}
    for vertex in vertices:
        if not isinstance(vertex, dict) or not _exact_id(vertex.get('id')):
            return None, 'invalid_vertex_id'
        identifier, label = vertex['id'], vertex.get('label')
        if identifier in by_id:
            return None, 'duplicate_vertex_id'
        # No case folding, whitespace removal, Unicode/subscript conversion or
        # inference from an internal ID: all of those can merge visible labels.
        if not isinstance(label, str) or not label.strip():
            return None, 'missing_printed_label'
        if label in by_label:
            return None, 'duplicate_printed_label'
        by_id[identifier] = label
        by_label[label] = identifier
    return (by_id, by_label), None


def remap_repair_edges(previous_graph, proposed_graph):
    """Return ``(edges, audit)`` or ``(None, rejection_audit)``.

    This function grants no repair permission. Use it only for a named panel
    whose edges the existing scope policy already allows rereading. Both
    inventories must contain the same number of vertices with the same unique,
    nonempty printed labels, including every isolated vertex. Anonymous or
    ambiguous inventories remain unresolved. Only ``from``/``to`` references
    change; edge order, parallel instances, loops and attributes are preserved.
    Neither input is mutated, and original vertices are never replaced.
    """
    audit = {'status': 'rejected', 'basis': 'unique_exact_printed_labels',
             'geometry_used': False, 'topology_used': False,
             'image_accuracy_certified': False}

    def reject(reason):
        return None, {**audit, 'reason': reason}

    if not isinstance(previous_graph, dict) or not isinstance(proposed_graph, dict):
        return reject('invalid_graph')
    graph_id = previous_graph.get('id')
    if not _exact_id(graph_id) or proposed_graph.get('id') != graph_id:
        return reject('graph_identity_mismatch')
    audit['graph_id'] = graph_id
    previous, reason = _vertex_inventory(previous_graph)
    if reason:
        return reject('previous_' + reason)
    proposed, reason = _vertex_inventory(proposed_graph)
    if reason:
        return reject('proposed_' + reason)
    previous_ids, previous_labels = previous
    proposed_ids, proposed_labels = proposed
    if len(previous_ids) != len(proposed_ids):
        return reject('vertex_count_changed')
    if previous_labels.keys() != proposed_labels.keys():
        return reject('printed_labels_changed')
    mapping = {identifier: previous_labels[label]
               for identifier, label in proposed_ids.items()}
    # Validate every proposed reference before copying anything. An incomplete
    # mapping must not salvage some edges while silently dropping others.
    proposed_edges = proposed_graph.get('edges')
    if not isinstance(proposed_edges, list):
        return reject('edge_inventory_missing')
    if len(proposed_edges) > MAX_EDGES:
        return reject('edge_capacity_exceeded')
    for edge in proposed_edges:
        if not isinstance(edge, dict):
            return reject('invalid_edge')
        for endpoint in ('from', 'to'):
            identifier = edge.get(endpoint)
            if not _exact_id(identifier) or identifier not in mapping:
                return reject('unknown_proposed_endpoint')
    edges = copy.deepcopy(proposed_edges)
    changed_endpoints = 0
    for edge in edges:
        for endpoint in ('from', 'to'):
            before = edge[endpoint]
            edge[endpoint] = mapping[before]
            changed_endpoints += before != edge[endpoint]
    return edges, {**audit, 'status': 'mapped',
                   'vertex_id_map': mapping,
                   'mapped_vertex_count': len(mapping),
                   'renamed_vertex_count': sum(old != new for old, new in mapping.items()),
                   'changed_endpoint_count': changed_endpoints,
                   'edge_instances_preserved': len(edges)}


__all__ = ['remap_repair_edges']
