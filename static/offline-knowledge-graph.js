/* Local-only knowledge graph. Drawing geometry, DOM classes and mobile
 * interactions match the online graph; session and video UI is omitted. */
(function(root){
'use strict';
const dmateUiText=(source,english)=>root.DMateI18n?.t(source,english)??source;
const dmateUiLanguage=()=>root.DMateI18n?.getLanguage()||'zh-CN';
const dmateKnowledgeLabel=name=>dmateUiText(String(name||''));
function createSvgElement(tag, attrs = {}) {
    const element = document.createElementNS(
        "http://www.w3.org/2000/svg",
        tag
    );

    for (const [key, value] of Object.entries(attrs)) {
        if (
            value !== undefined
            && value !== null
        ) {
            element.setAttribute(
                key,
                String(value)
            );
        }
    }

    return element;
}

function computeKnowledgeGraphLevels(nodes) {
    const byName = new Map(
        nodes.map(node => [node.name, node])
    );
    const memo = new Map();
    const visiting = new Set();

    function depth(node) {
        if (memo.has(node.id)) {
            return memo.get(node.id);
        }

        if (visiting.has(node.id)) {
            return 0;
        }

        visiting.add(node.id);

        let value = 0;

        for (const prerequisite of node.prerequisites) {
            const previous = byName.get(prerequisite);

            if (previous) {
                value = Math.max(
                    value,
                    depth(previous) + 1
                );
            }
        }

        visiting.delete(node.id);
        memo.set(node.id, value);

        return value;
    }

    for (const node of nodes) {
        depth(node);
    }

    return memo;
}

// Graph connections use a collision-free corridor when a direct curve would
// cross an intermediate knowledge node. Shared by SVG, mobile view and PNG.

function routeKnowledgeGraphConnection(fromId, toId, start, end, positions, nodeWidth, nodeHeight, stageHeight) {
    const x1 = start.x, y1 = start.y, x2 = end.x, y2 = end.y;
    const bend = Math.max(16, Math.abs(x2 - x1) * 0.42);
    const obstacles = [];
    for (const [id, pos] of positions) {
        if (id === fromId || id === toId) continue;
        obstacles.push({
            left:pos.x - 5, right:pos.x + nodeWidth + 5,
            top:pos.y - 5, bottom:pos.y + nodeHeight + 5
        });
    }
    const inside = (x, y) => obstacles.some(r => x > r.left && x < r.right && y > r.top && y < r.bottom);
    // Preserve the original smooth appearance for edges entirely in clear gaps.
    let curveSafe = true;
    for (let i = 1; i < 32; i++) {
        const t = i / 32, u = 1 - t;
        const cx = u*u*u*x1 + 3*u*u*t*(x1+bend) + 3*u*t*t*(x2-bend) + t*t*t*x2;
        const cy = u*u*u*y1 + 3*u*u*t*y1 + 3*u*t*t*y2 + t*t*t*y2;
        if (inside(cx, cy)) { curveSafe = false; break; }
    }
    if (curveSafe) return {type:'curve', x1,y1,x2,y2,bend};

    // Search the orthogonal passages between rows and columns. Travel inside
    // inter-column gaps for vertical movement; pass a column only in row gaps.
    const startX = Math.min(x1, x2), endX = Math.max(x1, x2);
    const xs = [x1, x2];
    const ys = [y1, y2, 11, Math.max(11, stageHeight - 11)];
    for (const r of obstacles) {
        for (const value of [r.left - 7, r.right + 7]) {
            if (value > startX && value < endX) xs.push(value);
        }
        for (const value of [r.top - 7, r.bottom + 7]) {
            if (value > 7 && value < stageHeight - 7) ys.push(value);
        }
    }
    const sortedUnique = values => [...new Set(values.map(x => Math.round(x * 100) / 100))].sort((a,b)=>a-b);
    const xx = sortedUnique(xs), yy = sortedUnique(ys);
    const sx=xx.indexOf(x1), tx=xx.indexOf(x2), sy=yy.indexOf(y1), ty=yy.indexOf(y2);
    const nx=xx.length, ny=yy.length;
    const startNode=(sy*nx+sx)*3, targetNode=(ty*nx+tx);
    const distances = new Float64Array(nx*ny*3).fill(Infinity);
    const prior = new Int32Array(nx*ny*3).fill(-1);
    const heap=[];
    const push=(cost,id)=>{ let p=heap.length; heap.push({cost,id}); while(p){const q=(p-1)>>1;if(heap[q].cost<=cost)break;heap[p]=heap[q];p=q;}heap[p]={cost,id};};
    const pop=()=>{const top=heap[0],last=heap.pop();if(heap.length){let p=0;while(2*p+1<heap.length){let q=2*p+1;if(q+1<heap.length&&heap[q+1].cost<heap[q].cost)q++;if(last.cost<=heap[q].cost)break;heap[p]=heap[q];p=q;}heap[p]=last;}return top;};
    const isClear=(a,b,c,d)=>{
        if (a===c) {const lo=Math.min(b,d),hi=Math.max(b,d);return !obstacles.some(r => a>r.left && a<r.right && hi>r.top && lo<r.bottom);}
        const lo=Math.min(a,c),hi=Math.max(a,c);return !obstacles.some(r => b>r.top && b<r.bottom && hi>r.left && lo<r.right);
    };
    distances[startNode]=0;push(0,startNode);
    let found=-1,expanded=0;
    while(heap.length && expanded<50000){
        const entry=pop(),id=entry.id;if(entry.cost>distances[id]+.001)continue;
        expanded++;
        const group=Math.floor(id/3),dir=id%3, xi=group%nx,yi=Math.floor(group/nx);
        if(group===targetNode){found=id;break;}
        for(const [dx,dy,nd] of [[-1,0,1],[1,0,1],[0,-1,2],[0,1,2]]){
            const a=xi+dx,b=yi+dy;if(a<0||a>=nx||b<0||b>=ny)continue;
            const ox=xx[xi],oy=yy[yi],ex=xx[a],ey=yy[b];
            if(!isClear(ox,oy,ex,ey))continue;
            const next=(b*nx+a)*3+nd;
            const delta=Math.abs(ex-ox)+Math.abs(ey-oy);
            // Penalise extra bends and backtracking, not the node count.
            const cost=entry.cost+delta+(dir&&dir!==nd?22:0)+(dx<0?delta*.4:0);
            if(cost>=distances[next]-.001)continue;
            distances[next]=cost;prior[next]=id;push(cost,next);
        }
    }
    let points=[];
    if(found>=0){
        for(let id=found;id>=0;id=prior[id]){const group=Math.floor(id/3);points.push([xx[group%nx],yy[Math.floor(group/nx)]]);}
        points.reverse();
        // Drop points which lie on the same straight corridor.
        const simplified=[];
        for(const p of points){const n=simplified.length;if(n>=2){const a=simplified[n-2],b=simplified[n-1];if((a[0]===b[0]&&b[0]===p[0])||(a[1]===b[1]&&b[1]===p[1])){simplified[n-1]=p;continue;}}simplified.push(p);}
        points=simplified;
    } else {
        // Guaranteed escape corridor, beyond all nodes, but inside SVG height.
        const topY=11, leftGap=Math.min(x2-8,x1+Math.max(10,(x2-x1)*.16));
        const rightGap=Math.max(x1+8,x2-Math.max(10,(x2-x1)*.16));
        points=[[x1,y1],[leftGap,y1],[leftGap,topY],[rightGap,topY],[rightGap,y2],[x2,y2]];
    }
    return {type:'polyline',points};
}

function knowledgeGraphRouteSvgD(route) {
    if(route.type==='curve')return `M ${route.x1} ${route.y1} C ${route.x1+route.bend} ${route.y1}, ${route.x2-route.bend} ${route.y2}, ${route.x2} ${route.y2}`;
    return route.points.map(([x,y],i)=>`${i?'L':'M'} ${x} ${y}`).join(' ');
}

function clampMobileGraphScale(value, minimum = 0.4) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 1;
    return Math.max(minimum, Math.min(3, number));
}

function updateMobileGraphEdgeEmphasis(canvas, selectedNodeId) {
    if (!canvas) return;
    canvas.querySelectorAll(".kg-mobile-edge").forEach(edge => {
        const related = Boolean(selectedNodeId) && (
            edge.dataset.from === selectedNodeId
            || edge.dataset.to === selectedNodeId
        );
        edge.classList.toggle("is-related", related);
    });
}

function mount(host,options={}) {
 if(!host)throw new Error('知识图谱容器未加载');
 const document=host.ownerDocument,window=document.defaultView||root;
 const controller=new AbortController(),signal=controller.signal;
 const allNodes=(Array.isArray(options.nodes)?options.nodes:[]).filter(n=>n&&n.id&&n.name).map(n=>({...n,prerequisites:Array.isArray(n.prerequisites)?n.prerequisites:[]}));
 const canvas=document.getElementById('knowledgeGraphCanvas');
 const categorySelect=document.getElementById('knowledgeGraphCategory');
 const categoryTrigger=document.getElementById('knowledgeGraphCategoryTrigger');
 const copyButton=document.getElementById('knowledgeGraphCopyBtn');
 const choice=document.getElementById('mobileChoiceModal');
 const categories=['全部',...[...new Set(allNodes.map(n=>n.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-Hans-CN'))];
 let category=categories.includes(options.category)?options.category:'全部';
 let knowledgeGraphSelectedNodeId=String(options.selectedId||allNodes[0]?.id||'');
 let knowledgeGraphDesktopScale=1,desktopFitted=true,destroyed=false,resizeFrame=0;
 let visibleNodes=[],fullscreenOrigin=null,mobileFullscreen=false;
 const viewMemory=host._dmateGraphViewMemory||(host._dmateGraphViewMemory=new Map());
 const isMobileAppShell=()=>window.matchMedia('(max-width:760px)').matches;
 const knowledgeGraphNodeState=()=>({key:'neutral',label:'',fill:'#111827',stroke:'#475569',text:'#ffffff',badge:''});
 const categoryOptionLabel=value=>value==='全部'?dmateUiText('全部模块','All modules'):dmateKnowledgeLabel(value);
 const categoryLabel=()=>dmateKnowledgeLabel(category);
 const countLabel=()=>dmateUiText(`${visibleNodes.length} 个知识点`,`${visibleNodes.length} concepts`);
 const disposeViews=()=>canvas.querySelectorAll('.kg-mobile-viewport,.kg-desktop-viewport').forEach(view=>view._kgDispose?.());
 const closeChoice=()=>{window.closeMobileChoiceModal?.(categoryTrigger);window.closeMobileChoiceModal?.(categorySelect);};
 function setCategory(value){category=categories.includes(value)?value:'全部';options.onCategoryChange?.(category);renderKnowledgeGraph();}
 async function openChoice(){
  if(categoryTrigger.disabled||typeof window.openMobileChoiceModal!=='function')return;
  const selected=await window.openMobileChoiceModal({title:dmateUiText('按模块筛选','Filter by module'),value:category,
   options:categories.map(value=>({value,label:categoryOptionLabel(value)})),owner:categoryTrigger});
  if(!destroyed&&selected&&categories.includes(selected.value))setCategory(selected.value);
  if(!destroyed&&categoryTrigger.isConnected)categoryTrigger.focus({preventScroll:true});
 }
 function renderDetail(){
  const title=document.getElementById('knowledgeGraphDetailTitle'),detail=document.getElementById('knowledgeGraphDetail');
  const node=allNodes.find(n=>String(n.id)===knowledgeGraphSelectedNodeId);
  detail.replaceChildren();title.textContent=dmateKnowledgeLabel(node?.name||'节点详情');
  if(!node){detail.textContent=dmateUiText('点击左侧知识点查看关系。');return;}
  const subline=document.createElement('div');subline.className='graph-detail-subline';
  if(node.level){const pill=document.createElement('span');pill.className='graph-level-pill';pill.textContent=node.level;subline.append(pill);}
  if(subline.childNodes.length)detail.append(subline);
  const names=new Set(visibleNodes.map(n=>n.name));
  const field=(text,values,empty,relations=false)=>{
   const box=document.createElement('div');box.className='graph-detail-field';
   const label=document.createElement('div');label.className='graph-detail-field-label';label.textContent=dmateUiText(text);
   const content=document.createElement('div');content.className='graph-detail-field-value graph-detail-term-list';
   if(values.length)for(const name of values){
    const target=relations?allNodes.find(record=>record.name===name):null;
    const term=document.createElement(target?'button':'span');term.className='graph-detail-term';term.textContent=dmateKnowledgeLabel(name);
    if(target){term.type='button';term.dataset.graphNodeId=String(target.id);term.addEventListener('click',()=>navigateRelation(target),{signal});}
    content.append(term);
   }else content.textContent=dmateUiText(empty);
   box.append(label,content);detail.append(box);
  };
  field('前置知识',node.prerequisites.filter(n=>names.has(n)),'当前图中暂无前置',true);
  field('后续知识',visibleNodes.filter(n=>n.prerequisites.includes(node.name)).map(n=>n.name),'当前图中暂无后续',true);
  if(node.note)field('说明',[node.note],'');
  if(typeof options.renderLearningLinks==='function'){
   // The offline study workspace owns concept/exercise matching and routing.
   // Rebuild these links with each node/language change alongside its details.
   const links=options.renderLearningLinks(node);if(links)detail.append(links);
  }else if(typeof options.onSelect==='function'){
   const links=document.createElement('div');links.className='offline-graph-learning-links';
   const parent=document.createElement('section');parent.className='graph-parent-concept';
   const heading=document.createElement('h3');heading.textContent=dmateUiText('总概念','Overview concept');
   const entry=document.createElement('button');entry.type='button';entry.className='graph-side-copy offline-graph-concept-button';entry.textContent=dmateKnowledgeLabel(node.name);
   entry.addEventListener('click',()=>{restoreInline();options.onSelect(node);},{signal});
   parent.append(heading,entry);links.append(parent);detail.append(links);
  }
  root.DMateI18n?.translate(detail);
 }
 function selectKnowledgeGraphNode(id,sourceElement=null){
  knowledgeGraphSelectedNodeId=String(id);
  for(const node of canvas.querySelectorAll('.kg-node-group,.kg-mobile-node')){
   const selected=node.dataset.nodeId===knowledgeGraphSelectedNodeId;node.classList.toggle('selected',selected);node.setAttribute('aria-pressed',String(selected));
   const rect=node.querySelector('rect');if(rect)rect.setAttribute('stroke-width',selected?'3':'2');
  }
  updateMobileGraphEdgeEmphasis(canvas,knowledgeGraphSelectedNodeId);renderDetail();
  options.onSelectionChange?.(allNodes.find(node=>String(node.id)===knowledgeGraphSelectedNodeId));
 }
 function navigateRelation(record){
  knowledgeGraphSelectedNodeId=String(record.id);
  const targetCategory=categories.includes(record.category)?record.category:'全部';
  if(category!==targetCategory)setCategory(targetCategory);
  if(isMobileAppShell()&&!host.classList.contains('graph-fullscreen-view'))toggleKnowledgeGraphFullscreenView();
  selectKnowledgeGraphNode(knowledgeGraphSelectedNodeId);
  revealSelectedGraphNode({focus:true,nearest:true});
 }
 function revealSelectedGraphNode({focus=false,nearest=false}={}){
  const targetId=knowledgeGraphSelectedNodeId,targetCategory=category;
  window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{
   if(destroyed||knowledgeGraphSelectedNodeId!==targetId||category!==targetCategory)return;
   const node=canvas.querySelector(`[data-node-id="${CSS.escape(targetId)}"]`);
   const viewport=canvas.querySelector('.kg-mobile-viewport,.kg-desktop-viewport');
   if(!node||!viewport)return;
   viewport._kgBeginViewInteraction?.();
   const rect=node.getBoundingClientRect(),view=viewport.getBoundingClientRect();
   const left=view.left+viewport.clientLeft,top=view.top+viewport.clientTop;
   const right=left+viewport.clientWidth,bottom=top+viewport.clientHeight;
   viewport.scrollLeft+=nearest?(rect.left<left?rect.left-left-8:rect.right>right?rect.right-right+8:0)
    :rect.left+rect.width/2-(left+viewport.clientWidth/2);
   viewport.scrollTop+=nearest?(rect.top<top?rect.top-top-8:rect.bottom>bottom?rect.bottom-bottom+8:0)
    :rect.top+rect.height/2-(top+viewport.clientHeight/2);
   viewport._kgRemember?.();
   if(!isMobileAppShell())desktopFitted=false;
   if(focus)node.focus({preventScroll:true});
  }));
 }
 function restoreInline(){
  host.classList.remove('graph-fullscreen-view');
  if(fullscreenOrigin){fullscreenOrigin.replaceWith(host);fullscreenOrigin=null;}
 }
 function toggleKnowledgeGraphFullscreenView(){
  if(host.classList.contains('graph-fullscreen-view'))restoreInline();
  else{
   fullscreenOrigin=document.createComment('offline graph fullscreen origin');
   host.before(fullscreenOrigin);document.body.append(host);host.classList.add('graph-fullscreen-view');
  }
  mobileFullscreen=host.classList.contains('graph-fullscreen-view');
  renderKnowledgeGraph();
 }
 function renderKnowledgeGraph(){
  if(destroyed)return;
  host.dataset.ready='false';host.dataset.graphReady='false';
  disposeViews();visibleNodes=allNodes.filter(n=>category==='全部'||n.category===category);
  if(!visibleNodes.some(n=>String(n.id)===knowledgeGraphSelectedNodeId))knowledgeGraphSelectedNodeId=String(visibleNodes[0]?.id||'');
  host.dataset.graphView='full';categorySelect.value=category;
  categorySelect.setAttribute('aria-label',dmateUiText('按模块筛选','Filter by module'));
  for(const option of categorySelect.options){const label=categoryOptionLabel(option.value);if(option.textContent!==label)option.textContent=label;}
  categoryTrigger.textContent=categoryOptionLabel(category);
  categoryTrigger.setAttribute('aria-label',dmateUiText('按模块筛选','Filter by module'));
  const fragment=document.createDocumentFragment();
  if(isMobileAppShell())renderMobileKnowledgeGraphSection(fragment,visibleNodes,categoryLabel(),countLabel(),{});
  else renderKnowledgeGraphSection(fragment,visibleNodes,categoryLabel(),countLabel(),{});
  canvas.replaceChildren(fragment);
  canvas.querySelectorAll('.kg-node-group,.kg-mobile-node').forEach((node,i)=>{
   node.dataset.nodeId=String(visibleNodes[i].id);node.setAttribute('role','button');node.setAttribute('aria-label',dmateKnowledgeLabel(visibleNodes[i].name));node.setAttribute('aria-pressed',String(node.classList.contains('selected')));
   if(node.localName==='g'){node.setAttribute('tabindex','0');node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectKnowledgeGraphNode(node.dataset.nodeId,node);}},{signal});}
  });
  const mobileGraph=isMobileAppShell();
  const viewKey=[mobileGraph?'mobile':'desktop',dmateUiLanguage(),visibleNodes.map(node=>node.id).join(',')].join('|');
  renderDetail();root.DMateI18n?.translate(host);
  const viewport=canvas.querySelector('.kg-mobile-viewport,.kg-desktop-viewport');
  const ready=()=>{if(!destroyed&&(!viewport||canvas.contains(viewport))){host.dataset.ready='true';host.dataset.graphReady='true';}};
  if(viewport)installKnowledgeGraphViewMemory(viewport,viewKey,viewMemory,mobileGraph,ready);
  else ready();
 }
 async function exportPNG(){
  const target=document.createElement('div');target.style.cssText='position:fixed;left:-10000px;top:0;pointer-events:none';host.append(target);
  try{
   renderKnowledgeGraphSection(target,visibleNodes,categoryLabel(),countLabel(),{},{forCopy:true});
   const source=target.querySelector('.kg-svg');if(!source)throw new Error(dmateUiText('当前范围没有可导出的知识节点','There are no knowledge nodes to export in this module.'));
   const clone=source.cloneNode(true),original=[source,...source.querySelectorAll('*')],copies=[clone,...clone.querySelectorAll('*')];
   const properties=['fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','opacity','font-size','font-family','font-weight','text-anchor'];
   original.forEach((node,i)=>{const css=window.getComputedStyle(node);for(const key of properties){const value=css.getPropertyValue(key);if(value)copies[i].style.setProperty(key,value);}});
   return await root.DMateDrawingExport.pngBlob(clone,{background:window.getComputedStyle(canvas).backgroundColor});
  }finally{target.remove();}
 }
 async function exportImage(){
  if(copyButton.disabled)return;copyButton.disabled=true;
  try{
   if(typeof root.DMateDrawingExport?.save!=='function')throw new Error(dmateUiText('导出模块未加载，请刷新后重试。','The export module is not loaded. Refresh and try again.'));
   await root.DMateDrawingExport.save(await exportPNG(),dmateUiText('知识图谱','Knowledge Graph'),{
    document,onStatus:message=>options.onStatus?.(message)
   });
  }catch(error){options.onStatus?.(error.message||dmateUiText('图谱图片导出失败，请重试','The graph image could not be exported. Try again.'));}
  finally{copyButton.disabled=false;}
 }
 categorySelect.replaceChildren();for(const value of categories){const option=document.createElement('option');option.value=value;option.textContent=categoryOptionLabel(value);categorySelect.append(option);}
 categorySelect.addEventListener('change',()=>setCategory(categorySelect.value),{signal});
 categoryTrigger.addEventListener('click',openChoice,{signal});
 document.getElementById('knowledgeGraphDesktopZoomOut').addEventListener('click',()=>setKnowledgeGraphDesktopScale(knowledgeGraphDesktopScale/1.2),{signal});
 document.getElementById('knowledgeGraphDesktopZoomIn').addEventListener('click',()=>setKnowledgeGraphDesktopScale(knowledgeGraphDesktopScale*1.2),{signal});
 document.getElementById('knowledgeGraphDesktopZoomFit').addEventListener('click',()=>{canvas.querySelector('.kg-desktop-viewport')?._kgBeginViewInteraction?.();fitKnowledgeGraphDesktop();},{signal});
 copyButton.addEventListener('click',exportImage,{signal});
 canvas.addEventListener('wheel',event=>{if(!event.ctrlKey||isMobileAppShell())return;event.preventDefault();setKnowledgeGraphDesktopScale(knowledgeGraphDesktopScale*(event.deltaY<0?1.12:.89));},{signal,passive:false});
 document.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||choice?.open||host.closest('#graphPanel')?.hidden||!host.getClientRects().length)return;
  if(document.querySelector('dialog[open],.modal:not(.hidden):not(#knowledgeGraphModal):not(#mobileChoiceModal)'))return;
  if(host.classList.contains('graph-fullscreen-view')){event.preventDefault();toggleKnowledgeGraphFullscreenView();}
 },{signal});
 let lastFontScale=root.DMateKnowledgeGraphLabels.fontScale(document);
 const fontObserver=new MutationObserver(()=>{
  const next=root.DMateKnowledgeGraphLabels.fontScale(document);
  if(next!==lastFontScale){lastFontScale=next;renderKnowledgeGraph();}
 });
 fontObserver.observe(document.documentElement,{attributes:true,attributeFilter:['style']});
 const breakpoint=window.matchMedia('(max-width:760px)');breakpoint.addEventListener('change',()=>{if(!breakpoint.matches)restoreInline();else if(mobileFullscreen&&!host.classList.contains('graph-fullscreen-view')){toggleKnowledgeGraphFullscreenView();return;}renderKnowledgeGraph();},{signal});
 window.addEventListener('dmate:languagechange',renderKnowledgeGraph,{signal});
 const observer=new ResizeObserver(()=>{if(!destroyed)canvas.querySelector('.kg-desktop-viewport')?._kgResizeRememberedView?.();});observer.observe(canvas);
 host.classList.remove('graph-fullscreen-view');renderKnowledgeGraph();
 return {exportPNG,select(id,selectionOptions={}){
  const record=allNodes.find(node=>String(node.id)===String(id));if(!record)return;
  const reveal=Boolean(selectionOptions?.reveal);knowledgeGraphSelectedNodeId=String(record.id);
  if(reveal&&!visibleNodes.some(node=>String(node.id)===knowledgeGraphSelectedNodeId))setCategory(record.category);
  if(reveal&&isMobileAppShell()&&!host.classList.contains('graph-fullscreen-view'))toggleKnowledgeGraphFullscreenView();
  const node=canvas.querySelector(`[data-node-id="${CSS.escape(knowledgeGraphSelectedNodeId)}"]`);
  selectKnowledgeGraphNode(knowledgeGraphSelectedNodeId,node);
  if(reveal)revealSelectedGraphNode();
 },destroy(){destroyed=true;disposeViews();fontObserver.disconnect();controller.abort();observer.disconnect();window.cancelAnimationFrame(resizeFrame);closeChoice();restoreInline();canvas.replaceChildren();delete host.dataset.ready;delete host.dataset.graphReady;}};
// A responsive renderer has a different layout, so keep its own camera. The
// cache outlives rebuilt DOM; scroll/zoom snapshots precede breakpoint changes.
function installKnowledgeGraphViewMemory(viewport, key, memory, mobile, onReady) {
    if (!viewport) return;
    const stage = viewport.querySelector(mobile ? '.kg-mobile-stage' : '.kg-desktop-zoom-stage');
    const surface = viewport.querySelector(mobile ? '.kg-mobile-zoom-surface' : '.kg-desktop-zoom-surface');
    if (!stage || !surface) return;
    viewport.style.visibility = 'hidden';
    viewport.dataset.kgReady = 'false';
    let initialized = false, applying = false, disposed = false, frame = 0, releaseFrame = 0;
    let width = 0, height = 0;
    let outerWidth = 0, outerHeight = 0;
    const active = () => window.matchMedia('(max-width:760px)').matches === mobile;
    const scale = () => Number(mobile ? viewport._kgScale : surface.dataset.scale) || 1;
    const remember = () => {
        // A real resize can clamp scroll before its callback runs. Scrollbars
        // created by zoom only change client dimensions, so they must still
        // commit the new camera instead of restoring an older fitted scale.
        if (!initialized || applying || disposed || !active()
            || !viewport.isConnected || viewport.offsetWidth !== outerWidth || viewport.offsetHeight !== outerHeight) return;
        const view = viewport.getBoundingClientRect(), bounds = stage.getBoundingClientRect(), zoom = scale();
        memory.set(key, {scale:zoom,
            x:(view.left + viewport.clientLeft + viewport.clientWidth / 2 - bounds.left) / zoom,
            y:(view.top + viewport.clientTop + viewport.clientHeight / 2 - bounds.top) / zoom});
    };
    const initialize = () => {
        if (disposed || !active() || !viewport.isConnected || !viewport.clientWidth || !viewport.clientHeight) return;
        const saved = memory.get(key);
        applying = true;
        width = viewport.clientWidth; height = viewport.clientHeight;
        if (saved) {
            if (mobile) viewport._kgRestoreScale?.(saved.scale);
            else setKnowledgeGraphDesktopScale(saved.scale, false);
            width = viewport.clientWidth; height = viewport.clientHeight;
            const view = viewport.getBoundingClientRect(), bounds = stage.getBoundingClientRect();
            viewport.scrollLeft += bounds.left + saved.x * scale() - (view.left + viewport.clientLeft + width / 2);
            viewport.scrollTop += bounds.top + saved.y * scale() - (view.top + viewport.clientTop + height / 2);
        } else {
            // Fitting can remove a scrollbar. Settle the resulting available
            // dimensions now, before the first visible frame or zoom label.
            for (let attempt = 0; attempt < 3; attempt++) {
                width = viewport.clientWidth; height = viewport.clientHeight;
                if (mobile) viewport._kgFit?.();
                else fitKnowledgeGraphDesktop();
                if (viewport.clientWidth === width && viewport.clientHeight === height) break;
            }
        }
        width = viewport.clientWidth; height = viewport.clientHeight;
        outerWidth = viewport.offsetWidth; outerHeight = viewport.offsetHeight;
        initialized = true;
        viewport.dataset.kgReady = 'true';
        viewport.style.visibility = '';
        onReady?.();
        // Scroll events produced by restoring/clamping arrive asynchronously.
        // Keep the saved graph point until actual user input changes the view.
        cancelAnimationFrame(releaseFrame);
        releaseFrame = requestAnimationFrame(() => {
            releaseFrame = requestAnimationFrame(() => {
                applying = false;
                if (!saved) remember();
            });
        });
    };
    const beginInteraction = () => {
        if (!initialized) initialize();
        cancelAnimationFrame(releaseFrame);
        applying = false;
    };
    const resize = () => {
        if (disposed || !active() || !viewport.clientWidth || !viewport.clientHeight) return;
        if (initialized && viewport.offsetWidth === outerWidth && viewport.offsetHeight === outerHeight) return;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(initialize);
    };
    viewport._kgRemember = remember;
    viewport._kgBeginViewInteraction = beginInteraction;
    viewport.addEventListener('pointerdown', beginInteraction, {capture:true});
    viewport.addEventListener('wheel', beginInteraction, {capture:true,passive:true});
    viewport.addEventListener('keydown', beginInteraction, {capture:true});
    viewport._kgInitializeView = () => { if (!initialized) initialize(); };
    viewport._kgResizeRememberedView = resize;
    viewport.addEventListener('scroll', remember, {passive:true});
    const observer = mobile ? null : new ResizeObserver(resize);
    observer?.observe(viewport, {box:'border-box'});
    const previousDispose = viewport._kgDispose;
    viewport._kgDispose = () => {
        if (disposed) return;
        disposed = true; cancelAnimationFrame(frame); cancelAnimationFrame(releaseFrame);
        observer?.disconnect(); viewport.removeEventListener('scroll', remember);
        viewport.removeEventListener('pointerdown', beginInteraction, {capture:true});
        viewport.removeEventListener('wheel', beginInteraction, {capture:true});
        viewport.removeEventListener('keydown', beginInteraction, {capture:true});
        previousDispose?.();
    };
    // The graph and its details are connected before installing the camera.
    // Complete fit/restore in this task; deferred calls only retry hidden views.
    initialize();
    requestAnimationFrame(() => requestAnimationFrame(() => viewport._kgInitializeView?.()));
}

function installMobileGraphInteraction(viewport, surface, stage, zoomLabel) {
    if (!viewport || !surface || !stage) return;

    const baseWidth = Math.max(1, Number(stage.dataset.baseWidth) || stage.scrollWidth || 1);
    const baseHeight = Math.max(1, Number(stage.dataset.baseHeight) || stage.scrollHeight || 1);
    const modal = document.getElementById("knowledgeGraphModal");
    const pointers = new Map();
    let fullscreenPan = null;
    let pinch = null;
    let pinchFrame = 0;
    let pendingPinch = null;
    let suppressClickUntil = 0;
    const dragSlop = 8;
    const minimumScale = 0.4;
    let fitted = true;
    let resizeFrame = 0;
    let lastCenterAnchor = null;

    const currentScale = () => (
        clampMobileGraphScale(viewport._kgScale || 1, minimumScale)
    );

    const updateLabel = scale => {
        if (zoomLabel) {
            zoomLabel.textContent = `${Math.round(scale * 100)}%`;
        }
    };

    const graphPoint = anchor => {
        const viewRect = viewport.getBoundingClientRect();
        const stageRect = stage.getBoundingClientRect();
        const scale = currentScale();
        return {
            x: (viewRect.left + anchor.x - stageRect.left) / scale,
            y: (viewRect.top + anchor.y - stageRect.top) / scale
        };
    };

    const positionGraphPoint = (point, anchor) => {
        const viewRect = viewport.getBoundingClientRect();
        const stageRect = stage.getBoundingClientRect();
        const scale = currentScale();
        viewport.scrollLeft += stageRect.left - viewRect.left + point.x * scale - anchor.x;
        viewport.scrollTop += stageRect.top - viewRect.top + point.y * scale - anchor.y;
    };

    const centerAnchor = () => {
        const styles = window.getComputedStyle(viewport);
        const left = parseFloat(styles.paddingLeft) || 0;
        const right = parseFloat(styles.paddingRight) || 0;
        const top = parseFloat(styles.paddingTop) || 0;
        const bottom = parseFloat(styles.paddingBottom) || 0;
        return {
            x: viewport.clientLeft + left + (viewport.clientWidth - left - right) / 2,
            y: viewport.clientTop + top + (viewport.clientHeight - top - bottom) / 2
        };
    };

    const applyScale = (nextScale, anchor = null) => {
        const scale = clampMobileGraphScale(nextScale, minimumScale);
        // A clamped button/wheel zoom has no new camera to apply. Avoid
        // reanchoring it or repainting the same graph at either limit.
        if (anchor && viewport._kgScale === scale) return scale;
        if (anchor) viewport._kgBeginViewInteraction?.();
        const point = anchor ? graphPoint(anchor) : null;
        fitted = false;
        viewport._kgScale = scale;
        viewport.dataset.scale = String(scale);
        surface.style.width = `${Math.ceil(baseWidth * scale)}px`;
        surface.style.height = `${Math.ceil(baseHeight * scale)}px`;
        stage.style.transform = `scale(${scale})`;
        // The surface fills each free axis; center the actual transformed graph
        // inside it, while oversized axes keep their full scroll range.
        stage.style.left = `${Math.max(0, (surface.clientWidth - baseWidth * scale) / 2)}px`;
        stage.style.top = `${Math.max(0, (surface.clientHeight - baseHeight * scale) / 2)}px`;
        updateLabel(scale);

        if (point) positionGraphPoint(point, anchor);
        lastCenterAnchor = centerAnchor();
        viewport._kgRemember?.();

        return scale;
    };

    const fitGraph = () => {
        if (!viewport.isConnected || !viewport.clientWidth || !viewport.clientHeight) return;
        const styles = window.getComputedStyle(viewport);
        const padding = name => parseFloat(styles[name]) || 0;
        // clientHeight 包含底部工具栏的预留内边距，不能算作图谱可用空间。
        const availableWidth = Math.max(1, viewport.clientWidth
            - padding("paddingLeft") - padding("paddingRight") - 24);
        const availableHeight = Math.max(1, viewport.clientHeight
            - padding("paddingTop") - padding("paddingBottom") - 24);
        const widthScale = availableWidth / baseWidth;
        const heightScale = availableHeight / baseHeight;
        const containedScale = Math.min(1, widthScale, heightScale);
        // Tall and wide graphs must remain readable. Allow scrolling instead
        // of shrinking labels to a few pixels, even at the manual zoom limit.
        const tall = heightScale < Math.min(1, widthScale) * 0.72;
        const scale = Math.max(0.85, tall ? Math.min(1, widthScale) : containedScale);
        applyScale(scale);
        fitted = true;
        viewport.style.visibility = "";
        viewport.scrollLeft = 0;
        viewport.scrollTop = 0;
        // In a large, sparse layout the top-left corner can contain no nodes.
        // Start at the selected concept; all other nodes remain reachable.
        const selected = stage.querySelector(".kg-mobile-node.selected");
        if (selected) {
            positionGraphPoint({
                x: selected.offsetLeft + selected.offsetWidth / 2,
                y: selected.offsetTop + selected.offsetHeight / 2
            }, centerAnchor());
        }
        viewport._kgRemember?.();
    };

    viewport._kgSetScale = applyScale;
    viewport._kgRestoreScale = value => applyScale(value);
    viewport._kgFit = fitGraph;
    viewport._kgReset = () => {
        applyScale(1);
        viewport.scrollLeft = 0;
        viewport.scrollTop = 0;
    };

    // 缩小 transform 不会缩小原始布局的溢出范围，避免留下虚假的巨大滚动区域。
    surface.style.overflow = "hidden";
    viewport.style.visibility = "hidden";
    applyScale(1);
    fitted = true;

    let previousSize = "";
    const resizeObserver = new ResizeObserver(() => {
        if (!viewport.isConnected) {
            viewport._kgDispose?.();
            return;
        }
        const size = `${viewport.clientWidth}:${viewport.clientHeight}`;
        if (size === previousSize || !viewport.clientWidth || !viewport.clientHeight) return;
        previousSize = size;
        const point = graphPoint(lastCenterAnchor || centerAnchor());
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
            resizeFrame = 0;
            if (viewport._kgResizeRememberedView) viewport._kgResizeRememberedView();
            else if (fitted) fitGraph();
            else {
                applyScale(currentScale());
                positionGraphPoint(point, centerAnchor());
            }
        });
    });
    resizeObserver.observe(viewport);
    viewport._kgDispose = () => {
        resizeObserver.disconnect();
        cancelAnimationFrame(resizeFrame);
        cancelAnimationFrame(pinchFrame);
    };

    const viewportPoint = event => {
        const rect = viewport.getBoundingClientRect();
        return {
            x: event.clientX - rect.left,
            y: event.clientY - rect.top
        };
    };

    const pointerDistance = (a, b) => Math.hypot(
        a.clientX - b.clientX,
        a.clientY - b.clientY
    );

    const pointerCenter = (a, b) => {
        const rect = viewport.getBoundingClientRect();
        return {
            x: (a.clientX + b.clientX) / 2 - rect.left,
            y: (a.clientY + b.clientY) / 2 - rect.top
        };
    };

    viewport.addEventListener("pointerdown", event => {
        if (event.pointerType === "mouse" && event.button !== 0) return;

        const fullscreen = Boolean(modal?.classList.contains("graph-fullscreen-view"));

        // 普通图谱预览由原生滚动容器接管横向、纵向两轴；
        // 不拦截 pointermove，以保留安卓浏览器的惯性与边界滚动。
        if (!fullscreen) return;

        // A fresh gesture must not inherit the previous drag's click guard.
        if (!pointers.size) suppressClickUntil = 0;
        pointers.set(event.pointerId, event);

        if (fullscreen) {
            if (pointers.size >= 2) {
                for (const pointerId of pointers.keys()) {
                    try { viewport.setPointerCapture(pointerId); } catch (_error) {}
                }
                const [a, b] = [...pointers.values()].slice(0, 2);
                const center = pointerCenter(a, b);
                const scale = currentScale();
                pinch = {
                    distance: Math.max(1, pointerDistance(a, b)),
                    scale,
                    point: graphPoint(center)
                };
                fullscreenPan = null;
                suppressClickUntil = performance.now() + 300;
                event.preventDefault();
                return;
            }

            fullscreenPan = {
                pointerId: event.pointerId,
                node: event.target.closest?.(".kg-mobile-node"),
                x: event.clientX,
                y: event.clientY,
                left: viewport.scrollLeft,
                top: viewport.scrollTop,
                moved: false
            };
            return;
        }

    }, { passive: false });

    viewport.addEventListener("pointermove", event => {
        const fullscreen = Boolean(modal?.classList.contains("graph-fullscreen-view"));

        if (!fullscreen) return;

        if (!pointers.has(event.pointerId)) return;
        pointers.set(event.pointerId, event);

        if (fullscreen && pointers.size >= 2) {
            const [a, b] = [...pointers.values()].slice(0, 2);
            if (!pinch) {
                const center = pointerCenter(a, b);
                const scale = currentScale();
                pinch = {
                    distance: Math.max(1, pointerDistance(a, b)),
                    scale,
                    point: graphPoint(center)
                };
            }

            const center = pointerCenter(a, b);
            const scale = clampMobileGraphScale(
                pinch.scale * pointerDistance(a, b) / pinch.distance,
                minimumScale
            );
            // 合并高频 pointermove：一帧只布局、缩放和定位一次。
            pendingPinch = { scale, center, point:pinch.point };
            if (!pinchFrame) {
                pinchFrame = requestAnimationFrame(() => {
                    pinchFrame = 0;
                    const target = pendingPinch;
                    pendingPinch = null;
                    if (!target) return;
                    applyScale(target.scale);
                    positionGraphPoint(target.point, target.center);
                });
            }
            suppressClickUntil = performance.now() + 300;
            event.preventDefault();
            return;
        }

        if (fullscreen && fullscreenPan?.pointerId === event.pointerId) {
            const dx = event.clientX - fullscreenPan.x;
            const dy = event.clientY - fullscreenPan.y;
            // Finger taps naturally wobble a few pixels. Keep the native node
            // click (and its original target) until this is a real drag.
            if (!fullscreenPan.moved) {
                if (Math.hypot(dx, dy) < dragSlop) return;
                fullscreenPan.moved = true;
                try { viewport.setPointerCapture(event.pointerId); } catch (_error) {}
            }
            fitted = false;
            suppressClickUntil = performance.now() + 300;
            viewport.scrollLeft = fullscreenPan.left - dx;
            viewport.scrollTop = fullscreenPan.top - dy;
            event.preventDefault();
            return;
        }

    }, { passive: false });

    const finishPointer = event => {
        const tappedNode = event.type === "pointerup" && event.pointerType !== "mouse"
            && fullscreenPan?.pointerId === event.pointerId && !fullscreenPan.moved
            && Math.hypot(event.clientX - fullscreenPan.x, event.clientY - fullscreenPan.y) < dragSlop
            && pointers.size === 1 && !pinch
            ? fullscreenPan.node : null;
        if (pinch || fullscreenPan?.moved) {
            // Suppress only the compatibility click from this completed
            // gesture, even if the user paused before lifting their finger.
            suppressClickUntil = performance.now() + 300;
        }
        const wasPinching = Boolean(pinch);
        pointers.delete(event.pointerId);

        if (fullscreenPan?.pointerId === event.pointerId) {
            fullscreenPan = null;
        }

        if (pointers.size < 2) {
            pinch = null;
        }

        if (
            modal?.classList.contains("graph-fullscreen-view")
            && pointers.size === 1
        ) {
            const remaining = [...pointers.values()][0];
            fullscreenPan = {
                pointerId: remaining.pointerId,
                x: remaining.clientX,
                y: remaining.clientY,
                left: viewport.scrollLeft,
                top: viewport.scrollTop,
                moved: wasPinching
            };
        }

        if (tappedNode?.isConnected) {
            // Some touch browsers omit the compatibility click after a drag.
            // Activate a recognized tap once, then ignore its duplicate click.
            suppressClickUntil = performance.now() + 300;
            tappedNode.click();
        }
    };

    viewport.addEventListener("pointerup", finishPointer, { passive: true });
    viewport.addEventListener("pointercancel", finishPointer, { passive: true });
    viewport.addEventListener("pointerleave", event => {
        if (event.pointerType === "mouse" && !viewport.hasPointerCapture(event.pointerId)) {
            finishPointer(event);
        }
    }, { passive: true });

    viewport.addEventListener("click", event => {
        if (event.detail > 0 && performance.now() < suppressClickUntil) {
            event.preventDefault();
            event.stopPropagation();
        }
    }, true);

    // 桌面调试/触控板也能 Ctrl+滚轮缩放完整图谱。
    viewport.addEventListener("wheel", event => {
        if (!modal?.classList.contains("graph-fullscreen-view") || !event.ctrlKey) {
            return;
        }
        const point = viewportPoint(event);
        const factor = event.deltaY < 0 ? 1.12 : 0.89;
        applyScale(currentScale() * factor, point);
        event.preventDefault();
    }, { passive: false });
}

function renderMobileKnowledgeGraphSection(container, nodes, title, description, context, options = {}) {
    const section = document.createElement("div");
    section.className = "kg-section kg-mobile-section";

    const heading = document.createElement("div");
    heading.className = "kg-section-title";
    heading.textContent = title;
    section.appendChild(heading);

    if (description) {
        const desc = document.createElement("div");
        desc.className = "kg-section-desc";
        desc.textContent = description;
        section.appendChild(desc);
    }

    const graphModal = document.getElementById("knowledgeGraphModal");
    const isExpanded = graphModal?.classList.contains("graph-fullscreen-view");
    const expandButton = document.createElement("button");
    expandButton.type = "button";
    expandButton.className = "kg-mobile-expand";
    expandButton.textContent = isExpanded ? "退出完整查看" : "完整查看";
    expandButton.setAttribute(
        "aria-label",
        isExpanded ? "退出知识图谱完整查看" : "完整查看知识图谱"
    );
    expandButton.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        toggleKnowledgeGraphFullscreenView();
    });
    section.appendChild(expandButton);

    if (!isExpanded && !options.forCopy) {
        // 不再渲染非完整查看的小图：只保留进入原有完整查看的入口。
        section.classList.add("kg-mobile-entry-only");
        container.appendChild(section);
        return;
    }

    const zoomControls = document.createElement("div");
    zoomControls.className = "kg-mobile-zoom-controls";

    const zoomOut = document.createElement("button");
    zoomOut.type = "button";
    zoomOut.className = "kg-mobile-zoom-btn";
    zoomOut.textContent = "−";
    zoomOut.setAttribute("aria-label", "缩小图谱");

    const zoomLabel = document.createElement("span");
    zoomLabel.className = "kg-mobile-zoom-label";
    zoomLabel.textContent = "100%";

    const zoomIn = document.createElement("button");
    zoomIn.type = "button";
    zoomIn.className = "kg-mobile-zoom-btn";
    zoomIn.textContent = "+";
    zoomIn.setAttribute("aria-label", "放大图谱");

    const zoomFit = document.createElement("button");
    zoomFit.type = "button";
    zoomFit.className = "kg-mobile-zoom-fit";
    zoomFit.textContent = "适应";
    zoomFit.setAttribute("aria-label", dmateUiText("适应可读大小，可拖动查看全部节点",
        "Fit to a readable size; drag to explore all concepts"));
    zoomFit.title = dmateUiText("小图居中显示，大图保持可读，可拖动查看全部节点",
        "Center small graphs and keep large graphs readable; drag to explore all concepts");

    zoomControls.append(zoomOut, zoomLabel, zoomIn, zoomFit);
    section.appendChild(zoomControls);

    if (!nodes.length) {
        const empty = document.createElement("div");
        empty.className = "kg-empty";
        empty.textContent = "这个分类下暂时没有可显示的节点";
        section.appendChild(empty);
        container.appendChild(section);
        return;
    }

    const levels = computeKnowledgeGraphLevels(nodes);
    const orderedNodes = nodes.slice();
    const orderMap = new Map(
        orderedNodes.map((node, index) => [node.id, index])
    );
    const columns = new Map();

    for (const node of orderedNodes) {
        const level = levels.get(node.id) || 0;
        if (!columns.has(level)) columns.set(level, []);
        columns.get(level).push(node);
    }

    const columnKeys = [...columns.keys()].sort((a, b) => a - b);
    // 按前一层前置节点的重心排列同层知识点，减少线条在层间交叉。
    const previousOrder = new Map();
    const categoryOrder = new Map();
    nodes.forEach(node => {
        if (!categoryOrder.has(node.category)) categoryOrder.set(node.category, categoryOrder.size);
    });
    for (const key of columnKeys) {
        const group = columns.get(key);
        group.sort((a, b) => {
            const average = node => {
                const indexes = (node.prerequisites || [])
                    .map(name => previousOrder.get(name)).filter(Number.isFinite);
                return indexes.length
                    ? indexes.reduce((sum, value) => sum + value, 0) / indexes.length
                    : Number.POSITIVE_INFINITY;
            };
            return (categoryOrder.get(a.category) - categoryOrder.get(b.category))
                || average(a) - average(b)
                || orderMap.get(a.id) - orderMap.get(b.id);
        });
        group.forEach((node, index) => previousOrder.set(node.name, index));
    }

    // 距离解决密集问题：左右预留足够走线通道，上下给弯曲关系留空间。
    const columnCount = Math.max(columnKeys.length, 1);
    const marginX = 38;
    const marginY = 48;
    const gapX = 116;
    const gapY = 60;
    const nodeWidth = dmateUiLanguage() === "en" ? 190 : 144;
    const labelPack = window.DMateKnowledgeGraphLabels.prepare(nodes, {
        label: node => dmateKnowledgeLabel(node.name),
        badge: node => dmateUiText(knowledgeGraphNodeState(node.name, context).badge || node.level || ""),
        width: nodeWidth, minHeight: 76, titleSize: 13, weight: 700,
        badgeSize: 10, badgeWeight: 600, paddingX: 12, paddingY: 10, gap: 5
    });
    const nodeHeight = labelPack.height;
    const maxRows = Math.max(...columnKeys.map(key => columns.get(key).length), 1);
    const stageWidth = marginX * 2 + columnCount * nodeWidth + (columnCount - 1) * gapX;
    const stageHeight = marginY * 2 + maxRows * nodeHeight + (maxRows - 1) * gapY;

    const viewport = document.createElement("div");
    viewport.className = "kg-mobile-viewport offline-graph-canvas";
    viewport.setAttribute("aria-label", "完整知识图谱：单指拖动、双指缩放，所有知识关联线均可见");

    const zoomSurface = document.createElement("div");
    zoomSurface.className = "kg-mobile-zoom-surface";
    zoomSurface.style.width = `${stageWidth}px`;
    zoomSurface.style.height = `${stageHeight}px`;

    const stage = document.createElement("div");
    stage.className = "kg-mobile-stage";
    stage.dataset.baseWidth = String(stageWidth);
    stage.dataset.baseHeight = String(stageHeight);
    stage.style.width = `${stageWidth}px`;
    stage.style.height = `${stageHeight}px`;

    const edgeSvg = createSvgElement("svg", {
        class: "kg-mobile-edge-layer",
        width: stageWidth,
        height: stageHeight,
        viewBox: `0 0 ${stageWidth} ${stageHeight}`,
        "aria-hidden": "true"
    });
    stage.appendChild(edgeSvg);

    const positions = new Map();
    for (let columnIndex = 0; columnIndex < columnKeys.length; columnIndex += 1) {
        const level = columnKeys[columnIndex];
        const group = columns.get(level);
        const x = marginX + columnIndex * (nodeWidth + gapX);
        const totalHeight = (
            group.length * nodeHeight
            + Math.max(group.length - 1, 0) * gapY
        );
        const startY = marginY + (stageHeight - marginY * 2 - totalHeight) / 2;

        for (let rowIndex = 0; rowIndex < group.length; rowIndex += 1) {
            const node = group[rowIndex];
            const y = startY + rowIndex * (nodeHeight + gapY);
            positions.set(node.id, { x, y });
        }
    }

    const byName = new Map(nodes.map(node => [node.name, node]));
    const edges = [];
    const outgoing = new Map();
    const incoming = new Map();
    for (const node of orderedNodes) {
        for (const prerequisiteName of node.prerequisites || []) {
            const parent = byName.get(prerequisiteName);
            if (!parent || !positions.has(parent.id) || !positions.has(node.id)) continue;
            const edge = {from:parent.id, to:node.id};
            edges.push(edge);
            if (!outgoing.has(edge.from)) outgoing.set(edge.from, []);
            if (!incoming.has(edge.to)) incoming.set(edge.to, []);
            outgoing.get(edge.from).push(edge);
            incoming.get(edge.to).push(edge);
        }
    }
    // 每条线分配自己的节点连接端口：全部保留，不再隐藏“次级关系”。
    const distributePort = (index, count) => (index - (count - 1) / 2) *
        Math.min(11, (nodeHeight - 18) / Math.max(count, 1));
    for (const group of outgoing.values()) {
        group.sort((a, b) => positions.get(a.to).y - positions.get(b.to).y);
    }
    for (const group of incoming.values()) {
        group.sort((a, b) => positions.get(a.from).y - positions.get(b.from).y);
    }
    for (const edge of edges) {
        const from = positions.get(edge.from);
        const to = positions.get(edge.to);
        const outGroup = outgoing.get(edge.from);
        const inGroup = incoming.get(edge.to);
        const x1 = from.x + nodeWidth;
        const x2 = to.x;
        const y1 = from.y + nodeHeight / 2 + distributePort(outGroup.indexOf(edge), outGroup.length);
        const y2 = to.y + nodeHeight / 2 + distributePort(inGroup.indexOf(edge), inGroup.length);
        const route = routeKnowledgeGraphConnection(
            edge.from, edge.to, {x:x1,y:y1}, {x:x2,y:y2},
            positions, nodeWidth, nodeHeight, stageHeight
        );
        const path = createSvgElement("path", {
            class:"kg-mobile-edge",
            d:knowledgeGraphRouteSvgD(route),
            "data-from":edge.from,
            "data-to":edge.to
        });
        edgeSvg.appendChild(path);
    }

    for (const node of orderedNodes) {
        const position = positions.get(node.id);
        if (!position) continue;

        const state = knowledgeGraphNodeState(node.name, context);
        const button = document.createElement("button");
        button.type = "button";
        button.className = (
            "kg-mobile-node"
            + (node.id === knowledgeGraphSelectedNodeId ? " selected" : "")
        );
        button.style.left = `${position.x}px`;
        button.style.top = `${position.y}px`;
        button.style.width = `${nodeWidth}px`;
        button.style.height = `${nodeHeight}px`;
        button.style.background = state.fill;
        button.style.borderColor = state.stroke;
        button.setAttribute("aria-label", dmateKnowledgeLabel(node.name));

        window.DMateKnowledgeGraphLabels.applyHtml(button, labelPack.layouts.get(node.id));

        button.addEventListener("click", () => {
            selectKnowledgeGraphNode(node.id, button);
        });

        stage.appendChild(button);
    }

    zoomSurface.appendChild(stage);
    viewport.appendChild(zoomSurface);
    section.appendChild(viewport);
    container.appendChild(section);
    updateMobileGraphEdgeEmphasis(section, knowledgeGraphSelectedNodeId);

    if (options.forCopy) return;

    installMobileGraphInteraction(
        viewport,
        zoomSurface,
        stage,
        zoomLabel
    );

    zoomOut.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        const rect = viewport.getBoundingClientRect();
        viewport._kgSetScale?.(
            (viewport._kgScale || 1) / 1.2,
            { x: rect.width / 2, y: rect.height / 2 }
        );
    });

    zoomIn.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        const rect = viewport.getBoundingClientRect();
        viewport._kgSetScale?.(
            (viewport._kgScale || 1) * 1.2,
            { x: rect.width / 2, y: rect.height / 2 }
        );
    });

    zoomFit.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        viewport._kgBeginViewInteraction?.();
        viewport._kgFit?.();
    });

    // section 先在 DocumentFragment 内构造；等挂载、全屏 flex 布局完成后再适应。
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            if (viewport._kgInitializeView) viewport._kgInitializeView();
            else viewport._kgFit?.();
        });
    });
}

// 桌面图谱始终按真实尺寸绘制，由独立画布处理缩放与二维滚动。
// 改变缩放只更新 transform，不重新生成节点、关系线或知识点详情。

function setKnowledgeGraphDesktopScale(value, keepCenter = true) {
    const canvas = document.getElementById("knowledgeGraphCanvas");
    const surface = canvas?.querySelector(".kg-desktop-zoom-surface");
    const stage = surface?.querySelector(".kg-desktop-zoom-stage");
    const viewport = canvas?.querySelector(".kg-desktop-viewport");
    if (!canvas || !surface || !stage || !viewport) return;

    const baseWidth = Number(stage.dataset.baseWidth) || 1;
    const baseHeight = Number(stage.dataset.baseHeight) || 1;
    const previous = Number(surface.dataset.scale) || 1;
    const next = Math.max(0.4, Math.min(2.5, Number(value) || 1));
    // Only real zoom changes should touch the viewport. Reapplying a clamped
    // scale resets its label and anchor and can restart resize/paint work.
    if (keepCenter && previous === next) return;
    if (keepCenter) viewport._kgBeginViewInteraction?.();
    const center = () => {
        const rect = viewport.getBoundingClientRect();
        return {
            x: rect.left + viewport.clientLeft + viewport.clientWidth / 2,
            y: rect.top + viewport.clientTop + viewport.clientHeight / 2
        };
    };
    const anchor = keepCenter ? center() : null;
    const oldStage = keepCenter ? stage.getBoundingClientRect() : null;
    const point = keepCenter ? {
        x: (anchor.x - oldStage.left) / previous,
        y: (anchor.y - oldStage.top) / previous
    } : null;

    knowledgeGraphDesktopScale = next;
    surface.dataset.scale = String(next);
    viewport.dataset.scale = String(next);
    desktopFitted = false;
    surface.style.width = `${Math.ceil(baseWidth * next)}px`;
    surface.style.height = `${Math.ceil(baseHeight * next)}px`;
    stage.style.transform = `scale(${next})`;
    if (keepCenter) {
        const movedStage = stage.getBoundingClientRect();
        const target = center();
        viewport.scrollLeft += movedStage.left + point.x * next - target.x;
        viewport.scrollTop += movedStage.top + point.y * next - target.y;
    }
    const label = document.getElementById("knowledgeGraphDesktopZoomLabel");
    if (label) label.textContent = `${Math.round(next * 100)}%`;
    viewport._kgRemember?.();
}

// 根据图谱形状选择适应策略：
//   - 节点较少、图谱不高：完整放入可视区域。
//   - “全部知识”这类高图：以可读宽度为主，允许在画布内纵向滚动。
// 不按几十行节点的总高度去缩小整张图，否则右侧空白且文字无法阅读。

function fitKnowledgeGraphDesktop() {
    const canvas = document.getElementById("knowledgeGraphCanvas");
    const stage = canvas?.querySelector(".kg-desktop-zoom-stage");
    const viewport = canvas?.querySelector(".kg-desktop-viewport");
    if (!canvas || !stage || !viewport) return;
    const width = Number(stage.dataset.baseWidth) || 1;
    const height = Number(stage.dataset.baseHeight) || 1;
    const availableWidth = Math.max(1, viewport.clientWidth - 24);
    const availableHeight = Math.max(1, viewport.clientHeight - 24);
    const widthScale = availableWidth / width;
    const heightScale = availableHeight / height;
    const isTall = heightScale < Math.min(widthScale, 1.15) * 0.72;
    const preferred = isTall
        ? Math.min(1.15, widthScale)
        : Math.min(1.15, widthScale, heightScale);
    // 极宽的图谱宁可局部横向滚动，也不能把节点文字缩至不可阅读。
    const fitted = Math.max(0.65, preferred);
    setKnowledgeGraphDesktopScale(fitted, false);
    viewport.scrollLeft = 0;
    viewport.scrollTop = 0;
    desktopFitted = true;
    viewport._kgRemember?.();
}

function renderKnowledgeGraphSection(container, nodes, title, description, context, options = {}) {
    const section = document.createElement("div");
    section.className = "kg-section";

    const heading = document.createElement("div");
    heading.className = "kg-section-title";
    heading.textContent = title;
    section.appendChild(heading);

    if (description) {
        const desc = document.createElement("div");
        desc.className = "kg-section-desc";
        desc.textContent = description;
        section.appendChild(desc);
    }

    if (!nodes.length) {
        const empty = document.createElement("div");
        empty.className = "kg-empty";
        empty.textContent = "这个分类下暂时没有可显示的节点";
        section.appendChild(empty);
        container.appendChild(section);
        return;
    }

    const levels = computeKnowledgeGraphLevels(nodes);
    const orderedNodes = nodes.slice();
    const orderMap = new Map(
        orderedNodes.map(
            (node, index) => [node.id, index]
        )
    );

    const columns = new Map();

    for (const node of orderedNodes) {
        const level = levels.get(node.id) || 0;
        if (!columns.has(level)) {
            columns.set(level, []);
        }
        columns.get(level).push(node);
    }

    const columnKeys = [...columns.keys()].sort((a, b) => a - b);

    for (const key of columnKeys) {
        columns.get(key).sort(
            (a, b) => (
                orderMap.get(a.id)
                - orderMap.get(b.id)
            )
        );
    }

    const mobileGraphLayout = !options.forCopy && isMobileAppShell();
    let nodeWidth = dmateUiLanguage() === "en" ? 190 : 132;
    let nodeHeight = dmateUiLanguage() === "en" ? 78 : 58;
    let horizontalGap = 74;
    let verticalGap = 26;
    let margin = 24;

    if (mobileGraphLayout) {
        const viewportWidth = Math.max(
            320,
            Math.min(Number(window.innerWidth) || 390, 760)
        );
        const columnCount = Math.max(columnKeys.length, 1);
        const usableWidth = Math.max(280, viewportWidth - 40);

        horizontalGap = columnCount <= 2 ? 26 : 18;
        margin = 12;

        const fittedWidth = Math.floor(
            (
                usableWidth
                - margin * 2
                - Math.max(columnCount - 1, 0) * horizontalGap
            ) / columnCount
        );

        // 手机优先把常见 2~3 列图谱完整放进卡片；列数再多时
        // 保持最低可读宽度，并只在图谱卡片内部横向滚动。
        nodeWidth = Math.max(88, Math.min(118, fittedWidth));
        nodeHeight = nodeWidth >= 108 ? 56 : 52;
        verticalGap = 22;
    }

    const labelPack = window.DMateKnowledgeGraphLabels.prepare(nodes, {
        label: node => dmateKnowledgeLabel(node.name),
        badge: node => dmateUiText(knowledgeGraphNodeState(node.name, context).badge || node.level || ""),
        width: nodeWidth, minHeight: nodeHeight,
        titleSize: mobileGraphLayout ? 14 : 12, weight: mobileGraphLayout ? 600 : 500,
        badgeSize: mobileGraphLayout ? 11 : 10, badgeWeight: 500,
        paddingX: 10, paddingY: 10, gap: 5
    });
    nodeHeight = labelPack.height;

    const maxRows = Math.max(
        ...columnKeys.map(
            key => columns.get(key).length
        ),
        1
    );

    const svgWidth = (
        margin * 2
        + columnKeys.length * nodeWidth
        + Math.max(columnKeys.length - 1, 0) * horizontalGap
    );

    const svgHeight = (
        margin * 2
        + maxRows * nodeHeight
        + Math.max(maxRows - 1, 0) * verticalGap
    );

    const svg = createSvgElement("svg", {
        class: "kg-svg",
        viewBox: `0 0 ${svgWidth} ${svgHeight}`,
        width: svgWidth,
        height: svgHeight,
        preserveAspectRatio: "xMinYMin meet"
    });

    const positions = new Map();

    for (let columnIndex = 0; columnIndex < columnKeys.length; columnIndex += 1) {
        const level = columnKeys[columnIndex];
        const group = columns.get(level);
        const x = margin + columnIndex * (nodeWidth + horizontalGap);
        const totalHeight = (
            group.length * nodeHeight
            + Math.max(group.length - 1, 0) * verticalGap
        );
        const startY = margin + (svgHeight - margin * 2 - totalHeight) / 2;

        for (let rowIndex = 0; rowIndex < group.length; rowIndex += 1) {
            const node = group[rowIndex];
            const y = startY + rowIndex * (nodeHeight + verticalGap);
            positions.set(node.id, { x, y });
        }
    }

    const byName = new Map(
        nodes.map(node => [node.name, node])
    );

    for (const node of orderedNodes) {
        const current = positions.get(node.id);

        if (!current) continue;

        for (const prerequisiteName of node.prerequisites) {
            const previousNode = byName.get(prerequisiteName);

            if (!previousNode) continue;

            const previous = positions.get(previousNode.id);

            if (!previous) continue;

            const x1 = previous.x + nodeWidth;
            const y1 = previous.y + nodeHeight / 2;
            const x2 = current.x;
            const y2 = current.y + nodeHeight / 2;
            const route = routeKnowledgeGraphConnection(
                previousNode.id, node.id, {x:x1,y:y1}, {x:x2,y:y2},
                positions, nodeWidth, nodeHeight, svgHeight
            );
            const path = createSvgElement("path", {
                class: "kg-edge",
                "data-from": previousNode.id,
                "data-to": node.id,
                d: knowledgeGraphRouteSvgD(route)
            });

            svg.appendChild(path);
        }
    }

    for (const node of orderedNodes) {
        const position = positions.get(node.id);

        if (!position) continue;

        const state = knowledgeGraphNodeState(
            node.name,
            context
        );
        const group = createSvgElement("g", {
            class: (
                "kg-node-group"
                + (node.id === knowledgeGraphSelectedNodeId ? " selected" : "")
            ),
            transform: `translate(${position.x}, ${position.y})`
        });

        group.addEventListener(
            "click",
            () => {
                selectKnowledgeGraphNode(node.id, group);
            }
        );

        const rect = createSvgElement("rect", {
            x: 0,
            y: 0,
            width: nodeWidth,
            height: nodeHeight,
            rx: 12,
            fill: state.fill,
            stroke: state.stroke,
            "stroke-width": node.id === knowledgeGraphSelectedNodeId ? 3 : 2
        });

        group.appendChild(rect);

        window.DMateKnowledgeGraphLabels.applySvg(group, labelPack.layouts.get(node.id), {
            width: nodeWidth, height: nodeHeight, titleColor: state.text || "#ffffff"
        });

        svg.appendChild(group);
    }

    // 固定圆角卡片的宽高，只有内部视口随真实尺寸的图谱二维滚动。
    const viewport = document.createElement("div");
    viewport.className = "kg-desktop-viewport offline-graph-canvas";
    // 注意不对 SVG 用 width:100%：整张大图会被压缩到容器宽度，文字小且滚动布局抖动。
    const surface = document.createElement("div");
    surface.className = "kg-desktop-zoom-surface";
    const stage = document.createElement("div");
    stage.className = "kg-desktop-zoom-stage";
    stage.dataset.baseWidth = String(svgWidth);
    stage.dataset.baseHeight = String(svgHeight);
    stage.style.width = `${svgWidth}px`;
    stage.style.height = `${svgHeight}px`;
    svg.style.width = `${svgWidth}px`;
    svg.style.height = `${svgHeight}px`;
    stage.appendChild(svg);
    surface.appendChild(stage);
    viewport.appendChild(surface);
    section.appendChild(viewport);
    container.appendChild(section);
}

}
root.DMateOfflineGraph={mount};
})(typeof window!=='undefined'?window:globalThis);
