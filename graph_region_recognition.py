"""User-selected original pixels -> graph-only result in source coordinates."""
import copy
import hashlib
import math

from graph_region import crop_region, validate_polygon
from image_evidence import decode_document_image
from image_upload_limits import MAX_IMAGE_PIXELS


def recognize_graph_region(raw, polygon, *, recognizer=None, **options):
    from graph_qwen_targeted import recognize_qwen_targeted, validate_draft
    polygon = validate_polygon(polygon)
    with decode_document_image(raw, max_pixels=MAX_IMAGE_PIXELS) as image:
        width, height = image.size
        x0=max(0,math.floor(min(p[0] for p in polygon)*width)-2)
        y0=max(0,math.floor(min(p[1] for p in polygon)*height)-2)
        x1=min(width,math.ceil(max(p[0] for p in polygon)*width)+2)
        y1=min(height,math.ceil(max(p[1] for p in polygon)*height)+2)
        cropped=crop_region(raw,polygon,_photo=image)
    result=copy.deepcopy((recognizer or recognize_qwen_targeted)(cropped,**options))
    document={'body_text':'','graphs':result.get('document',{}).get('graphs',[])}
    def point(p):
        return [(x0+p[0]*(x1-x0-1))/max(1,width-1),
                (y0+p[1]*(y1-y0-1))/max(1,height-1)]
    for graph in document['graphs']:
        for vertex in graph['vertices']:
            vertex['x'],vertex['y']=point([vertex['x'],vertex['y']])
        if graph.get('bbox'):
            a,b,c,d=graph['bbox'];graph['bbox']=[*point([a,b]),*point([c,d])]
        for edge in graph['edges']:
            if edge.get('path'):edge['path']=[point(p) for p in edge['path']]
    validate_draft(document)
    source=hashlib.sha256(raw).hexdigest()
    result.update(document=document,text='',graph_structures=document['graphs'],source_sha256=source,
        selection={'polygon':polygon,'source_box':[x0,y0,x1,y1],
                   'original_sha256':source,'crop_sha256':hashlib.sha256(cropped).hexdigest(),
                   'outside_polygon_masked':True})
    if not document['graphs']:
        result.update(recognition_status='partial',warning='选区内未识别到数学图形，请调整范围重试。',
                      review={'required':True,'reasons':['选区内未识别到数学图形，请调整范围重试。']})
    return result
