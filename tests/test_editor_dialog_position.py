"""The actual image editor is centered before its first visible frame."""
from test_scan_drawing_separation import scan_page
from test_editor_toolbar_chrome import install_production_appearance


def test_image_editor_reveals_only_after_modal_layout(scan_page):
    page = scan_page
    install_production_appearance(page)
    page.evaluate('''()=>{
      window.openingSamples=[];window.visibleSamples=[];
      const native=HTMLDialogElement.prototype.showModal;
      HTMLDialogElement.prototype.showModal=function(){
        native.call(this);
        if(this.id==='graphEditorDialog')openingSamples.push({
          visibility:getComputedStyle(this).visibility,position:getComputedStyle(this).position,
          imageVisibility:getComputedStyle(this.querySelector('.dge-overlay-image')).visibility});
      };
      window.recordDialog=true;
      function sample(){
        const dialog=document.getElementById('graphEditorDialog');
        if(dialog.open&&getComputedStyle(dialog).visibility==='visible'){
          const r=dialog.getBoundingClientRect();
          visibleSamples.push({x:r.x,y:r.y,width:r.width,height:r.height,
            viewportWidth:innerWidth,viewportHeight:innerHeight,pageX:scrollX,pageY:scrollY});
        }
        if(recordDialog)requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    }''')
    for _ in range(2):
        page.get_by_role('button', name='编辑核对', exact=True).click()
        page.wait_for_function('visibleSamples.length>=8')
        samples = page.evaluate('visibleSamples')
        for frame in samples:
            assert abs(frame['x'] + frame['width'] / 2 - frame['viewportWidth'] / 2) < 1
            assert abs(frame['y'] + frame['height'] / 2 - frame['viewportHeight'] / 2) < 1
            assert frame['pageX'] == frame['pageY'] == 0
        assert page.evaluate('document.activeElement.id') == 'graphEditorClose'
        page.get_by_role('button', name='关闭图形识别编辑器', exact=True).click()
        page.wait_for_function('ocrEditorTaskId===null')
        page.evaluate('visibleSamples=[]')
    assert page.evaluate('openingSamples') == [
        {'visibility': 'hidden', 'position': 'fixed', 'imageVisibility': 'hidden'},
        {'visibility': 'hidden', 'position': 'fixed', 'imageVisibility': 'hidden'},
    ]
    page.evaluate('recordDialog=false')


def watch_opening(page):
    install_production_appearance(page)
    page.evaluate('''()=>{
      window.hiddenFrames=[];window.visibleFrames=[];window.watchOpening=true;
      const rect=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
      function sample(){
        const dialog=document.getElementById('graphEditorDialog');
        if(dialog.open){
          if(getComputedStyle(dialog).visibility==='hidden')hiddenFrames.push({
            visibleChildren:[...dialog.querySelectorAll('*')].filter(node=>getComputedStyle(node).visibility==='visible').length,
            backdrop:getComputedStyle(dialog,'::backdrop').visibility});
          else visibleFrames.push({dialog:rect(dialog),image:rect(dialog.querySelector('.dge-overlay-image')),
            ready:dialog.querySelector('.dge-overlay').dataset.geometryReady,
            width:innerWidth,height:innerHeight,pageX:scrollX,pageY:scrollY});
        }
        if(watchOpening)requestAnimationFrame(sample);
      }requestAnimationFrame(sample);
    }''')


def image_bytes():
    import io
    from PIL import Image
    with Image.new('RGB',(900,1500),'white') as image:
        buffer=io.BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()


def assert_stable_reveal(page):
    page.wait_for_function('visibleFrames.length>=8')
    frames=page.evaluate('visibleFrames')
    first=frames[0]
    for frame in frames:
        assert abs(frame['dialog']['x']+frame['dialog']['width']/2-frame['width']/2)<1
        assert abs(frame['dialog']['y']+frame['dialog']['height']/2-frame['height']/2)<1
        assert frame['pageX']==frame['pageY']==0
        assert frame['ready']=='true'
        for part in ['dialog','image']:
            for key in ['x','y','width','height']:
                assert abs(frame[part][key]-first[part][key])<1
    assert page.evaluate('document.activeElement.id')=='graphEditorClose'


def test_slow_original_never_escapes_hidden_dialog_or_reveals_before_fit(scan_page):
    page=scan_page;watch_opening(page)
    pending=[]
    page.route('**/slow-editor-image.png',lambda route:pending.append(route))
    page.evaluate("ocrTasks.get('scan').originalUrl='https://dmate.test/slow-editor-image.png'")
    page.get_by_role('button',name='编辑核对',exact=True).click()
    page.wait_for_function('hiddenFrames.length>=6')
    assert len(pending)==1
    assert page.evaluate('visibleFrames.length')==0
    assert all(frame=={'visibleChildren':0,'backdrop':'hidden'} for frame in page.evaluate('hiddenFrames'))
    pending[0].fulfill(body=image_bytes(),content_type='image/png')
    assert_stable_reveal(page)
    page.locator('#graphEditorDialog').screenshot(path=f'/tmp/dmate-editor-ready-{page.viewport_size["width"]}.png')
    page.evaluate('watchOpening=false')


def test_image_failure_reveals_centered_editor_and_working_close(scan_page):
    page=scan_page;watch_opening(page)
    page.route('**/failed-editor-image.png',lambda route:route.fulfill(status=404,body='missing'))
    page.evaluate("ocrTasks.get('scan').originalUrl='https://dmate.test/failed-editor-image.png'")
    page.get_by_role('button',name='编辑核对',exact=True).click()
    page.locator('#graphEditorDialog').wait_for(state='visible')
    assert page.locator('.dge-overlay-status').inner_text()=='原图未能显示，可使用下方结构编辑'
    assert page.locator('#graphEditorDialog').get_attribute('data-positioning') is None
    page.get_by_role('button',name='关闭图形识别编辑器',exact=True).click()
    page.wait_for_function('ocrEditorTaskId===null')
    assert not page.locator('#graphEditorDialog').evaluate('dialog=>dialog.open')
    page.evaluate('watchOpening=false')


def test_closed_slow_opening_cannot_reveal_or_change_reopened_editor(scan_page):
    page=scan_page;watch_opening(page)
    original=page.evaluate("ocrTasks.get('scan').originalUrl")
    pending=[]
    page.route('**/old-editor-image.png',lambda route:pending.append(route))
    page.evaluate("ocrTasks.get('scan').originalUrl='https://dmate.test/old-editor-image.png'")
    page.get_by_role('button',name='编辑核对',exact=True).click()
    page.wait_for_function('hiddenFrames.length>=4')
    assert len(pending)==1 and page.evaluate('visibleFrames.length')==0
    page.keyboard.press('Escape')
    page.wait_for_function('ocrEditorTaskId===null')
    page.evaluate("value=>{ocrTasks.get('scan').originalUrl=value;visibleFrames=[];hiddenFrames=[];}",original)
    page.get_by_role('button',name='编辑核对',exact=True).click()
    assert_stable_reveal(page)
    before=page.locator('.dge-overlay-image').bounding_box()
    pending[0].fulfill(body=image_bytes(),content_type='image/png')
    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert page.locator('.dge-overlay-image').get_attribute('src')==original
    assert page.locator('.dge-overlay-image').bounding_box()==before
    assert page.locator('#graphEditorDialog').get_attribute('data-positioning') is None
    page.evaluate('watchOpening=false')


def test_decode_completion_precedes_the_first_visible_frame(scan_page):
    page=scan_page;watch_opening(page)
    page.evaluate('''()=>{
      const decode=HTMLImageElement.prototype.decode;
      HTMLImageElement.prototype.decode=function(){
        const completed=decode.call(this);
        return this.closest('#graphEditorDialog')
          ?completed.then(()=>new Promise(resolve=>window.releaseEditorDecode=resolve)):completed;
      };
    }''')
    page.get_by_role('button',name='编辑核对',exact=True).click()
    page.wait_for_function('typeof releaseEditorDecode==="function"&&hiddenFrames.length>=6')
    assert page.evaluate('visibleFrames.length')==0
    assert all(frame=={'visibleChildren':0,'backdrop':'hidden'} for frame in page.evaluate('hiddenFrames'))
    page.evaluate('releaseEditorDecode()')
    assert_stable_reveal(page)
    page.evaluate('watchOpening=false')
