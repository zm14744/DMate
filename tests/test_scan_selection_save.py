"""Selection is quiet and Save stays separate from sending to the solver."""
import pytest

from test_scan_drawing_separation import scan_page, open_scan, drag


def image_point(page, x, y):
    box = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    return box['x'] + box['width'] * x, box['y'] + box['height'] * y


def test_scan_opens_in_selection_without_debug_instruction_or_placeholder(scan_page):
    page = scan_page
    page.evaluate('''()=>{ocrTasks.get('scan').result={review:{reasons:[
      '原图无题干文字，body_text为空；边均按视觉连线判读。交叉点未作为顶点处理。']}};}''')
    open_scan(page)
    assert page.locator('.dge-overlay-svg').get_attribute('data-mode') == 'select'
    assert page.get_by_role('button', name='选择 / 平移', exact=True).get_attribute('aria-pressed') == 'true'
    assert not page.locator('.dgs-status').inner_text()
    assert page.get_by_label('要求（可选）', exact=True).get_attribute('placeholder') is None
    # Unknown directions remain explicit rather than hidden with debug notes.
    assert '方向待核对' in page.locator('.dgs-information').inner_text()
    assert page.get_by_role('button', name='保存并确认', exact=True).count() == 0


def test_first_frame_click_with_pointer_tremor_does_not_move_source(scan_page):
    page = scan_page
    open_scan(page)
    page.get_by_role('button', name='图形框选', exact=True).click()
    drag(page, [(.25, .25), (.7, .75)])
    page.wait_for_function('graphCalls.length===1')
    page.get_by_role('button', name='选择 / 平移', exact=True).click()
    page.mouse.click(*image_point(page, .9, .9))
    assert page.evaluate('ocrTasks.get("scan").scanState.selectedGraphId') is None
    before = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    x, y = image_point(page, .5, .5)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 1, y + 1)
    page.mouse.up()
    assert page.evaluate('ocrTasks.get("scan").scanState.selectedGraphId') == 'g1'
    after = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    assert after == pytest.approx(before, abs=.5)
    assert page.evaluate('graphCalls.length') == 1


def test_first_pan_from_fitted_fractional_bounds_moves_only_drag_distance(scan_page):
    page = scan_page
    open_scan(page)
    before = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    x, y = image_point(page, .5, .5)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 12, y + 12, steps=3)
    page.mouse.up()
    after = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    assert after['x'] - before['x'] == pytest.approx(12, abs=1.5)
    assert after['y'] - before['y'] == pytest.approx(12, abs=1.5)
    assert after['width'] == pytest.approx(before['width'], abs=.5)
    assert after['height'] == pytest.approx(before['height'], abs=.5)
    assert page.evaluate('graphCalls.length') == 0


def test_save_is_at_dialog_bottom_right_and_exits(scan_page):
    page = scan_page
    open_scan(page)
    save = page.get_by_role('button', name='保存', exact=True)
    box, dialog = save.bounding_box(), page.locator('#graphEditorDialog').bounding_box()
    assert box['x'] + box['width'] >= dialog['x'] + dialog['width'] - 25
    assert box['y'] + box['height'] >= dialog['y'] + dialog['height'] - 25
    assert box['y'] + box['height'] <= dialog['y'] + dialog['height']
    save.click()
    page.wait_for_function('!document.getElementById("graphEditorDialog").open')
    assert page.evaluate('posts.length') == 1


def test_reopening_a_task_resets_last_framing_mode_to_selection(scan_page):
    page = scan_page
    open_scan(page)
    page.get_by_role('button', name='文字框选', exact=True).click()
    page.get_by_label('关闭图形识别编辑器', exact=True).click()
    open_scan(page)
    assert page.locator('.dge-overlay-svg').get_attribute('data-mode') == 'select'


def test_selection_controls_are_ready_before_hidden_modal_has_layout(scan_page):
    result = scan_page.evaluate('''() => {
        const host=document.createElement('div');host.hidden=true;document.body.append(host);
        const overlay=DMateGraphOverlay.mount(host,{scanOnly:true,originalUrl:'',
            state:{mode:'select',zoom:100,visible:true},graph:()=>null,
            model:{getDocument:()=>({graphs:[]})}});
        const result={width:host.clientWidth,mode:host.querySelector('svg').dataset.mode,
            pressed:host.querySelector('[data-overlay-tool="select"]').getAttribute('aria-pressed')};
        overlay.destroy();host.remove();return result;
    }''')
    assert result == {'width': 0, 'mode': 'select', 'pressed': 'true'}


@pytest.mark.parametrize('response_kind,expected_status', [
    ('empty_review', 'empty'), ('empty_graph_object', 'empty'),
    ('not_graph_with_stale_payload', 'empty'), ('failed_with_stale_payload', 'error'),
])
def test_unsuccessful_graph_after_success_is_typed_once_and_never_reuses_prior_graph(scan_page, response_kind, expected_status):
    page = scan_page
    open_scan(page)
    original = page.evaluate('structuredClone(ocrTasks.get("scan").scanState.nativeDocument)')
    page.get_by_role('button', name='图形框选', exact=True).click()
    drag(page, [(.1, .1), (.35, .4)])
    page.wait_for_function('ocrTasks.get("scan").scanState.graphRegions[0]?.status==="complete"')
    page.get_by_role('checkbox', name='图形框1', exact=True).check()
    assert page.locator('.dgs-graph').count() == 1
    page.keyboard.press('Escape')
    page.evaluate('''kind => {
      const originalFetch=window.fetch;
      window.fetch=async(url,options)=>{
        if(url!=='/graph/recognize-region')return originalFetch(url,options);
        graphCalls.push(JSON.parse(options.body.get('polygon')));
        const stale=structuredClone(sample.graphs);
        let data={recognition_status:'partial',document:{body_text:'不得并入文字卡片',graphs:[]},
          warning:'选区内未识别到数学图形，请调整范围重试。',
          review:{required:true,reasons:['选区内未识别到数学图形，请调整范围重试。']}};
        if(kind==='empty_graph_object')data.document.graphs=[{id:'empty',name:'旧图形',vertices:[],edges:[]}];
        if(kind==='not_graph_with_stale_payload'){data.recognition_status='not_graph';data.document.graphs=stale;}
        if(kind==='failed_with_stale_payload'){data.recognition_status='failed';data.document.graphs=stale;data.error='模型服务故障';}
        return {ok:true,json:async()=>({...data,request_id:'scan',source_sha256:'a'.repeat(64),operation_id:options.body.get('operation_id')})};
      };
    }''', response_kind)
    drag(page, [(.55, .1), (.85, .4)])
    page.wait_for_function('status=>ocrTasks.get("scan").scanState.graphRegions[1]?.status===status', arg=expected_status)
    page.get_by_role('checkbox', name='图形框2', exact=True).check()
    page.get_by_role('checkbox', name='图形框1', exact=True).uncheck()
    assert page.evaluate('ocrTasks.get("scan").scanState.graphRegions[1].graphs') == []
    assert page.evaluate('ocrTasks.get("scan").draft') == {'body_text': '', 'graphs': []}
    graph_card = page.locator('.dgs-graphs')
    assert graph_card.locator('.dgs-graph').count() == 0
    assert graph_card.locator('.dgs-region-state').count() == 1
    notice = graph_card.locator('.dgs-region-state').inner_text()
    assert notice == ('图形框 2：未识别到图形。' if expected_status == 'empty' else '图形框 2：识别失败：模型服务故障')
    assert all(text not in graph_card.inner_text() for text in ('暂无', '待核对', '选区内未识别到数学图形', '旧图形'))
    assert '图形框' not in page.locator('.dgs-text').inner_text()
    assert '不得并入文字卡片' not in page.locator('.dgs-information').inner_text()
    assert graph_card.locator('.dgs-region-state').evaluate('e=>getComputedStyle(e).borderTopWidth') == '0px'
    assert page.get_by_role('button', name='保存', exact=True).is_disabled()
    # Excluding the failed source allows the independent successful frame.
    page.get_by_role('checkbox', name='图形框2', exact=True).uncheck()
    page.get_by_role('checkbox', name='图形框1', exact=True).check()
    assert page.get_by_role('button', name='保存', exact=True).is_enabled()
    assert page.evaluate('ocrTasks.get("scan").draft.graphs.map(g=>g.id)') == ['g1_1']
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft') == original


def test_restored_failed_rows_drop_stale_text_and_graphs_and_show_separate_single_notices(scan_page):
    page = scan_page
    page.evaluate('''()=>{
      const graph=structuredClone(sample.graphs[0]);graph.id='stale';
      ocrTasks.get('scan').scanState={sourcesVersion:3,mode:'manual',
        textRegions:[{id:1,selected:true,status:'complete',text:'有效文字',polygon:[[.1,.1],[.3,.1],[.3,.3],[.1,.3]]},
          {id:5,selected:true,status:'empty',text:'不得复用的旧文字',polygon:[[.4,.1],[.6,.1],[.6,.3],[.4,.3]]}],
        graphRegions:[{id:'g2',selected:true,status:'error',error:'模型服务故障',graphs:[graph],polygon:[[.1,.4],[.6,.4],[.6,.8],[.1,.8]]}]};
    }''')
    open_scan(page)
    assert page.locator('.dgs-body').inner_text() == '有效文字'
    assert page.locator('.dgs-text .dgs-region-state').all_text_contents() == ['文字框 5：未识别到文字。']
    assert page.locator('.dgs-graphs .dgs-region-state').all_text_contents() == ['图形框 2：识别失败：模型服务故障']
    assert page.locator('.dgs-graph').count() == 0
    assert '暂无' not in page.locator('.dgs-information').inner_text()
    assert '不得复用' not in page.locator('.dgs-information').inner_text()
    assert page.evaluate('ocrTasks.get("scan").scanState.textRegions[1].text') == ''
    assert page.evaluate('ocrTasks.get("scan").scanState.graphRegions[0].graphs') == []
    assert page.get_by_role('button', name='保存', exact=True).is_disabled()


@pytest.mark.parametrize('missing', [False, True])
def test_partial_text_batch_keeps_success_and_clears_only_the_failed_or_empty_frame(scan_page, missing):
    page = scan_page
    page.evaluate('''missing=>{
      const originalFetch=window.fetch;
      window.fetch=async(url,options)=>{
        if(url!=='/graph/text-region')return originalFetch(url,options);
        textCalls.push(JSON.parse(options.body.get('regions')));
        const regions=[{id:1,text:'最新有效文字',recognition_status:'complete'}];
        if(!missing)regions.push({id:5,text:'',recognition_status:'empty'});
        return {ok:true,json:async()=>({request_id:'scan',source_sha256:'a'.repeat(64),recognition_status:'partial',regions})};
      };
      ocrTasks.get('scan').scanState={sourcesVersion:3,mode:'manual',graphRegions:[],
        textRegions:[1,5].map(id=>({id,selected:true,status:'queued',version:1,text:'不得复用的旧文字',
          polygon:[[.1,.1],[.4,.1],[.4,.4],[.1,.4]]}))};
    }''', missing)
    open_scan(page)
    page.wait_for_function('ocrTasks.get("scan").scanState.textRegions.every(r=>r.status!=="running"&&r.status!=="queued")')
    assert page.locator('.dgs-body').inner_text() == '最新有效文字'
    assert page.evaluate('ocrTasks.get("scan").scanState.textRegions.map(r=>r.status)') == ['complete', 'error' if missing else 'empty']
    assert page.evaluate('ocrTasks.get("scan").scanState.textRegions[1].text') == ''
    assert page.locator('.dgs-text .dgs-region-state').count() == 1
    assert page.locator('.dgs-text .dgs-region-state').inner_text() == (
        '文字框 5：识别失败：文字识别响应缺少选区。' if missing else '文字框 5：未识别到文字。')
    assert page.get_by_role('button', name='保存', exact=True).is_disabled()
