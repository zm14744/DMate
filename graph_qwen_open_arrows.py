"""Paired original-ink wings distinguish open arrowheads from filled triangles."""
import math
import cv2
import numpy as np
from graph_qwen_text_inventory import _key


def _endpoint_wings(distance,node,other,path,radius,size,*,filled=False):
    width,height=size;line=np.asarray(path)*[width-1,height-1]
    if np.linalg.norm(line[0]-node)>np.linalg.norm(line[-1]-node):line=line[::-1]
    along=next((p for p in line if np.linalg.norm(p-node)>radius+14),other)
    tangent=along-node;tangent/=max(float(np.linalg.norm(tangent)),1e-9)
    normal=np.array([-tangent[1],tangent[0]]);best=(-1,None)
    for advance in np.arange(radius+2 if filled else max(1,radius-3),radius+17,1):
        for offset in (-2,0,2):
            tip=node+tangent*advance+normal*offset
            for degrees in (25,35,45,55):
                angle=math.radians(degrees)
                for length in (8,11,14,18):
                    supports=[]
                    for side in (-1,1):
                        wing=tangent*math.cos(angle)+normal*side*math.sin(angle)
                        xy=np.rint(tip+np.linspace(4,length,8)[:,None]*wing).astype('int32')
                        if (xy<0).any() or (xy[:,0]>=width).any() or (xy[:,1]>=height).any():supports.append(0.);continue
                        supports.append(float(np.mean(distance[xy[:,1],xy[:,0]]<=.95)))
                    score=min(supports)
                    if score>best[0]:best=(score,{'tip':tip.tolist(),'angle':degrees,'length':length,'supports':supports})
    return best


def prepare_open_arrows(image,graphs,*,allow_filled=False):
    directed=[(i,g) for i,g in enumerate(graphs) if g['directed'] is True]
    if not directed or any(g['weighted'] is not False for _,g in directed):return None
    for _,g in directed:
        proof=g.get('node_position_evidence',[])
        allowed=('native_hollow_size_consensus','native_filled_disk') if allow_filled else ('native_hollow_size_consensus',)
        if len(proof)!=len(g['vertices']) or any(p.get('marker_profile') not in allowed or not p.get('radius_pixels') for p in proof):return None
    targets=[(i,g,e) for i,g in directed for e in g['edges'] if e['from']!=e['to']]
    if not 1<=len(targets)<=48 or any(not e['path'] for _,_,e in targets):return None
    from graph_line_tracer import _foreground
    ink=_foreground(np.asarray(image));width,height=image.size
    for g in graphs:
        proof={p['vertex']:p for p in g.get('node_position_evidence',[])}
        for v in g['vertices']:
            radius=proof.get(v['id'],{}).get('radius_pixels')
            if radius:cv2.circle(ink,(round(v['x']*(width-1)),round(v['y']*(height-1))),math.ceil(radius+1),0,-1)
    distance=cv2.distanceTransform(np.uint8(ink==0),cv2.DIST_L2,3);items=[]
    for gi,g,e in targets:
        positions={v['id']:np.array([v['x']*(width-1),v['y']*(height-1)]) for v in g['vertices']}
        radii={p['vertex']:p['radius_pixels'] for p in g['node_position_evidence']}
        filled={p['vertex']:p.get('marker_profile')=='native_filled_disk' for p in g['node_position_evidence']}
        a,b=positions[e['from']],positions[e['to']]
        from_read=_endpoint_wings(distance,a,b,e['path'],radii[e['from']],image.size,filled=filled[e['from']])
        to_read=_endpoint_wings(distance,b,a,e['path'],radii[e['to']],image.size,filled=filled[e['to']])
        resolved=max(from_read[0],to_read[0])>=.875 and abs(from_read[0]-to_read[0])>=.25
        chosen=from_read if from_read[0]>to_read[0] else to_read
        tip=chosen[1]['tip'];x,y=map(round,tip);tangent=(b-a)/max(float(np.linalg.norm(b-a)),1e-9)
        items.append({'key':_key(len(items)),'graph_index':gi,'id':e['id'],
            'rect':[max(0,x-25),max(0,y-25),min(width,x+26),min(height,y+26)],
            'tangent':tangent.tolist(),'axis_resolved':bool(resolved),'native_reverse':from_read[0]>to_read[0],
            'native_open_wings':{'from_score':from_read[0],'to_score':to_read[0],
                'from_evidence':from_read[1],'to_evidence':to_read[1]}})
    if not any(item['axis_resolved'] for item in items):return None
    from graph_qwen_arrows import arrow_subset
    return arrow_subset(image,{'graphs':graphs},items,graphs)
