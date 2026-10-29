(function(root){
 'use strict';
 const clone=v=>JSON.parse(JSON.stringify(v));
 const blank=()=>({body_text:'',graphs:[{id:'G1',name:'我的图形',directed:false,weighted:false,vertices:[],edges:[]}]});
 const id=()=>root.crypto?.randomUUID?.()||'drawing-'+Date.now()+'-'+Math.random().toString(36).slice(2);
 const goodDocument=v=>v&&typeof v==='object'&&Array.isArray(v.graphs)&&v.graphs.length>0&&v.graphs.every(g=>g&&typeof g==='object'&&Array.isArray(g.vertices)&&Array.isArray(g.edges));
 const caption=v=>String(v||'未命名绘图').trim().slice(0,80)||'未命名绘图';
 const fingerprint=v=>JSON.stringify(v);
 function mount(host,options={}){
  const doc=host.ownerDocument,win=doc.defaultView;
  if(!root.DMateGraphEditor?.mount)throw new Error('绘图模块未加载，请刷新后重试。');
  const key=String(options.storageKey||'dmate:graph-gallery:v1:guest');
  let pages=[],activeId='',editor=null,timer=null,destroyed=false,persistError='',aiAbort=null,aiEpoch=0,exportBusy=false,panelMode='',uploadBusy=false;
  let savedRaw='',legacyRead=false,exportPreview=null,exportPreviewUrl='',chromeFrame=0,observedView=null;
  const el=(tag,className,text)=>{const n=doc.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;};
  const button=(text,fn,className)=>{const b=el('button',className,text);b.type='button';b.addEventListener('click',event=>{event.stopPropagation();if(!destroyed)void fn();});return b;};
  const shell=el('section','dmate-drawing-workspace'),top=el('div','ddw-header'),name=el('input','ddw-name');
  name.type='text';name.maxLength=80;name.setAttribute('aria-label','绘图名称');
  const actions=el('div','ddw-page-actions'),body=el('div','ddw-body'),editorHost=el('div','ddw-editor'),rail=el('div','ddw-side-actions'),panel=el('aside','ddw-side-panel'),status=el('p','ddw-status');
  status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const settingsButton=button('绘图设置',()=>toggleEditorPanel('graphs')),informationButton=button('图形信息',()=>toggleEditorPanel('results'));
  const historyButton=button('历史绘图',()=>togglePanel('history')),aiButton=button('AI 回答',()=>togglePanel('ai'));
  rail.setAttribute('role','toolbar');rail.setAttribute('aria-label','绘图面板');
  settingsButton.setAttribute('aria-expanded','false');informationButton.setAttribute('aria-expanded','false');
  historyButton.setAttribute('aria-expanded','false');aiButton.setAttribute('aria-expanded','false');
  const newButton=button('新建空白页',()=>newPage()),exportButton=button('导出图片',()=>exportImage()),uploadButton=button('上传到对话',()=>uploadImage(),'ddw-primary');
  actions.append(newButton,exportButton,uploadButton);top.append(name,actions);rail.append(settingsButton,informationButton,historyButton,aiButton);body.append(editorHost,rail,panel);shell.append(top,body,status);host.replaceChildren(shell);host.classList.add('has-drawing-workspace');
  let requirement='',answer='',answerDocument='',answerRequirement='';
  const active=()=>pages.find(p=>p.id===activeId);
  function setStatus(message){status.textContent=message||persistError;status.classList.toggle('is-error',Boolean(persistError));}
  function abortAnswer(){aiEpoch++;aiAbort?.abort();aiAbort=null;}
  function invalidateAnswer(){
   abortAnswer();answer='';answerDocument='';answerRequirement='';
   const ask=panel.querySelector('[data-drawing-guide]');if(ask){ask.disabled=false;ask.textContent='请求 AI 指导';}
   const result=panel.querySelector('.ddw-ai-answer');if(result)result.replaceChildren();
  }
  function editorPanel(key){return editorHost.querySelector('.dge-float-panel[data-panel-key="'+key+'"]');}
  function closeEditorPanels(){for(const item of editorHost.querySelectorAll('.dge-floating-actions > details[open]'))item.querySelector(':scope > summary')?.click();}
  function toggleEditorPanel(key){
   editorHost.querySelector('.dge-selection-panel .dge-panel-close')?.click();panelMode='';renderPanel();
   editorPanel(key)?.querySelector(':scope > summary')?.click();syncChrome();
  }
  function syncChrome(){
   if(destroyed)return;
   const rack=editorHost.querySelector('.dge-floating-actions'),view=editorHost.querySelector('.dge-view-controls');
   if(resizeObserver&&observedView!==view){if(observedView)resizeObserver.unobserve(observedView);observedView=view;if(view)resizeObserver.observe(view);}
   for(const item of editorHost.querySelectorAll('.dge-float-panel')){
    const content=item.querySelector(':scope > .dge-float-content');
    if(content&&!content.querySelector(':scope > .ddw-editor-panel-header')){
     const head=el('div','ddw-editor-panel-header'),close=button('',()=>{if(item.open)item.querySelector(':scope > summary')?.click();syncChrome();},'ddw-panel-close');
     close.setAttribute('aria-label',item.dataset.panelKey==='graphs'?'关闭绘图设置':'关闭图形信息');close.title=close.getAttribute('aria-label');
     head.append(el('h3','',item.dataset.panelKey==='graphs'?'绘图设置':'图形信息'),close);content.prepend(head);
    }
   }
   const editorOpen=Boolean(editorHost.querySelector('.dge-floating-actions > details[open]'));
   const properties=editorHost.querySelector('.dge-selection-panel');
   const propertyOpen=Boolean(properties?.childElementCount);
   settingsButton.setAttribute('aria-expanded',String(Boolean(editorPanel('graphs')?.open)));
   informationButton.setAttribute('aria-expanded',String(Boolean(editorPanel('results')?.open)));
   rail.hidden=Boolean(panelMode||editorOpen||propertyOpen);
   shell.dataset.panelOpen=String(Boolean(panelMode||editorOpen||propertyOpen));
   const origin=body.getBoundingClientRect(),anchor=rack?.getBoundingClientRect(),viewBox=view?.getBoundingClientRect();
   const top=anchor?anchor.top-origin.top:(viewBox?viewBox.bottom-origin.top+10:64);
   body.style.setProperty('--ddw-panel-top',Math.max(8,top)+'px');
   body.style.setProperty('--ddw-panel-space',Math.max(90,origin.height-Math.max(8,top)-10)+'px');
  }
  function queueChrome(){if(!chromeFrame&&!destroyed)chromeFrame=win.requestAnimationFrame(()=>{chromeFrame=0;syncChrome();});}
  const chromeObserver=new win.MutationObserver(queueChrome);chromeObserver.observe(editorHost,{childList:true,subtree:true});
  const resizeObserver=typeof win.ResizeObserver==='function'?new win.ResizeObserver(queueChrome):null;resizeObserver?.observe(body);
  editorHost.addEventListener('toggle',queueChrome,true);
  editorHost.addEventListener('pointerdown',event=>{if(panelMode&&event.target.closest('.dge-overlay-node,.dge-overlay-edge,.dge-overlay-handle')){panelMode='';renderPanel();}},true);
  function currentDocument(){return editor?.getDocument?.()||active()?.document||blank();}
  function collect(){const p=active();if(!p)return;p.document=clone(currentDocument());p.name=caption(name.value);p.updatedAt=Date.now();}
  function persist(message){
   clearTimeout(timer);timer=null;if(destroyed)return false;
   const payload=JSON.stringify({version:1,activeId,pages});
   if(payload===savedRaw){if(message)setStatus(message);return true;}
   try{win.localStorage.setItem(key,payload);savedRaw=payload;persistError='';if(message)setStatus(message);else setStatus('已自动保存到此设备。');return true;}
   catch(_){persistError='此设备存储不足，当前绘图仍在本页保留；请导出图片后再关闭。';setStatus();return false;}
  }
  function schedule(){clearTimeout(timer);timer=win.setTimeout(()=>persist(),350);}
  function mountPage(){
   editor?.destroy();editor=null;const p=active();if(!p)return;
   name.value=p.name;requirement=p.requirement||'';answer='';answerDocument='';answerRequirement='';
   const initial=blank(),url='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="100%" height="100%" fill="white"/></svg>');
   editor=root.DMateGraphEditor.mount(editorHost,{document:clone(p.document),initialDocument:initial,originalUrl:url,drawingOnly:true,
    onChange:value=>{if(destroyed)return;const selected=active();if(!selected)return;selected.document=clone(value);selected.updatedAt=Date.now();options.onChange?.(clone(value));invalidateAnswer();schedule();},
    onConfirm:async value=>{const selected=active();selected.document=clone(value);selected.name=caption(name.value);selected.updatedAt=Date.now();if(!persist('绘图已保存到历史绘图。'))throw new Error(persistError);if(panelMode==='history')renderPanel();}
   });
   options.onChange?.(clone(p.document));renderPanel();syncChrome();
  }
  function switchPage(pageId){if(pageId===activeId)return;collect();persist();abortAnswer();activeId=pageId;persist();mountPage();setStatus('已打开绘图。');}
  function newPage(){
   if(pages.length>=50){setStatus('最多保留 50 张绘图，请先导出并删除不再需要的历史绘图。');return;}
   collect();persist();abortAnswer();const p={id:id(),name:'绘图 '+(pages.length+1),document:blank(),requirement:'',createdAt:Date.now(),updatedAt:Date.now()};pages.push(p);activeId=p.id;persist();mountPage();setStatus('已新建空白页。');
  }
  function togglePanel(mode){editorHost.querySelector('.dge-selection-panel .dge-panel-close')?.click();closeEditorPanels();panelMode=panelMode===mode?'':mode;renderPanel();syncChrome();}
  function renderPanel(){
   panel.hidden=!panelMode;panel.replaceChildren();historyButton.setAttribute('aria-expanded',String(panelMode==='history'));aiButton.setAttribute('aria-expanded',String(panelMode==='ai'));
   if(!panelMode){queueChrome();return;}
   const header=el('div','ddw-panel-header'),close=button('',()=>togglePanel(panelMode),'ddw-panel-close');close.setAttribute('aria-label',panelMode==='history'?'关闭历史绘图':'关闭 AI 回答');close.title=close.getAttribute('aria-label');header.append(el('h3','',panelMode==='history'?'历史绘图':'AI 回答'),close);panel.append(header);
   if(panelMode==='history'){
    const list=el('div','ddw-history-list');
    pages.slice().sort((a,b)=>b.updatedAt-a.updatedAt).forEach(p=>{
     const row=el('div','ddw-history-item'+(p.id===activeId?' is-current':'')),open=button(p.name,()=>switchPage(p.id),'ddw-history-open');
     open.setAttribute('aria-current',String(p.id===activeId));
     const stats=p.document.graphs.reduce((a,g)=>[a[0]+g.vertices.length,a[1]+g.edges.length],[0,0]);
     row.append(open,el('span','ddw-history-meta',stats[0]+' 点 · '+stats[1]+' 边'),button('删除',()=>removePage(p.id),'ddw-history-delete'));list.append(row);
    });panel.append(list);queueChrome();return;
   }
   const label=el('label','ddw-ai-label','要求（可选）'),input=el('textarea','ddw-ai-requirement');input.rows=3;input.maxLength=2000;input.value=requirement;input.setAttribute('aria-label','绘图指导要求（可选）');
   input.addEventListener('input',()=>{requirement=input.value;const p=active();if(p){p.requirement=requirement;p.updatedAt=Date.now();schedule();}invalidateAnswer();});label.append(input);
   const ask=button(aiAbort?'正在回答…':'请求 AI 指导',()=>requestGuide(),'ddw-primary');ask.disabled=Boolean(aiAbort);ask.dataset.drawingGuide='true';
   const result=el('div','ddw-ai-answer');result.setAttribute('aria-live','polite');
   panel.append(label,ask,result);
   if(answer){
    const renderedAnswer=answer,renderedPage=activeId,renderedRequirement=requirement;
    if(root.DMateAIAnswer?.render)root.DMateAIAnswer.render(result,answer,{isCurrent:()=>!destroyed&&panelMode==='ai'&&activeId===renderedPage&&answer===renderedAnswer&&requirement===renderedRequirement});
    else result.textContent=answer;
   }
   queueChrome();
  }
  function removePage(pageId){
   const index=pages.findIndex(p=>p.id===pageId);if(index<0)return;
   if(pageId===activeId){abortAnswer();editor?.destroy();editor=null;pages.splice(index,1);if(!pages.length)pages.push({id:id(),name:'绘图 1',document:blank(),requirement:'',createdAt:Date.now(),updatedAt:Date.now()});activeId=pages[Math.min(index,pages.length-1)].id;persist();mountPage();}
   else{pages.splice(index,1);persist();renderPanel();}
   setStatus('已删除历史绘图。');
  }
  async function requestGuide(){
   if(aiAbort||destroyed)return;collect();persist();
   const snapshot=clone(currentDocument()),snapshotKey=fingerprint(snapshot),request=requirement,selected=activeId,epoch=++aiEpoch;
   const controller=new win.AbortController();aiAbort=controller;answer='';renderPanel();setStatus('AI 正在根据当前绘图回答…');
   try{
    const response=await win.fetch('/drawing/guide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document:snapshot,requirement:request}),signal:controller.signal});
    let result;try{result=await response.json();}catch(_){throw new Error('AI 返回内容无效，请重试。');}
    if(!response.ok||result.ok!==true||typeof result.answer!=='string'||!result.answer.trim())throw new Error(result.error||'AI 指导暂时失败，请重试。');
    if(destroyed||epoch!==aiEpoch||activeId!==selected||fingerprint(currentDocument())!==snapshotKey||requirement!==request)return;
    answer=result.answer;answerDocument=snapshotKey;answerRequirement=request;setStatus('AI 回答已完成。');
   }catch(error){if(!destroyed&&epoch===aiEpoch&&error?.name!=='AbortError')setStatus(error?.message||'AI 指导失败，请重试。');}
   finally{if(epoch===aiEpoch){aiAbort=null;if(!destroyed)renderPanel();}}
  }
  async function makeImage(){
   if(!root.DMateDrawingExport?.pngBlob)throw new Error('导出模块未加载，请刷新后重试。');
   if(!currentDocument().graphs.some(g=>g.vertices.length))throw new Error('请先在空白页添加顶点和边。');
   const svg=editor?.getDrawingSvg?.(),document=root.DMateDrawingExport.documentForImage(currentDocument(),svg);
   return {blob:await root.DMateDrawingExport.pngBlob(svg),document};
  }
  function busy(value){exportBusy=value;const disabled=value||Boolean(exportPreview);exportButton.disabled=disabled;uploadButton.disabled=disabled;newButton.disabled=disabled;name.disabled=disabled;editorHost.inert=disabled;panel.inert=disabled;rail.inert=disabled;}
  function closeExportPreview(){
   exportPreview?.remove();exportPreview=null;
   if(exportPreviewUrl){win.URL.revokeObjectURL(exportPreviewUrl);exportPreviewUrl='';}
   if(!destroyed){busy(exportBusy);exportButton.focus({preventScroll:true});}
  }
  function showExportPreview(blob,pageName){
   closeExportPreview();exportPreviewUrl=win.URL.createObjectURL(blob);
   exportPreview=el('section','ddw-export-preview');exportPreview.setAttribute('role','dialog');exportPreview.setAttribute('aria-modal','true');exportPreview.setAttribute('aria-label','导出绘图');
   const header=el('div','ddw-export-header'),close=button('',closeExportPreview,'ddw-export-close');close.setAttribute('aria-label','关闭图片预览');
   header.append(el('h3','','导出绘图'),close);
   const image=el('img','ddw-export-image');image.src=exportPreviewUrl;image.alt=pageName+'，绘图导出图片';
   const link=el('a','ddw-export-download','下载图片');link.href=exportPreviewUrl;link.download=pageName.replace(/[\\/:*?"<>|]/g,'_').slice(0,100)+'.png';
   exportPreview.append(header,el('p','ddw-note','长按图片可保存，也可点击下载图片。'),image,link);shell.append(exportPreview);
   exportPreview.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeExportPreview();}
    if(event.key==='Tab'){event.preventDefault();(doc.activeElement===close?link:close).focus();}
   });busy(exportBusy);close.focus({preventScroll:true});
  }
  async function exportImage(){if(exportBusy)return;busy(true);try{collect();persist();const {blob}=await makeImage();if(destroyed)return;const metadata={name:caption(name.value)};let message='绘图 PNG 图片已生成。';if(typeof options.onExport==='function'){const result=await options.onExport(blob,metadata);if(result?.message)message=result.message;}else if(win.innerWidth<=760||win.matchMedia?.('(pointer: coarse)').matches)showExportPreview(blob,metadata.name);else root.DMateDrawingExport.download(blob,metadata.name,doc);setStatus(message);}catch(error){if(!destroyed)setStatus(error?.message||'图片导出失败。');}finally{if(!destroyed)busy(false);}}
  async function uploadImage(){
   if(exportBusy)return;busy(true);uploadBusy=true;
   try{if(typeof options.onUpload!=='function')throw new Error('上传功能未就绪，请刷新后重试。');collect();persist();const pageName=caption(name.value),requirements=requirement,{blob,document}=await makeImage();if(destroyed)return;await options.onUpload(blob,{name:pageName,document,requirements});if(!destroyed){setStatus('绘图已放入待发送图片。');options.onClose?.();}}
   catch(error){if(!destroyed)setStatus(error?.message||'绘图上传失败，请重试。');}
   finally{uploadBusy=false;if(!destroyed)busy(false);}
  }
  name.addEventListener('input',()=>{const p=active();if(p){p.name=caption(name.value);p.updatedAt=Date.now();schedule();}});
  try{
   const raw=win.localStorage.getItem(key),value=raw?JSON.parse(raw):null;
   if(value?.version===1&&Array.isArray(value.pages)){
    pages=value.pages.filter(p=>p&&typeof p.id==='string'&&goodDocument(p.document)).slice(0,50).map(p=>({...p,name:caption(p.name),requirement:String(p.requirement||'').slice(0,2000),updatedAt:Number(p.updatedAt)||0}));
    const ids=new Set();pages=pages.filter(p=>{if(ids.has(p.id))return false;ids.add(p.id);return true;});activeId=pages.some(p=>p.id===value.activeId)?value.activeId:pages[0]?.id||'';savedRaw=JSON.stringify({version:1,activeId,pages});
   }
  }catch(_){persistError='历史绘图暂时无法读取，当前绘图仍可编辑和导出。';}
  if(!pages.length){
   const legacy=goodDocument(options.legacyDocument)?clone(options.legacyDocument):null;
   pages=[{id:id(),name:legacy?'我的图形':'绘图 1',document:legacy||blank(),requirement:'',createdAt:Date.now(),updatedAt:Date.now()}];activeId=pages[0].id;legacyRead=Boolean(legacy);
  }
  // Older drawing documents could contain several subgraphs. Every graph
  // becomes its own accessible page now that subgraph management is removed.
  pages=pages.flatMap(p=>p.document.graphs.length===1?[p]:p.document.graphs.map((graph,index)=>({...p,id:index?id():p.id,
   name:caption(graph.name||p.name+' '+(index+1)),document:{...clone(p.document),graphs:[clone(graph)]}})));
  mountPage();persist();if(legacyRead)setStatus('已保留之前的绘图。');
  const pageHide=()=>{collect();persist();};win.addEventListener('pagehide',pageHide);
  return{getDocument:()=>clone(currentDocument()),getPages:()=>clone(pages),isBusy:()=>uploadBusy,
   destroy(){if(destroyed)return;collect();persist();destroyed=true;closeExportPreview();clearTimeout(timer);if(chromeFrame)win.cancelAnimationFrame(chromeFrame);chromeObserver.disconnect();resizeObserver?.disconnect();abortAnswer();win.removeEventListener('pagehide',pageHide);editor?.destroy();host.replaceChildren();host.classList.remove('has-drawing-workspace');}};
 }
 root.DMateDrawingWorkspace={mount,blankDocument:blank};
})(typeof window!=='undefined'?window:globalThis);
