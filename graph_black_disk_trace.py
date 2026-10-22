"""Conservative pixel tracing of single undirected black-disc graph drawings.

An eligible graph must have a small set of real filled circles, long straight
ink strokes, and line endpoints that each attach to two detected circle centers.
Crossings are not endpoints; text and unrelated strokes are not graph edges.
"""
from __future__ import annotations

import io
import numpy as np
import cv2
from PIL import Image, ImageOps


def recognize_black_disk_edges(image_bytes):
    with Image.open(io.BytesIO(image_bytes)) as source:
        image=ImageOps.exif_transpose(source).convert("RGB")
    width,height=image.size
    if not (350 <= width <= 2600 and 280 <= height <= 2200):
        return {"graphs":[],"status":"unsupported","regions":[]}
    arr=np.asarray(image)
    gray=cv2.cvtColor(arr,cv2.COLOR_RGB2GRAY)
    ink=np.uint8(gray<105)*255
    kernel=cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (9,9) if min(image.size)>=390 else (7,7)
    )
    isolated=cv2.morphologyEx(ink,cv2.MORPH_OPEN,kernel)
    _,_,stats,centers=cv2.connectedComponentsWithStats(isolated)
    nodes=[]
    for i in range(1,len(stats)):
        _,_,w,h,area=[int(v) for v in stats[i]]
        if not (70<=area<=1800 and 8<=w<=44 and 8<=h<=44):
            continue
        if not .78 <= w/max(h,1) <= 1.25:
            continue
        if area/(w*h) < .40:
            continue
        nodes.append(np.asarray(centers[i],dtype=float))
    if not (3 <= len(nodes) <= 12):
        return {"graphs":[],"status":"unsupported","regions":[]}
    # Uniform actual printed black disks; an assortment of large text glyphs
    # must not be mistaken for the full vertex set.
    disk_widths=[]
    for point in nodes:
        x,y=int(round(point[0])),int(round(point[1]))
        disk_widths.append(
            int(np.count_nonzero(isolated[y,min(width-1,x)]))
        )
    if max(disk_widths) > max(5,min(disk_widths))*2.0:
        return {"graphs":[],"status":"partial","regions":[]}

    hough=cv2.HoughLinesP(
        ink,1,np.pi/360,threshold=25,
        minLineLength=max(52,min(width,height)//8),
        maxLineGap=10
    )
    if hough is None:
        return {"graphs":[],"status":"partial","regions":[]}
    normalized=[]
    for row in np.asarray(hough).reshape(-1,4):
        p=np.asarray(row,dtype=float).reshape(2,2)
        vector=p[1]-p[0]
        distance=float(np.linalg.norm(vector))
        if distance<50:
            continue
        unit=vector/distance
        if unit[0]<0 or (abs(unit[0])<.001 and unit[1]<0):
            unit=-unit
        normal=np.array([-unit[1],unit[0]])
        normalized.append({
            "unit":unit, "rho":float(p.mean(0)@normal),
            "lo":float(min(p@unit)), "hi":float(max(p@unit)), "points":p
        })
    lines=[]
    for current in sorted(normalized,key=lambda p:-(p["hi"]-p["lo"])):
        for known in lines:
            unit=known["unit"]
            normal=np.array([-unit[1],unit[0]])
            if abs(float(unit@current["unit"]))<.997:
                continue
            if abs(float(current["points"].mean(0)@normal)-known["rho"])>3.6:
                continue
            lo=float(min(current["points"]@unit))
            hi=float(max(current["points"]@unit))
            if lo>known["hi"]+17 or hi<known["lo"]-17:
                continue
            known["lo"]=min(lo,known["lo"])
            known["hi"]=max(hi,known["hi"])
            break
        else:
            lines.append({
                "unit":current["unit"],"rho":current["rho"],
                "lo":current["lo"],"hi":current["hi"]
            })
    if not (2<=len(lines)<=70):
        return {"graphs":[],"status":"partial","regions":[]}
    edges=set()
    invalid_strokes=0
    for line in lines:
        unit=line["unit"]
        normal=np.array([-unit[1],unit[0]])
        points=(
            unit*line["lo"]+normal*line["rho"],
            unit*line["hi"]+normal*line["rho"]
        )
        matched=[]
        for point in points:
            distances=[float(np.linalg.norm(point-v)) for v in nodes]
            if not distances or min(distances)>24:
                matched=[]
                break
            matched.append(int(np.argmin(distances)))
        if len(matched)!=2 or matched[0]==matched[1]:
            invalid_strokes+=1
            continue
        edges.add(tuple(sorted(matched)))
    # Do not allow unrelated text strokes to make or break a genuine graph,
    # but reject a page where most lines cannot be anchored to real dots.
    if invalid_strokes>max(3,len(edges)//2):
        return {"graphs":[],"status":"partial","regions":[]}
    if len(edges)<len(nodes)-1 or len(edges)>len(nodes)*(len(nodes)-1)//2:
        return {"graphs":[],"status":"partial","regions":[]}
    if len({vertex for pair in edges for vertex in pair}) != len(nodes):
        return {"graphs":[],"status":"partial","regions":[]}
    # Separate pictures that share a large empty region must never be
    # collapsed into one graph (the initial detection is single-graph only).
    # Every node must connect by the recorded candidate edge set.
    root=list(range(len(nodes)))
    def find(node):
        while root[node]!=node:
            node=root[node]
        return node
    for a,b in edges:
        root[find(a)]=find(b)
    if len({find(i) for i in range(len(nodes))}) != 1:
        return {"graphs":[],"status":"partial","regions":[]}

    order=sorted(range(len(nodes)),key=lambda i:(
        round(float(nodes[i][1])/14),float(nodes[i][0])
    ))
    numbering={old:i for i,old in enumerate(order)}
    vertices=[
        {
            "id":f"v{i+1}",
            "x":round(float(nodes[old][0])/width,5),
            "y":round(float(nodes[old][1])/height,5),
            "label":None
        }
        for i,old in enumerate(order)
    ]
    links=sorted(set(
        tuple(sorted((numbering[a],numbering[b])))
        for a,b in edges
    ))
    matrix=[[0]*len(nodes) for _ in nodes]
    for a,b in links:
        matrix[a][b]=matrix[b][a]=1
    box=[
        max(0,min(float(v[0]) for v in nodes)-24)/width,
        max(0,min(float(v[1]) for v in nodes)-24)/height,
        min(width,max(float(v[0]) for v in nodes)+24)/width,
        min(height,max(float(v[1]) for v in nodes)+24)/height
    ]
    graph={
        "id":"图1","directed":"unknown",
        "vertices":vertices,"vertex_count":len(nodes),
        "edges":[[f"v{a+1}",f"v{b+1}"] for a,b in links],
        "confirmed_edge_count":len(links),
        "adjacency_matrix":matrix,
        "component_count_of_confirmed_edges":1,
        "uncertain_edges":[],
        "confidence":"partial",
        "bbox":[round(x,5) for x in box],
    }
    return {
        "graphs":[graph],"regions":[graph["bbox"]],
        "status":"partial",
        "detector":"hough_filled_black_disk_single"
    }


__all__=["recognize_black_disk_edges"]
