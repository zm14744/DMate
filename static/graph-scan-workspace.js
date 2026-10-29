(function(root){
'use strict';
const copy=value=>JSON.parse(JSON.stringify(value));
function mount(container,options){
 const d=container.ownerDocument,state=options.scanState||{},withLabels=value=>root.DMateGraphEditorModel.ensureAnonymousLabels(value);
 const initial=options.initialDocument||options.document||{body_text:'',graphs:[]};
 if(!state.nativeDocument)state.nativeDocument=withLabels(initial);
 // The original AI scan is a separate snapshot. Neither region queues nor
 // source selection write into it, even when the selected output is saved.
 const nativeDocument=copy(state.nativeDocument);
 state.graphRegions||=[];state.textRegions||=[];
 state.nextGraph=Math.max(Number.isInteger(state.nextGraph)?state.nextGraph:1,1,...state.graphRegions.map(row=>/^g[0-9]+$/.test(row.id)?Number(String(row.id).slice(1))+1:1));
 state.nextText=Math.max(Number.isInteger(state.nextText)?state.nextText:1,1,...state.textRegions.map(row=>Number.isInteger(row.id)?row.id+1:1));
 const migratingMixedManual=state.sourcesVersion===2&&state.mode==='manual'&&Boolean(state.manualSources?.graphNative||state.manualSources?.textNative);
 if(state.sourcesVersion!==3){
  if(state.sourcesVersion!==2)state.mode=state.graphSelectionActive||state.textSelectionActive?'manual':'native';
  for(const row of [...state.graphRegions,...state.textRegions])row.selected=row.selected!==false;
  state.sourcesVersion=3;
 }
 state.mode=state.mode==='manual'?'manual':'native';delete state.manualSources;
 const usable=row=>row.status==='complete'||row.status==='partial';
 for(const row of state.graphRegions){if(!usable(row))row.graphs=[];else if(row.graphs)row.graphs=withLabels({graphs:row.graphs}).graphs;if(usable(row)&&!row.graphs?.length)row.status='empty';}
 for(const row of [...state.graphRegions,...state.textRegions]){if(row.status==='running')row.status='queued';if(row.selected===undefined)row.selected=true;}
 for(const row of state.textRegions){if(!usable(row))row.text='';else if(!String(row.text||'').trim())row.status='empty';}
 let document=copy(nativeDocument),destroyed=false,saving=false,graphBusy=false,textBusy=false,textTimer=null;
 let lastEmitted=JSON.stringify(options.document||{body_text:'',graphs:[]}),picker=null,pickerFrame=null,draggedSource=null,renderedPickerKey='',deletePending=null;
 const active=new Set(),el=(tag,cls,text)=>{const n=d.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const button=(text,fn)=>{const n=el('button','',text);n.type='button';n.disabled=saving;n.addEventListener('click',event=>{if(!saving)fn(event);});return n;};
 const left=el('section','dgs-source'),right=el('aside','dgs-information'),workspace=el('div','dgs-workspace');right.setAttribute('aria-label','识别信息');
 const textSection=el('section','dgs-text dgs-information-card'),graphSection=el('section','dgs-graphs dgs-information-card'),status=el('p','dgs-status');
 textSection.setAttribute('aria-label','文字信息');graphSection.setAttribute('aria-label','图形信息');status.setAttribute('role','status');right.append(textSection,graphSection,status);workspace.append(left,right);
 const modes=el('div','dgs-modes');modes.setAttribute('role','tablist');modes.setAttribute('aria-label','识别模式');
 const nativeMode=button('原生识别',()=>setMode('native')),manualMode=button('自主框选',()=>setMode('manual'));
 for(const b of [nativeMode,manualMode])b.setAttribute('role','tab');modes.append(nativeMode,manualMode);
 const requestLabel=el('label','dgs-requirements-label','要求（可选）'),request=el('textarea','dgs-requirements');request.rows=2;request.maxLength=4000;request.value=options.requirements||'';request.setAttribute('aria-label','要求（可选）');request.addEventListener('input',()=>options.onRequirementsChange?.(request.value));requestLabel.append(request);
 const footer=el('div','dge-footer'),confirm=button('保存',async()=>{if(pending()||saving)return;saving=true;refresh();try{await options.onConfirm(copy(document),options.isQuestion!==false);}catch(error){status.textContent=error?.message||'确认失败，请重试。';}finally{saving=false;if(!destroyed)refresh();}});confirm.classList.add('dge-primary');footer.append(confirm);
 const content=el('div','dgs-content');content.append(modes,workspace,requestLabel);container.replaceChildren(content,footer);container.classList.add('dmate-graph-editor','dmate-graph-scan');
 let contentClip=null;
 // Stay in the native dialog's top layer without taking space from either
 // information card or being clipped by their independent scroll containers.
 const pickerLayer=el('div','dmate-graph-editor dgs-source-picker-layer');
 const pickerPortal=container.closest('dialog')||container;pickerPortal.append(pickerLayer);
 const rows=kind=>kind==='graph'?state.graphRegions:state.textRegions;
 const selected=kind=>rows(kind).filter(row=>row.selected!==false),label=(row,kind)=>(kind==='graph'?'图形框 '+String(row.id).replace(/^g/,''):'文字框 '+row.id);
 const blocked=row=>['queued','running','error','empty'].includes(row.status);
 const pending=()=>!document.body_text?.trim()&&!document.graphs.length||state.mode==='manual'&&(selected('graph').some(row=>blocked(row)||!row.graphs?.length)||selected('text').some(row=>blocked(row)||!String(row.text||'').trim()));
 function assemble(){
  if(state.mode==='native'){document=copy(nativeDocument);return;}
  // A framed workspace has its own document. Native text, graph metadata and
  // references never bleed into the selected ROI result.
  document={body_text:selected('text').filter(usable).map(row=>row.text||'').filter(Boolean).join('\n\n'),
   graphs:selected('graph').filter(usable).flatMap(row=>copy(row.graphs||[]))};
 }
 function emit(){assemble();const serialized=JSON.stringify(document);if(serialized!==lastEmitted){lastEmitted=serialized;options.onChange?.(copy(document));}}
 function setMode(mode){if(saving)return;state.mode=mode;picker=null;emit();refresh();}
 const bounds=points=>{const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);return[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];};
 const frames=()=>state.graphRegions.map(row=>({id:row.id,bbox:bounds(row.polygon),...(row.irregular?{region_polygon:row.polygon}:{}),vertices:[],edges:[]}));
 const overlayState=state.view||={zoom:100,visible:true};overlayState.mode='select';overlayState.start=null;overlayState.polygonDraft=[];overlayState.regions=state.textRegions;
 function activate(kind){state.mode='manual';state[kind==='graph'?'graphSelectionActive':'textSelectionActive']=true;}
 function changeGraph(row,points,irregular,activateSource=true){row.polygon=copy(points);row.irregular=irregular;row.version=(row.version||0)+1;row.status='queued';row.error='';row.graphs=[];row.controller?.abort();if(activateSource)activate('graph');emit();refresh();void pumpGraphs();}
 function changeText(row,points,irregular,activateSource=true){row.polygon=copy(points);row.irregular=irregular;row.version=(row.version||0)+1;row.status='queued';row.error='';row.text='';if(activateSource)activate('text');emit();refresh();clearTimeout(textTimer);textTimer=setTimeout(pumpText,450);}
 function remove(row,kind){row.controller?.abort();const list=rows(kind),index=list.indexOf(row);if(index<0)return;list.splice(index,1);if(kind==='graph'&&state.selectedGraphId===row.id)state.selectedGraphId=null;if(kind==='text'&&overlayState.selectedId===row.id)overlayState.selectedId=null;emit();refresh();overlay.refresh();}
 async function requestRemove(row,kind){
  if(destroyed||saving||deletePending||!rows(kind).includes(row))return;
  const op={row,kind,version:row.version,polygon:JSON.stringify(row.polygon),mode:state.mode};deletePending=op;
  try{
   const settings={title:'删除这个'+(kind==='graph'?'图形框':'文字框')+'？',body:'删除后无法恢复。\n'+label(row,kind),confirmText:'删除'+(kind==='graph'?'图形框':'文字框')};
   if(typeof options.confirmDelete!=='function'&&!root.DMateDeleteConfirm?.request)throw new Error('删除确认界面未加载，请刷新后重试。');
   const confirmed=await (typeof options.confirmDelete==='function'?options.confirmDelete(settings):root.DMateDeleteConfirm.request(container,settings));
   if(!confirmed||destroyed||saving||deletePending!==op||state.mode!==op.mode||!rows(kind).includes(row)||row.version!==op.version||JSON.stringify(row.polygon)!==op.polygon)return;
   remove(row,kind);
   const focus=pickerLayer.querySelector('input,button')||container.querySelector('[data-source-picker="'+kind+'"]');focus?.focus({preventScroll:true});
  }catch(error){if(!destroyed)status.textContent=error?.message||'无法确认删除，请重试。';}
  finally{if(deletePending===op)deletePending=null;}
 }
 function reorder(kind,sourceId,targetId){const list=rows(kind),from=list.findIndex(row=>String(row.id)===sourceId),to=list.findIndex(row=>String(row.id)===targetId);if(from<0||to<0||from===to)return;const [row]=list.splice(from,1);list.splice(to,0,row);emit();refresh();}
 function closePicker(){picker=null;refresh();}
 function openPicker(kind){if(state.mode!=='manual')return;if(picker===kind){closePicker();return;}picker=kind;refresh();}
 function showNewSource(kind){picker=kind;refresh();}
 function positionPicker(){
  pickerFrame=null;const box=pickerLayer.firstElementChild;if(!box)return;
  const win=d.defaultView,dialog=container.closest('dialog'),limits=dialog?.getBoundingClientRect(),head=dialog?.querySelector('.graph-editor-dialog-head')?.getBoundingClientRect();
  const left=Math.max(8,(limits?.left||0)+8),right=Math.min(win.innerWidth-8,(limits?.right||win.innerWidth)-8),top=Math.max(8,(head?.bottom||limits?.top||0)+8),bottom=Math.min(win.innerHeight-8,(limits?.bottom||win.innerHeight)-8);
  box.style.width=Math.max(180,Math.min(360,right-left))+'px';box.style.maxHeight=Math.max(80,bottom-top)+'px';
  const anchor=container.querySelector('[data-source-picker="'+picker+'"]')?.getBoundingClientRect(),rect=box.getBoundingClientRect();
  const x=Math.max(left,Math.min((anchor?.right||right)-rect.width,right-rect.width));
  let y=(anchor?.bottom||top)+8;if(y+rect.height>bottom)y=(anchor?.top||bottom)-rect.height-8;
  y=Math.max(top,Math.min(y,bottom-rect.height));box.style.left=x+'px';box.style.top=y+'px';
  // Keep the popup translucent without painting information-card borders or
  // text through its title. The portaled picker is outside this paint-only
  // hole, so the wallpaper and panel alpha remain intact and layout is stable.
  if(contentClip===null)contentClip=content.style.clipPath;
  const behind=content.getBoundingClientRect(),a=x-behind.left,b=y-behind.top,c=a+rect.width,e=b+rect.height;
  content.style.clipPath='polygon(evenodd,0 0,100% 0,100% 100%,0 100%,0 0,'+[a+'px '+b+'px',c+'px '+b+'px',c+'px '+e+'px',a+'px '+e+'px',a+'px '+b+'px'].join(',')+')';
  box.style.visibility='visible';
 }
 function queuePickerPosition(){if(picker&&!pickerFrame)pickerFrame=d.defaultView.requestAnimationFrame(positionPicker);}
 function sourcePicker(kind){
  const box=el('div','dgs-source-picker');box.style.visibility='hidden';box.setAttribute('role','dialog');box.setAttribute('aria-label',kind==='graph'?'选择图形来源':'选择文字来源');
  const pickerHead=el('div','dgs-source-picker-head');pickerHead.append(el('strong','',kind==='graph'?'选择图形框':'选择文字框'));box.append(pickerHead);
  const check=(text,checked,change)=>{const wrap=el('label','dgs-source-choice'),input=el('input');input.type='checkbox';input.checked=checked;input.disabled=saving;input.setAttribute('aria-label',text);input.addEventListener('change',()=>change(input.checked));wrap.append(input,el('span','',text));return wrap;};
  const list=el('div','dgs-source-list');
  for(const row of rows(kind)){
   const card=el('div','dgs-source-card');card.dataset.sourceId=String(row.id);
   const name=label(row,kind).replace('框 ','框');
   card.append(check(name,row.selected!==false,value=>{row.selected=value;emit();refresh();}));
   const removeButton=button('',()=>{void requestRemove(row,kind);});removeButton.className='dgs-source-delete dmate-close-dot';removeButton.setAttribute('aria-label','删除'+name);removeButton.title='删除';card.append(removeButton);
   card.draggable=!saving;card.addEventListener('dragstart',event=>{draggedSource={kind,id:String(row.id)};event.dataTransfer?.setData('text/plain',String(row.id));});
   card.addEventListener('dragover',event=>{if(draggedSource?.kind===kind)event.preventDefault();});
   card.addEventListener('drop',event=>{event.preventDefault();if(draggedSource?.kind===kind)reorder(kind,draggedSource.id,String(row.id));draggedSource=null;});card.addEventListener('dragend',()=>{draggedSource=null;});
   list.append(card);
  }
  box.append(list);return box;
 }
 function regionStatus(row,kind){
  let message={queued:'等待识别。',running:'正在识别。',partial:'待核对。',empty:kind==='graph'?'未识别到图形。':'未识别到文字。',error:'识别失败。'}[row.status]||'待识别。';
  if(row.status==='error'&&row.error){const detail=String(row.error).replace(/^(?:选区|框内|局部)?(?:文字|图形)?识别(?:失败|未完成)[，,。:\s]*/,'');if(detail)message='识别失败：'+detail;}
  else if(row.status==='partial'&&row.error)message='待核对：'+row.error;
  const line=el('p','dgs-region-state',label(row,kind)+'：'+message);line.setAttribute('role','status');return line;
 }
 function heading(section,kind,title){const head=el('div','dgs-section-head');head.append(el('h3','',title));if(state.mode==='manual'){const choose=button('选择信息',()=>openPicker(kind));choose.dataset.sourcePicker=kind;choose.setAttribute('aria-label',kind==='graph'?'选择图形信息':'选择文字信息');choose.setAttribute('aria-expanded',String(picker===kind));head.append(choose);}section.replaceChildren(head);}
 function refresh(){
  if(destroyed)return;assemble();nativeMode.setAttribute('aria-selected',String(state.mode==='native'));manualMode.setAttribute('aria-selected',String(state.mode==='manual'));nativeMode.disabled=saving;manualMode.disabled=saving;
  const textStates=state.mode==='manual'?selected('text').filter(row=>blocked(row)||row.status==='partial'):[],graphStates=state.mode==='manual'?selected('graph').filter(row=>blocked(row)||row.status==='partial'):[];
  heading(textSection,'text','文字信息');if(document.body_text||!textStates.length){const body=el('div','dgs-body',document.body_text||'暂无文字信息。');body.style.whiteSpace='pre-wrap';textSection.append(body);}
  for(const row of textStates)textSection.append(regionStatus(row,'text'));
  heading(graphSection,'graph','图形信息');
  const graphInformation=el('div','dgs-graph-information');
  root.DMateGraphFormat.renderGraphInformation(graphInformation,document,{showEmpty:!graphStates.length});graphSection.append(graphInformation);
  for(const row of graphStates)graphSection.append(regionStatus(row,'graph'));
  confirm.disabled=saving||pending();confirm.textContent=saving?'正在保存…':'保存';request.disabled=saving;
  // Recognition updates the information cards, but must not remove a source
  // checkbox or drag target underneath an in-progress pointer action.
  const pickerKey=state.mode==='manual'&&picker?JSON.stringify([picker,saving,rows(picker).map(row=>[String(row.id),row.selected!==false])]):'';
  if(pickerKey!==renderedPickerKey){const focused=d.activeElement?.getAttribute('aria-label');pickerLayer.replaceChildren();if(pickerKey){pickerLayer.append(sourcePicker(picker));positionPicker();if(focused)for(const node of pickerLayer.querySelectorAll('[aria-label]'))if(node.getAttribute('aria-label')===focused)node.focus({preventScroll:true});}renderedPickerKey=pickerKey;}
  if(pickerKey)positionPicker();else if(contentClip!==null){content.style.clipPath=contentClip;contentClip=null;}
 }
 async function pumpGraphs(){
  if(graphBusy||destroyed)return;graphBusy=true;
  try{for(let row;(row=state.graphRegions.find(r=>r.status==='queued'))&&!destroyed;){
   const version=row.version,controller=new AbortController();row.controller=controller;active.add(controller);
   row.status='running';row.graphs=[];row.error='';refresh();
   try{
    const result=await options.onRecognizeGraph(copy(row.polygon),{signal:controller.signal});
    if(destroyed||row.version!==version||!state.graphRegions.includes(row))continue;
    if(!result||result.error||result.recognition_status==='failed')throw new Error(result?.error||'图形识别未完成');
    const graphs=['not_graph','empty'].includes(result.recognition_status)?[]:result.document?.graphs;
    if(!Array.isArray(graphs)||graphs.some(graph=>!Array.isArray(graph?.vertices)||!Array.isArray(graph?.edges)))throw new Error('图形识别响应不完整。');
    row.graphs=withLabels({graphs:copy(graphs.filter(graph=>graph.vertices.length||graph.edges.length))}).graphs.map((g,i)=>({...g,id:row.id+'_'+(i+1)}));
    // Review flags describe returned graphs. A zero-result response is empty,
    // even when the service also requests a review; it cannot reuse old data.
    row.status=row.graphs.length?'complete':'empty';row.error='';
    if(row.graphs.length&&(result.review?.required||['partial','incomplete','uncertain','needs_review','review_required'].includes(result.recognition_status))){row.status='partial';row.error=result.review?.reasons?.join('；')||result.warning||'局部识别仍有疑点，请对照原图核对。';}
   }catch(error){if(!destroyed&&row.version===version&&state.graphRegions.includes(row)){row.graphs=[];row.status='error';row.error=error?.message||'图形识别失败，请重试。';}}
   finally{active.delete(controller);if(row.controller===controller)delete row.controller;if(!destroyed){emit();refresh();}}
  }}finally{graphBusy=false;}
 }
 async function pumpText(){
  if(textBusy||destroyed)return;textBusy=true;
  const queued=state.textRegions.filter(r=>r.status==='queued'),versions=queued.map(r=>r.version),controller=new AbortController();
  if(!queued.length){textBusy=false;return;}active.add(controller);
  queued.forEach(row=>{row.status='running';row.text='';row.error='';});refresh();
  try{
   const result=await options.onRecognizeText(queued.map((row,index)=>({id:row.id,polygon:copy(row.polygon),order:index})),{signal:controller.signal});
   if(!result||result.error||result.recognition_status==='failed'||!Array.isArray(result.regions))throw new Error(result?.error||'文字识别响应不完整。');
   const returned=new Map(result.regions.map(row=>[row.id,row]));
   queued.forEach((row,index)=>{
    if(destroyed||row.version!==versions[index]||!state.textRegions.includes(row))return;
    const value=returned.get(row.id);row.text='';row.error='';
    if(!value||value.error||value.recognition_status==='failed'){row.status='error';row.error=value?.error||'文字识别响应缺少选区。';return;}
    if(value.recognition_status==='empty'){row.status='empty';return;}
    row.text=String(value.text||'');row.status=row.text.trim()?'complete':'empty';
   });
  }catch(error){queued.forEach((row,index)=>{if(!destroyed&&row.version===versions[index]&&state.textRegions.includes(row)){row.text='';row.status='error';row.error=error?.message||'文字识别失败，请重试。';}});}
  finally{active.delete(controller);textBusy=false;if(!destroyed){emit();refresh();if(state.textRegions.some(row=>row.status==='queued'))void pumpText();}}
 }
 const outsidePicker=event=>{if(!deletePending&&picker&&!pickerLayer.contains(event.target)&&!event.target.closest?.('[data-source-picker]'))closePicker();};
 const escapePicker=event=>{if(!deletePending&&picker&&event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();closePicker();}};
 d.addEventListener('pointerdown',outsidePicker,true);d.addEventListener('keydown',escapePicker,true);d.addEventListener('scroll',queuePickerPosition,true);d.defaultView.addEventListener('resize',queuePickerPosition);
 const overlay=root.DMateGraphOverlay.mount(left,{scanOnly:true,originalUrl:options.originalUrl,state:overlayState,model:{getDocument:()=>({graphs:frames()})},graph:()=>({id:state.selectedGraphId,vertices:[],edges:[]}),disabled:()=>saving,
  createRegion:(points,irregular)=>{const row={id:'g'+state.nextGraph++,graphs:[],selected:false};state.graphRegions.push(row);state.selectedGraphId=row.id;changeGraph(row,points,irregular);showNewSource('graph',row);return row.id;},resizeRegion:(id,points,irregular)=>{const row=state.graphRegions.find(r=>r.id===id);if(row)changeGraph(row,points,irregular);},selectGraph:id=>{state.selectedGraphId=id;},
  selectionChanged:(points,irregular)=>{if(!points)return;const row={id:state.nextText++,selected:false};state.textRegions.push(row);changeText(row,points,irregular);showNewSource('text',row);},resizeTextRegion:(id,points)=>{const row=state.textRegions.find(r=>r.id===id);if(row)changeText(row,points,row.irregular);},selectTextRegion:id=>{overlayState.selectedId=id;},clearSelection:()=>{state.selectedGraphId=null;overlayState.selectedId=null;}});
 assemble();if(migratingMixedManual)emit();else lastEmitted=JSON.stringify(document);refresh();void pumpGraphs();if(state.textRegions.some(r=>r.status==='queued'))void pumpText();
 return{getDocument:()=>copy(document),destroy(){destroyed=true;deletePending=null;root.DMateDeleteConfirm?.cancel(container);if(contentClip!==null)content.style.clipPath=contentClip;clearTimeout(textTimer);if(pickerFrame)d.defaultView.cancelAnimationFrame(pickerFrame);d.removeEventListener('pointerdown',outsidePicker,true);d.removeEventListener('keydown',escapePicker,true);d.removeEventListener('scroll',queuePickerPosition,true);d.defaultView.removeEventListener('resize',queuePickerPosition);pickerLayer.remove();for(const controller of active)controller.abort();overlay.destroy();container.replaceChildren();container.classList.remove('dmate-graph-editor','dmate-graph-scan');}};
}
root.DMateGraphScan={mount};
})(typeof window!=='undefined'?window:globalThis);
