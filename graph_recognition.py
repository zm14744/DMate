"""Conservative CPU-only recognition of *straight-edge, marked-vertex* textbook graphs.

No learned weights, paid OCR, or guessing missing edges. Output deliberately carries
uncertainty; graph recognition is advisory when endpoint evidence is incomplete.
"""
from __future__ import annotations

import io
import math
import time
from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 1650
MIN_RECOGNITION_SIDE = 1520
MAX_CIRCLES = 100
MAX_GRAPHS = 12


def _round_vertices(rgb):
    h, w = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # Include colored circles beyond red (blue/green nodes are common).
    colored = cv2.inRange(hsv, (0, 72, 65), (179, 255, 255))
    n, labels, stats, centers = cv2.connectedComponentsWithStats(colored, 8)
    found = []
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if 62 <= area <= 390 and 9 <= ww <= 19 and 9 <= hh <= 19 and .72 <= ww/max(hh,1) <= 1.39:
            perimeter = cv2.arcLength(cv2.findContours((labels[y:y+hh,x:x+ww]==i).astype('uint8'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0][0], True)
            circ = 4*math.pi*area/max(perimeter**2,1)
            if circ >= .53:
                found.append((float(centers[i][0]),float(centers[i][1]),float((ww+hh)/4),'red'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    circles = cv2.HoughCircles(cv2.medianBlur(gray,5), cv2.HOUGH_GRADIENT, 1.1, 18,
                               param1=105, param2=18, minRadius=4,
                               maxRadius=min(48, max(24, min(h,w)//18)))
    if circles is not None:
        for xx, yy, rr in circles[0]:
            x,y,r=int(round(xx)),int(round(yy)),int(round(rr))
            if x<r+2 or y<r+2 or x>=w-r-2 or y>=h-r-2:
                continue
            # Hollow circles are genuine vertices in many Graphviz/textbook
            # drawings. A white center alone cannot exclude them: verify the
            # surrounding continuous dark ring before treating it as a node.
            center_brightness = float(np.median(gray[y-2:y+3,x-2:x+3]))
            is_hollow = False
            if center_brightness > 241 and r >= 7:
                angles = np.linspace(0, 2*np.pi, 36, endpoint=False)
                xx_ring = np.clip(np.rint(x+r*np.cos(angles)).astype(int),0,w-1)
                yy_ring = np.clip(np.rint(y+r*np.sin(angles)).astype(int),0,h-1)
                xx_outer = np.clip(np.rint(x+(r+4)*np.cos(angles)).astype(int),0,w-1)
                yy_outer = np.clip(np.rint(y+(r+4)*np.sin(angles)).astype(int),0,h-1)
                inside = gray[yy_ring,xx_ring]
                outside = gray[yy_outer,xx_outer]
                is_hollow = (float(np.mean(inside < 140)) >= .60
                             and float(np.mean(outside)) - float(np.mean(inside)) >= 35)
                if not is_hollow:
                    continue
            elif center_brightness > 241:
                continue
            # Hough centers can be offset by 2-4 pixels at crossings. Refine
            # against the distinctive soft-gray *interior*, not dark junctions.
            best=None
            for dy in range(-4,5):
                for dx in range(-4,5):
                    px=x+dx;py=y+dy
                    if px<4 or py<4 or px>=w-4 or py>=h-4:continue
                    median=float(np.median(gray[py-3:py+4,px-3:px+4]))
                    if not (184 <= median <= 222):continue
                    cost=abs(median-203)+.4*math.hypot(dx,dy)
                    if best is None or cost<best[0]:best=(cost,px,py)
            # Neutral gray markers in screenshots have bright centers (~229)
            # and a darker rim. Shifting their centers towards a darker
            # interior pixel is exactly what breaks diagonal endpoint tests.
            center_median = float(np.median(gray[y-3:y+4, x-3:x+4]))
            if is_hollow or 216 <= center_median <= 239:
                candidate = (x, y)
            elif best:
                candidate = (best[1], best[2])
            else:
                continue
            if np.std(gray[max(0,y-r):min(h,y+r+1),max(0,x-r):min(w,x+r+1)]) > 20:
                found.append((float(candidate[0]),float(candidate[1]),float(rr),
                              'outline' if is_hollow else 'gray'))
    # Deduplicate Hough detections and overlapping red/gray segmentation.
    found.sort(key=lambda p: (p[3]!='red',-p[2]))
    unique=[]
    for v in found:
        if any(math.hypot(v[0]-q[0],v[1]-q[1])<max(v[2],q[2])*1.15 for q in unique):
            continue
        unique.append(v)
    return unique[:MAX_CIRCLES], gray


def _find_graph_boxes(vertices, gray):
    """Split independent drawings by blank ink columns within vertex row bands."""
    h,w=gray.shape
    if len(vertices)<3:
        return []
    # A slide can contain both text and marked graph circles. Gray textbook
    # balls usually form rows of >=4; solitary pseudo-circles in letters do not.
    grays=[v for v in vertices if v[3]=='gray']
    reds=[v for v in vertices if v[3]=='red']
    if len(reds)>=8:
        vertices=reds
    elif len(grays)>=8:
        vertices=grays
    elif len(reds)>=4:
        vertices=reds
    # Ignore isolated OCR glyphs: true textbook graph drawings have at least
    # two spatially separated rows of marked vertices. Group by horizontal band.
    vs=sorted(vertices,key=lambda p:p[1])
    bands=[]
    for v in vs:
        if not bands or v[1]-bands[-1][-1][1]>17:
            bands.append([v])
        else:
            bands[-1].append(v)
    bands=[row for row in bands if len(row)>=(4 if vertices is grays else 1)]
    groups=[];current=[]
    for band in bands:
        if current and band[0][1]-current[-1][1]>(140 if vertices is reds else 215):
            groups.append(current);current=[]
        current.extend(band)
    if current:groups.append(current)
    # Gray textbook dots often occupy two aligned rows much farther apart
    # than headline glyphs. Pair the rows by x-coordinates, rather than
    # chaining every apparent circle between the title and the diagrams.
    if vertices is grays and len(grays) >= 8:
        primary = [v for v in grays if v[2] >= 10]
        paired_bands = []
        for v in sorted(primary, key=lambda q: q[1]):
            if not paired_bands or v[1] - paired_bands[-1][-1][1] > 19:
                paired_bands.append([v])
            else:
                paired_bands[-1].append(v)
        matches = []
        for i, top in enumerate(paired_bands):
            if len(top) < 3: continue
            for bottom in paired_bands[i+1:]:
                if len(bottom) < 3: continue
                dy = float(np.median([v[1] for v in bottom]) - np.median([v[1] for v in top]))
                if not 33 <= dy <= 245: continue
                aligned = sum(any(abs(a[0]-b[0]) < 16 for b in bottom) for a in top)
                if aligned >= 3 and aligned >= min(len(top), len(bottom)) * .65:
                    matches.append((aligned, len(top)+len(bottom), top+bottom))
        if matches:
            # Most closely aligned rows are strong evidence of a graph strip.
            # Retain non-overlapping pairs only for multi-slide screenshots.
            matches.sort(reverse=True, key=lambda item:(item[0], item[1]))
            selected=[]; seen=set()
            for _, _, pair in matches:
                keys={id(v) for v in pair}
                if seen & keys:continue
                selected.append(pair); seen.update(keys)
            groups=selected
    output=[]
    for row in groups:
        if len(row)<4 or max(v[1] for v in row)-min(v[1] for v in row)<30:continue
        ymin=max(0,int(min(v[1] for v in row)-18))
        ymax=min(h,int(max(v[1] for v in row)+19))
        if ymax-ymin>(360 if vertices is reds else 270): # avoid mixed text/figures
            continue
        # Pixels darker than 155 include lines and nodes, remove sparse labels by
        # measuring uninterrupted column whitespace between endpoints.
        roi=gray[ymin:ymax]
        dark=(roi < 170).astype(np.uint8)
        density=(dark.sum(axis=0) > 2).astype(np.uint8)
        # Look for a gap of >= 14px in actual ink, not between adjacent dots.
        positions=sorted(row,key=lambda p:p[0]); bins=[];current=[positions[0]]
        for v in positions[1:]:
            prev=current[-1]
            a=max(0,int(prev[0]+max(5,prev[2])))
            b=min(w,int(v[0]-max(5,v[2])))
            if b-a>=14:
                empty=0; longest=0
                for val in density[a:b]:
                    empty = empty+1 if val==0 else 0
                    longest=max(longest,empty)
                split=longest>=18
            else:split=False
            if split:
                bins.append(current);current=[]
            current.append(v)
        bins.append(current)
        for part in bins:
            if len(part)<3:continue
            if len(part)>9: continue
            x1=max(0,int(min(v[0]-v[2] for v in part)-12))
            x2=min(w,int(max(v[0]+v[2] for v in part)+12))
            if x2-x1<22:continue
            output.append((part,(x1,ymin,x2,ymax)))
    return output[:MAX_GRAPHS]


def _fallback_graph_box(vertices, gray):
    """Fallback for one small diagram with 3–9 reliable circular markers.

    The normal layout splitter still handles full textbook pages. A one-graph
    cropped picture may have only two vertices on a row and must not be lost.
    This helper is used only when the primary multi-graph detector found nothing.
    """
    h, w = gray.shape
    if not 3 <= len(vertices) <= 9:
        return []
    xs=[v[0] for v in vertices]; ys=[v[1] for v in vertices]
    if max(xs)-min(xs) < 37 or max(ys)-min(ys) < 37:
        return []
    if max(xs)-min(xs) > .8*w or max(ys)-min(ys) > .8*h:
        return []
    x1=max(0,int(min(v[0]-v[2] for v in vertices)-12))
    y1=max(0,int(min(v[1]-v[2] for v in vertices)-12))
    x2=min(w,int(max(v[0]+v[2] for v in vertices)+12))
    y2=min(h,int(max(v[1]+v[2] for v in vertices)+12))
    return [(vertices,(x1,y1,x2,y2))]


def _relaxed_colored_vertices(rgb):
    """Catch larger solid-colour node markers; only a fallback on cropped art."""
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    mask=cv2.inRange(hsv,(0,105,75),(179,255,255))
    n, lab, stats, centers=cv2.connectedComponentsWithStats(mask,8)
    result=[]
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        if not (90 <= area <= 2100 and 11 <= w <= 52 and 11 <= h <= 52):
            continue
        if not .79 <= w / max(h,1) <= 1.26:
            continue
        patch=(lab[y:y+h,x:x+w]==i).astype(np.uint8)
        contours,_=cv2.findContours(patch,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:continue
        perimeter=cv2.arcLength(max(contours,key=cv2.contourArea),True)
        circularity=4*math.pi*area/max(perimeter*perimeter,1)
        if circularity>=.66 or (area / max(1, w*h)) >= .68:
            result.append((float(centers[i,0]),float(centers[i,1]),float((w+h)/4),'red'))
    return result[:MAX_CIRCLES]


def _edge_evidence(gray, a, b, all_nodes):
    x1,y1,r1,_=a; x2,y2,r2,_=b
    length=math.hypot(x2-x1,y2-y1)
    if length<18:return 0.0, 'too_close'
    # Another vertex ON a putative straight segment means this may be two
    # different edges; never promote it to a direct connection.
    vx=(x2-x1)/length;vy=(y2-y1)/length
    for c in all_nodes:
        if c is a or c is b:continue
        proj=(c[0]-x1)*vx+(c[1]-y1)*vy
        off=abs((c[0]-x1)*vy-(c[1]-y1)*vx)
        if r1+4 < proj < length-r2-4 and off < max(4,c[2]*.7):
            return 0.0,'intermediate_vertex'
    start=max(r1+3,5);end=length-max(r2+3,5)
    if end-start<9:return 0.0,'too_short'
    # Refit the straight chord by up to two pixels at each endpoint. A circular
    # shaded marker may shift Hough centers away from the actual line endpoint.
    num=max(20,int((end-start)/1.5))
    ts=np.linspace(start,end,num)
    H,W=gray.shape
    best=(0.0,0.0)
    # Slide diagrams often attach a line to the *edge* of a shaded dot,
    # several pixels away from its detected geometric center.
    shifts = (-10., -7., -4., -1., 2., 5., 8., 11.) if max(r1,r2) >= 12 else (-4.,-2.,0.,2.,4.)
    for shift_a in shifts:
        for shift_b in shifts:
            drift=shift_a+(shift_b-shift_a)*(ts/length)
            xx=x1+vx*ts-vy*drift
            yy=y1+vy*ts+vx*drift
            samples=[]
            for off in (-1.,0.,1.):
                xs=np.clip(np.rint(xx-off*vy).astype(int),0,W-1)
                ys=np.clip(np.rint(yy+off*vx).astype(int),0,H-1)
                samples.append(gray[ys,xs])
            occupancy=np.min(samples,axis=0)<186
            # Close only isolated 1-2px antialias gaps, not missing line parts.
            occ=cv2.morphologyEx(occupancy.astype(np.uint8).reshape(1,-1),
                                 cv2.MORPH_CLOSE,np.ones((1,3),np.uint8)).reshape(-1)>0
            coverage=float(occ.mean())
            pieces=[float(np.mean(x)) for x in np.array_split(occ,3)]
            min_piece=min(pieces)
            if min_piece > best[1] or (min_piece==best[1] and coverage>best[0]):
                best=(coverage,min_piece)
    cover,min_piece=best
    if min_piece<.52:return cover,'partial'
    if min_piece>=.77 and cover>=.88:return cover,'solid'
    return cover, 'uncertain' if cover>=.63 else 'partial'



def _hough_verified_edge(a, b, segments):
    """Collect collinear Hough segments without switching direction at crossings."""
    if segments is None:return False
    axy=np.array(a[:2],dtype=float);bxy=np.array(b[:2],dtype=float)
    d=bxy-axy;length=np.linalg.norm(d)
    if length<22:return False
    unit=d/length
    intervals=[]
    for x1,y1,x2,y2 in segments:
        p=np.array([x1,y1]);q=np.array([x2,y2]);seg=q-p
        seg_length=np.linalg.norm(seg)
        if seg_length<13:continue
        if abs(float(np.dot(seg,unit)))/seg_length<.975:continue
        if max(abs(float(np.cross(unit,p-axy))),abs(float(np.cross(unit,q-axy))))>8.5:continue
        pa=float(np.dot(p-axy,unit));qa=float(np.dot(q-axy,unit))
        lo,hi=max(0,min(pa,qa)),min(length,max(pa,qa))
        if hi>lo:intervals.append((lo,hi))
        if seg_length>=.73*length and min(pa,qa)<=max(9,a[2]+3) and max(pa,qa)>=length-max(9,b[2]+3):
            return True
    intervals.sort()
    if not intervals:return False
    merged=[]
    for lo,hi in intervals:
        if merged and lo-merged[-1][1]<=18:
            merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
        else:merged.append((lo,hi))
    return any(hi-lo>=.76*length and lo<=max(10,a[2]+5) and hi>=length-max(10,b[2]+5)
               for lo,hi in merged)


def _components(n, edges):
    parent=list(range(n))
    def root(i):
        while parent[i]!=i:
            i=parent[i]
        return i
    for a,b in edges:
        parent[root(a)]=root(b)
    return len(set(root(i) for i in range(n)))


def recognize_graphs(image_bytes, *, allow_without_context=False, text_hint=''):
    """Analyze full original bytes; return structured graphs with conservative uncertainty.

    Output graphs are ordered top-to-bottom then left-to-right. Only solid edges
    are called confirmed; borderline edges are listed separately for Vision review.
    Unsupported loops, curves, arrows and hand-drawn vertices remain *unknown*.
    """
    if not allow_without_context and not any(k in str(text_hint) for k in ('图','顶点','边','树','连通','邻接','路径','矩阵','欧拉','哈密顿','G₁','G1','G2','G3','G4')):
        return {'graphs':[], 'status':'not_graph', 'regions':[]}
    started=time.monotonic()
    # A page with six thin-blue outline graphs can trick the black-dot
    # detector into returning ONE accidental 8-vertex blob at high confidence.
    # A complete multi-panel circle+stroke match must take precedence over
    # that false positive (it never guesses missing figures or edges).
    try:
        from graph_sparse_panels import recognize_blue_outline_panels
        outline_result=recognize_blue_outline_panels(image_bytes)
        if len(outline_result.get("graphs") or []) >= 4:
            outline_result["elapsed_ms"]=round((time.monotonic()-started)*1000,1)
            return outline_result
    except (cv2.error, ValueError, TypeError, OSError) as exc:
        print(f"空心圆多图识别降级：{type(exc).__name__}")

    # The original Hough detector favors softly shaded/colored nodes. Prefer
    # filled-black-dot recognition for ordinary textbook graph drawings.
    # Failure never disables the existing detector or paid Vision fallback.
    try:
        from graph_recognition_v2 import recognize_filled_graphs
        filled_result = recognize_filled_graphs(
            image_bytes, allow_without_context=allow_without_context, text_hint=text_hint
        )
        if filled_result.get('graphs'):
            filled_result['elapsed_ms'] = round((time.monotonic()-started)*1000, 1)
            return filled_result
    except (cv2.error, ValueError, TypeError, OSError) as exc:
        print(f"实心点图结构检测降级：{type(exc).__name__}")
    # Strict disk-first recognition tests the original straight chord between
    # *two real disks* (not Hough line fragments). This is essential in MIT's
    # eight-node crossing diagram: Hough edges can end prematurely at a
    # crossing even though no vertex is there.
    try:
        from graph_black_disks import recognize_black_disk_graph
        disk_chords=recognize_black_disk_graph(image_bytes)
        if disk_chords.get("graphs"):
            disk_chords["elapsed_ms"]=round((time.monotonic()-started)*1000,1)
            return disk_chords
    except (cv2.error, ValueError, TypeError, OSError) as exc:
        print(f"黑色顶点原像素线段检测降级：{type(exc).__name__}")

    # If the filled-circle detector returned no usable topology, recover
    # real black-dot straight edges by endpoint-to-circle Hough tracing.
    # This does not overwrite successful v2 graphs or guess printed labels.
    try:
        from graph_black_disk_trace import recognize_black_disk_edges
        disk_result=recognize_black_disk_edges(image_bytes)
        if disk_result.get("graphs"):
            disk_result["elapsed_ms"]=round((time.monotonic()-started)*1000,1)
            return disk_result
    except (cv2.error,ValueError,TypeError,OSError) as exc:
        print(f"黑色实心顶点逐边检测降级：{type(exc).__name__}")

    with Image.open(io.BytesIO(image_bytes)) as im:
        im=ImageOps.exif_transpose(im).convert('RGB')
        longest=max(im.size)
        scale=min(MAX_SIDE/longest, max(1.0, MIN_RECOGNITION_SIDE/longest), 2.0)
        if abs(scale-1.0)>0.01:
            im=im.resize((int(im.width*scale),int(im.height*scale)),Image.Resampling.LANCZOS)
        rgb=np.asarray(im)
    vs,gray=_round_vertices(rgb)
    boxes=_find_graph_boxes(vs,gray)
    fallback=False
    if not boxes:
        candidates = _relaxed_colored_vertices(rgb)
        # The original detector can already have found good neutral-gray nodes.
        # Do not mix colour glyphs and gray vertices into a fictitious graph.
        if len(vs) >= 3 and len(vs) <= 9:
            candidates = vs
        boxes = _fallback_graph_box(candidates, gray)
        fallback=bool(boxes)
    graphs=[]
    for points,box in boxes:
        points=sorted(points,key=lambda p:(round(p[1]/22),p[0]))
        edges=[]; unsure=[]
        x1,y1,x2,y2=box
        roi=gray[y1:y2,x1:x2]
        segments_raw=cv2.HoughLinesP(cv2.Canny(roi,65,145), 1, np.pi/360,
                                      threshold=15,minLineLength=22,maxLineGap=7)
        segments=[]
        if segments_raw is not None:
            segments=[(u+x1,v+y1,w+x1,z+y1) for u,v,w,z in segments_raw[:,0]]
        for i in range(len(points)):
            for j in range(i+1,len(points)):
                score,status=_edge_evidence(gray,points[i],points[j],points)
                if status=='solid' or (status not in ('intermediate_vertex','too_close')
                                       and score>=.65 and _hough_verified_edge(points[i],points[j],segments)):
                    edges.append([i,j])
                elif status=='uncertain' or (status=='partial' and score>=.30):
                    unsure.append({'vertices':[i,j], 'coverage':round(score,2)})
        # Suppress OCR glyph constellations masquerading as an extra graph.
        # Real sparse/disconnected drawings without enough pixel evidence
        # fall back to Vision instead of inventing a third diagram.
        if len(edges)<2:
            # One accidental dark segment among decorative circles/glyphs is
            # not enough to present an OCR UI screenshot as a math graph.
            # Legitimate extremely sparse graphs fall back to Vision.
            continue
        if y1 > .83*gray.shape[0] and y2 > .9*gray.shape[0] and len(edges) < len(points)-1:
            # A partial diagram below the viewport edge of a slide screenshot.
            # Never present it as a ninth fully recovered graph.
            continue
        # If a circle-rich graph has too few verified edges, downgrade rather
        # than claim that it is a disconnected or empty graph.
        # A connected-looking subset of edges never proves the rest of the
        # image has been recognized. Record absent-edge evidence separately;
        # without strong evidence for EVERY pair, the graph remains partial.
        # A high confidence assertion needs consistent circle geometry,
        # no uncertain candidate, and all pairwise decisions supported.
        reliable_nodes = len(points) >= 3 and len(points) <= 9 and all(
            4 <= p[2] <= 22 for p in points
        )
        # Colorful/outlined nodes and graphviz layouts may carry curved,
        # directed or parallel edges that the straight-line detector misses.
        # Do not promote a plausible subset into a certain complete graph.
        colorful = bool(np.mean(
            np.max(rgb[y1:y2,x1:x2],axis=2).astype(np.int16)
            - np.min(rgb[y1:y2,x1:x2],axis=2).astype(np.int16) > 28) > .005)
        known_simple_markers = all(p[3] == 'gray' for p in points)
        confidence = 'high' if (
            reliable_nodes and known_simple_markers and not colorful
            and not unsure and scale <= 1.65 and not fallback
            and len(edges) >= len(points)-1
            and len(edges) <= len(points)*(len(points)-1)//2
        ) else 'partial'
        vertex_list=[{'id':f'v{i+1}','x':round(p[0]/rgb.shape[1],4),
                      'y':round(p[1]/rgb.shape[0],4), 'label':None} for i,p in enumerate(points)]
        matrix=[[0]*len(points) for _ in points]
        for i,j in edges:matrix[i][j]=matrix[j][i]=1
        graphs.append({'id':f'图{len(graphs)+1}', 'directed':'unknown',
                       'vertices':vertex_list,'vertex_count':len(points),
                       'edges':[[f'v{i+1}',f'v{j+1}'] for i,j in edges],
                       'confirmed_edge_count':len(edges),
                       'adjacency_matrix':matrix,
                       'component_count_of_confirmed_edges':_components(len(points),edges),
                       'uncertain_edges':[[f'v{item["vertices"][0]+1}',f'v{item["vertices"][1]+1}'] for item in unsure],
                       'confidence':confidence,
                       'bbox':[round(z/lim,4) for z,lim in zip(box,(rgb.shape[1],rgb.shape[0],rgb.shape[1],rgb.shape[0]))]})
    return {'status':'detected' if graphs else 'uncertain', 'graphs':graphs,
            'regions':[g['bbox'] for g in graphs],
            'warning':'OpenCV 仅自动确认直线、可见圆点的无向简单边；交叉点不自动视为顶点；曲线、重边、环、箭头、稀疏图及低分辨率的连接仍需 Vision 核对。',
            'elapsed_ms':round((time.monotonic()-started)*1000,1)}
