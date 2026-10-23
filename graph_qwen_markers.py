"""Measured marker context for a bounded Qwen inventory repair.

Candidates are image measurements, not a vertex inventory or reference answer.
Qwen must select actual vertices; arbitrary unlabeled crossings stay excluded.
"""
from __future__ import annotations
import copy
import math


def marker_context(image):
    import cv2
    import numpy as np
    from graph_staged import refine_node_positions
    from graph_glm_adapter import marker_inventory, marker_overlay
    from graph_qwen_geometry import connected_ring_markers
    rgb=np.asarray(image)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    colored=[]
    # Different edge/node hues can share one large connected component in
    # the broad saturation mask. Separate hues before measuring round marks.
    # Closing is used only to propose circles occluded by crossing ink; the
    # original picture remains the authority for accepting a vertex.
    for hue in range(0,180,10):
        mask=cv2.inRange(hsv,(max(0,hue-7),85,60),(min(179,hue+7),255,255))
        for diameter in (3,7,15):
            closed=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(diameter,diameter)))
            contours,_=cv2.findContours(closed,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x,y,w,h=cv2.boundingRect(contour)
                area=cv2.contourArea(contour);perimeter=cv2.arcLength(contour,True)
                if not(7<=w<=90 and 7<=h<=90 and .8<=w/h<=1.25
                       and .62<=area/(w*h)<=.87
                       and 4*math.pi*area/max(perimeter*perimeter,1)>=.78):continue
                cx,cy=x+w//2,y+h//2;radius=max(1,min(w,h)//5)
                core=hsv[max(0,cy-radius):cy+radius+1,max(0,cx-radius):cx+radius+1]
                if not core.size or np.mean((core[:,:,1]>85)&(core[:,:,2]>60))<.8:continue
                colored.append({'x':(x+w/2)/(image.width-1),'y':(y+h/2)/(image.height-1)})
    detected=[]
    refine_node_positions(image,[],partial=True,candidate_sink=detected)
    pool=marker_inventory(colored+connected_ring_markers(image)+detected)
    if len(pool)<3:return None
    for point in pool:point['id']='p'+point['id'][1:]
    from graph_black_disks import _black_disk_centers
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    solid=colored+[{'x':x/(image.width-1),'y':y/(image.height-1)}
                   for x,y,_,_ in _black_disk_centers(gray)]
    strong=[]
    for point in marker_inventory(solid):
        nearest=min(pool,key=lambda p:math.dist((p['x'],p['y']),(point['x'],point['y'])))
        if math.dist((nearest['x'],nearest['y']),(point['x'],point['y']))<.009:
            if nearest not in strong:strong.append(nearest)
    return {'markers':pool,'image':marker_overlay(image,pool),'strong_markers':strong}


def needs_inventory_repair(graphs, context):
    """Reserve the second call for a measured single-panel count conflict.

    This narrow gate protects already consistent inventories, directed graphs
    and the existing weighted-text profile. Measurements do not add vertices.
    """
    if not context or len(graphs)!=1:return False
    g=graphs[0]
    if g['directed'] is not False or g['weighted'] is not False:return False
    a,b,c,d=g['bbox']
    points=[p for p in context['strong_markers']
            if a-.06<=p['x']<=c+.06 and b-.06<=p['y']<=d+.06]
    observed=len(g['vertices']);measured=len(points)
    return bool(4<=measured<=48 and measured!=observed and .5<=measured/max(1,observed)<=2
                and max(p['x'] for p in points)-min(p['x'] for p in points)>.15
                and max(p['y'] for p in points)-min(p['y'] for p in points)>.1)


def ground_selected_markers(graphs, response, markers, *, image_size=None):
    """Bind only explicit, globally unique selections; retain all observations."""
    pool={p['id']:p for p in markers};selected={};used=set()
    raw_graphs={g['id']:g for g in response['graphs']}
    for graph in graphs:
        raw_vertices={v['id']:v for v in raw_graphs[graph['id']]['vertices']}
        for vertex in graph['vertices']:
            mid=raw_vertices[vertex['id']].get('marker_id')
            if mid is None:continue
            if not isinstance(mid,str) or mid not in pool or mid in used:
                raise ValueError('invalid_initial_marker_selection')
            selected[graph['id'],vertex['id']]=pool[mid];used.add(mid)
    for graph in graphs:
        old={v['id']:[v['x'],v['y']] for v in graph['vertices']}
        evidence=[]
        for vertex in graph['vertices']:
            point=selected.get((graph['id'],vertex['id']))
            if point is None:continue
            evidence.append({'source':'qwen_initial_marker_selection','vertex':vertex['id'],
                'marker_id':point['id'],'node_position':old[vertex['id']],
                'pixel_position':[point['x'],point['y']]})
            vertex['x'],vertex['y']=point['x'],point['y']
        graph['node_review']['initial_marker_selections']=copy.deepcopy(evidence)
        if len(evidence)==len(graph['vertices']):graph['node_position_evidence']=evidence
        positions={v['id']:[v['x'],v['y']] for v in graph['vertices']}
        if image_size and len(evidence)==len(graph['vertices']):
            width,height=image_size;points=list(positions.values())
            nearest=[min((math.hypot((x-a)*(width-1),(y-b)*(height-1))
                for j,(a,b) in enumerate(points) if i!=j),default=80.)
                for i,(x,y) in enumerate(points)]
            margin=max(34,min(120,sorted(nearest)[len(nearest)//2]*.62))
            a,b,c,d=graph['bbox']
            graph['bbox']=[max(0.,min(a,min(p[0] for p in points)-margin/(width-1))),
                max(0.,min(b,min(p[1] for p in points)-margin/(height-1))),
                min(1.,max(c,max(p[0] for p in points)+margin/(width-1))),
                min(1.,max(d,max(p[1] for p in points)+margin/(height-1)))]
        for edge in graph['edges']:
            path=edge['path'];a,b=old[edge['from']],old[edge['to']]
            u,v=positions[edge['from']],positions[edge['to']]
            if math.dist(path[0],a)+math.dist(path[-1],b)>math.dist(path[0],b)+math.dist(path[-1],a):
                a,b,u,v=b,a,v,u
            # Only endpoint measurements are substituted. Interior model
            # observations still need independent ink support downstream.
            original=copy.deepcopy(path)
            if math.dist(path[0],a)<.03:path[0]=u
            if math.dist(path[-1],b)<.03:path[-1]=v
            if path!=original:edge['evidence'].append({'source':'initial_marker_endpoints',
                                                       'observed_path':original})
    return graphs


MARKER_HINT='''
第二张是第一张原图的几何圆点候选辅助图；蓝框p编号不是原图文字。
候选可能包含字形或漏掉真点，不能照抄候选总数；只选原图真实图形顶点。
若真实顶点对应候选，在该vertex额外填写marker_id，并照抄该候选x/y（完整原图0到1000）。
未匹配候选的真实顶点仍按原图报告坐标，marker_id=null。不同图不得重复占用同一候选。
原图无节点名则label=null；贴在线旁的字母可能是edge_label，不能当顶点名或创造顶点。
边from/to使用真实选中顶点的id，不能使用没有选为顶点的辅助编号。
候选没有连接关系或方向答案；仍须逐笔画读第一张原图。
'''
