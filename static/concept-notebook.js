(function(root){
'use strict';
const copy=value=>JSON.parse(JSON.stringify(value));
const LIMITS={notes:100,title:160,content:6000,total:180000,selected:12,analysis:24000};
function mount(options){
 const button=options.button,dialog=options.dialog;
 if(!button||!dialog)throw new Error('笔记本入口未加载。');
 const d=dialog.ownerDocument,win=d.defaultView||root,transport=options.fetch||win.fetch.bind(win);
 const el=(tag,cls,text)=>{const n=d.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const action=(text,fn,cls='')=>{const b=el('button',cls,text);b.type='button';b.addEventListener('click',fn);return b;};
 let state={notes:[],deleted:{}},currentId=null,selected=new Set(),active=null,serial=0,destroyed=false,lastDeleted=null,saveError=false,loadedContext;
 const contextKey=()=>options.getContextKey?.()??'';
 const current=()=>state.notes.find(n=>n.id===currentId);
 const fingerprint=()=>JSON.stringify(state.notes.filter(n=>selected.has(n.id)).map(n=>({id:n.id,title:n.title,content:n.content})));
 const noteName=note=>note.title.trim()||'未命名概念';
 dialog.classList.add('dcn-dialog');dialog.setAttribute('aria-labelledby','conceptNotebookTitle');
 const heading=el('header','dcn-heading'),headingText=el('h2','','笔记本');headingText.id='conceptNotebookTitle';
 const closeButton=action('关闭',close,'dcn-close');closeButton.setAttribute('aria-label','关闭笔记本');heading.append(headingText,closeButton);
 const persistenceHint=el('p','dcn-persistence');
 const persistent=()=>options.isPersistent?Boolean(options.isPersistent()):true;
 const content=el('div','dcn-content'),sidebar=el('aside','dcn-sidebar'),main=el('section','dcn-main');
 sidebar.setAttribute('aria-label','概念笔记列表');
 const newButton=action('新建概念',create,'dcn-primary'),search=el('input','dcn-search');search.type='search';search.placeholder='搜索概念';search.setAttribute('aria-label','搜索概念');
 const list=el('div','dcn-list'),selection=el('div','dcn-selection'),count=el('span'),clearSelection=action('取消选择',()=>{selected.clear();invalidate();renderList();renderActions();});
 selection.append(count,clearSelection);sidebar.append(newButton,search,selection,list);
 const editor=el('section','dcn-editor'),empty=el('p','dcn-empty','记下概念的定义、例子或疑问，再选择笔记让 AI 解释或分析关联。');
 const titleLabel=el('label','','概念名称'),title=el('input','dcn-title');title.maxLength=LIMITS.title;title.setAttribute('aria-label','概念名称');titleLabel.append(title);
 const originalLabel=el('label','','我的概念笔记'),original=el('textarea','dcn-original');original.maxLength=LIMITS.content;original.rows=9;original.setAttribute('aria-label','我的概念笔记');originalLabel.append(original);
 const editorFoot=el('div','dcn-editor-foot'),saved=el('span','dcn-saved','输入后自动保存'),removeButton=action('删除概念',remove,'dcn-remove'),undoButton=action('撤销删除',undo);
 saved.setAttribute('role','status');undoButton.hidden=true;editorFoot.append(saved,removeButton,undoButton);editor.append(titleLabel,originalLabel,editorFoot);
 const ai=el('section','dcn-ai'),aiTitle=el('h3','','AI 阅读'),scope=el('p','dcn-scope','AI 只读取勾选的概念，解释和关联不会改写你的原文。');
 const questionLabel=el('label','','补充要求（可选）'),question=el('textarea','dcn-question');question.maxLength=1000;question.rows=2;question.setAttribute('aria-label','补充要求（可选）');questionLabel.append(question);
 const controls=el('div','dcn-ai-actions'),explainButton=action('AI 解释',()=>void analyze('explain'),'dcn-primary'),relationButton=action('分析关联',()=>void analyze('relations')),cancelButton=action('取消分析',()=>invalidate('已取消分析。'));
 const status=el('p','dcn-status'),result=el('div','dcn-results');status.setAttribute('role','status');result.setAttribute('aria-label','AI 解释与概念关联');
 controls.append(explainButton,relationButton,cancelButton);ai.append(aiTitle,scope,questionLabel,controls,status,result);main.append(empty,editor,ai);content.append(sidebar,main);dialog.replaceChildren(heading,persistenceHint,content);
 function load(){
  const key=contextKey();if(key!==loadedContext){currentId=null;selected.clear();question.value='';search.value='';lastDeleted=null;saveError=false;saved.textContent=persistent()?'输入后自动保存':'输入后自动保留在当前页面';loadedContext=key;}
  persistenceHint.textContent=persistent()?'笔记随账号保存并同步。':'未登录时笔记仅保留在当前页面；登录后可保存并同步。';
  const source=copy(options.getState?.()||{notes:[],deleted:{}});
  state={notes:Array.isArray(source.notes)?source.notes:[],deleted:source.deleted&&typeof source.deleted==='object'?source.deleted:{}};
  state.notes=state.notes.filter(n=>n&&typeof n.id==='string'&&typeof n.title==='string'&&typeof n.content==='string');
  selected=new Set([...selected].filter(id=>state.notes.some(n=>n.id===id)));
  if(!current())currentId=state.notes[0]?.id||null;
  if(!selected.size&&currentId)selected.add(currentId);
 }
 function persist(){
  try{options.onChange?.(copy(state));saveError=false;saved.textContent=persistent()?'已保存':'已保留在当前页面';return true;}
  catch(error){saveError=true;saved.textContent=error?.message||'保存失败，请保留当前页面后重试。';return false;}
 }
 function invalidate(message=''){
  serial++;active?.controller.abort();active=null;result.replaceChildren();status.textContent=message;renderActions();
 }
 function renderActions(){
  const size=selected.size;count.textContent='已选 '+size+' 条';
  clearSelection.disabled=!size;explainButton.disabled=!!active||size===0;relationButton.disabled=!!active||size<2;cancelButton.hidden=!active;
  newButton.disabled=state.notes.length>=LIMITS.notes;
 }
 function renderList(){
  const query=search.value.trim().toLocaleLowerCase();list.replaceChildren();
  const visible=state.notes.filter(note=>(note.title+'\n'+note.content).toLocaleLowerCase().includes(query));
  if(!visible.length)list.append(el('p','dcn-list-empty',state.notes.length?'没有匹配的概念。':'还没有概念笔记。'));
  for(const note of visible){
   const row=el('div','dcn-note'+(note.id===currentId?' is-current':''));row.dataset.noteId=note.id;
   const check=el('input');check.type='checkbox';check.checked=selected.has(note.id);check.setAttribute('aria-label','选择概念：'+noteName(note));
   check.addEventListener('change',()=>{if(check.checked)selected.add(note.id);else selected.delete(note.id);invalidate();renderActions();});
   const openNote=action(noteName(note),()=>{currentId=note.id;if(!selected.size)selected.add(note.id);renderList();renderEditor();renderActions();},'dcn-note-open');
   openNote.setAttribute('aria-current',String(note.id===currentId));row.append(check,openNote);list.append(row);
  }
 }
 function renderEditor(){
  const note=current();empty.hidden=!!note;editor.hidden=!note;
  if(note){title.value=note.title;original.value=note.content;}
  else{title.value='';original.value='';if(!saveError)saved.textContent=persistent()?'输入后自动保存':'输入后自动保留在当前页面';}
  removeButton.disabled=!note;undoButton.hidden=!lastDeleted;
 }
 function updatedAt(note){return Math.max(Date.now(),Number(note?.updatedAt||0)+1);}
 function create(){
  if(state.notes.length>=LIMITS.notes)return;
  const id=win.crypto?.randomUUID?.()||'concept-'+Date.now()+'-'+Math.random().toString(36).slice(2);
  const note={id,title:'',content:'',updatedAt:Date.now()};state.notes.unshift(note);currentId=id;selected=new Set([id]);search.value='';
  invalidate();persist();renderList();renderEditor();renderActions();title.focus({preventScroll:true});
 }
 function edit(field,value){
  const note=current();if(!note)return;
  const previousTotal=state.notes.reduce((sum,n)=>sum+n.title.length+n.content.length,0),total=previousTotal-note[field].length+value.length;
  if(total>LIMITS.total&&total>=previousTotal){saved.textContent='笔记总内容已达上限，请精简后继续。';(field==='title'?title:original).value=note[field];return;}
  note[field]=value;note.updatedAt=updatedAt(note);invalidate();persist();renderList();
 }
 function remove(){
  const note=current();if(!note)return;lastDeleted=copy(note);
  state.deleted[note.id]=updatedAt(note);state.notes=state.notes.filter(n=>n.id!==note.id);selected.delete(note.id);currentId=state.notes[0]?.id||null;
  invalidate();persist();renderList();renderEditor();renderActions();
 }
 function undo(){
  if(!lastDeleted||state.notes.length>=LIMITS.notes)return;
  const note=lastDeleted;note.updatedAt=Math.max(updatedAt(note),Number(state.deleted[note.id]||0)+1);
  delete state.deleted[note.id];state.notes.unshift(note);lastDeleted=null;currentId=note.id;selected=new Set([note.id]);
  invalidate();persist();renderList();renderEditor();renderActions();
 }
 function validateReply(data,notes){
  if(data?.ok!==true||!Array.isArray(data.explanations)||!Array.isArray(data.relations)||typeof data.summary!=='string')throw new Error('AI 返回的概念分析不完整，请重试。');
  const ids=new Set(notes.map(n=>n.id));
  if(!data.explanations.every(row=>row&&ids.has(row.note_id)&&typeof row.explanation==='string')||
   !data.relations.every(row=>row&&ids.has(row.from)&&ids.has(row.to)&&row.from!==row.to&&typeof row.type==='string'&&typeof row.explanation==='string'))throw new Error('AI 返回了未选中概念的关联，请重试。');
 }
 function showResult(data,notes){
  const names=new Map(notes.map(n=>[n.id,n.title.trim()||'未命名概念']));result.replaceChildren();
  if(data.summary)result.append(el('p','dcn-summary',data.summary));
  for(const row of data.explanations){const section=el('section','dcn-explanation');section.append(el('h4','',names.get(row.note_id)),el('div','dcn-ai-text',row.explanation));result.append(section);}
  if(data.relations.length){result.append(el('h4','','概念之间的关联'));for(const row of data.relations){const section=el('section','dcn-relation');section.append(el('strong','',names.get(row.from)+' → '+names.get(row.to)+' · '+row.type),el('p','dcn-ai-text',row.explanation));result.append(section);}}
  else if(active?.action==='relations')result.append(el('p','','没有得到可确认的直接关联。'));
 }
 async function analyze(kind){
  if(active)return;
  const notes=state.notes.filter(n=>selected.has(n.id)).map(n=>({id:n.id,title:n.title,content:n.content}));
  if(!notes.length||notes.length>LIMITS.selected){status.textContent='每次请选择1至12条概念。';return;}
  if(kind==='relations'&&notes.length<2){status.textContent='请选择至少两条概念分析关联。';return;}
  if(notes.some(n=>!n.title.trim()&&!n.content.trim())){status.textContent='请先写下所选概念的名称或内容。';return;}
  if(notes.reduce((sum,n)=>sum+n.title.length+n.content.length,0)>LIMITS.analysis){status.textContent='所选概念内容过长，请减少选择后分析。';return;}
  if(!persist()){status.textContent='笔记尚未保存，请先解决保存错误后再分析。';return;}
  const op={id:++serial,controller:new AbortController(),fingerprint:fingerprint(),context:contextKey(),action:kind};active=op;
  const valid=()=>!destroyed&&active===op&&serial===op.id&&dialog.open&&op.context===contextKey()&&op.fingerprint===fingerprint();
  result.replaceChildren();status.textContent=kind==='relations'?'正在分析所选概念的关联…':'正在解释所选概念…';renderActions();
  const timeout=setTimeout(()=>op.controller.abort(),85000);
  try{
   const response=await transport(options.endpoint||'/notebook/analyze',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},signal:op.controller.signal,
    body:JSON.stringify({action:kind,notes,question:question.value.trim()})});
   let data;try{data=await response.json();}catch(_){throw new Error('概念分析响应异常，请重试。');}
   if(!valid())return;
   if(!response.ok||data?.ok!==true)throw new Error(typeof data?.error==='string'?data.error:'概念分析失败，请重试。');
   validateReply(data,notes);if(data.action!==kind)throw new Error('概念分析任务不匹配，请重试。');
   showResult(data,notes);options.onResults?.(result);status.textContent='分析完成 · AI 解释仅供核对，原文保持不变。';
   result.scrollIntoView({block:'nearest'});
  }catch(error){if(valid())status.textContent=error?.name==='AbortError'?'概念分析超时，请重试。':error?.message||'概念分析失败，请重试。';}
  finally{clearTimeout(timeout);if(active===op){active=null;if(!destroyed)renderActions();}}
 }
 function open(){if(destroyed)return;invalidate();load();saveError=false;saved.textContent=persistent()?'输入后自动保存':'输入后自动保留在当前页面';lastDeleted=null;search.value='';renderList();renderEditor();renderActions();options.onOpen?.();if(!dialog.open)dialog.showModal();}
 function close(){if(saveError&&!persist())return;invalidate();if(dialog.open)dialog.close();}
 function refresh(){if(destroyed)return;invalidate();load();lastDeleted=null;renderList();renderEditor();renderActions();}
 const onClose=()=>invalidate();
 const onCancel=event=>{if(saveError&&!persist()){event.preventDefault();return;}invalidate();};
 title.addEventListener('input',()=>edit('title',title.value));original.addEventListener('input',()=>edit('content',original.value));
 question.addEventListener('input',()=>invalidate());search.addEventListener('input',renderList);button.addEventListener('click',open);dialog.addEventListener('close',onClose);dialog.addEventListener('cancel',onCancel);
 return {open,close,refresh,getState:()=>copy(state),destroy(){if(destroyed)return;invalidate();destroyed=true;button.removeEventListener('click',open);dialog.removeEventListener('close',onClose);dialog.removeEventListener('cancel',onCancel);if(dialog.open)dialog.close();dialog.replaceChildren();}};
}
root.DMateConceptNotebook={mount};
})(typeof window!=='undefined'?window:globalThis);
