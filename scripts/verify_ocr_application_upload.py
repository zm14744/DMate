"""Observe actual file-input -> Flask /ocr -> first response -> UI/status.

Synthetic mode runs the real application in a fresh, loopback-only process.
Only local worker and Qwen/DeepSeek transport boundaries are injected. It never
replaces /ocr, recognize_image, VisionProvider, graph extraction or the editor.
The result is a synthetic application CONTRACT check, not model/image accuracy.

Observed-http mode accepts an explicitly supplied loopback test service and a
private manifest. It uploads each original once through the actual file input.
Server-reported model metrics are retained as unverified observations; they do
not establish actual sends, server provenance or a complete accuracy certificate.
Neither mode promotes a fixture or an HTTP 200 into application certification.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_graph_first_pass import (digest, load_manifest, same_source,
                                               source_snapshot, utc_now, write_json)
from scripts.verify_graph_first_pass_ui import _cached_asset

MODES = ('synthetic', 'observed-http')
CASES = ('normal', 'memory_limit', 'vision_failure', 'cancel_local', 'duplicate_selection')
EXPECTED_BOUNDARY_CALLS = {'normal': (2, 1), 'memory_limit': (2, 1),
                           'vision_failure': (1, 0), 'cancel_local': (0, 0),
                           'duplicate_selection': (2, 1)}
SENTINEL = 'synthetic-boundary-only-not-a-real-key'
QUESTION = 'Count the edges.'


def private_directory(path):
    destination = Path(path).resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Private inputs and responses must remain outside the repository')
    # Every invocation preserves its own first observations, including failures.
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    return destination


def write_bytes(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def local_service(value):
    parsed = urlsplit(value)
    # Use a literal address: no DNS, proxy, credential, path or redirect target.
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or parsed.port is None):
        raise ValueError('Provide an explicit http://127.0.0.1:PORT test service')
    return value.rstrip('/')


def clean_child_environment(folder, inherited=None):
    """An allowlist excludes DB, mail, auth, account, proxy and real API config."""
    source = os.environ if inherited is None else inherited
    allowed = ('PATH', 'LANG', 'LC_ALL', 'TZ', 'LD_LIBRARY_PATH', 'SYSTEMROOT')
    env = {key: source[key] for key in allowed if key in source}
    env.update(PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1',
               TMPDIR=str(folder), DMATE_GRAPH_NEXTGEN='1',
               DMATE_GRAPH_PIPELINE='evidence-two-pass',
               DMATE_GRAPH_STAGE_AUDIT='1', VISION_ANALYSIS_ENABLED='1',
               DASHSCOPE_API_KEY=SENTINEL, DEEPSEEK_API_KEY=SENTINEL,
               TRUSTED_PROXY_CIDRS='', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    return env


def synthetic_image(path):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (400, 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text((10, 12), QUESTION, fill='black')
    draw.text((10, 38), 'SYNTHETIC UPLOAD CONTRACT ONLY', fill='black')
    draw.line((80, 156, 320, 156), fill='black', width=3)
    for x, label in ((80, 'a'), (320, 'b')):
        draw.ellipse((x-8, 148, x+8, 164), fill='white', outline='black', width=3)
        draw.text((x-3, 174), label, fill='black')
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    write_bytes(path, stream.getvalue())
    return {'id': 'synthetic', 'path': str(path), 'sha256': digest(stream.getvalue()),
            'width': 400, 'height': 240}


def _node_fixture():
    return {'coordinate_space': 'original_1000', 'panels_complete': True,
            'body_text': QUESTION, 'body_complete': True, 'graphs': [{
                'id': 'G', 'name': 'Synthetic G', 'bbox': [125, 420, 875, 850],
                'directed': False, 'weighted': False, 'multigraph': False,
                'node_complete': True, 'vertices': [
                    {'id': 'a', 'label': 'a', 'x': 200, 'y': 650},
                    {'id': 'b', 'label': 'b', 'x': 800, 'y': 650}]}]}


def _edge_fixture(prompt, scenario):
    # These are only answers for the generated synthetic two-node diagram.
    # Candidate IDs come from the real CPU pipeline; no production/gold lookup.
    proposal = json.loads(prompt.rsplit('\n', 1)[1])
    graphs = []
    for graph in proposal['graphs']:
        candidates = graph['candidates']
        eligible = [c for c in candidates if {c['from'], c['to']} == {'a', 'b'}]
        selected = eligible[0] if eligible else None
        vertices = {v['id']: v for v in graph['vertices']}
        edge = {'id': selected['id'] if selected else 'new_fixture_edge',
                'from': 'a', 'to': 'b', 'direction': 'undirected', 'style': 'solid',
                'path': [[vertices['a']['x'], vertices['a']['y']],
                         [vertices['b']['x'], vertices['b']['y']]]}
        graphs.append({'id': graph['id'], 'directed': False, 'weighted': False,
                       'multigraph': False, 'node_inventory_confirmed': True,
                       'inventory_complete': True, 'edges': [edge],
                       'reads': [{'vertex': v, 'complete': True, 'edge_ids': [edge['id']]}
                                 for v in ('a', 'b')],
                       'candidate_verdicts': [[c['id'], c['id'] == edge['id']] for c in candidates]})
    return {'coordinate_space': 'original_1000', 'panels_complete': True, 'graphs': graphs,
            'text_review': {'text': QUESTION, 'complete': scenario != 'memory_limit',
                            'regions': [{'id': h['id'], 'role': 'body', 'text': h['text']}
                                        for h in proposal.get('text_hints', [])]}}


def serve_synthetic(folder):
    """Internal child entry. Guard before importing app; never use production env."""
    import socket
    import smtplib
    import requests
    from flask import request, g
    from werkzeug.serving import make_server, WSGIRequestHandler

    folder = Path(folder).resolve()
    if os.environ.get('DMATE_GRAPH_NEXTGEN') != '1':
        raise ValueError('Nextgen must be selected before app import')
    expected = clean_child_environment(folder)
    if (set(os.environ) - set(expected) - {'LC_CTYPE'}
            or os.environ.get('DASHSCOPE_API_KEY') != SENTINEL
            or os.environ.get('DEEPSEEK_API_KEY') != SENTINEL):
        raise ValueError('Child environment is not isolated')
    lock = threading.RLock()
    ledger = {'fixture_only': True, 'actual_model_sends': {'qwen': 0, 'deepseek': 0},
              'guards': [], 'events': [], 'requests': []}

    def event(kind, **values):
        record = {'kind': kind, 'at': utc_now(), **values}
        with lock:
            ledger['events'].append(record)
            with (folder/'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False)+'\n')
        return record

    def forbidden(kind):
        def deny(*args, **kwargs):
            # Do not retain URLs, keys, DB connection strings or mail contents.
            with lock:
                ledger['guards'].append({'kind': kind, 'at': utc_now()})
            raise RuntimeError('synthetic_isolation_blocked_'+kind)
        return deny

    requests.sessions.Session.send = forbidden('http_send')
    socket.socket.connect = forbidden('socket_connect')
    socket.socket.connect_ex = forbidden('socket_connect_ex')
    smtplib.SMTP = forbidden('smtp')
    smtplib.SMTP_SSL = forbidden('smtp_ssl')
    try:
        import psycopg
        psycopg.connect = forbidden('database_connect')
    except ImportError:
        pass

    import app as application
    import ai
    import ocr_runtime
    if application.AUTH_CONFIGURED or application.TRUSTED_PROXY_CIDRS:
        raise ValueError('Child unexpectedly has accounts or trusted proxies configured')

    def identity():
        return {'case': request.headers.get('X-DMate-Test-Case', ''),
                'request_id': request.form.get('request_id', '')}

    def worker(stage, image_path, output_path, **kwargs):
        from PIL import Image
        info = identity()
        scenario = info['case']
        if scenario not in CASES:
            raise ValueError('Unknown synthetic scenario')
        with Image.open(image_path) as image:
            size = list(image.size)
        event('injected_worker', stage=stage, image_size=size, **info)
        metric = {'stage': stage, 'status': 'ok', 'seconds': 0,
                  'peak_rss_bytes': None, 'rss_observed': False, 'fixture_only': True}
        if stage == 'layout':
            return {'status': 'ok', 'regions': [
                {'role': 'figure', 'bbox': [.125, .42, .875, .85], 'score': 1}]}, metric
        if scenario in ('cancel_local', 'duplicate_selection'):
            event('worker_waiting', **info)
            release = folder/('release_'+info['request_id'])
            deadline = time.monotonic()+25
            while not release.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('Synthetic worker release deadline')
                time.sleep(.025)
        if scenario == 'memory_limit':
            metric['status'] = 'memory_limit'
            return None, metric
        return {'text': QUESTION, 'front_text': QUESTION, 'text_count': 1,
                'formula_count': 0, 'review_regions': [],
                'text_evidence': {'image_size': size, 'body': [
                    {'content': QUESTION, 'box': [10, 12, 250, 30], 'score': 1}]}}, metric

    def qwen(payload, headers, **kwargs):
        info = identity()
        event('injected_model_boundary', provider='qwen', **info)
        if info['case'] == 'vision_failure':
            raise requests.Timeout('synthetic Qwen timeout')
        content = payload['messages'][0]['content']
        prompt = next(item['text'] for item in content if item['type'] == 'text')
        value = _edge_fixture(prompt, info['case']) if 'first_body_text' in prompt.rsplit('\n', 1)[1] else _node_fixture()
        return 200, {}, {'model': 'qwen3-vl-plus', 'choices': [
            {'finish_reason': 'stop', 'message': {'content': json.dumps(value, ensure_ascii=False)}}]}

    def deepseek(*args, **kwargs):
        event('injected_model_boundary', provider='deepseek', **identity())
        return {'ok': True, 'content': '{"edits":[]}',
                'choice': {'finish_reason': 'stop'}, 'model': 'deepseek-flash'}

    ocr_runtime.run_worker = worker
    ai._request_qwen_completion = qwen
    ai._request_text_completion = deepseek

    @application.app.before_request
    def observe_request():
        g.upload_started = utc_now()

    @application.app.after_request
    def observe_first_response(response):
        if request.path not in ('/ocr', '/ocr/cancel', '/chat'):
            return response
        info = identity() if request.path == '/ocr' else {
            'case': request.headers.get('X-DMate-Test-Case', ''),
            'request_id': (request.get_json(silent=True) or {}).get('request_id')}
        raw = response.get_data()
        upload = request.files.get('image') if request.path == '/ocr' else None
        original = None
        if upload:
            position = upload.stream.tell()
            upload.stream.seek(0)
            original = upload.read()
            upload.stream.seek(position)
        with lock:
            index = len(ledger['requests'])+1
            name = f'response_{index:03d}.bin'
            write_bytes(folder/name, raw)
            body = response.get_json(silent=True) or {}
            ledger['requests'].append({**info, 'path': request.path, 'method': request.method,
                'started_at': g.upload_started, 'http_status': response.status_code,
                'image_sha256': digest(original) if original is not None else None,
                'image_bytes': len(original) if original is not None else None,
                'response_file': name, 'response_sha256': digest(raw),
                'cancelled': body.get('cancelled'), 'recognition_status': body.get('recognition_status')})
        event('response_completed', path=request.path, **info)
        return response

    class QuietHandler(WSGIRequestHandler):
        def log_request(self, *args, **kwargs):
            pass

    server = make_server('127.0.0.1', 0, application.app, threaded=True, request_handler=QuietHandler)
    write_json(folder/'server.json', {'url': f'http://127.0.0.1:{server.server_port}',
               'pid': os.getpid(), 'fixture_only': True, 'auth_configured': application.AUTH_CONFIGURED,
               'nextgen_selected_before_import': True, 'threaded': True})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while not (folder/'stop').exists():
            time.sleep(.05)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        with lock:
            write_json(folder/'server_report.json', ledger)


def wait_file(path, predicate=lambda value: value, timeout=25):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if Path(path).exists():
            try:
                value = json.loads(Path(path).read_text(encoding='utf-8'))
                if predicate(value):
                    return value
            except (ValueError, OSError):
                pass
        time.sleep(.025)
    raise TimeoutError('Expected local evidence was not written: '+str(Path(path).name))


def server_events(folder):
    path = folder/'events.jsonl'
    if not path.is_file():
        return []
    result = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            result.append(json.loads(line))
        except ValueError:
            pass  # Only an in-progress final line can be partial.
    return result


@contextmanager
def isolated_server(output):
    folder = output/'isolated_server'
    folder.mkdir(mode=0o700)
    with (folder/'process.log').open('xb') as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                    '--serve-synthetic', str(folder)], cwd=ROOT,
                                   env=clean_child_environment(folder), stdout=log, stderr=log)
        try:
            info = wait_file(folder/'server.json', timeout=30)
            yield info['url'], folder
        finally:
            (folder/'stop').touch(exist_ok=True)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


def health_observation(base_url):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Test service redirects are outside the observed contract')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    result = {}
    for path in ('/health', '/ready'):
        with opener.open(base_url+path, timeout=10) as response:
            if response.url != base_url+path:
                raise ValueError('Health endpoint redirected outside the observed contract')
            result[path] = {'http_status': response.status, 'body': json.loads(response.read())}
    return result


OBSERVER_INSTALL = r"""() => {
  if (typeof window.DMateGraphEditor?.mount !== 'function') throw Error('Real graph editor unavailable');
  window.__uploadDialogCalls = 0;
  window.__uploadFormEvidence = [];
  window.__uploadFormPromises = [];
  const originalFetch = window.fetch;
  window.fetch = function(input, options) {
    const result = originalFetch.apply(this, arguments);
    if (typeof input === 'string' && new URL(input, location.href).pathname === '/ocr'
        && options?.body instanceof FormData) {
      const file = options.body.get('image'), requestId = options.body.get('request_id');
      window.__uploadFormPromises.push((async () => {
        const bytes = await file.arrayBuffer();
        const sha = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
          .map(x => x.toString(16).padStart(2, '0')).join('');
        window.__uploadFormEvidence.push({request_id:requestId, image_sha256:sha,
          image_bytes:bytes.byteLength, file_name:file.name, mime_type:file.type});
      })());
    }
    return result;
  };
  const mount = window.DMateGraphEditor.mount;
  window.DMateGraphEditor.mount = function(container, options) {
    window.__uploadDialogCalls++;
    window.__editorInitialDocument = JSON.parse(JSON.stringify(options.document));
    return mount.call(this, container, options);
  };
}"""


def _check(case, name, condition):
    case['checks'].append({'name': name, 'status': 'pass' if condition else 'fail'})


def multipart_observation(raw, content_type):
    """Parse captured browser request bytes independently of Flask's upload."""
    from email.parser import BytesParser
    from email.policy import default
    message = BytesParser(policy=default).parsebytes(
        b'Content-Type: '+content_type.encode('ascii')+b'\r\nMIME-Version: 1.0\r\n\r\n'+raw)
    uploads, identifiers = [], []
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        payload = part.get_payload(decode=True)
        if name == 'image':
            uploads.append({'image_sha256': digest(payload), 'image_bytes': len(payload)})
        elif name == 'request_id':
            identifiers.append(payload.decode('utf-8'))
    if len(uploads) != 1 or len(identifiers) != 1 or not identifiers[0]:
        raise ValueError('Expected one original upload and one request ID')
    return {**uploads[0], 'request_id': identifiers[0]}


def capture_upload(context, base_url, row, case_id, folder, *, server_folder=None, mobile=False):
    """Observe real single-file upload and explicitly open/dismiss its editor.

    This retains the historical memory/failure/cancellation checks while using
    the editable task card. Recognition never opens a modal or solves by itself.
    """
    from PIL import Image, ImageOps
    case = {'id': case_id, 'image_id': row['id'], 'image_sha256': row['sha256'],
            'request_started_at': utc_now(), 'checks': [], 'requests': [],
            'http_responses': [], 'page_errors': [], 'fixture_only': server_folder is not None}
    folder.mkdir(mode=0o700)
    page = context.new_page()
    page.on('pageerror', lambda error: case['page_errors'].append(str(error)))
    captured_responses = []

    def observe_request(request):
        path = urlsplit(request.url).path
        if path not in ('/ocr', '/ocr/cancel', '/chat'): return
        record = {'path': path, 'method': request.method, 'at': utc_now(),
                  'post_data_sha256': digest(request.post_data_buffer or b'')}
        if path == '/ocr':
            try:
                multipart = multipart_observation(request.post_data_buffer or b'', request.headers.get('content-type', ''))
                record.update(request_id=multipart['request_id'], devtools_multipart=multipart,
                              devtools_omits_file_bytes=multipart['image_bytes'] == 0)
            except (ValueError, TypeError, UnicodeError) as exc:
                record['upload_capture_error'] = type(exc).__name__
        case['requests'].append(record)
    page.on('request', observe_request)
    page.on('response', lambda response: captured_responses.append(response)
            if urlsplit(response.url).path == '/ocr' else None)
    try:
        case['health_before'] = health_observation(base_url)
        page.goto(base_url, wait_until='networkidle', timeout=30000)
        page.wait_for_function('typeof handleImageSelected === "function" && !!window.DMateGraphEditor?.mount')
        page.evaluate(OBSERVER_INSTALL)
        _check(case, 'idle_before_selection', page.locator('[data-ocr-task-id]').count() == 0)
        selected = Path(row['path'])
        page.locator('#imageInput').set_input_files(str(selected))
        card = page.locator('article[data-ocr-task-id]').first
        card.wait_for(state='visible')
        if case_id in ('cancel_local', 'duplicate_selection') and server_folder is not None:
            deadline = time.monotonic()+20
            waiting = None
            while time.monotonic() < deadline:
                waiting = next((x for x in server_events(server_folder)
                                if x['kind'] == 'worker_waiting' and x['case'] == case_id), None)
                if waiting: break
                page.wait_for_timeout(25)
            if waiting is None: raise TimeoutError('Real request did not reach paused worker')
            if case_id == 'cancel_local':
                with page.expect_response(lambda r: urlsplit(r.url).path == '/ocr/cancel') as cancelled:
                    card.locator('[data-ocr-action="cancel"]').click()
                case['cancel_response'] = {'http_status': cancelled.value.status, 'body': cancelled.value.json()}
            # Re-selecting while a request runs is now permitted as a separate
            # task. The old duplicate scenario instead checks the editor guard.
            (server_folder/('release_'+waiting['request_id'])).touch(exist_ok=False)
        page.wait_for_function('document.querySelector("article[data-ocr-task-id]")?.dataset.state !== "recognizing"', timeout=60000)
        if case_id == 'cancel_local' and server_folder is not None:
            deadline = time.monotonic()+20
            while time.monotonic() < deadline and not any(e['kind'] == 'response_completed'
                    and e.get('path') == '/ocr' and e.get('case') == case_id for e in server_events(server_folder)):
                page.wait_for_timeout(25)
        page.wait_for_timeout(100)
        for index, response in enumerate(captured_responses):
            record = {'http_status': response.status, 'received_at': utc_now()}
            try:
                raw = response.body(); write_bytes(folder/f'first_response_{index+1:02d}.bin', raw)
                record.update(response_sha256=digest(raw), body=json.loads(raw))
            except Exception as exc: record['body_capture_error'] = type(exc).__name__
            case['http_responses'].append(record)
        prediction = case['http_responses'][0].get('body') if case['http_responses'] else None
        case['task_state'] = card.get_attribute('data-state')
        _check(case, 'no_automatic_editor_or_solver', page.evaluate('window.__uploadDialogCalls') == 0
               and not any(r['path'] == '/chat' for r in case['requests']))
        case['dialog_opened'] = False
        if case['task_state'] == 'ready':
            card.locator('[data-ocr-action="edit"]').click()
            page.locator('#graphEditorDialog').wait_for(state='visible')
            page.wait_for_function("[...document.querySelectorAll('#graphEditorMount img')].some(img => img.complete && img.naturalWidth > 0)")
            case['dialog_opened'] = True
            observed = page.evaluate("""() => ({document:window.__editorInitialDocument,
              body:document.querySelector('#graphEditorMount textarea[aria-label="题干、全部小问与公式"]')?.value,
              preview:[...document.querySelectorAll('#graphEditorMount img')].map(img=>({width:img.naturalWidth,height:img.naturalHeight})),
              svg:!!document.querySelector('#graphEditorMount .dge-visual svg'),
              renderedVertices:document.querySelectorAll('#graphEditorMount .dge-visual-node').length,
              renderedEdges:document.querySelectorAll('#graphEditorMount .dge-visual-edge').length})""")
            write_json(folder/'ui_observation.json', observed)
            expected = {'body_text': prediction.get('text', ''), 'graphs': prediction.get('graph_structures', [])}
            if isinstance(prediction.get('text_context'), dict): expected['text_context'] = prediction['text_context']
            _check(case, 'editor_uses_first_http_document', observed['document'] == expected)
            _check(case, 'editable_body_is_literal', observed['body'] == expected['body_text'])
            with Image.open(selected) as image: display_size = list(ImageOps.exif_transpose(image).size)
            _check(case, 'original_preview_and_graph_rendered', bool(observed['preview'])
                   and [observed['preview'][0]['width'], observed['preview'][0]['height']] == display_size
                   and (not expected['graphs'] or (observed['svg']
                        and observed['renderedVertices'] == len(expected['graphs'][0].get('vertices', []))
                        and observed['renderedEdges'] == len(expected['graphs'][0].get('edges', [])))))
            if case_id == 'duplicate_selection':
                page.locator('#imageInput').set_input_files(str(selected))
            page.locator('#graphEditorMount').get_by_role('button', name='稍后继续', exact=True).click()
            page.locator('#graphEditorDialog').wait_for(state='hidden')
        case['dialog_calls'] = page.evaluate('window.__uploadDialogCalls')
        case['browser_uploads'] = page.evaluate('async () => {await Promise.all(window.__uploadFormPromises); return window.__uploadFormEvidence;}')
        case['health_after'] = health_observation(base_url)
        after = page.evaluate("""() => ({messages:getCurrent()?.messages || [],
            inputValue:document.querySelector('#imageInput').value, inFlight:ocrRequestInFlight,
            reviewing:ocrReviewInProgress, uploadDisabled:document.querySelector('#imageBtn')?.disabled ?? null,
            body:document.body.innerText})""")
        case['ui_after'] = after
        _check(case, 'file_selection_reset', after['inputValue'] == '')
        _check(case, 'upload_handler_released', not after['inFlight'] and not after['reviewing'] and not after['uploadDisabled'])
        requests = [r for r in case['requests'] if r['path'] == '/ocr']
        _check(case, 'exactly_one_ocr_request', len(requests) == 1)
        _check(case, 'browser_submitted_original_bytes', len(case['browser_uploads']) == 1 and len(requests) == 1
               and case['browser_uploads'][0]['image_sha256'] == row['sha256']
               and case['browser_uploads'][0]['request_id'] == requests[0].get('request_id'))
        _check(case, 'no_chat_request', not any(r['path'] == '/chat' for r in case['requests']))
        _check(case, 'no_question_added_on_dismissal', not any(m.get('source') == 'ocr' for m in after['messages']))
        _check(case, 'no_browser_exception', not case['page_errors'])
        if case_id == 'cancel_local' and server_folder is not None:
            _check(case, 'cancelled_without_dialog', not case['dialog_opened'] and case['dialog_calls'] == 0
                   and case['task_state'] == 'cancelled')
            _check(case, 'actual_cancel_endpoint', case.get('cancel_response', {}).get('http_status') == 200
                   and case.get('cancel_response', {}).get('body', {}).get('cancelled') is True)
        elif case['task_state'] == 'failed':
            _check(case, 'failed_body_never_reviewed', not case['dialog_opened'] and case['dialog_calls'] == 0)
            error_text = str((prediction or {}).get('error') or '')
            _check(case, 'error_visible', error_text in card.inner_text() if error_text else
                   any(word in card.inner_text() for word in ('失败', '未完成')))
        else:
            _check(case, 'original_response_opened_once', case['dialog_opened'] and case['dialog_calls'] == 1)
        if server_folder is not None and case_id != 'cancel_local':
            ready = case['health_after']['/ready']['body']
            _check(case, 'local_worker_health_matches', ready['ocr_ready'] is (case_id != 'memory_limit'))
            if case_id == 'memory_limit':
                _check(case, 'memory_limit_not_formula_failure', '资源受限' in ready['ocr_status'] and '公式' not in ready['ocr_status'])
                _check(case, 'memory_limit_partial_not_complete', isinstance(prediction, dict)
                       and prediction.get('recognition_status') == 'partial'
                       and prediction.get('review', {}).get('required') is True)
            if case_id == 'vision_failure':
                _check(case, 'http_200_not_recognition_success', case['http_responses'][0]['http_status'] == 200
                       and prediction.get('recognition_status') == 'failed' and bool(prediction.get('error')))
            elif case_id in ('normal', 'duplicate_selection'):
                _check(case, 'synthetic_full_chain_completed', prediction.get('recognition_status') == 'complete')
        case['reported_model_evidence'] = {'verification': 'injected_boundaries' if server_folder else 'server_reported_unverified',
            'remote_metrics': (prediction or {}).get('diagnostics', {}).get('remote_metrics'),
            'transport_ledger': (prediction or {}).get('diagnostics', {}).get('transport_ledger')}
    except Exception as exc:
        case['exception'] = {'type': type(exc).__name__, 'message': str(exc)[:500]}
        _check(case, 'exception_free', False)
    finally:
        case['request_finished_at'] = utc_now()
        case['contract_status'] = 'pass' if case['checks'] and all(c['status'] == 'pass' for c in case['checks']) else 'fail'
        write_json(folder/'observation.json', case)
        page.close()
    return case


def browser_uploads(base_url, rows, output, browser_path, cache, *, server_folder=None):
    from playwright.sync_api import sync_playwright
    base_url = local_service(base_url)
    observations, blocked, served = [], [], []
    origin = urlsplit(base_url).netloc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_path), headless=True,
                                             args=['--no-sandbox'])
        try:
            for case_id, row in rows:
                context = browser.new_context(viewport={'width': 390, 'height': 844}
                                              if case_id == 'memory_limit' else {'width': 1440, 'height': 1000},
                                              service_workers='block')
                if server_folder is not None:
                    context.set_extra_http_headers({'X-DMate-Test-Case': case_id})

                def route_request(route):
                    parsed = urlsplit(route.request.url)
                    if parsed.scheme == 'http' and parsed.netloc == origin:
                        route.continue_()
                        return
                    try:
                        asset = _cached_asset(route.request.url, Path(cache))
                    except (ValueError, OSError) as exc:
                        blocked.append({'url': route.request.url, 'reason': type(exc).__name__})
                        route.abort()
                        return
                    if asset is not None:
                        raw, content_type = asset
                        served.append({'url': route.request.url, 'sha256': digest(raw)})
                        route.fulfill(body=raw, content_type=content_type)
                    else:
                        blocked.append({'url': route.request.url, 'reason': 'not_verified_cache_asset'})
                        route.abort()

                context.route('**/*', route_request)
                # No WebSocket transport is required by this upload contract.
                if hasattr(context, 'route_web_socket'):
                    context.route_web_socket('**/*', lambda route: route.close())
                observations.append(capture_upload(context, base_url, row, case_id, output/case_id,
                                                   server_folder=server_folder))
                context.close()
        finally:
            browser.close()
    return observations, {'external_requests_blocked': blocked,
                          'cached_assets': served, 'external_network_sends': 0}


def summarize(mode, cases, network, server, frozen, current):
    if mode not in MODES:
        raise ValueError('Unknown harness mode')
    problems = []
    if not cases or (mode == 'synthetic' and [c.get('id') for c in cases] != list(CASES)):
        problems.append('missing_or_changed_case_inventory')
    if not same_source(frozen, current) or frozen.get('dirty') != current.get('dirty'):
        problems.append('source_changed_during_observation')
    if network['external_requests_blocked']:
        problems.append('unexpected_or_unavailable_browser_asset')
    if any(c['contract_status'] != 'pass' for c in cases):
        problems.append('application_contract_check_failed')
    if mode == 'synthetic':
        if not server or server.get('guards'):
            problems.append('child_isolation_missing_or_violated')
        if server and server.get('actual_model_sends') != {'qwen': 0, 'deepseek': 0}:
            problems.append('synthetic_actual_model_send')
        initial = (server or {}).get('initial_health', {})
        if (initial.get('/health', {}).get('http_status') != 200
                or initial.get('/ready', {}).get('body', {}).get('ocr_ready') is not False):
            problems.append('fresh_application_readiness_not_observed')
        requests = (server or {}).get('requests', [])
        for case in cases:
            matching = [r for r in requests if r['path'] == '/ocr' and r['case'] == case['id']]
            client = [r for r in case['requests'] if r['path'] == '/ocr']
            if (len(matching) != 1 or matching[0]['image_sha256'] != case['image_sha256']
                    or len(client) != 1 or matching[0]['request_id'] != client[0].get('request_id')):
                problems.append(case['id']+':original_upload_not_bound')
            elif case['id'] != 'cancel_local':
                observed = case['http_responses']
                if len(observed) != 1 or matching[0]['response_sha256'] != observed[0].get('response_sha256'):
                    problems.append(case['id']+':first_http_response_not_bound')
            elif matching[0].get('cancelled') is not True or matching[0].get('http_status') != 200:
                problems.append('cancelled_request_not_discarded_by_real_route')
            events = [e for e in (server or {}).get('events', [])
                      if e.get('case') == case['id'] and e['kind'] == 'injected_model_boundary']
            calls = tuple(sum(e.get('provider') == p for e in events) for p in ('qwen', 'deepseek'))
            if calls != EXPECTED_BOUNDARY_CALLS.get(case['id']):
                problems.append(case['id']+':unexpected_injected_boundary_calls')
        cancelled_calls = [e for e in (server or {}).get('events', [])
                           if e.get('case') == 'cancel_local' and e['kind'] == 'injected_model_boundary']
        if cancelled_calls:
            problems.append('cancel_during_local_worker_entered_model')
    return {'status': 'fail' if problems else 'not_certified', 'mode': mode,
            'execution_scope': 'actual_file_input_http_response_ui_status',
            'fixture_only': mode == 'synthetic', 'recognition_accuracy_test': False,
            'application_contract_status': 'fail' if problems else 'pass',
            'application_status': 'not_certified', 'application_certified_passes': 0,
            'first_pass_certified_images': 0,
            'actual_model_sends': {'qwen': 0, 'deepseek': 0} if mode == 'synthetic' else None,
            'model_send_verification': 'isolated_injections_and_zero_outbound_guards' if mode == 'synthetic'
                                       else 'unverified_server_metrics_only',
            'source_unchanged': same_source(frozen, current), 'problems': sorted(set(problems)),
            'images_selected': len(cases), 'document_requests': sum(
                r['path'] == '/ocr' for c in cases for r in c['requests']),
            'contract_cases_passed': sum(c['contract_status'] == 'pass' for c in cases),
            'network': network, 'cases': cases}


def run(mode, output, browser, cache, *, base_url=None, manifest=None):
    if mode not in MODES:
        raise ValueError('Unknown harness mode')
    if mode == 'synthetic' and (base_url or manifest):
        raise ValueError('Synthetic mode never consumes an external service or original manifest')
    if mode == 'observed-http' and (not base_url or not manifest):
        raise ValueError('Observed mode requires an explicit loopback test URL and original manifest')
    if not Path(browser).is_file() or not Path(cache).is_dir():
        raise ValueError('Explicit existing Chromium and preverified CDN cache are required')
    if mode == 'observed-http':
        base_url = local_service(base_url)
        _, originals = load_manifest(manifest)
    output = private_directory(output)
    frozen = source_snapshot()
    metadata = {'execution_id': str(uuid.uuid4()), 'started_at': utc_now(), 'mode': mode,
                'fixture_only': mode == 'synthetic', 'source_snapshot': frozen,
                'policy': {'document_attempts_per_image': 1, 'automatic_retry': False,
                           'select_best_result': False, 'ocr_response_mocked': False},
                'server_provenance': 'fresh_isolated_child' if mode == 'synthetic' else 'unverified_test_service',
                'manifest_sha256': digest(Path(manifest).read_bytes()) if manifest else None}
    write_json(output/'run.json', metadata)
    server = None
    if mode == 'synthetic':
        row = synthetic_image(output/'synthetic_transparent.png')
        with isolated_server(output) as (base_url, folder):
            initial = health_observation(base_url)
            write_json(output/'initial_health.json', initial)
            cases, network = browser_uploads(base_url, [(name, row) for name in CASES], output,
                                            browser, cache, server_folder=folder)
        server = wait_file(folder/'server_report.json', timeout=2)
        server['initial_health'] = initial
        write_json(output/'server_evidence.json', server)
    else:
        cases, network = browser_uploads(base_url, [(r['id'], r) for r in originals], output, browser, cache)
    summary = summarize(mode, cases, network, server, frozen, source_snapshot())
    summary['execution_id'] = metadata['execution_id']
    summary['completed_at'] = utc_now()
    write_json(output/'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=MODES)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--browser', type=Path, default=os.environ.get('DMATE_BROWSER_EXECUTABLE'))
    parser.add_argument('--cdn-cache', type=Path, default=os.environ.get('DMATE_BROWSER_CDN_CACHE'))
    parser.add_argument('--base-url')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--serve-synthetic', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve_synthetic:
        serve_synthetic(args.serve_synthetic)
        return 0
    if not args.mode or not args.output or not args.browser or not args.cdn_cache:
        parser.error('--mode, --output, --browser and --cdn-cache are required')
    try:
        result = run(args.mode, args.output, args.browser, args.cdn_cache,
                     base_url=args.base_url, manifest=args.manifest)
    except (ValueError, OSError, TimeoutError) as exc:
        print(json.dumps({'status': 'blocked', 'type': type(exc).__name__, 'reason': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({key: result[key] for key in ('status', 'application_contract_status',
        'fixture_only', 'application_certified_passes', 'contract_cases_passed', 'problems')}, ensure_ascii=False))
    # Success here means only the explicitly scoped harness contract passed.
    return 0 if result['application_contract_status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
