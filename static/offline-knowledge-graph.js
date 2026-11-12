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
 const doc=host.ownerDocument,win=doc.defaultView||root;
 const nodes=(Array.isArray(options.nodes)?options.nodes:[]).filter(node=>node&&node.id&&node.name);
 const byId=new Map(nodes.map(node=>[String(node.id),node])),byName=new Map(nodes.map(node=>[node.name,node]));
 const controller=new AbortController(),signal=controller.signal;
 let selected=String(options.selectedId||nodes[0]?.id||''),scale=1,fitted=true,destroyed=false,frame=0;
 let pan=null,pinch=null,blockClickUntil=0;
 const pointers=new Map();
 host.classList.add('offline-graph-host');
 host.replaceChildren();
 const layout=element(doc,'div','offline-knowledge-graph knowledge-graph-layout');
 const main=element(doc,'section','knowledge-graph-main');
 const toolbar=element(doc,'div','offline-graph-toolbar graph-toolbar');
 const caption=element(doc,'span','offline-graph-caption',nodes.length+' 个知识点');
 const controls=element(doc,'div','kg-desktop-zoom-controls offline-graph-controls');
 controls.setAttribute('aria-label','图谱缩放');
 const control=(name,label,path)=>{
  const button=element(doc,'button');button.type='button';button.dataset.graphAction=name;button.title=label;button.setAttribute('aria-label',label);
  if(path){const icon=svgElement(doc,'svg',{viewBox:'0 0 24 24',width:18,height:18,fill:'none',stroke:'currentColor','stroke-width':1.8,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'});icon.append(svgElement(doc,'path',{d:path}));button.append(icon);}else button.textContent=label;
  return button;
 };
 const minus=control('zoom-out','缩小图谱','M5 12h14');
 const label=element(doc,'span','offline-graph-zoom-label','100%');label.setAttribute('aria-live','off');
 const plus=control('zoom-in','放大图谱','M12 5v14M5 12h14');
 const fitButton=control('fit','适应');
 const expand=control('expand','完整查看','M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5');
 expand.setAttribute('aria-pressed','false');
 controls.append(minus,label,plus,fitButton,expand);toolbar.append(caption,controls);
 const viewport=element(doc,'div','knowledge-graph-canvas offline-graph-canvas');
 viewport.setAttribute('aria-label','知识图谱，拖动平移，双指缩放');
 const surface=element(doc,'div','offline-graph-surface'),stage=element(doc,'div','offline-graph-stage');
 const side=element(doc,'aside','knowledge-graph-side offline-graph-detail');side.setAttribute('aria-label','知识点详情');
 const detailTitle=element(doc,'h2','graph-detail-title','节点详情'),detail=element(doc,'div','graph-detail-body');
 side.append(detailTitle,detail);surface.append(stage);viewport.append(surface);main.append(toolbar,viewport);layout.append(main,side);host.append(layout);
 if(!nodes.length){viewport.append(element(doc,'div','kg-empty','没有符合条件的知识点'));detail.append(element(doc,'div','graph-detail-empty','请选择其他模块或搜索词。'));layout.dataset.ready='true';return {destroy(){controller.abort();host.replaceChildren();}};}

 const levels=graphLevels(nodes),columns=new Map();
 nodes.forEach(node=>{const key=levels.get(node.id)||0;if(!columns.has(key))columns.set(key,[]);columns.get(key).push(node);});
 const keys=[...columns.keys()].sort((a,b)=>a-b),compact=win.matchMedia('(max-width:760px)').matches;
 const margin=compact?12:24,gapX=compact?26:74,gapY=compact?22:26;
 const nodeWidth=compact?118:132,nodeHeight=compact?56:58;
 const maxRows=Math.max(...[...columns.values()].map(column=>column.length));
 const baseWidth=margin*2+keys.length*nodeWidth+(keys.length-1)*gapX;
 const baseHeight=margin*2+maxRows*nodeHeight+(maxRows-1)*gapY;
 stage.style.width=baseWidth+'px';stage.style.height=baseHeight+'px';
 const svg=svgElement(doc,'svg',{class:'kg-svg',viewBox:`0 0 ${baseWidth} ${baseHeight}`,width:baseWidth,height:baseHeight,'aria-label':'知识点前置关系图'});
 const positions=new Map(),groups=new Map();
 keys.forEach((key,columnIndex)=>{const column=columns.get(key),height=column.length*nodeHeight+(column.length-1)*gapY,start=margin+(baseHeight-margin*2-height)/2;column.forEach((node,index)=>positions.set(node.id,{x:margin+columnIndex*(nodeWidth+gapX),y:start+index*(nodeHeight+gapY)}));});
 for(const node of nodes){
  const current=positions.get(node.id);
  for(const name of node.prerequisites||[]){
   const parent=byName.get(name);if(!parent)continue;
   const from=positions.get(parent.id),route=routeKnowledgeGraphConnection(parent.id,node.id,{x:from.x+nodeWidth,y:from.y+nodeHeight/2},{x:current.x,y:current.y+nodeHeight/2},positions,nodeWidth,nodeHeight,baseHeight);
   svg.append(svgElement(doc,'path',{class:'kg-edge',d:knowledgeGraphRouteSvgD(route),'data-from':parent.id,'data-to':node.id}));
  }
 }
 for(const node of nodes){
  const position=positions.get(node.id),group=svgElement(doc,'g',{class:'kg-node-group','data-node-id':node.id,transform:`translate(${position.x}, ${position.y})`,role:'button',tabindex:0,'aria-label':node.name,'aria-pressed':'false'});
  group.append(svgElement(doc,'rect',{x:0,y:0,width:nodeWidth,height:nodeHeight,rx:12,fill:'#111827',stroke:'#475569','stroke-width':2}));
  const text=svgElement(doc,'text',{class:'kg-node-label',x:nodeWidth/2,'text-anchor':'middle',fill:'#f8fafc'});
  const chars=Array.from(node.name),lineSize=compact?7:8,lines=[];
  for(let index=0;index<chars.length;index+=lineSize)lines.push(chars.slice(index,index+lineSize).join(''));
  const lineHeight=compact?14:14,firstY=nodeHeight/2-(lines.length-1)*lineHeight/2+4;
  lines.forEach((line,index)=>{const span=svgElement(doc,'tspan',{x:nodeWidth/2,y:firstY+index*lineHeight});span.textContent=line;text.append(span);});
  group.append(text);svg.append(group);groups.set(String(node.id),group);
  group.addEventListener('click',()=>select(String(node.id)),{signal});
  group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(String(node.id));}},{signal});
 }
 stage.append(svg);
 function field(title,values,empty){const box=element(doc,'section','graph-detail-field'),names=element(doc,'div','graph-detail-field-value graph-detail-term-list');box.append(element(doc,'h3','graph-detail-field-label',title));if(values.length)for(const name of values)names.append(element(doc,'span','graph-detail-term',name));else names.textContent=empty;box.append(names);detail.append(box);}
 function select(identifier){
  const node=byId.get(identifier);if(!node)return;
  selected=identifier;
  for(const [id,group] of groups){const active=id===identifier;group.classList.toggle('selected',active);group.setAttribute('aria-pressed',String(active));}
  for(const path of svg.querySelectorAll('.kg-edge'))path.classList.toggle('is-related',path.dataset.from===identifier||path.dataset.to===identifier);
  detailTitle.textContent=node.name;detail.replaceChildren();
  const subline=element(doc,'div','graph-detail-subline');subline.append(element(doc,'span','graph-level-pill',node.category||'知识点'));detail.append(subline);
  field('图中前置知识',(node.prerequisites||[]).filter(name=>byName.has(name)),'当前图中暂无前置');
  field('图中直接后续',nodes.filter(item=>(item.prerequisites||[]).includes(node.name)).map(item=>item.name),'当前图中暂无后续');
  if(node.note)field('说明',[node.note],'');
  if(typeof options.onSelect==='function'){
   const open=element(doc,'button','offline-graph-concept-button','查看概念');open.type='button';open.addEventListener('click',()=>options.onSelect(node),{signal});detail.append(open);
  }
 }
 const center=()=>{const styles=win.getComputedStyle(viewport),number=property=>parseFloat(styles[property])||0;return {x:viewport.clientLeft+number('paddingLeft')+(viewport.clientWidth-number('paddingLeft')-number('paddingRight'))/2,y:viewport.clientTop+number('paddingTop')+(viewport.clientHeight-number('paddingTop')-number('paddingBottom'))/2};};
 const graphPoint=anchor=>{const view=viewport.getBoundingClientRect(),rect=stage.getBoundingClientRect();return {x:(view.left+anchor.x-rect.left)/scale,y:(view.top+anchor.y-rect.top)/scale};};
 const positionPoint=(point,anchor)=>{const view=viewport.getBoundingClientRect(),rect=stage.getBoundingClientRect();viewport.scrollLeft+=rect.left-view.left+point.x*scale-anchor.x;viewport.scrollTop+=rect.top-view.top+point.y*scale-anchor.y;};
 function setScale(value,anchor=center()){
  const point=graphPoint(anchor);scale=Math.max(.2,Math.min(3,Number(value)||1));fitted=false;
  surface.style.width=Math.ceil(baseWidth*scale)+'px';surface.style.height=Math.ceil(baseHeight*scale)+'px';stage.style.transform=`scale(${scale})`;
  stage.style.left=Math.max(0,(surface.clientWidth-baseWidth*scale)/2)+'px';stage.style.top=Math.max(0,(surface.clientHeight-baseHeight*scale)/2)+'px';
  label.textContent=Math.round(scale*100)+'%';viewport.dataset.scale=String(scale);viewport._offlineGraphScale=scale;positionPoint(point,anchor);
 }
 function fit(){
  if(destroyed||!viewport.clientWidth||!viewport.clientHeight)return;
  const styles=win.getComputedStyle(viewport),number=property=>parseFloat(styles[property])||0;
  const width=Math.max(1,viewport.clientWidth-number('paddingLeft')-number('paddingRight')-24),height=Math.max(1,viewport.clientHeight-number('paddingTop')-number('paddingBottom')-24);
  const widthScale=width/baseWidth,heightScale=height/baseHeight,tall=heightScale<Math.min(1.15,widthScale)*.72;
  setScale(Math.max(compact?.85:.65,tall?Math.min(1.15,widthScale):Math.min(1.15,widthScale,heightScale)));
  fitted=true;viewport.scrollLeft=0;viewport.scrollTop=0;
  const position=positions.get(byId.get(selected)?.id);if(position)positionPoint({x:position.x+nodeWidth/2,y:position.y+nodeHeight/2},center());
  layout.dataset.ready='true';
 }
 minus.addEventListener('click',()=>setScale(scale/1.2),{signal});plus.addEventListener('click',()=>setScale(scale*1.2),{signal});fitButton.addEventListener('click',fit,{signal});
 function collapse(){layout.classList.remove('is-expanded');doc.body.classList.remove('offline-graph-expanded');expand.setAttribute('aria-pressed','false');expand.setAttribute('aria-label','完整查看');expand.title='完整查看';fit();}
 expand.addEventListener('click',()=>{const active=layout.classList.toggle('is-expanded');doc.body.classList.toggle('offline-graph-expanded',active);expand.setAttribute('aria-pressed',String(active));expand.setAttribute('aria-label',active?'退出完整查看':'完整查看');expand.title=active?'退出完整查看':'完整查看';win.requestAnimationFrame(fit);},{signal});
 doc.addEventListener('keydown',event=>{if(event.key==='Escape'&&layout.classList.contains('is-expanded')){event.preventDefault();collapse();}},{signal});
 viewport.addEventListener('wheel',event=>{if(!event.ctrlKey)return;event.preventDefault();const rect=viewport.getBoundingClientRect();setScale(scale*(event.deltaY<0?1.12:1/1.12),{x:event.clientX-rect.left,y:event.clientY-rect.top});},{signal,passive:false});
 const distance=(a,b)=>Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
 const midpoint=(a,b)=>{const rect=viewport.getBoundingClientRect();return {x:(a.clientX+b.clientX)/2-rect.left,y:(a.clientY+b.clientY)/2-rect.top};};
 viewport.addEventListener('pointerdown',event=>{
  if(event.pointerType==='mouse'&&event.button!==0)return;
  if(!pointers.size)blockClickUntil=0;
  pointers.set(event.pointerId,event);
  if(pointers.size>1){for(const id of pointers.keys())try{viewport.setPointerCapture(id);}catch(_){}const [a,b]=[...pointers.values()];const anchor=midpoint(a,b);pinch={distance:Math.max(1,distance(a,b)),scale,point:graphPoint(anchor)};pan=null;blockClickUntil=performance.now()+300;event.preventDefault();}
  else pan={id:event.pointerId,x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved:false,node:event.target.closest?.('.kg-node-group')};
 },{signal,passive:false});
 viewport.addEventListener('pointermove',event=>{
  if(!pointers.has(event.pointerId))return;pointers.set(event.pointerId,event);
  if(pinch&&pointers.size>1){const [a,b]=[...pointers.values()],anchor=midpoint(a,b);setScale(pinch.scale*distance(a,b)/pinch.distance,anchor);positionPoint(pinch.point,anchor);blockClickUntil=performance.now()+300;event.preventDefault();return;}
  if(pan?.id!==event.pointerId)return;
  const dx=event.clientX-pan.x,dy=event.clientY-pan.y;if(!pan.moved){if(Math.hypot(dx,dy)<8)return;pan.moved=true;try{viewport.setPointerCapture(event.pointerId);}catch(_){}}
  fitted=false;viewport.scrollLeft=pan.left-dx;viewport.scrollTop=pan.top-dy;blockClickUntil=performance.now()+300;event.preventDefault();
 },{signal,passive:false});
 const endPointer=event=>{
  const tap=event.type==='pointerup'&&event.pointerType!=='mouse'&&pan?.id===event.pointerId&&!pan.moved&&Math.hypot(event.clientX-pan.x,event.clientY-pan.y)<8&&pointers.size===1&&!pinch?pan.node:null;
  const moved=Boolean(pinch||pan?.moved);if(moved)blockClickUntil=performance.now()+300;
  pointers.delete(event.pointerId);if(pan?.id===event.pointerId)pan=null;if(pointers.size<2)pinch=null;
  if(pointers.size===1){const next=[...pointers.values()][0];pan={id:next.pointerId,x:next.clientX,y:next.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved,node:null};}
  if(tap?.isConnected){blockClickUntil=performance.now()+300;select(tap.dataset.nodeId);}
 };
 viewport.addEventListener('pointerup',endPointer,{signal});viewport.addEventListener('pointercancel',endPointer,{signal});
 viewport.addEventListener('pointerleave',event=>{if(event.pointerType==='mouse'&&!viewport.hasPointerCapture(event.pointerId))endPointer(event);},{signal});
 viewport.addEventListener('click',event=>{if(event.detail>0&&performance.now()<blockClickUntil){event.preventDefault();event.stopPropagation();}},{signal,capture:true});
 const observer=new ResizeObserver(()=>{if(!viewport.isConnected||destroyed)return;win.cancelAnimationFrame(frame);frame=win.requestAnimationFrame(()=>{if(fitted)fit();else setScale(scale);});});observer.observe(viewport);
 select(selected);frame=win.requestAnimationFrame(()=>win.requestAnimationFrame(fit));
 return {destroy(){destroyed=true;controller.abort();observer.disconnect();win.cancelAnimationFrame(frame);for(const id of pointers.keys())try{viewport.releasePointerCapture(id);}catch(_){}pointers.clear();if(layout.classList.contains('is-expanded'))doc.body.classList.remove('offline-graph-expanded');host.replaceChildren();}};
}
root.DMateOfflineGraph={mount};
})(typeof window!=='undefined'?window:globalThis);
