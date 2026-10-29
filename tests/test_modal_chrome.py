"""New tool headers match the existing modal chrome in the full page CSS."""
import os
import re
import shutil
from pathlib import Path

import pytest
from jinja2 import Template

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (700, 900), (390, 844)])
def modal_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    html = (ROOT / 'templates/index.html').read_text()
    # Keep the complete production DOM and stylesheet order, including themes
    # and the two different notebook/header responsive breakpoints.
    html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.I)
    html = Template(html).render(dmate_web_revision='modal-chrome-test',
                                 is_android=request.param[0] <= 760,
                                 is_android_browser=request.param[0] <= 760)
    html = re.sub(
        r'<link\b[^>]*href="(/static/[^"?]+\.css)[^">]*"[^>]*>',
        lambda match: '<style data-dmate-css="' + Path(match[1]).name + '">'
        + (ROOT / match[1].lstrip('/')).read_text() + '</style>', html)
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]},
                                reduced_motion='reduce')
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content(html)
        for name in ['graph-editor-model.js', 'graph-editor-format.js', 'graph-editor-overlay.js',
                     'graph-editor.js', 'drawing-export.js', 'drawing-workspace.js',
                     'graph-scan-workspace.js', 'concept-notebook-model.js', 'concept-notebook.js']:
            page.add_script_tag(content=(ROOT / 'static' / name).read_text())
        page.evaluate('''()=>{
          window.notes={notes:[{id:'n1',title:'集合',content:'集合的原始笔记。',updatedAt:1}],deleted:{}};
          window.notebook=DMateConceptNotebook.mount({button:document.querySelector('#conceptNotebookBtn'),
            dialog:document.querySelector('#conceptNotebookDialog'),getState:()=>structuredClone(notes),
            onChange:value=>{notes=value;},getContextKey:()=> 'alice'});
          window.sample={body_text:'原图的文字。',graphs:[{id:'G1',name:'原图',directed:false,weighted:false,
            vertices:[{id:'a',label:'A',x:.25,y:.35},{id:'b',label:'B',x:.75,y:.65}],
            edges:[{id:'ab',from:'a',to:'b',direction:'none',weight:null,edge_label:null}]}]};
          window.openGraph=mode=>{
            const dialog=document.querySelector('#graphEditorDialog'),mount=document.querySelector('#graphEditorMount');
            if(dialog.open)dialog.close();window.workspace?.destroy();
            document.querySelector('#graphEditorTitle').textContent=mode==='drawing'?'绘图':'离散数学图形.png';
            document.querySelector('#graphEditorClose').setAttribute('aria-label',mode==='drawing'?'关闭绘图':'关闭图形识别编辑器');
            if(mode==='drawing')window.workspace=DMateDrawingWorkspace.mount(mount,{
              storageKey:'modal-chrome-test',legacyDocument:structuredClone(sample),onClose:()=>dialog.close()});
            else window.workspace=DMateGraphScan.mount(mount,{
              document:structuredClone(sample),initialDocument:structuredClone(sample),
              originalUrl:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="100%" height="100%" fill="white"/></svg>'),
              onConfirm:async()=>{}});
            dialog.showModal();
          };
          document.querySelector('#graphEditorClose').addEventListener('click',()=>document.querySelector('#graphEditorDialog').close());
          window.measureHeader=(title,box,close)=>{
            const t=document.querySelector(title),b=document.querySelector(box),c=document.querySelector(close);
            const s=getComputedStyle(t),a=t.getBoundingClientRect(),r=b.getBoundingClientRect(),q=c.getBoundingClientRect();
            return {font:Object.fromEntries(['fontFamily','fontSize','fontWeight','lineHeight'].map(k=>[k,s[k]])),
              title:[a.x-r.x,a.y-r.y],size:[q.width,q.height],offset:[r.right-q.right,q.y-r.y],
              background:getComputedStyle(c).backgroundColor,radius:getComputedStyle(c).borderRadius};
          };
          window.referenceHeaders=()=>{
            return ['wrongBook','learningReview','knowledgeGraph'].map(name=>{
              const modal=document.querySelector('#'+name+'Modal');modal.classList.remove('hidden');
              const result=measureHeader('#'+name+'Modal .modal-head>div','#'+name+'Modal .modal-card','#'+name+'Modal .modal-close-dot');
              modal.classList.add('hidden');return result;
            });
          };
        }''')
        source = (ROOT / 'static/script.js').read_text()
        grouping = source[source.index('function nextOcrGroupId()'):source.index('function renderOcrTasks()')]
        page.add_script_tag(content='''
          const OCR_MAX_CONCURRENT=4,ocrTasks=new Map(),ocrSolvingSessions=new Set();
          let ocrBatchPreparing=false;
          function renderOcrTasks(){renderOcrGrouping(document.querySelector('#ocrTaskPanel'),true);}
        ''' + grouping)
        yield page
        browser.close()


def header(page, notebook=False):
    page.mouse.move(0, 0)
    return page.evaluate('''(notebook)=>notebook?
      measureHeader('.dcn-heading>h2','#conceptNotebookDialog','.dcn-heading>.dcn-close'):
      measureHeader('#graphEditorTitle','#graphEditorDialog','#graphEditorClose')''', notebook)


def assert_matching_chrome(actual, reference):
    assert actual['font'] == reference['font']
    for field in ['title', 'size', 'offset']:
        assert actual[field] == pytest.approx(reference[field], abs=.05)
    assert actual['background'] == reference['background'] == 'rgb(239, 68, 68)'
    assert actual['radius'] == reference['radius'] == '50%'


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_group_title_and_close_match_wrongbook_header_at_every_font_scale(modal_page, theme):
    page = modal_page
    page.evaluate('''theme=>{
      document.documentElement.dataset.appearanceTheme=theme;document.body.dataset.appearanceTheme=theme;
      ocrTasks.set('group-one',{id:'group-one',file:{name:'图.png'},groupId:'1',isQuestion:true,
        originalUrl:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30"/>')});
      openOcrGrouping();
    }''', theme)
    for scale in [.9, 1, 1.12]:
        page.evaluate('scale=>document.documentElement.style.setProperty("--font-scale",scale)', scale)
        actual = page.evaluate('measureHeader("#ocrGroupingTitle","#ocrGroupingDialog",".ocr-group-close")')
        reference = page.evaluate('referenceHeaders()[0]')
        assert_matching_chrome(actual, reference)
    bounds = page.locator('#ocrGroupingDialog').bounding_box()
    assert 0 <= bounds['x'] and bounds['x'] + bounds['width'] <= page.viewport_size['width']
    assert 0 <= bounds['y'] and bounds['y'] + bounds['height'] <= page.viewport_size['height']
    assert page.get_by_role('group', name='图片1是否为题目').get_by_role('button', name='是').get_attribute('aria-pressed') == 'true'
    page.get_by_label('图片1组别').select_option('2')
    assert page.evaluate('ocrTasks.get("group-one").groupId') == '2'
    page.get_by_label('关闭分组').click()
    assert not page.locator('#ocrGroupingDialog').evaluate('e=>e.open')


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_new_headers_match_real_existing_modal_typography_and_close_geometry(modal_page, theme):
    page = modal_page
    page.evaluate('theme=>{document.documentElement.dataset.appearanceTheme=theme;document.body.dataset.appearanceTheme=theme;}', theme)
    for scale in ['.9', '1', '1.15']:
        page.mouse.move(0, 0)
        page.evaluate('scale=>document.documentElement.style.setProperty("--font-scale",scale)', scale)
        references = page.evaluate('referenceHeaders()')
        assert references[0] == references[1] == references[2]
        for mode in ['drawing', 'scan']:
            page.evaluate('openGraph', mode)
            assert_matching_chrome(header(page), references[0])
            page.evaluate('document.querySelector("#graphEditorDialog").close()')
        page.evaluate('notebook.open()')
        assert_matching_chrome(header(page, notebook=True), references[0])
        page.get_by_role('button', name='关闭笔记本', exact=True).click()
        page.evaluate('notes={notes:[],deleted:{}};notebook.open()')
        assert_matching_chrome(header(page, notebook=True), references[0])
        assert page.locator('.dcn-main').is_hidden()
        assert page.locator('.dcn-selection').is_hidden()
        assert page.locator('.dcn-list').inner_text() == '无'
        assert page.locator('#conceptNotebookDialog').bounding_box()['height'] < 300
        page.get_by_role('button', name='关闭笔记本', exact=True).click()
        page.evaluate("notes={notes:[{id:'n1',title:'集合',content:'保留的概念笔记。',updatedAt:1}],deleted:{}}")
        stage_font = page.locator('#ocrTaskTitle').evaluate('''e=>{
          const s=getComputedStyle(e);return Object.fromEntries(['fontFamily','fontSize','fontWeight','lineHeight'].map(k=>[k,s[k]]));
        }''')
        assert stage_font == references[0]['font']


@pytest.mark.parametrize('mode', ['drawing', 'scan'])
def test_long_filename_and_content_scroll_keep_main_red_close_in_fixed_header(modal_page, mode):
    page = modal_page
    page.evaluate('openGraph', mode)
    before, dialog = header(page), page.locator('#graphEditorDialog').bounding_box()
    original_height = page.locator('.graph-editor-dialog-head').bounding_box()['height']
    page.locator('#graphEditorTitle').evaluate('e=>e.textContent="需要核对的离散数学原图_".repeat(80)+".png"')
    assert page.locator('.graph-editor-dialog-head').bounding_box()['height'] == original_height
    assert header(page)['offset'] == before['offset']
    assert page.locator('#graphEditorTitle').evaluate('e=>e.scrollWidth>e.clientWidth')
    assert page.locator('#graphEditorDialog').bounding_box() == dialog
    if mode == 'drawing':
        page.get_by_role('button', name='AI指导', exact=True).click()
        scroller = page.locator('.ddw-side-panel')
    else:
        scroller = page.locator('.dgs-content')
    scroller.evaluate('e=>{const p=document.createElement("p");p.textContent="保留的内容。".repeat(3000);e.append(p);e.scrollTop=e.scrollHeight;}')
    assert scroller.evaluate('e=>e.scrollTop') > 0
    assert header(page)['offset'] == before['offset']
    assert page.locator('#graphEditorDialog').evaluate('e=>e.scrollTop') == 0
    page.locator('#graphEditorClose').focus()
    assert page.locator('#graphEditorClose').evaluate('e=>getComputedStyle(e).outlineStyle') == 'none'
    page.locator('#graphEditorClose').click()
    assert not page.locator('#graphEditorDialog').evaluate('e=>e.open')


def test_header_unification_keeps_bodies_inside_dialogs_and_in_header_flow(modal_page):
    page = modal_page
    page.evaluate('openGraph("drawing")')
    page.wait_for_function('document.querySelector(".dge-overlay-image")?.naturalWidth===1000')
    measure = '''notebook=>{
      const rect=selector=>{
        const r=document.querySelector(selector).getBoundingClientRect();
        return Object.fromEntries(['x','y','width','height','right','bottom'].map(k=>[k,r[k]]));
      };
      const dialog=document.querySelector(notebook?'#conceptNotebookDialog':'#graphEditorDialog');
      const heading=dialog.querySelector(notebook?'.dcn-heading':'.graph-editor-dialog-head');
      const result={dialog:rect(notebook?'#conceptNotebookDialog':'#graphEditorDialog'),
        headerBottom:heading.getBoundingClientRect().bottom,
        flowBottom:heading.getBoundingClientRect().bottom+parseFloat(getComputedStyle(heading).marginBottom)};
      if(notebook){
        result.flowBottom+=parseFloat(getComputedStyle(dialog).rowGap);
        result.content=rect('.dcn-content');
      }else{
        result.canvas=rect('.dge-overlay-viewport');result.controls=rect('.dge-view-controls');
      }
      return result;
    }'''
    current = page.evaluate(measure, False)
    page.evaluate('document.querySelector(\'style[data-dmate-css="modal-chrome.css"]\').sheet.disabled=true')
    previous = page.evaluate(measure, False)
    assert current['dialog'] == pytest.approx(previous['dialog'], abs=.05)
    # The new inherited title font may change header height with the browser's
    # installed fonts. Both canvas and view bar must follow that same flow;
    # horizontal placement, bar height and the canvas bottom remain stable.
    flow_shift = current['flowBottom'] - previous['flowBottom']
    for name in ['canvas', 'controls']:
        for field in ['x', 'width']:
            assert current[name][field] == pytest.approx(previous[name][field], abs=.05)
        assert current[name]['y'] - previous[name]['y'] == pytest.approx(flow_shift, abs=.05)
        assert current[name]['width'] > 0 and current[name]['height'] > 0
        assert current['headerBottom'] <= current[name]['y']
        assert current['dialog']['x'] <= current[name]['x']
        assert current[name]['right'] <= current['dialog']['right']
        assert current[name]['bottom'] <= current['dialog']['bottom']
    assert current['controls']['height'] == pytest.approx(previous['controls']['height'], abs=.05)
    assert current['canvas']['bottom'] == pytest.approx(previous['canvas']['bottom'], abs=.05)
    assert current['controls']['bottom'] <= current['canvas']['y']
    page.evaluate('document.querySelector(\'style[data-dmate-css="modal-chrome.css"]\').sheet.disabled=false;document.querySelector("#graphEditorDialog").close();notebook.open()')
    current = page.evaluate(measure, True)
    page.evaluate('document.querySelector(\'style[data-dmate-css="modal-chrome.css"]\').sheet.disabled=true')
    previous = page.evaluate(measure, True)
    assert current['dialog'] == pytest.approx(previous['dialog'], abs=.05)
    for field in ['x', 'width', 'bottom']:
        assert current['content'][field] == pytest.approx(previous['content'][field], abs=.05)
    assert current['content']['y'] - previous['content']['y'] == pytest.approx(
        current['flowBottom'] - previous['flowBottom'], abs=.05)
    assert current['content']['width'] > 0 and current['content']['height'] > 0
    assert current['headerBottom'] <= current['content']['y']
    assert current['dialog']['x'] <= current['content']['x']
    assert current['content']['right'] <= current['dialog']['right']
    assert current['content']['bottom'] <= current['dialog']['bottom']
    assert page.locator('.dcn-content').evaluate('e=>e.scrollWidth<=e.clientWidth')


def test_full_page_menu_has_wider_group_gap_and_dmate_placeholder(modal_page):
    page = modal_page
    page.evaluate('document.body.classList.add("mobile-tools-open")')
    assert page.locator('#text').get_attribute('placeholder') == '询问DMate'
    menu = page.locator('.learning-panel')
    assert menu.locator('.learning-tools-primary button,.learning-tools-secondary button').all_text_contents() == [
        '错题本 (0)', '笔记本', '知识图谱', '绘图', '学习报告']
    primary, secondary = menu.locator('.learning-tools-primary').bounding_box(), menu.locator('.learning-tools-secondary').bounding_box()
    assert secondary['y'] - primary['y'] - primary['height'] == pytest.approx(32, abs=.1)
