"""Bounded CPU observations for the semantic reader, never graph answers.

The two phases run real OpenCV measurements and the existing isolated sknw
plugin.  Mathematical vertices, edge counts and final directions remain the
reader's responsibility.  Missing measurements are not negative evidence.
``document`` is an internal reusable pixel object, not a JSON/model field.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

VERSION = '2026-10-26-semantic-geometry-v1'
MAX_GRAPHS = 10
MAX_VERTICES = 30
MAX_CANDIDATES = 160
MAX_SECONDS = 20.
OPENCV_SECONDS = 7.
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class _BudgetStopped(Exception):
    def __init__(self, error):
        self.error = error


def _worker_checkpoint(budget):
    try:
        budget.check()
    except Exception as exc:
        raise _BudgetStopped(exc) from exc


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _box(value):
    if (isinstance(value, (list, tuple)) and len(value) == 4
            and all(_number(x) and 0 <= x <= 1000 for x in value)
            and value[0] < value[2] and value[1] < value[3]):
        return [float(x) / 1000 for x in value]
    return None


def _position(value):
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_number(x) and 0 <= x <= 1000 for x in value)):
        return [float(x) / 1000 for x in value]
    return None


def _vertex_position(vertex):
    point = _position(vertex.get('position'))
    if point is not None:
        return point
    # Existing semantic inventories may use a prose position plus numeric x/y.
    # Both numeric formats are explicitly original_1000, never guessed units.
    return _position([vertex.get('x'), vertex.get('y')])


def _issue(code, *, graph_id=None, **details):
    result = {'code': code, 'advisory_only': True, 'blocks_recognition': False, **details}
    if graph_id is not None:
        result['graph_id'] = graph_id
    return result


def _audit(tool, source, started, status, *, executed=False, **details):
    return {'tool': tool, 'version': VERSION, 'source_sha256': source,
            'status': status, 'executed': executed, 'proposal_only': True,
            'seconds': round(time.monotonic() - started, 4), **details}


def _original_point(point, document):
    pixels = [((point[i] * (document.work_size[i] - 1) + .5)
               / document.scale_xy[i] - .5) for i in (0, 1)]
    return [round(max(0., min(1000., pixels[i] /
                  max(document.original.size[i] - 1, 1) * 1000)), 3) for i in (0, 1)]


def _marker_view(pool, document):
    w, h = document.work_size
    return [{'id': item['id'], 'position': _original_point([item['x'], item['y']], document),
             'radius_x': round(item['radius_pixels'] / max(w - 1, 1) * 1000, 3),
             'radius_y': round(item['radius_pixels'] / max(h - 1, 1) * 1000, 3),
             'kind': item['kind'], 'confidence': float(item['confidence']),
             'source': item['evidence']['source'], 'proposal_only': True,
             'advisory_only': bool(item.get('advisory_only')),
             'connected_stroke': bool(item.get('connected_stroke'))}
            for item in pool.get('items', [])]


def _regions(document, pool):
    """Ink regions are crop suggestions; disconnected regions are NOT panels."""
    import cv2
    import numpy as np
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        np.uint8(document.ink_mask != 0), 8)
    w, h = document.work_size
    rows = []
    for index in range(1, count):
        x, y, rw, rh, area = (int(v) for v in stats[index])
        if min(rw, rh) < 12 or max(rw, rh) < 32 or area < 30:
            continue
        marker_ids = [m['id'] for m in pool.get('items', [])
                      if x <= m['x'] * (w - 1) < x + rw
                      and y <= m['y'] * (h - 1) < y + rh]
        if not marker_ids:
            continue
        rows.append({'bbox': [round(x / w * 1000, 3), round(y / h * 1000, 3),
                              round((x + rw) / w * 1000, 3),
                              round((y + rh) / h * 1000, 3)],
                     'marker_ids': marker_ids, 'ink_pixels': area,
                     'source': 'opencv_connected_ink_region',
                     'proposal_only': True, 'mathematical_panel_confirmed': False})
    rows.sort(key=lambda r: (-r['ink_pixels'], r['bbox']))
    return rows[:32], len(rows) > 32


def _layout_boxes(layout):
    if not isinstance(layout, dict):
        return []
    rows = layout.get('panels', [])
    if not isinstance(rows, list):
        return []
    return [box for row in rows[:64] if isinstance(row, dict)
            and (box := _box(row.get('bbox'))) is not None]


def _tool_graphs(draft, pool, document, layout):
    """Associate only a unique close marker; all other endpoints stay unmapped."""
    source = draft.get('graphs', []) if isinstance(draft, dict) else []
    if not isinstance(source, list):
        return [], {}, [_issue('invalid_geometry_inventory')]
    tools, associations, issues, seen = [], {}, [], set()
    w, h = document.work_size
    limited = any(v is True for k, v in pool.get('limits', {}).items()
                  if k.endswith('_limit_reached'))
    if limited:
        issues.append(_issue('marker_pool_incomplete_no_unique_association'))
    for graph in source[:MAX_GRAPHS]:
        if not isinstance(graph, dict):
            continue
        gid = graph.get('id')
        if not isinstance(gid, str) or not gid or len(gid) > 128 or gid in seen:
            issues.append(_issue('invalid_or_duplicate_graph_id'))
            continue
        seen.add(gid)
        vertices = graph.get('vertices', [])
        if not isinstance(vertices, list):
            issues.append(_issue('invalid_vertex_inventory', graph_id=gid))
            continue
        supplied, ids = [], set()
        for vertex in vertices:
            if not isinstance(vertex, dict):
                continue
            vid = vertex.get('id')
            if not isinstance(vid, str) or not vid or vid in ids:
                continue
            ids.add(vid)
            point = _vertex_position(vertex)
            if point is not None:
                point = [((point[i] * (document.original.size[i] - 1) + .5)
                           * document.scale_xy[i] - .5) / max(document.work_size[i] - 1, 1)
                         for i in (0, 1)]
                supplied.append((vid, point))
        box, box_source = _box(graph.get('bbox')), 'draft_crop_hint'
        if box is None and supplied:
            matches = [b for b in _layout_boxes(layout)
                       if all(b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]
                              for _, p in supplied)]
            if len(matches) == 1:
                box, box_source = matches[0], 'local_layout_crop_hint'
        if box is None and len(source) == 1:
            box, box_source = [0., 0., 1., 1.], 'single_inventory_overview'
        if box is None and supplied:
            xs, ys = [p[0] for _, p in supplied], [p[1] for _, p in supplied]
            px, py = max(.04, (max(xs) - min(xs)) * .18), max(.04, (max(ys) - min(ys)) * .18)
            box = [max(0., min(xs) - px), max(0., min(ys) - py),
                   min(1., max(xs) + px), min(1., max(ys) + py)]
            box_source = 'draft_position_extent_crop_hint'
            issues.append(_issue('panel_crop_inferred_not_confirmed', graph_id=gid))
        if box is None:
            issues.append(_issue('no_panel_geometry_for_tools', graph_id=gid))
            continue
        markers = [m for m in pool.get('items', [])
                   if box[0] <= m['x'] <= box[2] and box[1] <= m['y'] <= box[3]
                   and m['confidence'] >= .8 and not m.get('advisory_only')]
        if len(markers) + len(supplied) > MAX_VERTICES * 2:
            issues.append(_issue('geometry_vertex_capacity', graph_id=gid, limit=MAX_VERTICES))
            continue
        near, reverse = {}, {}
        for marker in markers:
            mid = marker['id']
            found = [vid for vid, point in supplied
                     if math.hypot((point[0] - marker['x']) * (w - 1),
                                   (point[1] - marker['y']) * (h - 1))
                     <= max(3., marker['radius_pixels'] * 1.5)]
            near[mid] = found
            for vid in found:
                reverse.setdefault(vid, []).append(mid)
        nodes, mapping, represented = [], {}, set()
        for marker in markers:
            mid = marker['id']
            close = near[mid]
            known = (not limited and not marker.get('advisory_only')
                     and marker['confidence'] >= .8 and len(close) == 1
                     and len(reverse[close[0]]) == 1
                     and any(vid == close[0] and box[0] <= p[0] <= box[2]
                             and box[1] <= p[1] <= box[3] for vid, p in supplied))
            vid = close[0] if known else None
            if vid:
                represented.add(vid)
            nodes.append({'id': mid, 'x': marker['x'], 'y': marker['y']})
            mapping[mid] = {'marker_id': mid, 'vertex_id': vid,
                            'position': _original_point([marker['x'], marker['y']], document),
                            'association': 'unique_close_marker' if known else 'unmapped'}
        for index, (vid, point) in enumerate(supplied):
            # Coarse model points cannot cut an already measured stroke into
            # additional nodes. Keep them in the draft only. With no marker
            # measurements at all, they may supply explicitly unmapped seeds.
            if markers:
                continue
            if vid in represented or reverse.get(vid):
                continue
            if not (box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]):
                issues.append(_issue('draft_position_outside_crop', graph_id=gid, vertex_id=vid))
                continue
            pid = 'draft_position_' + str(index + 1)
            nodes.append({'id': pid, 'x': point[0], 'y': point[1]})
            mapping[pid] = {'vertex_id': None, 'vertex_hint': vid,
                            'position': _original_point(point, document),
                            'association': 'unmapped_draft_position_only'}
        if not nodes or len(nodes) > MAX_VERTICES:
            issues.append(_issue('no_bounded_geometry_inventory', graph_id=gid,
                                 measured_endpoints=len(nodes), limit=MAX_VERTICES))
            continue
        # Neither marker counts nor working positions replace semantic nodes.
        tools.append({'id': gid, 'bbox': box, 'vertices': nodes, 'directed': None,
                      'crop_source': box_source})
        associations[gid] = mapping
        unresolved = [vid for vid in ids if vid not in represented]
        if unresolved:
            issues.append(_issue('vertices_without_unique_marker_association', graph_id=gid,
                                 vertex_ids=sorted(unresolved)[:100]))
    if len(source) > MAX_GRAPHS:
        issues.append(_issue('geometry_graph_capacity', limit=MAX_GRAPHS, count=len(source)))
    owners = {}
    for gid, mapping in associations.items():
        for endpoint in mapping.values():
            if endpoint.get('marker_id') and endpoint.get('vertex_id'):
                owners.setdefault(endpoint['marker_id'], []).append((gid, endpoint))
    for marker_id, entries in owners.items():
        if len(entries) > 1:
            for gid, endpoint in entries:
                endpoint['vertex_hint'] = endpoint['vertex_id']
                endpoint['vertex_id'] = None
                endpoint['association'] = 'unmapped_shared_panel_marker'
                issues.append(_issue('marker_assigned_to_multiple_panel_hints', graph_id=gid,
                                     marker_id=marker_id))
    return tools, associations, issues


def _trace_opencv(document, graphs, *, deadline, budget):
    """Contain the existing cooperative tracer in a killable CPU process."""
    import fcntl
    import numpy as np
    from graph_sknw_plugin import (_child_environment, _stop_process, _rss_bytes,
                                   MAX_RSS_BYTES)
    started = time.monotonic()
    inventory = {g['id']: [] for g in graphs}
    from graph_local_scheduler import local_model_lock
    with local_model_lock() as acquired:
        if not acquired:
            return inventory, [{'code': 'local_cpu_busy', 'status': 'failed', 'executed': False}]
        with tempfile.TemporaryDirectory(prefix='dmate-semantic-cv-') as name:
            folder = Path(name)
            np.savez(folder / 'pixels.npz', rgb=np.asarray(document.working),
                     normalized=np.asarray(document.normalized), ink=document.ink_mask,
                     strong=document.strong_ink, weak=document.uncertain_ink)
            (folder / 'request.json').write_text(json.dumps({
                'graphs': graphs, 'original_size': list(document.original.size),
                'work_size': list(document.work_size), 'scale_xy': list(document.scale_xy)}),
                encoding='utf-8')
            _worker_checkpoint(budget)
            if time.monotonic() >= deadline:
                return inventory, [{'code': 'deadline_exceeded', 'status': 'failed', 'executed': False}]
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--opencv-worker', name],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=_child_environment(folder), cwd=name, start_new_session=True)
            failure, peak = None, 0
            try:
                while proc.poll() is None:
                    _worker_checkpoint(budget)
                    peak = max(peak, _rss_bytes(proc.pid))
                    if time.monotonic() >= deadline or peak > MAX_RSS_BYTES:
                        failure = 'deadline_exceeded' if time.monotonic() >= deadline else 'memory_limit_exceeded'
                        break
                    time.sleep(.025)
            finally:
                _stop_process(proc)
            output = folder / 'response.json'
            result = {'candidates': inventory, 'diagnostics': []}
            if output.is_file() and output.stat().st_size <= MAX_OUTPUT_BYTES:
                result = json.loads(output.read_text(encoding='utf-8'))
            diagnostics = result['diagnostics']
            if failure or proc.returncode != 0:
                diagnostics.append({'code': failure or 'worker_failed', 'status': 'failed',
                                    'executed': any(d.get('code') == 'roi_traced' for d in diagnostics)})
            diagnostics.append({'code': 'worker_resources', 'status': 'ok',
                                'peak_rss_bytes': peak, 'cpu_parallelism': 1,
                                'seconds': round(time.monotonic() - started, 4)})
            return result['candidates'], diagnostics


def _color_measurement(document, path):
    import cv2
    import numpy as np
    w, h = document.work_size
    route = np.asarray(path, float) * [max(w - 1, 1), max(h - 1, 1)]
    mask = np.zeros((h, w), np.uint8)
    cv2.polylines(mask, [np.rint(route).astype(np.int32)], False, 255, 3)
    # Node disks and arrow terminals may have a different colour from the line.
    for endpoint in (route[0], route[-1]):
        cv2.circle(mask, tuple(np.rint(endpoint).astype(int)), 10, 0, -1)
    selected = (mask != 0) & (document.ink_mask != 0)
    pixels = np.asarray(document.working)[selected]
    if not len(pixels):
        return {'status': 'unmeasured', 'source': 'unmodified_working_rgb'}
    pixels = pixels[::max(1, math.ceil(len(pixels) / 2048))]
    hsv = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
    buckets = np.where(hsv[:, 1] >= 40, hsv[:, 0] // 15, 12)
    colors = []
    for key in sorted(set(int(v) for v in buckets), key=lambda k: (-int(np.sum(buckets == k)), k))[:3]:
        subset = pixels[buckets == key]
        colors.append({'rgb': [int(v) for v in np.median(subset, axis=0)],
                       'fraction': round(len(subset) / len(pixels), 4)})
    return {'status': 'measured', 'source': 'unmodified_working_rgb', 'colors': colors,
            'sample_count': len(pixels), 'semantic_color_confirmed': False}


def _project(document, inventories, associations, *, deadline=None, budget=None):
    graphs, archive, count = [], [], 0
    for gid, mapping in associations.items():
        candidates = []
        for source, inventory in inventories:
            for raw in inventory.get(gid, []):
                if budget is not None:
                    budget.check()
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if count >= MAX_CANDIDATES:
                    break
                path = raw.get('path')
                if (not isinstance(path, list) or not 2 <= len(path) <= 128
                        or any(not isinstance(p, (list, tuple)) or len(p) != 2
                               or not all(_number(v) and 0 <= v <= 1 for v in p) for p in path)):
                    continue
                a, b = mapping.get(raw.get('from')), mapping.get(raw.get('to'))
                if a is None or b is None:
                    continue
                instance = source + ':' + gid + ':' + str(raw.get('id', len(candidates)))
                selected = [path[round(i * (len(path) - 1) / min(23, len(path) - 1))]
                            for i in range(min(24, len(path)))]
                row = {'instance_id': instance, 'source': source, 'from': a.get('vertex_id'),
                       'to': b.get('vertex_id'), 'endpoints': [copy.deepcopy(a), copy.deepcopy(b)],
                       'unmapped': not (a.get('vertex_id') and b.get('vertex_id')),
                       'path_hint': [_original_point(p, document) for p in selected],
                       'coordinate_space': 'original_1000', 'proposal_only': True,
                       'color_measurement': _color_measurement(document, path)}
                if raw.get('style') in ('solid', 'dashed', 'dotted', 'unknown'):
                    row['style_hint'] = raw['style']
                arrow = raw.get('arrow_hint')
                if isinstance(arrow, dict) and _number(arrow.get('score')):
                    left, right = mapping.get(arrow.get('from')), mapping.get(arrow.get('to'))
                    if left is not None and right is not None:
                        row['arrow_measurement'] = {'from': left.get('vertex_id'), 'to': right.get('vertex_id'),
                            'endpoints': [copy.deepcopy(left), copy.deepcopy(right)],
                            'score': float(arrow['score']), 'confirmed': False,
                            'method': arrow.get('method'), 'source': 'unmodified_working_rgb'}
                candidates.append(row)
                # Full routes are evidence for diagnostics, never required model output.
                archive.append({'instance_id': instance, 'graph_id': gid,
                                'original_pixel_path': [[round((p[i] * (document.work_size[i] - 1) + .5)
                                                               / document.scale_xy[i] - .5, 4)
                                                         for i in (0, 1)] for p in path],
                                'raw_candidate': copy.deepcopy(raw)})
                count += 1
        graphs.append({'graph_id': gid, 'candidates': candidates})
    return graphs, archive, count


def prepare_semantic_geometry(raw, *, draft=None, budget, document=None, layout=None, run_sknw=True):
    """Measure a source twice at most: markers, then bounded per-graph routes.

    ``layout`` accepts source-bound layout panels in original_1000 coordinates.
    No tool result changes ``draft`` or certifies its content. Cancellation and
    the shared task deadline propagate; local tool failures return diagnostics.
    """
    from image_evidence import analyze_document, DocumentEvidence
    from graph_marker_grounding import marker_proposals
    from graph_sknw_plugin import suggest_candidates
    started = time.monotonic()
    budget.check()
    if type(run_sknw) is not bool:
        raise ValueError('invalid_sknw_policy')
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected_image_bytes')
    source = hashlib.sha256(raw).hexdigest()
    expected = getattr(budget, 'source_sha256', None)
    if expected is not None and expected != source:
        raise ValueError('source_identity_mismatch')
    cache = getattr(document, '_semantic_geometry_cache', None)
    if document is not None and (not isinstance(document, DocumentEvidence)
            or not isinstance(cache, dict) or cache.get('source_sha256') != source):
        raise ValueError('geometry_document_source_mismatch')
    result = {'version': VERSION, 'source_sha256': source, 'marker_candidates': [],
              'region_candidates': [], 'graphs': [], 'issues': [], 'tool_audit': [],
              'diagnostics': [], 'candidate_audit': [], 'proposal_only': True}
    try:
        if document is None:
            document = analyze_document(raw)
            pool = marker_proposals(document)
            regions, limited = _regions(document, pool)
            cache = {'source_sha256': source, 'pool': pool, 'regions': regions}
            document._semantic_geometry_cache = cache
            result['tool_audit'].append(_audit('image.semantic_markers', source, started,
                'success', executed=True, marker_count=len(pool['items']), region_count=len(regions)))
            if limited:
                result['issues'].append(_issue('region_candidate_capacity', limit=32))
        else:
            result['tool_audit'].append(_audit('image.semantic_markers', source, started,
                'reused', executed=False, source_measurement_reused=True))
        result['document'] = document
        result['marker_candidates'] = _marker_view(cache['pool'], document)
        result['region_candidates'] = copy.deepcopy(cache['regions'])
        result['diagnostics'].append({'marker_limits': copy.deepcopy(cache['pool'].get('limits', {})),
                                      'work_size': list(document.work_size),
                                      'original_size': list(document.original.size)})
    except Exception as exc:
        budget.check()
        result['document'] = None
        result['tool_audit'].append(_audit('image.semantic_markers', source, started, 'failed',
                                          error_type=type(exc).__name__))
        result['issues'].append(_issue('geometry_preparation_unavailable'))
        return result
    budget.check()
    if draft is None:
        result['diagnostics'].append({'stage': 'before_inventory', 'sknw': 'not_requested',
                                      'seconds': round(time.monotonic() - started, 4)})
        return result
    graphs, associations, issues = _tool_graphs(draft, cache['pool'], document, layout)
    result['issues'].extend(issues)
    deadline = min(budget.deadline, started + MAX_SECONDS)
    inventories = []
    for name in ('opencv', 'sknw'):
        tick = time.monotonic()
        if name == 'sknw' and not run_sknw:
            result['tool_audit'].append(_audit('image.semantic_sknw', source, tick, 'not_requested',
                reason='local_tool_policy', executed=False))
            continue
        if not graphs or tick >= deadline:
            result['tool_audit'].append(_audit('image.semantic_' + name, source, tick, 'skipped',
                reason='no_bounded_roi' if not graphs else 'geometry_deadline'))
            continue
        try:
            if name == 'opencv':
                inventory, diagnostics = _trace_opencv(document, graphs,
                    deadline=min(deadline, tick + OPENCV_SECONDS), budget=budget)
            else:
                inventory, diagnostics = suggest_candidates(document, copy.deepcopy(graphs),
                    max_candidates=MAX_CANDIDATES, deadline=deadline)
            executed = any(isinstance(d, dict) and d.get('code') == 'roi_traced' for d in diagnostics)
            failed = any(isinstance(d, dict) and d.get('status') == 'failed' for d in diagnostics)
            rows = sum(len(v) for v in inventory.values())
            inventories.append((name, inventory))
            result['diagnostics'].append({'tool': name, 'details': diagnostics})
            result['tool_audit'].append(_audit('image.semantic_' + name, source, tick,
                'partial' if failed and executed else 'failed' if failed or not executed else 'success',
                executed=executed, candidate_count=rows))
        except _BudgetStopped as exc:
            raise exc.error
        except Exception as exc:
            budget.check()
            result['tool_audit'].append(_audit('image.semantic_' + name, source, tick, 'failed',
                                              error_type=type(exc).__name__))
            result['issues'].append(_issue('geometry_tool_unavailable', tool=name))
        budget.check()
    result['graphs'], result['candidate_audit'], count = _project(document, inventories, associations,
                                                               deadline=deadline, budget=budget)
    if time.monotonic() >= deadline:
        result['issues'].append(_issue('geometry_stage_deadline', seconds=MAX_SECONDS))
    if count >= MAX_CANDIDATES:
        result['issues'].append(_issue('geometry_candidate_capacity', limit=MAX_CANDIDATES))
    result['diagnostics'].append({'stage': 'after_inventory', 'candidate_count': count,
        'seconds': round(time.monotonic() - started, 4), 'mathematical_edges_certified': False,
        'absence_is_not_negative_evidence': True})
    return result


def _opencv_worker(folder):
    import cv2
    import numpy as np
    from PIL import Image
    from image_evidence import DocumentEvidence
    from graph_evidence_pipeline import collect_candidates
    from graph_agent_plugins import _native_trace_measurements
    from graph_arrow_evidence import annotate_arrow_candidates
    cv2.setNumThreads(1)
    request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
    with np.load(folder / 'pixels.npz', allow_pickle=False) as data:
        document = DocumentEvidence(original=SimpleNamespace(size=tuple(request['original_size'])),
            working=Image.fromarray(data['rgb']), normalized=Image.fromarray(data['normalized']),
            sharpened=Image.fromarray(data['normalized']), ink_mask=data['ink'],
            strong_ink=data['strong'], uncertain_ink=data['weak'],
            work_size=tuple(request['work_size']), scale_xy=tuple(request['scale_xy']),
            quality={}, diagnostics=[])
        result = {'candidates': {}, 'diagnostics': []}
        for graph in request['graphs']:
            inventory, diagnostics = collect_candidates(document, [graph])
            rows = inventory.get(graph['id'], [])
            # Candidate assistance may use a normalized image; arrow evidence
            # is recomputed on the unmodified source working RGB per route.
            for row in rows:
                row.pop('arrow_hint', None)
                row.pop('arrow_candidate', None)
            points = [[v['x'] * (document.work_size[0] - 1),
                       v['y'] * (document.work_size[1] - 1)] for v in graph['vertices']]
            distances = [min((math.dist(p, q) for j, q in enumerate(points) if i != j), default=60.)
                         for i, p in enumerate(points)]
            radius = max(3, min(13, round(float(np.median(distances)) * .12)))
            annotate_arrow_candidates(np.asarray(document.working), graph, rows, radius)
            for row in rows:
                if isinstance(row.get('arrow_candidate'), dict):
                    row['arrow_hint'] = row.pop('arrow_candidate')
            result['candidates'].update(_native_trace_measurements(inventory))
            result['diagnostics'].append({'code': 'roi_traced', 'status': 'ok', 'graph_id': graph['id'],
                                          'candidate_count': len(inventory.get(graph['id'], []))})
            result['diagnostics'].extend({'code': str(d), 'status': 'partial'} for d in diagnostics)
            (folder / 'response.partial').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
            os.replace(folder / 'response.partial', folder / 'response.json')


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--opencv-worker':
        raise SystemExit(2)
    import resource
    from graph_sknw_plugin import MAX_ADDRESS_BYTES
    resource.setrlimit(resource.RLIMIT_AS, (MAX_ADDRESS_BYTES, MAX_ADDRESS_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (22, 22))
    if hasattr(os, 'sched_getaffinity'):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    _opencv_worker(Path(sys.argv[2]))


__all__ = ['prepare_semantic_geometry']
