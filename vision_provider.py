"""Remote graph-vision adapters. Production callers explicitly default to Qwen.

No SDK/model dependency, cross-provider answer sharing, or automatic fallback.
Zhipu's image encoding, sampling and thinking fields follow its official SDK;
they are deliberately not copied from DashScope's request.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import time
import requests

GLM_MODEL='glm-4.6v-flash'
GLM_PAID_MODEL='glm-4.6v'
GLM_URL='https://open.bigmodel.cn/api/paas/v4/chat/completions'
QWEN_MODEL='qwen3-vl-plus'


class VisionError(RuntimeError):
    def __init__(self,kind,status=None):
        self.kind,self.status=kind,status
        super().__init__(kind+(f'_http_{status}' if status else ''))


def _invalid_json_constant(value):
    raise ValueError('Non-finite JSON number')


def image_digest(url):
    if not isinstance(url,str) or not url.startswith('data:image/') or ';base64,' not in url:
        raise ValueError('Only explicitly supplied image bytes are supported')
    return hashlib.sha256(base64.b64decode(url.split(',',1)[1],validate=True)).hexdigest()


def _glm_request(payload,headers,timeout,wall_deadline):
    response=requests.post(GLM_URL,headers=headers,json=payload,timeout=timeout,stream=True)
    try:
        if response.status_code!=200:
            code=None
            try:
                value=str((response.json().get('error') or {}).get('code',''))
                if value.isdigit() and len(value)<=8:code=value
            except (ValueError,AttributeError):pass
            return response.status_code,'',{'error_code':code}  # Never retain error messages/headers.
        if 'text/event-stream' not in response.headers.get('Content-Type',''):
            return 200,'',response.json()
        response.encoding='utf-8'  # SSE is UTF-8 even without a charset header.
        text=[];finish=None;usage={};model=None;fingerprint=None;reasoning_chars=0;size=0
        for line in response.iter_lines(decode_unicode=True):
            if time.monotonic()>wall_deadline:raise TimeoutError('vision_wall_deadline')
            if isinstance(line,bytes):line=line.decode('utf-8')
            if not line or not line.startswith('data:'):continue
            data=line[5:].strip()
            if data=='[DONE]':break
            chunk=json.loads(data)
            model=chunk.get('model',model);fingerprint=chunk.get('system_fingerprint',fingerprint)
            usage=chunk.get('usage') or usage
            for choice in chunk.get('choices') or []:
                delta=choice.get('delta') or {}
                content=delta.get('content') or ''
                if isinstance(content,str):text.append(content);size+=len(content)
                reasoning_chars+=len(delta.get('reasoning_content') or '')
                finish=choice.get('finish_reason') or finish
            if size>262144:raise ValueError('vision_output_budget')
        return 200,'',{'model':model,'system_fingerprint':fingerprint,'usage':usage,
                      'reasoning_chars':reasoning_chars,
                      'choices':[{'message':{'content':''.join(text)},'finish_reason':finish}]}
    finally:response.close()


class VisionProvider:
    def __init__(self,name='qwen',*,model=None,thinking=False,retries=0,capture=False,transport=None,sleep=time.sleep):
        if name not in ('qwen','glm'):raise ValueError('Unsupported vision provider')
        if type(thinking) is not bool:raise ValueError('thinking must be explicit boolean')
        if type(retries) is not int or not 0<=retries<=2:raise ValueError('retry limit is 0..2')
        allowed=(QWEN_MODEL,) if name=='qwen' else (GLM_MODEL,GLM_PAID_MODEL)
        self.name=name;self.model=model or allowed[0]
        if self.model not in allowed:raise ValueError('Unsupported provider model')
        self.thinking=thinking;self.retries=retries;self.capture=capture
        self.transport=transport;self.sleep=sleep;self.observations=[]
        self.logical_calls=0

    def available(self):
        if self.name=='glm':return bool(os.environ.get('ZHIPU_API_KEY','').strip())
        import ai
        return bool(ai.API_KEY and ai.VISION_ENABLED)

    def payload(self,prompt,images):
        content=[{'type':'text','text':prompt}]
        for url in images[:2]:
            image_digest(url)
            # Official Zhipu SDK drop_prefix_image_data sends raw base64.
            value={'url':url if self.name=='qwen' else url.split(',',1)[1]}
            if self.name=='qwen':value['detail']='high'
            content.append({'type':'image_url','image_url':value})
        payload={'model':self.model,'messages':[{'role':'user','content':content}],
                 'max_tokens':6500,'stream':True}
        if self.name=='qwen':
            payload.update(enable_thinking=self.thinking,temperature=0,
                           stream_options={'include_usage':True})
            if not self.thinking:payload['response_format']={'type':'json_object'}
        else:
            # Zhipu's SDK treats temperature=0 as do_sample=False, not a valid
            # raw API temperature. Omit temperature when sampling is disabled.
            payload.update(thinking={'type':'enabled' if self.thinking else 'disabled'},do_sample=False)
            if not self.thinking:payload['response_format']={'type':'json_object'}
        return payload

    def __call__(self,prompt,images,budget):
        if not self.available():raise VisionError('missing_key')
        self.logical_calls+=1
        payload=self.payload(prompt,images)
        if self.name=='qwen':
            import ai
            key=ai.API_KEY;request=self.transport or ai._request_qwen_completion
        else:key=os.environ['ZHIPU_API_KEY'];request=self.transport or _glm_request
        for attempt in range(self.retries+1):
            timeout=budget.take();started=time.monotonic();status=None;raw=None;error=None
            metric={'provider':self.name,'model':self.model,'thinking':self.thinking,
                    'started_at_unix':time.time(),
                    'logical_call':self.logical_calls,'attempt':attempt+1,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                    'image_sha256':[image_digest(url) for url in images[:2]]}
            try:
                status,_,result=request(payload,{'Authorization':f'Bearer {key}','Content-Type':'application/json'},
                    timeout=(min(8,timeout),timeout),wall_deadline=time.monotonic()+timeout)
                metric['http_status']=status
                if isinstance(result,dict) and result.get('error_code'):metric['error_code']=result['error_code']
                if status!=200 or not isinstance(result,dict):raise VisionError('http_error',status)
                choice=(result.get('choices') or [{}])[0]
                raw=(choice.get('message') or {}).get('content','')
                metric.update(finish_reason=choice.get('finish_reason'),usage=result.get('usage') or {},
                              returned_model=result.get('model'),system_fingerprint=result.get('system_fingerprint'))
                returned=str(result.get('model') or '').lower()
                if returned and (not returned.startswith(self.model) or
                        self.model==GLM_PAID_MODEL and returned.startswith(GLM_MODEL)):
                    raise VisionError('model_mismatch')
                if choice.get('finish_reason')=='length':raise VisionError('truncated_output')
                if not isinstance(raw,str):raise VisionError('invalid_output')
                cleaned=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip(),flags=re.IGNORECASE)
                parsed=json.loads(cleaned,parse_constant=_invalid_json_constant)
                if not isinstance(parsed,dict):raise VisionError('invalid_output')
                metric['status']=200
                return parsed
            except (requests.RequestException,TimeoutError):
                error=VisionError('transport_failed');metric['status']='transport_failed'
            except (ValueError,TypeError,KeyError,IndexError,AttributeError):
                error=VisionError('invalid_output');metric['status']='invalid_output'
            except VisionError as exc:
                error=exc;metric['status']=exc.kind
            finally:
                metric['seconds']=round(time.monotonic()-started,3)
                metric['content_chars']=len(raw) if isinstance(raw,str) else 0
                budget.metrics.append(metric)
                if self.capture:
                    self.observations.append({**metric,'raw_content':raw,
                        'error':error.kind if error else None,'prompt':prompt,
                        'request_parameters':{k:v for k,v in payload.items() if k!='messages'}})
            retryable=error.kind=='transport_failed' or error.status in (429,500,502,503,504)
            if attempt>=self.retries or not retryable:raise error
            delay=min(4.,2.**attempt)
            if getattr(budget,'deadline',0)-time.monotonic()<delay+3:raise error
            metric['retry_delay_seconds']=delay
            if self.capture:self.observations[-1]['retry_delay_seconds']=delay
            self.sleep(delay)


def qwen_call(prompt,images,budget):
    """Keep production selection explicit; ZHIPU_API_KEY cannot switch it."""
    return VisionProvider('qwen')(prompt,images,budget)
