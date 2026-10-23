"""Real, serial Qwen versus one-slot GLM review experiment, opt-in only.

Both conditions run a fresh complete topology pipeline on the same originals.
There is no replay, shared model answer, or accuracy-based routing. Reports
retain failures and separately evaluate timing on all attempted conditions.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from graph_ab_metrics import compare_graphs, prf
from graph_hybrid_review import HybridReview, PROFILE
from graph_schema import canonical_graph
from graph_staged import Budget, recognize_staged
from graph_validation import audit_graph_records
from vision_provider import VisionProvider, VisionError
from scripts.benchmark_graph_vision import load_corpus, local_layout, operational_totals, resource_limits, sha


def execute(raw, condition, *, layout, review_seconds=25, candidate_limit=24):
    primary=VisionProvider('qwen',thinking=False,retries=0,capture=True)
    glm=VisionProvider('glm',model='glm-4.6v',thinking=False,retries=0,capture=True)
    router=HybridReview(glm,seconds=review_seconds,candidate_limit=candidate_limit) if condition=='hybrid' else None
    budget=Budget()  # Identical production-sized 155s / 7 calls / 45s for both.
    row={'condition':condition,'status':'not_run_missing_key','requests':[],
         'started_at':datetime.now(timezone.utc).isoformat()}
    if not primary.available() or router is not None and not glm.available():
        return {**row,'seconds':0.}
    start=time.monotonic()
    try:
        result=recognize_staged(raw,layout=layout,provider=primary,budget=budget,review_router=router)
        row['raw_result']=result
        graphs=result.get('graphs')
        if not isinstance(graphs,list):raise ValueError('invalid_graph_envelope')
        for index,graph in enumerate(graphs,1):canonical_graph(graph,index)
        row['mathematical_issues']=audit_graph_records(graphs)
        row['status']='success'
        observations=primary.observations+glm.observations
        errors=[r['error'] for r in observations if r.get('error')]
        if errors:row['status']=errors[0]
        elif primary.logical_calls+glm.logical_calls>len(observations):row['status']='budget_exhausted'
        elif any(d.startswith(('edge_read_failed:','local_review_failed','focused_arrow_review_failed',
                               'node_inventory_review_failed')) for d in result['diagnostics']):
            row['status']='invalid_stage_output'
    except VisionError as exc:row.update(status=exc.kind,http_status=exc.status)
    except TimeoutError:row['status']='budget_exhausted'
    except (ValueError,TypeError):row['status']='invalid_output'
    finally:
        row['seconds']=round(time.monotonic()-start,3)
        row['requests']=sorted(primary.observations+glm.observations,key=lambda r:r['started_at_unix'])
        row['hybrid_review_events']=router.events if router else []
        row['calls_remaining']=budget.remaining
        row['returned_model_versions']=sorted({r['returned_model'] for r in row['requests'] if r.get('returned_model')})
        row.update(operational_totals([row]))
    return row


def totals(rows, metric_key='metrics'):
    ms=[r[metric_key] for r in rows if r.get(metric_key,{}).get('status')=='scored']
    fields=('vertex_tp','expected_vertices','actual_vertices','edge_tp','actual_edges','expected_edges',
            'direction_correct','direction_expected','direction_trials','parallel_correct','parallel_trials',
            'weights_correct','weights_expected','weight_trials')
    result={k:sum(m.get(k,0) for m in ms) for k in fields}
    result.update(scored=len(ms),edge_set=prf(result['edge_tp'],result['actual_edges'],result['expected_edges']) if ms else None,
                  whole_correct=sum(m['whole_structure_correct'] for m in ms),
                  figure_count_correct=sum(m['figure_count_correct'] for m in ms),
                  figure_order_correct=sum(m['figure_order_correct'] is True for m in ms))
    return result


def write_reports(out, records, protocol):
    import csv
    groups={c:[r for r in records if r['condition']==c] for c in ('qwen','hybrid')}
    paired_ids=sorted(set(r['case_id'] for r in groups['qwen'] if r['status']=='success') &
                      set(r['case_id'] for r in groups['hybrid'] if r['status']=='success'))
    all_rows={c:{'accuracy':totals(rows),'operations':operational_totals(rows),
                 'status_counts':dict(Counter(r['status'] for r in rows)),
                 'median_seconds':statistics.median(r['seconds'] for r in rows) if rows else None,
                 'max_seconds':max((r['seconds'] for r in rows),default=None)} for c,rows in groups.items()}
    paired={c:totals([r for r in groups[c] if r['case_id'] in paired_ids]) for c in groups}
    accepted={c:totals([r for r in groups[c] if r['case_id'] in paired_ids],'accepted_metrics') for c in groups}
    report={'protocol':protocol,'paired_case_ids':paired_ids,'all_attempts':all_rows,
            'paired_accuracy':paired,'paired_accepted_diagnostic':accepted,'records':records}
    (out/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    fields=['case_id','condition','status','seconds','attempted_requests','sha256','edge_tp','actual_edges',
            'expected_edges','precision','recall','f1','vertex_tp','expected_vertices','direction_correct',
            'direction_expected','parallel_correct','parallel_trials','weights_correct','weights_expected',
            'whole_structure_correct','figure_count_correct','figure_order_correct']
    with (out/'details.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for row in records:
            m=row.get('metrics',{})
            values={**row,**m,**(m.get('edge_set') or {})}
            writer.writerow({k:values.get(k) for k in fields})
    lines=['# Qwen＋GLM限时复核真实测试','',
           '两条件均独立运行真实完整拓扑模块、真实远程API；没有回放或复用另一条件模型输出。',
           '同一原图、版面缓存、155秒/7次总预算，Qwen每次45秒。混合方案最多替换一个原有REVIEW调用，GLM限时25秒、零重试。',
           '平均耗时目标预设不超过单Qwen的1.2倍；全部失败保留，失败不给准确率分数。',
           '模块耗时不含双方共用的本地OCR预处理；未完成最新完整/ocr及Playwright验收。',
           '独立NODE/EDGE输出可能有波动；单次小样本不能把所有差值归因于复核模型。','',
           '|条件|成功/已尝试|同图配对边集F1|整图完全正确|全部平均秒|全部最大秒|',
           '|---|---|---|---|---|---|']
    for c in groups:
        a=paired[c];ops=all_rows[c]['operations'];f1=(a['edge_set'] or {}).get('f1')
        fmt=lambda x:'—' if x is None else f'{x:.1f}'
        lines.append(f"|{c}|{sum(r['status']=='success' for r in groups[c])}/{len(groups[c])}|{f'{f1:.1%}' if f1 is not None else '未评分'}|{a['whole_correct']}/{a['scored']}|{fmt(ops['mean_case_seconds'])}|{fmt(all_rows[c]['max_seconds'])}|")
    lines+=['','|原图|条件|状态|F1|耗时秒|','|---|---|---|---|---|']
    for r in records:
        f1=r.get('metrics',{}).get('edge_set',{}).get('f1')
        lines.append(f"|{r['case_id']}|{r['condition']}|{r['status']}|{f'{f1:.1%}' if f1 is not None else '未评分'}|{r['seconds']:.1f}|")
    (out/'comparison.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','output','layout-cache'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--case-ids',required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--stop-after',type=int,help='Pilot only the first N predeclared cases; resume the same protocol later')
    args=parser.parse_args();out=Path(args.output).resolve();repo=Path(__file__).resolve().parents[1]
    if out.is_relative_to(repo):parser.error('Keep private results outside the checkout')
    limits=resource_limits()
    if not limits['within_2cpu_4gib']:parser.error('Live test requires 2 CPU / 4 GiB container limits')
    _,cases,_=load_corpus(args.manifest);requested=args.case_ids.split(',')
    by_id={c['id']:c for c in cases}
    if len(set(requested))!=len(requested) or set(requested)-set(by_id):parser.error('Invalid/duplicate cases')
    cases=[by_id[cid] for cid in requested]
    if args.stop_after is not None and not 1<=args.stop_after<=len(cases):parser.error('Invalid pilot size')
    if any(c['truth'].get('reference_status')!='complete' for c in cases):parser.error('Independent complete references required')
    if not VisionProvider('qwen').available() or not VisionProvider('glm',model='glm-4.6v').available():
        parser.error('Both configured API keys required; no calls executed')
    tracked=['graph_staged.py','graph_hybrid_review.py','graph_glm_adapter.py','vision_provider.py',
             'graph_line_tracer.py','graph_relation.py','graph_schema.py','graph_ab_metrics.py','ai.py',
             'scripts/benchmark_graph_hybrid.py']
    code_hash=sha(b''.join((repo/p).read_bytes() for p in tracked))
    try:source_commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    except (OSError,subprocess.CalledProcessError):source_commit=os.environ.get('DMATE_BENCHMARK_COMMIT')
    protocol={'profile':PROFILE,'code_sha256':code_hash,'source_commit':source_commit,
              'case_ids':requested,'resource_limits':limits,'time_budget':{'total':155,'calls':7,'qwen_call':45,'glm_review':25},
              'candidate_limit':24,'thinking':False,'retries':0,'latency_target_ratio':1.2,
              'condition_order':'qwen/hybrid then hybrid/qwen, alternating by requested case order'}
    out.mkdir(parents=True,exist_ok=True)
    protocol_file=out/'protocol.json'
    if protocol_file.exists() and json.loads(protocol_file.read_text())!=protocol:parser.error('Resume protocol/source mismatch')
    protocol_file.write_text(json.dumps(protocol,ensure_ascii=False,indent=2))
    records=[]
    for index,c in enumerate(cases[:args.stop_after] if args.stop_after else cases):
        raw=c['path'].read_bytes();started=time.monotonic();prepared=local_layout(raw,Path(args.layout_cache))
        preprocessing_seconds=time.monotonic()-started
        if any(m['status']!='ok' for m in prepared.get('resource_metrics',[])):raise RuntimeError('local_preprocessing_failed')
        layout=prepared.get('layout',{}).get('regions',[])
        identity={'case_id':c['id'],'sha256':c['sha256'],'category':c.get('category'),
                  'ground_truth_sha256':sha(json.dumps(c['truth'],sort_keys=True).encode()),
                  'layout_sha256':sha(json.dumps(layout,sort_keys=True).encode()),'code_sha256':code_hash}
        for condition in (('qwen','hybrid') if index%2==0 else ('hybrid','qwen')):
            target=out/f"{c['id']}-{condition}.json";fingerprint=sha(json.dumps({**protocol,**identity,'condition':condition},sort_keys=True).encode())
            if target.exists():
                if not args.resume:parser.error('Existing result; use a new directory or --resume')
                row=json.loads(target.read_text())
                if row.get('fingerprint')!=fingerprint:parser.error('Resume result mismatch')
            else:
                row=execute(raw,condition,layout=layout)
                row.update(identity,fingerprint=fingerprint,preprocessing_seconds=preprocessing_seconds,
                           preprocessing_cache_hit=prepared.get('benchmark_cache_hit'))
                if row['status']=='success':
                    row['metrics']=compare_graphs(c['truth']['graphs'],row['raw_result']['graphs'])
                    accepted=[{**g,'edges':[e for e in g['edges'] if e.get('status')=='accepted']}
                              for g in row['raw_result']['graphs']]
                    row['accepted_metrics']=compare_graphs(c['truth']['graphs'],accepted)
                else:row['metrics']={'status':'not_scored_operational_failure'}
                target.write_text(json.dumps(row,ensure_ascii=False,indent=2))
            records.append(row);write_reports(out,records,protocol)
            print(c['id'],condition,row['status'],row['seconds'],
                  row.get('metrics',{}).get('edge_set',{}).get('f1'),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
