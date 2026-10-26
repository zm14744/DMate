"""Independent, edge-instance scoring. Never used as a recognition prompt.

Topology P/R/F1 includes endpoint identity, direction and multiplicity. The
stricter whole-image score additionally requires weights, edge names and styles.
Operational failures must be filtered by the caller, never scored as bad edges.
"""
from __future__ import annotations
from collections import Counter
from decimal import Decimal,InvalidOperation
import math
import re
import unicodedata
import networkx as nx


def label(value):
    text=unicodedata.normalize('NFKC',str(value or ''))
    return re.sub(r'[\\{}_$()\s]','',text).casefold()


def figure_name(value):
    return re.sub(r'^(?:figure|图)\s*','',label(value))


def weight(value):
    if value is None:return None
    try:return str(Decimal(str(value)).normalize())
    except InvalidOperation:return str(value)


def rate(numerator,denominator):
    return numerator/denominator if denominator else None


def prf(tp,predicted,expected):
    return {'precision':rate(tp,predicted),'recall':rate(tp,expected),
            'f1':2*tp/(predicted+expected) if predicted+expected else 1.}


def _aliases(want,got):
    expected=want.get('vertices',[]);actual=got.get('vertices',[])
    edges=nx.Graph()
    for i,v in enumerate(actual):
        for j,u in enumerate(expected):
            if u.get('label') is not None:
                if label(v.get('label') or v['id'])!=label(u['label']):continue
                distance=0.
            elif all(type(p.get(k)) in (int,float) and math.isfinite(p[k]) for p in (u,v) for k in ('x','y')):
                distance=math.dist((u['x'],u['y']),(v['x'],v['y']))
                if distance>.045:continue
            else:continue
            edges.add_edge(('actual',i),('expected',j),weight=distance)
    aliases={}
    for a,b in nx.min_weight_matching(edges):
        if a[0]=='expected':a,b=b,a
        aliases[actual[a[1]]['id']]=expected[b[1]]['id']
    return aliases


def _instances(graph,aliases=None,*,directed=None):
    aliases=aliases if aliases is not None else {v['id']:v['id'] for v in graph.get('vertices',[])}
    directed=graph.get('directed') is True if directed is None else directed
    output=[]
    for edge in graph.get('edges',[]):
        a,b=(aliases.get(edge.get(k),'__unmatched:'+str(edge.get(k))) for k in ('from','to'))
        if not directed:a,b=sorted((a,b))
        direction=edge.get('direction','unknown')
        count=edge.get('multiplicity',1)
        count=count if type(count) is int and 1<=count<=32 else 1
        for _ in range(count):
            output.append((a,b,direction,weight(edge.get('weight')),label(edge.get('edge_label')),
                           edge.get('style','unknown')))
    return output


def compare_graphs(expected,actual,*,reference_status='complete'):
    observed={'actual_vertices':sum(len(g.get('vertices',[])) for g in actual),
              'actual_edges':sum(len(_instances(g)) for g in actual),
              'expected_graphs':len(expected),'actual_graphs':len(actual)}
    if reference_status!='complete':return {**observed,'status':'unverified_reference'}
    vertex_tp=0;vertex_expected=0;edge_tp=0;edge_expected=0;strict_tp=0
    direction_correct=0;direction_trials=0;direction_expected=0
    weights_correct=0;weights_expected=0;weight_trials=0;parallel_correct=0;parallel_trials=0
    pairs_correct=0;pairs_trials=0;missing=[];extra=[];wrong_endpoints=0
    strict_missing=[];strict_extra=[];missing_vertices=[];extra_vertices=[]
    whole=len(expected)==len(actual);figure_checks=[]
    label_sets=[frozenset(label(v.get('label')) for v in g['vertices']) for g in expected]
    for index,want in enumerate(expected):
        got=actual[index] if index<len(actual) else {'vertices':[],'edges':[]}
        aliases=_aliases(want,got);vertex_tp+=len(aliases);vertex_expected+=len(want['vertices'])
        missing_vertices.extend({'graph_index':index,'vertex':v['id']} for v in want['vertices'] if v['id'] not in aliases.values())
        extra_vertices.extend({'graph_index':index,'vertex':v['id']} for v in got.get('vertices',[]) if v['id'] not in aliases)
        inventory=len(aliases)==len(want['vertices'])==len(got.get('vertices',[]))
        directed=want.get('directed') is True
        gold=_instances(want,directed=directed);seen=_instances(got,aliases,directed=directed)
        eg,ea=Counter(e[:3] for e in gold),Counter(e[:3] for e in seen)
        full_gold,full_actual=Counter(gold),Counter(seen)
        tp=sum((eg&ea).values());edge_tp+=tp;edge_expected+=len(gold)
        strict_tp+=sum((full_gold&full_actual).values())
        strict_missing.extend({'graph_index':index,'edge':list(k),'count':v} for k,v in (full_gold-full_actual).items())
        strict_extra.extend({'graph_index':index,'edge':list(k),'count':v} for k,v in (full_actual-full_gold).items())
        missing.extend({'graph_index':index,'edge':list(k),'count':v} for k,v in (eg-ea).items())
        extra.extend({'graph_index':index,'edge':list(k),'count':v} for k,v in (ea-eg).items())
        endpoint_gold=Counter(tuple(sorted(e[:2])) for e in gold)
        endpoint_actual=Counter(tuple(sorted(e[:2])) for e in seen)
        if directed:
            direction_correct+=tp;direction_expected+=len(gold)
            direction_trials+=sum((endpoint_gold&endpoint_actual).values())
        for pair in endpoint_gold.keys()|endpoint_actual.keys():
            equal=endpoint_gold[pair]==endpoint_actual[pair]
            pairs_correct+=int(equal);pairs_trials+=1
            if max(endpoint_gold[pair],endpoint_actual[pair])>=2:
                parallel_correct+=int(equal);parallel_trials+=1
        wrong_endpoints+=sum(n for k,n in (ea-eg).items() if tuple(sorted(k[:2])) not in endpoint_gold)
        wg=Counter(e[:4] for e in gold if e[3] is not None)
        wa=Counter(e[:4] for e in seen if e[3] is not None)
        weights_correct+=sum((wg&wa).values());weights_expected+=sum(wg.values())
        weight_trials+=sum((Counter(e[:3] for e in gold if e[3] is not None)&ea).values())
        ids=[e.get('id') for e in got.get('edges',[])]
        independent=all(ids) and len(set(ids))==len(ids) and all(e.get('multiplicity',1)==1 for e in got.get('edges',[]))
        if not ids:independent=True
        multigraph=want.get('multigraph')
        if type(multigraph) is not bool:
            multigraph=any(n>1 for n in endpoint_gold.values()) or any(a==b for a,b in endpoint_gold)
        types=all(got.get(k) is want.get(k) for k in ('directed','weighted')) and got.get('multigraph') is multigraph
        whole &= inventory and full_gold==full_actual and independent and types
        located=all(v.get('x') is not None and v.get('y') is not None for v in want['vertices'])
        unique_labels=(all(v.get('label') is not None for v in want['vertices'])
                       and label_sets.count(label_sets[index])==1)
        if want.get('name_verified'):
            name=figure_name(got.get('name'))
            name_equal=(figure_name(want['name'])==name or
                        bool(want.get('panel_label') and name==figure_name(want['panel_label'])))
            figure_checks.append(inventory and name_equal)
            whole &= figure_checks[-1]
        elif located or unique_labels or len(expected)==1:figure_checks.append(inventory)
        else:figure_checks.append(None)
    for index,got in enumerate(actual[len(expected):],len(expected)):
        extra.extend({'graph_index':index,'edge':list(e[:3]),'count':1} for e in _instances(got))
        extra_vertices.extend({'graph_index':index,'vertex':v['id']} for v in got.get('vertices',[]))
    actual_edges=observed['actual_edges'];actual_vertices=observed['actual_vertices']
    figures=(False if len(expected)!=len(actual) else
             None if any(v is None for v in figure_checks) else all(figure_checks))
    return {**observed,'status':'scored','vertex_tp':vertex_tp,'expected_vertices':vertex_expected,
            'missing_vertices':vertex_expected-vertex_tp,'extra_vertices':actual_vertices-vertex_tp,
            'edge_tp':edge_tp,'expected_edges':edge_expected,'missing_edges':edge_expected-edge_tp,
            'extra_edges':actual_edges-edge_tp,'wrong_endpoint_instances':wrong_endpoints,
            'edge_set':prf(edge_tp,actual_edges,edge_expected),'strict_edge_tp':strict_tp,
            'direction_correct':direction_correct,'direction_trials':direction_trials,
            'direction_expected':direction_expected,'direction_accuracy':rate(direction_correct,direction_trials),
            'wrong_direction_instances':direction_trials-direction_correct,
            'direction_recall':rate(direction_correct,direction_expected),
            'parallel_correct':parallel_correct,'parallel_trials':parallel_trials,
            'parallel_count_accuracy':rate(parallel_correct,parallel_trials),
            'pair_count_correct':pairs_correct,'pair_count_trials':pairs_trials,
            'weights_correct':weights_correct,'weights_expected':weights_expected,
            'weight_trials':weight_trials,'weight_match_accuracy':rate(weights_correct,weight_trials),
            'weight_recall':rate(weights_correct,weights_expected),
            'figure_count_correct':len(expected)==len(actual),'figure_order_correct':figures,
            'whole_structure_correct':bool(whole),'missing_edge_instances':missing,'extra_edge_instances':extra,
            'missing_strict_edge_instances':strict_missing,'extra_strict_edge_instances':strict_extra,
            'missing_vertex_identities':missing_vertices,'extra_vertex_identities':extra_vertices}
