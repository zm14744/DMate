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
        page.route("**/*", lambda request: request.abort())
        page.set_content('<main id="editor" style="max-width:1000px"></main>')
        page.add_style_tag(content=(ROOT / "static/graph-editor.css").read_text())
        for name in ("graph-editor-model.js", "graph-editor-format.js",
                     "graph-editor-overlay.js", "graph-editor.js"):
            page.add_script_tag(content=(ROOT / "static" / name).read_text())
        page.evaluate("""args => {
            window.confirmed = []; window.changed = []; window.textAreas = [];
            window.instance = DMateGraphEditor.mount(document.getElementById('editor'), {
                originalUrl: args.url, document: args.sample,
                onChange: document => changed.push(document),
                onConfirm: async document => confirmed.push(document),
                onRecognizeText: async polygon => {
                    textAreas.push(polygon);
                    return '框选文字';
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


def test_overlay_makes_named_and_anonymous_nodes_and_edges_editable(canvas_page):
    page = canvas_page
    assert page.locator(".dge-overlay-node").count() == 2
    state = page.evaluate("instance.getDocument()")
    assert state["graphs"][0]["vertices"][1]["display_label"] == "①"
    assert page.get_by_text("点：A、①").count() >= 1
    page.get_by_role("button", name="添加顶点", exact=True).click()
    bounds = page.locator(".dge-overlay-svg").bounding_box()
    page.mouse.click(bounds["x"] + .45*bounds["width"], bounds["y"] + .18*bounds["height"])
    graph = page.evaluate("instance.getDocument().graphs[0]")
    assert len(graph["vertices"]) == 3
    assert graph["vertices"][2]["display_label"] == "②"
    new_id = graph["vertices"][2]["id"]
    page.get_by_role("button", name="添加边", exact=True).click()
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
    page.get_by_role("button", name="选择移动", exact=True).click()
    before = page.evaluate("instance.getDocument().graphs[0].vertices[0].x")
    x, y = center(page.locator('[data-vertex-id="a"] .dge-overlay-dot'))
    page.mouse.move(x, y); page.mouse.down()
    page.mouse.move(x + 45, y + 24, steps=6); page.mouse.up()
    graph = page.evaluate("instance.getDocument().graphs[0]")
    assert graph["vertices"][0]["x"] > before
    assert graph["edges"][0]["path"][0] == pytest.approx(
        [graph["vertices"][0]["x"], graph["vertices"][0]["y"]])
    page.get_by_role("button", name="框选图形", exact=True).click()
    bounds = page.locator(".dge-overlay-svg").bounding_box()
    x, y = bounds["x"], bounds["y"]
    page.mouse.move(x + bounds["width"]*.05, y + bounds["height"]*.06)
    page.mouse.down()
    page.mouse.move(x + bounds["width"]*.93, y + bounds["height"]*.93, steps=6)
    page.mouse.up()
    graph = page.evaluate("instance.getDocument().graphs[0]")
    assert graph["bbox"][0] < graph["bbox"][2] and graph["bbox"][1] < graph["bbox"][3]
    page.get_by_label("我已对照原图核对题干与各子图", exact=True).check()
    page.get_by_role("button", name="保存并确认", exact=True).click()
    page.wait_for_function("confirmed.length===1")
    assert page.evaluate("confirmed[0].graphs[0].edges[0].path.length") == 3
    assert page.evaluate("confirmed[0].graphs[0].bbox.length") == 4


def test_mobile_overlay_fits_without_external_assets(canvas_page):
    page = canvas_page
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.locator(".dge-overlay").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
    page.get_by_role("button", name="隐藏描绘", exact=True).click()
    assert page.locator(".dge-overlay-svg.is-hidden").count() == 1
    page.get_by_role("button", name="显示描绘", exact=True).click()
    assert page.locator(".dge-overlay-svg.is-hidden").count() == 0

def test_overlay_keeps_image_and_zoom_when_selecting_or_renaming(canvas_page):
    page = canvas_page
    page.get_by_role("button", name="放大原图", exact=True).click()
    page.get_by_role("button", name="放大原图", exact=True).click()
    assert page.locator(".dge-overlay-zoom").inner_text() == "156%"
    page.evaluate("window.imageBefore=document.querySelector('.dge-overlay-image')")
    page.locator('[data-vertex-id="a"] .dge-overlay-node-hit').click()
    assert page.get_by_label("当前顶点名称").is_visible()
    assert page.evaluate("window.imageBefore===document.querySelector('.dge-overlay-image')")
    page.get_by_label("当前顶点名称").fill("Z")
    assert page.evaluate("window.imageBefore===document.querySelector('.dge-overlay-image')")
    assert page.get_by_text("点：Z、①", exact=True).is_visible()
    assert page.locator(".dge-overlay-zoom").inner_text() == "156%"
    assert "Z—①" in page.evaluate("DMateGraphFormat.toPlain(instance.getDocument().graphs)")


def test_coarse_pointer_has_real_touch_targets_on_phone(canvas_page):
    page = canvas_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("""() => {
        Object.defineProperty(navigator, 'maxTouchPoints', {configurable:true, value:5});
    }""")
    page.get_by_role("button", name="隐藏描绘", exact=True).click()
    page.get_by_role("button", name="显示描绘", exact=True).click()
    hit=page.locator('[data-vertex-id="a"] .dge-overlay-node-hit').bounding_box()
    assert hit is not None and hit["width"] >= 40, hit
    assert hit["height"] >= 40
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")

def test_free_polygon_graph_selection_saves_user_outline(canvas_page):
    page = canvas_page
    page.get_by_label("选区方式").select_option("graph_poly")
    bounds = page.locator(".dge-overlay-svg").bounding_box()
    assert bounds
    for x, y in ((.08, .12), (.86, .1), (.93, .91), (.08, .89)):
        page.mouse.click(bounds["x"] + bounds["width"]*x,
                         bounds["y"] + bounds["height"]*y)
    assert page.get_by_role("button", name="完成轮廓").is_enabled()
    page.get_by_role("button", name="完成轮廓").click()
    polygon = page.evaluate("instance.getDocument().graphs[0].region_polygon")
    assert len(polygon) == 4
    assert polygon[0] == pytest.approx([.08, .12], abs=.005)
    assert page.locator(".dge-overlay-polygon").count() == 1
    page.get_by_role("button", name="撤销", exact=True).click()
    assert "region_polygon" not in page.evaluate("instance.getDocument().graphs[0]")


def test_user_text_rectangle_and_diy_polygon_feed_only_selected_area(canvas_page):
    page = canvas_page
    bounds = page.locator(".dge-overlay-svg").bounding_box()
    assert bounds
    page.get_by_label("选区方式").select_option("text_rect")
    page.mouse.move(bounds["x"] + bounds["width"]*.08,
                    bounds["y"] + bounds["height"]*.05)
    page.mouse.down()
    page.mouse.move(bounds["x"] + bounds["width"]*.6,
                    bounds["y"] + bounds["height"]*.18, steps=7)
    page.mouse.up()
    page.get_by_role("button", name="识别所选文字").click()
    page.wait_for_function("textAreas.length===1")
    assert len(page.evaluate("textAreas[0]")) == 4
    assert "框选文字" in page.evaluate("instance.getDocument().body_text")
    page.get_by_label("选区方式").select_option("text_poly")
    bounds = page.locator(".dge-overlay-svg").bounding_box()
    for x, y in ((.08, .07), (.9, .06), (.55, .15)):
        page.mouse.click(bounds["x"] + bounds["width"]*x,
                         bounds["y"] + bounds["height"]*y)
    page.get_by_role("button", name="完成轮廓").click()
    page.get_by_role("button", name="识别所选文字").click()
    page.wait_for_function("textAreas.length===2")
    assert len(page.evaluate("textAreas[1]")) == 3
    assert page.evaluate("instance.getDocument().body_text").count("框选文字") == 2

def test_focus_after_diy_region_keeps_math_positions_unchanged(canvas_page):
    page = canvas_page
    initial = page.evaluate("instance.getDocument().graphs[0].vertices.map(v => [v.x,v.y])")
    page.get_by_label("选区方式").select_option("graph_poly")
    rect = page.locator(".dge-overlay-svg").bounding_box()
    assert rect
    for x, y in ((.17, .2), (.55, .2), (.52, .7), (.17, .7)):
        page.mouse.click(rect["x"] + rect["width"]*x,
                         rect["y"] + rect["height"]*y)
    page.get_by_role("button", name="完成轮廓").click()
    page.get_by_role("button", name="聚焦图形").click()
    assert int(page.locator(".dge-overlay-zoom").inner_text().rstrip("%")) > 100
    assert page.evaluate("instance.getDocument().graphs[0].vertices.map(v => [v.x,v.y])") == initial
