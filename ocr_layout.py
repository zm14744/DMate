"""PP-DocLayoutV3 result adapter and evidence-preserving text partition."""
from __future__ import annotations
import math

FIGURES={'image','chart','table'}
FORMULAS={'display_formula','inline_formula'}
NOISE={'number','header','footer','header_image','footer_image','footnote','vision_footnote','formula_number'}
CAPTIONS={'figure_title'}


def normalize_layout(results,width,height):
    regions=[]
    for result in results:
        data=result.json if hasattr(result,'json') else result
        if isinstance(data,str):
            import json
            data=json.loads(data)
        data=data.get('res',data)
        for box in data.get('boxes',[])[:128]:
            try:
                score=float(box['score']); xy=[float(v) for v in box['coordinate']]
                if len(xy)!=4 or not all(math.isfinite(v) for v in xy) or score<.45: continue
                x1,y1,x2,y2=xy
                if x2<=x1 or y2<=y1: continue
                bbox=[max(0.,min(1.,x1/width)),max(0.,min(1.,y1/height)),
                      max(0.,min(1.,x2/width)),max(0.,min(1.,y2/height))]
                label=str(box.get('label','unknown'))
                role='figure' if label in FIGURES else 'formula' if label in FORMULAS else (
                     'noise' if label in NOISE else 'caption' if label in CAPTIONS else 'text')
                regions.append({'id':f'r{len(regions)+1}','bbox':bbox,'label':label,'role':role,'score':score})
            except (KeyError,TypeError,ValueError,OverflowError): continue
    return regions[:128]


def partition_text(items,regions,width,height):
    """Separate graph labels without deleting them from the internal evidence.

    Only strong (> .70) overlap removes a line. Border/overlap ambiguity remains
    explicit, never silently treated as body text. Caption/page labels stay out.
    """
    body=[]; labels=[]; noise=[]; uncertain=[]
    for item in items:
        box=item.get('box') or []
        if len(box)!=4: uncertain.append(item); continue
        x1,y1,x2,y2=box; area=max(1.,(x2-x1)*(y2-y1))
        overlaps=[]
        for region in regions:
            a,b,c,d=region['bbox']; a*=width; c*=width; b*=height; d*=height
            overlap=max(0,min(x2,c)-max(x1,a))*max(0,min(y2,d)-max(y1,b))/area
            if overlap>=.5: overlaps.append((overlap,region))
        excluded=[r for ratio,r in overlaps if r['role'] in ('figure','caption','noise') and r['score']>=.70]
        if excluded:
            target=labels if any(r['role']=='figure' for r in excluded) else noise
            target.append({**item,'region_ids':[r['id'] for r in excluded]})
        elif any(r['role'] in ('figure','caption','noise') for _,r in overlaps): uncertain.append(item)
        else: body.append(item)
    return {'body':body,'graph_labels':labels,'noise':noise,'uncertain':uncertain}
