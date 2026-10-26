"""Original ink boundaries recover exterior strokes between collinear markers."""
import math
import cv2
import numpy as np


def boundary_paths(ink,graph,image_size):
    anchors={p['vertex']:p for p in graph.get('node_position_evidence',[])}
    if len(anchors)!=len(graph['vertices']) or len(anchors)<3 or any(
            p.get('marker_profile')!='native_hollow_size_consensus' or not p.get('radius_pixels') for p in anchors.values()):return []
    height,width=ink.shape;native_width,native_height=image_size
    nodes=[(v['id'],v['x']*(width-1),v['y']*(height-1),
            anchors[v['id']]['radius_pixels']*min(width/native_width,height/native_height)) for v in graph['vertices']]
    span_x=max(p[1] for p in nodes)-min(p[1] for p in nodes)
    span_y=max(p[2] for p in nodes)-min(p[2] for p in nodes)
    if min(span_x,span_y)>.2*max(span_x,span_y):return []
    bbox=graph['bbox'];left=max(0,int(bbox[0]*width));top=max(0,int(bbox[1]*height))
    right=min(width,math.ceil(bbox[2]*width));bottom=min(height,math.ceil(bbox[3]*height))
    contours,_=cv2.findContours(ink[top:bottom,left:right],cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    from graph_line_tracer import _sample_path
    output=[]
    for contour in contours:
        route=contour[:,0,:]+[left,top]
        if len(route)<30:continue
        positions=np.asarray([[x,y] for _,x,y,_ in nodes]);radii=np.asarray([r+3 for _,_,_,r in nodes])
        distances=np.linalg.norm(route[:,None,:]-positions[None,:,:],axis=2)
        nearest=np.argmin(distances,axis=1);hits=distances[np.arange(len(route)),nearest]<=radii[nearest]
        labels=np.where(hits,nearest,-1)
        starts=np.flatnonzero((labels>=0)&(np.roll(labels,1)!=labels))
        for start in starts:
            origin=int(labels[start]);i=int(start);visited=0
            while labels[i]==origin and visited<len(route):i=(i+1)%len(route);visited+=1
            first=(i-1)%len(route);body=[route[first]]
            while labels[i]<0 and visited<len(route):body.append(route[i]);i=(i+1)%len(route);visited+=1
            if visited>=len(route) or int(labels[i])==origin:continue
            target=int(labels[i]);body.append(route[i])
            if len(body)<12:continue
            path=_sample_path(body,width,height,max_error=.6)
            if not path:continue
            output.append({'from':nodes[origin][0],'to':nodes[target][0],'path':path,
                'score':.96,'style':'solid','method':'opencv_native_boundary_trace',
                'pixel_length':len(body),'needs_review':True})
            if len(output)>=48:return output
    return output
