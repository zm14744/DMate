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
    ink=_foreground(rgb)
    contours,hierarchy=cv2.findContours(ink,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
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
        thin_connected=pw>=80 and 3<=ph<50
        connected=pw>=80 and ph>=50 or thin_connected
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
            **({'native_thin_component':True} if thin_connected else {}),
            'isolated_circle_candidate':bool(isolated),'marker_profile':'native_hollow_size_consensus'})
    if not points:return []
    from collections import Counter
    thin_counts=Counter(p['component'] for p in points if p.get('native_thin_component'))
    points=[p for p in points if not p.get('native_thin_component') or thin_counts[p['component']]>=3]
    if not points:return []
    common=float(np.median([p['radius_pixels'] for p in points]))
    points=[p for p in points if .7*common<=p['radius_pixels']<=1.4*common]
    if paper is not None:points=_nearby_hole_fragments(points,ink)
    if paper is None:
        points=_fragmented_rings(gray,contours,points,common)
    return points


def complete_ring_subset(image,points,legacy,observed_count):
    """A partly occluded hole can complement a complete native circle set."""
    from graph_line_tracer import _foreground,_paper_gray
    if not points or len(points)>=observed_count or _paper_gray(np.asarray(image)) is None:return None
    ink=_foreground(np.asarray(image));common=float(np.median([p['radius_pixels'] for p in points]));output=list(points)
    for point in legacy:
        if any(math.hypot((point['x']-p['x'])*(image.width-1),(point['y']-p['y'])*(image.height-1))<common for p in output):continue
        if not .7*common<=point['radius_pixels']<=1.4*common:continue
        rim=native_rim_profile(ink,point)
        if not rim or rim['relative_median_deviation']>.2 or not common*.7<=rim['radius_pixels']<=common*1.7:continue
        output.append({**point,'marker_profile':'native_hollow_size_consensus','native_occluded_rim':rim})
    return output if len(output)==observed_count else None


def native_rim_profile(ink,point):
    """Measure the outside of a hole's enclosing ink, without reading text."""
    height,width=ink.shape;x=point['x']*(width-1);y=point['y']*(height-1)
    angles=np.linspace(0,2*np.pi,96,endpoint=False)
    radii=np.arange(max(36,math.ceil(point['radius_pixels']*4)))
    xs=np.clip(np.rint(x+radii[:,None]*np.cos(angles)).astype('int32'),0,width-1)
    ys=np.clip(np.rint(y+radii[:,None]*np.sin(angles)).astype('int32'),0,height-1)
    hits=ink[ys,xs]>0;ends=[]
    for k in range(len(angles)):
        start=next((i for i in range(1,len(radii)-2) if hits[i:i+2,k].all()),None)
        if start is None:continue
        end=next((i for i in range(start+2,len(radii)-2) if not hits[i:i+2,k].any()),None)
        if end is not None:ends.append(end)
    if len(ends)<50:return None
    radius=float(np.median(ends))
    return {'radius_pixels':radius,'relative_median_deviation':float(np.median(np.abs(np.asarray(ends)-radius))/radius),
            'observed_angles':len(ends)}


def _nearby_hole_fragments(points,ink):
    """A small asymmetric attachment hole is not a second adjacent circle."""
    height,width=ink.shape;profiles={};rejected=set()
    for i,p in enumerate(points):
        for j,q in enumerate(points[:i]):
            if math.hypot((p['x']-q['x'])*(width-1),(p['y']-q['y'])*(height-1))>=1.2*(p['radius_pixels']+q['radius_pixels']):continue
            for k in (i,j):
                if k not in profiles:profiles[k]=native_rim_profile(ink,points[k])
            for weak,strong in ((i,j),(j,i)):
                a,b=profiles[weak],profiles[strong]
                if (a and b and a['relative_median_deviation']>.3 and b['relative_median_deviation']<=.15
                        and points[weak]['radius_pixels']<.9*points[strong]['radius_pixels']):rejected.add(weak)
    return [p for i,p in enumerate(points) if i not in rejected]


def refine_surplus_rings(image,points,observed_count):
    """Resolve glyph holes only if the physical subset matches observed nodes.

    Counts come from the current vision observation, never a reference answer.
    Failure to establish a full subset leaves the original inventory intact.
    """
    from graph_line_tracer import _foreground,_paper_gray
    if observed_count is not None and not 0<observed_count<len(points):return None
    if _paper_gray(np.asarray(image)) is None:return None
    ink=_foreground(np.asarray(image));profiles=[native_rim_profile(ink,p) for p in points]
    measured=[p['radius_pixels'] for p in profiles if p]
    if not measured:return None
    common=float(np.median(measured));rejected={i for i,p in enumerate(profiles) if p and p['radius_pixels']<common*.75}
    for i,p in enumerate(points):
        if i in rejected or profiles[i] is None:continue
        for j,q in enumerate(points[:i]):
            if j in rejected or profiles[j] is None or p.get('component')!=q.get('component'):continue
            distance=math.hypot((p['x']-q['x'])*(image.width-1),(p['y']-q['y'])*(image.height-1))
            if distance>profiles[i]['radius_pixels']+profiles[j]['radius_pixels']+4:continue
            for weak,strong in ((i,j),(j,i)):
                a,b=profiles[weak],profiles[strong]
                if (a['relative_median_deviation']-b['relative_median_deviation']>=.04
                        and a['relative_median_deviation']>b['relative_median_deviation']*1.5
                        and b['radius_pixels']>=a['radius_pixels']*1.1):rejected.add(weak)
    if not rejected or observed_count is not None and len(points)-len(rejected)!=observed_count:return None
    removed=[{'pixel_position':[points[i]['x'],points[i]['y']],'native_rim':profiles[i]} for i in sorted(rejected)]
    return [{**p,'native_pool_size_before_filter':len(points),'native_rejected_holes':removed,
             **({'native_external_radius_pixels':profiles[i]['radius_pixels']} if profiles[i] else {})}
            for i,p in enumerate(points) if i not in rejected]


def _fragmented_rings(gray,contours,points,common):
    """A crossing stroke can split a true white centre into non-round holes."""
    from collections import Counter
    height,width=gray.shape;counts=Counter(p['component'] for p in points)
    parents=[key for key,n in counts.items() if isinstance(key,int) and n>=3]
    if not parents:return points
    circles=cv2.HoughCircles(gray,cv2.HOUGH_GRADIENT,1,max(6,common),param1=100,param2=10,
        minRadius=max(3,round(common*.6)),maxRadius=math.ceil(common*1.4))
    if circles is None:return points
    angles=np.linspace(0,2*np.pi,96,endpoint=False);output=list(points)
    for xx,yy,rr in circles[0]:
        x,y,r=map(float,(xx,yy,rr))
        if any(math.hypot(x-p['x']*(width-1),y-p['y']*(height-1))<common*1.5 for p in output):continue
        owners=[key for key in parents if cv2.pointPolygonTest(contours[key],(x,y),False)>=0]
        if len(owners)!=1:continue
        samples=[]
        for factor in (.35,.95,1.45):
            xs=np.clip(np.rint(x+r*factor*np.cos(angles)).astype('int32'),0,width-1)
            ys=np.clip(np.rint(y+r*factor*np.sin(angles)).astype('int32'),0,height-1)
            samples.append(float(np.mean(gray[ys,xs]<180)))
        # This repair is for a centre split by actual intrusion. An entirely
        # empty circular-looking face between several edges is not a marker.
        if samples[1]<.8 or not .15<=samples[0]<=.6 or samples[2]>.5:continue
        parent=owners[0];prior=next(p for p in points if p['component']==parent)
        output.append({'x':x/(width-1),'y':y/(height-1),'radius_pixels':r,'component':parent,
            'component_bbox':prior['component_bbox'],'marker_profile':'native_hollow_size_consensus',
            'isolated_circle_candidate':False,'native_fragmented_ring_rim':samples})
    return output


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
    if context is None:return None
    if len({p['component'] for p in context['markers']})<3:
        # A counted-out printed counter supplies positive native evidence for
        # a complete two-figure pool. Use measured IDs before VL can omit a
        # named node and displace both figures with coarse coordinates.
        selected=refine_surplus_rings(image,context['markers'],None)
        if selected is None:return None
        from collections import Counter
        counts=Counter(p['component'] for p in selected)
        if len(counts)!=2 or min(counts.values())<3:return None
        from graph_glm_adapter import marker_overlay
        context.update(markers=selected,strong_markers=selected,image=marker_overlay(image,selected),
                       core_inventory=True,native_two_figure_counter_filter=True)
    points=context['markers'];width,height=image.size
    close=any(math.hypot((p['x']-q['x'])*(width-1),(p['y']-q['y'])*(height-1))<2*(p['radius_pixels']+q['radius_pixels'])
              for i,p in enumerate(points) for q in points[i+1:])
    if close:
        selected=refine_surplus_rings(image,points,None)
        if selected is None:return None
        from collections import Counter
        counts=Counter(p['component'] for p in selected)
        if len(counts)<3 or min(counts.values())<3:return None
        points=selected
        from graph_glm_adapter import marker_overlay
        context.update(markers=points,strong_markers=points,image=marker_overlay(image,points),
                       core_inventory=True,native_rim_counter_filter=True)
    for i,p in enumerate(points):
        for q in points[i+1:]:
            distance=math.hypot((p['x']-q['x'])*(width-1),(p['y']-q['y'])*(height-1))
            # Touching printed letter counters are not a safe first-read pool.
            if distance<2*(p['radius_pixels']+q['radius_pixels']):return None
    context['automatic_photo_context']=True
    return context
