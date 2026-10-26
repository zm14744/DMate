"""Real reciprocal hybrids with fresh primary calls and controlled prefix pairs.

Each primary runs its unchanged complete topology pipeline once. Keep that
actual result as control, then run at most one opt-in, role-specific specialist
within the same 155s / 7-call budget. Private data must remain outside checkout.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graph_ab_metrics import compare_graphs
from graph_attribute_review import AttributeReview, PROFILE as ATTRIBUTE_PROFILE
from graph_topology_review import TopologyReview, PROFILE as TOPOLOGY_PROFILE
from graph_staged import Budget, recognize_staged
from graph_validation import audit_graph_records
from scripts.benchmark_graph_hybrid import totals
from scripts.benchmark_graph_vision import load_corpus, local_layout, operational_totals, resource_limits, sha
from vision_provider import VisionProvider, VisionError


def provider(name):
    return (VisionProvider('qwen', thinking=False, retries=0, capture=True) if name == 'qwen'
        else VisionProvider('glm', model='glm-5.3-flash', thinking=True,
                            reasoning_effort='low', retries=0, capture=True))


def execute(raw, primary_name, layout):
    primary = provider(primary_name)
    secondary = provider('glm' if primary_name == 'qwen' else 'qwen')
    specialist = AttributeReview(secondary) if primary_name == 'qwen' else TopologyReview(secondary)
    row = {'primary': primary_name, 'model': primary.model, 'secondary_model': secondary.model,
        'profile': ATTRIBUTE_PROFILE if primary_name == 'qwen' else TOPOLOGY_PROFILE,
        'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'not_run_missing_key',
        'primary_status': 'not_run', 'requests': [], 'seconds': 0., 'primary_seconds': 0.}
    if not primary.available() or not secondary.available():
        return row
    budget = Budget()
    start = time.monotonic()
    try:
        result = recognize_staged(raw, layout=layout, provider=primary, budget=budget, specialist=specialist)
        row['raw_result'] = result
        errors = [q.get('error') for q in primary.observations if q.get('error')]
        stage_errors = [d for d in result['diagnostics'] if d.startswith(('edge_read_failed:',
            'local_review_failed', 'focused_arrow_review_failed', 'node_inventory_review_failed'))]
        if errors:
            row.update(status='primary_failure', primary_status=errors[0])
        elif stage_errors or primary.logical_calls > len(primary.observations):
            row.update(status='primary_failure', primary_status='incomplete_primary_stage')
        else:
            row.update(status='success', primary_status='success')
            if any(e.get('status') == 'failed' for e in specialist.events):
                row['status'] = 'degraded_specialist_failure'
            row['primary_graphs'] = copy.deepcopy(specialist.primary_graphs)
            row['mathematical_issues'] = audit_graph_records(result['graphs'])
    except VisionError as exc:
        row.update(status='primary_failure', primary_status=exc.kind)
    except TimeoutError:
        row.update(status='primary_failure', primary_status='budget_exhausted')
    except (ValueError, TypeError) as exc:
        row.update(status='primary_failure', primary_status=type(exc).__name__)
    finally:
        row['seconds'] = round(time.monotonic()-start, 3)
        row['primary_seconds'] = (round(specialist.primary_finished_at-start, 3)
            if specialist.primary_finished_at is not None else row['seconds'])
        row['specialist_seconds'] = round(row['seconds']-row['primary_seconds'], 3)
        row['requests'] = sorted(primary.observations+secondary.observations, key=lambda q: q['started_at_unix'])
        row['primary_request_count'], row['secondary_request_count'] = len(primary.observations), len(secondary.observations)
        row['specialist_events'] = specialist.events
        row['calls_remaining'] = budget.remaining
        row.update(operational_totals([row]))
    return row


def aggregate(rows, metric_key):
    result = totals(rows, metric_key)
    scored = [r[metric_key] for r in rows if r.get(metric_key, {}).get('status') == 'scored']
    result['macro_f1'] = statistics.mean(m['edge_set']['f1'] for m in scored) if scored else None
    return result


def write_reports(out, rows, protocol):
    groups = {p: [r for r in rows if r['primary'] == p] for p in ('qwen', 'glm')}
    common = sorted(set(r['case_id'] for r in groups['qwen'] if r['primary_status'] == 'success') &
                    set(r['case_id'] for r in groups['glm'] if r['primary_status'] == 'success'))
    scores, operations = {}, {}
    for p, rr in groups.items():
        pair = [r for r in rr if r['case_id'] in common]
        scores[p] = {k: aggregate(pair, k) for k in ('baseline_metrics', 'metrics',
            'baseline_accepted_metrics', 'accepted_metrics')}
        requests = [q for r in rr for q in r['requests']]
        operations[p] = {'all_attempts': operational_totals(rr),
            'primary_mean_seconds': statistics.mean(r['primary_seconds'] for r in rr) if rr else None,
            'median_seconds': statistics.median(r['seconds'] for r in rr) if rr else None,
            'max_seconds': max((r['seconds'] for r in rr), default=None),
            'status_counts': dict(Counter(r['status'] for r in rr)),
            'specialist_routed_cases': sum(any(e.get('routed') for e in r['specialist_events']) for r in rr),
            'specialist_failed_cases': sum(any(e.get('status') == 'failed' for e in r['specialist_events']) for r in rr),
            'http_429_count': sum(q.get('http_status') == 429 for q in requests),
            'confirmed_timeout_count': sum(q.get('confirmed_timeout') is True for q in requests),
            'request_error_counts': dict(Counter(q['error'] for q in requests if q.get('error')))}
        op = operations[p]
        op['mean_latency_ratio_over_same_primary'] = (op['all_attempts']['mean_case_seconds']/op['primary_mean_seconds']
            if op['primary_mean_seconds'] else None)
    summary = {'protocol': protocol, 'common_completed_case_ids': common, 'paired_scores': scores,
        'operations': operations, 'all_actual_operations': operational_totals(rows),
        'within_primary_scores': {p: {k: aggregate(rr, k) for k in ('baseline_metrics', 'metrics')}
                                  for p, rr in groups.items()},
        'billing': 'Actual usage only; GLM 5.3 tariff and invoices unverified. No free-inference assumption.',
        'recommendation': 'Requires independent-reference error review; no automatic production selection.'}
    (out/'comparison.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    details, errors = [], []
    for r in rows:
        for control, key in ((True, 'baseline_metrics'), (False, 'metrics')):
            m = r.get(key, {})
            details.append({'case_id': r['case_id'], 'sha256': r['sha256'], 'primary': r['primary'],
                'condition': 'same_actual_primary_control' if control else 'with_specialist',
                'status': r['primary_status'] if control else r['status'],
                'seconds': r['primary_seconds'] if control else r['seconds'],
                **(m.get('edge_set') or {}), **{k: m.get(k) for k in ('vertex_tp', 'expected_vertices',
                    'edge_tp', 'actual_edges', 'expected_edges', 'direction_correct', 'direction_expected',
                    'parallel_correct', 'parallel_trials', 'weights_correct', 'weights_expected',
                    'whole_structure_correct', 'figure_count_correct', 'figure_order_correct')}})
            errors.append({'case_id': r['case_id'], 'primary': r['primary'], 'control': control,
                'status': r['primary_status'] if control else r['status'], 'metrics': m,
                'specialist_events': [] if control else r['specialist_events']})
    (out/'per-image-errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2))
    fields = list(dict.fromkeys(k for r in details for k in r))
    with (out/'details.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(details)
    pct = lambda v: '未评分' if v is None else f'{v:.1%}'
    lines = ['# Qwen主导 / GLM-5.3-Flash主导：限时互补真实测试', '',
        '两种主模型各自新鲜独立运行；每次保存实际主模型输出作对照，再运行至多一次局部专家。',
        '对照与混合共享同一次真实主流程，不将重放或估算时间冒充两次独立端到端调用。混合墙钟是实际主流程加实际复核时间。',
        'Qwen主导：保留复杂拓扑/重边，只让GLM low填未决权值或像素支持的未知箭头，最多8条。',
        'GLM主导：保留带权图，Qwen关闭思考复核一个小型无权子图，最多16个现有候选，经同一TRACE/RELATE检查，可复核类型和重数。',
        '这是两种职责优化方案的比较，局部提示和候选上限不同；主模型沿用各自既有适配。总预算相同155秒/7次，主调用45秒，局部20秒，串行零重试。',
        '局部失败保留真实主结果，标记degraded并单独统计API失败；主流程失败不评分。没有将失败当漏边或丢弃。',
        '参考来自固定独立视觉核验，不用被测模型答案；开发样本单次试验，非第三方人工标注/独立留出集。',
        '同图公平比较使用两种主流程均完成的交集。机制测试、HTTP200不能替代真实准确率。', '',
        '|同图条件|有效图|边集F1|箭头正确/全部|权值正确/全部|严格整图正确|',
        '|---|---|---|---|---|---|']
    for p in groups:
        for key in ('baseline_metrics', 'metrics'):
            a = scores[p][key]
            lines.append(f"|{p} {'单模型对照' if key=='baseline_metrics' else '主导混合'}|{len(common)}|{pct((a['edge_set'] or {}).get('f1'))}|{a['direction_correct']}/{a['direction_expected']}|{a['weights_correct']}/{a['weights_expected']}|{a['whole_correct']}/{len(common)}|")
    lines += ['', '|主模型|全部平均秒|原主流程平均秒|平均增幅|局部触发/尝试|局部失败|', '|---|---|---|---|---|---|']
    for p, o in operations.items():
        if not groups[p]: continue
        lines.append(f"|{p}|{o['all_attempts']['mean_case_seconds']:.1f}|{o['primary_mean_seconds']:.1f}|{o['mean_latency_ratio_over_same_primary']-1:.1%}|{o['specialist_routed_cases']}/{len(groups[p])}|{o['specialist_failed_cases']}|")
    lines += ['', '|原图|主模型|条件|状态|F1|秒|', '|---|---|---|---|---|---|']
    for r in details:
        lines.append(f"|{r['case_id']}|{r['primary']}|{r['condition']}|{r['status']}|{pct(r.get('f1'))}|{r['seconds']:.1f}|")
    lines += ['', '费用以逐请求真实usage计数：对照与混合不重复计费。缺失usage保持未知，不用4.6V单价套5.3 Flash。',
        '本测试为真实远程API+拓扑模块，不含共享PP预处理；未执行最新完整/ocr与Playwright、生产流量验收。',
        '未合并main、部署Zeabur、修改生产数据库或生产默认模型。', '']
    (out/'comparison.md').write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'output', 'layout-cache', 'case-ids'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--stop-after', type=int)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    out = Path(args.output).resolve()
    if out.is_relative_to(repo): parser.error('Private data must stay outside checkout')
    if not resource_limits()['within_2cpu_4gib']: parser.error('Live tests require 2 CPU / 4 GiB container')
    _, all_cases, _ = load_corpus(args.manifest)
    requested = args.case_ids.split(','); by_id = {c['id']: c for c in all_cases}
    if len(set(requested)) != len(requested) or set(requested)-by_id.keys(): parser.error('Invalid case IDs')
    cases = [by_id[cid] for cid in requested]
    if args.stop_after is not None and not 1 <= args.stop_after <= len(cases): parser.error('Invalid pilot count')
    if any(c['truth'].get('reference_status') != 'complete' for c in cases): parser.error('Independent complete references required')
    if not all(provider(p).available() for p in ('qwen', 'glm')): parser.error('Both configured keys required')
    tracked = sorted({p for p in repo.glob('graph_*.py')} | {repo/'vision_provider.py', repo/'ai.py', Path(__file__)})
    code_hash = sha(b''.join(p.read_bytes() for p in tracked))
    try: commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    except (OSError, subprocess.CalledProcessError): commit = os.environ.get('DMATE_BENCHMARK_COMMIT')
    protocol = {'source_commit': commit, 'code_sha256': code_hash, 'case_ids': requested,
        'profiles': [ATTRIBUTE_PROFILE, TOPOLOGY_PROFILE], 'resource_limits': resource_limits(),
        'seconds': 155, 'max_calls': 7, 'primary_call_seconds': 45, 'specialist_seconds': 20,
        'retries': 0, 'serial': True, 'latency_target_ratio_over_primary': 1.2,
        'control_design': 'Same fresh actual primary prefix; no repeated calls or duplicated usage.'}
    out.mkdir(parents=True, exist_ok=True)
    plan = out/'protocol.json'
    if plan.exists() and json.loads(plan.read_text()) != protocol: parser.error('Protocol/source mismatch')
    plan.write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    rows = []
    for i, case in enumerate(cases[:args.stop_after] if args.stop_after else cases):
        prepared = local_layout(case['path'].read_bytes(), Path(args.layout_cache))
        if any(m['status'] != 'ok' for m in prepared.get('resource_metrics', [])): raise RuntimeError('Local preprocessing failed')
        layout = prepared.get('layout', {}).get('regions', [])
        identity = {'case_id': case['id'], 'sha256': case['sha256'],
            'ground_truth_sha256': sha(json.dumps(case['truth'], sort_keys=True).encode()),
            'layout_sha256': sha(json.dumps(layout, sort_keys=True).encode()), 'code_sha256': code_hash}
        for p in (('qwen', 'glm') if i % 2 == 0 else ('glm', 'qwen')):
            target = out/f"{case['id']}-{p}-primary.json"
            fingerprint = sha(json.dumps({**protocol, **identity, 'primary': p}, sort_keys=True).encode())
            if target.exists():
                if not args.resume: parser.error('Existing result: use resume or new directory')
                row = json.loads(target.read_text())
                if row.get('fingerprint') != fingerprint: parser.error('Resume fingerprint mismatch')
            else:
                row = execute(case['path'].read_bytes(), p, layout)
                row.update(identity, fingerprint=fingerprint)
                for field, graphs in (('baseline_metrics', row.get('primary_graphs')),
                                      ('metrics', row.get('raw_result', {}).get('graphs'))):
                    row[field] = (compare_graphs(case['truth']['graphs'], graphs)
                        if row['primary_status'] == 'success' else {'status': 'not_scored_primary_failure'})
                    if row['primary_status'] == 'success':
                        accepted = [{**g, 'edges': [e for e in g['edges'] if e.get('status') == 'accepted']} for g in graphs]
                        row['baseline_accepted_metrics' if field == 'baseline_metrics' else 'accepted_metrics'] = compare_graphs(case['truth']['graphs'], accepted)
                target.write_text(json.dumps(row, ensure_ascii=False, indent=2))
            rows.append(row); write_reports(out, rows, protocol)
            print(case['id'], p, row['status'], row['seconds'],
                  (row['baseline_metrics'].get('edge_set') or {}).get('f1'),
                  (row['metrics'].get('edge_set') or {}).get('f1'), flush=True)
    return 0


if __name__ == '__main__': raise SystemExit(main())
