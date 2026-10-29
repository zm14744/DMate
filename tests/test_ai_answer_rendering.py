"""Learning panels share the wrong-book formatter, math path and answer style."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

import pytest

from test_concept_notebook_ui import notebook_page, open_notebook

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'templates/index.html').read_text()
SCRIPT = (ROOT / 'static/script.js').read_text()
APP_FORMATTER = SCRIPT[SCRIPT.index('function escapeRawHtml('):SCRIPT.index('function copyMathLatex(')]
URLS = {
    'marked': 'https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.umd.js',
    'purify': 'https://cdn.jsdelivr.net/npm/dompurify@3.2.6/dist/purify.min.js',
    'math': 'https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js',
}


@pytest.fixture(params=[(1440, 900), (390, 844)])
def answer_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]})
        page.set_content('<body data-appearance-theme="light"><div id="wrong" class="wrong-answer-inner"></div><div id="drawing"></div><div id="notebook"></div></body>')
        page.add_style_tag(content='\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>', HTML)))
        page.add_style_tag(content=(ROOT / 'static/ai-answer-renderer.css').read_text())
        page.add_script_tag(content=(ROOT / 'static/ai-answer-renderer.js').read_text())
        yield page
        browser.close()


def test_shared_renderer_delegates_to_the_wrong_book_callbacks_and_style(answer_page):
    page = answer_page
    result = page.evaluate('''async () => {
      window.markdownInputs=[];window.mathTargets=[];
      window.markdownToHtml=text=>{markdownInputs.push(text);const p=document.createElement('p');p.textContent=text;return p.outerHTML;};
      window.renderMath=target=>{mathTargets.push(target.id);return Promise.resolve();};
      const source='**结构** $x_1^2$\\n- 第一项',wrong=document.getElementById('wrong');
      wrong.innerHTML=markdownToHtml(source);await renderMath(wrong);
      await DMateAIAnswer.render(document.getElementById('drawing'),source);
      await DMateAIAnswer.render(document.getElementById('notebook'),source);
      const style=id=>{const s=getComputedStyle(document.getElementById(id));return [s.fontSize,s.lineHeight,s.padding,s.whiteSpace,s.color];};
      return {inputs:markdownInputs,targets:mathTargets,html:[wrong.innerHTML,drawing.innerHTML,notebook.innerHTML],
        styles:[style('wrong'),style('drawing'),style('notebook')],classes:drawing.className};
    }''')
    assert len(set(result['inputs'])) == 1 and len(result['inputs']) == 3
    assert result['targets'] == ['wrong', 'drawing', 'notebook']
    assert len(set(result['html'])) == 1
    assert result['styles'][0] == result['styles'][1] == result['styles'][2]
    assert 'wrong-answer-inner' in result['classes']


def test_unavailable_formatter_falls_back_to_complete_literal_text(answer_page):
    page = answer_page
    payload = '<img src=x onerror="window.injected=true"><script>window.injected=true</script> $x_1$'
    result = page.evaluate('''async text=>{
      await DMateAIAnswer.render(document.getElementById('drawing'),text);
      return {text:drawing.textContent,unsafe:drawing.querySelectorAll('img,script').length,
        injected:!!window.injected,plain:drawing.classList.contains('dmate-ai-answer-plain')};
    }''', payload)
    assert result == {'text': payload, 'unsafe': 0, 'injected': False, 'plain': True}


def test_superseded_and_detached_answers_do_not_run_late_math(answer_page):
    page = answer_page
    result = page.evaluate('''async()=>{
      let valid=true;window.mathCalls=[];
      DMateAIAnswer.configure({markdownToHtml:text=>'<p>'+text+'</p>',renderMath:target=>{mathCalls.push(target.textContent);}});
      const target=document.getElementById('drawing');
      const old=DMateAIAnswer.render(target,'旧内容');
      const latest=DMateAIAnswer.render(target,'新内容');
      await Promise.all([old,latest]);
      const pending=DMateAIAnswer.render(document.getElementById('notebook'),'已离开',{isCurrent:()=>valid});
      valid=false;await pending;
      const detached=DMateAIAnswer.render(target,'已关闭');target.remove();await detached;
      return {calls:mathCalls,text:target.textContent};
    }''')
    assert result['calls'] == ['新内容']
    assert result['text'] == '已关闭'


def test_separate_answer_sections_share_one_math_queue(answer_page):
    result = answer_page.evaluate('''async()=>{
      let active=0,peak=0;const calls=[];
      DMateAIAnswer.configure({markdownToHtml:text=>'<p>'+text+'</p>',renderMath:async target=>{
        active++;peak=Math.max(peak,active);calls.push(target.id);
        await new Promise(resolve=>setTimeout(resolve,5));active--;
      }});
      await Promise.all(['wrong','drawing','notebook'].map(id=>DMateAIAnswer.render(document.getElementById(id),id)));
      return {calls,peak};
    }''')
    assert result == {'calls': ['wrong', 'drawing', 'notebook'], 'peak': 1}


def test_notebook_ai_sections_use_shared_renderer_without_interpreting_note_titles(notebook_page):
    page = notebook_page
    page.add_script_tag(content=(ROOT / 'static/ai-answer-renderer.js').read_text())
    page.add_style_tag(content=(ROOT / 'static/ai-answer-renderer.css').read_text())
    page.evaluate('''()=>{
      window.renderedAnswers=[];window.mathSections=[];
      DMateAIAnswer.configure({markdownToHtml:text=>{renderedAnswers.push(text);const p=document.createElement('p');p.textContent=text;return p.outerHTML;},
        renderMath:target=>{mathSections.push(target.className);}});
      stored.notes[0].title='<img src=x onerror=alert(1)>';
    }''')
    open_notebook(page)
    page.get_by_role('checkbox', name='选择概念：<img src=x onerror=alert(1)>', exact=True).check()
    page.get_by_role('checkbox', name='选择概念：关系', exact=True).check()
    original = page.evaluate('structuredClone(stored)')
    page.get_by_role('button', name='分析关联', exact=True).click()
    page.wait_for_function('document.querySelectorAll(".dcn-results .dmate-ai-answer").length===4 && mathSections.length===4')
    assert page.locator('.dcn-summary > p').count() == 1
    assert page.locator('.dcn-ai-text.wrong-answer-inner > p').count() == 3
    assert page.locator('.dcn-results script,.dcn-results img').count() == 0
    assert page.locator('.dcn-explanation h4').first.inner_text() == '<img src=x onerror=alert(1)>'
    assert page.evaluate('stored') == original
    page.get_by_label('我的概念笔记', exact=True).fill('修改原文后旧回答失效')
    assert page.locator('.dcn-results').inner_text() == ''


def cached_asset(url):
    folder = os.environ.get('DMATE_BROWSER_CDN_CACHE')
    if not folder:
        pytest.skip('Set verified public CDN cache for real Markdown/MathJax parity replay')
    key = hashlib.sha256(url.encode()).hexdigest()
    data = (Path(folder) / (key + '.js')).read_bytes()
    metadata = json.loads((Path(folder) / (key + '.json')).read_text())
    assert metadata['url'] == url and metadata['tls_verified'] is True
    assert metadata['sha256'] == hashlib.sha256(data).hexdigest()
    return data.decode()


def test_real_wrong_book_markdown_and_math_render_identically(answer_page):
    page = answer_page
    assets = {key: cached_asset(url) for key, url in URLS.items()}
    config = HTML[HTML.index('window.MathJax = {'):].split('</script>', 1)[0]
    page.add_script_tag(content=config)
    for key in ('marked', 'purify', 'math'):
        page.add_script_tag(content=assets[key])
    page.add_script_tag(content=APP_FORMATTER)
    page.evaluate('()=>{marked.setOptions({gfm:true,breaks:true});}')
    page.evaluate('MathJax.startup.promise')
    source = r'''## 结构说明

**顶点**与公式 $x_1^2+1$。

- 第一步
- 第二步

| 顶点 | 度 |
| --- | --- |
| A | 2 |

$$\sum_{i=1}^{3}i=6$$

<img src=x onerror="window.injected=true"><script>window.injected=true</script>
'''
    result = page.evaluate('''async source=>{
      const wrong=document.getElementById('wrong');wrong.innerHTML=markdownToHtml(source);await renderMath(wrong);
      await DMateAIAnswer.render(drawing,source);await DMateAIAnswer.render(notebook,source);
      const signature=node=>({tags:[...node.querySelectorAll('h2,strong,li,table')].map(n=>n.tagName),
        math:[...node.querySelectorAll('mjx-container')].map(n=>({display:n.getAttribute('display'),svg:!!n.querySelector('svg'),error:!!n.querySelector('[data-mjx-error]')})),
        text:node.innerText.replace(/\\s+/g,' ').trim(),unsafe:node.querySelectorAll('script,[onerror]').length});
      return {wrong:signature(wrong),drawing:signature(drawing),notebook:signature(notebook),injected:!!window.injected};
    }''', source)
    assert result['wrong'] == result['drawing'] == result['notebook']
    assert result['wrong']['tags'][:2] == ['H2', 'STRONG']
    assert result['wrong']['unsafe'] == 0 and result['injected'] is False
    assert len(result['wrong']['math']) == 2
    assert all(row['svg'] and not row['error'] for row in result['wrong']['math'])
    page.locator('#drawing').screenshot(path='/tmp/dmate-ai-answer-rendering-' + str(page.viewport_size['width']) + '.png')
