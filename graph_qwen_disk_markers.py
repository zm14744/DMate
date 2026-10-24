"""Native radial contrast for small filled markers erased by large openings.

Only pixel positions are measured. Names, figure membership and connections
remain the vision model's decisions; this is not a topology template.
"""
import math
import cv2
import numpy as np


def disk_markers(image,*,min_contrast=.9,preserve_overlaps=False):
    from graph_line_tracer import _foreground
    rgb=np.asarray(image);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);h,w=gray.shape
    if max(w,h)>1800 or np.mean(gray>245)<.8:return []
    ink=np.uint8(gray<105)
    _,components,stats,_=cv2.connectedComponentsWithStats(_foreground(rgb),8)
    distance=cv2.distanceTransform(ink,cv2.DIST_L2,5)
    maxima=np.uint8((distance>=3)&(distance>=cv2.dilate(distance,np.ones((7,7),np.uint8))-.01))
    count,labels,_,centers=cv2.connectedComponentsWithStats(maxima,8)
    points=[];angles=np.linspace(0,2*np.pi,72,endpoint=False)
    offsets=np.asarray([(dx,dy) for dx in range(-3,4) for dy in range(-3,4)])
    cos,sin=np.cos(angles),np.sin(angles)
    for i in range(1,count):
        x,y=centers[i];component=int(components[round(y),round(x)])
        a,b,c,d,area=map(int,stats[component]);radius=float(distance[labels==i].max())
        if not component or c<50 or d<35 or not 3<=radius<=18:continue
        best=(-1,None)
        for r in (radius-.5,radius,radius+.5):
            samples=[]
            for ratio in (.65,1.4):
                xx=np.clip(np.rint(x+offsets[:,0,None]+r*ratio*cos).astype('int32'),0,w-1)
                yy=np.clip(np.rint(y+offsets[:,1,None]+r*ratio*sin).astype('int32'),0,h-1)
                samples.append(np.mean(ink[yy,xx]>0,axis=1))
            scores=samples[0]-samples[1];k=int(np.argmax(scores));score=float(scores[k])
            if score>best[0]:best=(score,(x+offsets[k,0],y+offsets[k,1],r))
        if best[0]<min_contrast:continue
        # The inscribed-circle maximum locates the centre. Radial contrast
        # confirms roundness; sliding that ring to avoid an attached stroke
        # must not move an already measured vertex.
        _,_,r=best[1]
        points.append({'x':x/(w-1),'y':y/(h-1),'radius_pixels':r,
            'native_core_radius':radius,
            'component':component,'marker_profile':'native_filled_disk',
            'radial_contrast':best[0],
            'component_bbox':[a/(w-1),b/(h-1),(a+c-1)/(w-1),(b+d-1)/(h-1)]})
    if preserve_overlaps:return points if 4<=len(points)<=96 else []
    selected=[]
    for point in sorted(points,key=lambda p:p['radial_contrast'],reverse=True):
        if any(math.hypot((point['x']-p['x'])*(w-1),(point['y']-p['y'])*(h-1))
               <2*max(point['radius_pixels'],p['radius_pixels']) for p in selected):continue
        selected.append(point)
    return selected if 4<=len(selected)<=48 else []


def radius_consensus_markers(image):
    """Do not let a nearby thin head suppress a larger genuine disk core."""
    points=disk_markers(image,min_contrast=.5,preserve_overlaps=True)
    strict=[p for p in points if p['radial_contrast']>=.9]
    if len(strict)<4:return []
    radius=float(np.median([p['native_core_radius'] for p in strict]))
    measured=[p for p in points if radius*.98<=p['native_core_radius']<=radius*1.25]
    selected=[]
    for point in sorted(measured,key=lambda p:(p['native_core_radius'],p['radial_contrast']),reverse=True):
        if any(math.hypot((point['x']-p['x'])*(image.width-1),(point['y']-p['y'])*(image.height-1))
               <2*max(point['radius_pixels'],p['radius_pixels']) for p in selected):continue
        selected.append({**point,'native_core_size_consensus':radius})
    return selected


def core_consensus_markers(image):
    """Use independently round disks to distinguish smaller nearby heads."""
    points=disk_markers(image,min_contrast=.75)
    strict=[p for p in points if p['radial_contrast']>=.9]
    if len(strict)<4:return []
    radius=float(np.median([p['native_core_radius'] for p in strict]))
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    size=max(3,round(radius*.75));size+=1-size%2
    opened=cv2.morphologyEx(np.uint8(gray<105)*255,cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(size,size)))
    _,labels,stats,_=cv2.connectedComponentsWithStats(opened,8)
    selected=[]
    for p in points:
        if p['native_core_radius']<radius*.85:continue
        x,y=round(p['x']*(image.width-1)),round(p['y']*(image.height-1));key=int(labels[y,x])
        if not key:continue
        _,_,w,h,area=map(int,stats[key])
        if .79<=w/h<=1.27 and .62<=area/(w*h)<=.92:selected.append(p)
    return selected


def reanchor_candidate_disks(image,graphs,context):
    """A weak selected head cannot override a full unique disk measurement."""
    if not context or context.get('source')!='native_candidate_disk_components':return graphs,[]
    points=core_consensus_markers(image)
    if len(points)!=sum(len(g['vertices']) for g in graphs) and context.get('core_inventory'):
        points=radius_consensus_markers(image)
    if len(points)!=sum(len(g['vertices']) for g in graphs):return graphs,[]
    from graph_qwen_geometry import anchor_inventory
    def measured(image,graphs,*,candidate_sink=None,**kwargs):
        if candidate_sink is not None:candidate_sink.extend(points)
        return graphs
    output=anchor_inventory(image,graphs,refiner=measured)
    exact=all(g.get('node_review',{}).get('position_alignment')=='exact_inventory_global_unique' for g in output)
    if exact:
        for graph in output:
            graph['node_review']['native_disk_core_consensus']=True
            if any('native_core_size_consensus' in p for p in context['markers']):
                graph['node_review']['native_disk_core_size_recovery']=True
            if any(v['label'] is None for v in graph['vertices']) and any(v['label'] is not None for v in graph['vertices']):
                graph['node_review']['native_candidate_missing_labels']=True
    return output,['native_disk_core_consensus_reanchor'] if exact else []


def candidate_disk_context(image):
    """Controlled candidate pool; touching arrowheads are NOT asserted nodes."""
    from graph_glm_adapter import marker_overlay
    points=disk_markers(image,min_contrast=.75)
    if not points:return None
    core=core_consensus_markers(image)
    from collections import Counter
    groups=Counter(p['component'] for p in core)
    complete=bool(groups and set(groups)=={p['component'] for p in points} and all(n>=3 for n in groups.values()))
    if not complete:
        alternate=radius_consensus_markers(image)
        counts=Counter(p['component'] for p in alternate)
        if counts and set(counts)=={p['component'] for p in points} and all(n>=3 for n in counts.values()):
            core=alternate;complete=True
    if complete:points=core
    markers=[{**p,'id':f'p{i+1}'} for i,p in enumerate(sorted(points,key=lambda p:(p['y'],p['x'])))]
    return {'markers':markers,'strong_markers':markers if complete else [p for p in markers if p['radial_contrast']>=.9],
            'core_inventory':complete,
            'source':'native_candidate_disk_components','image':marker_overlay(image,markers)}


def core_first_context(image):
    """Promote only complete separated neutral disk frames, never broad pools."""
    from collections import defaultdict
    from graph_qwen_components import ordered_components
    context=candidate_disk_context(image)
    if context is None or not context['core_inventory']:return None
    groups=defaultdict(list)
    for p in context['markers']:groups[p['component']].append(p)
    if not 2<=len(groups)<=8 or any(len(ps)<3 for ps in groups.values()) or ordered_components(groups) is None:return None
    hsv=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2HSV)
    for p in context['markers']:
        x,y=round(p['x']*(image.width-1)),round(p['y']*(image.height-1));r=max(2,round(p['radius_pixels']*.7))
        if np.median(hsv[max(0,y-r):y+r+1,max(0,x-r):x+r+1,1])>30:return None
    return context


def disk_first_context(image):
    from collections import defaultdict
    from graph_qwen_components import ordered_components
    from graph_glm_adapter import marker_overlay
    points=disk_markers(image);groups=defaultdict(list)
    for point in points:groups[point['component']].append(point)
    if not 2<=len(groups)<=8 or any(len(ps)<3 for ps in groups.values()):return None
    order=ordered_components(groups)
    if order is None:return None
    # Dark coloured centres belong to the existing hue-aware profile. A few
    # of their cores must not masquerade as a complete black disk inventory.
    hsv=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2HSV);width,height=image.size
    for p in points:
        x,y=round(p['x']*(width-1)),round(p['y']*(height-1));r=max(2,round(p['radius_pixels']*.7))
        if np.median(hsv[max(0,y-r):y+r+1,max(0,x-r):x+r+1,1])>30:return None
    from graph_line_tracer import _foreground
    _,_,stats,_=cv2.connectedComponentsWithStats(_foreground(np.asarray(image)),8)
    bands=[(min(p['y'] for p in ps)*(height-1),max(p['y'] for p in ps)*(height-1)) for ps in groups.values()]
    # Reject a missing figure alongside detected figures. Printed headings
    # above the actual drawing rows do not count as figure observations.
    for key,(x,y,w,h,area) in enumerate(stats):
        if key and key not in groups and w>=80 and h>=50 and any(
                min(y+h,bottom)-max(y,top)>=.5*min(h,bottom-top) for top,bottom in bands):return None
    markers=[]
    for key in order.values():
        for p in sorted(groups[key],key=lambda p:(p['y'],p['x'])):
            markers.append({**p,'id':f'p{len(markers)+1}'})
    return {'markers':markers,'strong_markers':markers,'image':marker_overlay(image,markers),
            'source':'native_small_filled_components'}
