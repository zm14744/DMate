"""Real Chromium layout regression for the OCR image-workspace redesign.

Uses the actual Jinja HTML/CSS fragment and exact renderOcrTasks function from
static/script.js with stubbed task/network clocks. No paid AI, server or fake
image-generation task. Checks desktop/mobile, panel geometry and restoration
of ordinary chat input after the last image is removed.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static/script.js").read_text(encoding="utf-8")


@pytest.fixture
def layout_page(request):
    executable = os.environ.get("DMATE_BROWSER_EXECUTABLE") or shutil.which("chromium")
    if not executable:
        pytest.skip("Chromium unavailable")
    pw = pytest.importorskip("playwright.sync_api")
    width, height, theme = request.param
    # Inject exactly the production image panel and normal composer, with
    # their shared actual file-input DOM, not an unrelated mockup.
    marker = '<div id="ocrUploadStage"'
    assert HTML.count(marker) == 1
    fragment = marker + HTML.split(marker, 1)[1].split('\n<div class="right">', 1)[0]
    styles = '\n'.join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", HTML))
    assert ".ocr-upload-stage" in styles
    start = SCRIPT.index("function renderOcrTasks()")
    end = SCRIPT.index("\nfunction draftFromOcrResponse", start)
    render_code = SCRIPT[start:end]
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(
            "<!doctype html><html><body data-appearance-theme='" + theme + "'>"
            "<div class='center' style='height:85dvh;min-height:0'>"
            + fragment + "</body></html>"
        )
        page.add_style_tag(content=styles)
        page.evaluate("""code => {
            window.ocrTasks = new Map();
            window.ocrTaskLabel = t => t.state === 'recognizing' ? '识别中' : '已就绪';
            window.ocrTaskSeconds = () => 0;
            window.updateOcrTaskTimes = () => {};
            window.syncOcrTaskAvailability = () => {};
            window.queueChatJumpControlsUpdate = () => {};
            window.renderTasks = new Function(code + '\\nreturn renderOcrTasks;')();
            window.renderTasks();
        }""", render_code)
        yield page
        browser.close()


@pytest.mark.parametrize("layout_page", [
    (1440, 900, "dark"),
    (1440, 900, "light"),
    (390, 844, "dark"),
    (390, 844, "light"),
], indirect=True)
def test_single_upload_action_and_larger_image_panel(layout_page):
    page = layout_page
    # Without image tasks, ordinary chat must still have ONE upload control.
    assert page.locator('#imageBtn').count() == 1
    assert page.locator('#imageInput').count() == 1
    assert page.get_by_role('button', name='上传图片').is_visible()
    assert page.locator('#ocrUploadStage').is_hidden()
    assert page.locator('.center > .input-wrap').is_visible()
    assert page.locator('#imagePickerWrap').evaluate(
        'element => element.parentElement.className') == 'input'

    page.evaluate("""() => {
        ocrTasks.set('upload-1', {
            id:'upload-1',file:{name:'数学图片.png'},
            originalUrl:'data:image/png;base64,iVBORw0KGgo=',
            state:'recognizing',startedAt:0,finishedAt:null,
            error:'',confirming:false,sending:false
        });
        renderTasks();
    }""")
    panel = page.locator('#ocrTaskPanel')
    stage = page.locator('#ocrUploadStage')
    upload_button = page.get_by_role('button', name='上传图片')
    assert stage.is_visible()
    assert panel.is_visible()
    assert panel.locator('h2').inner_text() == '图片'
    assert panel.locator('.ocr-task-card').count() == 1
    assert page.locator('.center > .input-wrap').is_hidden()
    assert page.locator('#sendBtn').is_hidden()
    assert page.locator('#imagePickerWrap').evaluate(
        'el => el.parentElement.id') == 'ocrUploadActions'
    assert upload_button.is_visible()
    assert page.locator('#imageBtn').count() == 1
    assert page.locator('#imageInput').count() == 1
    panel_bounds = panel.bounding_box()
    upload_bounds = upload_button.bounding_box()
    assert panel_bounds is not None and upload_bounds is not None
    if page.viewport_size['width'] > 760:
        assert panel_bounds['width'] > 950, panel_bounds
        assert panel_bounds['height'] >= 250, panel_bounds
        assert upload_bounds['x'] >= panel_bounds['x'] + panel_bounds['width'] + 5
        assert abs((upload_bounds['y'] + upload_bounds['height'])
                   - (panel_bounds['y'] + panel_bounds['height'])) <= 3
    else:
        assert panel_bounds['width'] > 320, panel_bounds
        assert upload_bounds['x'] + upload_bounds['width'] <= (
            panel_bounds['x'] + panel_bounds['width'] + 2)
        assert upload_bounds['y'] >= panel_bounds['y'] + panel_bounds['height']
    # The native input is a real hit-area for WebView, not display:none.
    file_bounds = page.locator('#imageInput').bounding_box()
    assert file_bounds and file_bounds['width'] >= upload_bounds['width'] - 3
    assert file_bounds['height'] >= upload_bounds['height'] - 3

    page.evaluate("() => {ocrTasks.clear();renderTasks();}")
    assert page.locator('#ocrUploadStage').is_hidden()
    assert page.locator('.center > .input-wrap').is_visible()
    assert page.get_by_role('button', name='发送').is_visible()
    assert page.get_by_role('button', name='上传图片').is_visible()
    assert page.locator('#imagePickerWrap').evaluate(
        'element => element.parentElement.className') == 'input'


def test_only_selected_ui_names_are_changed():
    assert '<h2 id="ocrTaskTitle">图片</h2>' in HTML
    assert 'id="ocrTaskTitle">图片识题</h2>' not in HTML
    assert '<button id="imageBtn"' in HTML
    assert '>上传图片</button>' in HTML
    assert 'id="ocrUploadActions"' in HTML
    assert 'id="ocrUploadStage"' in HTML
    assert HTML.count('id="imageBtn"') == 1
    assert HTML.count('id="imageInput"') == 1
    assert 'composerWrap.hidden = hasImages' in SCRIPT
    assert 'uploadActions.appendChild(picker)' in SCRIPT
    assert 'normalComposer.insertBefore(picker' in SCRIPT


@pytest.mark.parametrize("layout_page", [(1440, 900, "dark")], indirect=True)
def test_red_cancel_immediately_removes_running_image_instead_of_cancelled_card(layout_page):
    page = layout_page
    # Run the actual production cancel implementation against the actual
    # production upload-card renderer, not a hand-written mock of UI behavior.
    source = SCRIPT.split("function discardOcrTask(task) {", 1)[1].split(
        "\\nfunction openImagePicker()", 1)[0]
    source = "function discardOcrTask(task) {" + source
    page.evaluate("""source => {
        window.cancelNotification = false;
        window.abortObserved = false;
        window.cancelTask = new Function(
            'ocrTasks', 'renderOcrTasks', 'notifyOcrCancelled',
            source + '\\nreturn cancelOcrTask;'
        )(window.ocrTasks, window.renderTasks, () => {
            window.cancelNotification = true;
        });
        window.ocrTasks.set('running', {
            id: 'running',
            file: {name: 'test.png'},
            originalUrl: 'data:image/png;base64,iVBORw0KGgo=',
            state: 'recognizing',
            startedAt: performance.now(),
            finishedAt: null,
            controller: {abort: () => {window.abortObserved = true;}},
            error: '', confirming: false, sending: false
        });
        renderTasks();
    }""", source)
    assert page.locator(".ocr-task-card").count() == 1
    page.evaluate("cancelTask('running')")
    assert page.locator(".ocr-task-card").count() == 0
    assert page.locator("#ocrTaskPanel").is_hidden()
    assert page.get_by_role("button", name="上传图片").is_visible()
    assert page.evaluate("abortObserved && cancelNotification && ocrTasks.size === 0")
