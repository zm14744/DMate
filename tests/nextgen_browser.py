"""Four-image OCR task-card/editor contract OR explicit original-image API regression.
Contract mode mocks /ocr and NEVER grades recognition accuracy. Live mode uses
only a local branch server, not production. Original bytes must match SHA256.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
import networkx as nx
from playwright.sync_api import sync_playwright
from graph_schema import canonical_graph,display_graph
from ocr_regression import run_case

BANNED=['图形结构待核对','首次识别的图形候选','识别说明（结构化边表尚未核实）',
        '多图边集已二次核对','结构已列出（仍需以原图核对）']


def semantic_graph_equal(want,got):
    cls=nx.MultiDiGraph if want.get('directed') is True else nx.MultiGraph
    def build(g,expected=False):
        network=cls()
        for v in g.get('vertices',[]):
            v={'id':v,'label':v} if isinstance(v,str) else v
            network.add_node(str(v['id']),label=str(v.get('label') or v['id']))
        for e in g.get('edges',[]):
            if not expected and e.get('direction')=='unknown': return None
            if not expected and e.get('direction') not in (None, 'forward' if want.get('directed') is True else 'undirected'):
                return None
            if e.get('from') not in network or e.get('to') not in network: return None
            network.add_edge(e['from'],e['to'],weight=str(e.get('weight')),edge_label=str(e.get('edge_label')))
        return network
    a,b=build(want,True),build(got)
    if a is None or b is None or got.get('directed') is not want.get('directed'): return False
    node_match=None if want.get('match_mode')=='isomorphic' else nx.algorithms.isomorphism.categorical_node_match('label',None)
    def edge_match(x,y):
        from collections import Counter
        return Counter((e['weight'],e['edge_label']) for e in x.values())==Counter((e['weight'],e['edge_label']) for e in y.values())
    return nx.is_isomorphic(a,b,node_match=node_match,edge_match=edge_match)


def grade(case,response,record):
    actual=response.get('graph_display_data') or []; expected=case['expected']['graphs']
    visible=(record.get('rendered') or {}).get('graph','')
    equal=len(actual)==len(expected) and all(semantic_graph_equal(w,g) for w,g in zip(expected,actual))
    exact=case.get('expected_question_text')
    verified=case.get('reference_status','complete')=='complete'
    return {'点和边':('通过' if equal else '不通过') if verified else '无法核实',
            '题目文字':('通过' if response.get('text','')==exact else '不通过') if exact is not None else '无法核实',
            '数学公式及界面渲染':'部分通过' if record.get('operational_ok') else '不通过',
            '图形描述':('部分通过' if equal and visible else '不通过') if verified else '无法核实',
            '描述统一':'通过' if visible and not any(w in visible for w in BANNED) else '不通过',
            '图形分隔':('通过' if equal else '不通过') if verified else '无法核实'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['contract','live'],required=True)
    parser.add_argument('--base-url',default='http://127.0.0.1:8080');parser.add_argument('--output',required=True)
    parser.add_argument('--manifest',default='tests/real_graph_corpus/manifest.json',
                        help='May point to a private corpus outside the checkout')
    parser.add_argument('--case-ids',help='Comma-separated original case IDs; omitted means all cases')
    parser.add_argument('--capture-only',action='store_true',
                        help='Collect actual JSON/dialog before complete independent annotation; never grades accuracy')
    parser.add_argument('--browser-executable',help='Use an existing Chromium installation')
    parser.add_argument('--cdn-cache',help='Optional TLS-verified cache of pinned public CDN scripts; never intercepts /ocr')
    args=parser.parse_args()
    if urlsplit(args.base_url).hostname not in ('127.0.0.1','localhost'): raise SystemExit('Only an isolated local branch server is allowed')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    if args.mode=='live':
        from scripts.graph_corpus import validate_corpus,safe_child
        manifest_path=Path(args.manifest).resolve()
        issues=validate_corpus(manifest_path,full=not args.capture_only,require_results=False)
        if issues:
            (out/'report.json').write_text(json.dumps({'mode':'live','status':'blocked_missing_original_corpus',
                'recognition_accuracy_test':False,'issues':issues},ensure_ascii=False,indent=2))
            print('Full regression blocked: original conversation corpus has not been completely imported')
            return 2
        corpus=json.loads(manifest_path.read_text());cases=[]
        for row in corpus['cases']:
            truth={} if args.capture_only else json.loads(safe_child(manifest_path.parent,row['ground_truth']).read_text())
            cases.append({'id':row['id'],'image':str(safe_child(manifest_path.parent,row['image'])),
                          'source_sha256':row['sha256'],'expected':truth.get('expected',{}),
                          'reference_status':truth.get('reference_status','complete' if truth else 'unverified'),
                          **({'expected_question_text':truth['expected_question_text']} if 'expected_question_text' in truth else {})})
    else:
        cases=json.loads(Path('tests/fixtures/ouc_two_originals_gold.json').read_text())['cases']
    if args.case_ids:
        selected=set(args.case_ids.split(','))
        if selected-{case['id'] for case in cases}: raise SystemExit('Unknown case ID')
        cases=[case for case in cases if case['id'] in selected]
    if not cases: raise SystemExit('No original cases selected')
    server=None; log=None
    if args.mode=='contract':
        env=os.environ.copy();env.update(DMATE_GRAPH_NEXTGEN='1',PORT=str(urlsplit(args.base_url).port or 8080),
                                         DASHSCOPE_API_KEY='',DASHSCOPE_VISION_API_KEY='',DEEPSEEK_API_KEY='')
        log=(out/'server.log').open('w')
        server=subprocess.Popen([sys.executable,'app.py'],env=env,stdout=log,stderr=log)
    report={'mode':args.mode,'recognition_accuracy_test':args.mode=='live' and not args.capture_only,
            'capture_only':args.capture_only,'cases':[]}
    try:
        for _ in range(80):
            try:
                if requests.get(args.base_url+'/health',timeout=1).ok: break
            except requests.RequestException: pass
            time.sleep(.5)
        else: raise RuntimeError('branch server not ready')
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,**({'executable_path':args.browser_executable} if args.browser_executable else {}))
            for case in cases:
                image=Path('tests/fixtures/original_ouc_20261021')/case['image']
                digest=hashlib.sha256(image.read_bytes()).hexdigest()
                if digest!=case['source_sha256']: raise RuntimeError('original hash mismatch')
                input_case=copy.deepcopy(case)
                if args.mode=='contract':
                    graphs=[]
                    for idx,g in enumerate(input_case['expected']['graphs'],1):
                        g['complete']=True
                        for e in g['edges']: e['status']='accepted'
                        graphs.append(display_graph(canonical_graph(g,idx)))
                    input_case['expected']['graphs']=graphs
                    input_case['mock_text']='核对图形：\\(\\kappa(G)\\)'
                    input_case['mock_visual']='contract fixture, not recognition result'
                record=run_case(browser,input_case,args.base_url,image,out,
                                'mock' if args.mode=='contract' else 'live',False,290,cdn_cache=args.cdn_cache)
                record['source_sha256']=digest
                if args.mode=='live' and not args.capture_only:
                    response_path=out/(case['id']+'-ocr-response.json')
                    response=json.loads(response_path.read_text()) if response_path.exists() else {}
                    record['six_dimensions']=grade(case,response,record)
                elif args.mode=='contract':
                    shown=record.get('rendered') or {}
                    visible=shown.get('graph','')
                    panels=len(input_case['expected']['graphs'])
                    record['contract_ok']=bool(
                        record['operational_ok']
                        and shown.get('renderer')=='editable_graph_editor'
                        and shown.get('editor_graph_count')==panels
                        and record.get('task_summary','').startswith(f'{panels} 幅子图')
                        and visible and not any(x in visible for x in BANNED))
                    record['semantic_status']='NOT_AN_ACCURACY_TEST'
                else:
                    record['semantic_status']='UNVERIFIED_CAPTURE_ONLY'
                report['cases'].append(record)
            browser.close()
    finally:
        if server: server.terminate();server.wait(timeout=10)
        if log: log.close()
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if args.mode=='contract': return 0 if all(r.get('contract_ok') for r in report['cases']) else 1
    if args.capture_only: return 0 if all(r.get('operational_ok') for r in report['cases']) else 1
    # Missing text/formula annotation and manual UI review are acceptance blockers.
    return 0 if all(all(v=='通过' for v in r['six_dimensions'].values()) for r in report['cases']) else 2


if __name__=='__main__': raise SystemExit(main())
