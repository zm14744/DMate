"""Recover bounded marker/route evidence from a single coarse visual inventory.

No graph templates, labels from references, or remote requests are used here.
"""
from __future__ import annotations
import copy
import math
from collections import defaultdict

import networkx as nx

from graph_staged import refine_node_positions


def connected_ring_markers(image):
    """Holes in large ink components distinguish junction rings from text.

    A textbook label's round glyph has a small parent component; a real hollow
    marker belongs to the connected drawn graph. Work before downsampling.
    """
    import cv2
    import numpy as np
    from graph_line_tracer import _foreground
    rgb=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR)
    contours,hierarchy=cv2.findContours(_foreground(rgb),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:return []
    points=[]
    for i,c in enumerate(contours):
        parent=int(hierarchy[0,i,3])
        if parent<0:continue
        _,_,width,height=cv2.boundingRect(c)
        area=cv2.contourArea(c); perimeter=cv2.arcLength(c,True)
        _,_,pw,ph=cv2.boundingRect(contours[parent])
        if (not 3<=width<=28 or not 3<=height<=28 or not .65<=width/height<=1.5
                or not 4<=area<=300 or 4*np.pi*area/max(perimeter*perimeter,1)<.55
                or pw<80 or ph<50):continue
        moments=cv2.moments(c)
        points.append({'component':parent,'x':moments['m10']/moments['m00']/(image.width-1),
                       'y':moments['m01']/moments['m00']/(image.height-1)})
    return points


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
    rings=connected_ring_markers(image)
    if len(rings)==len(nodes):markers=rings
    if len(markers) != len(nodes) or len(nodes) > 48:
        return refiner(image, graphs, partial=True)
    # With a complete connected-ring inventory, remove per-panel scale/offset
    # from the matching cost. Coarse VL coordinates on the textbook displaced
    # every node in the same direction, giving nearly tied raw-distance sums.
    groups=defaultdict(list)
    for p in markers:
        if 'component' in p:groups[p['component']].append(p)
    owners={}; priors={}; used=set(); offset=0
    for g in graphs:
        eligible=[(key,ps) for key,ps in groups.items() if key not in used and len(ps)==len(g['vertices'])]
        if len(eligible)==1:
            key,ps=eligible[0];used.add(key)
            for i,v in enumerate(g['vertices'],offset):
                owners[i]=key
                q=[]
                for coordinate in ('x','y'):
                    lo=min(n[coordinate] for n in g['vertices']);hi=max(n[coordinate] for n in g['vertices'])
                    a=min(p[coordinate] for p in ps);b=max(p[coordinate] for p in ps)
                    q.append(a+(v[coordinate]-lo)/(hi-lo)*(b-a) if hi>lo else (a+b)/2)
                priors[i]=q
        offset+=len(g['vertices'])
    assignment = nx.Graph()
    for i, v in enumerate(nodes):
        for j, p in enumerate(markers):
            if i in owners and p.get('component')!=owners[i]:continue
            x,y=priors.get(i,(v['x'],v['y']))
            distance = math.hypot(x-p['x'], y-p['y'])
            if distance <= .28:
                assignment.add_edge(('v', i), ('p', j), weight=distance)
    panel_indices=[]; offset=0
    for g in graphs:
        panel_indices.append(list(range(offset,offset+len(g['vertices']))));offset+=len(g['vertices'])
    def order_ok(matching):
        mapping={}
        for a,b in matching:
            if a[0]=='p':a,b=b,a
            mapping[a[1]]=markers[b[1]]
        for indices in panel_indices:
            for k,i in enumerate(indices):
                for j in indices[k+1:]:
                    a,b=nodes[i],nodes[j];u,v=mapping[i],mapping[j]
                    if abs(a['y']-b['y'])<=.025 and abs(a['x']-b['x'])>.04:
                        if (a['x']-b['x'])*(u['x']-v['x'])<0:return False
                    if abs(a['x']-b['x'])<=.025 and abs(a['y']-b['y'])>.04:
                        if (a['y']-b['y'])*(u['y']-v['y'])<0:return False
        return True
    best = nx.min_weight_matching(assignment)
    if len(best) != len(nodes) or not order_ok(best):
        return refiner(image, graphs, partial=True)
    cost = sum(assignment[a][b]['weight'] for a, b in best)
    # A near-equivalent full matching is unresolved, not a license to relabel
    # two actual markers. Check the runner-up without factorial enumeration.
    for a, b in best:
        weight = assignment[a][b]['weight']
        assignment.remove_edge(a, b)
        other = nx.min_weight_matching(assignment)
        ambiguous = (len(other) == len(nodes) and order_ok(other)
                     and sum(assignment[u][v]['weight'] for u, v in other)-cost < .015)
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
        by_pair[tuple(sorted((e['from'], e['to'])))].append(e)
    for trace in traces:
        path = copy.deepcopy(trace['path'])
        a, b = nodes[trace['from']], nodes[trace['to']]
        if math.dist(path[0], a)+math.dist(path[-1], b) > math.dist(path[0], b)+math.dist(path[-1], a):
            a, b = b, a
        path = [a]+path+[b]
        proof = _ink_support(path, ink, trace.get('style'), source='qwen')
        if proof is not None and not _intermediate_nodes(path, trace, graph['vertices']):
            if trace.get('style') not in ('solid','dashed','dotted') and proof['continuous']:
                trace['style']='solid'
            measured[tuple(sorted((trace['from'], trace['to'])))].append((trace, path, proof))
    for pair, edges in by_pair.items():
        choices = measured.get(pair, [])
        if not choices:
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


def guard_local_decisions(graph, decisions, ink):
    """A model denial cannot erase independently measured continuous ink.

    Keep contradictory strokes pending for human review rather than declaring
    completion. Reject local direction changes incompatible with graph type.
    """
    from graph_glm_adapter import _ink_support
    from graph_relation import _intermediate_nodes, _wrong_path_endpoints
    decisions=copy.deepcopy(decisions); notes=[]
    for e in graph['edges']:
        d=decisions.get(e['id'],{})
        sources={p.get('source') for p in e['evidence'] if isinstance(p,dict)}
        measured=bool(sources.intersection({'pixels','measured_route_binding'}))
        proof=(_ink_support(e['path'],ink,e['style'],source='qwen') if measured and e['path']
               and not _wrong_path_endpoints(e,graph['vertices'])
               and not _intermediate_nodes(e['path'],e,graph['vertices']) else None)
        if d.get('visible') is False and proof is not None:
            e['evidence'].append({'source':'qwen_geometry_conflict','field':'visible',
                                  'reported':False,'independent_ink':proof})
            d.pop('visible'); d.pop('path',None)
            d.pop('weight',None);d.pop('edge_label',None)
            notes.append('review_denial_conflicts_with_measured_ink:'+e['id'])
        if graph['directed'] is False and d.get('direction') in ('forward','reverse'):
            e['evidence'].append({'source':'qwen_geometry_conflict','field':'direction',
                                  'reported':d['direction'],'graph_directed':False})
            d['direction']='undirected'
            notes.append('review_direction_conflicts_with_graph_type:'+e['id'])
    return decisions,notes


def exclude_unmeasured_proposals(graph, ink):
    """A model-only line is a proposal, not an edge in the public table.

    Require the entire measured marker inventory before applying this guard;
    otherwise incorrect node positions could invalidate genuine connections.
    Rejected observations remain server-side, with their original IDs.
    """
    from graph_relation import _intermediate_nodes, _wrong_path_endpoints
    anchors=graph.get('node_position_evidence',[])
    if len(anchors)!=len(graph['vertices']) or any('partial' in e['source'] for e in anchors):
        return graph,[]
    retained=[]; rejected=[]
    for e in graph['edges']:
        invalid=bool(_intermediate_nodes(e['path'],e,graph['vertices']) or
                     _wrong_path_endpoints(e,graph['vertices']))
        measured=any(p.get('source')=='measured_route_binding' for p in e['evidence'] if isinstance(p,dict))
        # Continuity alone can be a fragment of another route. Each displayed
        # instance needs its OWN complete trace assignment; trimmed endpoint
        # coverage had certified an extra v--w copy of the exterior v--y arc.
        supported=measured
        if invalid or not supported:
            rejected.append({'reason':'intermediate_vertex_or_endpoints' if invalid else 'no_independent_measured_instance',
                             'proposal':copy.deepcopy(e)})
        else:retained.append(e)
    graph['edges']=retained
    if rejected:graph['node_review']['unsupported_edge_proposals']=rejected
    return graph,[f"unmeasured_visual_proposal:{graph['id']}:{r['proposal']['id']}" for r in rejected]


def mark_review_conflicts(graph):
    ids=set()
    for e in graph['edges']:
        if any(p.get('source')=='qwen_geometry_conflict' for p in e['evidence'] if isinstance(p,dict)):
            e['status']='pending';ids.add(e['id'])
    for a in graph.get('relation_audit',[]):
        if a['id'] in ids:a.update(status='pending',review_conflict=True)
    if ids:graph['complete']=False
    return graph


def locate_missing_weight_regions(image, graph):
    """Locate isolated text beside a measured stroke, without reading its value.

    Mid-stroke projection excludes endpoint/subscript labels. Ambiguous glyph
    regions abstain. The vision model still reads the actual original pixels.
    """
    import cv2
    import numpy as np
    from graph_line_tracer import _foreground
    rgb=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR)
    count,_,stats,centers=cv2.connectedComponentsWithStats(_foreground(rgb),8)
    width,height=image.size
    for e in graph['_candidates']:
        if e['weight'] is not None or not e['path']:continue
        route=np.asarray(e['path'])*[width-1,height-1]
        lengths=np.linalg.norm(np.diff(route,axis=0),axis=1);total=float(lengths.sum())
        if total<60:continue
        candidates=[]
        for i in range(1,count):
            x,y,bw,bh,area=map(int,stats[i])
            if not (4<=bw<=70 and 8<=bh<=65 and 15<=area<=1500):continue
            best=None;advance=0.
            for a,b,length in zip(route,route[1:],lengths):
                if length==0:continue
                t=float(np.clip(np.dot(centers[i]-a,b-a)/(length*length),0,1))
                distance=float(np.linalg.norm(centers[i]-(a+t*(b-a))))
                trial=(distance,(advance+t*length)/total)
                if best is None or trial<best:best=trial
                advance+=length
            distance,along=best
            if .25<=along<=.75 and distance<=max(18,bh*1.5):
                candidates.append((distance/bh,i,distance))
        candidates.sort()
        if not candidates:continue
        if len(candidates)>1 and candidates[1][0]-candidates[0][0]<.3:
            i,j=candidates[0][1],candidates[1][1]
            x,y,bw,bh,_=map(int,stats[i]);qx,qy,qw,qh,_=map(int,stats[j])
            gap=max(0,qx-(x+bw-1),x-(qx+qw-1))
            if gap>bh*.65 or abs(float(centers[j][1])-float(centers[i][1]))>bh*.25:continue
        _,i,distance=candidates[0];x,y,bw,bh,_=map(int,stats[i]);a,b,c,d=x,y,x+bw-1,y+bh-1
        # Include adjacent digits/signs on the same baseline, never another
        # distant edge's number. Do not interpret a multi-digit weight here.
        for j in range(1,count):
            if j==i:continue
            qx,qy,qw,qh,area=map(int,stats[j])
            gap=max(0,qx-c,a-(qx+qw-1))
            if (2<=qw<=70 and 2<=qh<=65 and 4<=area<=1500 and gap<=bh*.65
                    and abs(float(centers[j][1])-float(centers[i][1]))<=bh*.25):
                a,b,c,d=min(a,qx),min(b,qy),max(c,qx+qw-1),max(d,qy+qh-1)
        e['evidence'].append({'source':'pixel_attribute_region','field':'weight',
            'bbox':[a/(width-1),b/(height-1),c/(width-1),d/(height-1)],
            'method':'isolated_text_near_measured_stroke','distance_pixels':round(distance,3)})
