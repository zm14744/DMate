"""Second-pass panel corrections which preserve old candidate ink identities.

Source references are graph-local IDs, never image names or reference answers.
"""
from __future__ import annotations
import copy
import hashlib

from graph_qwen_coordinates import box, graph_name, identifier


def transfer_id(graph_id, candidate_id):
    key = (graph_id + '\0' + candidate_id).encode('utf-8')
    return 'carry_' + hashlib.blake2s(key, digest_size=8).hexdigest()


def _reason(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 400:
        raise ValueError('panel_revision_reason_required')
    return value


def _source(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('invalid_revision_source')
    return identifier(value[0]), identifier(value[1])


def update_panel(graph, row):
    update = row.get('panel_update')
    if update is None:
        return
    if not isinstance(update, dict) or not ({'bbox', 'name'} & update.keys()):
        raise ValueError('invalid_panel_update')
    reason = _reason(update.get('reason'))
    before = {'bbox': copy.deepcopy(graph.get('bbox')), 'name': graph.get('name')}
    if 'bbox' in update:
        graph['bbox'] = box(update['bbox'])
    if 'name' in update:
        graph['name'] = graph_name(update['name'])[:80]
    graph['panel_revision_audit'] = {'kind': 'update', 'reason': reason, 'before': before}


def revise_panels(response, initial, proposals, decode):
    """Each replaced node is referenced once or explicitly retired.

Candidates whose endpoints migrate to one panel transfer automatically under
their advertised revision_id. Others require explicit retirement decisions.
    """
    revision = response.get('panel_revision')
    if revision is None:
        return initial, proposals, [], False
    if not isinstance(revision, dict):
        raise ValueError('invalid_panel_revision')
    reason = _reason(revision.get('reason'))
    replaced = revision.get('replaces')
    if not isinstance(replaced, list) or any(not isinstance(x, str) for x in replaced):
        raise ValueError('invalid_replaced_panels')
    if len(replaced) != len(set(replaced)):
        raise ValueError('duplicate_replaced_panel')
    old_by_id = {g['id']: g for g in initial}
    if set(replaced) - old_by_id.keys():
        raise ValueError('unknown_replaced_panel')
    raw_new = revision.get('graphs')
    if not isinstance(raw_new, list) or not (replaced or raw_new):
        raise ValueError('empty_panel_revision')
    fresh = decode({'coordinate_space': 'original_1000', 'graphs': raw_new}) if raw_new else []
    if any(not g['id'].startswith('panel_new_') or g['id'] in old_by_id for g in fresh):
        raise ValueError('revision_requires_fresh_panel_id')
    final_count = len(initial) - len(replaced) + len(fresh)
    if not 1 <= final_count <= 12:
        raise ValueError('revised_panel_budget')
    source_nodes = {(gid, v['id']): v for gid in replaced for v in old_by_id[gid]['vertices']}
    mapping = {}
    for raw in raw_new:
        for vertex in raw['vertices']:
            if 'source' not in vertex:
                continue
            source = _source(vertex['source'])
            if source not in source_nodes or source in mapping:
                raise ValueError('unknown_or_reused_source_node')
            mapping[source] = (raw['id'], vertex['id'])
    retired = revision.get('retired_vertices', [])
    if not isinstance(retired, list):
        raise ValueError('invalid_retired_vertices')
    removed = {}
    for item in retired:
        if not isinstance(item, dict):
            raise ValueError('invalid_retired_vertex')
        source = _source(item.get('source'))
        if source not in source_nodes or source in mapping or source in removed:
            raise ValueError('invalid_retired_vertex_identity')
        removed[source] = _reason(item.get('reason'))
    if set(source_nodes) != set(mapping) | set(removed):
        raise ValueError('revision_source_nodes_unaccounted')
    moved = {gid: copy.deepcopy(rows) for gid, rows in proposals.items() if gid not in replaced}
    for graph in fresh:
        moved[graph['id']] = []
    needs_retirement, transfers = set(), []
    for gid in replaced:
        for candidate in proposals.get(gid, []):
            source = (gid, candidate['id'])
            start = mapping.get((gid, candidate['from']))
            end = mapping.get((gid, candidate['to']))
            if start is None or end is None or start[0] != end[0]:
                needs_retirement.add(source)
                continue
            item = copy.deepcopy(candidate)
            item.update(id=transfer_id(*source), **{'from': start[1], 'to': end[1]})
            item['source_candidate'] = list(source)
            connector=item.get('connector_evidence')
            if isinstance(connector,dict):
                for field in ('head_vertex','tail_vertex'):
                    if field in connector:
                        target=mapping.get((gid,connector[field]))
                        if target is None or target[0]!=start[0]:
                            raise ValueError('invalid_transferred_connector_endpoint')
                        connector[field]=target[1]
            if isinstance(item.get('ports'),list):
                for port in item['ports']:
                    target=mapping.get((gid,port.get('vertex')))
                    if target is None or target[0]!=start[0]:
                        raise ValueError('invalid_transferred_port_endpoint')
                    port['vertex']=target[1]
            if isinstance(item.get('arrow_hint'),dict):
                for field in ('from','to'):
                    if field in item['arrow_hint']:
                        target=mapping.get((gid,item['arrow_hint'][field]))
                        if target is None or target[0]!=start[0]:
                            raise ValueError('invalid_transferred_arrow_endpoint')
                        item['arrow_hint'][field]=target[1]
            moved[start[0]].append(item)
            transfers.append({'source': list(source), 'graph': start[0], 'id': item['id']})
    retired_candidates = revision.get('retired_candidates', [])
    if not isinstance(retired_candidates, list):
        raise ValueError('invalid_retired_candidates')
    resolved, issues = {}, []
    for item in retired_candidates:
        if not isinstance(item, dict):
            raise ValueError('invalid_retired_candidate')
        source = _source(item.get('source'))
        if source not in needs_retirement or source in resolved:
            raise ValueError('invalid_retired_candidate_identity')
        _reason(item.get('reason'))
        if item.get('visible') is not False:
            issues.append('unresolved_retired_candidate:' + '/'.join(source))
        resolved[source] = copy.deepcopy(item)
    if needs_retirement != resolved.keys():
        raise ValueError('revision_candidates_unaccounted')
    audit = {'kind': 'replace', 'reason': reason, 'replaced_panels': list(replaced),
             'node_sources': [{'source': list(k), 'graph': v[0], 'vertex': v[1]} for k, v in mapping.items()],
             'retired_vertices': copy.deepcopy(retired), 'candidate_transfers': transfers,
             'retired_candidates': copy.deepcopy(retired_candidates)}
    for graph in fresh:
        graph['panel_revision_audit'] = copy.deepcopy(audit)
    output, inserted = [], False
    for graph in initial:
        if graph['id'] in replaced:
            if not inserted:
                output.extend(fresh)
                inserted = True
        else:
            output.append(copy.deepcopy(graph))
    if not inserted:
        output.extend(fresh)
    if sum(len(g['vertices']) for g in output) > 160:
        raise ValueError('revised_total_node_budget')
    return output, moved, issues, True
