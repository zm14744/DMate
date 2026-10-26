"""Replay a complete frozen first-pass run in Chromium, with no OCR or network.

Requires the same checkout, original bytes and a preverified public CDN cache.
The original response/result files are never replaced. New browser observations,
frontend_evidence.json, result_with_frontend.json and summary_with_frontend.json
remain in the private run directory. This verifies the existing original preview
and text cards, not a newly drawn graph or recognition accuracy by itself.

Example (requires no model credentials):
  python scripts/verify_graph_first_pass_ui.py --run /private/first-pass \
    --manifest /private/manifest.json --browser /private/chromium/chrome \
    --cdn-cache /private/verified-public-js
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import threading
import unicodedata
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graph_first_pass_eval import (FRONTEND_CHECKS, evaluate_prediction,
                                   prediction_digest)
from scripts.benchmark_graph_first_pass import (digest, load_manifest, same_source,
                                               source_snapshot, utc_now, write_json)

GRAPH_FIELDS = ('schema_version', 'id', 'name', 'directed', 'weighted', 'multigraph', 'complete')
VERTEX_FIELDS = ('id', 'label', 'isolated_confirmed')
EDGE_FIELDS = ('id', 'from', 'to', 'direction', 'edge_label', 'weight', 'multiplicity',
               'parallel_count', 'style', 'color', 'status')
MODES = {'desktop': {'width': 1440, 'height': 1000}, 'mobile': {'width': 390, 'height': 844}}


def read_json(path):
    def invalid(value):
        raise ValueError('Non-finite JSON value: '+value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)


def _same_snapshot(first, second):
    return same_source(first, second) and type(first.get('dirty')) is bool and first['dirty'] == second.get('dirty')


def load_frozen_run(run, manifest_path):
    """Reject partial, changed, preflight or already-replayed runs before launch."""
    run = Path(run).resolve()
    if run == ROOT or ROOT in run.parents:
        raise ValueError('Private run and browser artifacts must remain outside the repository')
    manifest, rows = load_manifest(manifest_path)
    metadata, summary, refs = [read_json(run/name) for name in ('run.json', 'summary.json', 'references.json')]
    identifiers = [row['id'] for row in rows]
    if metadata.get('check_only') is not False or summary.get('check_only') is True:
        raise ValueError('A preflight is not a completed first-pass run')
    if metadata.get('manifest_sha256') != digest(Path(manifest_path).read_bytes()):
        raise ValueError('Manifest changed after the first-pass freeze')
    if (metadata.get('selected_image_ids') != identifiers
            or metadata.get('original_manifest_count') != len(rows)
            or summary.get('full_corpus_selected') is not True
            or summary.get('images_requested') != len(rows)
            or summary.get('actual_document_requests') != len(rows)):
        raise ValueError('Replay requires the complete manifest and one completed request per original')
    results = summary.get('results')
    if not isinstance(results, list) or [r.get('id') for r in results] != identifiers:
        raise ValueError('First-pass summary is incomplete or out of order')
    policy = metadata.get('policy') or {}
    if (policy.get('document_attempts_per_image') != 1 or policy.get('automatic_retry') is not False
            or policy.get('select_best_result') is not False):
        raise ValueError('First-pass policy is missing or permits replacement attempts')
    frozen = metadata.get('source_snapshot') or {}
    if not _same_snapshot(frozen, source_snapshot()):
        raise ValueError('Current source differs from the recognition freeze; do not replay with a different frontend')
    if (refs.get('evaluation_only') is not True or refs.get('production_lookup_forbidden') is not True
            or not isinstance(refs.get('records'), list) or len(refs['records']) != len(rows)):
        raise ValueError('Missing frozen evaluation-only reference records')
    if (run/'frontend').exists() or (run/'summary_with_frontend.json').exists():
        raise ValueError('This run already has a frontend replay; observations cannot be replaced')
    baseline = {str(run/name): digest((run/name).read_bytes())
                for name in ('run.json', 'summary.json', 'references.json')}
    cases, executions = [], set()
    for row, reference in zip(rows, refs['records']):
        folder = run/row['id']
        response_path, result_path = folder/'response.json', folder/'result.json'
        response, result = read_json(response_path), read_json(result_path)
        if result.get('id') != row['id'] or result.get('actual_document_requests') != 1:
            raise ValueError('Missing first document request for '+row['id'])
        if (folder/'frontend_evidence.json').exists() or (folder/'result_with_frontend.json').exists():
            raise ValueError('Case already replayed: '+row['id'])
        evidence, prediction = response.get('execution_evidence'), response.get('prediction')
        if not isinstance(evidence, dict):
            raise ValueError('Missing frozen execution evidence: '+row['id'])
        execution = evidence.get('execution_id')
        if not isinstance(execution, str) or not execution or execution in executions:
            raise ValueError('Missing or reused execution ID: '+row['id'])
        executions.add(execution)
        if (evidence.get('document_requests') != 1 or evidence.get('source_unchanged') is not True
                or not _same_snapshot(evidence.get('source_snapshot') or {}, frozen)
                or evidence.get('image_sha256') != row['sha256']
                or evidence.get('prediction_sha256') != prediction_digest(prediction)):
            raise ValueError('Response is not bound to the frozen original/source: '+row['id'])
        if reference is not None and (not isinstance(reference, dict)
                or reference.get('id', reference.get('image_id')) != row['id']
                or reference.get('sha256') != row['sha256']):
            raise ValueError('Frozen reference belongs to a different original: '+row['id'])
        baseline[str(response_path)] = digest(response_path.read_bytes())
        baseline[str(result_path)] = digest(result_path.read_bytes())
        cases.append({'row': row, 'reference': reference, 'prediction': prediction,
                      'execution': evidence, 'folder': folder,
                      'response_sha256': baseline[str(response_path)]})
    return {'run': run, 'metadata': metadata, 'summary': summary, 'cases': cases,
            'baseline': baseline, 'source': frozen,
            'fixture_only': metadata.get('fixture_only') is True
                            or metadata.get('kind') == 'synthetic_runner_validation'
                            or any(c['execution'].get('is_live') is not True for c in cases)}


def originals_unchanged(loaded):
    return (all(Path(path).is_file() and digest(Path(path).read_bytes()) == sha
                for path, sha in loaded['baseline'].items())
            and all(digest(Path(c['row']['path']).read_bytes()) == c['row']['sha256'] for c in loaded['cases']))


def public_projection_issues(prediction):
    """Independent field projection: do not call production display_graph()."""
    if not isinstance(prediction, dict):
        return ['missing_prediction']
    graphs, shown = prediction.get('graph_structures'), prediction.get('graph_display_data')
    if not isinstance(graphs, list) or not isinstance(shown, list) or len(graphs) != len(shown):
        return ['public_panel_inventory_mismatch']
    expected = []
    try:
        for graph in graphs:
            if graph.get('schema_version') != 'dmate.graph/1':
                return ['unsupported_public_schema']
            record = {key: graph[key] for key in GRAPH_FIELDS if key in graph}
            record['vertices'] = [{key: v[key] for key in VERTEX_FIELDS if key in v} for v in graph['vertices']]
            record['edges'] = [{key: e[key] for key in EDGE_FIELDS if key in e} for e in graph['edges']]
            expected.append(record)
    except (KeyError, TypeError, AttributeError):
        return ['invalid_canonical_graph']
    return [] if expected == shown else ['canonical_public_projection_changed']


def _string(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _label(value):
    """Only the documented Latin/subscript presentation transformation is allowed."""
    raw = _string(value).strip()
    label = raw.translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789'))
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)?', label):
        return raw
    numbered = re.fullmatch(r'([A-Za-z]+)([0-9]+)', label)
    if numbered:
        return numbered[1]+'_{'+numbered[2]+'}'
    return re.sub(r'_([A-Za-z0-9]+)', r'_{\1}', label)


def _compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', _string(value)))


def expected_panels(prediction):
    panels = []
    for index, graph in enumerate(prediction.get('graph_structures') or []):
        vertices, edges = graph['vertices'], graph['edges']
        labels = {_string(v['id']): _label(v.get('label') or v['id']) for v in vertices}
        raw_labels = [_string(v.get('label') or v['id']).strip() for v in vertices]
        properties = ['有向图' if graph.get('directed') is True else '无向图'
                      if graph.get('directed') is False else '方向未确定']
        if graph.get('weighted') is True:
            properties.append('带权')
        if graph.get('multigraph') is True:
            properties.append('多重图')
        paragraphs = ['类型： '+' · '.join(properties)]
        if graph.get('complete') is not True:
            paragraphs.append('部分内容未识别完整，请对照原图确认。')
        vertices_line = '顶点（'+str(len(vertices))+'）： '+'、'.join(labels[_string(v['id'])] for v in vertices)
        paragraphs.append(vertices_line)
        incident = {_string(e[k]) for e in edges for k in ('from', 'to')}
        isolated = [v for v in vertices if _string(v['id']) not in incident
                    and (graph.get('complete') is True or v.get('isolated_confirmed') is True)]
        if isolated:
            paragraphs.append('孤立顶点： '+'、'.join(labels[_string(v['id'])] for v in isolated))
        edge_heading = '边（'+('' if graph.get('complete') is True else '暂录 ')+str(len(edges))+' 条）：'
        paragraphs.append(edge_heading)
        rows = []
        for number, edge in enumerate(edges, 1):
            attrs = []
            if edge.get('edge_label') not in (None, ''):
                attrs.append('边名：'+_string(edge['edge_label']).strip())
            if edge.get('weight') is not None:
                attrs.append('权值：'+_string(edge['weight']).strip())
            if edge.get('parallel_count', 1) > 1:
                attrs.append('同端点共 '+str(edge['parallel_count'])+' 条')
            if edge.get('style') in ('dashed', 'dotted'):
                attrs.append('虚线' if edge['style'] == 'dashed' else '点线')
            if edge.get('direction') == 'unknown':
                attrs.append('方向未确定')
            if edge.get('status') != 'accepted':
                attrs.append('待确认')
            relation = labels[_string(edge['from'])]+{'forward': ' → ', 'undirected': ' — '}.get(edge.get('direction'), ' ? ')+labels[_string(edge['to'])]
            rows.append('e'+str(number)+'：'+relation+('（'+'，'.join(attrs)+'）' if attrs else ''))
        if not edges:
            paragraphs.append('—')
        panels.append({'heading': '图 '+str(index+1)+'（'+_string(graph.get('name') or graph['id']).strip()+'）',
                       'paragraphs': paragraphs, 'rows': rows, 'vertices_line': vertices_line,
                       'raw_labels': raw_labels, 'edges': edges})
    return panels


def expected_notice(prediction):
    review = prediction.get('review') or {}
    reasons = list(dict.fromkeys(r.strip() for r in review.get('reasons', []) if isinstance(r, str) and r.strip()))
    warning = prediction.get('warning')
    warning = warning.strip() if isinstance(warning, str) else ''
    status = _string(prediction.get('recognition_status')).lower()
    incomplete = status in ('partial', 'failed', 'incomplete', 'uncertain', 'needs_review', 'review_required')
    incomplete |= (prediction.get('diagnostics') or {}).get('text_evidence', {}).get('complete') is False
    if review.get('required') is not True and not incomplete and not warning:
        return ''
    return '识别结果待核对：'+(' '.join(reasons) or warning or '部分内容尚未完整确定，请对照原图确认。')


# This observer reads actual DOM and MathJax source attached to actual SVG nodes.
# Its question oracle uses raw source + the external Markdown parser directly;
# it never calls prepareAiDisplayText, markdownToHtml or the production formatter.
OBSERVE_JS = r"""async ({sourceText}) => {
  const graph=document.querySelector('#ocrReviewGraph');
  const question=document.querySelector('#ocrReviewQuestion');
  await renderMath(question); await renderMath(graph);
  const mathMap=new Map();
  for(const root of [question,graph]) for(const item of MathJax.startup.document.getMathItemsWithin(root)) {
    mathMap.set(item.typesetRoot, {tex:item.math, display:item.display});
  }
  const math=[];
  function semantic(node) {
    if(node.nodeType===Node.TEXT_NODE) return node.textContent;
    if(node.nodeType!==Node.ELEMENT_NODE) return '';
    if(node.tagName.toLowerCase()==='mjx-container') {
      const item=mathMap.get(node);
      const box=node.getBoundingClientRect();
      math.push({tex:item?.tex??null,svg:!!node.querySelector('svg'),
        error:!!node.querySelector('[data-mml-node="merror"],mjx-merror'),
        width:box.width,height:box.height});
      return item?.tex??'UNBOUND_MATH_NODE';
    }
    if(node.tagName==='BR') return '\n';
    return [...node.childNodes].map(semantic).join('');
  }
  const panels=[],orphanGraphContent=[]; let panel=null;
  for(const child of graph.childNodes) {
    if(child.nodeType===Node.TEXT_NODE) {if(child.textContent.trim())orphanGraphContent.push(child.textContent);continue;}
    if(child.tagName==='H3') {panel={heading:semantic(child),paragraphs:[],rows:[]};panels.push(panel);}
    else if(child.tagName==='HR') continue;
    else if(panel && child.tagName==='UL') panel.rows.push(...[...child.children].map(semantic));
    else if(panel) panel.paragraphs.push(semantic(child));
    else orphanGraphContent.push(semantic(child));
  }
  const questionSemantic=semantic(question);
  const ranges=[], tokenPrefix='DMATEORACLE'+crypto.randomUUID().replace(/-/g,'')+'TOKEN';
  const protectedText=sourceText.replace(/\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$(?!\$)(?:\\.|[^$\n])+\$/g,
    match=>{const n=ranges.length; const size=match.startsWith('$$')||match.startsWith('\\')?2:1;
      ranges.push(match.slice(size,-size));return tokenPrefix+n+'END';});
  const template=document.createElement('template'); template.innerHTML=marked.parse(protectedText);
  let expectedQuestion=template.content.textContent;
  ranges.forEach((tex,index)=>{expectedQuestion=expectedQuestion.split(tokenPrefix+index+'END').join(tex);});
  const preview=document.querySelector('#ocrReviewImage');
  const bytes=await (await fetch(preview.src)).arrayBuffer();
  const imageSha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
  const elements=[...graph.querySelectorAll('h3,p,li')];
  const invisible=elements.filter(el=>{
    if(!el.getBoundingClientRect().width||!el.getBoundingClientRect().height)return true;
    for(let n=el;n&&n!==document.body;n=n.parentElement){const s=getComputedStyle(n);
      if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return true;}
    return false;
  }).length;
  return {panels,orphanGraphContent,questionSemantic,expectedQuestion,questionEmpty:!!question.querySelector('.ocr-review-empty'),
    notice:document.querySelector('#ocrReviewError').textContent,
    noticeCount:document.querySelectorAll('#ocrReviewError').length,
    responseUnchanged:window.__firstPassBefore===JSON.stringify(window.__firstPassResponse),
    originalSha256:imageSha,imageWidth:preview.naturalWidth,imageHeight:preview.naturalHeight,
    imageBackground:getComputedStyle(preview).backgroundColor,previewBlob:preview.src.startsWith('blob:'),
    imageVisible:!!preview.getBoundingClientRect().width&&!!preview.getBoundingClientRect().height,
    readonly:graph.contentEditable!=='true'&&question.contentEditable!=='true',
    graphDangerousElements:graph.querySelectorAll('script,img,iframe,object,embed,input,textarea,button').length,
    graphErrorHandlers:[...graph.querySelectorAll('*')].filter(e=>[...e.attributes].some(a=>a.name.startsWith('on'))).length,
    invisibleElements:invisible,math,graphHtml:graph.innerHTML,questionHtml:question.innerHTML,
    dialogWidth:document.querySelector('#ocrReviewDialog').getBoundingClientRect().width,viewportWidth:innerWidth};
}"""


def compare_observation(prediction, observed, row, display_size):
    expected = expected_panels(prediction)
    actual = observed.get('panels') or []
    same_panels = len(expected) == len(actual)
    headings = same_panels and all(_compact(a['heading']) == _compact(b.get('heading')) for a, b in zip(expected, actual))
    unassigned = observed.get('orphanGraphContent')
    if expected:
        headings = headings and unassigned == []
    else:
        empty_message = '图形结构暂无可展示的边表' if _string(prediction.get('visual_text')).strip() else '未识别到内容'
        headings = headings and unassigned == [empty_message]
    paragraphs = same_panels and all([_compact(x) for x in a['paragraphs']] == [_compact(x) for x in b.get('paragraphs', [])]
                                    for a, b in zip(expected, actual))
    rows_match = same_panels and all([_compact(x) for x in a['rows']] == [_compact(x) for x in b.get('rows', [])]
                                    for a, b in zip(expected, actual))
    # Internal spaces in literal labels are significant even though Markdown
    # layout whitespace is ignored by the block comparator.
    literal_labels = same_panels and all(all(label in ''.join(b.get('paragraphs', []))
        for label in a['raw_labels'] if _label(label) == label)
        for a, b in zip(expected, actual))
    raw_edge_labels = same_panels and all(all(edge.get('edge_label') is None
        or _string(edge.get('edge_label')).strip() in shown
        for edge, shown in zip(a['edges'], b.get('rows', []))) for a, b in zip(expected, actual))
    math_valid = all(m.get('tex') is not None and m.get('svg') is True and not m.get('error')
                     and m.get('width', 0) > 0 and m.get('height', 0) > 0 for m in observed.get('math', []))
    text = _string(prediction.get('text')).strip()
    body = (observed.get('questionEmpty') is True if not text else
            not observed.get('questionEmpty') and _compact(observed.get('questionSemantic')) == _compact(observed.get('expectedQuestion')))
    values = {'public_projection': not public_projection_issues(prediction), 'panels': headings,
              'vertex_labels': paragraphs and literal_labels, 'graph_types': paragraphs,
              'edge_instances': rows_match, 'edge_endpoints': rows_match, 'directions': rows_match,
              'multiplicity': rows_match, 'self_loops': rows_match, 'weights': rows_match,
              'edge_labels': rows_match and raw_edge_labels, 'styles': rows_match,
              'status': paragraphs and observed.get('notice') == expected_notice(prediction) and observed.get('noticeCount') == 1,
              'text': body and math_valid,
              'original_preview': observed.get('originalSha256') == row['sha256']
                  and [observed.get('imageWidth'), observed.get('imageHeight')] == list(display_size)
                  and observed.get('imageBackground') == 'rgb(255, 255, 255)'
                  and observed.get('previewBlob') is True and observed.get('imageVisible') is True,
              'response_immutable': observed.get('responseUnchanged') is True,
              'readonly': observed.get('readonly') is True and observed.get('invisibleElements') == 0
                  and observed.get('dialogWidth', 1) <= observed.get('viewportWidth', 0),
              'no_markup_injection': observed.get('graphDangerousElements') == 0 and observed.get('graphErrorHandlers') == 0}
    return [{'name': name, 'status': 'pass' if truth else 'fail'} for name, truth in values.items()]


def _cached_asset(url, cache):
    # Never call the cache downloader; absent/tampered public assets are a block.
    sys.path.insert(0, str(ROOT/'tests'))
    from browser_assets import allowed_asset
    if not allowed_asset(url):
        return None
    key = hashlib.sha256(url.encode()).hexdigest()
    payload, metadata = cache/(key+'.js'), cache/(key+'.json')
    if not payload.is_file() or not metadata.is_file():
        raise ValueError('Required verified public asset is absent from cache')
    record, raw = read_json(metadata), payload.read_bytes()
    if record.get('url') != url or record.get('tls_verified') is not True or record.get('sha256') != digest(raw):
        raise ValueError('Cached public asset integrity mismatch')
    return raw, record.get('content_type', 'application/javascript')


def replay(loaded, browser_path, cache):
    from flask import Flask, render_template
    from werkzeug.serving import make_server, WSGIRequestHandler
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageOps

    app = Flask('dmate_frozen_first_response', template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))

    @app.get('/')
    def index():
        return render_template('index.html', knowledge_graph_data={}, is_dmate_android_app=False,
            is_dmate_desktop_app=False, android_apk_url='', desktop_windows_url='', desktop_macos_url='',
            desktop_linux_deb_url='', desktop_linux_appimage_url='')

    class QuietHandler(WSGIRequestHandler):
        def log_request(self, code='-', size='-'):
            pass

    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler)
    output = loaded['run']/'frontend'
    output.mkdir(mode=0o700)
    write_json(output/'replay.json', {'started_at': utc_now(), 'kind': 'frozen_first_response_replay',
        'fixture_only': loaded['fixture_only'], 'source_snapshot': loaded['source'],
        'first_files_sha256': loaded['baseline'], 'ocr_requests_allowed': 0,
        'external_network_allowed': 0, 'modes': list(MODES)})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:'+str(server.server_port)
    network = {'ocr_requests': [], 'external_requests_blocked': [], 'external_network_requests': 0,
               'local_mutations_blocked': [], 'cache_errors': [], 'cache_deliveries': [], 'page_errors': []}
    records = []
    actual_browser, browser_version = False, None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_path), headless=True,
                args=['--disable-background-networking', '--disable-component-update', '--disable-sync',
                      '--no-first-run', '--disable-default-apps'])
            actual_browser, browser_version = True, browser.version
            try:
                for case in loaded['cases']:
                    row, prediction = case['row'], case['prediction']
                    case_record = {'id': row['id'], 'views': [], 'artifacts': [], 'errors': []}
                    records.append(case_record)
                    if not _same_snapshot(loaded['source'], source_snapshot()) or not originals_unchanged(loaded):
                        case_record['errors'].append('frozen_input_or_source_changed')
                        continue
                    if not isinstance(prediction, dict):
                        case_record['errors'].append('no_response_to_render')
                        continue
                    raw = Path(row['path']).read_bytes()
                    with Image.open(io.BytesIO(raw)) as source:
                        mime = Image.MIME.get(source.format, 'application/octet-stream')
                        display_size = ImageOps.exif_transpose(source).size
                    for mode, viewport in MODES.items():
                        context = browser.new_context(viewport=viewport, locale='zh-CN', device_scale_factor=1,
                            is_mobile=mode == 'mobile', has_touch=mode == 'mobile', service_workers='block')
                        def route_request(route):
                            url, method = route.request.url, route.request.method
                            parsed = urlsplit(url)
                            if parsed.path == '/ocr' or parsed.path.startswith('/ocr/'):
                                network['ocr_requests'].append({'url': url, 'method': method})
                                route.abort(); return
                            if parsed.netloc == urlsplit(base).netloc:
                                if method != 'GET':
                                    network['local_mutations_blocked'].append({'url': url, 'method': method})
                                    route.abort()
                                elif parsed.path == '/' or parsed.path.startswith('/static/'):
                                    route.continue_()
                                else:
                                    route.abort()
                                return
                            try:
                                asset = _cached_asset(url, cache)
                                if asset is not None:
                                    network['cache_deliveries'].append({'url': url, 'sha256': digest(asset[0])})
                                    route.fulfill(status=200, body=asset[0], content_type=asset[1],
                                                  headers={'Access-Control-Allow-Origin': '*'})
                                    return
                            except (OSError, ValueError) as exc:
                                network['cache_errors'].append(str(exc))
                            network['external_requests_blocked'].append({'url': url, 'method': method})
                            route.abort()
                        context.route('**/*', route_request)
                        # Playwright >= 1.48 intercepts sockets separately from routes.
                        if hasattr(context, 'route_web_socket'):
                            def close_socket(socket):
                                network['external_requests_blocked'].append({'url': socket.url, 'method': 'WEBSOCKET'})
                                socket.close()
                            context.route_web_socket('**/*', close_socket)
                        page = context.new_page()
                        page.on('pageerror', lambda error: network['page_errors'].append(str(error)))
                        try:
                            response = page.goto(base, wait_until='domcontentloaded', timeout=60000)
                            if not response or response.status != 200:
                                raise ValueError('Local template did not load')
                            page.wait_for_function("typeof reviewRecognizedQuestion==='function' && window.marked && window.DOMPurify && window.MathJax?.typesetPromise", timeout=30000)
                            page.evaluate('async()=>{await MathJax.startup.promise;}')
                            page.evaluate("""({bytes,mime,data})=>{
                              const file=new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],'private-original',{type:mime});
                              window.__firstPassResponse=data; window.__firstPassBefore=JSON.stringify(data);
                              window.__firstPassDialog=reviewRecognizedQuestion(file,data);
                            }""", {'bytes': base64.b64encode(raw).decode(), 'mime': mime, 'data': prediction})
                            page.locator('#ocrReviewDialog').wait_for(state='visible')
                            page.wait_for_function("document.querySelector('#ocrReviewImage').complete && document.querySelector('#ocrReviewImage').naturalWidth>0")
                            observed = page.evaluate(OBSERVE_JS, {'sourceText': _string(prediction.get('text')).strip()})
                            checks = compare_observation(prediction, observed, row, display_size)
                            # Every card and row must be reachable in the actual scroll container.
                            for element in page.locator('#ocrReviewGraph h3, #ocrReviewGraph li').all():
                                element.scroll_into_view_if_needed()
                                if not element.is_visible():
                                    checks.append({'name': 'readonly', 'status': 'fail', 'reason': 'unreachable_card_or_edge'})
                            artifact = output/(row['id']+'_'+mode+'_dom.json')
                            write_json(artifact, {'id': row['id'], 'mode': mode, 'observed': observed, 'checks': checks})
                            screen = output/(row['id']+'_'+mode+'.png')
                            page.locator('#ocrReviewDialog').screenshot(path=str(screen))
                            os.chmod(screen, 0o600)
                            case_record['artifacts'].extend([str(artifact), str(screen)])
                            case_record['views'].append({'mode': mode, 'checks': checks})
                            page.locator('#ocrReviewCancel').click()
                            page.locator('#ocrReviewDialog').wait_for(state='hidden')
                            page.evaluate('async()=>{await window.__firstPassDialog;}')
                        except Exception as exc:
                            case_record['errors'].append(mode+':'+type(exc).__name__+':'+str(exc)[:800])
                        finally:
                            context.close()
            finally:
                browser.close()
    except Exception as exc:
        network['runner_error'] = type(exc).__name__+':'+str(exc)[:800]
    finally:
        server.shutdown()
        thread.join(timeout=5)
    stable = _same_snapshot(loaded['source'], source_snapshot()) and originals_unchanged(loaded)
    network_path = output/'network.json'
    write_json(network_path, network)
    network_ok = not any(network.get(key) for key in ('ocr_requests', 'external_requests_blocked',
        'external_network_requests', 'local_mutations_blocked', 'cache_errors', 'page_errors', 'runner_error'))
    assessments = []
    by_id = {r['id']: r for r in records}
    for case in loaded['cases']:
        row, prediction = case['row'], case['prediction']
        record = by_id.get(row['id'], {'views': [], 'artifacts': [], 'errors': ['browser_not_started']})
        checks = []
        for name in FRONTEND_CHECKS:
            if name == 'source_unchanged':
                success = stable
            elif name == 'network_isolation':
                success = network_ok
            else:
                success = len(record['views']) == len(MODES) and all(
                    any(c['name'] == name and c['status'] == 'pass' for c in view['checks'])
                    and not any(c['name'] == name and c['status'] != 'pass' for c in view['checks'])
                    for view in record['views'])
            checks.append({'name': name, 'status': 'pass' if success else 'fail'})
        passed = actual_browser and not record['errors'] and all(c['status'] == 'pass' for c in checks)
        artifacts = record['artifacts']+[str(network_path)]
        evidence = {'schema_version': 2, 'status': 'pass' if passed else 'fail',
            'kind': 'synthetic_runner_validation' if loaded['fixture_only'] else 'original_response',
            'fixture_only': loaded['fixture_only'], 'actual_browser': actual_browser,
            'browser_version': browser_version, 'contract': 'original_preview_and_text_cards',
            'exact_edge_projection_checked': passed, 'checks': checks, 'views': record['views'],
            'image_sha256': row['sha256'], 'prediction_sha256': prediction_digest(prediction),
            'execution_id': case['execution']['execution_id'], 'first_response_file_sha256': case['response_sha256'],
            'source_tree_sha256': loaded['source']['source_tree_sha256'],
            'source_snapshot': {k: loaded['source'][k] for k in ('git_sha', 'dirty', 'source_tree_sha256')},
            'source_unchanged': stable, 'ocr_requests': len(network['ocr_requests']),
            'external_network_requests': network['external_network_requests'],
            'external_requests_blocked': len(network['external_requests_blocked']),
            'artifact_paths': artifacts, 'artifact_sha256': {path: digest(Path(path).read_bytes()) for path in artifacts},
            'finished_at': utc_now(), 'errors': record['errors']}
        write_json(case['folder']/'frontend_evidence.json', evidence)
        result = evaluate_prediction(case['reference'], prediction,
                                     run_evidence=case['execution'], frontend_evidence=evidence)
        result.update(id=row['id'], actual_document_requests=1, frontend_replay_document_requests=0,
                      response_file=str(case['folder']/'response.json'),
                      frontend_evidence_file=str(case['folder']/'frontend_evidence.json'))
        write_json(case['folder']/'result_with_frontend.json', result)
        assessments.append(result)
    counts = Counter(r['status'] for r in assessments)
    summary = {'status': 'pass' if counts.get('pass', 0) == len(assessments) else 'incomplete',
        'kind': 'synthetic_runner_validation' if loaded['fixture_only'] else 'original_response',
        'fixture_only': loaded['fixture_only'], 'finished_at': utc_now(), 'images_requested': len(assessments),
        'actual_document_requests': loaded['summary']['actual_document_requests'],
        'frontend_replay_document_requests': 0, 'frontend_rendering': 'checked' if actual_browser else 'not_run',
        'actual_browser': actual_browser,
        'frontend_contract_passes': sum(all(c['status'] == 'pass' for c in read_json(case['folder']/'frontend_evidence.json')['checks'])
                                        for case in loaded['cases']),
        'source_unchanged': stable, 'original_files_unchanged': originals_unchanged(loaded),
        'status_counts': dict(counts), 'certified_passes': counts.get('pass', 0),
        'full_corpus_selected': True, 'ocr_requests': len(network['ocr_requests']),
        'external_network_requests': network['external_network_requests'],
        'results': [{k: r.get(k) for k in ('id', 'status', 'structure_status')} for r in assessments]}
    write_json(loaded['run']/'summary_with_frontend.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='Complete, frozen private first-pass output directory')
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--browser', required=True, help='Installed Chromium executable')
    parser.add_argument('--cdn-cache', default=os.environ.get('DMATE_BROWSER_CDN_CACHE'),
                        help='Existing verified public asset cache; downloads are forbidden')
    args = parser.parse_args(argv)
    try:
        browser = Path(args.browser).resolve()
        if not browser.is_file() or not os.access(browser, os.X_OK):
            raise ValueError('Chromium executable is unavailable')
        if not args.cdn_cache or not Path(args.cdn_cache).is_dir():
            raise ValueError('A preverified public CDN cache is required; no download is permitted')
        loaded = load_frozen_run(args.run, args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    summary = replay(loaded, browser, Path(args.cdn_cache).resolve())
    print(json.dumps({key: summary[key] for key in ('status', 'kind', 'images_requested',
        'frontend_contract_passes', 'certified_passes', 'frontend_replay_document_requests',
        'ocr_requests', 'external_network_requests', 'source_unchanged')}, ensure_ascii=False))
    return 0 if summary['status'] == 'pass' else 2


if __name__ == '__main__':
    raise SystemExit(main())
