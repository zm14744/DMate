"""Strict CPU black-filled-circle graph recognition with crossing-aware edges.

Detect actual disk centers first by morphological opening, then accept edges
only if most of one uninterrupted original-pixel chord is dark. Visual crossing
without a disk is not a vertex. All results are unlabelled positional evidence;
OCR must separately match a/b/c/.. to original disks.

This is a conservative full-graph recognizer. Text glyphs, curvature,
arrowheads, broken diagrams or incomplete endpoints cause abstention.
"""
from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image, ImageOps


def _black_disk_centers(gray):
    h, w = gray.shape
    if min(h, w) < 100:
        return []
    dark = np.uint8(gray < 105) * 255
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (7, 7) if max(h, w) >= 580 else (5, 5)
    )
    opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(opened, 8)
    candidates = []
    for index in range(1, count):
        x, y, width, height, area = map(int, stats[index])
        if not (7 <= width <= 38 and 7 <= height <= 38):
            continue
        aspect = width / max(height, 1)
        if not (.79 <= aspect <= 1.27):
            continue
        if area < max(36, width * height * .62):
            continue
        cx, cy = map(float, centers[index])
        radius = (width + height) * .25
        # A letter or intersection is often elongated after opening.
        if float(gray[max(0,int(cy)-2):int(cy)+3,
                      max(0,int(cx)-2):int(cx)+3].mean()) > 110:
            continue
        candidates.append((cx, cy, radius, area))
    if not 4 <= len(candidates) <= 28:
        return []
    sizes = np.asarray([p[2] for p in candidates])
    common = float(np.median(sizes))
    circles = [p for p in candidates if .72 * common <= p[2] <= 1.35 * common]
    if not 4 <= len(circles) <= 18:
        return []
    if len(circles) < .85 * len(candidates):
        # Too many unrelated round glyphs relative to actual vertices.
        return []
    return circles


def _solid_chord(gray, first, second, others, *, cutoff=178):
    ax, ay, ar, _ = first
    bx, by, br, _ = second
    length = math.hypot(bx - ax, by - ay)
    if length < max(26, ar+br+12):
        return 0., 0.
    vx, vy = (bx-ax)/length, (by-ay)/length
    for node in others:
        if node is first or node is second:
            continue
        px, py, pr, _ = node
        dist_along = (px-ax)*vx + (py-ay)*vy
        dist_away = abs((px-ax)*vy - (py-ay)*vx)
        if ar+3 < dist_along < length-br-3 and dist_away < max(4.0,pr*.75):
            # Chord is split at that *actual* filled circle.
            return 0., 0.
    start = max(4.0, ar+3)
    end = length-max(4.0, br+3)
    if end - start < 14:
        return 0., 0.
    t = np.linspace(start, end, min(480, max(46, int(length))))
    h, w = gray.shape
    highest = (0., 0.)
    for start_drift in (-2., 0., 2.):
        for end_drift in (-2., 0., 2.):
            drift = start_drift + (end_drift - start_drift) * t / length
            xs = ax + vx*t - vy*drift
            ys = ay + vy*t + vx*drift
            readings = []
            for offset in (-1., 0., 1.):
                xi = np.clip(np.rint(xs-vy*offset).astype(int),0,w-1)
                yi = np.clip(np.rint(ys+vx*offset).astype(int),0,h-1)
                readings.append(gray[yi,xi])
            hits = (np.min(readings,axis=0) < cutoff).astype(np.uint8)
            hits = cv2.morphologyEx(
                hits.reshape(1,-1), cv2.MORPH_CLOSE,
                np.ones((1,3),np.uint8)
            ).ravel() > 0
            coverage = float(hits.mean())
            local = min(float(chunk.mean()) for chunk in np.array_split(hits, 5))
            if (local, coverage) > (highest[1], highest[0]):
                highest = (coverage, local)
    return highest


def recognize_black_disk_graph(image_bytes):
    """One full simple graph, if all black disks and straight edges validate.

    Never infer original printed labels or unseen edges. If any continuous edge
    is ambiguous, return no graph so the existing Vision route can inspect it.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            im = ImageOps.exif_transpose(source).convert("RGB")
        w0, h0 = im.size
        if min(w0,h0) < 190 or max(w0,h0) > 3600:
            return {"status":"unsupported","graphs":[],"regions":[]}
        if max(w0,h0) > 1800:
            ratio = 1800/max(w0,h0)
            im = im.resize((round(w0*ratio),round(h0*ratio)),
                           Image.Resampling.LANCZOS)
        rgb=np.asarray(im)
        h,w=rgb.shape[:2]
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        # Require a nearly uniform bright paper background. This protects
        # existing colour, dark-mode and multi-panel recognition paths.
        if np.percentile(gray,65) < 233:
            return {"status":"unsupported","graphs":[],"regions":[]}
        centers=_black_disk_centers(gray)
        if len(centers) < 4:
            return {"status":"uncertain","graphs":[],"regions":[]}
        xs=[v[0] for v in centers]
        ys=[v[1] for v in centers]
        # The whole disk cloud must be spatially spread across the page.
        if max(xs)-min(xs) < 60 or max(ys)-min(ys) < 50:
            return {"status":"uncertain","graphs":[],"regions":[]}
        centers.sort(key=lambda c:(round(c[1]/22), c[0]))
        edges=[]
        ambiguous=[]
        for i in range(len(centers)):
            for j in range(i+1,len(centers)):
                coverage,segment=_solid_chord(gray,centers[i],centers[j],centers)
                if coverage>=.945 and segment>=.81:
                    edges.append((i,j))
                elif coverage>=.60 and segment>=.38:
                    ambiguous.append((i,j))
        if len(edges)<3 or ambiguous:
            return {"status":"uncertain","graphs":[],"regions":[]}
        incident={a for edge in edges for a in edge}
        if len(incident)!=len(centers):
            return {"status":"uncertain","graphs":[],"regions":[]}
        # Disk/line evidence should not be dominated by printed text.
        # Never promote a single lucky four-node subset of an unrelated page.
        if len(centers)>14 and len(edges)<len(centers)-2:
            return {"status":"uncertain","graphs":[],"regions":[]}
        vertices=[
            {"id":f"v{i+1}","x":round(p[0]/w,5),
             "y":round(p[1]/h,5),"label":None}
            for i,p in enumerate(centers)
        ]
        matrix=[[0]*len(vertices) for _ in vertices]
        roots=list(range(len(vertices)))
        def find(z):
            while roots[z]!=z:
                roots[z]=roots[roots[z]]
                z=roots[z]
            return z
        for a,b in edges:
            matrix[a][b]=matrix[b][a]=1
            roots[find(a)]=find(b)
        graph={
            "id":"图1","directed":"unknown","vertices":vertices,
            "vertex_count":len(vertices),
            "edges":[[f"v{a+1}",f"v{b+1}"] for a,b in edges],
            "confirmed_edge_count":len(edges),
            "adjacency_matrix":matrix,
            "component_count_of_confirmed_edges":len({find(i) for i in range(len(vertices))}),
            "uncertain_edges":[],
            "confidence":"high",
            "bbox":[round(max(0,min(xs)-20)/w,5),
                    round(max(0,min(ys)-20)/h,5),
                    round(min(w,max(xs)+20)/w,5),
                    round(min(h,max(ys)+20)/h,5)]
        }
        return {"status":"detected","graphs":[graph],
                "regions":[graph["bbox"]],
                "detector":"black_disk_chord_pixel"}
    except (OSError,cv2.error,ValueError,TypeError):
        return {"status":"uncertain","graphs":[],"regions":[]}


__all__=["recognize_black_disk_graph"]
