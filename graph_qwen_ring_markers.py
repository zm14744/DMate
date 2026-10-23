"""Scale-consistent native hollow markers, including disconnected circles.

Candidates supply positions and radii only. The caller still requires a full
count and unique spatial assignment before moving any observed graph vertex.
"""
import math
import cv2
import numpy as np


def ring_markers(image):
    from graph_line_tracer import _foreground,_paper_gray
    rgb=np.asarray(image);paper=_paper_gray(rgb)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY) if paper is None else paper
    contours,hierarchy=cv2.findContours(_foreground(rgb),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:return []
    points=[]
    for i,contour in enumerate(contours):
        parent=int(hierarchy[0,i,3])
        if parent<0:continue
        x,y,width,height=cv2.boundingRect(contour)
        area=cv2.contourArea(contour);perimeter=cv2.arcLength(contour,True)
        px,py,pw,ph=cv2.boundingRect(contours[parent])
        parent_area=cv2.contourArea(contours[parent]);parent_perimeter=cv2.arcLength(contours[parent],True)
        if not (3<=width<=32 and 3<=height<=32 and .75<=width/height<=1.4
                and 4<=area<=650 and 4*math.pi*area/max(perimeter*perimeter,1)>.7):continue
        connected=pw>=80 and ph>=50
        isolated=(5<=pw<=45 and 5<=ph<=45 and .75<=pw/ph<=1.4
                  and 4*math.pi*parent_area/max(parent_perimeter*parent_perimeter,1)>.7
                  and .12<area/max(parent_area,1)<.8)
        if not (connected or isolated):continue
        interior=np.zeros((height,width),dtype='uint8')
        cv2.drawContours(interior,[contour-[x,y]],-1,255,-1)
        interior=cv2.erode(interior,np.ones((3,3),dtype='uint8'))
        values=gray[y:y+height,x:x+width][interior>0]
        # A sphere's pale highlight is not the white centre of a hollow node.
        if not len(values) or float(np.median(values))<(245 if paper is None else 235):continue
        moments=cv2.moments(contour)
        points.append({'x':moments['m10']/moments['m00']/(image.width-1),
            'y':moments['m01']/moments['m00']/(image.height-1),
            'radius_pixels':max(width,height)/2+3,
            'component_bbox':[px/(image.width-1),py/(image.height-1),
                min(1,(px+pw)/(image.width-1)),min(1,(py+ph)/(image.height-1))],
            'component':parent if connected else 'isolated_ring_'+str(i),
            'isolated_circle_candidate':bool(isolated),'marker_profile':'native_hollow_size_consensus'})
    if not points:return []
    common=float(np.median([p['radius_pixels'] for p in points]))
    return [p for p in points if .7*common<=p['radius_pixels']<=1.4*common]


def attach_isolated_frames(points,graphs,image_size):
    """Associate isolated circles only with a uniquely nearby figure hull."""
    from collections import defaultdict
    from graph_qwen_components import assign_components
    groups=defaultdict(list)
    for p in points:groups[p['component']].append(p)
    core={key:ps for key,ps in groups.items() if len(ps)>=3}
    isolated=[p for p in points if p.get('isolated_circle_candidate')]
    if not isolated or len(core)!=len(graphs) or assign_components(graphs,core) is None:return points
    width,height=image_size;ownership={}
    for p in isolated:
        distances=[]
        for key,ps in core.items():
            left,right=min(q['x'] for q in ps),max(q['x'] for q in ps)
            top,bottom=min(q['y'] for q in ps),max(q['y'] for q in ps)
            dx=max(left-p['x'],0,p['x']-right)*(width-1)
            dy=max(top-p['y'],0,p['y']-bottom)*(height-1)
            distances.append((math.hypot(dx,dy),key))
        distances.sort(key=lambda pair:pair[0])
        if distances[0][0]>.25*min(width,height):return points
        if len(distances)>1 and distances[1][0]-distances[0][0]<2*p['radius_pixels']+12:return points
        ownership[p['component']]=distances[0][1]
    return [{**p,'original_native_component':p['component'],
             'component':ownership.get(p['component'],p['component'])} for p in points]


def hollow_first_context(image):
    """Controlled coordinate-free first-read context for separated ring figures."""
    from collections import defaultdict
    from graph_qwen_components import ordered_components
    from graph_glm_adapter import marker_overlay
    points=ring_markers(image);groups=defaultdict(list)
    if not 4<=len(points)<=48 or any(p.get('isolated_circle_candidate') for p in points):return None
    for p in points:groups[p['component']].append(p)
    if not 2<=len(groups)<=8 or any(len(ps)<3 for ps in groups.values()):return None
    order=ordered_components(groups,min_extent=0)
    if order is None:return None
    pool=[]
    for i in range(len(groups)):
        for p in sorted(groups[order[i]],key=lambda p:(p['y'],p['x'])):
            pool.append({**p,'id':f'p{len(pool)+1}'})
    return {'source':'native_hollow_components','markers':pool,'strong_markers':pool,
            'image':marker_overlay(image,pool)}


def photo_first_context(image):
    """Avoid verbose coordinate output on well separated multi-figure photos."""
    from graph_line_tracer import _paper_gray
    if _paper_gray(np.asarray(image)) is None:return None
    context=hollow_first_context(image)
    if context is None or len({p['component'] for p in context['markers']})<3:return None
    points=context['markers'];width,height=image.size
    for i,p in enumerate(points):
        for q in points[i+1:]:
            distance=math.hypot((p['x']-q['x'])*(width-1),(p['y']-q['y'])*(height-1))
            # Touching printed letter counters are not a safe first-read pool.
            if distance<2*(p['radius_pixels']+q['radius_pixels']):return None
    context['automatic_photo_context']=True
    return context
