"""Circular destructive actions share one painted red across themes/states."""
import io

import pytest

from test_appearance_surfaces import appearance_page, install_appearance


SAMPLES = [
    ('session-delete', '<div class="left"><div id="sessions"><div class="session"><button class="del"></button></div></div></div>'),
    ('modal-close', '<div class="modal-head"><button class="modal-close-dot"></button></div>'),
    ('drawer-close', '<button class="mobile-drawer-close"></button>'),
    ('ocr-cancel', '<div class="input-wrap"><div class="input"><button id="ocrCancelBtn"></button></div></div>'),
    ('ai-stop', '<div class="center"><div class="input-wrap"><div class="input"><button id="sendBtn" class="ai-stop-button">停止</button></div></div></div>'),
    ('wrong-search-clear', '<div id="wrongBookModal"><div class="wrong-tools"><div class="wrong-search-wrap"><button class="wrong-search-clear"></button></div></div></div>'),
    ('ocr-task-remove', '<div class="ocr-task-card"><button class="ocr-task-remove"></button></div>'),
    ('image-editor-close', '<div class="graph-editor-dialog"><button class="graph-editor-close-dot"></button></div>'),
    ('group-close', '<div class="ocr-group-dialog"><header><button class="ocr-group-close"></button></header></div>'),
    ('notebook-close', '<div class="dcn-dialog"><div class="dcn-heading"><button class="dcn-close"></button></div></div>'),
    ('notebook-analysis-cancel', '<div class="dcn-dialog"><div class="dcn-ai-actions"><button class="dcn-close dcn-analysis-cancel"></button></div></div>'),
    ('notebook-search-clear', '<div class="dcn-dialog"><div class="dcn-search-wrap"><button class="dcn-search-clear"></button></div></div>'),
    ('notebook-delete', '<div class="dcn-dialog"><div class="dcn-note"><button class="dcn-note-delete"></button></div></div>'),
    ('graph-panel-close', '<div class="dmate-graph-editor"><button class="dge-panel-close"></button></div>'),
    ('scan-source-delete', '<div class="dmate-graph-editor"><button class="dgs-source-delete"></button></div>'),
    ('drawing-history-delete', '<div class="dmate-drawing-workspace"><button class="ddw-history-delete"></button></div>'),
    ('drawing-export-close', '<div class="dmate-drawing-workspace"><button class="ddw-export-close"></button></div>'),
]


def assert_same_red(button):
    assert button.evaluate('''e=>{
      const s=getComputedStyle(e);
      return s.backgroundColor==='rgb(239, 68, 68)'&&s.backgroundImage==='none'&&s.filter==='none';
    }'''), button.get_attribute('aria-label')


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
def test_all_red_circle_families_keep_one_color_when_hovered_pressed_or_focused(appearance_page, theme):
    page = appearance_page
    install_appearance(page)
    # Preserve every real stylesheet and its order. Only wrapper geometry is
    # flattened to put the otherwise separate panels next to each other.
    page.evaluate('''({theme,samples})=>{
      appearanceSettings.mode=theme;applyAppearanceSettings({save:false});
      document.body.innerHTML='<main id="colorAudit">'+samples.map(([name,html])=>
        '<section class="sample"><span>'+name+'</span>'+html+'</section>').join('')+'</main>';
      document.querySelectorAll('#colorAudit .sample').forEach(section=>{
        section.querySelector('button').setAttribute('aria-label',section.querySelector('span').textContent);
        section.querySelectorAll('div,header').forEach(e=>e.classList.add('audit-context'));
      });
    }''', {'theme': theme, 'samples': SAMPLES})
    page.add_style_tag(content='''
      #colorAudit{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:12px;box-sizing:border-box;max-height:100dvh;overflow:auto}
      #colorAudit .sample{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;min-height:56px;padding:5px 10px;background:var(--surface-1);border:1px solid var(--border-strong);border-radius:10px}
      #colorAudit .sample>span{overflow-wrap:anywhere;font-size:12px;color:var(--text-primary)}
      #colorAudit .audit-context{display:contents!important}
      @layer dmate-red-circle-audit-layout {
        #colorAudit button{position:relative!important;inset:auto!important;transform:none!important;margin:0!important;flex-shrink:0!important}
        /* Display the mobile-only drawer control in the desktop inventory too. */
        #colorAudit .mobile-drawer-close{width:22px!important;height:22px!important;padding:0!important;border:0!important;border-radius:50%!important}
      }
    ''')
    for name, _ in SAMPLES:
        button = page.get_by_role('button', name=name, exact=True)
        page.mouse.move(0, 0)
        assert_same_red(button)
        button.hover()
        assert_same_red(button)
        page.mouse.down()
        assert_same_red(button)
        page.mouse.up()
        button.focus()
        assert_same_red(button)
        button.evaluate('e=>e.disabled=true')
        assert_same_red(button)
        if name == 'ocr-task-remove':
            assert button.evaluate('e=>getComputedStyle(e).opacity') == '0.45'
        button.evaluate('e=>e.disabled=false')
    page.mouse.move(0, 0)
    page.locator('#colorAudit').screenshot(path=f'/tmp/dmate-red-circle-audit-{theme}-{page.viewport_size["width"]}.png')
    # Pixel checks catch focus/hover filters, not just the CSS color string.
    image_module = pytest.importorskip('PIL.Image')
    for name in ['session-delete', 'ocr-task-remove', 'drawing-export-close']:
        button = page.get_by_role('button', name=name, exact=True)
        button.focus()
        image = image_module.open(io.BytesIO(button.screenshot())).convert('RGB')
        assert image.getpixel((image.width//2,image.height//2)) == (239,68,68)
