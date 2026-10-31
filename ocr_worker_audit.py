"""Bounded, text-free audit records for isolated local OCR workers.

Only shapes, counts, fixed phase names and numeric resource data are written.
The parent can read the sidecar even when a native worker is killed mid-call.
This module imports no image or model libraries.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time

DETECTOR_SIDE_LIMIT=1600
DETECTOR_LIMIT_TYPE='max'
MAX_AUDIT_BYTES=96*1024
PHASES={'startup','cache','decode','layout_init','layout_predict','text_init',
        'text_predict','text_det','text_rec','text_enhance','text_merge',
        'text_partition','output','complete'}


def audit_path(output_path):
    path=Path(output_path)
    return path.with_name(path.name+'.audit.json')


def self_rss():
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'): return int(line.split()[1])*1024
    except (OSError,ValueError): pass
    return 0


def read_audit(path):
    """Only consume our versioned bounded sidecar, never process stderr."""
    try:
        if Path(path).stat().st_size>MAX_AUDIT_BYTES: return None
        data=json.loads(Path(path).read_text())
        if (not isinstance(data,dict) or data.get('schema_version')!=1
                or data.get('current',{}).get('phase') not in PHASES): return None
        return data
    except (OSError,ValueError,TypeError,AttributeError): return None


def detector_size(width,height):
    """Installed PaddleX 3.7 max-side resize rule, including 32 alignment.

    This is a derived expected size, not an intercepted internal tensor shape.
    """
    ratio=min(1.,DETECTOR_SIDE_LIMIT/max(width,height))
    return [max(32,round(int(width*ratio)/32)*32),
            max(32,round(int(height*ratio)/32)*32)]


class WorkerAudit:
    def __init__(self,output_path,stage,on_phase=None):
        self.path=audit_path(output_path)
        self.started=time.monotonic()
        self.on_phase=on_phase
        self.data={'schema_version':1,'stage':stage,'current':{'phase':'startup','pass_index':0},
                   'events':[],'passes':[],
                   'parameters':({'text_det_limit_side_len':DETECTOR_SIDE_LIMIT,
                                 'text_det_limit_type':DETECTOR_LIMIT_TYPE,
                                 'maximum_ocr_passes':2} if stage=='text' else
                                 {'model':'PP-DocLayoutV3','batch_size':1})}
        self.flush()

    def flush(self):
        # All fields originate here or from numeric shapes/counts below.
        payload=json.dumps(self.data,separators=(',',':'))
        if len(payload)>MAX_AUDIT_BYTES: raise ValueError('audit_size_exceeded')
        temporary=self.path.with_suffix(self.path.suffix+'.tmp')
        temporary.write_text(payload)
        os.replace(temporary,self.path)

    def set_phase(self,name):
        if name not in PHASES: raise ValueError('invalid_audit_phase')
        self.data['current']['phase']=name
        if self.on_phase: self.on_phase(name)
        self.flush()

    @contextmanager
    def phase(self,name,**numbers):
        previous=self.data['current']['phase']
        row={'phase':name,'pass_index':self.data['current'].get('pass_index',0),
             'pass_kind':self.data['current'].get('pass_kind'),
             'started_seconds':round(time.monotonic()-self.started,6),
             'entry_rss_bytes':self_rss(),**numbers}
        if len(self.data['events'])>=48: raise ValueError('audit_event_limit')
        self.data['events'].append(row)
        self.set_phase(name)
        try:
            yield row
        except BaseException:
            row['status']='failed'
            row['finished_seconds']=round(time.monotonic()-self.started,6)
            row['exit_rss_bytes']=self_rss()
            self.flush()
            raise
        else:
            row['status']='ok'
            row['finished_seconds']=round(time.monotonic()-self.started,6)
            row['exit_rss_bytes']=self_rss()
            self.set_phase(previous)

    def start_pass(self,kind,image):
        if kind not in ('original','enhanced') or len(self.data['passes'])>=2:
            raise ValueError('ocr_pass_limit')
        height,width=image.shape[:2]
        index=len(self.data['passes'])+1
        row={'pass_index':index,'kind':kind,'source_size':[width,height],
             'expected_detector_size':detector_size(width,height),
             'detector_tensor_size_observed':False,'coordinate_space':'canonical_image_pixels'}
        self.data['passes'].append(row)
        self.data['current']={'phase':'text_predict','pass_index':index,'pass_kind':kind}
        self.set_phase('text_predict')
        return row


class AuditedPredictor:
    """Preserve lazy predictor results and parameters while marking its call."""
    def __init__(self,target,audit,phase):
        self.target,self.audit,self.phase=target,audit,phase

    def __getattr__(self,name): return getattr(self.target,name)

    def __call__(self,*args,**kwargs):
        inputs=args[0] if args else None
        shapes=([list(item.shape[:2]) for item in inputs if hasattr(item,'shape')]
                if isinstance(inputs,(list,tuple)) else
                [list(inputs.shape[:2])] if hasattr(inputs,'shape') else [])
        largest=max(shapes,key=lambda size:size[0]*size[1]) if shapes else None
        fields={'input_count':len(shapes),'largest_input_size':list(reversed(largest)) if largest else None}
        if self.phase=='text_det':
            fields.update(limit_side_len=kwargs.get('limit_side_len'),limit_type=kwargs.get('limit_type'))
        with self.audit.phase(self.phase,**fields) as event:
            result_count=0; detection_boxes=0
            for result in self.target(*args,**kwargs):
                result_count+=1
                if self.phase=='text_det' and hasattr(result,'get'):
                    boxes=result.get('dt_polys')
                    if boxes is not None: detection_boxes+=len(boxes)
                yield result
            event['result_count']=result_count
            if self.phase=='text_det': event['postprocess_detection_boxes']=detection_boxes


class BoundedTextModel:
    """Explicit detector-only budget; the pipeline input/crop pixels stay native."""
    def __init__(self,target,audit):
        self.target=target
        wrapper=target.paddlex_pipeline
        pipeline=getattr(wrapper,'_pipeline',wrapper)
        if not callable(getattr(pipeline,'text_det_model',None)) or not callable(getattr(pipeline,'text_rec_model',None)):
            raise RuntimeError('ocr_predictor_audit_unavailable')
        from ocr_text_engine import selected_text_engine
        engine=selected_text_engine()
        runners={}
        for name in ('text_det_model','text_rec_model'):
            runner=getattr(getattr(pipeline,name),'runner',None)
            session=getattr(runner,'session',None)
            if session is None: session=getattr(runner,'_session',None)
            providers=session.get_providers() if hasattr(session,'get_providers') else None
            if engine=='onnxruntime' and (type(runner).__name__!='ONNXRuntimeRunner'
                                          or providers!=['CPUExecutionProvider']):
                raise RuntimeError('text_engine_runtime_mismatch')
            runners[name]={'runner':type(runner).__name__,'providers':providers}
        audit.data['parameters'].update(text_engine=engine,runners=runners)
        audit.flush()
        pipeline.text_det_model=AuditedPredictor(pipeline.text_det_model,audit,'text_det')
        pipeline.text_rec_model=AuditedPredictor(pipeline.text_rec_model,audit,'text_rec')

    def __getattr__(self,name): return getattr(self.target,name)

    def predict(self,*args,**kwargs):
        kwargs.update(text_det_limit_side_len=DETECTOR_SIDE_LIMIT,text_det_limit_type=DETECTOR_LIMIT_TYPE)
        return self.target.predict(*args,**kwargs)
