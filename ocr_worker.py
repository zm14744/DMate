"""Private subprocess entrypoint; never imported by Flask."""
import json
import math
import os
from pathlib import Path
import sys

WORKER_PHASE='startup'


def _set_phase(name):
    global WORKER_PHASE
    WORKER_PHASE=name


def _unconfirmed_enhanced(merged,enhanced):
    """Keep distinct auxiliary reads as evidence, never promote them to body.

    The existing merge can deliberately reject a numeric conflict or a newly
    detected region. Such reads still matter to the full-image review. Only a
    same-text, geometrically overlapping duplicate of a selected item is omitted.
    """
    by_text={}
    for item in merged:
        by_text.setdefault(str(item.get('content','')).strip(),[]).append(item)
    candidates=[]
    for item in enhanced:
        text=str(item.get('content','')).strip();box=item.get('box')
        try:
            score=float(item.get('score',0))
            valid=(text and isinstance(box,(list,tuple)) and len(box)==4
                   and all(math.isfinite(float(v)) for v in box)
                   and box[2]>box[0] and box[3]>box[1] and math.isfinite(score) and score>=.45)
        except (TypeError,ValueError): valid=False
        if not valid: continue
        duplicate=False
        for old in by_text.get(text,[]):
            other=old.get('box') or []
            if len(other)!=4: continue
            intersection=max(0,min(box[2],other[2])-max(box[0],other[0]))*max(0,min(box[3],other[3])-max(box[1],other[1]))
            area=(box[2]-box[0])*(box[3]-box[1])
            old_area=max(1.,(other[2]-other[0])*(other[3]-other[1]))
            if intersection/max(1.,min(area,old_area))>=.5:
                duplicate=True;break
        if not duplicate:
            candidates.append({**item,'review_reason':'enhanced_candidate_unconfirmed'})
    return candidates


def failure_payload(exc):
    """Operational evidence without exception messages, image text or secrets."""
    from ocr_runtime import ModelCacheError
    if isinstance(exc,ModelCacheError): kind='model_cache_unavailable'
    elif isinstance(exc,MemoryError): kind='memory_allocation_failed'
    elif isinstance(exc,PermissionError): kind='filesystem_permission_denied'
    elif isinstance(exc,(ImportError,ModuleNotFoundError)): kind='dependency_unavailable'
    elif WORKER_PHASE=='decode': kind='image_decode_failed'
    elif WORKER_PHASE.endswith('_init'): kind='model_initialization_failed'
    else: kind='model_inference_failed'
    return {'worker_error':type(exc).__name__,'error_kind':kind,'phase':WORKER_PHASE}


def _limit_resources():
    """The worker stays isolated and below the existing 4-GB host budget."""

    # Limit private data allocations, not all virtual address mappings. Paddle
    # and its shared libraries can reserve >3 GB of address space while actual
    # RSS is ~1.1 GB; RLIMIT_AS incorrectly rejected PP-DocLayoutV3 inference.
    # The parent still enforces 1.6-GB RSS and the 4-GB cgroup working-set budget.
    if sys.platform=='linux':
        import resource
        try:
            Path('/proc/self/oom_score_adj').write_text('800')
        except OSError:
            pass
        resource.setrlimit(resource.RLIMIT_DATA,(3*1024**3,3*1024**3))


def main():
    stage,image_path,output_path=sys.argv[1:4]
    if stage not in ('layout','text'): raise ValueError('unknown_stage')
    from ocr_worker_audit import WorkerAudit,BoundedTextModel
    audit=WorkerAudit(output_path,stage,on_phase=_set_phase)
    audit.set_phase('cache')
    from ocr_runtime import configure_model_cache,write_worker_result
    configure_model_cache(os.environ)
    # This also applies to explicitly invoked standalone cache-preparation
    # workers; do not rely only on the parent process setting these variables.
    for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[key]='1'
    os.environ['DMATE_FORMULA_ENABLED']='0'
    _limit_resources()
    with audit.phase('decode'):
        import cv2
        cv2.setNumThreads(1)
        image=cv2.imread(image_path)
        if image is None: raise ValueError('decode_failed')
        audit.data['input_size']=[image.shape[1],image.shape[0]]
    if stage=='layout':
        with audit.phase('layout_init'):
            from paddleocr import LayoutDetection
            from ocr_layout import normalize_layout
            model=LayoutDetection(model_name='PP-DocLayoutV3',device='cpu',cpu_threads=2,enable_mkldnn=False)
        with audit.phase('layout_predict') as event:
            regions=normalize_layout(model.predict(image,batch_size=1,layout_nms=True),image.shape[1],image.shape[0])
            event['retained_regions']=len(regions)
        result={'model':'PP-DocLayoutV3','status':'ok','regions':regions}
    elif stage=='text':
        with audit.phase('text_init'):
            import ocr
            from ocr_layout import partition_text
            ocr.load_models()
            ocr._text_ocr=BoundedTextModel(ocr._text_ocr,audit)
        original_pass=audit.start_pass('original',image)
        items=ocr._extract_text_items(image)
        unconfirmed=[]
        original_pass['accepted_items']=len(items)
        for index,item in enumerate(items):
            item['ocr_provenance']={'pass_index':1,'pass_kind':'original','item_index':index}
        audit.flush()
        # One bounded auxiliary pass, never a retry loop. It keeps native source
        # dimensions and the same detector budget; numeric changes still use
        # the existing conservative merge policy in ocr.py.
        if ocr._ocr_text_strength(items)<28 or ocr._math_line_risk(items):
            enhanced_pass=audit.start_pass('enhanced',image)
            with audit.phase('text_enhance'):
                enhanced_image=ocr._enhance_faded_photo(image)
            enhanced=ocr._extract_text_items(enhanced_image)
            del enhanced_image
            enhanced_pass['accepted_items']=len(enhanced)
            for index,item in enumerate(enhanced):
                item['ocr_provenance']={'pass_index':2,'pass_kind':'enhanced','item_index':index}
            with audit.phase('text_merge') as event:
                items=ocr._merge_text_ocr_passes(items,enhanced)
                unconfirmed=_unconfirmed_enhanced(items,enhanced)
                event['retained_items']=len(items)
                event['unconfirmed_enhanced_items']=len(unconfirmed)
            del enhanced
        with audit.phase('text_partition') as event:
            regions=json.loads(Path(sys.argv[4]).read_text()).get('regions',[])
            partition=partition_text(items,regions,image.shape[1],image.shape[0])
            partition['uncertain'].extend(unconfirmed)
            partition['image_size']=[image.shape[1],image.shape[0]]
            partition['coordinate_space']='canonical_image_pixels'
            body=ocr._front_side_text_items(partition['body'],image)
            # Keep the exact emitted OCR items and their original pixel boxes.
            # The automatic figure detector later removes only labels INSIDE
            # recognized diagrams; it must not heuristically delete words from
            # an already assembled question string.
            partition['emitted_body']=body
            text=ocr._compose_markdown(body,image.shape[1])
            event['partition_counts']={key:len(partition[key]) for key in ('body','graph_labels','noise','uncertain')}
            event['emitted_body_items']=len(body)
        result={'text':text,'front_text':text,'text_count':len(body),'formula_count':0,
                'review_regions':ocr._review_regions(body,image.shape[1],image.shape[0]),
                'text_evidence':partition,'warning':None}
    with audit.phase('output'):
        completion=write_worker_result(stage,output_path,result)
    audit.data['completion']=completion
    audit.set_phase('complete')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        # No image text or credentials in operational errors.
        if len(sys.argv)>3:
            try:
                Path(sys.argv[3]).write_text(json.dumps(failure_payload(exc)),encoding='utf-8')
            except OSError:
                pass
        raise SystemExit(2)

