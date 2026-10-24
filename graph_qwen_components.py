"""Associate measured ink components with figures without graph templates."""
import math
import networkx as nx


def assign_components(graphs,groups,*,equal_counts=False):
    """Require a full, spatially unique figure/component assignment."""
    if len(groups)!=len(graphs):return None
    components=list(groups);matching=nx.Graph()
    for i,g in enumerate(graphs):
        a,b,c,d=g['bbox'];center=((a+c)/2,(b+d)/2)
        for key in components:
            points=groups[key]
            if equal_counts and len(points)!=len(g['vertices']):continue
            if not .5<=len(points)/len(g['vertices'])<=2:continue
            pc=((min(p['x'] for p in points)+max(p['x'] for p in points))/2,
                (min(p['y'] for p in points)+max(p['y'] for p in points))/2)
            distance=math.dist(center,pc)
            if distance<=.18 and all(a-.08<=p['x']<=c+.08 and b-.08<=p['y']<=d+.08 for p in points):
                matching.add_edge(('g',i),('p',key),weight=distance)
    best=nx.min_weight_matching(matching)
    if len(best)!=len(graphs):return None
    cost=sum(matching[a][b]['weight'] for a,b in best)
    for a,b in best:
        weight=matching[a][b]['weight'];matching.remove_edge(a,b)
        other=nx.min_weight_matching(matching)
        ambiguous=(len(other)==len(graphs) and
            sum(matching[u][v]['weight'] for u,v in other)-cost<.06)
        matching.add_edge(a,b,weight=weight)
        if ambiguous:return None
    assigned={}
    for a,b in best:
        if a[0]=='p':a,b=b,a
        assigned[a[1]]=b[1]
    return assigned


def ordered_components(groups,*,min_extent=.03):
    """A provisional reading order requires physically separate figure hulls."""
    boxes={key:(min(p['x'] for p in ps),min(p['y'] for p in ps),
                max(p['x'] for p in ps),max(p['y'] for p in ps)) for key,ps in groups.items()}
    if any(c-a<min_extent or d-b<min_extent for a,b,c,d in boxes.values()):return None
    rows=[]
    for key,(a,b,c,d) in sorted(boxes.items(),key=lambda item:(item[1][1]+item[1][3])/2):
        for row in rows:
            _,rb,_,rd=boxes[row[0]]
            if min(d,rd)-max(b,rb)>=.5*min(d-b,rd-rb):
                row.append(key);break
        else:rows.append([key])
    ordered=[]
    for row in rows:
        row.sort(key=lambda key:boxes[key][0])
        if any(boxes[b][0]-boxes[a][2]<.02 for a,b in zip(row,row[1:])):return None
        ordered.extend(row)
    for ri,row in enumerate(rows[1:],1):
        if min(boxes[k][1] for k in row)-max(boxes[k][3] for k in rows[ri-1])<.02:return None
    return dict(enumerate(ordered))


def reconcile_component_inventory(image,graphs):
    """Reconcile per-figure counts, preserving labels on uniquely matched disks."""
    import copy
    from collections import defaultdict
    import cv2
    import numpy as np
    from graph_qwen_gradient_markers import gradient_markers
    from graph_line_tracer import _foreground
    from graph_schema import canonical_graph
    from graph_qwen_geometry import _rebase_refined_paths
    if (len(graphs)<2 or any(type(g['directed']) is not bool or g['weighted'] is not False
            for g in graphs)):
        return graphs,[]
    points=gradient_markers(image);groups=defaultdict(list)
    hollow_repair=False
    if not points:
        from graph_qwen_ring_markers import ring_markers
        rings=ring_markers(image)
        if len(rings)>sum(len(g['vertices']) for g in graphs):
            points=rings;hollow_repair=True
    if not points or len(points)>48 or any('component' not in p for p in points):return graphs,[]
    for p in points:groups[p['component']].append(p)
    if len(groups)!=len(graphs) or any(len(ps)<3 for ps in groups.values()):return graphs,[]
    assigned=assign_components(graphs,groups)
    provisional=assigned is None
    if provisional:assigned=ordered_components(groups)
    if assigned is None or (not provisional and all(len(g['vertices'])==len(groups[assigned[i]]) for i,g in enumerate(graphs))):
        return graphs,[]
    ink=_foreground(np.asarray(image))
    depth=cv2.distanceTransform(ink,cv2.DIST_L2,3)
    width,height=image.size;output=[];notes=['component_frame_reading_order_provisional'] if provisional else []
    if hollow_repair:notes.append('native_hollow_component_count_repair')
    for i,old in enumerate(graphs):
        ps=sorted(groups[assigned[i]],key=lambda p:(p['y'],p['x']))
        normalized=[]
        for v in old['vertices']:
            q=[]
            for c in ('x','y'):
                lo=min(n[c] for n in old['vertices']);hi=max(n[c] for n in old['vertices'])
                a=min(p[c] for p in ps);b=max(p[c] for p in ps)
                q.append(a+(v[c]-lo)/(hi-lo)*(b-a) if hi>lo else (a+b)/2)
            normalized.append(q)
        matching=nx.Graph()
        for vi,q in enumerate(normalized):
            for pi,p in enumerate(ps):
                distance=math.dist(q,(p['x'],p['y']))
                if distance<=.06:matching.add_edge(('v',vi),('p',pi),weight=distance)
        matches=nx.min_weight_matching(matching);mapped={};selected=set()
        for a,b in matches:
            if a[0]=='p':a,b=b,a
            mapped[b[1]]=old['vertices'][a[1]];selected.add(a[1])
        # A filled mark missed by the shaded profile must not be silently
        # deleted. Thin unmarked crossings and bare curves have no disk core.
        for vi,q in enumerate(normalized):
            if vi in selected:continue
            x,y=round(q[0]*(width-1)),round(q[1]*(height-1))
            core=depth[max(0,y-6):y+7,max(0,x-6):x+7]
            marker_radius=sorted(p.get('radius_pixels',8.) for p in ps)[len(ps)//2]
            # Filled arrowheads are smaller than these measured shaded disks;
            # their ink alone must not keep a hallucinated graph vertex.
            if core.size and float(core.max())>=max(5,marker_radius*.65):
                return graphs,['component_inventory_abstained:unmatched_filled_ink']
        g=copy.deepcopy(old);g['vertices']=[];used={v['id'] for v in old['vertices']};proof=[]
        for pi,p in enumerate(ps):
            prior=mapped.get(pi)
            if prior is not None:vid=prior['id'];label=prior['label']
            else:
                number=len(used)+1;vid=f'v{number}';label=None
                while vid in used:
                    number+=1;vid=f'v{number}'
                used.add(vid)
            g['vertices'].append({'id':vid,'label':label,'x':p['x'],'y':p['y']})
            proof.append({'source':'component_circle_inventory','vertex':vid,
                'pixel_position':[p['x'],p['y']],'native_component':p['component'],
                'radius_pixels':p.get('radius_pixels'),'marker_profile':p.get('marker_profile')})
        retained={v['id'] for v in g['vertices']}
        g['edges']=[e for e in g['edges'] if e['from'] in retained and e['to'] in retained]
        g.setdefault('node_review',{})['observed_vertices']=copy.deepcopy(old['vertices'])
        if hollow_repair and any(v['label'] is not None for v in old['vertices']) and (
                len(selected)!=len(old['vertices']) or len(ps)!=len(old['vertices'])):
            g['node_review']['component_label_rebinding']=True
        g['node_review']['component_inventory_observations']={'before':len(old['vertices']),
            'measured':len(ps),'frame_reading_order_provisional':provisional,'discarded_edge_proposals':[e for e in old['edges'] if e not in g['edges']]}
        separation=[min((math.hypot((p['x']-q['x'])*(width-1),(p['y']-q['y'])*(height-1))
            for q in ps if q is not p),default=60.) for p in ps]
        margin=max(34,min(120,sorted(separation)[len(separation)//2]*.62))
        g['bbox']=[max(0,min(p['x'] for p in ps)-margin/(width-1)),
            max(0,min(p['y'] for p in ps)-margin/(height-1)),
            min(1,max(p['x'] for p in ps)+margin/(width-1)),
            min(1,max(p['y'] for p in ps)+margin/(height-1))]
        boxes=[p['component_bbox'] for p in ps if p.get('component_bbox')]
        if boxes:
            g['bbox']=[max(0,min(g['bbox'][0],min(b[0] for b in boxes)-8/(width-1))),
                max(0,min(g['bbox'][1],min(b[1] for b in boxes)-8/(height-1))),
                min(1,max(g['bbox'][2],max(b[2] for b in boxes)+8/(width-1))),
                min(1,max(g['bbox'][3],max(b[3] for b in boxes)+8/(height-1)))]
        g['node_position_evidence']=proof;g['node_complete']=False;g['complete']=False
        _rebase_refined_paths([g],[old]);output.append(canonical_graph(g))
        if len(old['vertices'])!=len(ps):
            notes.append(f"component_node_count_reconciled:{g['id']}:{len(old['vertices'])}:{len(ps)}")
    return output,notes


def native_first_context(image):
    """A coordinate-free first-read candidate for separated shaded figures."""
    from collections import defaultdict
    import cv2
    import numpy as np
    from graph_qwen_gradient_markers import gradient_markers
    from graph_qwen_markers import marker_context
    from graph_glm_adapter import marker_overlay
    from graph_line_tracer import _foreground
    points=gradient_markers(image);groups=defaultdict(list)
    if not 4<=len(points)<=48 or any('component' not in p for p in points):return None
    for p in points:groups[p['component']].append(p)
    if not 2<=len(groups)<=8 or any(len(ps)<3 for ps in groups.values()):return None
    order=ordered_components(groups)
    if order is None:return None
    broad=marker_context(image)
    if broad is None:return None
    rgb=np.asarray(image);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    _,components=cv2.connectedComponents(_foreground(rgb)|(np.uint8(gray<230)*255),8)
    shaded_only=all(p.get('std',0)>=18 for p in points)
    common_radius=float(np.median([p['radius_pixels'] for p in points]))
    opened=cv2.morphologyEx(np.uint8(gray<230)*255,cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(13,13)))
    _,head_labels,head_stats,_=cv2.connectedComponentsWithStats(opened,8)
    rejected_heads=[]
    width,height=image.size;other=defaultdict(list)
    for p in broad['strong_markers']:
        if any(math.dist((p['x'],p['y']),(q['x'],q['y']))<.012 for q in points):continue
        x,y=round(p['x']*(width-1)),round(p['y']*(height-1));key=int(components[y,x])
        if key in groups:
            if shaded_only and _small_flat_asymmetric_blob(gray,head_labels,head_stats,x,y,common_radius):
                rejected_heads.append({'x':p['x'],'y':p['y'],'source':'flat_small_asymmetric_ink_inside_shaded_figure'})
                continue
            return None
        other[key].append(p)
    for key,ps in other.items():
        if key and len(ps)>=3 and ((max(p['x'] for p in ps)-min(p['x'] for p in ps))*width>50
                and (max(p['y'] for p in ps)-min(p['y'] for p in ps))*height>50):return None
    pool=[]
    for i in range(len(groups)):
        for p in sorted(groups[order[i]],key=lambda p:(p['y'],p['x'])):
            pool.append({**p,'id':f'p{len(pool)+1}'})
    return {'markers':pool,'strong_markers':pool,'image':marker_overlay(image,pool),
            'source':'native_shaded_components',
            **({'native_small_flat_head_rejections':rejected_heads} if rejected_heads else {})}


def _small_flat_asymmetric_blob(gray,labels,stats,x,y,reference_radius):
    """Small flat triangular heads must not veto large shaded-circle frames."""
    import numpy as np
    key=int(labels[y,x])
    if not key:return False
    left,top,width,height,area=map(int,stats[key])
    if not (12<=width<=65 and 12<=height<=65 and (width+height)/4<reference_radius*.8):return False
    core=gray[max(0,y-3):y+4,max(0,x-3):x+4]
    if not core.size or np.median(core)>=60 or np.std(core)>10:return False
    yy,xx=np.where(labels[top:top+height,left:left+width]==key)
    if len(xx)<20:return False
    xy=np.column_stack((xx,yy));maximum=0.
    for angle in np.linspace(0,np.pi,16,endpoint=False):
        projected=xy@np.array([np.cos(angle),np.sin(angle)]);centered=projected-projected.mean()
        skew=abs(float(np.mean(centered**3)/max(float(np.mean(centered*centered))**1.5,1e-9)))
        maximum=max(maximum,skew)
    return maximum>=.1
