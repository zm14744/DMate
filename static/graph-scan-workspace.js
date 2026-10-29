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
 for(const row of state.graphRegions)if(row.graphs)row.graphs=withLabels({graphs:row.graphs}).graphs;
 for(const row of [...state.graphRegions,...state.textRegions]){if(row.status==='running')row.status='queued';if(row.selected===undefined)row.selected=true;}
 let document=copy(nativeDocument),destroyed=false,saving=false,graphBusy=false,textBusy=false,textTimer=null;
 let lastEmitted=JSON.stringify(options.document||{body_text:'',graphs:[]}),picker=null,pickerDraft=null;
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
 const rows=kind=>kind==='graph'?state.graphRegions:state.textRegions;
 const selected=kind=>rows(kind).filter(row=>row.selected!==false),label=(row,kind)=>(kind==='graph'?'图形框 '+String(row.id).replace(/^g/,''):'文字框 '+row.id);
 const blocked=row=>['queued','running','error','empty'].includes(row.status);
 const pending=()=>!document.body_text?.trim()&&!document.graphs.length||state.mode==='manual'&&(selected('graph').some(row=>blocked(row)||!row.graphs?.length)||selected('text').some(row=>blocked(row)||!String(row.text||'').trim()));
 function assemble(){
  if(state.mode==='native'){document=copy(nativeDocument);return;}
  // A framed workspace has its own document. Native text, graph metadata and
  // references never bleed into the selected ROI result.
  document={body_text:selected('text').map(row=>row.text||'').filter(Boolean).join('\n\n'),
   graphs:selected('graph').flatMap(row=>copy(row.graphs||[]))};
 }
 function emit(){assemble();const serialized=JSON.stringify(document);if(serialized!==lastEmitted){lastEmitted=serialized;options.onChange?.(copy(document));}}
 function setMode(mode){if(saving)return;state.mode=mode;picker=null;pickerDraft=null;emit();refresh();}
 const bounds=points=>{const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);return[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];};
 const frames=()=>state.graphRegions.map(row=>({id:row.id,bbox:bounds(row.polygon),...(row.irregular?{region_polygon:row.polygon}:{}),vertices:[],edges:[]}));
 const overlayState=state.view||={zoom:100,visible:true};overlayState.mode='select';overlayState.start=null;overlayState.polygonDraft=[];overlayState.regions=state.textRegions;
 function activate(kind){state.mode='manual';state[kind==='graph'?'graphSelectionActive':'textSelectionActive']=true;}
 function changeGraph(row,points,irregular,activateSource=true){row.polygon=copy(points);row.irregular=irregular;row.version=(row.version||0)+1;row.status='queued';row.error='';row.graphs=[];if(activateSource)activate('graph');emit();refresh();void pumpGraphs();}
 function changeText(row,points,irregular,activateSource=true){row.polygon=copy(points);row.irregular=irregular;row.version=(row.version||0)+1;row.status='queued';row.error='';row.text='';if(activateSource)activate('text');emit();refresh();clearTimeout(textTimer);textTimer=setTimeout(pumpText,450);}
 function remove(row,kind){row.controller?.abort();const list=rows(kind),index=list.indexOf(row);if(index<0)return;list.splice(index,1);if(pickerDraft)delete pickerDraft.selected[String(row.id)];if(kind==='graph'&&state.selectedGraphId===row.id)state.selectedGraphId=null;if(kind==='text'&&overlayState.selectedId===row.id)overlayState.selectedId=null;emit();refresh();overlay.refresh();}
 function move(row,kind,step){const list=rows(kind),index=list.indexOf(row),to=index+step;if(index<0||to<0||to>=list.length)return;list.splice(index,1);list.splice(to,0,row);emit();refresh();}
 function closePicker(){picker=null;pickerDraft=null;refresh();}
 function openPicker(kind){if(state.mode!=='manual')return;if(picker===kind){closePicker();return;}picker=kind;pickerDraft={selected:Object.fromEntries(rows(kind).map(row=>[String(row.id),row.selected!==false]))};refresh();}
 function showNewSource(kind,row){if(picker!==kind){picker=kind;pickerDraft={selected:Object.fromEntries(rows(kind).map(source=>[String(source.id),source.selected!==false]))};}else pickerDraft.selected[String(row.id)]=false;refresh();}
 function sourcePicker(kind){
  const box=el('div','dgs-source-picker');box.setAttribute('role','group');box.setAttribute('aria-label',kind==='graph'?'选择图形来源':'选择文字来源');
  const pickerHead=el('div','dgs-source-picker-head'),close=button('',closePicker);close.className='dgs-source-picker-close dmate-close-dot';close.setAttribute('aria-label',kind==='graph'?'关闭图形信息选择':'关闭文字信息选择');close.title='关闭';pickerHead.append(el('strong','',kind==='graph'?'选择图形框':'选择文字框'),close);box.append(pickerHead);
  const check=(text,checked,change)=>{const wrap=el('label','dgs-source-choice'),input=el('input');input.type='checkbox';input.checked=checked;input.disabled=saving;input.setAttribute('aria-label',text);input.addEventListener('change',()=>change(input.checked));wrap.append(input,el('span','',text));return wrap;};
  for(const [index,row]of rows(kind).entries()){
   const card=el('div','dgs-source-card');card.dataset.sourceId=String(row.id);
   card.append(check('放入'+label(row,kind),pickerDraft.selected[String(row.id)]===true,value=>{pickerDraft.selected[String(row.id)]=value;}));
   const preview=kind==='text'?row.text:(row.graphs||[]).map((g,i)=>root.DMateGraphFormat.graphRows(g,i).title+' · '+g.vertices.length+'点/'+g.edges.length+'边').join('；');
   if(preview)card.append(el('p','dgs-source-preview',preview));
   card.append(regionStatus(row,kind));
   const order=el('div','dgs-source-order'),up=button('上移',()=>move(row,kind,-1)),down=button('下移',()=>move(row,kind,1));
   up.setAttribute('aria-label','上移'+label(row,kind));down.setAttribute('aria-label','下移'+label(row,kind));up.disabled=saving||index===0;down.disabled=saving||index===rows(kind).length-1;order.append(up,down);card.append(order);box.append(card);
  }
  if(!rows(kind).length)box.append(el('p','dgs-source-note','尚无框选结果，可在左侧连续框选。'));
  const apply=button(kind==='graph'?'放入所选图形信息':'放入所选文字信息',()=>{state.mode='manual';for(const row of rows(kind))row.selected=pickerDraft.selected[String(row.id)]===true;picker=null;pickerDraft=null;emit();refresh();});
  apply.className='dge-primary';box.append(apply);return box;
 }
 function regionStatus(row,kind){const line=el('div','dgs-region-state');line.append(el('span','',label(row,kind)+'：'+({queued:'等待识别',running:'识别中',complete:'已识别',partial:'待核对',empty:'未识别到内容',error:'识别失败'}[row.status]||'待识别')));if(row.error)line.append(el('p','',row.error));if(['error','empty'].includes(row.status))line.append(button('重新识别',()=>kind==='graph'?changeGraph(row,row.polygon,row.irregular,false):changeText(row,row.polygon,row.irregular,false)));line.append(button('删除'+label(row,kind),()=>remove(row,kind)));return line;}
 function heading(section,kind,title){const head=el('div','dgs-section-head');head.append(el('h3','',title));if(state.mode==='manual'){const choose=button('选择信息',()=>openPicker(kind));choose.setAttribute('aria-label',kind==='graph'?'选择图形信息':'选择文字信息');choose.setAttribute('aria-expanded',String(picker===kind));head.append(choose);}section.replaceChildren(head);if(state.mode==='manual'&&picker===kind)section.append(sourcePicker(kind));}
 function refresh(){
  if(destroyed)return;assemble();nativeMode.setAttribute('aria-selected',String(state.mode==='native'));manualMode.setAttribute('aria-selected',String(state.mode==='manual'));nativeMode.disabled=saving;manualMode.disabled=saving;
  heading(textSection,'text','文字信息');const body=el('div','dgs-body',document.body_text||'暂无文字信息，可在左侧框选文字。');body.style.whiteSpace='pre-wrap';textSection.append(body);
  if(state.mode==='manual'&&picker!=='text')for(const row of state.textRegions)textSection.append(regionStatus(row,'text'));
  heading(graphSection,'graph','图形信息');if(!document.graphs.length)graphSection.append(el('p','','暂无图形信息，可在左侧框选图形。'));
  document.graphs.forEach((graph,index)=>{const row=root.DMateGraphFormat.graphRows(graph,index),section=el('section','dgs-graph');section.append(el('h4','',row.title));if(row.showType!==false)section.append(el('p','',row.type));section.append(el('p','','顶点：'+(row.vertices.join('、')||'无')),el('p','',`${graph.vertices.length} 个顶点 · ${graph.edges.length} 条边`));section.append(el('p','dgs-appearance','图形外观：'+(row.description||'未提供外观描述。')));if(row.anonymousNote)section.append(el('p','dgs-anonymous-note',row.anonymousNote));if(row.positions.length){section.append(el('h5','','顶点位置'));for(const vertex of row.positions)section.append(el('p','dgs-vertex-position',vertex.txt));}if(row.named.length)section.append(el('p','','边：'+row.named.join('、')));for(const edge of row.relations)section.append(el('p','dgs-relation',edge.txt));graphSection.append(section);});
  if(state.mode==='manual'&&picker!=='graph')for(const row of state.graphRegions)graphSection.append(regionStatus(row,'graph'));
  confirm.disabled=saving||pending();confirm.textContent=saving?'正在保存…':'保存';request.disabled=saving;
 }
 async function pumpGraphs(){if(graphBusy||destroyed)return;graphBusy=true;try{for(let row;(row=state.graphRegions.find(r=>r.status==='queued'))&&!destroyed;){const version=row.version,controller=new AbortController();row.controller=controller;active.add(controller);row.status='running';refresh();try{const result=await options.onRecognizeGraph(copy(row.polygon),{signal:controller.signal});if(destroyed||row.version!==version||!state.graphRegions.includes(row))continue;if(result.recognition_status==='failed')throw new Error(result.error||'图形识别未完成');row.graphs=withLabels({graphs:copy(result.document?.graphs||[])}).graphs.map((g,i)=>({...g,id:row.id+'_'+(i+1)}));row.status=row.graphs.length?'complete':'empty';row.error=result.warning||'';if(result.review?.required){row.status='partial';row.error=result.review.reasons?.join('；')||'局部识别仍有疑点，请对照原图核对。';}}catch(error){if(!destroyed&&row.version===version&&state.graphRegions.includes(row)){row.status='error';row.error=error?.message||'图形识别失败，请重试。';}}finally{active.delete(controller);if(!destroyed){emit();refresh();}}}}finally{graphBusy=false;}}
 async function pumpText(){if(textBusy||destroyed)return;textBusy=true;const queued=state.textRegions.filter(r=>r.status==='queued'),versions=queued.map(r=>r.version),controller=new AbortController();if(!queued.length){textBusy=false;return;}active.add(controller);queued.forEach(r=>{r.status='running';});refresh();try{const result=await options.onRecognizeText(queued.map((r,index)=>({id:r.id,polygon:copy(r.polygon),order:index})),{signal:controller.signal});const returned=new Map((result.regions||[]).map(r=>[r.id,r]));queued.forEach((row,i)=>{if(destroyed||row.version!==versions[i]||!state.textRegions.includes(row))return;const value=returned.get(row.id);if(!value)throw new Error('文字识别响应缺少选区');row.text=String(value.text||'');row.status=row.text.trim()?'complete':'empty';});}catch(error){queued.forEach((row,i)=>{if(!destroyed&&row.version===versions[i]&&state.textRegions.includes(row)){row.status='error';row.error=error?.message||'文字识别失败，请重试。';}});}finally{active.delete(controller);textBusy=false;if(!destroyed){emit();refresh();if(state.textRegions.some(r=>r.status==='queued'))void pumpText();}}}
 const overlay=root.DMateGraphOverlay.mount(left,{scanOnly:true,originalUrl:options.originalUrl,state:overlayState,model:{getDocument:()=>({graphs:frames()})},graph:()=>({id:state.selectedGraphId,vertices:[],edges:[]}),disabled:()=>saving,
  createRegion:(points,irregular)=>{const row={id:'g'+state.nextGraph++,graphs:[],selected:false};state.graphRegions.push(row);state.selectedGraphId=row.id;changeGraph(row,points,irregular);showNewSource('graph',row);return row.id;},resizeRegion:(id,points,irregular)=>{const row=state.graphRegions.find(r=>r.id===id);if(row)changeGraph(row,points,irregular);},selectGraph:id=>{state.selectedGraphId=id;},
  selectionChanged:(points,irregular)=>{if(!points)return;const row={id:state.nextText++,selected:false};state.textRegions.push(row);changeText(row,points,irregular);showNewSource('text',row);},resizeTextRegion:(id,points)=>{const row=state.textRegions.find(r=>r.id===id);if(row)changeText(row,points,row.irregular);},selectTextRegion:id=>{overlayState.selectedId=id;},clearSelection:()=>{state.selectedGraphId=null;overlayState.selectedId=null;}});
 assemble();if(migratingMixedManual)emit();else lastEmitted=JSON.stringify(document);refresh();void pumpGraphs();if(state.textRegions.some(r=>r.status==='queued'))void pumpText();
 return{getDocument:()=>copy(document),destroy(){destroyed=true;clearTimeout(textTimer);for(const controller of active)controller.abort();overlay.destroy();container.replaceChildren();container.classList.remove('dmate-graph-editor','dmate-graph-scan');}};
}
root.DMateGraphScan={mount};
})(typeof window!=='undefined'?window:globalThis);
