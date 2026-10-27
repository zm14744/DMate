"""Real Chromium/Flask contract for four independent editable image tasks.

The generated pictures and injected model/heavy-worker transports are synthetic.
Real HTTP upload, the fast LangGraph pipeline, schema/NetworkX checks, editor,
confirmation registry and solver route run. This never measures image accuracy
or certifies the 120-second production performance target.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_ocr_application_upload import (SENTINEL, clean_child_environment,
    private_directory, wait_file, write_bytes)
from scripts.verify_graph_first_pass_ui import _cached_asset


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def fixture_document(case):
    return {'body_text': f'Synthetic {case}. Find vertex degrees.', 'graphs': [{
        'id': 'G', 'name': 'Synthetic '+case,
        'vertices': [{'id': 'a', 'label': case+'-a'}, {'id': 'b', 'label': case+'-b'},
                     {'id': 'c', 'label': case+'-c'}],
        'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'undirected', 'weight': 2,
                   'style': 'solid', 'color': 'black'},
                  {'id': 'e2', 'from': 'b', 'to': 'c', 'direction': 'undirected', 'weight': 3,
                   'style': 'solid', 'color': 'black'}]}], 'uncertainties': []}


def make_images(folder):
    from PIL import Image, ImageDraw
    rows = []
    for index, case in enumerate('ABCD'):
        image = Image.new('RGBA', (400+index*20, 240), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.text((15, 15), 'SYNTHETIC '+case+' - EDITABLE UI CONTRACT', fill='black')
        draw.line((75, 150, 300, 150), fill='black', width=3)
        for x, label in ((75, 'a'), (185, 'b'), (300, 'c')):
            draw.ellipse((x-7, 143, x+7, 157), fill='white', outline='black', width=2)
            draw.text((x, 168), case+'-'+label, fill='black')
        stream = io.BytesIO(); image.save(stream, format='PNG')
        raw = stream.getvalue(); path = folder/(case+'.png'); write_bytes(path, raw)
        rows.append({'case': case, 'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
    return rows


def child_environment(folder):
    env = clean_child_environment(folder)
    env.update(DMATE_GRAPH_PIPELINE='agent-tools',
               DMATE_GRAPH_CONFIRMATION_DB=str(folder/'confirmations.sqlite3'))
    return env


def serve(folder):
    import socket
    import smtplib
    import requests
    from flask import request, g
    from werkzeug.serving import make_server, WSGIRequestHandler
    folder = Path(folder).resolve()
    expected = child_environment(folder)
    if (set(os.environ)-set(expected)-{'LC_CTYPE'} or
            os.environ.get('DASHSCOPE_API_KEY') != SENTINEL):
        raise ValueError('Synthetic child environment is not isolated')
    lock = threading.RLock()
    ledger = {'fixture_only': True, 'external_model_sends': 0, 'guards': [], 'events': [],
              'requests': [], 'active_visual': 0, 'max_active_visual': 0,
              'active_heavy_worker': 0, 'max_active_heavy_worker': 0}
    identities = {}

    def event(kind, **values):
        row = {'kind': kind, 'monotonic': time.monotonic(), **values}
        with lock:
            ledger['events'].append(row)
            with (folder/'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False)+'\n')

    def forbidden(kind):
        def deny(*args, **kwargs):
            with lock: ledger['guards'].append(kind)
            raise RuntimeError('Synthetic isolation blocked '+kind)
        return deny

    requests.sessions.Session.send = forbidden('external_http')
    socket.socket.connect = forbidden('socket_connect')
    socket.socket.connect_ex = forbidden('socket_connect_ex')
    smtplib.SMTP = forbidden('smtp'); smtplib.SMTP_SSL = forbidden('smtp_ssl')
    try:
        import psycopg
        psycopg.connect = forbidden('database')
    except ImportError:
        pass
    import app as application
    import ai
    import ocr_runtime
    import graph_semantic_text
    from vision_provider import VisionProvider
    if application.AUTH_CONFIGURED or application.TRUSTED_PROXY_CIDRS:
        raise ValueError('Unexpected production account configuration')
    graph_semantic_text._cache_readiness = lambda: {
        'status': 'ready', 'worker_started': False, 'fixture_only': True}

    def worker(stage, image_path, output_path, **kwargs):
        from PIL import Image
        with lock:
            ledger['active_heavy_worker'] += 1
            ledger['max_active_heavy_worker'] = max(ledger['max_active_heavy_worker'], ledger['active_heavy_worker'])
        try:
            event('injected_heavy_worker', stage=stage)
            with Image.open(image_path) as image: width, height = image.size
            time.sleep(.05)
            metric = {'stage': stage, 'status': 'ok', 'seconds': .05,
                      'fixture_only': True, 'peak_rss_bytes': None, 'rss_observed': False}
            if stage == 'layout':
                return {'status': 'ok', 'model': 'PP-DocLayoutV3', 'regions': []}, metric
            if stage == 'text':
                return {'text': '', 'front_text': '', 'text_count': 0, 'formula_count': 0,
                    'review_regions': [], 'text_evidence': {'image_size': [width, height],
                    'coordinate_space': 'canonical_image_pixels', 'body': [],
                    'graph_labels': [], 'uncertain': [], 'noise': []}}, metric
            raise AssertionError('Unexpected heavy stage '+stage)
        finally:
            with lock: ledger['active_heavy_worker'] -= 1
    ocr_runtime.run_worker = worker
    original_call = VisionProvider.__call__

    def provider_call(self, prompt, images, budget):
        task_id = budget.metrics.task_id
        with lock: identity = copy.deepcopy(identities[task_id])
        case = identity['case']

        def transport(payload, headers, **kwargs):
            if self.name != 'qwen':
                raise AssertionError('Synthetic complete drafts must not request GLM')
            with lock:
                ledger['active_visual'] += 1
                ledger['max_active_visual'] = max(ledger['max_active_visual'], ledger['active_visual'])
            event('visual_entered', task_id=task_id, case=case)
            try:
                deadline = time.monotonic()+45
                while not (folder/('release_'+case)).exists():
                    if time.monotonic() >= deadline: raise TimeoutError('Synthetic release deadline')
                    time.sleep(.02)
                if case == 'C': return 400, {}, {'error': {'message': 'Synthetic model failure'}}
                return 200, {}, {'model': 'qwen3-vl-plus', 'choices': [{
                    'finish_reason': 'stop', 'message': {'content': json.dumps(fixture_document(case))}}]}
            finally:
                event('visual_exited', task_id=task_id, case=case)
                with lock: ledger['active_visual'] -= 1
        self.transport = transport
        return original_call(self, prompt, images, budget)
    VisionProvider.__call__ = provider_call

    def text_transport(messages, **kwargs):
        event('solver_boundary', messages=copy.deepcopy(messages))
        return {'ok': True, 'content': '合成测试回复：已读取用户确认的结构。',
                'choice': {'finish_reason': 'stop'}, 'model': 'deepseek-flash'}
    ai._request_text_completion = text_transport

    @application.app.before_request
    def observe_request():
        g.contract_started = time.monotonic()
        if request.path == '/ocr':
            uploaded = request.files.get('image')
            raw = uploaded.read(); uploaded.stream.seek(0)
            case = Path(uploaded.filename).stem
            if case not in 'ABCD' or len(case) != 1: raise ValueError('Unexpected synthetic image')
            row = {'case': case, 'request_id': request.form['request_id'],
                   'image_sha256': hashlib.sha256(raw).hexdigest(), 'image_bytes': len(raw)}
            with lock: identities[row['request_id']] = row
            event('upload_started', **row)

    @application.app.after_request
    def observe_response(response):
        if request.path not in ('/ocr', '/ocr/cancel', '/graph/confirm', '/chat'): return response
        body = request.get_json(silent=True) if request.is_json else None
        raw = response.get_data()
        row = {'path': request.path, 'status': response.status_code,
               'started': getattr(g, 'contract_started', None), 'finished': time.monotonic(),
               'request': copy.deepcopy(body), 'response': response.get_json(silent=True)}
        if request.path == '/ocr':
            with lock: row.update(identities.get(request.form.get('request_id'), {}))
        with lock:
            row['response_file'] = f"http-response-{len(ledger['requests'])+1:03d}.bin"
            row['response_sha256'] = hashlib.sha256(raw).hexdigest()
            write_bytes(folder/row['response_file'], raw)
            ledger['requests'].append(row)
        event('http_finished', path=request.path, status=response.status_code,
              case=row.get('case'), request_id=row.get('request_id'))
        return response

    class Quiet(WSGIRequestHandler):
        def log_request(self, *args, **kwargs): pass
    server = make_server('127.0.0.1', 0, application.app, threaded=True, request_handler=Quiet)
    write_json(folder/'server.json', {'url': f'http://127.0.0.1:{server.server_port}',
                                     'pid': os.getpid(), 'fixture_only': True})
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        while not (folder/'stop').exists(): time.sleep(.05)
    finally:
        for case in 'ABCD': (folder/('release_'+case)).touch()
        server.shutdown(); thread.join(5); server.server_close()
        with lock: write_json(folder/'server_report.json', ledger)


@contextmanager
def isolated_server(output):
    folder = output/'server'; folder.mkdir()
    with (folder/'process.log').open('xb') as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', str(folder)],
            cwd=ROOT, env=child_environment(folder), stdout=log, stderr=log)
        try:
            info = wait_file(folder/'server.json', timeout=40)
            yield info['url'], folder
        finally:
            for case in 'ABCD': (folder/('release_'+case)).touch()
            (folder/'stop').touch()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=5)


def events(folder):
    path = folder/'events.jsonl'
    if not path.exists(): return []
    rows = []
    for line in path.read_text().splitlines():
        try: rows.append(json.loads(line))
        except ValueError: pass
    return rows


def wait_events(page, folder, predicate, timeout=30):
    until = time.monotonic()+timeout
    while time.monotonic() < until:
        rows = events(folder)
        if predicate(rows): return rows
        page.wait_for_timeout(30)
    raise TimeoutError('Expected synthetic server events were not observed')


def run(output, browser, cache):
    from playwright.sync_api import sync_playwright
    output = private_directory(output)
    rows = make_images(output)
    report = {'kind': 'synthetic_four_image_editing_contract', 'fixture_only': True,
              'actual_browser': True, 'recognition_accuracy_test': False,
              'production_performance_test': False, 'external_model_sends': 0,
              'checks': [], 'errors': [], 'network': {'blocked': [], 'cached_assets': []}}
    def check(name, condition):
        report['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition: raise AssertionError(name)
    try:
        with isolated_server(output) as (base, folder), sync_playwright() as playwright:
            chromium = playwright.chromium.launch(executable_path=str(browser), headless=True, args=['--no-sandbox'])
            context = chromium.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
            origin = urlsplit(base).netloc
            def route_request(route):
                parsed = urlsplit(route.request.url)
                if parsed.scheme == 'http' and parsed.netloc == origin: return route.continue_()
                try: asset = _cached_asset(route.request.url, Path(cache))
                except (ValueError, OSError): asset = None
                if asset is not None:
                    raw, content_type = asset
                    report['network']['cached_assets'].append(route.request.url)
                    return route.fulfill(body=raw, content_type=content_type)
                report['network']['blocked'].append(route.request.url); route.abort()
            context.route('**/*', route_request)
            if hasattr(context, 'route_web_socket'): context.route_web_socket('**/*', lambda route: route.close())
            page = context.new_page()
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            http = []
            page.on('response', lambda response: http.append(response)
                    if urlsplit(response.url).path in ('/chat', '/graph/confirm') else None)
            page.goto(base, wait_until='networkidle')
            page.wait_for_function('typeof handleImageSelected === "function" && !!window.DMateGraphEditor?.mount')
            check('file_input_accepts_multiple', page.locator('#imageInput').get_attribute('multiple') is not None)
            page.locator('#imageInput').set_input_files([row['path'] for row in rows])
            observed = wait_events(page, folder, lambda es: sum(e['kind']=='visual_entered' for e in es)==4)
            identities = {e['case']: e['request_id'] for e in observed if e['kind']=='upload_started'}
            check('four_distinct_request_ids', len(set(identities.values())) == 4)
            cards = {case: page.locator(f'article[data-ocr-task-id="{iid}"]') for case, iid in identities.items()}
            check('four_independent_running_cards', all(card.get_attribute('data-state')=='recognizing' for card in cards.values()))
            (folder/'release_B').touch()
            cards['B'].wait_for(state='visible')
            page.wait_for_function('(id)=>document.querySelector(`[data-ocr-task-id="${id}"]`)?.dataset.state==="ready"', arg=identities['B'])
            check('one_result_ready_without_waiting_for_others', all(cards[x].get_attribute('data-state')=='recognizing' for x in 'ACD'))
            cards['B'].locator('[data-ocr-action="edit"]').click()
            editor = page.locator('#graphEditorMount')
            editor.get_by_label('节点 1 标签', exact=True).fill('B-edited')
            editor.get_by_label('边 1 起点', exact=True).select_option('b')
            editor.get_by_label('边 1 终点', exact=True).select_option('a')
            editor.get_by_label('边 1 方向', exact=True).select_option('forward')
            editor.get_by_label('边 1 权重', exact=True).fill('9')
            editor.get_by_label('边 1 相同边数量', exact=True).fill('3')
            editor.locator('.dge-edge-row').first.get_by_role('button', name='应用数量', exact=True).click()
            editor.get_by_label('题干、全部小问与公式', exact=True).fill('已修改题干：求各顶点的度数。')
            editor.get_by_label('我已对照原图核对题干与各子图', exact=True).check()
            editor.get_by_role('button', name='保存并确认', exact=True).click()
            page.locator('#graphEditorDialog').wait_for(state='hidden')
            confirmations = [response.json() for response in http if urlsplit(response.url).path=='/graph/confirm']
            check('confirmation_uses_actual_edited_document', len(confirmations)==1)
            first = confirmations[0]
            graph = first['document']['graphs'][0]
            check('node_body_direction_weight_and_parallel_count_preserved',
                first['document']['body_text']=='已修改题干：求各顶点的度数。'
                and graph['vertices'][0]['label']=='B-edited'
                and sum(edge['from']=='b' and edge['to']=='a' and edge['direction']=='forward'
                        and str(edge.get('weight'))=='9' for edge in graph['edges'])==3)
            check('confirm_does_not_solve', not any(e['kind']=='solver_boundary' for e in events(folder)))
            completed_b_seconds = float(cards['B'].get_attribute('data-elapsed-seconds'))
            page.wait_for_function('''({id, seconds}) => Number(document.querySelector(
                `[data-ocr-task-id="${id}"]`)?.dataset.elapsedSeconds) > seconds''',
                arg={'id': identities['A'], 'seconds': completed_b_seconds}, timeout=5000)
            check('completed_task_clock_freezes_while_other_tasks_continue',
                  completed_b_seconds > 0
                  and float(cards['B'].get_attribute('data-elapsed-seconds')) == completed_b_seconds)
            (folder/'release_A').touch(); (folder/'release_C').touch()
            cards['D'].locator('[data-ocr-action="cancel"]').click()
            wait_events(page, folder, lambda es: any(e['kind']=='http_finished' and e['path']=='/ocr/cancel' for e in es))
            (folder/'release_D').touch()
            wait_events(page, folder, lambda es: sum(e['kind']=='http_finished' and e['path']=='/ocr' for e in es)==4)
            page.wait_for_timeout(100)
            check('failure_and_cancel_are_isolated', {case: card.get_attribute('data-state') for case,card in cards.items()}
                  == {'A':'ready','B':'ready','C':'failed','D':'cancelled'})
            cards['B'].locator('[data-ocr-field="userRequest"]').fill('请计算各顶点的度数。')
            with page.expect_response(lambda response: urlsplit(response.url).path=='/chat') as response_info:
                cards['B'].locator('[data-ocr-action="solve"]').click()
            solved = response_info.value
            payload = solved.request.post_data_json
            check('older_completed_card_sends_its_latest_confirmed_snapshot', solved.status==200
                and payload['semantic_context']['document']==first['document']
                and payload['semantic_context']['confirmation_token']==first['confirmation_token']
                and payload['semantic_context']['source_sha256']==next(row['sha256'] for row in rows if row['case']=='B'))
            check('only_explicit_solve_reaches_text_model', sum(e['kind']=='solver_boundary' for e in events(folder))==1)
            model_messages = next(e['messages'] for e in events(folder) if e['kind']=='solver_boundary')
            model_context_text = next(message['content'] for message in model_messages
                if '【当前题目的统一语义结构与程序计算数据】\n' in message.get('content', ''))
            model_context = json.loads(model_context_text.split('【当前题目的统一语义结构与程序计算数据】\n', 1)[1]
                                       .split('\n【程序数据结束】', 1)[0])
            check('solver_model_receives_edited_structure_and_recomputed_degrees',
                  model_context['document'] == first['document']
                  and any(calculation.get('result', {}).get('status') == 'computed'
                          and calculation['result'].get('operation') == 'degrees'
                          and {row['vertex_id']: row['degree'] for row in calculation['result']['facts']['degrees']}
                              == {'a': 3, 'b': 4, 'c': 1}
                          for calculation in model_context['calculations']))
            page.wait_for_function('(id)=>!document.querySelector(`[data-ocr-action="solve"][data-task-id="${id}"]`)?.disabled', arg=identities['B'])
            cards['B'].locator('[data-ocr-action="edit"]').click()
            editor.get_by_label('边 1 权重', exact=True).fill('11')
            editor.get_by_role('button', name='稍后继续', exact=True).click()
            # Native dialog.close() queues its close event. The real close
            # handler destroys the mounted editor and renders the updated
            # task card; click() can resolve before that event runs.
            report['dismissal_observation'] = page.evaluate('''(id) => ({
                dialogOpen: document.querySelector('#graphEditorDialog').open,
                editorChildren: document.querySelector('#graphEditorMount').childElementCount,
                solveButtons: document.querySelectorAll(
                    `[data-ocr-action="solve"][data-task-id="${id}"]`).length
            })''', identities['B'])
            page.wait_for_function('''() => !document.querySelector('#graphEditorDialog').open
                && document.querySelector('#graphEditorMount').childElementCount === 0''')
            check('editing_invalidates_old_confirmation_in_ui', cards['B'].locator('[data-ocr-action="solve"]').count()==0)
            check('editing_does_not_send_another_solver_request', sum(e['kind']=='solver_boundary' for e in events(folder))==1)
            cards['B'].locator('[data-ocr-action="edit"]').click()
            editor.get_by_label('我已对照原图核对题干与各子图', exact=True).check()
            editor.get_by_role('button', name='保存并确认', exact=True).click()
            page.locator('#graphEditorDialog').wait_for(state='hidden')
            second = [response.json() for response in http if urlsplit(response.url).path=='/graph/confirm'][-1]
            check('reconfirmation_has_new_revision_and_weight', second['revision']>first['revision']
                and second['confirmation_token']!=first['confirmation_token']
                and str(second['document']['graphs'][0]['edges'][0]['weight'])=='11')
            stale = context.request.post(base+'/chat', data=payload)
            check('old_token_rejected_after_new_confirmation', stale.status==409)
            check('stale_request_did_not_reach_solver', sum(e['kind']=='solver_boundary' for e in events(folder))==1)
            page.screenshot(path=str(output/'four-cards.png'), full_page=True)
            report['cards'] = {case: {'request_id': identities[case], 'state': card.get_attribute('data-state'),
                'elapsed_seconds': card.get_attribute('data-elapsed-seconds')} for case,card in cards.items()}
            check('four_independent_final_clocks_preserve_completion_order',
                  all(float(card['elapsed_seconds']) > 0 for card in report['cards'].values())
                  and float(report['cards']['B']['elapsed_seconds']) == completed_b_seconds
                  and float(report['cards']['A']['elapsed_seconds']) > completed_b_seconds)
            report['confirmation_documents'] = [first['document'], second['document']]
            context.close(); chromium.close()
        server = json.loads((output/'server'/'server_report.json').read_text())
        report['server_summary'] = {key: server[key] for key in ('max_active_visual','max_active_heavy_worker','external_model_sends','guards')}
        check('actual_four_visual_transports_overlap', server['max_active_visual']==4)
        check('shared_heavy_worker_is_serial', server['max_active_heavy_worker']==1)
        check('exactly_four_original_uploads', sum(row['path']=='/ocr' for row in server['requests'])==4)
        check('each_task_retains_its_original_bytes_and_identity',
              {row['case']: (row['request_id'], row['image_sha256'])
               for row in server['requests'] if row['path']=='/ocr'}
              == {row['case']: (identities[row['case']], row['sha256']) for row in rows})
        check('zero_external_model_or_data_sends', server['external_model_sends']==0 and not server['guards'])
        check('no_browser_javascript_errors', not report['errors'])
    except Exception as exc:
        report['errors'].append(type(exc).__name__+': '+str(exc))
    report['status'] = 'pass' if report['checks'] and all(x['passed'] for x in report['checks']) and not report['errors'] else 'fail'
    write_json(output/'summary.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve'); parser.add_argument('--output'); parser.add_argument('--browser'); parser.add_argument('--cache')
    args = parser.parse_args()
    if args.serve: serve(args.serve); return 0
    if not all((args.output,args.browser,args.cache)): parser.error('Provide output, browser and cache')
    report = run(args.output,args.browser,args.cache)
    print(json.dumps({'status':report['status'],'checks':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
    return 0 if report['status']=='pass' else 2


if __name__ == '__main__':
    raise SystemExit(main())
