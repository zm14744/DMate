"""Public OCR card contract; synthetic fixtures are NOT recognition acceptance.

The optional Chromium test serves the existing template and static files on a
loopback-only Flask server. It calls the actual dialog function with constructed
responses, never /ocr, a model, a private original, or a gold annotation.

Run the browser check explicitly with DMATE_BROWSER_EXECUTABLE and a private
DMATE_FRONTEND_CONTRACT_OUTPUT outside the checkout. With no browser configured,
pytest records a skip; that is not a browser pass and cannot certify originals.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from urllib.parse import urlsplit

import pytest

from graph_schema import canonical_graph, describe_graphs, display_graph

ROOT = Path(__file__).resolve().parents[1]


def canonical_fixture(*, uncertain=False):
    return canonical_graph({
        'id': 'contract', 'name': '合成卡片契约样例', 'bbox': [.1, .1, .9, .9],
        'directed': True, 'weighted': True, 'multigraph': True,
        'complete': True, 'node_complete': True, 'inventory_reviewed': True,
        'vertices': [{'id': 'a', 'label': '甲', 'x': .2, 'y': .5},
                     {'id': 'b', 'label': '乙', 'x': .8, 'y': .5}],
        'edges': [
            {'id': 'loop', 'from': 'a', 'to': 'a', 'direction': 'forward',
             'weight': 0, 'edge_label': 'loop', 'style': 'solid', 'color': 'black', 'status': 'accepted',
             'path': [[.2, .5], [.1, .2], [.3, .2], [.2, .5]]},
            {'id': 'first_parallel', 'from': 'a', 'to': 'b', 'direction': 'forward',
             'weight': 1, 'edge_label': 'alpha', 'style': 'solid', 'color': 'red', 'status': 'accepted',
             'path': [[.2, .5], [.5, .3], [.8, .5]]},
            {'id': 'second_parallel', 'from': 'a', 'to': 'b', 'direction': 'forward',
             'weight': 2, 'edge_label': 'beta', 'style': 'dashed', 'color': 'blue', 'status': 'accepted',
             'path': [[.2, .5], [.5, .7], [.8, .5]]},
            {'id': 'uncertain_direction', 'from': 'b', 'to': 'a',
             'direction': 'unknown' if uncertain else 'forward', 'weight': 3,
             'edge_label': 'gamma', 'style': 'dotted', 'color': '#2244aa',
             'status': 'pending' if uncertain else 'accepted',
             'path': [[.8, .5], [.5, .5], [.2, .5]]},
        ], 'relation_audit': ['PRIVATE_ROUTE_AUDIT'],
    })


def response_fixture(*, uncertain=False, text_complete=True):
    graph = canonical_fixture(uncertain=uncertain)
    partial = uncertain or not text_complete
    reasons = ['题干文字尚未核对完整。'] if not text_complete else ['部分连线方向尚未确定。'] if uncertain else []
    return {'text': '求图的边数，并计算 \\(x^2+1\\)。',
            'visual_text': 'PRIVATE_SOLVER_GRAPH_TEXT',
            'graph_structures': [graph], 'graph_display_data': [display_graph(graph)],
            'recognition_status': 'partial' if partial else 'complete',
            'review': {'required': partial, 'reasons': reasons},
            'warning': ' '.join(reasons) or None,
            'diagnostics': {'text_evidence': {'source': 'original_visual_transcription',
                                             'complete': text_complete,
                                             'visual_body_complete': text_complete,
                                             'second_pass_reviewed': text_complete,
                                             'reconciliation': {'issues': [] if text_complete else ['text_incomplete']}}}}


def test_public_projection_preserves_atomic_edges_but_is_not_a_drawing_api():
    source = canonical_fixture(uncertain=True)
    original = deepcopy(source)
    public = display_graph(source)
    assert len(public['edges']) == 4
    assert public['edges'][0]['from'] == public['edges'][0]['to'] == 'a'
    assert [edge['direction'] for edge in public['edges']] == ['forward']*3+['unknown']
    assert [edge['weight'] for edge in public['edges']] == [0, 1, 2, 3]
    assert [edge['edge_label'] for edge in public['edges']] == ['loop', 'alpha', 'beta', 'gamma']
    assert [edge['style'] for edge in public['edges']] == ['solid', 'solid', 'dashed', 'dotted']
    assert [edge['color'] for edge in public['edges']] == ['black', 'red', 'blue', '#2244aa']
    assert len([edge for edge in public['edges'] if (edge['from'], edge['to']) == ('a', 'b')]) == 2
    assert all(edge['multiplicity'] == 1 for edge in public['edges'])
    assert public['edges'][-1]['status'] == 'pending' and public['complete'] is False
    assert 'bbox' not in public and all('x' not in vertex for vertex in public['vertices'])
    assert all('path' not in edge for edge in public['edges'])
    assert source == original and source['edges'][0]['path']


def test_semantic_graph_text_preserves_printed_attributes_without_any_positions_or_pixel_evidence():
    raw = canonical_fixture()
    raw['vertices'][0]['label'] = 'v₂'
    raw['vertices'][1]['label'] = 'V₂'
    raw.pop('bbox')
    for vertex in raw['vertices']:
        vertex.pop('x'); vertex.pop('y')
    for edge in raw['edges']:
        edge.pop('path'); edge.pop('evidence')
    raw['edges'][1]['edge_label'] = 'q₂'
    raw['edges'][2]['edge_label'] = 'Q₂'
    graph = canonical_graph(raw)
    before = deepcopy(graph)
    text = describe_graphs([graph])
    assert all(v['x'] is None and v['y'] is None for v in graph['vertices'])
    assert all(e['path'] == [] and e['evidence'] == [] for e in graph['edges'])
    assert 'v₂→V₂' in text and 'V₂→v₂' in text
    assert '边名 q₂' in text and '边名 Q₂' in text and '权值 0' in text
    assert all(style in text for style in ('实线', '虚线', '点线'))
    assert all('颜色 '+color in text for color in ('black', 'red', 'blue', '#2244aa'))
    assert text.count('颜色 ') == len(graph['edges']), 'Each instance has one observed color, without endpoint deduplication.'
    assert '边（共4条）' in text and '自环' in text
    assert graph == before


@pytest.mark.parametrize('color', [None, '', 'unknown', ' UNKNOWN '])
def test_describe_graphs_does_not_invent_an_absent_color(color):
    graph = canonical_fixture()
    for edge in graph['edges']: edge['color'] = color
    assert '颜色 ' not in describe_graphs([graph])


def test_new_pipeline_text_partial_survives_public_envelope(monkeypatch):
    import ocr_nextgen
    monkeypatch.setattr(ocr_nextgen, 'correct_text', lambda text: (text, {'status': 'ok'}))
    result = {'graphs': [canonical_fixture()], 'diagnostics': [],
              'body_text': '未完成的题干', 'body_complete': False}
    public = ocr_nextgen._render_graph_result(b'synthetic', {'text': '已读文字'}, result, 'contract-test', {})
    assert public['graph_structures'][0]['complete'] is True
    assert public['graph_display_data'][0]['complete'] is True
    assert public['review']['required'] is True
    assert public['recognition_status'] == 'partial'
    assert public['diagnostics']['text_evidence']['complete'] is False
    assert any('题干' in reason for reason in public['review']['reasons'])


def test_formatter_keeps_literals_and_separate_document_review_state():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node unavailable; formatter execution not run')
    program = r"""
const fs=require('node:fs'), vm=require('node:vm');
const src=fs.readFileSync('static/script.js','utf8');
const start=src.indexOf('function ocrReviewPlain(');
const end=src.indexOf('// OCR review displays recognized content', start);
const api=vm.runInNewContext(src.slice(start,end)+'\n({ocrReviewPlain,ocrReviewStatusText,formatCanonicalGraphReview})');
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const before=JSON.stringify(payload.graphs);
const rendered=api.formatCanonicalGraphReview(payload.graphs);
process.stdout.write(JSON.stringify({
 literal:api.ocrReviewPlain('<b>A&[x]</b>'), rendered,
 statuses:payload.responses.map(api.ocrReviewStatusText),
 unchanged:before===JSON.stringify(payload.graphs)
}));
"""
    data = {'graphs': response_fixture(uncertain=True)['graph_display_data'],
            'responses': [response_fixture(text_complete=False),
                          {'warning': '旧响应提示'}, {'recognition_status': 'partial'},
                          {'review': {'required': False}, 'recognition_status': 'complete'}, {}]}
    process = subprocess.run([node, '-e', program], input=json.dumps(data, ensure_ascii=False),
                             text=True, capture_output=True, cwd=ROOT, check=True)
    observed = json.loads(process.stdout)
    assert observed['literal'] == '&lt;b&gt;A&amp;&#91;x&#93;&lt;/b&gt;'
    assert observed['unchanged'] is True
    assert observed['rendered'].count('- e') == 4
    assert '甲 → 甲' in observed['rendered'] and '乙 ? 甲' in observed['rendered']
    assert '权值：0' in observed['rendered'] and '虚线' in observed['rendered'] and '点线' in observed['rendered']
    assert '实线' in observed['rendered'] and '颜色：red' in observed['rendered'] and '颜色：blue' in observed['rendered']
    assert observed['statuses'][0].count('题干文字尚未核对完整。') == 1
    assert all('待核对' in text for text in observed['statuses'][:3])
    assert observed['statuses'][3:] == ['', '']


def _synthetic_preview(*, transparent=False):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA' if transparent else 'RGB', (320, 180),
                      (0, 0, 0, 0) if transparent else 'white')
    draw = ImageDraw.Draw(image)
    draw.text((18, 20), 'SYNTHETIC UI CONTRACT ONLY', fill='black')
    draw.text((18, 44), 'No original image / no OCR request', fill='black')
    draw.ellipse((65, 95, 85, 115), outline='black', width=3)
    draw.ellipse((235, 95, 255, 115), outline='black', width=3)
    draw.line((85, 105, 235, 105), fill='black', width=2)
    data = io.BytesIO()
    image.save(data, format='PNG')
    return base64.b64encode(data.getvalue()).decode('ascii')


def test_actual_chromium_dialog_contract(monkeypatch):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE')
    destination = os.environ.get('DMATE_FRONTEND_CONTRACT_OUTPUT')
    if not executable or not destination:
        pytest.skip('Actual browser not run: set executable and private artifact output explicitly')
    pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright
    from flask import Flask, render_template
    from werkzeug.serving import make_server
    from browser_assets import install_verified_cdn_routes
    import requests

    def no_external_asset_download(*args, **kwargs):
        raise AssertionError('Browser contract requires preverified public CDN cache; no external request allowed')

    monkeypatch.setattr(requests.sessions.Session, 'send', no_external_asset_download)

    output = Path(destination).resolve()
    if output == ROOT or ROOT in output.parents:
        pytest.fail('Browser artifacts must remain outside the repository')
    if output.exists() and any(output.iterdir()):
        pytest.fail('Use a new private browser artifact directory; earlier observations are not replaced')
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    cache = Path(os.environ.get('DMATE_BROWSER_CDN_CACHE', str(output.parent/'frontend_public_cdn_cache')))
    app = Flask('dmate_frontend_contract', template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))

    @app.get('/')
    def homepage():
        return render_template('index.html', knowledge_graph_data={},
                               is_dmate_android_app=False, is_dmate_desktop_app=False,
                               android_apk_url='', desktop_windows_url='', desktop_macos_url='',
                               desktop_linux_deb_url='', desktop_linux_appimage_url='')

    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f'http://127.0.0.1:{server.server_port}'
    report = {'kind': 'synthetic_contract', 'fixture_only': True, 'actual_browser': False,
              'execution_scope': 'synthetic_frontend_contract', 'frontend_scope': 'response_dialog_replay',
              'application_status': 'not_run', 'application_certified_passes': 0,
              'recognition_accuracy_test': False, 'first_pass_certified_images': 0,
              'contract': 'original_preview_and_text_cards', 'ocr_requests': [],
              'external_network_requests': 0,
              'source_files': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                               for name in ('static/script.js', 'templates/index.html', 'graph_schema.py')},
              'cases': [], 'page_errors': [], 'external_requests_blocked': []}
    failures = []

    def check(case, name, truth):
        case['checks'].append({'name': name, 'status': 'pass' if truth else 'fail'})
        if not truth:
            failures.append(case['id']+':'+name)

    literal = response_fixture()
    literal_graph = literal['graph_structures'][0]
    literal_graph['name'] = '<b>图&[1]</b>'
    literal_graph['vertices'][0]['label'] = '<img src=x onerror=window.__labelExecuted=1>'
    literal_graph['vertices'][1]['label'] = 'v₁'
    literal_graph['edges'][0]['edge_label'] = '<b>loop&[x]</b>'
    literal_graph['edges'][0]['color'] = '<b>red&[x]</b>'
    literal['graph_display_data'] = [display_graph(literal_graph)]
    legacy = response_fixture()
    for key in ('review', 'warning', 'recognition_status', 'diagnostics'):
        legacy.pop(key)
    cases = [('edge_semantics', response_fixture(uncertain=True)),
             ('literal_labels', literal), ('text_partial', response_fixture(text_complete=False)),
             ('legacy_complete', legacy), ('legacy_warning', {**legacy, 'warning': '旧响应仍需核对题干。'}),
             *[('transparent_'+theme, response_fixture()) for theme in ('light', 'dark', 'navy')]]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=executable, headless=True)
            report.update(actual_browser=True, browser_version=browser.version)
            try:
                for mode, viewport in [('desktop', {'width': 1440, 'height': 1000}),
                                       ('mobile', {'width': 390, 'height': 844})]:
                    context = browser.new_context(viewport=viewport, locale='zh-CN', device_scale_factor=1,
                                                  is_mobile=mode == 'mobile', has_touch=mode == 'mobile')
                    def local_or_public_asset(route):
                        url = route.request.url
                        if urlsplit(url).path == '/ocr':
                            report['ocr_requests'].append({'url': url, 'method': route.request.method})
                            route.abort()
                        elif urlsplit(url).netloc == urlsplit(base_url).netloc:
                            route.continue_()
                        else:
                            report['external_requests_blocked'].append(url)
                            route.abort()
                    context.route('**/*', local_or_public_asset)
                    install_verified_cdn_routes(context, cache)
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    page = context.new_page()
                    page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                    try:
                        response = page.goto(base_url, wait_until='domcontentloaded', timeout=60000)
                        assert response and response.status == 200
                        page.wait_for_function("typeof reviewRecognizedQuestion === 'function' && window.marked && window.DOMPurify && window.MathJax?.typesetPromise", timeout=45000)
                        page.evaluate('async () => { await MathJax.startup.promise; }')
                        selected = cases if mode == 'desktop' else [cases[0], cases[2], *cases[-3:]]
                        for name, payload in selected:
                            case = {'id': mode+'_'+name, 'checks': []}
                            report['cases'].append(case)
                            transparent = name.startswith('transparent_')
                            theme = name.split('_', 1)[1] if transparent else 'light'
                            page.locator('[data-appearance-mode="'+theme+'"]').dispatch_event('click')
                            page.evaluate("""({data, png}) => {
                              const bytes=Uint8Array.from(atob(png), ch=>ch.charCodeAt(0));
                              const file=new File([bytes], 'synthetic-contract.png', {type:'image/png'});
                              window.__labelExecuted=0;
                              window.__contractData=data;
                              window.__contractBefore=JSON.stringify(data);
                              window.__contractPromise=reviewRecognizedQuestion(file,data);
                            }""", {'data': payload, 'png': _synthetic_preview(transparent=transparent)})
                            page.locator('#ocrReviewDialog').wait_for(state='visible')
                            page.wait_for_function("document.querySelector('#ocrReviewImage').naturalWidth === 320")
                            page.wait_for_function("document.querySelector('#ocrReviewQuestion mjx-container svg') !== null", timeout=20000)
                            # Finish the real queued MathJax work before collecting the DOM.
                            page.evaluate("async () => { await renderMath(document.querySelector('#ocrReviewGraph')); }")
                            observed = page.evaluate("""() => {
                              const graph=document.querySelector('#ocrReviewGraph');
                              const question=document.querySelector('#ocrReviewQuestion');
                              const notice=document.querySelector('#ocrReviewError');
                              return {text:graph.textContent, html:graph.innerHTML,
                                rows:[...graph.querySelectorAll('li')].map(el=>el.textContent),
                                heading:graph.querySelector('h3')?.textContent,
                                notice:notice.textContent, noticeCount:document.querySelectorAll('#ocrReviewError').length,
                                imageWidth:document.querySelector('#ocrReviewImage').naturalWidth,
                                imageBackground:getComputedStyle(document.querySelector('#ocrReviewImage')).backgroundColor,
                                theme:document.body.dataset.appearanceTheme,
                                mathSvgCount:question.querySelectorAll('mjx-container svg').length,
                                embeddedImages:graph.querySelectorAll('img').length,
                                injectedMarkup:graph.querySelectorAll('b,em,script').length,
                                codeExecuted:window.__labelExecuted,
                                responseUnchanged:window.__contractBefore===JSON.stringify(window.__contractData),
                                readonly:graph.contentEditable!=='true' && question.contentEditable!=='true',
                                dialogWidth:document.querySelector('#ocrReviewDialog').getBoundingClientRect().width,
                                viewportWidth:window.innerWidth};
                            }""")
                            case['observed'] = observed
                            check(case, 'original_preview_visible', observed['imageWidth'] == 320)
                            check(case, 'mathjax_actually_rendered', observed['mathSvgCount'] > 0)
                            check(case, 'canonical_edges_not_collapsed', len(observed['rows']) == 4)
                            check(case, 'raw_response_unchanged', observed['responseUnchanged'])
                            check(case, 'cards_are_readonly', observed['readonly'])
                            check(case, 'no_internal_diagnostics', 'PRIVATE_' not in observed['text'])
                            check(case, 'dialog_fits_viewport', observed['dialogWidth'] <= observed['viewportWidth'])
                            if transparent:
                                from PIL import Image
                                rendered = Image.open(io.BytesIO(page.locator('#ocrReviewImage').screenshot())).convert('RGB')
                                observed['transparent_background_pixel'] = list(rendered.getpixel((10, 10)))
                                check(case, 'actual_requested_theme', observed['theme'] == theme)
                                check(case, 'white_alpha_background', observed['imageBackground'] == 'rgb(255, 255, 255)'
                                      and observed['transparent_background_pixel'] == [255, 255, 255])
                            if name == 'edge_semantics':
                                rows = [''.join(row.split()) for row in observed['rows']]
                                check(case, 'self_loop_preserved', '甲→甲' in rows[0])
                                check(case, 'distinct_parallel_rows', all('甲→乙' in row for row in rows[1:3])
                                      and 'alpha' in rows[1] and 'beta' in rows[2])
                                check(case, 'zero_weight_preserved', '权值：0' in rows[0])
                                check(case, 'unknown_direction_not_arrow', '乙?甲' in rows[3] and '方向未确定' in rows[3] and '待确认' in rows[3])
                                check(case, 'dash_and_dot_preserved', '虚线' in rows[2] and '点线' in rows[3])
                                check(case, 'observed_colors_and_solid_preserved',
                                      '实线' in rows[1] and '颜色：red' in rows[1]
                                      and '颜色：blue' in rows[2] and '颜色：#2244aa' in rows[3])
                            if name == 'literal_labels':
                                check(case, 'html_labels_are_literal', literal_graph['name'] == observed['heading'].split('（', 1)[-1].rsplit('）', 1)[0]
                                      and literal_graph['vertices'][0]['label'] in observed['text']
                                      and literal_graph['edges'][0]['edge_label'] in observed['rows'][0]
                                      and literal_graph['edges'][0]['color'] in observed['rows'][0])
                                check(case, 'labels_create_no_elements_or_events', observed['embeddedImages'] == 0
                                      and observed['injectedMarkup'] == 0 and observed['codeExecuted'] == 0)
                            if name == 'text_partial':
                                check(case, 'complete_graph_does_not_hide_partial_text', '题干文字尚未核对完整。' in observed['notice'])
                                check(case, 'single_document_notice', observed['noticeCount'] == 1 and observed['notice'].count('题干文字尚未核对完整。') == 1)
                            if name == 'legacy_complete':
                                check(case, 'legacy_complete_stays_quiet', not observed['notice'])
                            if name == 'legacy_warning':
                                check(case, 'legacy_warning_remains_visible', observed['notice'].count('旧响应仍需核对题干。') == 1)
                            page.locator('#ocrReviewGraph').scroll_into_view_if_needed()
                            page.screenshot(path=str(output/(case['id']+'.png')), full_page=False)
                            if observed['notice']:
                                page.locator('#ocrReviewError').scroll_into_view_if_needed()
                                page.screenshot(path=str(output/(case['id']+'_notice.png')), full_page=False)
                            (output/(case['id']+'_dom.json')).write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding='utf-8')
                            page.locator('#ocrReviewCancel').click()
                            page.locator('#ocrReviewDialog').wait_for(state='hidden')
                            page.evaluate('async () => { await window.__contractPromise; }')
                    finally:
                        context.tracing.stop(path=str(output/(mode+'_trace.zip')))
                        context.close()
            finally:
                browser.close()
        if report['ocr_requests']:
            failures.append('unexpected_ocr_request')
        if report['page_errors']:
            failures.append('browser_page_error')
    except Exception as exc:
        report['exception_type'] = type(exc).__name__
        failures.append(str(exc)[:1800])
        raise
    finally:
        server.shutdown()
        thread.join(timeout=5)
        report['failures'] = failures
        report['status'] = 'pass' if not failures and report['actual_browser'] else 'fail'
        (output/'contract_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert not failures, failures
