"""The actual image editor is centered before its first visible frame."""
from test_scan_drawing_separation import scan_page


def test_image_editor_reveals_only_after_modal_layout(scan_page):
    page = scan_page
    page.evaluate('''()=>{
      window.openingSamples=[];window.visibleSamples=[];
      const native=HTMLDialogElement.prototype.showModal;
      HTMLDialogElement.prototype.showModal=function(){
        native.call(this);
        if(this.id==='graphEditorDialog')openingSamples.push({
          visibility:getComputedStyle(this).visibility,position:getComputedStyle(this).position});
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
        {'visibility': 'hidden', 'position': 'fixed'},
        {'visibility': 'hidden', 'position': 'fixed'},
    ]
    page.evaluate('recordDialog=false')
