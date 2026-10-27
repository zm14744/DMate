"""Graph-nextgen orchestration; spent graph budgets never start old vision."""
from __future__ import annotations
import os
import time
from graph_schema import display_graph
from graph_staged import recognize_staged, Budget
from graph_validation import audit_graph_records
from ocr_correction import correct_text
from ocr_layout import partition_text


def recognize_graph_document(raw,text_result,*,vision_provider=None,graph_pipeline='evidence-two-pass',
                             cancelled=None,task_id=None,request_deadline=None):
    # The application's agent-tools selection uses the fast editable workflow.
    # Older explicit engines remain available for existing diagnostic callers.
    if graph_pipeline not in ('staged','qwen-simple-candidate','evidence-two-pass','agent-tools','agent-tools-strict'):
        raise ValueError('Unknown graph pipeline')
    engine=recognize_staged
    version='2026-10-26-qwen-stable-review-v13'
    if graph_pipeline=='qwen-simple-candidate':
        from graph_qwen_simple import recognize_simple
        engine=recognize_simple
        version='qwen-simple-candidate-v59'
    elif graph_pipeline=='evidence-two-pass':
        from graph_evidence_pipeline import recognize_evidence, VERSION
        engine=recognize_evidence
        version=VERSION
    elif graph_pipeline=='agent-tools':
        from graph_fast_pipeline import recognize_fast
        from graph_pipeline_version import AGENT_PIPELINE_VERSION
        engine=recognize_fast
        version=AGENT_PIPELINE_VERSION
    elif graph_pipeline=='agent-tools-strict':
        from graph_agent_pipeline import recognize_agents
        engine=recognize_agents
        version='2026-10-26-agent-tools-v6-unpublished-comparison'
    layout=text_result.get('layout') or {}
    if graph_pipeline == 'agent-tools':
        from graph_fast_pipeline import configured_fast_budget
        budget=configured_fast_budget(task_id=task_id,cancelled=cancelled)
        if request_deadline is not None:
            budget.deadline=min(budget.deadline,request_deadline-3)
    elif graph_pipeline == 'agent-tools-strict':
        from graph_agent_runtime import AgentBudget
        budget=AgentBudget.configured(task_id=task_id,cancelled=cancelled)
        if request_deadline is not None:
            budget.deadline=min(budget.deadline,request_deadline-28)
    else:
        budget=Budget(seconds=140,calls=2,call_seconds=75) if graph_pipeline!='staged' else Budget()
    try:
        extra = {'text_result': text_result} if graph_pipeline in ('evidence-two-pass','agent-tools','agent-tools-strict') else {}
        if graph_pipeline in ('agent-tools','agent-tools-strict'):
            extra.update(cancelled=cancelled,task_id=task_id)
        layout_input = layout if graph_pipeline == 'agent-tools' else layout.get('regions', [])
        result=engine(raw,layout=layout_input,provider=vision_provider,
                               budget=budget,audit=os.environ.get('DMATE_GRAPH_STAGE_AUDIT')=='1', **extra)
        if not result['graphs'] and 'semantic_workflow' not in result:
            raise ValueError('empty_graph_inventory')
    except Exception as exc:
        # Return a diagnosed failure, so /ocr cannot silently start another
        # legacy vision pipeline outside the already spent graph budget.
        return _failed_graph_result(exc,version,budget,text_result)
    try:
        if cancelled is not None and cancelled():
            from graph_agent_runtime import AgentCancelled
            raise AgentCancelled('upload_cancelled')
        rendered=_render_graph_result(raw,text_result,result,version,layout,
                                      cancelled=cancelled,request_deadline=request_deadline)
        if result.get('recognition_profile') == 'fast-editable':
            seconds=round(time.monotonic()-budget.started,6)
            rendered.update(confirmation_required=True,recognition_profile='fast-editable',
                recognition_timing={'seconds':seconds,'target_seconds':120,
                    'within_target':seconds<=120,'scope':'recognition_and_response_rendering'})
            warnings=result.get('service_warnings',[])
            if warnings:
                rendered['service_warnings']=warnings
                rendered['warning']=' '.join(filter(None,[rendered.get('warning')]+[
                    item.get('message') for item in warnings]))
        return rendered
    except Exception as exc:
        return _failed_graph_result(exc,version,budget,text_result,stage_audit=result.get('stage_audit'))


def _failed_graph_result(exc,version,budget,text_result,*,stage_audit=None):
    failure={'error':'本次图形结构识别未完成，请核对原图。','graph_display_version':version,
        'recognition_status':'failed','review':{'required':True,'reasons':['图形识别未完成。']},
        'diagnostics':{'stages':['graph_pipeline_failed'],'failure_kind':type(exc).__name__,
            'remote_metrics':budget.metrics,'resource_metrics':text_result.get('resource_metrics',[])}}
    local_tools = getattr(budget, 'local_tool_execution', None)
    if isinstance(local_tools, dict):
        failure['diagnostics']['local_tools'] = local_tools
    evidence=getattr(exc,'graph_stage_audit',stage_audit)
    if os.environ.get('DMATE_GRAPH_STAGE_AUDIT')=='1' and evidence is not None:
        failure['diagnostics']['stage_audit']=evidence
    return failure


def _render_graph_result(raw,text_result,result,version,layout,*,cancelled=None,request_deadline=None):
    graphs=result['graphs']
    semantic = 'semantic_workflow' in result
    if isinstance(result.get('local_layout_result'), dict) and result['local_layout_result']:
        layout = result['local_layout_result']
    resource_metrics = text_result.get('resource_metrics', [])
    if result.get('local_resource_metrics'):
        replaced_stages = {row.get('stage') for row in result['local_resource_metrics'] if isinstance(row, dict)}
        resource_metrics = [row for row in resource_metrics if row.get('stage') not in replaced_stages] + result['local_resource_metrics']
    if isinstance(result.get('local_text_result'), dict):
        text_result = {**text_result, **result['local_text_result']}
    text=text_result.get('text') or ''
    local_text=text
    # If layout failed, use Qwen's explicit graph bounds to partition Small's
    # coordinate evidence, never regex-delete labels from an unlocated paragraph.
    evidence=text_result.get('text_evidence') or {}
    if text_result.get('layout_degraded') and evidence:
        regions=[]
        for graph in graphs:
            box=graph.get('bbox')
            if isinstance(box,list) and len(box)==4:
                try:
                    a,b,c,d=map(float,box)
                    if 0<=a<c<=1 and 0<=b<d<=1:
                        regions.append({'id':graph['id'],'bbox':[a,b,c,d],'role':'figure','score':.75})
                except (TypeError,ValueError): pass
        size=evidence.get('image_size')
        if regions and size:
            parts=partition_text(evidence.get('body',[]),regions,*size)
            text='\n'.join(x['content'] for x in parts['body'])
    text_source='paddle'
    text_complete=True
    if 'body_complete' in result:
        # The image pipeline supplies the final reviewed transcription.
        # Keep even an incomplete visual result, with its status, instead of
        # silently swapping back to a different unreviewed OCR paragraph.
        text_complete=result.get('body_complete') is True
        body=result.get('body_text')
        if isinstance(body,str):
            text=body
            text_source='original_visual_transcription'
    if cancelled is not None and cancelled():
        from graph_agent_runtime import AgentCancelled
        raise AgentCancelled('upload_cancelled')
    try:
        if semantic:
            # The semantic chain already performed literal visual checks.
            # DeepSeek supplies optional question advice, not another editor
            # that rewrites the source spans or spends an extra remote call.
            corrected,correction=text,{'status':'not_run','reason':'literal_semantic_text_preserved'}
        elif request_deadline is not None and request_deadline-time.monotonic()<3:
            corrected,correction=text,{'status':'not_run_deadline'}
        elif cancelled is not None or request_deadline is not None:
            remaining=(request_deadline-time.monotonic()) if request_deadline is not None else 25
            corrected,correction=correct_text(text,cancelled=cancelled,timeout_seconds=min(25,remaining))
        else:
            corrected,correction=correct_text(text)
    except Exception as exc:
        # A text-service exception does not erase independently reviewed graphs.
        corrected,correction=text,{'status':'failed','failure_kind':type(exc).__name__}
    if cancelled is not None and cancelled():
        from graph_agent_runtime import AgentCancelled
        raise AgentCancelled('upload_cancelled')
    if ('body_complete' in result and text.strip() and correction.get('status') not in ('ok','empty')
            and 'agent_workflow' not in result and 'semantic_workflow' not in result):
        text_complete=False
    issues=audit_graph_records(graphs)
    semantic_issues = result.get('semantic_issues', []) if semantic else []
    # The semantic adapter validates actual endpoint references and retains
    # uncertain content. Legacy whole-graph type flags are advisory here: a
    # mixed graph or a page with only some weighted edges can be legitimate.
    if issues and not semantic:
        for g in graphs: g['complete']=False
    from ai import _format_graph_data
    visual=_format_graph_data(graphs)
    graph_incomplete=any(g.get('complete') is not True for g in graphs)
    incomplete=graph_incomplete or not text_complete or bool(semantic_issues)
    reasons=[]
    if graph_incomplete:reasons.append('部分子图、顶点或连线尚未核对完整。')
    if not text_complete:reasons.append('题干文字尚未核对完整。')
    if semantic_issues:
        reasons += list(dict.fromkeys(str(i.get('message') or '部分内容仍需核对。')[:240]
                         for i in semantic_issues if isinstance(i,dict)))[:5]
    return {'text':corrected,'visual_text':visual,
            'graph_display_data':[display_graph(g) for g in graphs],
            'graph_structures':graphs,'raw_ocr_text':text,
            **({'text_context':result['text_context']} if isinstance(result.get('text_context'),dict) else {}),
            'graph_display_version':version,
            'review':{'required':incomplete,'reasons':reasons},
            'text_count':(len([line for line in corrected.splitlines() if line.strip()])
                          if text_source=='original_visual_transcription' else text_result.get('text_count',0)),
            'formula_count':0,
            'vision_used':True,'warning':' '.join(reasons) if reasons else None,
            'recognition_status':'partial' if incomplete else 'complete',
            'diagnostics':{'resource_metrics':resource_metrics,
                           'layout_status':layout.get('status','unavailable'),
                           'correction':correction,'validation':issues,
                           'text_evidence':{'source':text_source,'complete':text_complete,
                                            'paddle_text':local_text,
                                            'visual_body_complete':result.get('body_complete'),
                                            'second_pass_reviewed':result.get('body_audit',{}).get('second_pass_reviewed'),
                                            'reconciliation':result.get('body_audit',{})},
                           **({'image_quality':result['image_quality']} if 'image_quality' in result else {}),
                           'stages':result['diagnostics'],
                           'remote_metrics':result.get('remote_metrics',[]),
                           **({'agent_workflow':result['agent_workflow']} if 'agent_workflow' in result else {}),
                           **({'semantic_workflow':result['semantic_workflow'],
                               'semantic_issues':semantic_issues} if semantic else {}),
                           **({'stage_audit':result['stage_audit']} if 'stage_audit' in result else {})}}
