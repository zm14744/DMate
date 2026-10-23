"""CPU global route selection; no learned VisAdj model or invented edges."""
from __future__ import annotations
import copy
import math
from collections import defaultdict
from graph_schema import canonical_graph, path_points

MAX_CANDIDATES = 96


def _samples(path, count=32):
    lengths = [math.dist(a,b) for a,b in zip(path,path[1:])]
    total = sum(lengths)
    if total <= 0: return []
    output=[]
    for n in range(count):
        distance=total*(n+.5)/count
        for k,length in enumerate(lengths):
            if distance <= length:
                t=distance/max(length,1e-9)
                output.append([path[k][0]*(1-t)+path[k+1][0]*t,
                               path[k][1]*(1-t)+path[k+1][1]*t]); break
            distance-=length
    return output


def route_overlap(a,b,tolerance=.003):
    aa,bb=_samples(a),_samples(b)
    if not aa or not bb: return 0.
    def distance(p,line):
        best=10.
        for u,v in zip(line,line[1:]):
            dx,dy=v[0]-u[0],v[1]-u[1]
            t=max(0.,min(1.,((p[0]-u[0])*dx+(p[1]-u[1])*dy)/max(dx*dx+dy*dy,1e-12)))
            best=min(best,math.hypot(p[0]-u[0]-t*dx,p[1]-u[1]-t*dy))
        return best
    return min(sum(distance(p,b)<tolerance for p in aa)/len(aa),
               sum(distance(p,a)<tolerance for p in bb)/len(bb))


def _intermediate_nodes(path,edge,nodes,radius=.009):
    samples=_samples(path,80)
    return [v['id'] for v in nodes if v['id'] not in (edge['from'],edge['to'])
            and v.get('x') is not None and v.get('y') is not None
            and any(math.dist(p,(v['x'],v['y']))<radius for p in samples[4:-4])]


def _wrong_path_endpoints(edge,nodes,tolerance=.06):
    by_id={v['id']:v for v in nodes}
    a,b=by_id[edge['from']],by_id[edge['to']]
    if not edge['path'] or any(v.get(k) is None for v in (a,b) for k in ('x','y')):
        return False
    u,v=(a['x'],a['y']),(b['x'],b['y'])
    first,last=edge['path'][0],edge['path'][-1]
    return min(max(math.dist(first,u),math.dist(last,v)),
               max(math.dist(first,v),math.dist(last,u)))>tolerance


def recover_relations(graph,traces,*,review=None):
    """Reselect competing routes after new evidence, preserving rejected audit.

    Relations are shared-ink conflicts and real-vertex intersections. Per-node
    reciprocal observations and pixel continuity supply local evidence. No degree
    or template completion. Reviews address IDs so parallel edges stay separate.
    """
    graph=canonical_graph(graph)
    nodes=graph['vertices']; ids={v['id'] for v in nodes}; candidates=[]
    for edge in graph['edges']:
        c=copy.deepcopy(edge)
        sources={e.get('source') for e in c.get('evidence',[]) if isinstance(e,dict)}
        # Carried TRACE candidates retain their provenance through REVIEW.
        # They must not acquire visual confidence merely by entering this list.
        c['_visual']=not ('pixels' in sources and not sources.intersection(
            {'node_read','qwen_review_new_stroke','qwen_image_read'}))
        c['_pixel']=0.; candidates.append(c)
    for ti,trace in enumerate(traces[:MAX_CANDIDATES]):
        if trace.get('from') not in ids or trace.get('to') not in ids: continue
        path=path_points(trace.get('path'))
        if not path: continue
        pair={trace['from'],trace['to']}
        matches=[c for c in candidates if {c['from'],c['to']}==pair and c['path']
                 and route_overlap(c['path'],path)>=.70]
        no_path=[c for c in candidates if {c['from'],c['to']}==pair and not c['path']]
        same_pair=[c for c in candidates if {c['from'],c['to']}==pair]
        pair_traces=[t for t in traces if {t.get('from'),t.get('to')}==pair]
        if not matches and len(no_path)==len(same_pair)==len(pair_traces)==1: matches=no_path
        if len(matches)==1:
            c=matches[0]; c['path']=path
        else:
            c={'id':f'pixel_{ti+1}','from':trace['from'],'to':trace['to'],
               'direction':'undirected' if graph['directed'] is False else 'unknown',
               'weight':None,'edge_label':None,'path':path,'multiplicity':1,
               'style':trace.get('style','unknown'),'color':'unknown','evidence':[],
               '_visual':False,'_pixel':0.}
            candidates.append(c)
        c['_pixel']=max(c['_pixel'],min(1.,max(0.,float(trace.get('score',0)))))
        c['evidence'].append({'source':'pixels','method':trace.get('method'),'score':trace.get('score')})
        if trace.get('arrow_candidate'):
            c['_arrow']=trace['arrow_candidate']
            # Review payloads must receive arrow evidence too. Private _arrow
            # fields alone were stripped before the Qwen REVIEW request.
            c['evidence'].append({'source':'arrow_pixels',**trace['arrow_candidate']})
        if trace.get('arrow_ambiguous'): c['_arrow_ambiguous']=True
    candidates=candidates[:MAX_CANDIDATES]
    used=set()
    for n,c in enumerate(candidates):
        if c['id'] in used: c['id']=f"route_{n+1}_{c['id']}"
        used.add(c['id'])
    scores=[]; conflicts=defaultdict(list)
    for i,c in enumerate(candidates):
        c['_blocked']=bool(_intermediate_nodes(c['path'],c,nodes)) if c['path'] else False
        c['_endpoint_mismatch']=_wrong_path_endpoints(c,nodes)
        c['_blocked'] |= c['_endpoint_mismatch']
        reciprocal=len({e.get('vertex') for e in c['evidence'] if isinstance(e,dict)
                        and e.get('source')=='node_read' and e.get('vertex') in (c['from'],c['to'])})>=2
        score=.25*int(c['_visual'])+.55*c['_pixel']+.18*int(reciprocal)
        decision=(review or {}).get(c['id'],{})
        if decision.get('visible') is False: c['_blocked']=True
        if decision.get('visible') is True and c['path'] and not c['_blocked']:
            score=max(score,.92)
            c['evidence'].append({'source':'local_review','visible':True})
            direction=decision.get('direction')
            if direction=='unknown': c['direction']='unknown'
            if direction in ('forward','reverse','undirected'):
                if direction=='reverse': c['from'],c['to']=c['to'],c['from']
                c['direction']='forward' if direction!='undirected' else 'undirected'
            for key in ('weight','edge_label','style','color'):
                if key in decision: c[key]=decision[key]
        arrow=c.get('_arrow')
        if arrow and c['direction']=='forward' and (arrow['from'],arrow['to'])!=(c['from'],c['to']):
            # A generic visual "visible" decision cannot erase contradictory
            # arrow pixels. Preserve both observations and keep direction open.
            c['evidence'].append({'source':'direction_conflict','visual_from':c['from'],
                                  'visual_to':c['to'],'pixel_from':arrow['from'],'pixel_to':arrow['to']})
            c['direction']='unknown'; score-=.10
        if c.get('_arrow_ambiguous') and graph['directed'] is not False and decision.get('visible') is not True:
            c['direction']='unknown'
        if ((graph['directed'] is False and c['direction']=='forward')
                or (graph['directed'] is True and c['direction']=='undirected')):
            c['evidence'].append({'source':'graph_direction_conflict','observed_direction':c['direction'],
                                  'graph_directed':graph['directed']})
            c['direction']='unknown'
        if c['_blocked']: score=-1.
        scores.append(score)
        for j,old in enumerate(candidates[:i]):
            if c['path'] and old['path'] and route_overlap(c['path'],old['path'])>=.72:
                conflicts[i].append(j); conflicts[j].append(i)
    # Bounded coordinate ascent on weighted mutually exclusive route variables.
    chosen=set()
    for _ in range(3):
        changed=False
        for i in sorted(range(len(candidates)),key=lambda n:(-scores[n],candidates[n]['id'])):
            if scores[i]<.72: continue
            occupied=chosen.intersection(conflicts[i])
            if i not in chosen and scores[i]>sum(scores[j] for j in occupied)+.001:
                chosen.difference_update(occupied); chosen.add(i); changed=True
        if not changed: break
    edges=[]; audit=[]; unresolved=False
    for i,c in enumerate(candidates):
        contradicted=c['_blocked'] or bool(chosen.intersection(conflicts[i]))
        selected=i in chosen
        status='rejected' if contradicted and not selected else ('accepted' if selected else 'pending')
        if status=='accepted' and (c['direction']=='unknown' or (graph['weighted'] is True and c['weight'] is None)):
            status='pending'
        audit.append({'id':c['id'],'status':status,'score':round(scores[i],4),
                      'conflicts':[candidates[j]['id'] for j in conflicts[i]],
                      'blocked_by_vertex':c['_blocked'],'path':c['path'],'evidence':c['evidence']})
        audit[-1]['endpoint_mismatch']=c['_endpoint_mismatch']
        if status=='rejected': continue
        unresolved |= status=='pending'; c['status']=status
        edges.append({k:v for k,v in c.items() if not k.startswith('_')})
    graph['edges']=edges
    if unresolved: graph['uncertain_edges'].append('unresolved_routes')
    # A candidate set cannot certify that no edges were missed.
    graph['complete']=bool(graph.get('inventory_reviewed') is True and graph.get('node_complete') is True
                           and not unresolved and not graph['uncertain_edges'])
    graph=canonical_graph(graph); graph['relation_audit']=audit
    graph['_candidates']=[{k:v for k,v in c.items() if not k.startswith('_')} for c in candidates]
    return graph
