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
GLM_53_FLASH_MODEL='glm-5.3-flash'
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
    text=[];finish=None;usage={};model=None;fingerprint=None;reasoning_chars=0;size=0;is_sse=False
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
        is_sse=True
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
    except (requests.RequestException,TimeoutError) as exc:
        if is_sse:
            # Audit evidence only. The caller still reports transport failure
            # and must never parse a partial stream as a completed graph.
            exc.vision_partial_result={'http_status':response.status_code,'partial_stream':True,
                'content':''.join(text),'model':model,'system_fingerprint':fingerprint,
                'usage':usage,'reasoning_chars':reasoning_chars,'finish_reason':finish}
        raise
    finally:response.close()


class VisionProvider:
    def __init__(self,name='qwen',*,model=None,thinking=False,reasoning_effort=None,thinking_budget=None,retries=0,capture=False,transport=None,sleep=time.sleep):
        if name not in ('qwen','glm'):raise ValueError('Unsupported vision provider')
        if type(thinking) is not bool:raise ValueError('thinking must be explicit boolean')
        if type(retries) is not int or not 0<=retries<=2:raise ValueError('retry limit is 0..2')
        allowed=(QWEN_MODEL,) if name=='qwen' else (GLM_MODEL,GLM_PAID_MODEL,GLM_53_FLASH_MODEL)
        self.name=name;self.model=model or allowed[0]
        if self.model not in allowed:raise ValueError('Unsupported provider model')
        if self.model==GLM_53_FLASH_MODEL:
            if not thinking:raise ValueError('glm-5.3-flash requires thinking=True; thinking cannot be disabled')
            reasoning_effort=reasoning_effort or 'low'
            if reasoning_effort not in ('low','high','max'):raise ValueError('GLM 5.3 reasoning effort must be low/high/max')
        elif reasoning_effort is not None:
            raise ValueError('reasoning_effort is supported only for glm-5.3-flash')
        self.reasoning_effort=reasoning_effort
        if thinking_budget is not None and (name!='qwen' or not thinking
                or type(thinking_budget) is not int or not 256<=thinking_budget<=4096):
            raise ValueError('thinking_budget requires Qwen thinking on, integer 256..4096')
        self.thinking_budget=thinking_budget
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
            if self.thinking_budget is not None:payload['thinking_budget']=self.thinking_budget
            if not self.thinking:payload['response_format']={'type':'json_object'}
        else:
            # Zhipu's SDK treats temperature=0 as do_sample=False, not a valid
            # raw API temperature. Omit temperature when sampling is disabled.
            payload.update(thinking={'type':'enabled' if self.thinking else 'disabled'},do_sample=False)
            if self.model==GLM_53_FLASH_MODEL:
                payload['reasoning_effort']=self.reasoning_effort
                # Verified on original photos: GLM 5.3 accepts JSON mode while
                # thinking is enabled. Qwen's thinking payload is different.
                payload['response_format']={'type':'json_object'}
            if not self.thinking:payload['response_format']={'type':'json_object'}
        return payload

    def __call__(self,prompt,images,budget):
        if not self.available():raise VisionError('missing_key')
        self.logical_calls+=1
        payload=self.payload(prompt,images)
        if self.name=='qwen' and hasattr(budget,'output_tokens'):
            value=budget.output_tokens
            if type(value) is not int or not 1024<=value<=16384:
                raise ValueError('invalid_bounded_output_budget')
            payload['max_tokens']=value
        if self.name=='qwen':
            import ai
            key=ai.API_KEY;request=self.transport or ai._request_qwen_completion
        else:key=os.environ['ZHIPU_API_KEY'];request=self.transport or _glm_request
        for attempt in range(self.retries+1):
            timeout=budget.take();started=time.monotonic();status=None;raw=None;error=None
            metric={'provider':self.name,'model':self.model,'thinking':self.thinking,
                    'max_output_tokens':payload['max_tokens'],
                    'reasoning_effort':self.reasoning_effort,
                    'thinking_budget':self.thinking_budget,
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
                              returned_model=result.get('model'),system_fingerprint=result.get('system_fingerprint'),
                              reasoning_chars=result.get('reasoning_chars',len((choice.get('message') or {}).get('reasoning_content') or '')))
                returned=str(result.get('model') or '').lower()
                if self.model==GLM_53_FLASH_MODEL and not returned:
                    raise VisionError('model_identity_unverified')
                if returned and (not (returned==self.model or returned.startswith(self.model+'-')) or
                        self.model==GLM_PAID_MODEL and returned.startswith(GLM_MODEL)):
                    raise VisionError('model_mismatch')
                if choice.get('finish_reason')=='network_error':raise VisionError('upstream_network_error')
                if choice.get('finish_reason')=='length':raise VisionError('truncated_output')
                if not isinstance(raw,str):
                    metric['output_error']='content_not_string'
                    raise VisionError('invalid_output')
                if not raw.strip() and metric['reasoning_chars']:
                    raise VisionError('reasoning_only_output')
                # Some vision responses append two backticks to an otherwise
                # complete JSON object. Remove formatting only, then validate
                # the ENTIRE root; never salvage an inner/truncated fragment.
                cleaned=re.sub(r'^`{1,3}(?:json)?\s*|\s*`{1,3}$','',raw.strip(),flags=re.IGNORECASE)
                try:
                    parsed=json.loads(cleaned,parse_constant=_invalid_json_constant)
                except json.JSONDecodeError as exc:
                    # Positions are enough to locate a captured failure without
                    # copying private model text into ordinary request metrics.
                    metric.update(output_error='json_syntax',json_error={
                        'line':exc.lineno,'column':exc.colno,'position':exc.pos})
                    raise VisionError('invalid_output') from exc
                except ValueError as exc:
                    metric['output_error']='non_finite_json_number'
                    raise VisionError('invalid_output') from exc
                if not isinstance(parsed,dict):
                    metric.update(output_error='root_not_object',json_root_type=type(parsed).__name__)
                    raise VisionError('invalid_output')
                metric['status']=200
                return parsed
            except (requests.RequestException,TimeoutError) as exc:
                error=VisionError('transport_failed');metric['status']='transport_failed'
                metric['exception_type']=type(exc).__name__
                metric['confirmed_timeout']=True if isinstance(exc,(requests.Timeout,TimeoutError)) else None
                partial=getattr(exc,'vision_partial_result',None)
                if isinstance(partial,dict) and partial.get('partial_stream') is True:
                    raw=partial.get('content')
                    metric.update(http_status=partial.get('http_status'),partial_stream=True,
                        returned_model=partial.get('model'),system_fingerprint=partial.get('system_fingerprint'),
                        usage=partial.get('usage') or {},reasoning_chars=partial.get('reasoning_chars'),
                        finish_reason=partial.get('finish_reason'))
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
