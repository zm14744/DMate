"""Exercise the real editable image overlay, not just semantic form fields."""
import base64
import io
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def canvas_page():
    executable = os.environ.get("DMATE_BROWSER_EXECUTABLE") or shutil.which("chromium")
    if not executable:
        pytest.skip("Chromium not available")
    playwright = pytest.importorskip("playwright.sync_api")
    from PIL import Image, ImageDraw

    picture = Image.new("RGB", (900, 580), "white")
    ink = ImageDraw.Draw(picture)
    ink.line((180, 145, 720, 435), fill="black", width=3)
    ink.ellipse((172, 137, 188, 153), fill="black")
    ink.ellipse((712, 427, 728, 443), fill="black")
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    sample = {"body_text": "判断图中各边方向", "graphs": [{
        "id": "G1", "name": "G1", "directed": False, "weighted": False,
        "vertices": [
            {"id": "a", "label": "A", "x": .2, "y": .25},
            {"id": "b", "label": None, "x": .8, "y": .75}],
        "edges": [{"id": "e1", "from": "a", "to": "b", "direction": "undirected",
                   "path": [[.2, .25], [.5, .5], [.8, .75]]}]
    }]}
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.set_default_timeout(5000)
        page.route("**/*", lambda request: request.abort())
        page.set_content('<main id="editor" style="max-width:1000px"></main>')
        page.add_style_tag(content=(ROOT / "static/graph-editor.css").read_text())
        for name in ("graph-editor-model.js", "graph-editor-format.js",
                     "graph-editor-overlay.js", "graph-editor.js"):
            page.add_script_tag(content=(ROOT / "static" / name).read_text())
        page.evaluate("""args => {
            window.confirmed = []; window.changed = []; window.textAreas = []; window.requirementsChanges = [];
            window.instance = DMateGraphEditor.mount(document.getElementById('editor'), {
                originalUrl: args.url, document: args.sample,
                onChange: document => changed.push(document),
                onConfirm: async document => confirmed.push(document),
                onRequirementsChange: value => requirementsChanges.push(value),
                onRecognizeText: async polygon => {
                    textAreas.push(polygon);
                    if (window.deferText) return new Promise(resolve => window.resolveText = resolve);
                    return {regions:polygon.map(r=>({id:r.id,text:'框选文字 '+r.id}))};
                }
            });
        }""", {"url": data_url, "sample": sample})
        page.wait_for_function("document.querySelector('.dge-overlay-image').naturalWidth===900")
        yield page
        browser.close()


def center(locator):
    box = locator.bounding_box()
    assert box and box["width"] and box["height"]
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def tool(page,name):
    page.locator('.dge-tool-palette').evaluate('e=>e.open=true')
    page.get_by_role('button',name=name,exact=True).click()


def test_overlay_makes_named_and_anonymous_nodes_and_edges_editable(canvas_page):
    page = canvas_page
    assert page.locator(".dge-overlay-hint, .dge-validation, .dge-context, .dge-footer .dge-check").count() == 0
    assert page.locator(".dge-overlay-viewport + .dge-overlay-status").count() == 0
    assert page.locator(".dge-overlay-tools .dge-overlay-status").count() == 1
    assert page.locator(".dge-overlay-node").count() == 2
    state = page.evaluate("instance.getDocument()")
    assert state["graphs"][0]["vertices"][1]["display_label"] == "①"
    assert page.get_by_text("点：A、①").count() >= 1
    tool(page,'添加顶点')
    bounds = page.locator(".dge-overlay-svg").bounding_box()
    page.mouse.click(bounds["x"] + .45*bounds["width"], bounds["y"] + .18*bounds["height"])
    graph = page.evaluate("instance.getDocument().graphs[0]")
    assert len(graph["vertices"]) == 3
    assert graph["vertices"][2]["display_label"] == "②"
    new_id = graph["vertices"][2]["id"]
    tool(page,'添加边')
    ax, ay = center(page.locator('[data-vertex-id="a"] .dge-overlay-dot'))
    bx, by = center(page.locator(f'[data-vertex-id="{new_id}"] .dge-overlay-dot'))
    page.mouse.click(ax, ay)
    page.mouse.click(bx, by)
    graph = page.evaluate("instance.getDocument().graphs[0]")
    assert len(graph["edges"]) == 2
    assert graph["edges"][-1]["from"] == "a"
    assert graph["edges"][-1]["to"] == new_id
    assert "A—②" in page.evaluate("DMateGraphFormat.toPlain(instance.getDocument().graphs)")


def test_drag_geometry_and_bounds_can_be_saved_and_restored(canvas_page):
    page = canvas_page
    tool(page,'选择 / 移动')
    before = page.evaluate("instance.getDocument().graphs[0].vertices[0].x")
    x, y = center(page.locator('[data-vertex-id="a"] .dge-overlay-dot'))
    page.mouse.move(x, y); page.mouse.down()
    page.mouse.move(x + 45, y + 24, steps=6); page.mouse.up()
    graph = page.evaluate("instance.getDocument().graphs[0]")
    assert graph["vertices"][0]["x"] > before
    assert graph["edges"][0]["path"][0] == pytest.approx(
        [graph["vertices"][0]["x"], graph["vertices"][0]["y"]])
    tool(page,'框选图形')
    bounds = page.locator(".dge-overlay-svg").bounding_box()
    x, y = bounds["x"], bounds["y"]
    page.mouse.move(x + bounds["width"]*.2, y + bounds["height"]*.15)
    page.mouse.down()
    page.mouse.move(x + bounds["width"]*.93, y + bounds["height"]*.93, steps=6)
    page.mouse.up()
    graph = page.evaluate("instance.getDocument().graphs.at(-1)")
    assert graph["bbox"][0] < graph["bbox"][2] and graph["bbox"][1] < graph["bbox"][3]
    tool(page,'添加顶点')
    view=page.locator(".dge-overlay-viewport").bounding_box()
    page.mouse.click(view["x"]+view["width"]/2,view["y"]+view["height"]/2)
    page.get_by_role("button", name="保存并确认", exact=True).click()
    page.wait_for_function("confirmed.length===1")
    assert page.evaluate("confirmed[0].graphs[0].edges[0].path.length") == 3
    assert page.evaluate("confirmed[0].graphs.at(-1).bbox.length") == 4


def test_mobile_overlay_fits_without_external_assets(canvas_page):
    page = canvas_page
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.locator(".dge-overlay").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
    tool(page,'隐藏描绘')
    assert page.locator(".dge-overlay-svg.is-hidden").count() == 1
    tool(page,'显示描绘')
    assert page.locator(".dge-overlay-svg.is-hidden").count() == 0

def test_overlay_zoom_out_and_fit_below_100_percent(canvas_page):
    page = canvas_page
    initial=float(page.locator('.dge-overlay-zoom').text_content().rstrip('%'))
    for _ in range(3):
        tool(page,'缩小原图')
    assert float(page.locator('.dge-overlay-zoom').text_content().rstrip('%')) < initial
    assert page.evaluate("""() => {
        const stage=document.querySelector('.dge-overlay-stage');
        const viewport=document.querySelector('.dge-overlay-viewport');
        return stage.getBoundingClientRect().width >= viewport.getBoundingClientRect().width;
    }""")
    for _ in range(20):
        tool(page,'缩小原图')
    assert float(page.locator('.dge-overlay-zoom').text_content().rstrip('%')) >= .01
    tool(page,'适应')
    fitted = float(page.locator('.dge-overlay-zoom').text_content().rstrip('%'))
    assert .01 <= fitted <= 100


def test_overlay_keeps_image_and_zoom_when_selecting_or_renaming(canvas_page):
    page = canvas_page
    tool(page,'放大原图')
    tool(page,'放大原图')
    zoom_before=page.locator(".dge-overlay-zoom").text_content()
    page.evaluate("window.imageBefore=document.querySelector('.dge-overlay-image')")
    page.locator(".dge-tool-palette").evaluate("e=>e.open=false")
    page.locator('[data-vertex-id="a"] .dge-overlay-node-hit').click()
    assert page.get_by_label("当前顶点名称").is_visible()
    assert page.evaluate("window.imageBefore===document.querySelector('.dge-overlay-image')")
    page.get_by_label("当前顶点名称").fill("Z")
    assert page.evaluate("window.imageBefore===document.querySelector('.dge-overlay-image')")
    page.locator(".dge-float-results").evaluate("e=>e.open=true")
    assert page.get_by_text("点：Z、①", exact=True).is_visible()
    assert page.locator(".dge-overlay-zoom").text_content() == zoom_before
    assert "Z—①" in page.evaluate("DMateGraphFormat.toPlain(instance.getDocument().graphs)")


def test_coarse_pointer_has_real_touch_targets_on_phone(canvas_page):
    page = canvas_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("""() => {
        Object.defineProperty(navigator, 'maxTouchPoints', {configurable:true, value:5});
    }""")
    tool(page,'隐藏描绘')
    tool(page,'显示描绘')
    hit=page.locator('[data-vertex-id="a"] .dge-overlay-node-hit').bounding_box()
    assert hit is not None and hit["width"] >= 40, hit
    assert hit["height"] >= 40
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")

def test_free_polygon_graph_selection_saves_user_outline(canvas_page):
    page = canvas_page
    tool(page,'适应')
    page.locator(".dge-tool-palette").evaluate("e=>e.open=true")
    page.get_by_label("选区方式").select_option("graph_poly")
    bounds = page.locator(".dge-overlay-image").bounding_box()
    assert bounds
    for x, y in ((.18, .12), (.86, .1), (.93, .91), (.18, .89)):
        page.mouse.click(bounds["x"] + bounds["width"]*x,
                         bounds["y"] + bounds["height"]*y)
    page.locator(".dge-tool-palette").evaluate("e=>e.open=true")
    assert page.get_by_role("button", name="完成轮廓").is_enabled()
    tool(page,'完成轮廓')
    polygon = page.evaluate("instance.getDocument().graphs.at(-1).region_polygon")
    assert len(polygon) == 4
    assert polygon[0] == pytest.approx([.18, .12], abs=.005)
    assert page.locator(".dge-overlay-polygon").count() == 1
    assert page.evaluate("instance.getDocument().graphs.length")==2
    assert page.get_by_label('选区方式').input_value()=='graph_poly'
    for x,y in ((.2,.2),(.4,.2),(.4,.4),(.2,.4)):
        page.mouse.click(bounds['x']+bounds['width']*x,bounds['y']+bounds['height']*y)
    tool(page,'完成轮廓')
    assert page.evaluate('instance.getDocument().graphs.length')==3
    page.get_by_role("button", name="撤销", exact=True).click()
    assert page.evaluate("instance.getDocument().graphs.length")==2
    page.get_by_role("button", name="撤销", exact=True).click()
    assert page.evaluate("instance.getDocument().graphs.length")==1
    assert "region_polygon" not in page.evaluate("instance.getDocument().graphs[0]")



def test_fit_after_diy_region_keeps_math_positions_unchanged(canvas_page):
    page = canvas_page
    initial = page.evaluate("instance.getDocument().graphs[0].vertices.map(v => [v.x,v.y])")
    page.locator(".dge-tool-palette").evaluate("e=>e.open=true")
    page.get_by_label("选区方式").select_option("graph_poly")
    rect = page.locator(".dge-overlay-svg").bounding_box()
    assert rect
    for x, y in ((.17, .2), (.55, .2), (.52, .7), (.17, .7)):
        page.mouse.click(rect["x"] + rect["width"]*x,
                         rect["y"] + rect["height"]*y)
    tool(page,'完成轮廓')
    assert page.get_by_role('button',name='聚焦图形',exact=True).count()==0
    page.get_by_role('button',name='适应',exact=True).click()
    assert float(page.locator(".dge-overlay-zoom").text_content().rstrip("%")) <= 100
    assert page.evaluate("instance.getDocument().graphs[0].vertices.map(v => [v.x,v.y])") == initial


def test_empty_auto_detected_panel_has_no_predrawn_strokes(canvas_page):
    page = canvas_page
    page.evaluate("""() => {
        const url = document.querySelector('.dge-overlay-image').src;
        window.instance.destroy();
        window.instance = DMateGraphEditor.mount(
            document.getElementById('editor'), {
                originalUrl: url,
                document: { body_text: '手动描绘', graphs: [
                    {id:'G1',name:'图 G', directed:true, weighted:false,
                     bbox:[.06,.08,.9,.92], vertices:[],edges:[]}
                ]},
                onChange: doc => changed.push(doc),
                onConfirm: async doc => confirmed.push(doc)
            });
    }""")
    assert page.locator('.dge-overlay-node, .dge-overlay-edge').count() == 0
    assert page.locator('.dge-overlay-bbox').count() == 1
    assert page.locator('.dge-detected-type').text_content() == '有向图 · 无权图'
    assert page.evaluate('instance.getDocument().graphs[0].vertices.length') == 0
    assert page.evaluate('instance.getDocument().graphs[0].edges.length') == 0

    # A vertex appears ONLY after the user selects Add and clicks.
    tool(page,'添加顶点')
    rect = page.locator('.dge-overlay-svg').bounding_box()
    assert rect
    page.mouse.click(rect['x'] + .33 * rect['width'],
                     rect['y'] + .37 * rect['height'])
    assert page.locator('.dge-overlay-node').count() == 1
    assert page.locator('.dge-overlay-edge').count() == 0


def test_pure_text_ocr_does_not_create_a_dummy_graph_canvas(canvas_page):
    page = canvas_page
    page.evaluate("""() => {
        const url = document.querySelector('.dge-overlay-image').src;
        window.instance.destroy();
        window.instance = DMateGraphEditor.mount(
            document.getElementById('editor'), {
                originalUrl: url,
                document: {body_text:'这张图片只有文字和公式',graphs:[]},
                onChange: doc => changed.push(doc),
                onConfirm: async doc => confirmed.push(doc)
            });
    }""")
    assert page.locator('.dge-overlay').count() == 1
    assert page.locator('.dge-visual').count() == 0
    assert page.locator('.dge-overlay-image').is_visible()
    assert page.get_by_label('题干、全部小问与公式').count() == 0
    assert page.evaluate('instance.getDocument().body_text') == '这张图片只有文字和公式'
    page.get_by_role('button', name='保存并确认', exact=True).click()
    page.wait_for_function('confirmed.length===1')
    assert page.evaluate('confirmed[0].graphs') == []



def test_repeated_vertex_placement_does_not_jump_back_to_top(canvas_page):
    """Actual browser pointer events must not remount the photograph or scroll."""
    page = canvas_page
    # Produce both nested image scrolling and a long editor page.
    tool(page,'放大原图')
    tool(page,'放大原图')
    tool(page,'放大原图')
    tool(page,'添加顶点')
    page.evaluate("""() => {
        const nested = document.querySelector('.dge-overlay-viewport');
        nested.scrollTop = Math.min(160, nested.scrollHeight - nested.clientHeight);
        const root = document.scrollingElement;
        root.scrollTop = Math.min(160, root.scrollHeight - root.clientHeight);
        window.originalImageElement = document.querySelector('.dge-overlay-image');
        window.originalNestedScroller = nested;
    }""")
    # Click inside the VISIBLY SCROLLED image viewport (not an advanced form).
    for count, fx in enumerate((.45, .55, .65), start=3):
        before = page.evaluate("""() => ({
            nested: document.querySelector('.dge-overlay-viewport').scrollTop,
            outer: document.scrollingElement.scrollTop,
            zoom: document.querySelector('.dge-overlay-zoom').textContent
        })""")
        viewport = page.locator('.dge-overlay-viewport').bounding_box()
        assert viewport
        x = viewport['x'] + viewport['width'] * fx
        y = max(35, viewport['y'] + min(90, viewport['height']*.25))
        assert y < min(885, viewport['y'] + viewport['height'])
        page.mouse.click(x, y)
        page.wait_for_function(f"instance.getDocument().graphs[0].vertices.length === {count}")
        after = page.evaluate("""() => ({
            nested: document.querySelector('.dge-overlay-viewport').scrollTop,
            outer: document.scrollingElement.scrollTop,
            zoom: document.querySelector('.dge-overlay-zoom').textContent,
            sameImage: window.originalImageElement === document.querySelector('.dge-overlay-image'),
            sameScroller: window.originalNestedScroller === document.querySelector('.dge-overlay-viewport'),
            count: document.querySelector('.dge-node-panel h3').textContent
        })""")
        assert after['sameImage'] and after['sameScroller']
        assert after['zoom'] == before['zoom']
        assert after['nested'] == pytest.approx(before['nested'], abs=1.5)
        assert after['outer'] == pytest.approx(before['outer'], abs=1.5)
        assert after['count'] == '节点 · ' + str(count)
    # In-place vertex edits must still keep every node accessible for renaming.
    assert page.get_by_label('节点 5 标签').count() == 1



def test_original_can_be_hidden_for_drawing_only_and_opacity_is_adjustable(canvas_page):
    page = canvas_page
    slider = page.get_by_role("slider", name="原图透明度")
    photo = page.locator(".dge-overlay-image")
    assert slider.input_value() == "100"
    assert photo.evaluate("node => node.style.visibility") == "visible"
    page.evaluate("""() => {
        window.originalPhoto = document.querySelector('.dge-overlay-image');
        window.originalGraph = JSON.stringify(instance.getDocument());
        window.originalStageSize = [
            document.querySelector('.dge-overlay-stage').scrollWidth,
            document.querySelector('.dge-overlay-stage').scrollHeight
        ];
    }""")
    slider.evaluate("""el => {
        el.value = '38';
        el.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    assert slider.input_value() == "38"
    assert photo.evaluate("node => node.style.opacity") == "0.38"
    assert page.locator(".dge-overlay-opacity-value").inner_text() == "38%"
    # Hiding the original leaves the drawing layer and source coordinate system intact.
    tool(page,'隐藏原图')
    assert photo.evaluate("node => node.style.visibility") == "hidden"
    assert page.locator(".dge-overlay-node").count() == 2
    assert page.locator(".dge-overlay-edge").count() == 1
    assert page.locator(".dge-overlay-stage").evaluate(
        "node => getComputedStyle(node).backgroundColor") == "rgb(255, 255, 255)"
    assert page.get_by_role("button", name="显示原图").is_visible()
    assert page.evaluate("""() => {
        return window.originalPhoto === document.querySelector('.dge-overlay-image')
            && window.originalGraph === JSON.stringify(instance.getDocument())
            && JSON.stringify(window.originalStageSize) === JSON.stringify([
                document.querySelector('.dge-overlay-stage').scrollWidth,
                document.querySelector('.dge-overlay-stage').scrollHeight
            ]);
    }""")
    # Restore photo at the same opacity; slider changes do not alter drawing.
    tool(page,'显示原图')
    assert photo.evaluate("node => node.style.visibility") == "visible"
    assert photo.evaluate("node => node.style.opacity") == "0.38"
    slider.evaluate("""el => {
        el.value = '100';
        el.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    assert photo.evaluate("node => node.style.opacity") == "1"


def test_points_and_edges_choose_high_contrast_ink_from_local_pixels(canvas_page):
    page = canvas_page
    page.evaluate("""() => {
        const canvas = document.createElement('canvas');
        canvas.width = 900; canvas.height = 580;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, 900, 580);
        ctx.fillStyle = '#080808'; ctx.fillRect(450, 0, 450, 580);
        const url = canvas.toDataURL('image/png');
        instance.destroy();
        instance = DMateGraphEditor.mount(document.getElementById('editor'), {
            originalUrl: url,
            document: {body_text:'', graphs:[{
                id:'G1', name:'图 G', directed:true, weighted:false, bbox:[0,0,1,1],
                vertices:[
                    {id:'left', label:'A', x:.25, y:.5},
                    {id:'right', label:'B', x:.75, y:.5}
                ],
                edges:[{id:'edge1', from:'left', to:'right', direction:'forward'}]
            }]},
            onChange: doc => changed.push(doc),
            onConfirm: async doc => confirmed.push(doc)
        });
    }""")
    page.wait_for_function("""() => {
        const img = document.querySelector('.dge-overlay-image');
        const left = document.querySelector('[data-vertex-id="left"] .dge-overlay-dot');
        const right = document.querySelector('[data-vertex-id="right"] .dge-overlay-dot');
        return img?.naturalWidth === 900 && left?.dataset.ink && right?.dataset.ink;
    }""")
    left = page.locator('[data-vertex-id="left"] .dge-overlay-dot')
    right = page.locator('[data-vertex-id="right"] .dge-overlay-dot')
    # White paper => black ink; dark shadow/background => white ink.
    assert left.get_attribute("data-ink") == "#111827"
    assert right.get_attribute("data-ink") == "#ffffff"
    cores = page.locator('[data-edge-id="edge1"] .dge-overlay-stroke')
    inks = cores.evaluate_all("nodes => [...new Set(nodes.map(node => node.dataset.ink))]")
    assert "#111827" in inks and "#ffffff" in inks
    # Every local core stroke gets the complementary halo, including across
    # the white-to-dark boundary; arrowheads use the same contrast family.
    pairs = cores.evaluate_all("""nodes => nodes.map(node => ({
        ink: node.dataset.ink,
        halo: node.previousElementSibling?.dataset.ink,
        marker: node.getAttribute('marker-end') || ''
    }))""")
    assert all((row["halo"] == "#ffffff" if row["ink"] == "#111827"
                else row["halo"] == "#111827") for row in pairs)
    assert any(row["marker"].endswith("-light)") for row in pairs)
    # Contrast follows the displayed image after opacity blending.
    page.get_by_role("slider", name="原图透明度").evaluate("""el => {
        el.value = '10'; el.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    assert left.get_attribute("data-ink") == "#111827"
    assert right.get_attribute("data-ink") == "#111827"
    tool(page,'隐藏原图')
    assert page.locator('[data-vertex-id="left"] .dge-overlay-dot').get_attribute("data-ink") == "#111827"
    assert page.locator('[data-vertex-id="right"] .dge-overlay-dot').get_attribute("data-ink") == "#111827"


def test_fixed_viewport_and_drawing_beyond_source_image(canvas_page):
    page = canvas_page
    viewport = page.locator('.dge-overlay-viewport')
    before = viewport.bounding_box()
    tool(page,'缩小原图')
    after = viewport.bounding_box()
    assert abs(before['height'] - after['height']) < 1
    assert abs(before['width'] - after['width']) < 1
    tool(page,'选择 / 移动')
    box = viewport.bounding_box()
    x, y = box['x'] + 180, box['y'] + 100
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+300,y+100,steps=5);page.mouse.up()
    tool(page,'添加顶点')
    page.mouse.click(box['x']+170,box['y']+80)
    node = page.evaluate('instance.getDocument().graphs[0].vertices.at(-1)')
    assert node['x'] < 0 or node['y'] < 0
    tool(page,'隐藏原图')
    assert page.locator('.dge-overlay-image').evaluate('e=>getComputedStyle(e).visibility') == 'hidden'
    assert page.locator('.dge-overlay-node').count() == 3




def test_initial_fit_and_blank_viewport_can_receive_nodes(canvas_page):
    page=canvas_page
    viewport=page.locator('.dge-overlay-viewport')
    photo=page.locator('.dge-overlay-image')
    v=viewport.bounding_box();image=photo.bounding_box()
    assert image['width'] <= v['width']+1 and image['height'] <= v['height']+1
    for _ in range(4):tool(page,'缩小原图')
    assert abs(viewport.bounding_box()['height']-v['height'])<1
    assert abs(viewport.bounding_box()['width']-v['width'])<1
    tool(page,'添加顶点')
    page.mouse.click(v['x']+v['width']-25,v['y']+v['height']-25)
    node=page.evaluate('instance.getDocument().graphs[0].vertices.at(-1)')
    assert node['x']>1 or node['y']>1
    assert page.get_by_label('选区方式').locator('option[value^="text_"]').count()==0
    assert page.locator('.dge-body').count()==0


def test_fit_waits_until_hidden_editor_becomes_visible(canvas_page):
    page=canvas_page
    page.evaluate('''() => {
      const url=document.querySelector('.dge-overlay-image').src,doc=instance.getDocument();instance.destroy();
      const host=document.getElementById('editor');host.style.display='none';
      instance=DMateGraphEditor.mount(host,{originalUrl:url,document:doc});
    }''')
    page.wait_for_function("document.querySelector('.dge-overlay-image').naturalWidth===900")
    page.evaluate("document.getElementById('editor').style.display='block'")
    page.wait_for_function("document.querySelector('.dge-overlay-image').getBoundingClientRect().width>100")
    photo=page.locator('.dge-overlay-image').bounding_box();box=page.locator('.dge-overlay-viewport').bounding_box()
    assert photo['height']<=box['height']+1 and photo['width']<=box['width']+1


def test_fit_centres_the_entire_image_in_fixed_viewport(canvas_page):
    page=canvas_page
    for width,height in [(900,580),(240,1800),(1800,240)]:
        page.evaluate('''([w,h])=>{
          const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
          canvas.getContext('2d').fillRect(0,0,w,h);
          document.querySelector('.dge-overlay-image').src=canvas.toDataURL();
        }''',[width,height])
        page.wait_for_function('(w)=>document.querySelector(".dge-overlay-image").naturalWidth===w',arg=width)
        tool(page,'适应')
        page.evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        image=page.locator('.dge-overlay-image').bounding_box()
        view=page.locator('.dge-overlay-viewport').evaluate('e=>{const b=e.getBoundingClientRect();return {x:b.x+e.clientLeft,y:b.y+e.clientTop,w:e.clientWidth,h:e.clientHeight}}')
        assert image['width']<=view['w']+1 and image['height']<=view['h']+1
        assert abs(image['x']+image['width']/2-view['x']-view['w']/2)<3
        assert abs(image['y']+image['height']/2-view['y']-view['h']/2)<3


def test_consecutive_frames_add_graphs_without_camera_jump_even_after_type_reply(canvas_page):
    page=canvas_page
    page.evaluate('''()=>{
      const url=document.querySelector('.dge-overlay-image').src,doc=instance.getDocument();instance.destroy();
      window.typeReplies=[];
      instance=DMateGraphEditor.mount(document.getElementById('editor'),{originalUrl:url,document:doc,
        onRecognizeGraphType:()=>new Promise(r=>typeReplies.push(r))});
    }''')
    page.wait_for_function('document.querySelector(".dge-overlay-image").naturalWidth===900')
    tool(page,'放大原图')
    tool(page,'框选图形')
    def camera():
        return page.locator('.dge-overlay-viewport').evaluate('e=>{const i=e.querySelector("img").getBoundingClientRect();return {left:e.scrollLeft,top:e.scrollTop,x:i.x,y:i.y,w:i.width,h:i.height}}')
    before=camera()
    for n in range(2):
        box=page.locator('.dge-overlay-viewport').bounding_box()
        x=box['x']+180+140*n;y=box['y']+110
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+95,y+100,steps=5);page.mouse.up()
        page.wait_for_function('(n)=>instance.getDocument().graphs.length===n',arg=n+2)
        assert page.locator('[data-overlay-tool="bounds"]').get_attribute('aria-pressed')=='true'
        assert len(page.evaluate('instance.getDocument().graphs[0].vertices'))==2
        after=camera()
        for key in before:assert abs(after[key]-before[key])<1.5,(key,before,after)
    assert page.locator('.dge-overlay-bbox').count()==2
    page.evaluate('typeReplies.forEach(r=>r({directed:false,weighted:false,recognition_status:"complete"}))')
    page.wait_for_function('instance.getDocument().graphs.slice(1).every(g=>g.directed===false)')
    after=camera()
    for key in before:assert abs(after[key]-before[key])<1.5,(key,before,after)
    page.get_by_role('button',name='撤销',exact=True).click()
