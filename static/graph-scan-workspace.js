(function(root){
'use strict';
const copy=value=>JSON.parse(JSON.stringify(value));
function mount(container,options){
 const d=container.ownerDocument, state=options.scanState||{};
 const withLabels=value=>root.DMateGraphEditorModel.ensureAnonymousLabels(value);
 let document=withLabels(options.document||{body_text:'',graphs:[]}),destroyed=false,saving=false,graphBusy=false,textBusy=false,textTimer=null;
 state.graphRegions ||= [];state.textRegions ||= [];state.nextGraph ||= 1;state.nextText ||= 1;
 for(const row of state.graphRegions)if(row.graphs)row.graphs=withLabels({graphs:row.graphs}).graphs;
 for(const row of [...state.graphRegions,...state.textRegions])if(row.status==='running')row.status='queued';
 const active=new Set();
 const el=(tag,cls,text)=>{const n=d.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const button=(text,fn)=>{const n=el('button','',text);n.type='button';n.addEventListener('click',fn);return n;};
 const left=el('section','dgs-source'),right=el('aside','dgs-information'),workspace=el('div','dgs-workspace');
 right.setAttribute('aria-label','识别信息');
 const textSection=el('section','dgs-text'),graphSection=el('section','dgs-graphs'),status=el('p','dgs-status');
 textSection.setAttribute('aria-label','文字信息');graphSection.setAttribute('aria-label','图形信息');status.setAttribute('role','status');
 // Model reasoning/debug notes are not user-facing instructions. Current
 // frame failures and uncertain edge attributes remain visible in their rows.
 right.append(textSection,graphSection,status);workspace.append(left,right);
 const requestLabel=el('label','dgs-requirements-label','要求（可选）'),request=el('textarea','dgs-requirements');
 request.rows=2;request.maxLength=4000;request.value=options.requirements||'';
 request.setAttribute('aria-label','要求（可选）');request.addEventListener('input',()=>options.onRequirementsChange?.(request.value));requestLabel.append(request);
 const footer=el('div','dge-footer'),confirm=button('保存',async()=>{
  if(pending()||saving)return;saving=true;refresh();
  try{await options.onConfirm(copy(document),options.isQuestion!==false);}catch(error){status.textContent=error?.message||'确认失败，请重试。';}
  finally{saving=false;if(!destroyed)refresh();}
 });footer.append(confirm);confirm.classList.add('dge-primary');
 const content=el('div','dgs-content');content.append(workspace,requestLabel);
 container.replaceChildren(content,footer);container.classList.add('dmate-graph-editor','dmate-graph-scan');
 const pending=()=>[...state.graphRegions,...state.textRegions].some(r=>['queued','running','error'].includes(r.status));
 const emit=()=>options.onChange?.(copy(document));
 const bounds=points=>{const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];};
 const frames=()=>state.graphRegions.map(row=>({id:row.id,bbox:bounds(row.polygon),...(row.irregular?{region_polygon:row.polygon}:{}),vertices:[],edges:[]}));
 const overlayState=state.view ||= {zoom:100,visible:true};
 // Opening a saved task starts with selection, even if its last gesture was
 // a framing tool. Keep the task's source coordinates and recognition rows.
 overlayState.mode='select';overlayState.start=null;overlayState.polygonDraft=[];overlayState.regions=state.textRegions;
 function assembleGraphs(){if(state.graphSelectionActive)document.graphs=state.graphRegions.flatMap(r=>r.graphs||[]);}
 function assembleText(){if(state.textSelectionActive)document.body_text=state.textRegions.slice().sort((a,b)=>a.id-b.id).map(r=>r.text||'').filter(Boolean).join('\n\n');}
 function changeGraph(row,points,irregular){
  row.polygon=copy(points);row.irregular=irregular;row.version=(row.version||0)+1;row.status='queued';row.error='';row.graphs=[];
  state.graphSelectionActive=true;assembleGraphs();emit();refresh();void pumpGraphs();
 }
 function changeText(row,points,irregular){
  row.polygon=copy(points);row.irregular=irregular;row.version=(row.version||0)+1;row.status='queued';row.error='';row.text='';
  state.textSelectionActive=true;assembleText();emit();refresh();clearTimeout(textTimer);textTimer=setTimeout(pumpText,450);
 }
 function remove(row,kind){
  row.controller?.abort();
  const list=kind==='graph'?state.graphRegions:state.textRegions;list.splice(list.indexOf(row),1);
  assembleGraphs();assembleText();emit();refresh();overlay.refresh();
 }
 function regionStatus(row,kind){
  const label=kind==='graph'?'图形框 '+row.id.replace(/^g/,''):'文字框 '+row.id;
  const line=el('div','dgs-region-state');line.append(el('span','',label+'：'+({queued:'等待识别',running:'识别中',complete:'已识别',partial:'待核对',empty:'未识别到内容',error:'识别失败'}[row.status]||'待识别')));
  if(row.error)line.append(el('p','',row.error));
  if(['error','empty'].includes(row.status))line.append(button('重新识别',()=>kind==='graph'?changeGraph(row,row.polygon,row.irregular):changeText(row,row.polygon,row.irregular)));
  line.append(button('删除'+label,()=>remove(row,kind)));return line;
 }
 function refresh(){
  if(destroyed)return;
  textSection.replaceChildren(el('h3','','文字信息'));
  const body=el('div','dgs-body',document.body_text||'暂无文字信息，可在左侧框选文字。');body.style.whiteSpace='pre-wrap';textSection.append(body);
  for(const row of state.textRegions)textSection.append(regionStatus(row,'text'));
  graphSection.replaceChildren(el('h3','','图形信息'));
  if(!document.graphs.length)graphSection.append(el('p','','暂无图形信息，可在左侧框选图形。'));
  document.graphs.forEach((graph,index)=>{
   const row=root.DMateGraphFormat.graphRows(graph,index),section=el('section','dgs-graph');
   section.append(el('h4','',row.title),el('p','',row.type),el('p','','顶点：'+(row.vertices.join('、')||'无')),
    el('p','',`${graph.vertices.length} 个顶点 · ${graph.edges.length} 条边`));
   section.append(el('p','dgs-appearance','图形外观：'+(row.description||'未提供外观描述。')));
   if(row.anonymousNote)section.append(el('p','dgs-anonymous-note',row.anonymousNote));
   if(row.positions.length){section.append(el('h5','','顶点位置'));for(const vertex of row.positions)section.append(el('p','dgs-vertex-position',vertex.txt));}
   if(row.named.length)section.append(el('p','','边：'+row.named.join('、')));
   for(const edge of row.relations)section.append(el('p','dgs-relation',edge.txt));graphSection.append(section);
  });
  for(const row of state.graphRegions)graphSection.append(regionStatus(row,'graph'));
  confirm.disabled=saving||pending();confirm.textContent=saving?'正在保存…':'保存';request.disabled=saving;
 }
 async function pumpGraphs(){
  if(graphBusy||destroyed)return;graphBusy=true;
  try{for(let row;(row=state.graphRegions.find(r=>r.status==='queued'))&&!destroyed;){
   const version=row.version,controller=new AbortController();row.controller=controller;active.add(controller);row.status='running';refresh();
   try{
    const result=await options.onRecognizeGraph(copy(row.polygon),{signal:controller.signal});
    if(destroyed||row.version!==version||!state.graphRegions.includes(row))continue;
    if(result.recognition_status==='failed')throw new Error(result.error||'图形识别未完成');
    row.graphs=withLabels({graphs:copy(result.document?.graphs||[])}).graphs.map((g,i)=>({...g,id:row.id+'_'+(i+1)}));
    row.status=row.graphs.length?'complete':'empty';row.error=result.warning||'';
    // Pending model doubts are retained in the read-only information panel.
    if(result.review?.required){row.status='partial';row.error=result.review.reasons?.join('；')||'局部识别仍有疑点，请对照原图核对。';}
   }catch(error){if(!destroyed&&row.version===version&&state.graphRegions.includes(row)){row.status='error';row.error=error?.message||'图形识别失败，请重试。';}}
   finally{active.delete(controller);if(!destroyed){assembleGraphs();emit();refresh();}}
  }}finally{graphBusy=false;}
 }
 async function pumpText(){
  if(textBusy||destroyed)return;textBusy=true;
  const rows=state.textRegions.filter(r=>r.status==='queued'),versions=rows.map(r=>r.version),controller=new AbortController();
  if(!rows.length){textBusy=false;return;}active.add(controller);rows.forEach(r=>{r.status='running';});refresh();
  try{
   const result=await options.onRecognizeText(rows.map(r=>({id:r.id,polygon:copy(r.polygon)})),{signal:controller.signal});
   const returned=new Map((result.regions||[]).map(r=>[r.id,r]));
   rows.forEach((row,i)=>{if(destroyed||row.version!==versions[i]||!state.textRegions.includes(row))return;
    const value=returned.get(row.id);if(!value)throw new Error('文字识别响应缺少选区');
    row.text=String(value.text||'');row.status=row.text.trim()?'complete':'empty';});
  }catch(error){rows.forEach((row,i)=>{if(!destroyed&&row.version===versions[i]&&state.textRegions.includes(row)){row.status='error';row.error=error?.message||'文字识别失败，请重试。';}});}
  finally{active.delete(controller);textBusy=false;if(!destroyed){assembleText();emit();refresh();if(state.textRegions.some(r=>r.status==='queued'))void pumpText();}}
 }
 const overlay=root.DMateGraphOverlay.mount(left,{
  scanOnly:true,originalUrl:options.originalUrl,state:overlayState,model:{getDocument:()=>({graphs:frames()})},
  graph:()=>({id:state.selectedGraphId,vertices:[],edges:[]}),disabled:()=>saving,
  createRegion:(points,irregular)=>{const row={id:'g'+state.nextGraph++,graphs:[]};state.graphRegions.push(row);state.selectedGraphId=row.id;changeGraph(row,points,irregular);return row.id;},
  resizeRegion:(id,points,irregular)=>{const row=state.graphRegions.find(r=>r.id===id);if(row)changeGraph(row,points,irregular);},
  selectGraph:id=>{state.selectedGraphId=id;},
  selectionChanged:(points,irregular)=>{if(!points)return;const row={id:state.nextText++};state.textRegions.push(row);changeText(row,points,irregular);},
  resizeTextRegion:(id,points)=>{const row=state.textRegions.find(r=>r.id===id);if(row)changeText(row,points,row.irregular);},
  selectTextRegion:id=>{overlayState.selectedId=id;},clearSelection:()=>{state.selectedGraphId=null;overlayState.selectedId=null;}
 });
 if(JSON.stringify(document)!==JSON.stringify(options.document||{body_text:'',graphs:[]}))emit();
 refresh();void pumpGraphs();if(state.textRegions.some(r=>r.status==='queued'))void pumpText();
 return {getDocument:()=>copy(document),destroy(){destroyed=true;clearTimeout(textTimer);for(const c of active)c.abort();overlay.destroy();container.replaceChildren();container.classList.remove('dmate-graph-editor','dmate-graph-scan');}};
}
root.DMateGraphScan={mount};
})(typeof window!=='undefined'?window:globalThis);
