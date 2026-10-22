"""Private subprocess entrypoint; never imported by Flask."""
import json
import os
from pathlib import Path
import sys


def main():
    stage,image_path,output_path=sys.argv[1:4]
    # Linux address-space ceiling is an additional guard against abrupt native
    # allocations between RSS polls. A failed allocation degrades this worker.
    if sys.platform=='linux':
        import resource
        try:
            Path('/proc/self/oom_score_adj').write_text('800')
        except OSError:
            pass
        resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3))
    import cv2
    cv2.setNumThreads(1)
    image=cv2.imread(image_path)
    if image is None: raise ValueError('decode_failed')
    if stage=='layout':
        from paddleocr import LayoutDetection
        from ocr_layout import normalize_layout
        model=LayoutDetection(model_name='PP-DocLayoutV3',device='cpu',cpu_threads=2,enable_mkldnn=False)
        regions=normalize_layout(model.predict(image,batch_size=1,layout_nms=True),image.shape[1],image.shape[0])
        result={'model':'PP-DocLayoutV3','status':'ok','regions':regions}
    elif stage=='text':
        os.environ['DMATE_FORMULA_ENABLED']='0'
        import ocr
        from ocr_layout import partition_text
        ocr.load_models()
        items=ocr._extract_text_items(image)
        if ocr._ocr_text_strength(items)<28 or ocr._math_line_risk(items):
            enhanced=ocr._extract_text_items(ocr._enhance_faded_photo(image))
            items=ocr._merge_text_ocr_passes(items,enhanced)
        regions=json.loads(Path(sys.argv[4]).read_text()).get('regions',[])
        partition=partition_text(items,regions,image.shape[1],image.shape[0])
        partition['image_size']=[image.shape[1],image.shape[0]]
        body=ocr._front_side_text_items(partition['body'],image)
        text=ocr._compose_markdown(body,image.shape[1])
        result={'text':text,'front_text':text,'text_count':len(body),'formula_count':0,
                'review_regions':ocr._review_regions(body,image.shape[1],image.shape[0]),
                'text_evidence':partition,'warning':None}
    else: raise ValueError('unknown_stage')
    Path(output_path).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__': main()
