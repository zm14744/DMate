"""Render nested production panel trees over two high-contrast wallpapers."""
import io

import pytest
from PIL import Image

from test_appearance_surfaces import ROOT, appearance_page, install_appearance


MARK_ROOT = '<i data-sample="root"></i>'
MARK_INNER = '<i data-sample="inner"></i>'


def install_board(page):
    """Batch the real CSS/ancestor combinations without repeated browser boots.

    Only the probe layout is compacted. Panel, child-card, field, image and
    floating-surface backgrounds are the unchanged production declarations.
    """
    page.set_viewport_size({'width': page.viewport_size['width'], 'height': 1800})
    page.add_style_tag(content='''
      #opacity-board{position:absolute;inset:0 0 auto;z-index:99999;display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;padding:16px}
      #opacity-board .probe-tile{height:260px;min-width:0;overflow:hidden}
      #opacity-board .probe-tile>*,#opacity-board .modal-card{position:relative!important;inset:auto!important;
        width:100%!important;max-width:none!important;height:260px!important;max-height:none!important;
        min-height:0!important;margin:0!important;box-sizing:border-box!important;transform:none!important}
      #opacity-board .modal{display:block!important;padding:0!important}
      #opacity-board dialog[open]{display:flex!important;flex-direction:column!important}
      #opacity-board :is(.dcn-content,.dcn-main,.dgs-content,.dgs-workspace,.ocr-task-list){display:block!important;overflow:visible!important}
      #opacity-board .probe-content{padding:12px;min-height:0}
      #opacity-board .probe-card{min-height:64px;padding:12px!important;margin:8px 0!important}
      #opacity-board [data-sample]{display:block!important;width:12px!important;height:12px!important;
        min-width:12px!important;min-height:12px!important;flex:0 0 12px!important;margin:0 16px;
        padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important}
      #opacity-board .probe-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
      #opacity-board .probe-field{width:100%!important;height:38px!important;min-height:38px!important;margin:8px 0!important}
      #opacity-board .probe-image{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
      #opacity-board .probe-float{position:absolute!important;visibility:visible!important;inset:18px!important;
        width:auto!important;height:auto!important;max-width:none!important;max-height:none!important}
      @media(max-width:760px){#opacity-board{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:8px}}
    ''')
    r, i = MARK_ROOT, MARK_INNER
    trees = {
        'notebook': f'<dialog open class="dcn-dialog"><header class="dcn-heading"><h2>笔记本</h2>{r}</header><div class="dcn-content"><div class="dcn-main probe-content"><div class="dcn-explanation probe-card">概念解释{i}</div><textarea class="dcn-original probe-field" aria-label="原文"></textarea></div></div></dialog>',
        'account': f'<div id="accountModal" class="modal"><div class="modal-card account-card"><div class="modal-head"><div>账号</div>{r}</div><div class="account-body probe-content"><div class="account-register-panel probe-card">账号面板{i}</div></div></div></div>',
        'appearance': f'<div id="appearanceModal" class="modal"><div class="modal-card appearance-card"><div class="modal-head"><div>外观</div>{r}</div><div class="appearance-body probe-content"><div class="appearance-section probe-card">外观设置{i}</div></div></div></div>',
        'wrongbook': f'<div id="wrongBookModal" class="modal"><div class="modal-card"><div class="modal-head"><div>错题本</div>{r}</div><div id="wrongBookList" class="probe-content"><div class="wrong-card probe-card"><div class="wrong-feedback probe-card">回答{i}</div></div></div></div></div>',
        'report': f'<div id="learningReviewModal" class="modal"><div class="modal-card learning-review-card"><div class="modal-head"><div>学习报告</div>{r}</div><div id="learningReviewBody" class="learning-review-body"><section class="learning-review-section probe-card">学习报告{i}</section></div></div></div>',
        'knowledge': f'<div id="knowledgeGraphModal" class="modal"><div class="modal-card graph-modal-card"><div class="modal-head"><div>知识图谱</div>{r}</div><div class="knowledge-graph-canvas probe-content"><section class="kg-section probe-card"><div class="kg-mobile-viewport probe-card">知识关联{i}</div></section></div></div></div>',
        'scan': f'<dialog open class="graph-editor-dialog"><header class="graph-editor-dialog-head"><h2>图片识别</h2>{r}</header><div class="dmate-graph-editor dmate-graph-scan probe-content"><div class="dgs-modes probe-card">原生识别<i data-sample="modes"></i></div><div class="dgs-information"><section class="dgs-information-card probe-card">文字信息{i}</section></div></div></dialog>',
        'ocr': f'<section class="ocr-task-panel"><header class="ocr-task-panel-head"><h2>图片</h2>{r}</header><div class="ocr-task-list"><article class="ocr-task-card probe-card"><div class="ocr-task-structure probe-card">图形信息{i}</div></article></div></section>',
        'group': f'<dialog open class="ocr-group-dialog"><header><h2>分组</h2>{r}</header><div class="ocr-group-list"><div class="ocr-group-row probe-card"><div class="ocr-group-content">图片分组{i}</div></div></div></dialog>',
        'sidebar': f'<aside class="right"><div class="probe-head">对话信息{r}</div><div id="info" class="probe-card">无{i}</div></aside>',
        'floating': f'<div class="graph-editor-dialog"><img class="probe-image" alt="不透明绘图画布"><div class="dmate-drawing-workspace"><aside class="ddw-side-panel probe-float"><header class="probe-head">历史绘图{r}</header><div class="ddw-history-item is-current probe-card">我的图形{i}</div></aside></div></div>',
        'source': f'<div class="graph-editor-dialog"><img class="probe-image" alt="不透明原图"><div class="dmate-graph-editor"><aside class="dgs-source-picker probe-float"><header class="probe-head">选择来源{r}</header><div class="dgs-source-card probe-card">文字框1{i}</div></aside></div></div>',
    }
    page.evaluate('''trees=>{
      document.querySelector('.layout').style.visibility='hidden';
      const board=document.createElement('main');board.id='opacity-board';
      for(const [name,html] of Object.entries(trees)){
        const tile=document.createElement('section');tile.className='probe-tile';tile.dataset.probe=name;
        tile.innerHTML=html;
        for(const e of tile.querySelectorAll('[id]'))document.getElementById(e.id)?.remove();
        board.append(tile);
      }
      document.body.append(board);
    }''', trees)


def contrast_capture(page, phase):
    colors = ('black', 'white') if phase == 0 else ('white', 'black')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="50" height="100" fill="{colors[0]}"/><rect x="50" width="50" height="100" fill="{colors[1]}"/></svg>'
    page.evaluate('''async svg=>{
      setAppearanceBackgroundVisual(new Blob([svg],{type:'image/svg+xml'}));
      for(const image of document.querySelectorAll('.probe-image'))image.src='data:image/svg+xml,'+encodeURIComponent(svg);
      const wallpaper=new Image();wallpaper.src=appearanceBackgroundObjectUrl;
      await wallpaper.decode();
      await Promise.all([...document.querySelectorAll('.probe-image')].map(image=>image.decode()));
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    }''', svg)
    page.wait_for_function('[...document.querySelectorAll(".probe-image")].every(image=>image.complete&&image.naturalWidth>0)')
    return Image.open(io.BytesIO(page.screenshot(animations='disabled'))).convert('RGB')


def sample_points(page):
    return page.evaluate(r'''()=>Object.fromEntries([...document.querySelectorAll('[data-probe]')].map(tile=>{
      const points=Object.fromEntries([...tile.querySelectorAll('[data-sample]')].map(e=>{
        const r=e.getBoundingClientRect();return [e.dataset.sample,[Math.floor(r.x+r.width/2),Math.floor(r.y+r.height/2)]];
      }));
      const modal=tile.querySelector('.modal'),rgba=modal?getComputedStyle(modal).backgroundColor.match(/rgba?\(([^)]+)\)/):null;
      const mask=rgba&&rgba[1].split(',').length===4?Number(rgba[1].split(',')[3]):0;
      return [tile.dataset.probe,{points,mask}];
    }))''')


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
def test_wallpaper_reaches_nested_panels_without_extra_white_sheets(appearance_page, theme):
    page = appearance_page
    install_appearance(page)
    install_board(page)
    page.evaluate('theme=>{appearanceSettings.mode=theme;appearanceSettings.mask=0;appearanceSettings.blur=0;applyAppearanceSettings();}', theme)
    points = sample_points(page)
    transmissions = {}
    for amount in [75, 85, 100]:
        page.evaluate('amount=>{appearanceSettings.panelOpacity=amount;applyAppearanceSettings();}', amount)
        black, white = contrast_capture(page, 0), contrast_capture(page, 1)
        transmissions[amount] = {}
        for name, probe in points.items():
            delta = {kind: max(abs(a-b) for a, b in zip(black.getpixel(tuple(point)), white.getpixel(tuple(point))))
                     for kind, point in probe['points'].items()}
            transmissions[amount][name] = delta['root']
            if amount < 100:
                expected = 255 * (1 - amount / 100) * (1 - probe['mask'])
                assert delta['root'] == pytest.approx(expected, abs=2), (theme, amount, name, delta)
                assert all(abs(value-delta['root']) <= 3 for value in delta.values()), (theme, amount, name, delta)
            else:
                assert delta['root'] <= 1 and delta['inner'] <= 1, (theme, name, delta)
        if amount == 75:
            black.save(f'/tmp/dmate-panel-composite-{theme}-{page.viewport_size["width"]}.png')
    for name in points:
        assert transmissions[75][name] > transmissions[85][name] > transmissions[100][name]
    # The canvas/image is an opaque content source; a single floating panel
    # transmits its pixels instead of making those source pixels translucent.
    assert page.locator('.probe-image').first.evaluate('e=>getComputedStyle(e).opacity') == '1'
    assert page.locator('.dcn-original').evaluate('e=>getComputedStyle(e).backgroundColor') != 'rgba(0, 0, 0, 0)'
    assert page.evaluate('getComputedStyle(document.body).opacity') == '1'
    page.evaluate('appearanceSettings.mask=35;appearanceSettings.blur=5;applyAppearanceSettings()')
    assert page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--background-mask-alpha")') == '0.35'
    page.wait_for_function('getComputedStyle(document.querySelector("#appearanceBackgroundLayer")).filter==="blur(5px)"')
    assert page.locator('#appearanceBackgroundLayer').evaluate('e=>getComputedStyle(e).filter') == 'blur(5px)'


def test_wrongbook_empty_is_plain_centered_text_and_light_report_lines_are_visible(appearance_page):
    page = appearance_page
    install_appearance(page)
    page.evaluate('''()=>{
      appearanceSettings.mode='light';applyAppearanceSettings();
      document.querySelector('#wrongBookList').innerHTML='<div class="wrong-empty">无</div>';
      document.querySelector('#learningReviewBody').innerHTML='<section class="learning-review-section">学习报告</section>';
    }''')
    empty = page.locator('#wrongBookList>.wrong-empty')
    assert empty.inner_text() == '无'
    assert empty.evaluate('''e=>{const s=getComputedStyle(e);return [s.backgroundColor,s.backgroundImage,s.textAlign,s.paddingTop,s.paddingBottom,s.boxShadow];}''') == [
        'rgba(0, 0, 0, 0)', 'none', 'center', '28px', '28px', 'none']
    if page.viewport_size['width'] > 1100:
        for selector in ['#learningReviewModal .modal-head', '.learning-review-section']:
            assert page.locator(selector).evaluate('e=>getComputedStyle(e).borderBottomColor') == 'rgb(148, 163, 184)'


def test_editable_fields_and_selected_controls_keep_their_visual_feedback(appearance_page):
    page = appearance_page
    install_appearance(page)
    page.evaluate("appearanceSettings.mode='light';appearanceSettings.panelOpacity=75;applyAppearanceSettings()")
    page.add_script_tag(content=(ROOT / 'static/concept-notebook.js').read_text())
    page.evaluate('''()=>{
      const notebook=DMateConceptNotebook.mount({button:document.querySelector('#conceptNotebookBtn'),
        dialog:document.querySelector('#conceptNotebookDialog'),getContextKey:()=>'',
        getState:()=>({notes:[{id:'a',title:'集合',content:'原文',updatedAt:1},
          {id:'b',title:'关系',content:'原文',updatedAt:2}],deleted:{}}),onChange:()=>{}});
      notebook.open();
      const choice=document.createElement('button');choice.className='mobile-choice-option active';
      choice.textContent='已选择';document.querySelector('#mobileChoiceList').append(choice);
    }''')
    page.get_by_role('checkbox', name='选择概念：集合', exact=True).check()
    assert page.locator('.dcn-note.is-current').evaluate('e=>getComputedStyle(e).borderTopColor') != page.locator('.dcn-note:not(.is-current)').evaluate('e=>getComputedStyle(e).borderTopColor')
    assert page.get_by_role('checkbox', name='选择概念：集合', exact=True).evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(59, 130, 246)'
    assert page.locator('.dcn-original').evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgba(255, 255, 255, 0.75)'
    assert page.locator('.mobile-choice-option.active').evaluate('e=>getComputedStyle(e).backgroundColor') != 'rgba(0, 0, 0, 0)'
