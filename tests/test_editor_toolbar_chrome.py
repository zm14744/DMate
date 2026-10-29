"""Full-template toolbar paint and spacing retain real editor interactions."""
from pathlib import Path
import re

import pytest

from test_drawing_editor_controls import drawing_page
from test_scan_drawing_separation import drag, open_scan, scan_page

ROOT=Path(__file__).resolve().parents[1]


def install_production_appearance(page):
    template=(ROOT/'templates/index.html').read_text()
    blocks=[];linked=[]
    # The graph stylesheet sits between two inline template styles. Rebuild
    # that full order rather than appending a second, differently ordered copy
    # to the lightweight fixtures' existing styles.
    for match in re.finditer(r'<style\b[^>]*>([\s\S]*?)</style>|<link\b[^>]*href="(/static/[^"?]+\.css)[^"]*"[^>]*>',template,re.I):
        if match[1] is not None:blocks.append(match[1])
        else:
            path=ROOT/match[2].lstrip('/');linked.append(path.name);blocks.append(path.read_text())
    assert linked[-2:]==['appearance-panels.css','red-circle-controls.css']
    theme='dark' if page.viewport_size['width']<760 else 'light'
    page.emulate_media(color_scheme=theme)
    page.evaluate('''theme=>{
      for(const node of [document.documentElement,document.body]){
        node.dataset.appearanceTheme=theme;node.style.colorScheme=theme==='light'?'only light':'dark';
      }
      document.documentElement.style.setProperty('--panel-alpha','.85');
      document.querySelectorAll('head style').forEach(style=>style.remove());
    }''',theme)
    sheet=page.add_style_tag(content='\n'.join(blocks))
    sheet.evaluate('(style,files)=>style.dataset.toolbarProductionCss=files.join(",")',linked)
    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert page.locator('html').get_attribute('data-appearance-theme')==theme
    assert page.locator('body').get_attribute('data-appearance-theme')==theme


def assert_appearance_panel_is_active(page):
    # Structural toolbar backgrounds may intentionally stay transparent.
    # An independent popup proves the important appearance layer is active
    # without imposing a second paint layer on the real scan toolbar.
    assert page.evaluate('''()=>{
      const panel=document.createElement('div');panel.className='dge-float-content';
      panel.style.cssText='position:fixed;visibility:hidden;background-color:rgb(255,0,255)';document.body.append(panel);
      const color=getComputedStyle(panel).backgroundColor,match=color.match(/^rgba\\((.*),\\s*([.\\d]+)\\)$/);
      panel.remove();return !!match&&Math.abs(Number(match[2])-.85)<.001;
    }''')


def history_icons(page):
    return page.locator('.dge-history-arrow').evaluate_all('''buttons=>buttons.map(button=>{
      const svg=button.querySelector('svg'),box=svg?.getBoundingClientRect();return {
        label:button.getAttribute('aria-label'),title:button.title,text:button.textContent,
        hidden:svg?.getAttribute('aria-hidden'),focusable:svg?.getAttribute('focusable'),
        viewBox:svg?.getAttribute('viewBox'),stroke:svg?.getAttribute('stroke'),
        width:box?.width,height:box?.height,color:getComputedStyle(button).color,
        paths:[...button.querySelectorAll('path')].map(path=>({d:path.getAttribute('d'),
          stroke:getComputedStyle(path).stroke,cap:getComputedStyle(path).strokeLinecap,
          join:getComputedStyle(path).strokeLinejoin,bounds:[path.getBBox().width,path.getBBox().height]}))};})''')


def test_undo_redo_use_fixed_svg_paths_and_still_restore_the_actual_model(drawing_page):
    page=drawing_page
    install_production_appearance(page)
    page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    assert_appearance_panel_is_active(page)
    page.evaluate('window.beforeHistory=JSON.stringify(editor.getDocument())')
    icons=history_icons(page)
    assert [icon['label'] for icon in icons]==['撤销','重做']
    for icon in icons:
        assert icon['title']==icon['label'] and icon['text']==''
        assert icon['viewBox']=='0 0 24 24' and icon['stroke']=='currentColor'
        assert icon['hidden']=='true' and icon['focusable']=='false'
        assert (icon['width'],icon['height'])==(24,24)
        assert len(icon['paths'])==2
        for path in icon['paths']:
            assert len(path['d'])>8 and all(value>0 for value in path['bounds'])
            assert path['stroke']==icon['color']
            assert path['cap']==path['join']=='round'
    assert [path['d'] for path in icons[0]['paths']] != [path['d'] for path in icons[1]['paths']]
    assert page.get_by_role('button',name='撤销',exact=True).is_disabled()
    assert page.get_by_role('button',name='重做',exact=True).is_disabled()
    page.locator('[data-vertex-id="a"] .dge-overlay-node-hit').click()
    page.get_by_role('button',name='删除这个顶点',exact=True).click()
    deleted=page.evaluate('editor.getDocument()')
    assert [vertex['id'] for vertex in deleted['graphs'][0]['vertices']]==['b']
    assert deleted['graphs'][0]['edges']==[]
    assert not page.get_by_role('button',name='撤销',exact=True).is_disabled()
    assert page.get_by_role('button',name='重做',exact=True).is_disabled()
    page.get_by_role('button',name='撤销',exact=True).click()
    assert page.evaluate('JSON.stringify(editor.getDocument())===beforeHistory')
    assert page.get_by_role('button',name='撤销',exact=True).is_disabled()
    assert not page.get_by_role('button',name='重做',exact=True).is_disabled()
    page.get_by_role('button',name='重做',exact=True).click()
    assert page.evaluate('editor.getDocument()')==deleted
    assert page.get_by_role('button',name='重做',exact=True).is_disabled()
    after=history_icons(page)
    for initial,current in zip(icons,after):
        assert [p['d'] for p in initial['paths']]==[p['d'] for p in current['paths']]
        assert (current['width'],current['height'])==(24,24)
    size='mobile' if page.viewport_size['width']<760 else 'desktop'
    page.locator('.dge-topline').screenshot(path=f'/tmp/dmate-toolbar-drawing-{size}.png')


def toolbar_spacing(page,selector):
    return page.locator(selector).evaluate('''bar=>{
      const style=getComputedStyle(bar),box=bar.getBoundingClientRect(),controls=[...bar.children]
        .filter(node=>getComputedStyle(node).position!=='absolute')
        .map(node=>node.getBoundingClientRect()).filter(box=>box.width>1&&box.height>1);
      return {radii:[style.borderTopLeftRadius,style.borderTopRightRadius,style.borderBottomLeftRadius,style.borderBottomRightRadius].map(parseFloat),
        above:Math.min(...controls.map(control=>control.top))-box.top,
        below:box.bottom-Math.max(...controls.map(control=>control.bottom)),count:controls.length};}''')


def test_scan_toolbar_rounding_and_whitespace_keep_source_gestures_and_save_usable(scan_page):
    page=scan_page
    install_production_appearance(page)
    open_scan(page)
    page.wait_for_function('document.querySelector(".dgs-source .dge-overlay").dataset.geometryReady==="true"')
    assert_appearance_panel_is_active(page)
    for selector in ['.dgs-modes','.dgs-source .dge-view-controls','.dge-scan-only .dge-overlay-tools']:
        spacing=toolbar_spacing(page,selector)
        assert spacing['count']>=2
        assert min(spacing['radii'])>=10
        assert spacing['above']>=7 and spacing['below']>=7
    gaps=page.locator('.dgs-modes').evaluate('''row=>{
      const box=row.getBoundingClientRect(),content=row.closest('.dgs-content'),mount=document.getElementById('graphEditorMount');
      return [box.top-content.getBoundingClientRect().top-content.clientTop,
        box.top-mount.getBoundingClientRect().top-mount.clientTop];}''')
    assert min(gaps)>=8
    image=page.locator('.dgs-source .dge-overlay-image')
    assert image.evaluate('e=>[e.naturalWidth,e.naturalHeight]')==[600,400]
    before=image.bounding_box()
    size='mobile' if page.viewport_size['width']<760 else 'desktop'
    page.locator('#graphEditorDialog').screenshot(path=f'/tmp/dmate-toolbar-scan-{size}.png')
    page.get_by_role('tab',name='自主框选',exact=True).click()
    assert page.get_by_role('tab',name='自主框选',exact=True).get_attribute('aria-selected')=='true'
    page.get_by_role('tab',name='原生识别',exact=True).click()
    assert page.get_by_role('tab',name='原生识别',exact=True).get_attribute('aria-selected')=='true'
    page.get_by_role('button',name='图形框选',exact=True).click()
    assert page.get_by_role('button',name='图形框选',exact=True).get_attribute('aria-pressed')=='true'
    drag(page,[(.16,.22),(.43,.62)])
    page.wait_for_function('graphCalls.length===1&&ocrTasks.get("scan").scanState.graphRegions[0].status==="complete"')
    polygon=page.evaluate('ocrTasks.get("scan").scanState.graphRegions[0].polygon')
    expected=[(.16,.22),(.43,.22),(.43,.62),(.16,.62)]
    for point,target in zip(polygon,expected):assert point==pytest.approx(target,abs=.012)
    # A new recognized region is deliberately unselected until its checkbox
    # is chosen; selecting the real source makes this a saveable document.
    page.get_by_role('checkbox',name='图形框1',exact=True).check()
    page.keyboard.press('Escape')
    assert image.bounding_box()==pytest.approx(before,abs=1.5)
    page.get_by_role('button',name='选择 / 平移',exact=True).click()
    page.get_by_role('button',name='放大原图',exact=True).click()
    page.get_by_role('button',name='放大原图',exact=True).click()
    assert image.bounding_box()['width']>before['width']*1.4
    page.get_by_role('button',name='适应',exact=True).click()
    assert image.bounding_box()==pytest.approx(before,abs=1.5)
    assert image.evaluate('e=>[e.naturalWidth,e.naturalHeight]')==[600,400]
    assert page.evaluate('ocrTasks.get("scan").scanState.graphRegions[0].polygon')==polygon
    save=page.get_by_role('button',name='保存',exact=True)
    footer=save.bounding_box()
    # Stress the actual inner scroll container, while keeping the recognized
    # source pixels and normalized ROI unchanged underneath the dialog chrome.
    page.locator('.dgs-content').evaluate('''e=>{const note=document.createElement('p');
      note.textContent='保留的补充要求。'.repeat(1500);e.append(note);e.scrollTop=e.scrollHeight;}''')
    assert page.locator('.dgs-content').evaluate('e=>e.scrollTop')>0
    assert save.bounding_box()==pytest.approx(footer,abs=1)
    assert page.locator('#graphEditorDialog').evaluate('e=>e.scrollTop')==0
    assert image.bounding_box()['width']==pytest.approx(before['width'],abs=1)
    assert image.bounding_box()['height']==pytest.approx(before['height'],abs=1)
    assert page.evaluate('ocrTasks.get("scan").scanState.graphRegions[0].polygon')==polygon
    assert not save.is_disabled()
    save.click()
    page.wait_for_function('posts.length===1')
    assert page.evaluate('posts[0].document.graphs[0].edges.length')==3
