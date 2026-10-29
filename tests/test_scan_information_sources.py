"""Native scans remain recoverable while region sources are selected/ordered."""
import pytest

from test_scan_drawing_separation import scan_page, open_scan, drag


def native_snapshot(page):
    return page.evaluate('structuredClone(ocrTasks.get("scan").scanState.nativeDocument)')


def open_picker(page, kind):
    button = page.get_by_role('button', name='选择图形信息' if kind == 'graph' else '选择文字信息', exact=True)
    if button.get_attribute('aria-expanded') != 'true':
        button.click()


def apply_frames(page, kind, ids):
    open_picker(page, kind)
    label = '图形' if kind == 'graph' else '文字'
    for number in ids:
        page.get_by_role('checkbox', name=f'放入{label}框 {number}', exact=True).check()
    page.get_by_role('button', name=f'放入所选{label}信息', exact=True).click()


def test_native_scan_is_not_replaced_by_late_or_deleted_region(scan_page):
    page = scan_page
    open_scan(page)
    original = native_snapshot(page)
    assert page.get_by_role('tab', name='原生识别', exact=True).get_attribute('aria-selected') == 'true'
    assert page.locator('.dgs-section-head button').count() == 0
    page.evaluate('window.deferGraph=true')
    page.get_by_role('button', name='图形框选', exact=True).click()
    drag(page, [(.2, .2), (.6, .6)])
    page.wait_for_function('graphCalls.length===1')
    assert page.get_by_role('tab', name='自主框选', exact=True).get_attribute('aria-selected') == 'true'
    assert page.get_by_role('button', name='保存', exact=True).is_disabled()
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.get_by_role('button', name='保存', exact=True).is_enabled()
    assert page.evaluate('ocrTasks.get("scan").draft') == original
    page.evaluate('resolveGraph()')
    page.wait_for_function('ocrTasks.get("scan").scanState.graphRegions[0].status==="complete"')
    assert native_snapshot(page) == original
    assert page.evaluate('ocrTasks.get("scan").draft') == original
    assert page.get_by_role('button', name='删除图形框 1', exact=True).count() == 0
    page.get_by_role('tab', name='自主框选', exact=True).click()
    page.get_by_role('button', name='删除图形框 1', exact=True).click()
    assert page.locator('.dge-overlay-bbox').count() == 0
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft') == original
    assert page.get_by_role('button', name='删除原生', exact=False).count() == 0


def test_graph_sources_multiselect_queue_order_delete_and_restore(scan_page):
    page = scan_page
    open_scan(page)
    original = native_snapshot(page)
    page.evaluate('window.deferGraph=true')
    page.get_by_role('button', name='图形框选', exact=True).click()
    for start, end in [((.1, .15), (.25, .35)), ((.4, .15), (.55, .35)), ((.7, .15), (.85, .35))]:
        drag(page, [start, end])
    page.wait_for_function('ocrTasks.get("scan").scanState.graphRegions.length===3 && graphCalls.length===1')
    open_picker(page, 'graph')
    page.get_by_role('button', name='上移图形框 3', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").scanState.graphRegions.map(r=>r.id)') == ['g1', 'g3', 'g2']
    assert page.locator('[data-frame-label-id="g1"]').text_content() == '图形 1'
    assert page.locator('[data-frame-label-id="g2"]').text_content() == '图形 2'
    assert page.locator('[data-frame-label-id="g3"]').text_content() == '图形 3'
    page.evaluate('resolveGraph()')
    page.wait_for_function('graphCalls.length===2')
    assert page.evaluate('graphCalls[1][0][0]') == pytest.approx(.7, abs=.01)
    page.evaluate('resolveGraph()')
    page.wait_for_function('graphCalls.length===3')
    assert page.evaluate('graphCalls[2][0][0]') == pytest.approx(.4, abs=.01)
    page.evaluate('resolveGraph()')
    page.wait_for_function('ocrTasks.get("scan").scanState.graphRegions.every(r=>r.status==="complete")')
    assert page.evaluate('ocrTasks.get("scan").draft') == {'body_text': '', 'graphs': []}
    apply_frames(page, 'graph', [1, 3])
    assert page.evaluate('ocrTasks.get("scan").draft.graphs.map(g=>g.id)') == ['g1_1', 'g3_1']
    assert native_snapshot(page) == original
    page.get_by_role('button', name='删除图形框 1', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft.graphs.map(g=>g.id)') == ['g3_1']
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft') == original


def test_text_sources_multiselect_order_controls_recognition_and_saved_output(scan_page):
    page = scan_page
    page.evaluate('''() => {
        const originalFetch=window.fetch;
        window.fetch=async(url,options)=>{
            if(url!=='/graph/text-region')return originalFetch(url,options);
            const regions=JSON.parse(options.body.get('regions'));textCalls.push(regions);
            return new Promise(resolve=>window.resolveText=()=>resolve({ok:true,json:async()=>({
                request_id:'scan',source_sha256:'a'.repeat(64),regions:regions.map(r=>({id:r.id,text:'文字区域 '+r.id}))})}));
        };
    }''')
    open_scan(page)
    original = native_snapshot(page)
    page.get_by_role('button', name='文字框选', exact=True).click()
    drag(page, [(.1, .1), (.3, .3)])
    page.wait_for_function('textCalls.length===1')
    drag(page, [(.4, .1), (.6, .3)])
    drag(page, [(.7, .1), (.9, .3)])
    open_picker(page, 'text')
    page.get_by_role('button', name='上移文字框 3', exact=True).click()
    page.evaluate('resolveText()')
    page.wait_for_function('textCalls.length===2')
    assert page.evaluate('textCalls[1].map(r=>r.id)') == [3, 2]
    assert page.evaluate('textCalls[1].map(r=>r.order)') == [0, 1]
    page.evaluate('resolveText()')
    page.wait_for_function('ocrTasks.get("scan").scanState.textRegions.every(r=>r.status==="complete")')
    assert page.evaluate('ocrTasks.get("scan").draft') == {'body_text': '', 'graphs': []}
    apply_frames(page, 'text', [1, 3])
    assert page.locator('.dgs-body').inner_text() == '文字区域 1\n\n文字区域 3'
    assert native_snapshot(page) == original
    page.get_by_role('button', name='保存', exact=True).click()
    page.wait_for_function('posts.length===1')
    assert page.evaluate('posts[0].document.body_text') == '文字区域 1\n\n文字区域 3'
    # Reopen preserves selected/manual state without using the saved manual
    # output as the next immutable original scan.
    page.get_by_role('button', name='继续修改', exact=True).click()
    page.wait_for_function('document.querySelector(".dgs-source .dge-overlay-image").naturalWidth===600')
    assert page.locator('.dgs-body').inner_text() == '文字区域 1\n\n文字区域 3'
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.locator('.dgs-body').inner_text() == original['body_text']


def test_unselected_failed_sources_do_not_block_native_or_other_selected_results(scan_page):
    page = scan_page
    page.evaluate('''() => {
        const graph=structuredClone(sample.graphs[0]);graph.id='g1_1';
        ocrTasks.get('scan').scanState={sourcesVersion:2,mode:'manual',
            manualSources:{graphNative:false,textNative:true},graphSelectionActive:true,
            graphRegions:[{id:'g1',selected:true,status:'complete',polygon:[[.1,.1],[.4,.1],[.4,.4],[.1,.4]],graphs:[graph]},
              {id:'g2',selected:false,status:'error',error:'模型服务故障',polygon:[[.6,.1],[.9,.1],[.9,.4],[.6,.4]],graphs:[]}],textRegions:[]};
    }''')
    open_scan(page)
    assert page.get_by_role('button', name='保存', exact=True).is_enabled()
    open_picker(page, 'graph')
    page.get_by_role('checkbox', name='放入图形框 2', exact=True).check()
    page.get_by_role('button', name='放入所选图形信息', exact=True).click()
    assert page.get_by_role('button', name='保存', exact=True).is_disabled()
    assert '模型服务故障' in page.locator('.dgs-information').inner_text()
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.get_by_role('button', name='保存', exact=True).is_enabled()


def test_manual_sources_are_only_inserted_after_explicit_multiselection(scan_page):
    page = scan_page
    open_scan(page)
    original = native_snapshot(page)
    page.get_by_role('tab', name='自主框选', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft') == {'body_text': '', 'graphs': []}
    assert page.get_by_role('button', name='保存', exact=True).is_disabled()
    page.get_by_role('button', name='文字框选', exact=True).click()
    drag(page, [(.1, .1), (.5, .3)])
    page.wait_for_function('textCalls.length===1 && ocrTasks.get("scan").scanState.textRegions[0].status==="complete"')
    assert page.get_by_role('button', name='选择文字信息', exact=True).get_attribute('aria-expanded') == 'true'
    assert page.get_by_role('checkbox', name='放入文字框 1', exact=True).is_checked() is False
    assert page.get_by_role('checkbox', name='放入原生文字信息', exact=True).count() == 0
    assert page.evaluate('ocrTasks.get("scan").draft') == {'body_text': '', 'graphs': []}
    apply_frames(page, 'text', [1])
    assert page.locator('.dgs-body').inner_text() == '文字区域 1'
    assert page.evaluate('ocrTasks.get("scan").draft.graphs') == []
    assert page.locator('.dgs-body textarea,.dgs-body input,[contenteditable=true]').count() == 0
    assert native_snapshot(page) == original
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft') == original
    assert page.locator('.dgs-section-head button').count() == 0


def test_manual_results_do_not_import_native_text_context_or_graphs(scan_page):
    page = scan_page
    page.evaluate('''() => {
        const task=ocrTasks.get('scan');
        task.initialDocument.text_context={legends:[{text:'红色边表示待选边',graph_ids:['G1']}],captions:[]};
        task.draft=structuredClone(task.initialDocument);
    }''')
    open_scan(page)
    original = native_snapshot(page)
    page.get_by_role('button', name='图形框选', exact=True).click()
    drag(page, [(.1, .1), (.6, .6)])
    page.wait_for_function('graphCalls.length===1 && ocrTasks.get("scan").scanState.graphRegions[0].status==="complete"')
    apply_frames(page, 'graph', [1])
    document = page.evaluate('structuredClone(ocrTasks.get("scan").draft)')
    assert document['body_text'] == ''
    assert 'text_context' not in document
    assert [graph['id'] for graph in document['graphs']] == ['g1_1']
    page.get_by_role('button', name='文字框选', exact=True).click()
    drag(page, [(.1, .7), (.6, .9)])
    page.wait_for_function('textCalls.length===1 && ocrTasks.get("scan").scanState.textRegions[0].status==="complete"')
    apply_frames(page, 'text', [1])
    assert page.evaluate('ocrTasks.get("scan").draft.body_text') == '文字区域 1'
    assert page.evaluate('"text_context" in ocrTasks.get("scan").draft') is False
    assert native_snapshot(page) == original
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft.text_context') == original['text_context']


def test_red_close_discards_unapplied_picker_selection(scan_page):
    page = scan_page
    open_scan(page)
    page.get_by_role('button', name='文字框选', exact=True).click()
    drag(page, [(.1, .1), (.5, .3)])
    page.wait_for_function('textCalls.length===1 && ocrTasks.get("scan").scanState.textRegions[0].status==="complete"')
    page.get_by_role('checkbox', name='放入文字框 1', exact=True).check()
    close = page.get_by_role('button', name='关闭文字信息选择', exact=True)
    assert 'dmate-close-dot' in close.get_attribute('class')
    close.click()
    assert page.locator('.dgs-source-picker').count() == 0
    assert page.evaluate('ocrTasks.get("scan").draft') == {'body_text': '', 'graphs': []}
    open_picker(page, 'text')
    assert page.get_by_role('checkbox', name='放入文字框 1', exact=True).is_checked() is False


def test_legacy_mixed_manual_flags_never_import_native_content(scan_page):
    page = scan_page
    page.evaluate('''() => {
        const task=ocrTasks.get('scan'),graph=structuredClone(sample.graphs[0]);graph.id='g1_1';
        task.scanState={sourcesVersion:2,mode:'manual',manualSources:{graphNative:true,textNative:true},
            graphRegions:[{id:'g1',selected:true,status:'complete',polygon:[[.1,.1],[.4,.1],[.4,.4],[.1,.4]],graphs:[graph]}],textRegions:[]};
    }''')
    open_scan(page)
    assert page.evaluate('ocrTasks.get("scan").draft.body_text') == ''
    assert page.evaluate('ocrTasks.get("scan").draft.graphs.map(g=>g.id)') == ['g1_1']
    assert page.evaluate('ocrTasks.get("scan").scanState.sourcesVersion') == 3
    assert page.evaluate('"manualSources" in ocrTasks.get("scan").scanState') is False
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").draft') == native_snapshot(page)


def test_reopen_without_editing_preserves_saved_confirmation_despite_normalized_metadata(scan_page):
    page = scan_page
    page.evaluate('''() => {
        const originalFetch=window.fetch;
        window.fetch=async(url,options)=>{
            if(url!=='/graph/confirm')return originalFetch(url,options);
            const payload=JSON.parse(options.body);posts.push(payload);
            const saved=structuredClone(payload.document);
            for(const graph of saved.graphs){graph.complete=true;for(const edge of graph.edges)edge.status='accepted';}
            return {ok:true,json:async()=>({document:saved,drawing_document:saved,
                confirmation_token:'fixture',revision:1,semantic_context:{}})};
        };
    }''')
    open_scan(page)
    page.get_by_role('button', name='保存', exact=True).click()
    page.wait_for_function('posts.length===1 && !document.getElementById("graphEditorDialog").open')
    saved = page.evaluate('structuredClone(ocrTasks.get("scan").confirmation)')
    page.get_by_role('button', name='继续修改', exact=True).click()
    page.wait_for_function('document.querySelector(".dgs-source .dge-overlay-image").naturalWidth===600')
    page.get_by_label('关闭图形识别编辑器', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").dirty') is False
    assert page.evaluate('ocrTasks.get("scan").confirmation') == saved
    assert page.evaluate('posts.length') == 1
    # A real source change still invalidates the old signed structure.
    page.get_by_role('button', name='继续修改', exact=True).click()
    page.wait_for_function('document.querySelector(".dgs-source .dge-overlay-image").naturalWidth===600')
    page.get_by_role('button', name='文字框选', exact=True).click()
    drag(page, [(.1, .1), (.5, .3)])
    page.wait_for_function('textCalls.length===1 && ocrTasks.get("scan").scanState.textRegions[0].status==="complete"')
    assert page.evaluate('ocrTasks.get("scan").dirty') is True
    assert page.evaluate('ocrTasks.get("scan").confirmation') is None
    page.get_by_role('tab', name='原生识别', exact=True).click()
    assert page.evaluate('ocrTasks.get("scan").dirty') is True


def test_text_and_graph_information_have_their_own_bordered_cards(scan_page):
    page = scan_page
    open_scan(page)
    metrics = page.evaluate('''()=>{
      const owner=document.querySelector('.dgs-information'),text=document.querySelector('.dgs-text'),graph=document.querySelector('.dgs-graphs');
      const style=e=>{const s=getComputedStyle(e);return {border:s.borderTopWidth,radius:s.borderTopLeftRadius};};
      return {owner:style(owner),text:style(text),graph:style(graph),
        gap:graph.getBoundingClientRect().top-text.getBoundingClientRect().bottom};
    }''')
    assert metrics['owner']['border'] == '0px'
    assert metrics['text']['border'] == metrics['graph']['border'] == '1px'
    assert metrics['text']['radius'] == metrics['graph']['radius'] == '12px'
    assert metrics['gap'] >= 12
    assert page.locator('.dgs-section-head button').count() == 0


def test_manual_source_choices_are_large_solid_circles_and_close_is_red(scan_page):
    page = scan_page
    open_scan(page)
    page.get_by_role('button', name='文字框选', exact=True).click()
    drag(page, [(.1, .1), (.5, .3)])
    page.wait_for_function('textCalls.length===1 && ocrTasks.get("scan").scanState.textRegions[0].status==="complete"')
    choice = page.get_by_role('checkbox', name='放入文字框 1', exact=True)
    choice.check()
    metrics = choice.evaluate('''e=>{const s=getComputedStyle(e);return {
      width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,
      radius:s.borderRadius,appearance:s.appearance,fill:s.backgroundColor,
      hit:e.closest('label').getBoundingClientRect().height};}''')
    assert metrics['width'] == metrics['height'] >= 24
    assert metrics['hit'] >= 44
    assert metrics['radius'] == '50%' and metrics['appearance'] == 'none'
    assert metrics['fill'] not in ('transparent', 'rgba(0, 0, 0, 0)')
    close = page.get_by_role('button', name='关闭文字信息选择', exact=True)
    metrics = close.evaluate('''e=>{const s=getComputedStyle(e);return {
      width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,
      radius:s.borderRadius,fill:s.backgroundColor};}''')
    assert metrics['width'] == metrics['height']
    assert metrics['radius'] == '50%' and metrics['fill'] == 'rgb(239, 68, 68)'
