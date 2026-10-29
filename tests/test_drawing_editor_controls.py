"""Real pointer controls in the standalone drawing editor, desktop and phone."""
import base64
import io
import os
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440,900),(390,844)])
def drawing_page(request):
    chromium=os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not chromium:pytest.skip('Chromium unavailable')
    pw=pytest.importorskip('playwright.sync_api')
    styles='\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>',(ROOT/'templates/index.html').read_text()))
    with Image.new('RGB',(1000,700),'white') as image:
        out=io.BytesIO();image.save(out,format='PNG')
    src='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
    with pw.sync_playwright() as engine:
        browser=engine.chromium.launch(executable_path=chromium,headless=True)
        p=browser.new_page(viewport={'width':request.param[0],'height':request.param[1]})
        p.set_content('<main id="editor"></main>')
        p.add_style_tag(content=styles)
        p.add_style_tag(content=(ROOT/'static/graph-editor.css').read_text())
        for name in ['graph-editor-model.js','graph-editor-format.js','graph-editor-overlay.js','graph-editor.js']:
            p.add_script_tag(content=(ROOT/'static'/name).read_text())
        p.evaluate('''src=>{window.changes=0;window.editor=DMateGraphEditor.mount(document.querySelector('#editor'),{
          drawingOnly:true,originalUrl:src,onChange:()=>changes++,document:{body_text:'',graphs:[{
            id:'G1',name:'我的图形',directed:true,weighted:true,
            vertices:[{id:'a',label:'A',x:.3,y:.4},{id:'b',label:'B',x:.7,y:.6}],
            edges:[{id:'ab',from:'a',to:'b',direction:'forward',weight:5}]}]}});}''',src)
        p.wait_for_function('document.querySelector(".dge-overlay-image").naturalWidth===1000')
        yield p
        browser.close()


def test_one_click_deletes_a_vertex_and_its_incident_edges_and_undo_restores(drawing_page):
    p=drawing_page
    p.locator('[data-vertex-id="a"] .dge-overlay-node-hit').click()
    p.get_by_role('button',name='删除这个顶点',exact=True).click()
    assert p.evaluate('editor.getDocument().graphs[0].vertices.map(v=>v.id)')==['b']
    assert p.evaluate('editor.getDocument().graphs[0].edges.length')==0
    assert p.locator('.dge-selection-panel').count()==0
    p.get_by_role('button',name='撤销',exact=True).click()
    assert p.evaluate('editor.getDocument().graphs[0].vertices.length')==2
    assert p.evaluate('editor.getDocument().graphs[0].edges.length')==1


def test_one_click_deletes_one_edge_without_altering_its_vertices(drawing_page):
    p=drawing_page
    p.locator('[data-edge-id="ab"] .dge-overlay-hit').click()
    p.get_by_role('button',name='删除这条边',exact=True).click()
    assert p.evaluate('editor.getDocument().graphs[0].edges.length')==0
    assert p.evaluate('editor.getDocument().graphs[0].vertices.length')==2
    p.get_by_role('button',name='撤销',exact=True).click()
    assert p.evaluate('editor.getDocument().graphs[0].edges.length')==1


def test_modes_are_exclusive_and_tools_fold_without_activating_other_buttons(drawing_page):
    p=drawing_page
    for name,key in [('添加顶点','vertex'),('添加边','edge'),('选择 / 移动','select')]:
        p.get_by_role('button',name=name,exact=True).click()
        assert p.locator('.dge-overlay-tools [aria-pressed=true]').count()==1
        assert p.locator('.dge-overlay-tools .is-active').get_attribute('data-overlay-tool')==key
        assert p.locator('.dge-overlay-svg').get_attribute('data-mode')==key
    p.locator('.dge-tool-palette > summary').click()
    assert not p.get_by_role('button',name='添加顶点',exact=True).is_visible()
    assert p.get_by_role('button',name='适应',exact=True).is_visible()
    p.locator('.dge-tool-palette > summary').click()
    assert p.get_by_role('button',name='添加顶点',exact=True).is_visible()
    assert p.evaluate('changes')==0
    assert p.get_by_role('button',name='框选图形',exact=True).count()==0
    assert p.get_by_label('选区方式').count()==0
    assert p.get_by_role('button',name='隐藏描绘',exact=True).count()==0
    assert p.get_by_role('button',name='显示描绘',exact=True).count()==0
    assert p.locator('.dge-advanced-panel,.dge-float-advanced').count()==0
    assert p.get_by_text('批量编辑',exact=True).count()==0
    assert p.get_by_text('子图管理',exact=True).count()==0


def test_settings_and_graph_information_are_separate_full_panels(drawing_page):
    p=drawing_page
    p.locator('.dge-float-graphs > summary').click()
    assert p.get_by_label('画页名称',exact=True).count()==0
    assert p.get_by_label('绘图方向',exact=True).is_visible()
    assert p.get_by_label('绘图权值',exact=True).is_visible()
    assert p.get_by_label('绘图方向',exact=True).locator('option').all_text_contents()==['无向','有向']
    assert p.get_by_label('绘图权值',exact=True).locator('option').all_text_contents()==['无权','带权']
    assert p.get_by_label('当前子图',exact=True).count()==0
    # One click switches the active popup. Inner information has no nested
    # collapsing disclosure: all vertices and relationships are already there.
    p.locator('.dge-float-results > summary').click()
    assert p.locator('.dge-floating-actions > details[open]').count()==1
    assert p.locator('.dge-review-summary').is_visible()
    assert p.locator('.dge-review-summary').evaluate('e=>e.tagName')=='SECTION'
    assert p.locator('.dge-review-summary summary').count()==0
    assert 'A' in p.locator('.dge-review-content').inner_text()
    assert 'B' in p.locator('.dge-review-content').inner_text()
    assert '5' in p.locator('.dge-review-content').inner_text()


def test_export_svg_contains_actual_drawing_with_standalone_styles_and_no_editor_hits(drawing_page):
    p=drawing_page
    p.locator('[data-edge-id="ab"] .dge-overlay-hit').click()
    result=p.evaluate('''()=>{const svg=editor.getDrawingSvg();const b=svg.viewBox.baseVal;return {
      text:svg.textContent,xml:new XMLSerializer().serializeToString(svg),width:Number(svg.getAttribute('width')),
      height:Number(svg.getAttribute('height')),hits:svg.querySelectorAll('.dge-overlay-hit,.dge-overlay-node-hit,.dge-overlay-handle').length,
      nodes:svg.querySelectorAll('.dge-overlay-node').length,edges:svg.querySelectorAll('.dge-overlay-edge').length,
      strokes:[...svg.querySelectorAll('.dge-overlay-stroke')].map(e=>e.style.stroke),defs:svg.querySelectorAll('marker').length};}''')
    assert result['nodes']==2 and result['edges']==1
    assert result['hits']==0 and result['defs']==2
    assert result['width']>64 and result['height']>64
    assert all(result['strokes'])
    assert 'A' in result['text'] and 'B' in result['text'] and '5' in result['text']
    assert 'xmlns="http://www.w3.org/2000/svg"' in result['xml']
    assert 'font-size' in result['xml'] and 'paint-order' in result['xml']


def test_drawing_type_changes_refresh_contextual_controls(drawing_page):
    p=drawing_page
    p.locator('.dge-float-graphs > summary').click()
    p.get_by_label('绘图方向',exact=True).select_option('no')
    p.get_by_label('绘图权值',exact=True).select_option('no')
    p.locator('.dge-float-graphs > summary').click()
    p.locator('[data-edge-id="ab"] .dge-overlay-hit').click()
    assert p.get_by_label('当前边端点一',exact=True).is_visible()
    assert p.get_by_label('当前边端点二',exact=True).is_visible()
    assert p.get_by_label('当前边方向',exact=True).count()==0
    assert p.get_by_label('当前边权值',exact=True).count()==0
    assert p.get_by_role('button',name='反转方向',exact=True).count()==0


def test_settings_open_and_change_in_one_task_preserves_popover(drawing_page):
    p=drawing_page
    # Do not yield to the event loop between summary activation and change.
    # Native details.toggle may otherwise conceal this redraw race locally.
    result=p.evaluate('''()=>{
      const panel=document.querySelector('.dge-float-graphs');
      panel.querySelector('summary').click();
      const direction=panel.querySelector('[aria-label="绘图方向"]');
      direction.value='no';direction.dispatchEvent(new Event('change',{bubbles:true}));
      const next=document.querySelector('.dge-float-graphs');
      return {open:next.open,replaced:next!==panel,weight:next.querySelector('[aria-label="绘图权值"]').getBoundingClientRect().height};
    }''')
    assert result['replaced'] and result['open'] and result['weight']>0
    assert p.get_by_label('绘图权值',exact=True).is_visible()


def test_detached_toggle_cannot_override_current_popover_and_live_state_is_retained(drawing_page):
    p=drawing_page
    result=p.evaluate('''()=>{
      const old=document.querySelector('.dge-float-graphs');old.querySelector('summary').click();
      const change=(label,value)=>{const control=document.querySelector('[aria-label="'+label+'"]');control.value=value;control.dispatchEvent(new Event('change',{bubbles:true}));};
      change('绘图方向','no');
      // This event may already be queued by Chromium when the old tree is
      // detached. Deliver it explicitly before another redraw.
      old.open=false;old.dispatchEvent(new Event('toggle'));
      change('绘图权值','no');
      const afterStale=document.querySelector('.dge-float-graphs').open;
      // Programmatic/native details changes also survive a same-task redraw,
      // even before their queued toggle callback has had time to run.
      document.querySelector('.dge-float-graphs').open=false;
      change('绘图方向','yes');
      const afterClose=document.querySelector('.dge-float-graphs').open;
      document.querySelector('.dge-float-graphs').open=true;
      change('绘图权值','yes');
      return {afterStale,afterClose,afterOpen:document.querySelector('.dge-float-graphs').open};
    }''')
    assert result=={'afterStale':True,'afterClose':False,'afterOpen':True}
    assert p.get_by_label('绘图权值',exact=True).is_visible()


def test_graph_information_tracks_model_changes_without_rebuilding_popup_or_camera(drawing_page):
    p=drawing_page
    p.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    # Enough real relationships make the information panel scroll on both
    # phone and desktop, so replacing its scroll container would be visible.
    p.evaluate('''()=>{for(let i=0;i<18;i++)editor.model.addEdge('G1',{
      from:'a',to:'b',direction:'forward',weight:i+20});}''')
    for _ in range(3):p.get_by_role('button',name='放大原图',exact=True).click()
    p.locator('.dge-float-results > summary').click()
    p.evaluate('''()=>{
      const viewport=document.querySelector('.dge-overlay-viewport');
      viewport.scrollLeft=55;viewport.scrollTop=80;
      window.infoPopup=document.querySelector('.dge-float-results');
      window.infoScroll=infoPopup.querySelector('.dge-float-content');
      window.infoSection=infoPopup.querySelector('.dge-review-summary');
      window.canvasViewport=viewport;window.canvasImage=document.querySelector('.dge-overlay-image');
      infoScroll.scrollTop=110;
      const box=canvasImage.getBoundingClientRect();
      window.liveCamera=[viewport.scrollLeft,viewport.scrollTop,box.x,box.y,box.width,box.height];
      window.liveInfoScroll=infoScroll.scrollTop;
    }''')
    assert p.evaluate('liveInfoScroll')>0

    def check(points,edges,*expected):
        heading=p.locator('.dge-review-content .dgs-counts').text_content()
        assert f'{points} 个顶点 · {edges} 条边' in heading
        text=p.locator('.dge-review-content').text_content()
        for value in expected:assert value in text
        state=p.evaluate('''()=>{
          const box=canvasImage.getBoundingClientRect();return {
            same:document.querySelector('.dge-float-results')===infoPopup&&
              document.querySelector('.dge-float-results .dge-float-content')===infoScroll&&
              document.querySelector('.dge-review-summary')===infoSection&&
              document.querySelector('.dge-overlay-viewport')===canvasViewport&&
              document.querySelector('.dge-overlay-image')===canvasImage,
            open:infoPopup.open,scroll:infoScroll.scrollTop,
            camera:[canvasViewport.scrollLeft,canvasViewport.scrollTop,box.x,box.y,box.width,box.height]};}''')
        assert state['same'] and state['open']
        assert state['scroll']==pytest.approx(p.evaluate('liveInfoScroll'),abs=1)
        assert state['camera']==pytest.approx(p.evaluate('liveCamera'),abs=1)

    check(2,19,'A→B','权值：5')
    p.evaluate("window.liveVertex=editor.model.addVertex('G1','C',.5,.8)")
    check(3,19,'顶点：A、B、C')
    p.evaluate("window.liveEdge=editor.model.addEdge('G1',{from:'b',to:liveVertex,direction:'forward',weight:9})")
    check(3,20,'B→C（权值：9）')
    p.evaluate("editor.model.renameVertex('G1',liveVertex,'顶点丙')")
    check(3,20,'B→顶点丙（权值：9）')
    p.evaluate("editor.model.updateEdges('G1',[liveEdge],'weight',11)")
    check(3,20,'B→顶点丙（权值：11）')
    p.evaluate("editor.model.updateEdges('G1',[liveEdge],'edge_label','新线路')")
    check(3,20,'新线路：B→顶点丙（权值：11）')
    p.evaluate("editor.model.setGraphType('G1','directed',false)")
    check(3,20,'无向 · 带权','新线路：B—顶点丙')
    p.evaluate("editor.model.setGraphType('G1','weighted',false)")
    check(3,20,'无向 · 无权','新线路：B—顶点丙')
    assert '权值：' not in p.locator('.dge-review-content').text_content()
    p.evaluate("editor.model.deleteEdges('G1',[liveEdge])")
    check(3,19,'顶点：A、B、顶点丙')
    assert '新线路' not in p.locator('.dge-review-content').text_content()
    p.evaluate('editor.model.undo()')
    check(3,20,'新线路：B—顶点丙')
    p.evaluate('editor.model.redo()')
    check(3,19,'顶点：A、B、顶点丙')
    p.evaluate("editor.model.deleteVertices('G1',[liveVertex])")
    check(2,19,'顶点：A、B')
    assert '顶点丙' not in p.locator('.dge-review-content').text_content()
    p.evaluate('editor.model.undo()')
    check(3,19,'顶点：A、B、顶点丙')
    p.evaluate("editor.model.renameGraph('G1','实时绘图')")
    check(3,19,'图 1（实时绘图）')
    # Geometry does not change the structure text; it should not even replace
    # its children during a node drag or another geometry-only publication.
    p.evaluate("window.liveReviewChild=infoSection.querySelector('.dge-review-content').firstElementChild;editor.model.moveVertex('G1','a',.31,.41)")
    check(3,19,'顶点：A、B、顶点丙')
    assert p.evaluate("infoSection.querySelector('.dge-review-content').firstElementChild===liveReviewChild")


def test_first_blank_vertices_and_edge_update_information_through_pointer_controls(drawing_page):
    p=drawing_page
    p.evaluate('''()=>{const originalUrl=document.querySelector('.dge-overlay-image').src;editor.destroy();
      editor=DMateGraphEditor.mount(document.querySelector('#editor'),{drawingOnly:true,originalUrl,
        document:{body_text:'',graphs:[{id:'G1',name:'空白页',directed:false,weighted:false,vertices:[],edges:[]}]}});}''')
    p.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    assert '0 个顶点 · 0 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    p.get_by_role('button',name='添加顶点',exact=True).click()
    p.locator('.dge-tool-palette > summary').click()

    def click_source(x,y):
        point=p.locator('.dge-overlay-svg').evaluate('''(svg,point)=>{
          const p=svg.createSVGPoint();p.x=point[0]*1000;p.y=point[1]*700;
          const screen=p.matrixTransform(svg.getScreenCTM());return [screen.x,screen.y];}''',[x,y])
        p.mouse.click(*point)

    click_source(.3,.65)
    assert '1 个顶点 · 0 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    assert '顶点：1' in p.locator('.dge-review-content').text_content()
    click_source(.7,.75)
    assert '2 个顶点 · 0 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    assert '顶点：1、2' in p.locator('.dge-review-content').text_content()
    p.locator('.dge-tool-palette > summary').click()
    p.get_by_role('button',name='添加边',exact=True).click()
    p.locator('.dge-tool-palette > summary').click()
    click_source(.3,.65)
    click_source(.7,.75)
    assert '2 个顶点 · 1 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    assert '1—2' in p.locator('.dge-review-content').text_content()
    p.locator('.dge-tool-palette > summary').click()
    p.get_by_role('button',name='选择 / 移动',exact=True).click()
    p.locator('.dge-tool-palette > summary').click()
    click_source(.5,.7)
    p.get_by_role('button',name='删除这条边',exact=True).click()
    assert '2 个顶点 · 0 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    p.get_by_role('button',name='撤销',exact=True).click()
    assert '2 个顶点 · 1 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    assert '1—2' in p.locator('.dge-review-content').text_content()
    p.get_by_role('button',name='重做',exact=True).click()
    assert '2 个顶点 · 0 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    click_source(.3,.65)
    p.get_by_role('button',name='删除这个顶点',exact=True).click()
    assert '1 个顶点 · 0 条边' in p.locator('.dge-review-content .dgs-counts').text_content()
    assert '顶点：2' in p.locator('.dge-review-content').text_content()
    p.get_by_role('button',name='撤销',exact=True).click()
    assert '2 个顶点 · 0 条边' in p.locator('.dge-review-content .dgs-counts').text_content()


def test_property_typing_updates_closed_information_without_losing_focus_or_caret(drawing_page):
    p=drawing_page
    p.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    p.locator('[data-vertex-id="a"] .dge-overlay-node-hit').click()
    name=p.get_by_label('当前顶点名称',exact=True)
    name.fill('Alpha')
    p.evaluate('''()=>{window.liveNameInput=document.querySelector('[aria-label="当前顶点名称"]');
      liveNameInput.focus();liveNameInput.setSelectionRange(2,2);
      window.closedInfo=document.querySelector('.dge-float-results');
      window.closedReview=document.querySelector('.dge-review-summary');}''')
    name.press_sequentially('Z')
    result=p.evaluate('''()=>({same:document.querySelector('[aria-label="当前顶点名称"]')===liveNameInput,
      focused:document.activeElement===liveNameInput,value:liveNameInput.value,
      start:liveNameInput.selectionStart,end:liveNameInput.selectionEnd,
      popupSame:document.querySelector('.dge-float-results')===closedInfo,
      reviewSame:document.querySelector('.dge-review-summary')===closedReview,open:closedInfo.open})''')
    assert result=={'same':True,'focused':True,'value':'AlZpha','start':3,'end':3,
                    'popupSame':True,'reviewSame':True,'open':False}
    assert '顶点：AlZpha、B' in p.locator('.dge-review-content').text_content()
    assert 'AlZpha→B（权值：5）' in p.locator('.dge-review-content').text_content()
    p.locator('.dge-float-results > summary').click()
    assert 'AlZpha→B（权值：5）' in p.locator('.dge-review-content').text_content()


def test_property_and_settings_edits_update_graph_information_immediately(drawing_page):
    p=drawing_page
    p.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    p.locator('[data-edge-id="ab"] .dge-overlay-hit').click()
    p.get_by_label('当前边权值',exact=True).fill('17')
    assert 'A→B（权值：17）' in p.locator('.dge-review-content').text_content()
    p.get_by_label('当前边名称',exact=True).fill('路线甲')
    assert '路线甲：A→B（权值：17）' in p.locator('.dge-review-content').text_content()
    p.get_by_role('button',name='关闭属性',exact=True).click()
    p.locator('.dge-float-graphs > summary').click()
    p.get_by_label('绘图方向',exact=True).select_option('no')
    assert '无向 · 带权' in p.locator('.dge-review-content').text_content()
    assert '路线甲：A—B（权值：17）' in p.locator('.dge-review-content').text_content()
    p.get_by_label('绘图权值',exact=True).select_option('no')
    assert '无向 · 无权' in p.locator('.dge-review-content').text_content()
    assert '权值：' not in p.locator('.dge-review-content').text_content()
    p.locator('.dge-float-results > summary').click()
    assert p.locator('.dge-review-summary').is_visible()
    assert '路线甲：A—B' in p.locator('.dge-review-content').text_content()


def test_drawing_has_no_save_footer_and_model_edits_still_publish(drawing_page):
    page = drawing_page
    assert page.locator('.dge-footer').count() == 0
    assert page.get_by_role('button', name='保存绘图', exact=True).count() == 0
    assert page.get_by_role('button', name='保存并确认', exact=True).count() == 0
    before = page.evaluate('changes')
    page.evaluate("editor.model.renameVertex('G1','a','实时保存顶点')")
    assert page.evaluate('changes') > before
    assert page.evaluate('editor.getDocument().graphs[0].vertices[0].label') == '实时保存顶点'
    assert '顶点：实时保存顶点、B' in page.locator('.dge-review-content').text_content()
