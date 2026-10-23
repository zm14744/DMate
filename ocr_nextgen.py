"""Opt-in orchestration; original /ocr stays available as a fallback."""
from __future__ import annotations
import os
from graph_schema import display_graph
from graph_staged import recognize_staged, Budget
from graph_validation import audit_graph_records
from ocr_correction import correct_text
from ocr_layout import partition_text


def recognize_graph_document(raw,text_result,*,vision_provider=None):
    layout=text_result.get('layout') or {}
    budget=Budget()
    try:
        result=recognize_staged(raw,layout=layout.get('regions',[]),provider=vision_provider,
                               budget=budget,audit=os.environ.get('DMATE_GRAPH_STAGE_AUDIT')=='1')
        if not result['graphs']:raise ValueError('empty_graph_inventory')
    except (ValueError,RuntimeError,TimeoutError):
        # Return a diagnosed failure, so /ocr cannot silently start another
        # legacy vision pipeline outside the already spent graph budget.
        return {'error':'本次图形结构识别未完成，请核对原图。',
                'graph_display_version':'2026-10-23-qwen-stage-integrity-v13',
                'diagnostics':{'stages':['graph_pipeline_failed'],
                               'remote_metrics':budget.metrics,
                               'resource_metrics':text_result.get('resource_metrics',[])}}
    graphs=result['graphs']
    text=text_result.get('text') or ''
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
    corrected,correction=correct_text(text)
    issues=audit_graph_records(graphs)
    if issues:
        for g in graphs: g['complete']=False
    from ai import _format_graph_data
    visual=_format_graph_data(graphs)
    incomplete=any(g.get('complete') is not True for g in graphs)
    return {'text':corrected,'visual_text':visual,
            'graph_display_data':[display_graph(g) for g in graphs],
            'graph_structures':graphs,'raw_ocr_text':text,
            'graph_display_version':'2026-10-23-qwen-stage-integrity-v13',
            'review':{'required':incomplete,'reasons':[]},
            'text_count':text_result.get('text_count',0),'formula_count':0,
            'vision_used':True,'warning':None,
            'recognition_status':'partial' if incomplete else 'complete',
            'diagnostics':{'resource_metrics':text_result.get('resource_metrics',[]),
                           'layout_status':layout.get('status','unavailable'),
                           'correction':correction,'validation':issues,
                           'stages':result['diagnostics'],
                           'remote_metrics':result.get('remote_metrics',[]),
                           **({'stage_audit':result['stage_audit']} if 'stage_audit' in result else {})}}
