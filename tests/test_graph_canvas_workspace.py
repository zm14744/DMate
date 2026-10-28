"""Actual-browser regressions for the canvas-first workspace."""
import pytest
from test_graph_overlay import canvas_page


def close_tools(page):
    page.locator('.dge-tool-palette').evaluate('e=>e.open=false')


def open_tools(page):
    page.locator('.dge-tool-palette').evaluate('e=>e.open=true')


def test_undirected_unweighted_graph_hides_irrelevant_edge_controls(canvas_page):
    page=canvas_page;close_tools(page)
    page.locator('[data-edge-id="e1"] .dge-overlay-hit').click()
    assert page.get_by_label('当前边端点一').is_visible()
    assert page.get_by_label('当前边方向').count()==0
    assert page.get_by_label('当前边权值').count()==0
    assert page.get_by_role('button',name='反转方向',exact=True).count()==0
    assert page.get_by_label('边 1 方向',exact=True).count()==0
    assert page.get_by_label('边 1 权重',exact=True).count()==0
    assert page.locator('.dge-selection-panel').evaluate('e=>getComputedStyle(e).position')=='absolute'


def test_delete_final_graph_once_keeps_canvas_and_clears_all_frames(canvas_page):
    page=canvas_page;close_tools(page)
    page.evaluate("instance.model.setGraphBounds('G1',[.1,.1,.9,.9])")
    open_tools(page);page.get_by_role('button',name='选择 / 移动',exact=True).click();close_tools(page)
    assert page.locator('.dge-frame-hit').count()==1
    page.locator('.dge-float-graphs > summary').click()
    page.get_by_role('button',name='删除子图',exact=True).click()
    assert page.evaluate('instance.getDocument().graphs.length')==0
    assert page.locator('.dge-frame-hit,.dge-overlay-node,.dge-overlay-edge').count()==0
    assert page.locator('.dge-overlay-image').is_visible()
    page.locator('.dge-float-graphs').evaluate('e=>e.open=false')
    open_tools(page)
    page.get_by_role('button',name='缩小原图',exact=True).click()
    page.get_by_role('button',name='适应',exact=True).click()
    assert page.locator('.dge-overlay-viewport').is_visible()
    page.get_by_role('button',name='框选图形',exact=True).click();close_tools(page)
    box=page.locator('.dge-overlay-viewport').bounding_box()
    page.mouse.move(box['x']+170,box['y']+220);page.mouse.down()
    page.mouse.move(box['x']+260,box['y']+350,steps=5);page.mouse.up()
    assert page.evaluate('instance.getDocument().graphs.length')==1
    assert page.locator('.dge-frame-hit').count()==1


def test_selection_moves_nodes_edges_and_pans_blank_canvas(canvas_page):
    page=canvas_page
    assert page.get_by_role('button',name='平移',exact=True).count()==0
    assert page.get_by_role('button',name='选择 / 移动',exact=True).count()==1
    close_tools(page)
    node=page.locator('[data-vertex-id="a"] .dge-overlay-node-hit').bounding_box()
    before=page.evaluate('instance.getDocument().graphs[0].vertices[0].x')
    x,y=node['x']+node['width']/2,node['y']+node['height']/2
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+45,y+20,steps=5);page.mouse.up()
    assert page.get_by_label('当前顶点名称').is_visible()
    assert page.evaluate('instance.getDocument().graphs[0].vertices[0].x')>before
    page.get_by_role('button',name='关闭属性',exact=True).click()
    edge=page.locator('[data-edge-id="e1"] .dge-overlay-hit').bounding_box()
    before=page.evaluate('instance.getDocument().graphs[0].vertices.map(v=>[v.x,v.y])')
    x,y=edge['x']+edge['width']/2,edge['y']+edge['height']/2
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+25,y+12,steps=5);page.mouse.up()
    after=page.evaluate('instance.getDocument().graphs[0].vertices.map(v=>[v.x,v.y])')
    assert all(a[0]>b[0] and a[1]>b[1] for a,b in zip(after,before))
    assert page.get_by_label('当前边端点一').is_visible()
    page.get_by_role('button',name='关闭属性',exact=True).click()
    box=page.locator('.dge-overlay-viewport').bounding_box()
    photo=page.locator('.dge-overlay-image').bounding_box()
    x,y=box['x']+30,box['y']+box['height']-40
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+60,y-20,steps=5);page.mouse.up()
    moved=page.locator('.dge-overlay-image').bounding_box()
    assert moved['x']-photo['x']==pytest.approx(60,abs=2)


def test_frame_click_selects_graph_and_results_popover_does_not_resize_canvas(canvas_page):
    page=canvas_page;close_tools(page)
    page.evaluate("instance.model.setGraphBounds('G1',[.1,.1,.4,.4]);instance.model.addGraph({bbox:[.6,.6,.9,.9]})")
    open_tools(page);page.get_by_role('button',name='选择 / 移动',exact=True).click();close_tools(page)
    box=page.locator('[data-graph-id="G2"]').bounding_box()
    page.mouse.click(box['x']+box['width']*.7,box['y']+box['height']*.7)
    assert page.get_by_label('当前子图名称').is_visible()
    assert page.get_by_label('当前子图名称').input_value()=='图 2'
    before=page.locator('.dge-overlay-viewport').bounding_box()
    page.get_by_role('button',name='关闭属性',exact=True).click()
    page.locator('.dge-float-results > summary').click()
    assert page.locator('.dge-float-results').evaluate('e=>e.open')
    after=page.locator('.dge-overlay-viewport').bounding_box()
    assert after==pytest.approx(before,abs=1)


@pytest.mark.parametrize(('directed','weighted'),[(False,False),(False,True),(True,False),(True,True)])
def test_edge_properties_follow_known_graph_type(canvas_page,directed,weighted):
    page=canvas_page
    page.evaluate('''([directed,weighted])=>{
      const url=document.querySelector('.dge-overlay-image').src,doc=instance.getDocument();instance.destroy();
      doc.graphs[0].directed=directed;doc.graphs[0].weighted=weighted;
      doc.graphs[0].edges[0].direction=directed?'forward':'undirected';
      doc.graphs[0].edges[0].weight=weighted?3:null;
      instance=DMateGraphEditor.mount(document.getElementById('editor'),{originalUrl:url,document:doc});
    }''',[directed,weighted])
    page.wait_for_function("document.querySelector('.dge-overlay-image').naturalWidth===900")
    close_tools(page);page.locator('[data-edge-id="e1"] .dge-overlay-hit').click()
    assert page.get_by_label('当前边方向',exact=True).count()==int(directed)
    assert page.get_by_label('当前边权值',exact=True).count()==int(weighted)
    assert page.get_by_role('button',name='反转方向',exact=True).count()==int(directed)


def test_delete_all_graphs_also_clears_unfinished_polygon(canvas_page):
    page=canvas_page
    page.get_by_label('选区方式').select_option('graph_poly')
    box=page.locator('.dge-overlay-viewport').bounding_box()
    page.mouse.click(box['x']+250,box['y']+240)
    page.mouse.click(box['x']+380,box['y']+260)
    assert page.locator('.dge-overlay-polygon-draft').count()==1
    page.locator('.dge-float-graphs > summary').click()
    page.get_by_role('button',name='删除子图',exact=True).click()
    assert page.evaluate('instance.getDocument().graphs.length')==0
    page.locator('.dge-float-graphs').evaluate('e=>e.open=false')
    open_tools(page);page.get_by_role('button',name='添加顶点',exact=True).click()
    box=page.locator('.dge-overlay-viewport').bounding_box()
    page.mouse.click(box['x']+300,box['y']+300)
    assert page.locator('.dge-overlay-node').count()==1
    assert page.locator('.dge-frame-hit,.dge-overlay-polygon-draft').count()==0


def test_mobile_floating_panels_remain_inside_the_screen(canvas_page):
    page=canvas_page;page.set_viewport_size({'width':390,'height':844});close_tools(page)
    page.locator('.dge-float-graphs > summary').click()
    box=page.locator('.dge-float-graphs .dge-float-content').bounding_box()
    assert box['x']>=0 and box['x']+box['width']<=392
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.locator('.dge-float-results > summary').click()
    assert not page.locator('.dge-float-graphs').evaluate('e=>e.open')
    assert page.locator('.dge-float-results').evaluate('e=>e.open')
