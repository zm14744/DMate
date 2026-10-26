"""Optional, bounded sknw path proposals; never final mathematical edges.

All CPU work runs in one disposable subprocess under the local-OCR file lock.
Only a bounded graph ROI with known node footprints erased is skeletonized.
sknw junctions are tool-local pixels, not mathematical vertices, and its
``weight`` (pixel length) is deliberately not copied into graph semantics.
"""
from __future__ import annotations

import copy
import importlib.metadata
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace


PLUGIN_VERSION = '2026-10-26-sknw-proposals-v1'
PARAMETERS = {'multi': True, 'iso': True, 'ring': True, 'full': False}
EXPECTED_VERSIONS = {'sknw': '0.15', 'numba': '0.61.2', 'llvmlite': '0.44.0', 'numpy': '1.26.4'}
MAX_CANDIDATES = 160
MAX_GRAPHS = 10
MAX_SKELETON_PIXELS = 50_000  # sknw 0.15 has a fixed 131072-element trace buffer.
MAX_TOOL_NODES = 512
MAX_TOOL_EDGES = 768
MAX_JUNCTION_PIXELS = 128
MAX_ROUTE_PIXELS = 8192
MAX_ROUTE_SEGMENTS = 64
MAX_RAW_ROUTES = 640
MAX_RSS_BYTES = 768*1024*1024
MAX_ADDRESS_BYTES = 1536*1024*1024
MAX_OUTPUT_BYTES = 8*1024*1024
DEFAULT_SECONDS = 25.


def _diagnostic(code, status='partial', **extra):
    return {'tool': 'sknw', 'tool_version': '0.15', 'adapter_version': PLUGIN_VERSION,
            'status': status, 'code': code, 'proposal_only': True, **extra}


def _validated_graphs(graphs):
    if not isinstance(graphs, list):
        raise ValueError('graphs_must_be_list')
    output, seen = [], set()
    for graph in graphs:
        if not isinstance(graph, dict) or not isinstance(graph.get('id'), str):
            raise ValueError('invalid_graph_id')
        gid = graph['id']
        if not gid or len(gid) > 128 or gid in seen:
            raise ValueError('invalid_or_duplicate_graph_id')
        seen.add(gid)
        vertices = graph.get('vertices')
        if not isinstance(vertices, list):
            raise ValueError('invalid_vertices')
        nodes, names = [], set()
        for vertex in vertices:
            if not isinstance(vertex, dict):
                raise ValueError('invalid_vertex')
            name = vertex.get('id')
            if not isinstance(name, str) or not name or len(name) > 128 or name in names:
                raise ValueError('invalid_or_duplicate_vertex_id')
            names.add(name)
            xy = [vertex.get('x'), vertex.get('y')]
            if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in xy):
                raise ValueError('invalid_vertex_position')
            nodes.append({'id': name, 'x': xy[0], 'y': xy[1]})
        # Labels, existing edges, OCR text and model responses are not needed
        # by this local tool and are never serialized into its worker input.
        output.append({'id': gid, 'vertices': nodes, 'bbox': copy.deepcopy(graph.get('bbox')),
                       'directed': graph.get('directed')})
    return output


def _child_environment(folder):
    env = {name: os.environ[name] for name in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT') if name in os.environ}
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                'OPENBLAS_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1',
                'NUMBA_CACHE_DIR': str(folder/'numba-cache'), 'TMPDIR': str(folder)})
    return env


def _stop_process(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=.4)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=2.)


def _rss_bytes(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1])*1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def suggest_candidates(document, graphs, *, max_candidates=MAX_CANDIDATES, deadline=None):
    """Return proposals and explicit diagnostics; ``deadline`` is monotonic.

    Missing plugins, busy local OCR, hard timeouts and exceeded bounds abstain.
    A successful tool run means only candidate generation, never recognition
    completeness. The caller must pass candidates to the ordinary edge judge.
    """
    started = time.monotonic()
    try:
        if type(max_candidates) is not int or not 1 <= max_candidates <= MAX_CANDIDATES:
            raise ValueError('invalid_candidate_limit')
        if deadline is None:
            deadline = started+DEFAULT_SECONDS
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('invalid_deadline')
        selected = _validated_graphs(graphs)
        inventory = {g['id']: [] for g in selected}
    except (TypeError, ValueError) as exc:
        return {}, [_diagnostic(str(exc), 'failed')]
    if not selected:
        return inventory, [_diagnostic('no_graphs', 'ok', candidates=0)]
    if time.monotonic() >= deadline:
        return inventory, [_diagnostic('deadline_exceeded', 'failed')]
    try:
        import fcntl
        import numpy as np
        width, height = document.work_size
        if (type(width) is not int or type(height) is not int or
                min(width, height) < 2 or max(width, height) > 1600):
            raise ValueError('working_image_limit')
        masks = [document.ink_mask, document.strong_ink, document.uncertain_ink]
        if any(m.dtype != np.uint8 or m.shape != (height, width) for m in masks):
            raise ValueError('invalid_original_masks')
        original_size = list(document.original.size)
        scale = list(document.scale_xy)
        if any(not math.isfinite(v) or v <= 0 for v in scale):
            raise ValueError('invalid_coordinate_scale')
        if any(abs(scale[i]-document.work_size[i]/original_size[i]) > 1e-8 for i in (0, 1)):
            raise ValueError('inconsistent_coordinate_scale')
        lock_path = Path(tempfile.gettempdir())/'dmate-local-model.lock'
        with lock_path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return inventory, [_diagnostic('local_cpu_busy', 'failed')]
            try:
                with tempfile.TemporaryDirectory(prefix='dmate-sknw-') as name:
                    folder = Path(name)
                    np.savez(folder/'masks.npz', ink=masks[0], strong=masks[1], weak=masks[2])
                    request = {'graphs': selected[:MAX_GRAPHS], 'work_size': [width, height],
                               'original_size': original_size, 'scale_xy': scale,
                               'max_candidates': max_candidates}
                    (folder/'request.json').write_text(json.dumps(request), encoding='utf-8')
                    if time.monotonic() >= deadline:
                        return inventory, [_diagnostic('deadline_exceeded', 'failed')]
                    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(folder)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        env=_child_environment(folder), start_new_session=True, cwd=str(folder))
                    peak = 0
                    failure = None
                    try:
                        while proc.poll() is None:
                            peak = max(peak, _rss_bytes(proc.pid))
                            if time.monotonic() >= deadline:
                                failure = 'deadline_exceeded'
                                break
                            if peak > MAX_RSS_BYTES:
                                failure = 'memory_limit_exceeded'
                                break
                            time.sleep(min(.025, max(.001, deadline-time.monotonic())))
                    finally:
                        _stop_process(proc)
                    if failure:
                        return inventory, [_diagnostic(failure, 'failed', peak_rss_bytes=peak,
                            seconds=round(time.monotonic()-started, 3))]
                    output = folder/'response.json'
                    if proc.returncode != 0 or not output.is_file() or output.stat().st_size > MAX_OUTPUT_BYTES:
                        return inventory, [_diagnostic('worker_failed', 'failed', returncode=proc.returncode)]
                    result = json.loads(output.read_text(encoding='utf-8'))
                    if not isinstance(result.get('inventory'), dict) or not isinstance(result.get('diagnostics'), list):
                        raise ValueError('invalid_worker_result')
                    inventory.update(result['inventory'])
                    diagnostics = result['diagnostics']
                    if len(selected) > MAX_GRAPHS:
                        diagnostics.append(_diagnostic('graph_capacity_reached', graph_limit=MAX_GRAPHS,
                                                       graph_count=len(selected)))
                    reported_peak = result.get('worker_peak_rss_bytes', 0)
                    diagnostics.append(_diagnostic('worker_resources', 'ok', peak_rss_bytes=max(peak, reported_peak),
                        rss_observed=bool(peak or reported_peak), address_space_limit_bytes=MAX_ADDRESS_BYTES,
                        seconds=round(time.monotonic()-started, 3), cpu_parallelism=1))
                    return inventory, diagnostics
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except (ImportError, OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        # Never leak input bytes, file paths, arbitrary worker output or env.
        return inventory, [_diagnostic('worker_unavailable', 'failed', error_type=type(exc).__name__)]


def _junction_path(points, start, end):
    """Join segment ports through actual junction pixels, never its centroid."""
    from collections import deque
    pixels = {tuple(map(int, point)) for point in points}
    start, end = tuple(map(int, start)), tuple(map(int, end))
    if len(pixels) > MAX_JUNCTION_PIXELS or start not in pixels or end not in pixels:
        return None
    queue, parent = deque([start]), {start: None}
    while queue:
        p = queue.popleft()
        if p == end:
            route = []
            while p is not None:
                route.append(p)
                p = parent[p]
            return route[::-1]
        for dx, dy in ((-1,-1), (0,-1), (1,-1), (-1,0), (1,0), (-1,1), (0,1), (1,1)):
            q = (p[0]+dx, p[1]+dy)
            if q in pixels and q not in parent:
                parent[q] = p
                queue.append(q)
    return None


def _compact_junctions(graph):
    """Group only tiny touching raster junctions, retaining every real pixel.

    A diagonal crossing can become two sknw forks joined by 2--4 pixels.
    Their short connector is not a separate mathematical edge. Grouping its
    pixels permits tangent matching across that junction; no centroid chord
    or gap fill is introduced, and nearby long parallel strokes stay separate.
    """
    import networkx as nx
    import numpy as np
    parents = {node: node for node in graph}
    pixels = {node: {tuple(map(int, p)) for p in data['pts']}
              for node, data in graph.nodes(data=True)}
    def root(node):
        while parents[node] != node:
            node = parents[node]
        return node
    merged = set()
    rows = list(graph.edges(keys=True, data=True))
    for index, (a, b, _, data) in enumerate(rows):
        if a == b or graph.degree(a) < 3 or graph.degree(b) < 3 or len(data['pts']) > 5:
            continue
        ra, rb = root(a), root(b)
        if ra == rb:
            continue
        combined = pixels[ra] | pixels[rb] | {tuple(map(int, p)) for p in data['pts']}
        array = np.asarray(list(combined))
        if len(combined) > MAX_JUNCTION_PIXELS or np.max(np.ptp(array, axis=0)) > 7:
            continue
        parents[rb] = ra
        pixels[ra] = combined
        merged.add(index)
    if not merged:
        return graph
    output = nx.MultiGraph()
    for node in graph:
        r = root(node)
        if r not in output:
            pts = np.asarray(sorted(pixels[r]), dtype=np.int32)
            output.add_node(r, pts=pts, o=pts.mean(axis=0))
    for index, (a, b, _, data) in enumerate(rows):
        if index not in merged:
            output.add_edge(root(a), root(b), **data)
    return output


def _trace_tool_routes(tool_graph, roi):
    """Traverse unique near-straight continuations through unmarked junctions."""
    import numpy as np
    from graph_node_geometry import boundary_distance
    tool_graph = _compact_junctions(tool_graph)
    segments, incident, routes = {}, {}, []
    counts = {'unattached_segments': 0, 'ambiguous_junctions': 0, 'route_capacity_reached': False}
    for index, (u, v, _, data) in enumerate(tool_graph.edges(keys=True, data=True)):
        pts = np.asarray(data['pts'], dtype=np.int32)[:, ::-1]
        # NetworkX's iteration order need not match sknw's stored trace order.
        up = np.asarray(tool_graph.nodes[u]['pts'], float)[:, ::-1]
        if np.min(np.linalg.norm(up-pts[-1], axis=1)) < np.min(np.linalg.norm(up-pts[0], axis=1)):
            pts = pts[::-1]
        segments[index] = (u, v, pts)
        incident.setdefault(u, []).append((index, 0))
        incident.setdefault(v, []).append((index, 1))

    def oriented(key):
        u, v, pts = segments[key[0]]
        return (u, v, pts) if key[1] == 0 else (v, u, pts[::-1])

    def attachment(point):
        matches = [name for name, geo in roi['local_geometry'].items()
                   if .25 <= float(boundary_distance(point, geo)) <= 4.]
        return matches[0] if len(matches) == 1 else None

    def tangent(pts):
        delta = pts[min(len(pts)-1, 7)]-pts[0]
        return delta/max(1e-8, float(np.linalg.norm(delta)))

    for index, (u, v, points) in segments.items():
        for side in (0, 1):
            if len(routes) >= MAX_RAW_ROUTES:
                counts['route_capacity_reached'] = True
                counts['unattached_segments'] = len(segments)-len({i for row in routes for i in row['segment_ids']})
                return routes, counts
            _, _, initial = oriented((index, side))
            source = attachment(initial[0])
            if source is None:
                continue
            key, used, path, chain = (index, side), set(), [], []
            for _ in range(MAX_ROUTE_SEGMENTS):
                if key[0] in used:
                    break
                used.add(key[0])
                _, junction, pts = oriented(key)
                path.extend(map(tuple, pts if not path else pts[1:]))
                chain.append(key[0])
                if len(path) > MAX_ROUTE_PIXELS:
                    counts['route_capacity_reached'] = True
                    break
                target = attachment(pts[-1])
                if target is not None:
                    routes.append({'from': source, 'to': target, 'pixels': path,
                                   'segment_ids': chain})
                    break
                options = []
                incoming = -tangent(pts[::-1])
                for next_key in incident.get(junction, []):
                    if next_key[0] in used:
                        continue
                    _, _, following = oriented(next_key)
                    score = float(incoming @ tangent(following))
                    if score >= .85:
                        options.append((score, next_key, following))
                options.sort(key=lambda item: item[0], reverse=True)
                if not options or len(options) > 1 and options[0][0]-options[1][0] < .15:
                    counts['ambiguous_junctions'] += int(len(incident.get(junction, [])) > 2)
                    break
                _, next_key, following = options[0]
                junction_pixels = np.asarray(tool_graph.nodes[junction]['pts'])[:, ::-1]
                bridge = _junction_path(junction_pixels, pts[-1], following[0])
                if bridge is None:
                    counts['ambiguous_junctions'] += 1
                    break
                path.extend(bridge[1:])
                key = next_key
            else:
                counts['route_capacity_reached'] = True
    used = {index for route in routes for index in route['segment_ids']}
    counts['unattached_segments'] = len(segments)-len(used)
    return routes, counts


def _process(document, graphs, max_candidates, build_sknw, versions):
    import cv2
    import numpy as np
    from graph_line_tracer import prepare_skeleton_roi, keep_path_candidate
    from graph_stroke_checks import StrokeEvidence
    evidence = StrokeEvidence(document)
    inventory, diagnostics, total = {g['id']: [] for g in graphs}, [], 0
    for graph_index, graph in enumerate(graphs):
        gid = graph['id']
        if total >= max_candidates:
            diagnostics.append(_diagnostic('candidate_capacity_reached', graph_id=gid, limit=max_candidates))
            break
        try:
            roi = prepare_skeleton_roi(document, graph, evidence=evidence)
        except (ValueError, TypeError, KeyError) as exc:
            diagnostics.append(_diagnostic('roi_unavailable', graph_id=gid, error_type=type(exc).__name__))
            continue
        pixels = int(np.count_nonzero(roi['skeleton']))
        if pixels >= MAX_SKELETON_PIXELS:
            diagnostics.append(_diagnostic('skeleton_capacity_reached', graph_id=gid, pixels=pixels,
                                           limit=MAX_SKELETON_PIXELS))
            continue
        tool_graph = build_sknw(np.uint8(roi['skeleton'] > 0), **PARAMETERS)
        if len(tool_graph) > MAX_TOOL_NODES or tool_graph.number_of_edges() > MAX_TOOL_EDGES:
            diagnostics.append(_diagnostic('tool_graph_capacity_reached', graph_id=gid,
                nodes=len(tool_graph), segments=tool_graph.number_of_edges()))
            continue
        routes, counts = _trace_tool_routes(tool_graph, roi)
        diagnostics.append(_diagnostic('roi_traced', 'partial' if any(counts.values()) else 'ok',
            graph_id=gid, skeleton_pixels=pixels, tool_nodes=len(tool_graph),
            tool_segments=tool_graph.number_of_edges(), **counts))
        by_id = {v['id']: v for v in graph['vertices']}
        variants = {}
        width, height = document.work_size
        offset = np.asarray(roi['offset'], np.float32)
        for route in routes:
            points = np.asarray(route['pixels'], np.float32)+offset
            simplified = cv2.approxPolyDP(points.reshape(-1, 1, 2), .6, False).reshape(-1, 2)
            if not 2 <= len(simplified) <= 126:
                diagnostics.append(_diagnostic('path_point_capacity_or_degenerate', graph_id=gid))
                continue
            norm = simplified/np.asarray([width-1, height-1])
            source, target = by_id[route['from']], by_id[route['to']]
            path = [[source['x'], source['y']]]+np.round(norm, 6).tolist()+[[target['x'], target['y']]]
            candidate = {'id': f'sknw_{graph_index+1}_{len(variants)+1}_{len(routes)}',
                'from': route['from'], 'to': route['to'], 'path': path,
                'direction': 'undirected' if graph.get('directed') is False else 'unknown',
                'style': 'unknown', 'needs_review': True,
                'connector_evidence': {'kind': 'stroke_chain', 'source': 'sknw_node_erased_roi',
                                       'proposal_only': True}}
            proof = evidence.inspect(candidate, graph)
            if proof['coverage'] < .20 and proof.get('weak_coverage', 0) < .35:
                continue
            candidate['pixel_evidence'] = proof
            candidate['ports'] = copy.deepcopy(proof.get('ports', []))
            candidate['score'] = proof['coverage']
            original = (simplified+.5)/np.asarray(document.scale_xy)-.5
            candidate['tool_evidence'] = {'tool': 'sknw', 'tool_version': versions['sknw'],
                'adapter_version': PLUGIN_VERSION, 'versions': versions, 'parameters': dict(PARAMETERS),
                'proposal_only': True, 'segment_ids': route['segment_ids'],
                'original_pixel_path': np.round(original, 4).tolist(),
                'coordinate_space': 'canonical_original_pixel_centres',
                'original_size': list(document.original_size), 'work_size': [width, height],
                'scale_xy': list(document.scale_xy), 'roi_offset': list(roi['offset'])}
            pair = tuple(sorted((route['from'], route['to'])))
            decision = keep_path_candidate(candidate, variants.setdefault(pair, []), roi)
            if decision == 'pair_capacity_reached':
                diagnostics.append(_diagnostic('pair_capacity_reached', graph_id=gid, limit=6))
        candidates = []
        for rows in variants.values():
            for candidate in rows:
                if any(evidence.duplicate(candidate, old, graph=graph) for old in candidates):
                    continue
                candidate['id'] = f'sknw_{graph_index+1}_{len(candidates)+1}'
                candidate.pop('score', None)
                candidates.append(candidate)
                if total+len(candidates) >= max_candidates:
                    diagnostics.append(_diagnostic('candidate_capacity_reached', graph_id=gid, limit=max_candidates))
                    break
            if total+len(candidates) >= max_candidates:
                break
        inventory[gid] = candidates
        total += len(candidates)
    return {'inventory': inventory, 'diagnostics': diagnostics}


def _worker(folder):
    result = {'inventory': {}, 'diagnostics': []}
    try:
        versions = {name: importlib.metadata.version(name) for name in EXPECTED_VERSIONS}
        if versions != EXPECTED_VERSIONS:
            result['diagnostics'].append(_diagnostic('dependency_version_mismatch', 'failed', versions=versions))
        else:
            import cv2
            import numpy as np
            import numba
            import sknw
            cv2.setNumThreads(1)
            numba.set_num_threads(1)
            request = json.loads((folder/'request.json').read_text(encoding='utf-8'))
            with np.load(folder/'masks.npz', allow_pickle=False) as masks:
                document = SimpleNamespace(work_size=tuple(request['work_size']),
                    original_size=tuple(request['original_size']), scale_xy=tuple(request['scale_xy']),
                    ink_mask=masks['ink'], strong_ink=masks['strong'], uncertain_ink=masks['weak'])
                result = _process(document, request['graphs'], request['max_candidates'], sknw.build_sknw, versions)
    except importlib.metadata.PackageNotFoundError:
        result['diagnostics'].append(_diagnostic('dependency_missing', 'failed'))
    except Exception as exc:
        result['diagnostics'].append(_diagnostic('worker_exception', 'failed', error_type=type(exc).__name__))
    try:
        import resource
        result['worker_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    except (ImportError, OSError):
        result['worker_peak_rss_bytes'] = 0
    (folder/'response.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker':
        raise SystemExit(2)
    # OS process limits apply only to the disposable worker, never a caller
    # importing this plugin. The address-space limit remains effective even
    # when /proc RSS observation is unavailable in a container.
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MAX_ADDRESS_BYTES, MAX_ADDRESS_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    if hasattr(os, 'sched_getaffinity'):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    _worker(Path(sys.argv[2]))
