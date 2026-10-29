"""System defaults and panel alpha use the production appearance controls/CSS."""
import os
import re
import shutil
from pathlib import Path

import pytest
from jinja2 import Template

ROOT = Path(__file__).resolve().parents[1]
PAINT_STYLE = r'''e=>{
  const s=getComputedStyle(e),match=s.backgroundColor.match(/rgba?\(([^)]+)\)/);
  return {color:s.backgroundColor,alpha:match?(match[1].split(',').length===4?Number(match[1].split(',')[3]):1):null,
    image:s.backgroundImage,opacity:s.opacity,text:s.color};
}'''


def appearance_html(width):
    source = (ROOT / 'templates/index.html').read_text()
    source = re.sub(r'<script\b[^>]*>[\s\S]*?</script>',
                    lambda match: match[0] if re.search(r'id="dmateAppearance(?:Body)?Bootstrap"', match[0]) else '',
                    source, flags=re.I)
    source = Template(source).render(dmate_web_revision='appearance-test',
                                     is_android=width <= 760, is_android_browser=width <= 760)
    return re.sub(r'<link\b[^>]*href="(/static/[^"?]+\.css)[^">]*"[^>]*>',
                  lambda match: '<style>' + (ROOT / match[1].lstrip('/')).read_text() + '</style>', source)


@pytest.fixture(params=[(1440, 900), (390, 844)])
def appearance_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]},
                                color_scheme='dark', reduced_motion='reduce')
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content(appearance_html(request.param[0]))
        yield page
        browser.close()


def install_appearance(page, authenticated=False, mode=None):
    page.evaluate('''({authenticated,mode})=>{
      window.accountState={authenticated,username:authenticated?'alice':''};
      window.shouldPersistClientState=()=>Boolean(accountState.authenticated&&accountState.username);
      window.readCloudSyncMeta=()=>({});window.toasts=[];window.showCopyToast=text=>toasts.push(text);
      if(mode)localStorage.setItem('discrete_math_ai_appearance_v1::alice',JSON.stringify({mode,panelOpacity:85}));
    }''', {'authenticated': authenticated, 'mode': mode})
    script = (ROOT / 'static/script.js').read_text()
    source = script[script.index('const APPEARANCE_STORAGE_KEY'):script.index('\n\nlet wrongBookFilter')]
    page.add_script_tag(content=source)
    # Exercise real preview/cancel/save state transitions without IndexedDB or
    # background-image conversion; no AI, OCR or ASR endpoint is contacted.
    page.evaluate('''()=>{
      window.backgroundReads=0;
      loadAppearanceBackground=async()=>{backgroundReads++;};
      writeAppearanceBackgroundBlob=async()=>{};deleteAppearanceBackgroundBlob=async()=>{};
      initAppearanceSystem();
    }''')


def paint(page, selector):
    assert page.locator(selector).count(), selector
    return page.locator(selector).first.evaluate(PAINT_STYLE)


def paints(page, selectors):
    return page.evaluate('''selectors=>{
      const read=''' + PAINT_STYLE + ''';
      return Object.fromEntries(selectors.map(selector=>{
        const element=document.querySelector(selector);
        if(!element)throw new Error('Panel missing: '+selector);
        return [selector,read(element)];
      }));
    }''', selectors)


@pytest.mark.parametrize('system', ['light', 'dark'])
def test_first_frame_and_default_follow_system_without_account_storage(appearance_page, system):
    page = appearance_page
    page.emulate_media(color_scheme=system)
    page.set_content(appearance_html(page.viewport_size['width']))
    assert page.locator('html').get_attribute('data-appearance-theme') == system
    assert page.locator('body').get_attribute('data-appearance-theme') == system
    assert page.locator('meta[name="color-scheme"]').get_attribute('content') == ('only light' if system == 'light' else 'dark')
    page.evaluate("localStorage.setItem('discrete_math_ai_appearance_v1::alice',JSON.stringify({mode:'light'}))")
    install_appearance(page)
    assert page.evaluate('appearanceSettings.mode') == 'system'
    assert page.locator('body').get_attribute('data-appearance-theme') == system
    page.emulate_media(color_scheme='light')
    page.wait_for_function('document.body.dataset.appearanceTheme==="light"')
    assert page.locator('meta[name="color-scheme"]').get_attribute('content') == 'only light'
    page.emulate_media(color_scheme='dark')
    page.wait_for_function('document.body.dataset.appearanceTheme==="dark"')


@pytest.mark.parametrize('mode', ['light', 'dark'])
def test_authenticated_explicit_mode_survives_system_changes_and_reset_uses_system(appearance_page, mode):
    page = appearance_page
    install_appearance(page, authenticated=True, mode=mode)
    assert page.evaluate('appearanceSettings.mode') == mode
    assert page.evaluate('appearanceSettings.panelOpacity') == 85
    page.emulate_media(color_scheme='light' if mode == 'dark' else 'dark')
    page.wait_for_timeout(30)
    assert page.locator('body').get_attribute('data-appearance-theme') == mode
    page.evaluate('openAppearance()')
    page.get_by_role('button', name='恢复默认', exact=True).click()
    assert page.evaluate('appearanceSettings.mode') == 'system'
    assert page.locator('body').get_attribute('data-appearance-theme') == ('light' if mode == 'dark' else 'dark')
    page.get_by_role('button', name='确认', exact=True).click()
    assert page.evaluate("JSON.parse(localStorage.getItem('discrete_math_ai_appearance_v1::alice')).mode") == 'system'


def test_panel_slider_previews_cancels_and_commits_without_changing_bubble_opacity(appearance_page):
    page = appearance_page
    install_appearance(page, authenticated=True, mode='light')
    page.evaluate('openAppearance()')
    slider = page.locator('#appearancePanelRange')
    assert slider.get_attribute('min') == '75'
    slider.fill('75')
    assert page.evaluate('appearanceSettings.panelOpacity') == 75
    assert paint(page, '#appearanceModal .modal-card')['alpha'] == .75
    assert page.evaluate("JSON.parse(localStorage.getItem('discrete_math_ai_appearance_v1::alice')).panelOpacity") == 85
    page.locator('#appearanceClose').click()
    page.wait_for_function('appearanceSettings.panelOpacity===85')
    assert paint(page, '#appearanceModal .modal-card')['alpha'] == .85
    page.evaluate('openAppearance()')
    slider.fill('100')
    page.locator('#appearanceDone').click()
    assert page.evaluate("JSON.parse(localStorage.getItem('discrete_math_ai_appearance_v1::alice')).panelOpacity") == 100
    assert page.evaluate('appearanceSettings.bubbleOpacity') == 100
    assert page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--bubble-alpha")') == '1'


def test_panel_alpha_preserves_wallpaper_and_its_image_preview(appearance_page):
    page = appearance_page
    install_appearance(page)
    page.evaluate('''()=>{
      const image=new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="green"/></svg>'],{type:'image/svg+xml'});
      setAppearanceBackgroundVisual(image);
    }''')
    wallpaper = page.locator('#appearanceBackgroundLayer').evaluate('e=>getComputedStyle(e).backgroundImage')
    preview = page.locator('#appearanceBackgroundPreview').evaluate('e=>getComputedStyle(e).backgroundImage')
    assert wallpaper.startswith('url(') and preview.startswith('url(')
    page.evaluate('appearanceSettings.panelOpacity=75;applyAppearanceSettings({save:false})')
    assert page.locator('#appearanceBackgroundLayer').evaluate('e=>getComputedStyle(e).backgroundImage') == wallpaper
    assert page.locator('#appearanceBackgroundPreview').evaluate('e=>getComputedStyle(e).backgroundImage') == preview
    assert page.locator('body').evaluate('e=>e.classList.contains("has-custom-background")')


def install_panel_examples(page):
    for name in ['graph-editor-model.js', 'graph-editor-format.js', 'graph-editor-overlay.js',
                 'graph-editor.js', 'drawing-export.js', 'drawing-workspace.js',
                 'graph-scan-workspace.js', 'concept-notebook.js']:
        page.add_script_tag(content=(ROOT / 'static' / name).read_text())
    page.evaluate('''async()=>{
      window.notebook=DMateConceptNotebook.mount({button:document.querySelector('#conceptNotebookBtn'),
        dialog:document.querySelector('#conceptNotebookDialog'),getContextKey:()=>'',
        getState:()=>({notes:[{id:'n1',title:'集合',content:'概念原文。',updatedAt:1}],deleted:{}}),onChange:()=>{}});
      notebook.open();notebook.close();
      await new Promise(resolve=>requestAnimationFrame(resolve));
      const doc={body_text:'题目文字。',graphs:[{id:'G1',name:'原图',directed:false,weighted:false,
        vertices:[{id:'a',label:'A',x:.2,y:.3},{id:'b',label:'B',x:.8,y:.7}],
        edges:[{id:'ab',from:'a',to:'b',direction:'none',weight:null,edge_label:null}]}]};
      window.drawing=DMateDrawingWorkspace.mount(document.querySelector('#graphEditorMount'),{
        storageKey:'appearance-panel-test',legacyDocument:structuredClone(doc)});
      document.querySelector('.ddw-page-actions button:nth-child(2)').click();
      const scan=document.createElement('div');scan.id='appearance-scan';document.body.append(scan);
      const state={sourcesVersion:3,mode:'manual',nativeDocument:structuredClone(doc),
        graphRegions:[],textRegions:[{id:1,status:'complete',text:'局部文字。',selected:true,
          polygon:[[.1,.1],[.4,.1],[.4,.4],[.1,.4]]}]};
      window.scan=DMateGraphScan.mount(scan,{document:structuredClone(doc),initialDocument:structuredClone(doc),
        scanState:state,originalUrl:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="100%" height="100%" fill="white"/></svg>'),onConfirm:async()=>{}});
      scan.querySelector('[data-source-picker="text"]').click();
      const append=(parent,html)=>document.querySelector(parent).insertAdjacentHTML('beforeend',html);
      append('#wrongBookList','<div class="wrong-card"><div class="wrong-feedback">已保存的回答。</div></div>');
      append('#learningReviewBody','<section class="learning-review-section">学习报告。</section>');
      append('#knowledgeGraphCanvas','<section class="kg-section"><div class="kg-mobile-viewport">图谱</div></section>');
      append('#knowledgeGraphDetail','<div class="graph-metric">3</div>');
      append('.dcn-results','<section class="dcn-explanation">概念解释。</section>');
      append('#ocrTaskList','<article class="ocr-task-card"><img class="ocr-task-thumbnail" alt="原图"><div class="ocr-task-structure">图形结构</div></article>');
      append('#graphEditorMount','<aside class="dge-selection-panel">属性</aside><div class="ddw-export-preview"><img class="ddw-export-image" alt="导出图片"></div>');
      append('body','<dialog class="ocr-group-dialog"><div class="ocr-group-row"><img alt="原图"></div></dialog><dialog class="dcn-confirm"></dialog><div class="dmate-png-save-panel"><img class="dmate-png-save-preview" alt="预览"></div><div class="ai">AI回答</div><div class="user">消息</div>');
    }''')


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
@pytest.mark.parametrize('wallpaper', [False, True])
def test_all_major_panels_follow_slider_and_structural_wrappers_do_not_stack(appearance_page, theme, wallpaper):
    page = appearance_page
    install_appearance(page)
    install_panel_examples(page)
    surfaces = ['.left', '.right', '.input', '#appearanceModal .modal-card', '#accountModal .modal-card',
                '#wrongBookModal .modal-card', '#wrongBookList .wrong-card', '#learningReviewModal .modal-card',
                '.learning-review-section', '#knowledgeGraphModal .modal-card', '.kg-section', '.kg-mobile-viewport',
                '.graph-metric', '#graphEditorDialog', '#conceptNotebookDialog', '.dcn-note.is-current',
                '.dcn-explanation', '.dcn-confirm', '.ocr-task-panel', '.ocr-task-card', '.ocr-task-structure',
                '.ocr-group-dialog', '.ddw-side-panel', '.ddw-history-item.is-current', '.ddw-export-preview',
                '.dge-selection-panel', '.dge-view-controls', '.dge-float-content', '.dge-tool-palette>.dge-overlay-tools',
                '.dgs-information-card', '.dgs-source-picker',
                '.dgs-source-card', '.dmate-png-save-panel', '.ocr-review-rendered', '.ocr-review-preview',
                '.appearance-background-preview']
    wrappers = ['.layout', '.center', '.chat', '.input-wrap', '#appearanceModal .modal-head',
                '.appearance-body', '.appearance-footer', '#accountModal .modal-head', '.account-body',
                '.wrong-toolbar', '.wrong-tools', '#wrongBookList', '.learning-review-body', '.graph-toolbar',
                '.knowledge-graph-canvas', '.knowledge-graph-side', '.dgs-information', '.dge-overlay-host',
                '.dge-overlay-viewport', '.appearance-background-viewer-body', '#info']
    content = ['.dge-overlay-stage', '.dge-overlay-image', '.ddw-export-image', '.dmate-png-save-preview',
               '.ocr-task-thumbnail', '.ocr-group-row>img']
    page.evaluate('''({theme,wallpaper})=>{
      appearanceSettings.mode=theme;appearanceSettings.bubbleOpacity=80;
      document.body.classList.toggle('has-custom-background',wallpaper);
      applyAppearanceSettings({save:false});
    }''', {'theme': theme, 'wallpaper': wallpaper})
    selectors = surfaces + wrappers + content + ['.ai', '.user', '#graphEditorClose', '#sendBtn']
    baseline = paints(page, selectors)
    for amount in [100, 85, 75]:
        page.evaluate('amount=>{appearanceSettings.panelOpacity=amount;applyAppearanceSettings({save:false});}', amount)
        styles = paints(page, selectors)
        for selector in surfaces:
            actual = styles[selector]
            assert actual['alpha'] == pytest.approx(amount / 100, abs=.005), (selector, actual)
            assert actual['image'] == 'none', (selector, actual)
            assert actual['opacity'] == '1', (selector, actual)
            assert actual['text'] == baseline[selector]['text'], (selector, actual)
        for selector in wrappers:
            actual = styles[selector]
            assert actual['alpha'] == 0 and actual['image'] == 'none', (selector, actual)
        for selector in content:
            actual = styles[selector]
            assert actual['alpha'] == 1 and actual['opacity'] == '1', (selector, actual)
        for selector in ['.ai', '.user']:
            assert styles[selector] == baseline[selector]
        assert styles['#graphEditorClose']['alpha'] == 1
        assert styles['#sendBtn']['alpha'] == 1
        assert page.evaluate('getComputedStyle(document.body).opacity') == '1'
