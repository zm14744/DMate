(function(root){
'use strict';
const uiText=(source,english)=>root.DMateI18n?.t?.(source,english)??source;
const contentNode=node=>{node.setAttribute('data-i18n-content','');return node;};
const copy=value=>JSON.parse(JSON.stringify(value));
const LIMITS={notes:100,title:160,content:6000,total:180000,selected:12,analysis:24000};
function squarePenIcon(doc){
 const icon=doc.createElementNS('http://www.w3.org/2000/svg','svg');
 for(const [attribute,value] of Object.entries({class:'dmate-lucide-icon',viewBox:'0 0 24 24',width:20,height:20,fill:'none',stroke:'currentColor','stroke-width':1.8,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false','data-icon':'square-pen'}))icon.setAttribute(attribute,value);
 icon.innerHTML='<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M16 3a2.121 2.121 0 0 1 3 3l-9 9-4 1 1-4Z"/>';
 return icon;
}
function mount(options){
 const button=options.button,dialog=options.dialog;
 if(!button||!dialog)throw new Error(uiText('笔记本入口未加载。'));
 const d=dialog.ownerDocument,win=d.defaultView||root,transport=options.fetch||win.fetch.bind(win);
 const el=(tag,cls,text)=>{const n=d.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const action=(text,fn,cls='')=>{const b=el('button',cls,text);b.type='button';b.addEventListener('click',fn);return b;};
 let state={notes:[],deleted:{}},currentId=null,selected=new Set(),active=null,serial=0,destroyed=false,saveError=false,analysisComplete=false,loadedContext,deletePending=null,deletePrompt=null;
 const contextKey=()=>options.getContextKey?.()??'';
 const current=()=>state.notes.find(n=>n.id===currentId);
 const fingerprint=()=>JSON.stringify(state.notes.filter(n=>selected.has(n.id)).map(n=>({id:n.id,title:n.title,content:n.content})));
 const noteName=note=>note.title.trim()||uiText('未命名条目','Untitled entry');
 dialog.classList.add('dcn-dialog');dialog.setAttribute('aria-labelledby','conceptNotebookTitle');
 const heading=el('header','dcn-heading'),headingText=el('h2','','笔记本');headingText.id='conceptNotebookTitle';
 // Announce the notebook first instead of focusing the close button and
 // immediately displaying its tooltip. Tab still reaches every action.
 headingText.tabIndex=-1;headingText.autofocus=true;
 const closeButton=action('',close,'dcn-close');closeButton.title='关闭笔记本';closeButton.setAttribute('aria-label','关闭笔记本');heading.append(headingText,closeButton);
 const content=el('div','dcn-content'),sidebar=el('aside','dcn-sidebar'),main=el('section','dcn-main');
 sidebar.setAttribute('aria-label','概念笔记列表');
 const newButton=action('',create,'dcn-new'),search=el('input','dcn-search');
 newButton.title=uiText('新条目','New entry');newButton.setAttribute('aria-label',newButton.title);
 newButton.append(squarePenIcon(d),el('span','dmate-ui-label',newButton.title));search.type='search';search.setAttribute('aria-label','搜索');
 const searchWrap=el('div','dcn-search-wrap'),searchClear=action('',()=>{search.value='';renderList();search.focus({preventScroll:true});},'dcn-search-clear');
 searchClear.setAttribute('aria-label','清空搜索');searchClear.title='清空搜索';searchClear.hidden=true;searchWrap.append(search,searchClear);
 const list=el('div','dcn-list'),selection=el('div','dcn-selection'),count=el('span');
 const tools=el('div','dcn-tools'),toolsRight=el('div','dcn-tools-right');
 const relationButton=action('分析关联',toggleAnalysisPanel,'dcn-relation-trigger');
 relationButton.setAttribute('aria-haspopup','dialog');relationButton.setAttribute('aria-controls','conceptNotebookAnalysis');relationButton.setAttribute('aria-expanded','false');
 toolsRight.append(relationButton,searchWrap);tools.append(newButton,toolsRight);selection.append(count);sidebar.append(tools,selection,list);
 const editor=el('section','dcn-editor');
 const titleLabel=el('label','','条目名称'),title=el('textarea','dcn-title');title.maxLength=LIMITS.title;title.rows=1;title.setAttribute('aria-label','条目名称');titleLabel.append(title);
 const originalLabel=el('label','','条目内容'),original=el('textarea','dcn-original');original.maxLength=LIMITS.content;original.rows=1;original.setAttribute('aria-label','条目内容');originalLabel.append(original);
 const saved=el('span','dcn-saved');saved.setAttribute('role','status');editor.append(titleLabel,originalLabel,saved);
 const analysisPanel=el('div','dcn-analysis-panel');analysisPanel.id='conceptNotebookAnalysis';analysisPanel.hidden=true;
 analysisPanel.setAttribute('role','dialog');analysisPanel.setAttribute('aria-label','分析关联');
 const questionLabel=el('label','','分析要求（可选）'),question=el('textarea','dcn-question');question.maxLength=1000;question.rows=3;questionLabel.append(question);
 const controls=el('div','dcn-analysis-actions'),submitButton=action('',()=>void analyze(),'dcn-analysis-submit');
 submitButton.setAttribute('aria-label','提交分析');submitButton.title='提交分析';
 const sendIcon=d.createElementNS('http://www.w3.org/2000/svg','svg');
 sendIcon.setAttribute('viewBox','0 0 24 24');sendIcon.setAttribute('aria-hidden','true');
 sendIcon.innerHTML='<path d="M12 19V5m-6 6 6-6 6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
 submitButton.append(sendIcon);
 const cancelButton=action('',()=>{invalidate();submitButton.focus({preventScroll:true});},'dcn-close dcn-analysis-cancel');
 cancelButton.setAttribute('aria-label','取消分析');cancelButton.title='取消分析';
 const status=el('p','dcn-status'),result=el('div','dcn-results');status.setAttribute('role','status');result.setAttribute('aria-label','关联分析结果');result.setAttribute('role','region');result.tabIndex=-1;
 controls.append(submitButton,cancelButton);analysisPanel.append(questionLabel,controls,status,result);
 main.append(editor);content.append(sidebar,main);dialog.replaceChildren(heading,content,analysisPanel);
 const sheet=root.DMateNotebookSheet?.mount?.(dialog),sheetMedia=win.matchMedia?.('(max-width:760px)');
 const isMobile=()=>Boolean(sheet?.isMobile());
 const noteTrigger=identifier=>[...list.querySelectorAll('.dcn-note')].find(row=>row.dataset.noteId===identifier)?.querySelector('.dcn-note-open')||newButton;
 function openEditorSheet(isNew=false){
  if(!isMobile()||!current()||!dialog.open)return;
  sheet.open(editor,{label:isNew?uiText('新条目','New entry'):uiText('编辑条目','Edit entry'),
   returnFocus:isNew?newButton:()=>noteTrigger(currentId),initialFocus:isNew?title:undefined});
 }
 const analysisPanelSize=typeof win.ResizeObserver==='function'?new win.ResizeObserver(positionAnalysisPanel):null;
 function positionAnalysisPanel(){
  if(analysisPanel.hidden||isMobile()||sheet?.contains(analysisPanel))return;
  const viewport=win.visualViewport,frame=dialog.getBoundingClientRect(),anchor=relationButton.getBoundingClientRect();
  const left=Math.max(frame.left,viewport?.offsetLeft||0)+8,top=Math.max(frame.top,viewport?.offsetTop||0)+8;
  const right=Math.min(frame.right,(viewport?.offsetLeft||0)+(viewport?.width||win.innerWidth))-8;
  const bottom=Math.min(frame.bottom,(viewport?.offsetTop||0)+(viewport?.height||win.innerHeight))-8;
  const below=bottom-anchor.bottom-8,above=anchor.top-top-8,up=below<160&&above>below;
  analysisPanel.style.maxWidth=Math.max(1,right-left)+'px';
  analysisPanel.style.maxHeight=Math.max(1,Math.min(bottom-top,Math.max(120,up?above:below)))+'px';
  const {width,height}=analysisPanel.getBoundingClientRect();
  analysisPanel.style.left=Math.max(left,Math.min(anchor.left,right-width))+'px';
  analysisPanel.style.top=Math.max(top,Math.min(up?anchor.top-8-height:anchor.bottom+8,bottom-height))+'px';
 }
 function finishAnalysisPanel(){
  analysisPanel.hidden=true;analysisPanel.setAttribute('role','dialog');relationButton.setAttribute('aria-expanded','false');
  analysisPanelSize?.disconnect();
  win.removeEventListener('resize',positionAnalysisPanel);
  win.visualViewport?.removeEventListener('resize',positionAnalysisPanel);
  win.visualViewport?.removeEventListener('scroll',positionAnalysisPanel);
 }
 function hideAnalysisPanel(restoreFocus=false){
  const wasOpen=!analysisPanel.hidden,inSheet=sheet?.contains(analysisPanel);
  finishAnalysisPanel();
  if(inSheet){sheet.close({restoreFocus});return;}
  if(wasOpen&&restoreFocus)relationButton.focus({preventScroll:true});
 }
 function toggleAnalysisPanel(){
  if(relationButton.disabled)return;
  if(!analysisPanel.hidden){if(!sheet?.expand())hideAnalysisPanel(true);return;}
  if(!active)invalidate();
  analysisPanel.hidden=false;relationButton.setAttribute('aria-expanded','true');
  if(isMobile()){
   for(const property of ['left','top','max-width','max-height'])analysisPanel.style.removeProperty(property);
   analysisPanel.setAttribute('role','group');
   sheet.open(analysisPanel,{label:uiText('分析关联','Analyze relationships'),returnFocus:relationButton,onClose:finishAnalysisPanel});
   return;
  }
  positionAnalysisPanel();
  analysisPanelSize?.observe(analysisPanel);
  win.addEventListener('resize',positionAnalysisPanel);
  win.visualViewport?.addEventListener('resize',positionAnalysisPanel);
  win.visualViewport?.addEventListener('scroll',positionAnalysisPanel);
  question.focus({preventScroll:true});
 }
 function load(){
  const key=contextKey();if(key!==loadedContext){currentId=null;selected.clear();question.value='';search.value='';saveError=false;saved.textContent='';loadedContext=key;}
  const source=copy(options.getState?.()||{notes:[],deleted:{}});
  state={notes:Array.isArray(source.notes)?source.notes:[],deleted:source.deleted&&typeof source.deleted==='object'?source.deleted:{}};
  state.notes=state.notes.filter(n=>n&&typeof n.id==='string'&&typeof n.title==='string'&&typeof n.content==='string');
  selected=new Set([...selected].filter(id=>state.notes.some(n=>n.id===id)));
  if(!current())currentId=state.notes[0]?.id||null;
 }
 function persist(){
  try{options.onChange?.(copy(state));win.dispatchEvent(new Event('dmate:notebook-viewchange'));saveError=false;saved.textContent='';return true;}
  catch(error){saveError=true;saved.textContent=error?.message||'保存失败，请保留当前页面后重试。';return false;}
 }
 function invalidate(){
  deletePrompt?.finish(false);deletePending=null;serial++;active?.controller.abort();active=null;analysisComplete=false;result.replaceChildren();status.textContent='';renderActions();
 }
 function renderActions(){
  const focused=d.activeElement,focusResult=analysisComplete&&(questionLabel.contains(focused)||controls.contains(focused));
  const focusAction=focused===submitButton&&!!active||focused===cancelButton&&!active;
  const empty=state.notes.length===0;dialog.classList.toggle('is-empty',empty);selection.hidden=empty;relationButton.hidden=empty&&!isMobile();
  const size=selected.size;count.textContent=uiText('已选 '+size+' 条',size+' selected');
  questionLabel.hidden=analysisComplete;controls.hidden=analysisComplete;
  relationButton.disabled=size<2;submitButton.disabled=Boolean(active)||size<2;cancelButton.hidden=!active;
  submitButton.setAttribute('aria-busy',String(Boolean(active)));
  if(relationButton.disabled)hideAnalysisPanel();
  newButton.disabled=state.notes.length>=LIMITS.notes;
  for(const remove of list.querySelectorAll('.dcn-note-delete'))remove.disabled=!!deletePending;
  if(!analysisPanel.hidden){if(focusResult)result.focus({preventScroll:true});else if(focusAction&&!analysisComplete)(active?cancelButton:submitButton).focus({preventScroll:true});}
 }
 function renderList(){
  const query=search.value.trim().toLocaleLowerCase();searchClear.hidden=!search.value;list.replaceChildren();
  const visible=state.notes.filter(note=>(note.title+'\n'+note.content).toLocaleLowerCase().includes(query));
  if(!visible.length)list.append(el('p','dcn-list-empty',state.notes.length?uiText('无','None'):uiText('暂无条目','No entries yet')));
  const names=new Map();for(const note of state.notes)names.set(noteName(note),(names.get(noteName(note))||0)+1);
  for(const note of visible){
   const row=el('div','dcn-note'+(note.id===currentId?' is-current':''));row.dataset.noteId=note.id;
   const name=noteName(note);
   const hit=el('label','dcn-note-select'),check=el('input');check.type='checkbox';check.checked=selected.has(note.id);check.setAttribute('aria-label',uiText('选择概念：'+name,'Select concept: '+name));hit.append(check);
   check.addEventListener('change',()=>{if(check.checked)selected.add(note.id);else selected.delete(note.id);invalidate();renderActions();});
   const openNote=action(name,()=>{currentId=note.id;renderList();renderEditor();renderActions();openEditorSheet();},'dcn-note-open');
   const remove=action('',event=>{event.stopPropagation();void removeNote(note.id);},'dcn-note-delete');
   remove.disabled=!!deletePending;remove.title=uiText('删除概念','Delete concept');
   const duplicate=names.get(name)>1?'（'+note.id+'）':'';
   remove.setAttribute('aria-label',uiText('删除概念：'+name,'Delete concept: '+name)+duplicate);
   if(note.title.trim())contentNode(openNote);
   openNote.setAttribute('aria-current',String(note.id===currentId));row.append(hit,openNote,remove);list.append(row);
  }
 }
 function renderEditor(){
  const note=current();editor.hidden=!note;
  if(note){title.value=note.title;original.value=note.content;}
  else{title.value='';original.value='';if(!saveError)saved.textContent='';}
 }
 function updatedAt(note){return Math.max(Date.now(),Number(note?.updatedAt||0)+1);}
 function create(){
  if(state.notes.length>=LIMITS.notes)return;
  const id=win.crypto?.randomUUID?.()||'concept-'+Date.now()+'-'+Math.random().toString(36).slice(2);
  const note={id,title:'',content:'',updatedAt:Date.now()};state.notes.unshift(note);currentId=id;search.value='';
  invalidate();persist();renderList();renderEditor();renderActions();
  if(isMobile())openEditorSheet(true);else title.focus({preventScroll:true});
 }
 function edit(field,value){
  const note=current();if(!note)return;
  const previousTotal=state.notes.reduce((sum,n)=>sum+n.title.length+n.content.length,0),total=previousTotal-note[field].length+value.length;
  if(total>LIMITS.total&&total>=previousTotal){saved.textContent='笔记总内容已达上限，请精简后继续。';(field==='title'?title:original).value=note[field];return;}
  note[field]=value;note.updatedAt=updatedAt(note);invalidate();persist();renderList();
 }
 function askToDelete(){
  const title='删除这个概念？',bodyText='删除后，笔记内容将不可恢复';
  const settings={title,body:bodyText,confirmText:'删除概念',cancelText:'取消',confirmTone:'danger',fallbackText:uiText(title)+'\n\n'+uiText(bodyText)};
  if(typeof options.confirmDelete==='function')return options.confirmDelete(settings);
  return new Promise(resolve=>{
   const prompt=el('dialog','dcn-confirm'),head=el('header','dcn-confirm-head'),heading=el('h3','',settings.title);
   heading.id='conceptNotebookDeleteTitle';prompt.setAttribute('aria-labelledby',heading.id);
   const finish=value=>{if(deletePrompt?.node!==prompt)return;deletePrompt=null;if(prompt.open)prompt.close();prompt.remove();resolve(Boolean(value));};
   const cancel=action('',()=>finish(false),'dcn-close');cancel.setAttribute('aria-label','取消删除');cancel.title='取消删除';head.append(heading,cancel);
   const body=el('p','dcn-confirm-body',uiText(bodyText)),actions=el('footer','dcn-confirm-actions');
   actions.append(action(settings.confirmText,()=>finish(true),'dcn-confirm-delete'));
   prompt.append(head,body,actions);dialog.append(prompt);deletePrompt={node:prompt,finish};
   prompt.addEventListener('cancel',event=>{event.preventDefault();finish(false);});prompt.addEventListener('close',()=>finish(false));
   // Closing on pointerdown cannot consume the click that opened the prompt.
   prompt.addEventListener('pointerdown',event=>{if(event.target===prompt){const box=prompt.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)finish(false);}});
   prompt.showModal();cancel.focus({preventScroll:true});
  });
 }
 async function removeNote(identifier){
  const note=state.notes.find(item=>item.id===identifier);if(!note||deletePending)return;
  const op={context:contextKey(),id:note.id,note:JSON.stringify(note)};deletePending=op;renderActions();
  try{
   const confirmed=await askToDelete();
   const currentNote=state.notes.find(item=>item.id===op.id);
   if(!confirmed||destroyed||!dialog.open||deletePending!==op||op.context!==contextKey()||JSON.stringify(currentNote)!==op.note)return;
   const index=state.notes.findIndex(item=>item.id===op.id);
   state.deleted[note.id]=updatedAt(note);state.notes=state.notes.filter(n=>n.id!==note.id);selected.delete(note.id);
   if(currentId===note.id)currentId=state.notes[Math.min(index,state.notes.length-1)]?.id||null;
   invalidate();persist();renderList();renderEditor();renderActions();
  }catch(error){if(deletePending===op)status.textContent=error?.message||'无法确认删除，请重试。';}
  finally{if(deletePending===op)deletePending=null;if(!destroyed){renderEditor();renderActions();}}
 }
 function validateReply(data,notes){
  if(data?.ok!==true||!Array.isArray(data.relations))throw new Error(uiText('AI 返回的概念分析不完整，请重试。'));
  const ids=new Set(notes.map(n=>n.id));
  if(!data.relations.every(row=>row&&ids.has(row.from)&&ids.has(row.to)&&row.from!==row.to&&typeof row.explanation==='string'&&row.explanation.trim()))throw new Error(uiText('AI 返回了未选中概念的关联，请重试。'));
 }
 function showResult(data,notes){
  const names=new Map(notes.map(note=>[note.id,noteName(note)])),version=serial,key=contextKey(),source=fingerprint();result.replaceChildren();
  const isCurrent=()=>!destroyed&&dialog.open&&serial===version&&contextKey()===key&&fingerprint()===source;
  const rich=text=>{const node=contentNode(el('div','dcn-ai-text'));if(root.DMateAIAnswer?.render)void root.DMateAIAnswer.render(node,text,{typography:'inline',isCurrent});else node.textContent=text;return node;};
  for(const row of data.relations){const from=names.get(row.from),to=names.get(row.to),section=el('section','dcn-relation');section.append(contentNode(el('strong','',uiText(from+'与'+to,from+' and '+to))),rich(row.explanation));result.append(section);}
  if(!data.relations.length)result.append(el('p','',uiText('没有得到可确认的直接关联','No confirmed direct relationships found')));
 }
 async function analyze(){
  if(active||analysisPanel.hidden||analysisComplete)return;
  const notes=state.notes.filter(n=>selected.has(n.id)).map(n=>({id:n.id,title:n.title,content:n.content}));
  if(notes.length<2||notes.length>LIMITS.selected){status.textContent='每次请选择 2 至 12 条条目';return;}
  if(notes.some(n=>!n.title.trim()&&!n.content.trim())){status.textContent='请先完善所选条目';return;}
  if(notes.reduce((sum,n)=>sum+n.title.length+n.content.length,0)>LIMITS.analysis){status.textContent='所选概念内容过长，请减少选择后分析。';return;}
  if(!persist()){status.textContent='笔记尚未保存，请先解决保存错误后再分析。';return;}
  const op={id:++serial,controller:new AbortController(),fingerprint:fingerprint(),context:contextKey()};active=op;
  const valid=()=>!destroyed&&active===op&&serial===op.id&&dialog.open&&op.context===contextKey()&&op.fingerprint===fingerprint();
  result.replaceChildren();status.textContent='';renderActions();
  const timeout=setTimeout(()=>op.controller.abort(),85000);
  try{
   const response=await transport(options.endpoint||'/notebook/analyze',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},signal:op.controller.signal,
    body:JSON.stringify({action:'relations',notes,question:question.value.trim(),language:root.DMateI18n?.getLanguage?.()||d.documentElement.lang||'zh-CN'})});
   let data;try{data=await response.json();}catch(_){throw new Error(uiText('概念分析响应异常，请重试。'));}
   if(!valid())return;
   if(!response.ok||data?.ok!==true)throw new Error(typeof data?.error==='string'?data.error:'概念分析失败，请重试。');
   validateReply(data,notes);if(data.action!=='relations')throw new Error(uiText('概念分析任务不匹配，请重试。'));
   showResult(data,notes);options.onResults?.(result);if(!valid())return;analysisComplete=true;status.textContent='';renderActions();
   if(!analysisPanel.hidden){positionAnalysisPanel();analysisPanel.scrollTop=0;const body=analysisPanel.closest('.dcn-sheet-body');if(body)body.scrollTop=0;}
  }catch(error){if(valid())status.textContent=error?.name==='AbortError'?'概念分析超时，请重试。':error?.message||'概念分析失败，请重试。';}
  finally{clearTimeout(timeout);if(active===op){active=null;if(!destroyed)renderActions();}}
 }
 function open(){if(destroyed)return;sheet?.close();hideAnalysisPanel();invalidate();load();saveError=false;saved.textContent='';search.value='';renderList();renderEditor();renderActions();options.onOpen?.();if(!dialog.open)dialog.showModal();}
 function close(){if(saveError&&!persist())return;sheet?.close();hideAnalysisPanel();invalidate();if(dialog.open)dialog.close();}
 function refresh(){if(destroyed)return;sheet?.close();hideAnalysisPanel();invalidate();load();renderList();renderEditor();renderActions();}
 const onClose=event=>{if(event.target!==dialog)return;sheet?.close();hideAnalysisPanel();invalidate();};
 const onCancel=event=>{if(event.target!==dialog)return;if(sheet?.contains(editor)||sheet?.contains(analysisPanel)){event.preventDefault();sheet.close({restoreFocus:true});return;}if(!analysisPanel.hidden){event.preventDefault();hideAnalysisPanel(true);return;}if(saveError&&!persist()){event.preventDefault();return;}invalidate();};
 const onKeyDown=event=>{if(event.key!=='Escape'||event.isComposing||isMobile()||analysisPanel.hidden||event.target.closest?.('dialog')!==dialog)return;event.preventDefault();event.stopPropagation();hideAnalysisPanel(true);};
 const onPointerDown=event=>{if(isMobile()||sheet?.contains(editor)||sheet?.contains(analysisPanel))return;if(!analysisPanel.contains(event.target)&&!relationButton.contains(event.target))hideAnalysisPanel();};
 const onBreakpointChange=()=>{if(destroyed)return;sheet?.close();hideAnalysisPanel();renderActions();};
 sheetMedia?.addEventListener('change',onBreakpointChange);
 title.addEventListener('input',()=>edit('title',title.value));original.addEventListener('input',()=>edit('content',original.value));
 question.addEventListener('input',()=>invalidate());search.addEventListener('input',renderList);button.addEventListener('click',open);dialog.addEventListener('close',onClose);dialog.addEventListener('cancel',onCancel);dialog.addEventListener('keydown',onKeyDown,true);dialog.addEventListener('pointerdown',onPointerDown);
 const viewChange=()=>queueMicrotask(()=>win.dispatchEvent(new Event('dmate:notebook-viewchange')));
 for(const type of ['input','change','click'])dialog.addEventListener(type,viewChange);
 return {open,close,refresh,getState:()=>copy(state),getViewState:()=>({currentId,selected:[...selected],search:search.value,question:question.value}),restoreViewState(value){
  if(!value||typeof value!=='object')return;const previous=JSON.stringify([loadedContext,state.notes,[...selected].sort()]);load();
  if(state.notes.some(note=>note.id===value.currentId))currentId=value.currentId;
  selected=new Set((Array.isArray(value.selected)?value.selected:[]).filter(id=>state.notes.some(note=>note.id===id)));
  search.value=typeof value.search==='string'?value.search:'';question.value=typeof value.question==='string'?value.question:'';
  if(previous!==JSON.stringify([loadedContext,state.notes,[...selected].sort()]))invalidate();
  renderList();renderEditor();renderActions();
 },destroy(){if(destroyed)return;sheet?.close();hideAnalysisPanel();invalidate();destroyed=true;sheetMedia?.removeEventListener('change',onBreakpointChange);sheet?.destroy();button.removeEventListener('click',open);dialog.removeEventListener('close',onClose);dialog.removeEventListener('cancel',onCancel);dialog.removeEventListener('keydown',onKeyDown,true);dialog.removeEventListener('pointerdown',onPointerDown);for(const type of ['input','change','click'])dialog.removeEventListener(type,viewChange);if(dialog.open)dialog.close();dialog.replaceChildren();}};
}
root.DMateConceptNotebook={mount};
})(typeof window!=='undefined'?window:globalThis);
