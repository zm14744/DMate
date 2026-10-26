"""Remote graph-vision adapters. Production callers explicitly default to Qwen.

No SDK/model dependency, cross-provider answer sharing, or automatic fallback.
Zhipu's image encoding, sampling and thinking fields follow its official SDK;
they are deliberately not copied from DashScope's request.
"""
from __future__ import annotations
import base64
import hashlib
import json
import math
import os
import re
import socket
import ssl
import time
import requests
from urllib3 import exceptions as urllib3_errors

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


def _selected_images(images,max_images):
    # This is a trusted caller budget, never a field supplied by model output.
    if type(max_images) is not int or not 1<=max_images<=5:
        raise ValueError('invalid_max_images')
    return tuple(images[:max_images])


def _transport_failure_metrics(exc):
    """Describe transport failures without serializing exception messages/URLs.

    Requests turns an urllib3 ReadTimeoutError during iter_content into a
    ConnectionError. Its inner exception can live in args or reason rather
    than __cause__, so inspect those exception objects with a fixed bound.
    """
    pending=[exc];chain=[];seen=set()
    while pending and len(chain)<16:
        error=pending.pop(0)
        if not isinstance(error,BaseException) or id(error) in seen:continue
        seen.add(id(error));chain.append(error)
        cause=getattr(error,'__cause__',None)
        if cause is not None:pending.append(cause)
        elif not getattr(error,'__suppress_context__',False):
            pending.append(getattr(error,'__context__',None))
        pending.extend(getattr(error,key,None) for key in ('reason','original_error'))
        pending.extend(value for value in error.args[:8] if isinstance(value,BaseException))
    truncated=any(isinstance(value,BaseException) and id(value) not in seen for value in pending)
    def has(*types):return any(isinstance(error,types) for error in chain)
    def type_name(error):
        value=type(error).__module__+'.'+type(error).__name__
        return value if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,159}',value) else 'Exception'

    context=getattr(exc,'vision_failure_context',None)
    context=context if isinstance(context,dict) else {}
    partial=getattr(exc,'vision_partial_result',None)
    partial=partial if isinstance(partial,dict) else {}
    phase=context.get('failure_phase')
    if phase not in ('request_start','response_headers','response_body','sse_stream'):
        phase='sse_stream' if partial.get('partial_stream') is True else 'unknown'
    status=context.get('http_status',partial.get('http_status'))
    if type(status) is not int or not 100<=status<=599:
        status=getattr(getattr(exc,'response',None),'status_code',None)
    if type(status) is not int or not 100<=status<=599:status=None

    read_timeout=has(requests.ReadTimeout,urllib3_errors.ReadTimeoutError)
    # urllib3's NewConnectionError (also DNS failure) inherits from
    # ConnectTimeoutError, despite not establishing that a timeout occurred.
    connect_timeout=has(requests.ConnectTimeout) or any(
        isinstance(error,urllib3_errors.ConnectTimeoutError)
        and not isinstance(error,urllib3_errors.NewConnectionError) for error in chain)
    wall_timeout=context.get('wall_deadline_exceeded') is True
    timed_out=wall_timeout or read_timeout or connect_timeout or has(requests.Timeout,TimeoutError)
    incomplete=context.get('incomplete_stream') is True
    known_non_timeout=incomplete or has(ssl.SSLCertVerificationError,socket.gaierror,
                                        ConnectionRefusedError,ConnectionResetError,BrokenPipeError)
    timeout=True if timed_out else (False if known_non_timeout and not truncated else None)
    if wall_timeout:kind='wall_deadline'
    elif incomplete:kind='incomplete_stream'
    elif has(requests.exceptions.SSLError,urllib3_errors.SSLError,ssl.SSLError):kind='tls'
    elif has(socket.gaierror) or any(type(error).__name__=='NameResolutionError' for error in chain):kind='dns'
    elif read_timeout:kind='read_timeout'
    elif connect_timeout:kind='connect_timeout'
    elif timed_out:kind='timeout'
    elif has(requests.exceptions.ChunkedEncodingError,urllib3_errors.ProtocolError):kind='protocol'
    elif has(requests.exceptions.ProxyError,urllib3_errors.ProxyError):kind='proxy'
    elif has(requests.ConnectionError,urllib3_errors.NewConnectionError):kind='connection'
    else:kind='unknown'
    metric={'exception_type':type_name(exc).rsplit('.',1)[-1],
            'exception_chain':[type_name(error) for error in chain],
            'exception_chain_truncated':truncated,'failure_phase':phase,
            'transport_failure_kind':kind,'confirmed_timeout':timeout,
            'timeout_kind':('wall_deadline' if wall_timeout else 'read' if read_timeout
                            else 'connect' if connect_timeout else 'unspecified' if timed_out else None),
            'response_headers_received':context.get('response_headers_received') is True or status is not None,
            'partial_stream':context.get('partial_stream') is True or partial.get('partial_stream') is True}
    if status is not None:metric['http_status']=status
    for key in ('stream_lines_received','sse_events_received'):
        value=context.get(key)
        if type(value) is int and value>=0:metric[key]=value
    if type(context.get('stream_done_received')) is bool:
        metric['stream_done_received']=context['stream_done_received']
    if type(context.get('request_started')) is bool:
        metric['request_started']=context['request_started']
    return metric


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

    def payload(self,prompt,images,*,max_images=2):
        content=[{'type':'text','text':prompt}]
        for url in _selected_images(images,max_images):
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
        # Existing v3 budgets keep eight seconds; the agent budget can choose
        # another cap without adding a request or changing the wall deadline.
        connect_requested=getattr(budget,'connect_seconds',8.)
        if (type(connect_requested) not in (int,float) or not math.isfinite(connect_requested)
                or connect_requested<=0):
            raise ValueError('invalid_connect_seconds')
        max_images=getattr(budget,'max_images',2)
        selected_images=_selected_images(images,max_images)
        self.logical_calls+=1
        payload=self.payload(prompt,selected_images,max_images=max_images)
        image_sha256=[image_digest(url) for url in selected_images]
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
            if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
                raise ValueError('invalid_call_seconds')
            deadline=getattr(budget,'deadline',started+timeout)
            if type(deadline) not in (int,float) or not math.isfinite(deadline):
                raise ValueError('invalid_wall_deadline')
            wall_deadline=min(started+timeout,deadline)
            metric={'provider':self.name,'model':self.model,'thinking':self.thinking,
                    'max_output_tokens':payload['max_tokens'],
                    'reasoning_effort':self.reasoning_effort,
                    'thinking_budget':self.thinking_budget,
                    'started_at_unix':time.time(),
                    'logical_call':self.logical_calls,'attempt':attempt+1,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                    'max_images':max_images,'image_count':len(selected_images),
                    'image_sha256':list(image_sha256)}
            try:
                remaining=wall_deadline-time.monotonic()
                if remaining<=0:
                    expired=TimeoutError('vision_wall_deadline')
                    expired.vision_failure_context={'failure_phase':'request_start',
                        'request_started':False,'wall_deadline_exceeded':True}
                    raise expired
                connect_timeout=min(float(connect_requested),remaining)
                read_timeout=min(float(timeout),remaining)
                metric.update(connect_timeout_requested_seconds=float(connect_requested),
                    connect_timeout_seconds=round(connect_timeout,6),
                    read_timeout_seconds=round(read_timeout,6),
                    wall_timeout_seconds=round(remaining,6),
                    deadline_enforcement='cooperative_socket_timeout')
                status,_,result=request(payload,{'Authorization':f'Bearer {key}','Content-Type':'application/json'},
                    timeout=(connect_timeout,read_timeout),wall_deadline=wall_deadline)
                # Injected transports and JSON gateways must not turn a late
                # response into a successful result outside the task budget.
                if time.monotonic()>=wall_deadline:
                    expired=TimeoutError('vision_wall_deadline')
                    expired.vision_failure_context={'failure_phase':'response_body',
                        'request_started':True,'response_headers_received':True,
                        'http_status':status,'wall_deadline_exceeded':True}
                    raise expired
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
                metric.update(_transport_failure_metrics(exc))
                partial=getattr(exc,'vision_partial_result',None)
                if isinstance(partial,dict) and partial.get('partial_stream') is True:
                    raw=partial.get('content')
                    metric.update(partial_stream=True,
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
