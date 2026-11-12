/* Offline graph uses the online SVG node style and collision-free edge routing. */
(function(root){
'use strict';
const SVG='http://www.w3.org/2000/svg';
function element(doc,tag,className,text){const node=doc.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=String(text);return node;}
function svgElement(doc,tag,attributes={}){const node=doc.createElementNS(SVG,tag);for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));return node;}
function graphLevels(nodes){
 const byName=new Map(nodes.map(node=>[node.name,node])),memo=new Map(),visiting=new Set();
 const depth=node=>{if(memo.has(node.id))return memo.get(node.id);if(visiting.has(node.id))return 0;visiting.add(node.id);let value=0;for(const name of node.prerequisites||[]){const parent=byName.get(name);if(parent)value=Math.max(value,depth(parent)+1);}visiting.delete(node.id);memo.set(node.id,value);return value;};
 nodes.forEach(depth);return memo;
}
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



function mount(host,options={}){
 if(!host)throw new Error('知识图谱容器未加载');
 const doc=host.ownerDocument,win=doc.defaultView||root,modal=host.closest('#knowledgeGraphModal');
 if(!modal)throw new Error('知识图谱弹窗未加载');
 const nodes=(Array.isArray(options.nodes)?options.nodes:[]).filter(node=>node&&node.id&&node.name);
 const byId=new Map(nodes.map(node=>[String(node.id),node]));
 const outer=new AbortController(),signal=outer.signal,find=id=>modal.querySelector('#'+id);
 let selected=String(options.selectedId||nodes[0]?.id||''),visible=nodes,renderer=null,destroyed=false;
 const detailTitle=find('knowledgeGraphDetailTitle'),detail=find('knowledgeGraphDetail');
 const desktopLabel=find('knowledgeGraphDesktopZoomLabel');
 host.classList.add('offline-graph-host');host.dataset.offlineGraph='true';
 function notice(message){options.onNotice?.(message);}
 function field(title,values,empty){
  const box=element(doc,'div','graph-detail-field'),names=element(doc,'div','graph-detail-field-value graph-detail-term-list');
  box.append(element(doc,'div','graph-detail-field-label',title));
  if(values.length)for(const name of values)names.append(element(doc,'span','graph-detail-term',name));else names.textContent=empty;
  box.append(names);detail?.append(box);
 }
 function select(identifier){
  const node=byId.get(String(identifier));if(!node)return;selected=String(identifier);
  find('knowledgeGraphDetailTab')?.classList.add('active');find('knowledgeGraphHistoryTab')?.classList.remove('active');
  find('knowledgeGraphDetailWrap')?.classList.remove('hidden');find('knowledgeGraphHistoryWrap')?.classList.add('hidden');
  host.querySelectorAll('[data-node-id]').forEach(group=>{const active=group.dataset.nodeId===selected;group.classList.toggle('selected',active);group.setAttribute('aria-pressed',String(active));});
  host.querySelectorAll('[data-from]').forEach(edge=>edge.classList.toggle('is-related',edge.dataset.from===selected||edge.dataset.to===selected));
  if(detailTitle)detailTitle.textContent=node.name;
  if(detail){
   detail.replaceChildren();const byName=new Set(visible.map(item=>item.name));
   const subline=element(doc,'div','graph-detail-subline');if(node.level)subline.append(element(doc,'span','graph-level-pill',node.level));detail.append(subline);
   field('图中前置知识',(node.prerequisites||[]).filter(name=>byName.has(name)),'当前图中暂无前置');
   field('图中直接后续',visible.filter(item=>(item.prerequisites||[]).includes(node.name)).map(item=>item.name),'当前图中暂无后续');
   if(node.note)field('说明',[node.note],'');
   if(typeof options.onSelect==='function'){
    const open=element(doc,'button','offline-graph-concept-button','查看概念');open.type='button';open.addEventListener('click',()=>options.onSelect(node),{signal});detail.append(open);
   }
  }
  options.onNodeSelect?.(node);
 }
 function render(){
  renderer?.destroy();renderer=null;host.replaceChildren();delete host.dataset.ready;
  if(destroyed)return;
  if(!visible.some(node=>String(node.id)===selected))selected=String(visible[0]?.id||'');
  const compact=win.matchMedia('(max-width:760px)').matches;
  const expanded=modal.classList.contains('graph-fullscreen-view');
  const section=element(doc,'div','kg-section'+(compact?' kg-mobile-section':''));
  const heading=element(doc,'div','kg-section-title',options.title||([...new Set(visible.map(node=>node.category))].length===1?visible[0]?.category:'全部'));
  section.append(heading,element(doc,'div','kg-section-desc',visible.length+' 个知识点'));
  if(compact){
   const expand=element(doc,'button','kg-mobile-expand',expanded?'退出完整查看':'完整查看');expand.type='button';expand.setAttribute('aria-label',expanded?'退出知识图谱完整查看':'完整查看知识图谱');
   expand.addEventListener('click',()=>{modal.classList.toggle('graph-fullscreen-view');render();},{signal});section.append(expand);
   if(!expanded){section.classList.add('kg-mobile-entry-only');host.append(section);host.dataset.ready='true';select(selected);return;}
  }
  if(!visible.length){section.append(element(doc,'div','kg-empty','这个分类下暂时没有可显示的节点'));host.append(section);host.dataset.ready='true';if(detailTitle)detailTitle.textContent='节点详情';detail?.replaceChildren(element(doc,'div','graph-detail-empty','请选择其他模块或搜索词。'));return;}
  const inner=new AbortController(),innerSignal=inner.signal;
  let scale=1,fitted=true,frame=0,pan=null,pinch=null,blockClickUntil=0,lastCenter=null;
  const pointers=new Map();
  let mobileLabel=null;
  let viewport=host;
  const surface=element(doc,'div',compact?'kg-mobile-zoom-surface':'kg-desktop-zoom-surface');
  const stage=element(doc,'div',compact?'kg-mobile-stage':'kg-desktop-zoom-stage');
  if(compact){
   const controls=element(doc,'div','kg-mobile-zoom-controls');
   const control=(text,cls,label,action)=>{const button=element(doc,'button',cls,text);button.type='button';button.setAttribute('aria-label',label);button.addEventListener('click',action,{signal:innerSignal});return button;};
   const out=control('−','kg-mobile-zoom-btn','缩小图谱',()=>setScale(scale/1.2));mobileLabel=element(doc,'span','kg-mobile-zoom-label','100%');
   const zoomIn=control('+','kg-mobile-zoom-btn','放大图谱',()=>setScale(scale*1.2));
   const fitButton=control('适应','kg-mobile-zoom-fit','适应可读大小，可拖动查看全部节点',fit);
   controls.append(out,mobileLabel,zoomIn,fitButton);section.append(controls);
   viewport=element(doc,'div','kg-mobile-viewport');viewport.setAttribute('aria-label','完整知识图谱：单指拖动、双指缩放，所有知识关联线均可见');
  }
  const graphNodes=visible.slice(),byName=new Map(graphNodes.map(node=>[node.name,node]));
  const levels=graphLevels(graphNodes),columns=new Map();
  graphNodes.forEach(node=>{const key=levels.get(node.id)||0;if(!columns.has(key))columns.set(key,[]);columns.get(key).push(node);});
  const keys=[...columns.keys()].sort((a,b)=>a-b);
  const marginX=compact?38:24,marginY=compact?48:24,gapX=compact?116:74,gapY=compact?60:26,nodeWidth=compact?144:132,nodeHeight=compact?76:58;
  const maxRows=Math.max(...[...columns.values()].map(column=>column.length));
  const baseWidth=marginX*2+keys.length*nodeWidth+(keys.length-1)*gapX;
  const baseHeight=marginY*2+maxRows*nodeHeight+(maxRows-1)*gapY;
  stage.dataset.baseWidth=String(baseWidth);stage.dataset.baseHeight=String(baseHeight);stage.style.width=baseWidth+'px';stage.style.height=baseHeight+'px';
  const positions=new Map();
  keys.forEach((key,columnIndex)=>{const column=columns.get(key),height=column.length*nodeHeight+(column.length-1)*gapY,start=marginY+(baseHeight-marginY*2-height)/2;column.forEach((node,index)=>positions.set(node.id,{x:marginX+columnIndex*(nodeWidth+gapX),y:start+index*(nodeHeight+gapY)}));});
  const paths=[];
  for(const node of graphNodes){const current=positions.get(node.id);for(const name of node.prerequisites||[]){const parent=byName.get(name);if(!parent)continue;const from=positions.get(parent.id);paths.push({from:String(parent.id),to:String(node.id),d:knowledgeGraphRouteSvgD(routeKnowledgeGraphConnection(parent.id,node.id,{x:from.x+nodeWidth,y:from.y+nodeHeight/2},{x:current.x,y:current.y+nodeHeight/2},positions,nodeWidth,nodeHeight,baseHeight))});}}
  const makeSvg=forImage=>{
   const svg=svgElement(doc,'svg',{class:compact&&!forImage?'kg-mobile-edge-layer':'kg-svg',viewBox:`0 0 ${baseWidth} ${baseHeight}`,width:baseWidth,height:baseHeight});
   const stroke=win.getComputedStyle(modal).getPropertyValue('--kg-link-stroke').trim()||'#8296b2';
   for(const path of paths)svg.append(svgElement(doc,'path',{class:compact&&!forImage?'kg-mobile-edge':'kg-edge',d:path.d,'data-from':path.from,'data-to':path.to,fill:'none',stroke,'stroke-width':1.8,'stroke-linecap':'round','stroke-linejoin':'round'}));
   if(!compact||forImage)for(const node of graphNodes){
    const position=positions.get(node.id),group=svgElement(doc,'g',{class:'kg-node-group','data-node-id':node.id,transform:`translate(${position.x}, ${position.y})`,role:'button',tabindex:0,'aria-label':node.name,'aria-pressed':String(String(node.id)===selected)});
    const active=forImage&&String(node.id)===selected;
    group.append(svgElement(doc,'rect',{x:0,y:0,width:nodeWidth,height:nodeHeight,rx:12,fill:'#111827',stroke:active?(win.getComputedStyle(modal).getPropertyValue('--accent').trim()||'#3b82f6'):'#475569','stroke-width':active?3.5:2}));
    const text=svgElement(doc,'text',{class:'kg-node-label',x:nodeWidth/2,'text-anchor':'middle',fill:'#f8fafc','font-family':'system-ui,sans-serif','font-size':compact?13:12,'font-weight':500});
    const chars=Array.from(node.name),lines=[];for(let index=0;index<chars.length;index+=7)lines.push(chars.slice(index,index+7).join(''));
    const firstY=22;
    lines.forEach((line,index)=>{const span=svgElement(doc,'tspan',{x:nodeWidth/2,y:firstY+index*14});span.textContent=line;text.append(span);});group.append(text);
    if(!forImage){group.addEventListener('click',()=>select(String(node.id)),{signal:innerSignal});group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(String(node.id));}},{signal:innerSignal});}svg.append(group);
   }
   return svg;
  };
  stage.append(makeSvg(false));
  if(compact)for(const node of graphNodes){const position=positions.get(node.id),button=element(doc,'button','kg-mobile-node');button.type='button';button.dataset.nodeId=String(node.id);button.style.cssText=`left:${position.x}px;top:${position.y}px;width:${nodeWidth}px;height:${nodeHeight}px;background:#111827;border-color:#475569`;
   button.setAttribute('aria-label',node.name);button.setAttribute('aria-pressed','false');button.append(element(doc,'span','kg-mobile-node-name',node.name));if(node.level)button.append(element(doc,'span','kg-mobile-node-badge',node.level));button.addEventListener('click',()=>select(String(node.id)),{signal:innerSignal});stage.append(button);
  }
  surface.append(stage);if(compact){viewport.append(surface);section.append(viewport);}else section.append(surface);host.append(section);
  const center=()=>{const styles=win.getComputedStyle(viewport),number=property=>parseFloat(styles[property])||0;return {x:viewport.clientLeft+number('paddingLeft')+(viewport.clientWidth-number('paddingLeft')-number('paddingRight'))/2,y:viewport.clientTop+number('paddingTop')+(viewport.clientHeight-number('paddingTop')-number('paddingBottom'))/2};};
  const graphPoint=anchor=>{const view=viewport.getBoundingClientRect(),rect=stage.getBoundingClientRect();return {x:(view.left+anchor.x-rect.left)/scale,y:(view.top+anchor.y-rect.top)/scale};};
  const positionPoint=(point,anchor)=>{const view=viewport.getBoundingClientRect(),rect=stage.getBoundingClientRect();viewport.scrollLeft+=rect.left-view.left+point.x*scale-anchor.x;viewport.scrollTop+=rect.top-view.top+point.y*scale-anchor.y;};
  function setScale(value,anchor=center()){
   const point=graphPoint(anchor);scale=Math.max(.2,Math.min(compact?3:2.5,Number(value)||1));fitted=false;
   surface.style.width=Math.ceil(baseWidth*scale)+'px';surface.style.height=Math.ceil(baseHeight*scale)+'px';stage.style.transform=`scale(${scale})`;
   stage.style.left=Math.max(0,(surface.clientWidth-baseWidth*scale)/2)+'px';stage.style.top=Math.max(0,(surface.clientHeight-baseHeight*scale)/2)+'px';
   for(const label of [desktopLabel,mobileLabel])if(label)label.textContent=Math.round(scale*100)+'%';viewport.dataset.scale=String(scale);viewport._offlineGraphScale=scale;positionPoint(point,anchor);lastCenter=center();
  }
  function fit(){
   if(destroyed||!viewport.clientWidth||!viewport.clientHeight)return;
   const styles=win.getComputedStyle(viewport),number=property=>parseFloat(styles[property])||0;
   const width=Math.max(1,viewport.clientWidth-number('paddingLeft')-number('paddingRight')-24),height=Math.max(1,viewport.clientHeight-number('paddingTop')-number('paddingBottom')-24);
   const widthScale=width/baseWidth,heightScale=height/baseHeight,tall=heightScale<Math.min(compact?1:1.15,widthScale)*.72;
   setScale(Math.max(compact?.85:.65,tall?Math.min(compact?1:1.15,widthScale):Math.min(compact?1:1.15,widthScale,heightScale)));
   fitted=true;viewport.scrollLeft=0;viewport.scrollTop=0;
   const position=positions.get(byId.get(selected)?.id);if(position)positionPoint({x:position.x+nodeWidth/2,y:position.y+nodeHeight/2},center());host.dataset.ready='true';
  }
  viewport.addEventListener('wheel',event=>{if(!event.ctrlKey)return;event.preventDefault();const rect=viewport.getBoundingClientRect();setScale(scale*(event.deltaY<0?1.12:1/1.12),{x:event.clientX-rect.left,y:event.clientY-rect.top});},{signal:innerSignal,passive:false});
  const distance=(a,b)=>Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY),midpoint=(a,b)=>{const rect=viewport.getBoundingClientRect();return {x:(a.clientX+b.clientX)/2-rect.left,y:(a.clientY+b.clientY)/2-rect.top};};
  viewport.addEventListener('pointerdown',event=>{if(event.pointerType==='mouse'&&event.button!==0)return;if(!pointers.size)blockClickUntil=0;pointers.set(event.pointerId,event);
   if(pointers.size>1){for(const id of pointers.keys())try{viewport.setPointerCapture(id);}catch(_){}const [a,b]=[...pointers.values()];const anchor=midpoint(a,b);pinch={distance:Math.max(1,distance(a,b)),scale,point:graphPoint(anchor)};pan=null;blockClickUntil=performance.now()+300;event.preventDefault();}
   else pan={id:event.pointerId,x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved:false,node:event.target.closest?.('[data-node-id]')};
  },{signal:innerSignal,passive:false});
  viewport.addEventListener('pointermove',event=>{if(!pointers.has(event.pointerId))return;pointers.set(event.pointerId,event);if(pinch&&pointers.size>1){const [a,b]=[...pointers.values()],anchor=midpoint(a,b);setScale(pinch.scale*distance(a,b)/pinch.distance,anchor);positionPoint(pinch.point,anchor);blockClickUntil=performance.now()+300;event.preventDefault();return;}if(pan?.id!==event.pointerId)return;const dx=event.clientX-pan.x,dy=event.clientY-pan.y;if(!pan.moved){if(Math.hypot(dx,dy)<8)return;pan.moved=true;try{viewport.setPointerCapture(event.pointerId);}catch(_){}}fitted=false;viewport.scrollLeft=pan.left-dx;viewport.scrollTop=pan.top-dy;blockClickUntil=performance.now()+300;event.preventDefault();},{signal:innerSignal,passive:false});
  const endPointer=event=>{const tap=event.type==='pointerup'&&event.pointerType!=='mouse'&&pan?.id===event.pointerId&&!pan.moved&&Math.hypot(event.clientX-pan.x,event.clientY-pan.y)<8&&pointers.size===1&&!pinch?pan.node:null;const moved=Boolean(pinch||pan?.moved);if(moved)blockClickUntil=performance.now()+300;pointers.delete(event.pointerId);if(pan?.id===event.pointerId)pan=null;if(pointers.size<2)pinch=null;if(pointers.size===1){const next=[...pointers.values()][0];pan={id:next.pointerId,x:next.clientX,y:next.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved,node:null};}if(tap?.isConnected){blockClickUntil=performance.now()+300;select(tap.dataset.nodeId);}};
  viewport.addEventListener('pointerup',endPointer,{signal:innerSignal});viewport.addEventListener('pointercancel',endPointer,{signal:innerSignal});viewport.addEventListener('pointerleave',event=>{if(event.pointerType==='mouse'&&!viewport.hasPointerCapture(event.pointerId))endPointer(event);},{signal:innerSignal});viewport.addEventListener('click',event=>{if(event.detail>0&&performance.now()<blockClickUntil){event.preventDefault();event.stopPropagation();}},{signal:innerSignal,capture:true});
  const observer=new ResizeObserver(()=>{if(!viewport.isConnected||destroyed)return;const point=graphPoint(lastCenter||center());win.cancelAnimationFrame(frame);frame=win.requestAnimationFrame(()=>{if(fitted)fit();else{setScale(scale);positionPoint(point,center());}});});observer.observe(viewport);
  renderer={fit,setScale,get scale(){return scale;},svg:()=>makeSvg(true),destroy(){inner.abort();observer.disconnect();win.cancelAnimationFrame(frame);for(const id of pointers.keys())try{viewport.releasePointerCapture(id);}catch(_){}pointers.clear();}};
  select(selected);frame=win.requestAnimationFrame(()=>{frame=win.requestAnimationFrame(fit);});
 }
 async function copyImage(){
  if(!visible.length){notice('暂无可复制的知识图谱');return;}
  if(!renderer){const prior=modal.classList.contains('graph-fullscreen-view');modal.classList.add('graph-fullscreen-view');render();if(!prior)modal.classList.remove('graph-fullscreen-view');}
  const svg=renderer?.svg();if(!svg)return;const width=Number(svg.getAttribute('width'))||1,height=Number(svg.getAttribute('height'))||1;
  const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml'}));
  try{const image=new Image();await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error('图谱图片生成失败'));image.src=url;});const canvas=doc.createElement('canvas');canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d');ctx.fillStyle=win.getComputedStyle(modal).getPropertyValue('--surface-0').trim()||'#171717';ctx.fillRect(0,0,width,height);ctx.drawImage(image,0,0);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error('图谱图片生成失败');if(win.ClipboardItem&&win.navigator.clipboard?.write){try{await win.navigator.clipboard.write([new win.ClipboardItem({'image/png':blob})]);notice('图谱图片已复制');return;}catch(_){}}
   const download=URL.createObjectURL(blob),link=element(doc,'a');link.href=download;link.download='DMate-知识图谱.png';doc.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(download),1000);notice('图谱图片已导出');
  }catch(error){notice(error.message||'图谱图片暂时无法生成');}finally{URL.revokeObjectURL(url);if(win.matchMedia('(max-width:760px)').matches&&!modal.classList.contains('graph-fullscreen-view'))render();}
 }
 find('knowledgeGraphDesktopZoomOut')?.addEventListener('click',()=>renderer?.setScale(renderer.scale/1.2),{signal});find('knowledgeGraphDesktopZoomIn')?.addEventListener('click',()=>renderer?.setScale(renderer.scale*1.2),{signal});find('knowledgeGraphDesktopZoomFit')?.addEventListener('click',()=>renderer?.fit(),{signal});find('knowledgeGraphCopyBtn')?.addEventListener('click',copyImage,{signal});
 doc.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||modal.classList.contains('hidden')||!modal.classList.contains('graph-fullscreen-view'))return;
  const owner=event.target.closest?.('.modal:not(.hidden),dialog[open]');
  if(owner&&owner!==modal&&!modal.contains(owner))return;
  event.preventDefault();event.stopImmediatePropagation();modal.classList.remove('graph-fullscreen-view');render();
 },{signal,capture:true});
 const media=win.matchMedia('(max-width:760px)');media.addEventListener('change',render,{signal});render();
 return {fit(){renderer?.fit();},select,focus(names){const requested=new Set((names||[]).map(String));if(!requested.size&&selected)requested.add(selected);const included=new Set(nodes.filter(node=>requested.has(String(node.id))||requested.has(node.name)).map(node=>node.name));for(const node of nodes)if(included.has(node.name)){for(const name of node.prerequisites||[])included.add(name);}visible=nodes.filter(node=>included.has(node.name)||(node.prerequisites||[]).some(name=>included.has(name)));render();},showAll(){visible=nodes;render();},get selectedNode(){return byId.get(selected)||null;},destroy(){destroyed=true;outer.abort();renderer?.destroy();host.replaceChildren();delete host.dataset.ready;}};
}
root.DMateOfflineGraph={mount};
})(typeof window!=='undefined'?window:globalThis);
