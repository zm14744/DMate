"""Interrupted strokes: bridged proposals, original-pixel dash certificates."""
import copy,heapq,math
import cv2
import numpy as np
from graph_relation import _samples


def dash_support(path,ink):
    height,width=ink.shape;route=np.asarray(path)*[width-1,height-1]
    length=float(np.linalg.norm(np.diff(route,axis=0),axis=1).sum())
    if not 40<=length<=2200:return None
    points=np.asarray(_samples(route.tolist(),min(2200,max(80,round(length)))))
    trim=max(3,round(len(points)*.07));points=points[trim:-trim]
    distance=cv2.distanceTransform(np.uint8(ink==0),cv2.DIST_L2,3)
    at=np.rint(points).astype('int32')
    if (at<0).any() or (at[:,0]>=width).any() or (at[:,1]>=height).any():return None
    hits=distance[at[:,1],at[:,0]]<=.75;runs=[]
    for hit in hits:
        if runs and runs[-1][0]==bool(hit):runs[-1][1]+=1
        else:runs.append([bool(hit),1])
    spacing=length/(len(points)+2*trim)
    gaps=[n*spacing for hit,n in runs[1:-1] if not hit and n*spacing>2]
    coverage=float(np.mean(hits));largest=max([n*spacing for hit,n in runs if not hit],default=0)
    ratio=float(np.percentile(gaps,90)/max(.01,np.percentile(gaps,10))) if gaps else float('inf')
    if not (.4<=coverage<.94 and len(gaps)>=3 and ratio<=3 and largest<=min(20,length*.13)):return None
    dark=[n*spacing for hit,n in runs[1:-1] if hit and n*spacing>2]
    if not dark:return None
    style='dashed' if np.median(dark)>=np.median(gaps)*1.2 else 'dotted'
    return {'coverage':coverage,'largest_gap_pixels':largest,'native_gap_lengths':gaps,
            'continuous':False,'dashed':True,'style':style,'method':'original_native_repeated_gaps'}


def _window(graphs,index):
    hulls=[(min(v['x'] for v in g['vertices']),min(v['y'] for v in g['vertices']),
            max(v['x'] for v in g['vertices']),max(v['y'] for v in g['vertices'])) for g in graphs]
    x,y,r,b=hulls[index];left,top,right,bottom=0.,0.,1.,1.
    for j,(xx,yy,rr,bb) in enumerate(hulls):
        if j==index:continue
        if min(b,bb)>=max(y,yy):
            if rr<x:left=max(left,(rr+x)/2)
            if xx>r:right=min(right,(r+xx)/2)
        if min(r,rr)>=max(x,xx):
            if bb<y:top=max(top,(bb+y)/2)
            if yy>b:bottom=min(bottom,(b+yy)/2)
    return left,top,right,bottom


def dashed_photo_paths(ink,graphs,index,image_size):
    graph=graphs[index]
    if graph.get('weighted') is not True or graph.get('directed') is not False:return []
    proof={p['vertex']:p for p in graph.get('node_position_evidence',[])}
    if len(proof)!=len(graph['vertices']) or any(p.get('marker_profile')!='native_hollow_size_consensus' or not p.get('radius_pixels') for p in proof.values()):return []
    pairs={tuple(sorted((e['from'],e['to']))) for e in graph['edges'] if e['style'] in ('dashed','dotted') and e['from']!=e['to']}
    if not pairs or len(pairs)>16:return []
    height,width=ink.shape;scale=min(width/image_size[0],height/image_size[1])
    positions={v['id']:(round(v['x']*(width-1)),round(v['y']*(height-1))) for v in graph['vertices']}
    radii={key:proof[key]['radius_pixels']*scale for key in proof}
    left,top,right,bottom=_window(graphs,index)
    bounds=(max(0,round(left*(width-1))),max(0,round(top*(height-1))),min(width,math.ceil(right*width)),min(height,math.ceil(bottom*height)))
    mask=np.zeros_like(ink);a,b,c,d=bounds;mask[b:d,a:c]=ink[b:d,a:c]
    size=max(9,min(23,round(float(np.median(list(radii.values())))*2.8)))|1
    closed=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(size,size)))
    from graph_line_tracer import _thin,_sample_path
    skeleton=_thin(closed);output=[]
    for origin,target in sorted(pairs):
        start=np.asarray(positions[origin]);end=np.asarray(positions[target]);vector=end-start
        normal=np.array([-vector[1],vector[0]])/max(float(np.linalg.norm(vector)),1e-9)
        linear=[]
        for offset in np.arange(-4,4.01,.5):
            line=[((point+offset*normal)/[width-1,height-1]).tolist() for point in (start,end)]
            certificate=dash_support(line,ink)
            if certificate:linear.append((certificate['coverage'],line,certificate))
        if linear:
            _,path,certificate=max(linear,key=lambda t:t[0])
            output.append({'from':origin,'to':target,'path':path,'style':certificate['style'],
                'score':.96,'method':'opencv_original_dash_certificate','native_dash_certificate':certificate,
                'pixel_length':float(np.linalg.norm(vector)),'needs_review':True})
            continue
        available=skeleton.copy()
        for key,point in positions.items():
            if key not in (origin,target):cv2.circle(available,point,math.ceil(radii[key])+size//2+5,0,-1)
        yy,xx=np.where(available>0);start=positions[origin];end=positions[target]
        sources=[(int(x),int(y)) for x,y in zip(xx,yy) if math.hypot(x-start[0],y-start[1])<=radii[origin]+5]
        goals={(int(x),int(y)) for x,y in zip(xx,yy) if math.hypot(x-end[0],y-end[1])<=radii[target]+5}
        if not sources or not goals:continue
        queue=[(0,x,y) for x,y in sources];heapq.heapify(queue);dist={(x,y):0 for x,y in sources};parent={};found=None
        while queue:
            cost,x,y=heapq.heappop(queue)
            if cost!=dist[x,y]:continue
            if (x,y) in goals:found=(x,y);break
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nx,ny=x+dx,y+dy
                if not 0<=nx<width or not 0<=ny<height or not available[ny,nx]:continue
                new=cost+(14 if dx and dy else 10)
                if new<dist.get((nx,ny),10**9):dist[nx,ny]=new;parent[nx,ny]=(x,y);heapq.heappush(queue,(new,nx,ny))
        if found is None:continue
        route=[found]
        while route[-1] in parent:route.append(parent[route[-1]])
        route.reverse();path=_sample_path(route,width,height,max_error=.6)
        certificate=dash_support(path,ink) if path else None
        if certificate is None:continue
        output.append({'from':origin,'to':target,'path':path,'style':certificate['style'],
            'score':.96,'method':'opencv_original_dash_certificate','native_dash_certificate':certificate,
            'pixel_length':len(route),'needs_review':True})
    return output
