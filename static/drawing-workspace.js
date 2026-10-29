(function(root){
 'use strict';
 const clone=v=>JSON.parse(JSON.stringify(v));
 const blank=(name='我的图形')=>({body_text:'',graphs:[{id:'G1',name,directed:false,weighted:false,vertices:[],edges:[]}]});
 const emptyDocument=()=>({body_text:'',graphs:[]});
 const id=()=>root.crypto?.randomUUID?.()||'drawing-'+Date.now()+'-'+Math.random().toString(36).slice(2);
 const goodDocument=v=>v&&typeof v==='object'&&Array.isArray(v.graphs)&&v.graphs.length>0&&v.graphs.every(g=>g&&typeof g==='object'&&Array.isArray(g.vertices)&&Array.isArray(g.edges));
 const meaningfulDocument=v=>goodDocument(v)&&(String(v.body_text||'').trim()||v.graphs.some(g=>g.vertices.length||g.edges.length||String(g.name||'').trim()&&!['我的图形','图 1','图1'].includes(String(g.name).trim())));
 const caption=v=>String(v||'未命名绘图').trim().slice(0,80)||'未命名绘图';
 const fingerprint=v=>JSON.stringify(v);
 function mount(host,options={}){
  const doc=host.ownerDocument,win=doc.defaultView;
  if(!root.DMateGraphEditor?.mount)throw new Error('绘图模块未加载，请刷新后重试。');
  const key=String(options.storageKey||'dmate:graph-gallery:v1:guest');
  let pages=[],activeId='',editor=null,timer=null,destroyed=false,persistError='',aiAbort=null,aiEpoch=0,exportBusy=false,panelMode='',uploadBusy=false;
  let savedRaw='',restoredGallery=false,exportPreview=null,exportPreviewUrl='',chromeFrame=0,observedView=null,observedViewport=null,observedPalette=null,toolsExpanded=false,deletePending=null;
  const el=(tag,className,text)=>{const n=doc.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;};
  const button=(text,fn,className)=>{const b=el('button',className,text);b.type='button';b.addEventListener('click',event=>{event.stopPropagation();if(!destroyed)void fn();});return b;};
  const sendIcon=()=>{const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg'),path=doc.createElementNS(svg.namespaceURI,'path');
   svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
   for(const [key,value] of Object.entries({d:'M12 20V4m-7 7 7-7 7 7',fill:'none',stroke:'#fff','stroke-width':'2.4','stroke-linecap':'round','stroke-linejoin':'round'}))path.setAttribute(key,value);svg.append(path);return svg;};
  const shell=el('section','dmate-drawing-workspace'),top=el('div','ddw-header'),name=el('input','ddw-name');
  name.type='text';name.maxLength=80;name.setAttribute('aria-label','绘图名称');
  const actions=el('div','ddw-page-actions'),body=el('div','ddw-body'),editorHost=el('div','ddw-editor'),rail=el('div','ddw-side-actions'),panel=el('aside','ddw-side-panel'),status=el('p','ddw-status');
  status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const settingsButton=button('绘图设置',()=>toggleEditorPanel('graphs')),informationButton=button('图形信息',()=>toggleEditorPanel('results'));
  const historyButton=button('历史绘图',()=>togglePanel('history')),aiButton=button('AI指导',()=>togglePanel('ai'));
  rail.setAttribute('role','toolbar');rail.setAttribute('aria-label','绘图面板');
  settingsButton.setAttribute('aria-expanded','false');informationButton.setAttribute('aria-expanded','false');
  historyButton.setAttribute('aria-expanded','false');aiButton.setAttribute('aria-expanded','false');
  const newButton=button('新建空白页',()=>newPage()),exportButton=button('导出图片',()=>exportImage()),uploadButton=button('上传',()=>uploadImage(),'ddw-primary ddw-upload-button');
  uploadButton.setAttribute('aria-label','上传');uploadButton.title='上传';
  actions.append(newButton,historyButton,exportButton,uploadButton);top.append(name,actions);rail.append(settingsButton,informationButton,aiButton);body.append(editorHost,rail);shell.append(top,body,panel,status);host.replaceChildren(shell);host.classList.add('has-drawing-workspace');
  let requirement='',answer='',answerDocument='',answerRequirement='',nameFollowsGraph=false;
  const active=()=>pages.find(p=>p.id===activeId);
  function setStatus(message){status.textContent=message||persistError;status.classList.toggle('is-error',Boolean(status.textContent));}
  function abortAnswer(){aiEpoch++;aiAbort?.abort();aiAbort=null;}
  function invalidateAnswer(){
   abortAnswer();answer='';answerDocument='';answerRequirement='';
   const ask=panel.querySelector('[data-drawing-guide]');if(ask){ask.disabled=false;ask.setAttribute('aria-busy','false');}
   const result=panel.querySelector('.ddw-ai-answer');if(result)result.replaceChildren();
  }
  function editorPanel(key){return editorHost.querySelector('.dge-float-panel[data-panel-key="'+key+'"]');}
  function closeEditorPanels(){for(const item of editorHost.querySelectorAll('.dge-floating-actions > details[open]'))item.querySelector(':scope > summary')?.click();}
  function closeTools(){toolsExpanded=false;const palette=editorHost.querySelector('.dge-tool-palette');if(palette)palette.open=false;}
  function dismissPanels(){closeTools();closeEditorPanels();panelMode='';renderPanel();syncChrome();}
  function toggleTools(){if(!active()){newPage();if(!active())return;}const next=!toolsExpanded;editorHost.querySelector('.dge-selection-panel .dge-panel-close')?.click();closeEditorPanels();panelMode='';renderPanel();toolsExpanded=next;syncChrome();}
  function toggleEditorPanel(key){
   if(!active())return;
   closeTools();editorHost.querySelector('.dge-selection-panel .dge-panel-close')?.click();panelMode='';renderPanel();
   editorPanel(key)?.querySelector(':scope > summary')?.click();syncChrome();
  }
  function positionPopover(content,trigger,alignLeft=false){
   if(!content||!trigger)return;
   content.style.visibility='hidden';
   const viewport=win.visualViewport,margin=8,gap=8,leftEdge=(viewport?.offsetLeft||0)+margin,topEdge=(viewport?.offsetTop||0)+margin;
   const rightEdge=leftEdge+(viewport?.width||win.innerWidth)-2*margin,bottomEdge=topEdge+(viewport?.height||win.innerHeight)-2*margin;
   const anchor=trigger.getBoundingClientRect(),below=bottomEdge-anchor.bottom-gap,above=anchor.top-gap-topEdge;
   const upwards=below<120&&above>below,space=Math.max(40,upwards?above:below);
   content.style.maxHeight=space+'px';content.style.maxWidth=Math.max(40,rightEdge-leftEdge)+'px';
   const box=content.getBoundingClientRect(),left=Math.max(leftEdge,Math.min(alignLeft?anchor.left:anchor.right-box.width,rightEdge-box.width));
   const top=Math.max(topEdge,Math.min(upwards?anchor.top-gap-box.height:anchor.bottom+gap,bottomEdge-box.height));
   content.style.left=left+'px';content.style.right='auto';content.style.top=top+'px';content.style.visibility='visible';
  }
  function syncCanvasClip(viewport=observedViewport){
   const stage=viewport?.querySelector(':scope > .dge-overlay-stage');
   if(!stage||!viewport.clientWidth||!viewport.clientHeight)return;
   // The native scrollbar gutters sit outside the white canvas. Rounding the
   // scroll container alone leaves three of its visible content corners square.
   // Clip the source and drawing together at the stationary client rectangle;
   // this changes neither camera coordinates nor the exported SVG.
   const canvas=viewport.getBoundingClientRect(),bounds=stage.getBoundingClientRect(),style=win.getComputedStyle(stage);
   const scaleX=bounds.width/parseFloat(style.width)||1,scaleY=bounds.height/parseFloat(style.height)||1;
   const left=canvas.left+viewport.clientLeft*scaleX,top=canvas.top+viewport.clientTop*scaleY;
   const right=left+viewport.clientWidth*scaleX,bottom=top+viewport.clientHeight*scaleY;
   const insets=[(top-bounds.top)/scaleY,(bounds.right-right)/scaleX,(bounds.bottom-bottom)/scaleY,(left-bounds.left)/scaleX];
   stage.style.clipPath='inset('+insets.map(value=>Math.max(0,value)+'px').join(' ')+' round 12px)';
  }
  const canvasScrolled=event=>{syncCanvasClip(event.currentTarget);queueChrome();};
  function syncChrome(){
   if(destroyed)return;
   const view=editorHost.querySelector('.dge-view-controls'),viewport=editorHost.querySelector('.dge-overlay-viewport'),palette=editorHost.querySelector('.dge-tool-palette');
   if(resizeObserver&&observedView!==view){if(observedView)resizeObserver.unobserve(observedView);observedView=view;if(view)resizeObserver.observe(view);}
   if(observedViewport!==viewport){
    if(observedViewport){resizeObserver?.unobserve(observedViewport);observedViewport.removeEventListener('scroll',canvasScrolled);}
    observedViewport=viewport;
    if(viewport){resizeObserver?.observe(viewport);viewport.addEventListener('scroll',canvasScrolled,{passive:true});}
   }
   syncCanvasClip(viewport);
   if(palette&&observedPalette!==palette){
    observedPalette=palette;const trigger=palette.querySelector(':scope > summary');
    trigger?.setAttribute('aria-label','绘图工具');trigger?.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();toggleTools();});
   }
   const empty=!active(),disabled=exportBusy||Boolean(exportPreview);name.disabled=empty||disabled;editorHost.inert=disabled;rail.inert=empty||disabled;
   if(viewport)viewport.inert=empty;
   settingsButton.disabled=empty||disabled;informationButton.disabled=empty||disabled;aiButton.disabled=empty||disabled;shell.classList.toggle('is-empty',empty);
   if(palette){palette.open=toolsExpanded&&!empty;const trigger=palette.querySelector(':scope > summary');trigger?.setAttribute('aria-expanded',String(palette.open));trigger?.setAttribute('aria-disabled',String(disabled));}
   for(const item of editorHost.querySelectorAll('.dge-float-panel')){
    const content=item.querySelector(':scope > .dge-float-content');
    if(content&&!content.querySelector(':scope > .ddw-editor-panel-header')){
     const head=el('div','ddw-editor-panel-header');head.append(el('h3','',item.dataset.panelKey==='graphs'?'绘图设置':'图形信息'));content.prepend(head);
    }
   }
   const editorOpen=Boolean(editorHost.querySelector('.dge-floating-actions > details[open]'));
   const properties=editorHost.querySelector('.dge-selection-panel');
   const propertyOpen=Boolean(properties?.childElementCount);
   settingsButton.setAttribute('aria-expanded',String(Boolean(editorPanel('graphs')?.open)));
   informationButton.setAttribute('aria-expanded',String(Boolean(editorPanel('results')?.open)));
   shell.dataset.panelOpen=String(Boolean(panelMode||editorOpen||propertyOpen||toolsExpanded));
   const origin=body.getBoundingClientRect(),viewBox=view?.getBoundingClientRect(),canvasBox=viewport?.getBoundingClientRect(),inset=18;
   const controlsTop=Math.max(origin.top+inset,viewBox?viewBox.bottom+inset:origin.top+64);
   const canvasStyle=viewport?win.getComputedStyle(viewport):null,borderLeft=parseFloat(canvasStyle?.borderLeftWidth)||0,borderRight=parseFloat(canvasStyle?.borderRightWidth)||0;
   const leftSpace=viewport?viewport.clientLeft:borderLeft,rightSpace=viewport?Math.max(borderRight,viewport.offsetWidth-viewport.clientWidth-leftSpace):borderRight;
   const canvasRight=canvasBox?canvasBox.right-rightSpace:origin.right,canvasLeft=canvasBox?canvasBox.left+leftSpace:origin.left;
   rail.style.right=Math.max(inset,origin.right-canvasRight+inset)+'px';rail.style.top=(controlsTop-origin.top)+'px';
   body.style.setProperty('--ddw-controls-top',(controlsTop-origin.top)+'px');
   if(palette){const parent=palette.offsetParent?.getBoundingClientRect()||origin;palette.style.top=(controlsTop-parent.top)+'px';palette.style.left=(canvasLeft+inset-parent.left)+'px';}
   const toolBox=palette?.querySelector(':scope > summary')?.getBoundingClientRect();
   if(toolBox&&rail.getBoundingClientRect().left<toolBox.right+12)rail.style.top=(toolBox.bottom-origin.top+12)+'px';
   const top=Math.max(rail.getBoundingClientRect().bottom,toolBox?.bottom||0)-origin.top+8;
   body.style.setProperty('--ddw-panel-top',top+'px');
   body.style.setProperty('--ddw-panel-space',Math.max(90,origin.height-top-10)+'px');
   if(panelMode)positionPopover(panel,panelMode==='history'?historyButton:aiButton);
   for(const [key,trigger] of [['graphs',settingsButton],['results',informationButton]]){const item=editorPanel(key);if(item?.open)positionPopover(item.querySelector(':scope > .dge-float-content'),trigger);}
   if(palette?.open)positionPopover(palette.querySelector(':scope > .dge-overlay-tools'),palette.querySelector(':scope > summary'),true);
  }
  function queueChrome(){if(!chromeFrame&&!destroyed)chromeFrame=win.requestAnimationFrame(()=>{chromeFrame=0;syncChrome();});}
  const chromeObserver=new win.MutationObserver(queueChrome);chromeObserver.observe(editorHost,{childList:true,subtree:true});
  const resizeObserver=typeof win.ResizeObserver==='function'?new win.ResizeObserver(queueChrome):null;resizeObserver?.observe(body);
  editorHost.addEventListener('toggle',queueChrome,true);
  editorHost.addEventListener('pointerdown',event=>{if(panelMode&&event.target.closest('.dge-overlay-node,.dge-overlay-edge,.dge-overlay-handle')){panelMode='';renderPanel();}},true);
  const outsidePointer=event=>{
   if(destroyed||exportPreview||deletePending||!event.target?.closest)return;
   if(!panelMode&&!toolsExpanded&&!editorHost.querySelector('.dge-floating-actions > details[open]'))return;
   if(event.target.closest('.ddw-side-actions,.ddw-side-panel,.dge-float-content,.dge-tool-palette')||historyButton.contains(event.target))return;
   dismissPanels();
  };
  const escapeKey=event=>{
   if(event.key!=='Escape'||exportPreview||deletePending||(!panelMode&&!toolsExpanded&&!editorHost.querySelector('.dge-floating-actions > details[open]')))return;
   event.preventDefault();event.stopPropagation();const focus=panelMode==='history'?historyButton:panelMode==='ai'?aiButton:editorPanel('graphs')?.open?settingsButton:editorPanel('results')?.open?informationButton:editorHost.querySelector('.dge-tool-palette > summary');
   dismissPanels();focus?.focus({preventScroll:true});
  };
  doc.addEventListener('pointerdown',outsidePointer,true);doc.addEventListener('keydown',escapeKey,true);
  win.addEventListener('resize',queueChrome);doc.addEventListener('scroll',queueChrome,true);win.visualViewport?.addEventListener('resize',queueChrome);win.visualViewport?.addEventListener('scroll',queueChrome);
  function currentDocument(){return editor?.getDocument?.()||active()?.document||emptyDocument();}
  function collect(){const p=active();if(!p)return;p.document=clone(currentDocument());p.name=caption(name.value);p.updatedAt=Date.now();}
  function persist(){
   clearTimeout(timer);timer=null;if(destroyed)return false;
   const payload=JSON.stringify({version:2,activeId,pages});
   if(payload===savedRaw)return true;
   try{win.localStorage.setItem(key,payload);savedRaw=payload;persistError='';setStatus('');return true;}
   catch(_){persistError='此设备存储不足，当前绘图仍在本页保留；请导出图片后再关闭。';setStatus();return false;}
  }
  function schedule(){clearTimeout(timer);timer=win.setTimeout(()=>persist(),350);}
  function mountPage(){
   editor?.destroy();editor=null;const p=active(),documentValue=p?.document||emptyDocument();
   name.value=p?.name||'';nameFollowsGraph=false;requirement=p?.requirement||'';answer='';answerDocument='';answerRequirement='';
   const initial=p?blank(p.name):emptyDocument(),url='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="100%" height="100%" fill="white"/></svg>');
   editor=root.DMateGraphEditor.mount(editorHost,{document:clone(documentValue),initialDocument:initial,originalUrl:url,drawingOnly:true,
    onChange:value=>{if(destroyed)return;const selected=active();if(!selected)return;selected.document=clone(value);selected.updatedAt=Date.now();
     if(nameFollowsGraph&&doc.activeElement!==name&&value.graphs[0]){selected.name=caption(value.graphs[0].name);name.value=selected.name;}
     options.onChange?.(clone(value));invalidateAnswer();schedule();},
    onConfirm:async value=>{const selected=active();if(!selected)return;selected.document=clone(value);selected.name=caption(name.value);selected.updatedAt=Date.now();if(!persist())throw new Error(persistError);if(panelMode==='history')renderPanel();}
   });
   options.onChange?.(clone(documentValue));renderPanel();syncChrome();
  }
  function switchPage(pageId){if(pageId===activeId||!pages.some(p=>p.id===pageId))return;cancelDelete();collect();persist();abortAnswer();activeId=pageId;persist();mountPage();setStatus('');}
  function newPage(){
   if(pages.length>=50){setStatus('最多保留 50 张绘图，请先导出并删除不再需要的历史绘图。');return;}
   cancelDelete();collect();persist();abortAnswer();const pageName='绘图 '+(pages.length+1),p={id:id(),name:pageName,document:blank(pageName),requirement:'',createdAt:Date.now(),updatedAt:Date.now()};pages.push(p);activeId=p.id;persist();mountPage();setStatus('');
  }
  function togglePanel(mode){if(mode==='ai'&&!active())return;closeTools();editorHost.querySelector('.dge-selection-panel .dge-panel-close')?.click();closeEditorPanels();panelMode=panelMode===mode?'':mode;renderPanel();syncChrome();}
  function renderPanel(){
   panel.style.visibility='hidden';panel.hidden=!panelMode;panel.replaceChildren();historyButton.setAttribute('aria-expanded',String(panelMode==='history'));aiButton.setAttribute('aria-expanded',String(panelMode==='ai'));
   if(!panelMode){queueChrome();return;}
   const header=el('div','ddw-panel-header');header.append(el('h3','',panelMode==='history'?'历史绘图':'AI指导'));panel.append(header);
   if(panelMode==='history'){
    const list=el('div','ddw-history-list');
    pages.slice().sort((a,b)=>b.updatedAt-a.updatedAt).forEach(p=>{
     const row=el('div','ddw-history-item'+(p.id===activeId?' is-current':'')),open=button(p.name,()=>switchPage(p.id),'ddw-history-open');
     open.setAttribute('aria-current',String(p.id===activeId));
     const remove=button('',()=>requestRemovePage(p.id,remove),'ddw-history-delete');remove.setAttribute('aria-label','删除绘图：'+p.name+'（'+p.id+'）');remove.title='删除'+p.name;remove.disabled=Boolean(deletePending);
     row.append(open,remove);list.append(row);
    });if(!pages.length)list.append(el('p','ddw-history-empty','无'));panel.append(list);syncChrome();return;
   }
   const label=el('label','ddw-ai-label','要求（可选）'),input=el('textarea','ddw-ai-requirement');input.rows=3;input.maxLength=2000;input.value=requirement;input.setAttribute('aria-label','绘图指导要求（可选）');
   input.addEventListener('input',()=>{requirement=input.value;const p=active();if(p){p.requirement=requirement;p.updatedAt=Date.now();schedule();}invalidateAnswer();});label.append(input);
   const ask=button('',()=>requestGuide(),'ddw-guide-button');ask.append(sendIcon());ask.disabled=Boolean(aiAbort);ask.dataset.drawingGuide='true';ask.setAttribute('aria-label','请求 AI 指导');ask.title='请求 AI 指导';ask.setAttribute('aria-busy',String(Boolean(aiAbort)));
   const result=el('div','ddw-ai-answer');result.setAttribute('aria-live','polite');
   panel.append(label,ask,result);
   if(answer){
    const renderedAnswer=answer,renderedPage=activeId,renderedRequirement=requirement;
    if(root.DMateAIAnswer?.render)root.DMateAIAnswer.render(result,answer,{isCurrent:()=>!destroyed&&panelMode==='ai'&&activeId===renderedPage&&answer===renderedAnswer&&requirement===renderedRequirement});
    else result.textContent=answer;
   }
   syncChrome();
  }
  function syncDeleteButtons(){for(const control of panel.querySelectorAll('.ddw-history-delete'))control.disabled=Boolean(deletePending);}
  function cancelDelete(){deletePending=null;root.DMateDeleteConfirm?.cancel(shell);syncDeleteButtons();}
  function deletionSnapshot(page){return fingerprint({...page,document:page.id===activeId?currentDocument():page.document});}
  async function requestRemovePage(pageId,trigger){
   const page=pages.find(item=>item.id===pageId);if(!page||deletePending||destroyed)return;
   const op={id:pageId,page,activeId,snapshot:deletionSnapshot(page),trigger};deletePending=op;
   const settings={title:'删除这个绘图？',body:'删除后无法恢复。\n'+page.name,confirmText:'删除绘图',confirmTone:'danger'};
   try{
    if(typeof options.confirmDelete!=='function'&&typeof root.DMateDeleteConfirm?.request!=='function')throw new Error('删除确认界面未加载，请刷新后重试。');
    const confirmation=typeof options.confirmDelete==='function'?options.confirmDelete(settings):root.DMateDeleteConfirm?.request(shell,settings);
    syncDeleteButtons();const confirmed=await confirmation;
    const current=pages.find(item=>item.id===op.id);
    if(!confirmed||destroyed||deletePending!==op||activeId!==op.activeId||current!==op.page||deletionSnapshot(current)!==op.snapshot)return;
    removePage(op.id);
   }catch(error){if(!destroyed&&deletePending===op)setStatus(error?.message||'无法确认删除，请重试。');}
   finally{if(deletePending===op){deletePending=null;if(!destroyed){syncDeleteButtons();(trigger?.isConnected?trigger:historyButton).focus({preventScroll:true});}}}
  }
  function removePage(pageId){
   const index=pages.findIndex(p=>p.id===pageId);if(index<0)return;
   if(pageId===activeId){abortAnswer();editor?.destroy();editor=null;pages.splice(index,1);activeId=pages[Math.min(index,pages.length-1)]?.id||'';persist();mountPage();}
   else{collect();pages.splice(index,1);persist();renderPanel();}
   setStatus('');
  }
  async function requestGuide(){
   if(aiAbort||destroyed||!active())return;collect();persist();
   const snapshot=clone(currentDocument()),snapshotKey=fingerprint(snapshot),request=requirement,selected=activeId,epoch=++aiEpoch;
   const controller=new win.AbortController();aiAbort=controller;answer='';renderPanel();setStatus('');
   try{
    const response=await win.fetch('/drawing/guide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document:snapshot,requirement:request}),signal:controller.signal});
    let result;try{result=await response.json();}catch(_){throw new Error('AI 返回内容无效，请重试。');}
    if(!response.ok||result.ok!==true||typeof result.answer!=='string'||!result.answer.trim())throw new Error(result.error||'AI 指导暂时失败，请重试。');
    if(destroyed||epoch!==aiEpoch||activeId!==selected||fingerprint(currentDocument())!==snapshotKey||requirement!==request)return;
    answer=result.answer;answerDocument=snapshotKey;answerRequirement=request;setStatus('');
   }catch(error){if(!destroyed&&epoch===aiEpoch&&error?.name!=='AbortError')setStatus(error?.message||'AI 指导失败，请重试。');}
   finally{if(epoch===aiEpoch){aiAbort=null;if(!destroyed)renderPanel();}}
  }
  async function makeImage(){
   if(!active())throw new Error('请先新建空白页。');
   if(!root.DMateDrawingExport?.pngBlob)throw new Error('导出模块未加载，请刷新后重试。');
   if(!currentDocument().graphs.some(g=>g.vertices.length))throw new Error('请先在空白页添加顶点和边。');
   const svg=editor?.getDrawingSvg?.(),document=root.DMateDrawingExport.documentForImage(currentDocument(),svg);
   return {blob:await root.DMateDrawingExport.pngBlob(svg),document};
  }
  function busy(value){exportBusy=value;const disabled=value||Boolean(exportPreview);exportButton.disabled=disabled;uploadButton.disabled=disabled;newButton.disabled=disabled;historyButton.disabled=disabled;panel.inert=disabled;syncChrome();}
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
   exportPreview.append(header,image,link);shell.append(exportPreview);
   exportPreview.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeExportPreview();}
    if(event.key==='Tab'){event.preventDefault();(doc.activeElement===close?link:close).focus();}
   });busy(exportBusy);close.focus({preventScroll:true});
  }
  async function exportImage(){if(exportBusy)return;busy(true);try{collect();persist();const {blob}=await makeImage();if(destroyed)return;const metadata={name:caption(name.value)};if(typeof options.onExport==='function')await options.onExport(blob,metadata);else if(win.innerWidth<=760||win.matchMedia?.('(pointer: coarse)').matches)showExportPreview(blob,metadata.name);else root.DMateDrawingExport.download(blob,metadata.name,doc);setStatus('');}catch(error){if(!destroyed)setStatus(error?.message||'图片导出失败。');}finally{if(!destroyed)busy(false);}}
  async function uploadImage(){
   if(exportBusy)return;busy(true);uploadBusy=true;
   try{if(typeof options.onUpload!=='function')throw new Error('上传功能未就绪，请刷新后重试。');collect();persist();const pageName=caption(name.value),requirements=requirement,{blob,document}=await makeImage();if(destroyed)return;await options.onUpload(blob,{name:pageName,document,requirements});if(!destroyed){setStatus('');options.onClose?.();}}
   catch(error){if(!destroyed)setStatus(error?.message||'绘图上传失败，请重试。');}
   finally{uploadBusy=false;if(!destroyed)busy(false);}
  }
  name.addEventListener('input',()=>{const p=active();if(p){nameFollowsGraph=true;p.name=caption(name.value);p.updatedAt=Date.now();
   const graph=editor?.getDocument?.().graphs[0];
   if(graph&&graph.name!==p.name){editor.model?.renameGraph(graph.id,p.name);editor.refresh?.();}
   schedule();}});
  try{
   const raw=win.localStorage.getItem(key),value=raw?JSON.parse(raw):null;
   if((value?.version===1||value?.version===2)&&Array.isArray(value.pages)){
    restoredGallery=true;
    pages=value.pages.filter(p=>p&&typeof p.id==='string'&&goodDocument(p.document)).slice(0,50).map(p=>({...p,name:caption(p.name),requirement:String(p.requirement||'').slice(0,2000),updatedAt:Number(p.updatedAt)||0}));
    const ids=new Set();pages=pages.filter(p=>{if(ids.has(p.id))return false;ids.add(p.id);return true;});activeId=pages.some(p=>p.id===value.activeId)?value.activeId:pages[0]?.id||'';savedRaw=JSON.stringify({version:value.version,activeId,pages});
   }
  }catch(_){persistError='历史绘图暂时无法读取，当前绘图仍可编辑和导出。';}
  if(!restoredGallery){
   const legacy=meaningfulDocument(options.legacyDocument)?clone(options.legacyDocument):null;
   if(legacy){pages=[{id:id(),name:'我的图形',document:legacy,requirement:'',createdAt:Date.now(),updatedAt:Date.now()}];activeId=pages[0].id;}
  }
  // Older blank pages kept the generic graph title after receiving a page number.
  if(restoredGallery)for(const p of pages)if(/^绘图\s*\d+$/.test(p.name)&&p.document.graphs.length===1&&p.document.graphs[0].name==='我的图形')p.document.graphs[0].name=p.name;
  // Older drawing documents could contain several subgraphs. Every graph
  // becomes its own accessible page now that subgraph management is removed.
  pages=pages.flatMap(p=>p.document.graphs.length===1?[p]:p.document.graphs.map((graph,index)=>({...p,id:index?id():p.id,
   name:caption(graph.name||p.name+' '+(index+1)),document:{...clone(p.document),graphs:[clone(graph)]}})));
  mountPage();persist();
  const pageHide=()=>{collect();persist();};win.addEventListener('pagehide',pageHide);
  return{getDocument:()=>clone(currentDocument()),getPages:()=>clone(pages),isBusy:()=>uploadBusy,
   destroy(){if(destroyed)return;collect();persist();destroyed=true;cancelDelete();closeExportPreview();clearTimeout(timer);if(chromeFrame)win.cancelAnimationFrame(chromeFrame);chromeObserver.disconnect();resizeObserver?.disconnect();observedViewport?.removeEventListener('scroll',canvasScrolled);abortAnswer();doc.removeEventListener('pointerdown',outsidePointer,true);doc.removeEventListener('keydown',escapeKey,true);doc.removeEventListener('scroll',queueChrome,true);win.removeEventListener('resize',queueChrome);win.visualViewport?.removeEventListener('resize',queueChrome);win.visualViewport?.removeEventListener('scroll',queueChrome);win.removeEventListener('pagehide',pageHide);editor?.destroy();host.replaceChildren();host.classList.remove('has-drawing-workspace');}};
 }
 root.DMateDrawingWorkspace={mount,blankDocument:blank};
})(typeof window!=='undefined'?window:globalThis);
