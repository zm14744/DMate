(function(root){
'use strict';
const NS='http://www.w3.org/2000/svg',clamp=x=>Math.max(0,Math.min(1,x)),unit=x=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=1;
const E=(d,t,a={})=>{const n=d.createElementNS(NS,t);for(const [k,v] of Object.entries(a))n.setAttribute(k,String(v));return n;};
function mount(host,o){
 const d=host.ownerDocument,s=o.state||{mode:'select',zoom:100,visible:true,start:null};
 s.polygonDraft ||= [];
 let w=1000,h=1000,active=null,ghost=null,base=null,textBusy=false;const pointers=new Map();
 const root=d.createElement('section'),bar=d.createElement('div'),scroll=d.createElement('div'),stage=d.createElement('div'),image=d.createElement('img'),svg=E(d,'svg',{viewBox:'0 0 1000 1000',role:'group','aria-label':'图形原图描绘层'}),status=d.createElement('span');
 root.className='dge-overlay';bar.className='dge-overlay-tools';scroll.className='dge-overlay-viewport';stage.className='dge-overlay-stage';image.className='dge-overlay-image';image.alt='原图';svg.classList.add('dge-overlay-svg');status.className='dge-overlay-status';
 stage.append(image,svg);scroll.append(stage);root.append(bar,scroll);host.append(root);
 const button=(label,key,fn)=>{const b=d.createElement('button');b.type='button';b.textContent=label;b.dataset.overlayTool=key;b.addEventListener('click',()=>{if(!o.disabled?.())fn();});bar.append(b);return b;};
 for(const [key,label] of [['select','选择移动'],['pan','平移'],['vertex','添加顶点'],['edge','添加边'],['bounds','框选图形']]){
  button(label,key,()=>{s.mode=key;s.start=null;draw();});
 }
 const regionMode=d.createElement('select');
 regionMode.setAttribute('aria-label','选区方式');
 for(const [key,label] of [['','更多框选方式'],['graph_poly','不规则框选图形'],
     ['text_rect','矩形框选文字'],['text_poly','不规则框选文字']]){
   const item=d.createElement('option');item.value=key;item.textContent=label;regionMode.append(item);
 }
 regionMode.addEventListener('change',()=>{
   if(o.disabled?.())return;
   s.mode=regionMode.value||'select';s.start=null;s.polygonDraft=[];draw();
 });
 bar.append(regionMode);
 const finishPolygon=()=>{
   if(!['graph_poly','text_poly'].includes(s.mode) || s.polygonDraft.length<3) return;
   const points=s.polygonDraft.map(p=>[...p]);
   const nextMode=s.mode;
   s.polygonDraft=[];s.mode='select';regionMode.value='';
   if(nextMode==='graph_poly'){
     const g=o.graph();if(g)change(()=>o.model.setGraphPolygon(g.id,points));
   }else{
     s.textRegion=points;
     status.textContent='已限定文字区域，点击“识别所选文字”。';
   }
   draw();
 };
 const finishButton=button('完成轮廓','finish-polygon',finishPolygon);
 const clearButton=button('清除文字选区','clear-text',()=>{s.textRegion=null;s.polygonDraft=[];status.textContent='已清除文字选区';draw();});
 const textButton=button('识别所选文字','recognize-text',async()=>{
   if(textBusy || !s.textRegion || !o.recognizeText)return;
   textBusy=true;status.textContent='正在识别限定区域内的文字…';draw();
   try{
      const recognized=await o.recognizeText(s.textRegion.map(p=>[...p]));
      if(typeof recognized==='string' && recognized.trim()){
        s.textRegion=null;
        status.textContent='文字已追加到题干，请校对。';
      }else status.textContent='没有识别到文字，可扩大范围或直接输入。';
   }catch(error){status.textContent=error?.message||'文字识别暂不可用，请手动输入。';}
   finally{textBusy=false;draw();}
 });
 const select=(label,entries,type)=>{const n=d.createElement('select');n.setAttribute('aria-label',label);for(const [v,t] of entries){const p=d.createElement('option');p.value=v;p.textContent=t;n.append(p);}n.addEventListener('change',()=>{const g=o.graph();if(g&&n.value!=='unknown')change(()=>o.model.setGraphType(g.id,type,n.value==='true'));});bar.append(n);return n;};
 const dir=select('图形方向',[['unknown','方向待核对'],['false','无向图'],['true','有向图']],'directed'),weight=select('图形权值',[['unknown','权值待核对'],['false','无权图'],['true','带权图']],'weighted');
 const visible=button('隐藏描绘','visibility',()=>{s.visible=!s.visible;draw();});
 const MIN_ZOOM=25,MAX_ZOOM=400;
 const zoom=x=>{
   const previous=s.zoom||100;
   const cx=scroll.scrollLeft+scroll.clientWidth/2,cy=scroll.scrollTop+scroll.clientHeight/2;
   s.zoom=Math.max(MIN_ZOOM,Math.min(MAX_ZOOM,Math.round(x)));
   stage.style.width=s.zoom+'%';value.textContent=s.zoom+'%';
   const ratio=s.zoom/previous;
   scroll.scrollLeft=cx*ratio-scroll.clientWidth/2;
   scroll.scrollTop=cy*ratio-scroll.clientHeight/2;
 };
 // 100% fills the viewport width. "Fit" also accounts for tall images.
 const fitImage=()=>{
   const win=d.defaultView;
   const viewportWidth=Math.max(1,scroll.clientWidth);
   const viewportHeight=Math.min(700,(win?.innerHeight||800)*(win?.innerWidth<=760 ? 0.55 : 0.63));
   const originalHeightAt100=viewportWidth*h/Math.max(1,w);
   zoom(Math.min(100,Math.floor(viewportHeight/Math.max(1,originalHeightAt100)*100)));
 };
 button('－','zoom-out',()=>zoom(s.zoom/1.25)).setAttribute('aria-label','缩小原图');
 const value=d.createElement('span');value.className='dge-overlay-zoom';bar.append(value);
 button('＋','zoom-in',()=>zoom(s.zoom*1.25)).setAttribute('aria-label','放大原图');
 button('适应','zoom-fit',fitImage);
  const focusButton=button('聚焦图形','focus-region',()=>{
   const g=o.graph();
   const p=g?.region_polygon;
   const box=Array.isArray(p)&&p.length>=3
     ?[Math.min(...p.map(v=>v[0])),Math.min(...p.map(v=>v[1])),
       Math.max(...p.map(v=>v[0])),Math.max(...p.map(v=>v[1]))]
     :g?.bbox;
   if(!Array.isArray(box)||box.length!==4) {
      status.textContent='请先框选当前图形的矩形或多边形范围';
      return;
   }
   const dx=box[2]-box[0],dy=box[3]-box[1];
   zoom(Math.min(MAX_ZOOM,Math.max(MIN_ZOOM,Math.round(90/Math.max(dx,dy,.1)))));
   scroll.scrollLeft=stage.scrollWidth*(box[0]+box[2])/2-scroll.clientWidth/2;
   scroll.scrollTop=stage.scrollHeight*(box[1]+box[3])/2-scroll.clientHeight/2;
 });
 bar.append(status); // Actionable feedback appears with the tools, never below the photo.
 const change=fn=>{try{fn();o.changed?.();draw();}catch(e){status.textContent=e?.message||'修改失败';}};
 const pos=(v,i,g)=>{
  if(ghost?.vertex===v.id)return ghost.pos;
  if(unit(v.x)&&unit(v.y))return [v.x,v.y];
  const b=g.bbox?.length===4?g.bbox:[0,0,1,1],a=i*Math.PI*2/Math.max(1,g.vertices.length)-Math.PI/2;
  return [clamp((b[0]+b[2])/2+(b[2]-b[0])*.34*Math.cos(a)),clamp((b[1]+b[3])/2+(b[3]-b[1])*.34*Math.sin(a))];
 };
 const px=p=>[p[0]*w,p[1]*h],mouse=e=>{const r=svg.getBoundingClientRect();return [clamp((e.clientX-r.left)/Math.max(1,r.width)),clamp((e.clientY-r.top)/Math.max(1,r.height))];};
 function draw(){
  const g=o.graph();dir.value=typeof g?.directed==='boolean'?String(g.directed):'unknown';weight.value=typeof g?.weighted==='boolean'?String(g.weighted):'unknown';visible.textContent=s.visible?'隐藏描绘':'显示描绘';svg.classList.toggle('is-hidden',!s.visible);svg.dataset.mode=s.mode;
  regionMode.value=['graph_poly','text_rect','text_poly'].includes(s.mode)?s.mode:'';
  finishButton.hidden=!['graph_poly','text_poly'].includes(s.mode);
  finishButton.disabled=s.polygonDraft.length<3||Boolean(o.disabled?.());
  textButton.hidden=!s.textRegion&&!textBusy;
  textButton.disabled=textBusy||!s.textRegion||Boolean(o.disabled?.());
  clearButton.hidden=!s.textRegion;
  focusButton.disabled=!(g?.region_polygon?.length>=3 || g?.bbox?.length===4);
  for(const b of bar.querySelectorAll('[data-overlay-tool]')){const active=b.dataset.overlayTool===s.mode;b.classList.toggle('is-active',active);if(['select','pan','vertex','edge','bounds'].includes(b.dataset.overlayTool))b.setAttribute('aria-pressed',String(active));}
  svg.replaceChildren();if(!g||!s.visible)return;
  // The mathematical path is in original-image coordinates. Input targets
  // and labels instead use a constant on-screen size, including at 400% zoom.
  const radius=Math.max(5,Math.min(w,h)*.008);
  const scale=Math.max(.0001,svg.getBoundingClientRect().width/w);
  const browser = d.defaultView;
  const touch=Boolean(browser?.navigator?.maxTouchPoints
      || browser?.matchMedia?.('(pointer: coarse)')?.matches);
  const hitRadius=Math.max(radius*2.6,(touch?22:12)/scale);
  const dotRadius=Math.max(1.5,4.5/scale);
  const handleRadius=Math.max(radius*1.1,(touch?15:8)/scale);
  const labelSize=Math.max(3,Math.min(80,13/scale));
  const labelOffset=Math.max(radius*1.25,11/scale);
  const defs=E(d,'defs'),mark=E(d,'marker',{id:o.instance+'-arrow',viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:7,markerHeight:7,orient:'auto'});mark.append(E(d,'path',{d:'M0 0 L10 5 L0 10z',fill:'currentColor'}));defs.append(mark);svg.append(defs);
  const coords=new Map(g.vertices.map((v,i)=>[v.id,pos(v,i,g)]));
  if(g.bbox?.length===4)svg.append(E(d,'rect',{x:g.bbox[0]*w,y:g.bbox[1]*h,width:(g.bbox[2]-g.bbox[0])*w,height:(g.bbox[3]-g.bbox[1])*h,class:'dge-overlay-bbox'}));
  const outline=(points,cssClass)=>{
    if(Array.isArray(points)&&points.length){
      const polygon=E(d,'polygon',{points:points.map(p=>px(p).join(',')).join(' '),class:cssClass});
      svg.append(polygon);
      if(cssClass.includes('draft'))for(const p of points)
        svg.append(E(d,'circle',{cx:p[0]*w,cy:p[1]*h,r:hitRadius*.45,class:'dge-overlay-draft-dot'}));
    }
  };
  outline(g.region_polygon,'dge-overlay-polygon');
  outline(s.textRegion,'dge-overlay-text-region');
  const pairs=new Map();for(const e of g.edges){const key=[e.from,e.to].sort().join('/');if(!pairs.has(key))pairs.set(key,[]);pairs.get(key).push(e);}
  for(const edges of pairs.values())for(const [i,e] of edges.entries()){
   if(!coords.has(e.from)||!coords.has(e.to))continue;
   const a=px(coords.get(e.from)),b=px(coords.get(e.to)),pts=Array.isArray(e.path)&&e.path.length>=2&&e.path.every(p=>Array.isArray(p)&&p.length===2&&p.every(unit))?e.path:null;
   let line,center;
   if(ghost?.edge===e.id){center=px(ghost.pos);line='M '+a.join(' ')+' L '+center.join(' ')+' L '+b.join(' ');}
   else if(pts){const ps=pts.map(px);ps[0]=a;ps[ps.length-1]=b;center=ps[Math.floor(ps.length/2)];line='M '+ps.map(p=>p.join(' ')).join(' L ');}
   else if(e.from===e.to){const r=radius*(5+i*2);line='M '+(a[0]-r*.3)+' '+(a[1]-r*.3)+' C '+(a[0]-2*r)+' '+(a[1]-2*r)+' '+(a[0]+2*r)+' '+(a[1]-2*r)+' '+(a[0]+r*.3)+' '+(a[1]-r*.3);center=[a[0],a[1]-r*1.5];}
   else{const mid=[(a[0]+b[0])/2,(a[1]+b[1])/2],len=Math.hypot(b[0]-a[0],b[1]-a[1])||1,k=(i-(edges.length-1)/2)*radius*3,c=[mid[0]-(b[1]-a[1])*k/len,mid[1]+(b[0]-a[0])*k/len];center=[(mid[0]+c[0])/2,(mid[1]+c[1])/2];line='M '+a.join(' ')+' Q '+c.join(' ')+' '+b.join(' ');}
   const chosen=o.edgeSelected?.()===e.id,group=E(d,'g',{'data-edge-id':e.id,class:'dge-overlay-edge'+(chosen?' is-selected':'')+(e.direction==='unknown'?' is-uncertain':'')});
   const hit=E(d,'path',{d:line,class:'dge-overlay-hit'});
   hit.style.strokeWidth=(touch?44:18)/scale+'px';
   group.append(hit);
   const att={d:line,class:'dge-overlay-stroke'};if(e.direction==='forward')att['marker-end']='url(#'+o.instance+'-arrow)';if(e.style==='dashed')att['stroke-dasharray']='9 6';if(e.style==='dotted')att['stroke-dasharray']='2 5';
   const stroke=E(d,'path',att);stroke.style.strokeWidth=(chosen?3.6:2.1)/scale+'px';group.append(stroke);
   const label=[e.edge_label,e.weight==null?'':String(e.weight)].filter(Boolean).join(' · ');if(label){
     const t=E(d,'text',{x:center[0],y:center[1]-labelOffset,class:'dge-overlay-label','text-anchor':'middle'});
     t.textContent=label;t.style.fontSize=labelSize+'px';group.append(t);
   }
   if(chosen&&e.from!==e.to&&s.mode==='select')group.append(E(d,'circle',{cx:center[0],cy:center[1],r:handleRadius,class:'dge-overlay-handle','data-handle-id':e.id}));svg.append(group);
  }
  for(const [i,v] of g.vertices.entries()){
   const p=px(coords.get(v.id)),gNode=E(d,'g',{'data-vertex-id':v.id,class:'dge-overlay-node'+(!unit(v.x)||!unit(v.y)?' is-estimated':'')+(o.nodeSelected?.().has(v.id)?' is-selected':'')});
   gNode.append(E(d,'circle',{cx:p[0],cy:p[1],r:hitRadius,class:'dge-overlay-node-hit'}));
   const dot=E(d,'circle',{cx:p[0],cy:p[1],r:dotRadius,class:'dge-overlay-dot'});
   dot.style.strokeWidth=(o.nodeSelected?.().has(v.id)?3:2)/scale+'px';gNode.append(dot);
   const t=E(d,'text',{x:p[0]+labelOffset,y:p[1]-labelOffset,class:'dge-overlay-label'});
   t.textContent=v.label||v.display_label||'未命名'+(i+1);t.style.fontSize=labelSize+'px';
   gNode.append(t);svg.append(gNode);
  }
  if(s.start&&coords.has(s.start)){const p=px(coords.get(s.start));svg.append(E(d,'circle',{cx:p[0],cy:p[1],r:radius*1.8,class:'dge-overlay-pending'}));}
  if(s.polygonDraft?.length)outline(s.polygonDraft,
     'dge-overlay-polygon-draft'+(s.mode==='text_poly'?' is-text':''));
  if(active?.kind==='bounds'||active?.kind==='text_bounds'){
    const a=active.start,b=active.end;
    svg.append(E(d,'rect',{x:Math.min(a[0],b[0])*w,y:Math.min(a[1],b[1])*h,
      width:Math.abs(a[0]-b[0])*w,height:Math.abs(a[1]-b[1])*h,
      class:active.kind==='text_bounds'?'dge-overlay-text-region':'dge-overlay-selection'}));
  }
 }
 svg.addEventListener('pointerdown',e=>{
  if(o.disabled?.()||!s.visible||!o.graph())return;
  pointers.set(e.pointerId,[e.clientX,e.clientY]);
  if(pointers.size===2){const a=[...pointers.values()];base={distance:Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]),zoom:s.zoom};active=null;ghost=null;return;}if(pointers.size>2)return;
  const node=e.target.closest('[data-vertex-id]')?.dataset.vertexId,edge=e.target.closest('[data-edge-id]')?.dataset.edgeId,handle=e.target.closest('[data-handle-id]')?.dataset.handleId,p=mouse(e),g=o.graph();
  if(s.mode==='graph_poly'||s.mode==='text_poly'){
    if(s.polygonDraft.length>=64){status.textContent='轮廓最多64个角点';return;}
    s.polygonDraft.push(p);draw();return;
  }
  if(s.mode==='vertex'&&!node){change(()=>o.model.addVertex(g.id,'',...p));return;}
  if(s.mode==='edge'&&node){if(!s.start){s.start=node;draw();}else{const from=s.start;s.start=null;change(()=>o.model.addEdge(g.id,{from,to:node,direction:g.directed===true?'forward':'undirected'}));}return;}
  if(s.mode==='text_rect')active={kind:'text_bounds',pointer:e.pointerId,start:p,end:p};
  else if(s.mode==='pan'||(s.mode==='select'&&e.shiftKey))active={kind:'pan',pointer:e.pointerId,start:[e.clientX,e.clientY],sx:scroll.scrollLeft,sy:scroll.scrollTop};
  else if(s.mode==='bounds'&&!node&&!edge)active={kind:'bounds',pointer:e.pointerId,start:p,end:p};
  else if(s.mode==='select'&&handle)active={kind:'handle',pointer:e.pointerId,id:handle,start:p,end:p};
  else if(s.mode==='select'&&node)active={kind:'node',pointer:e.pointerId,id:node,start:p,end:p};
  else if(s.mode==='select'&&edge)o.selectEdge?.(edge);
  if(active){e.preventDefault();svg.setPointerCapture?.(e.pointerId);}
 });
 svg.addEventListener('pointermove',e=>{
  if(pointers.has(e.pointerId))pointers.set(e.pointerId,[e.clientX,e.clientY]);
  if(base&&pointers.size>=2){const a=[...pointers.values()],distance=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]);if(base.distance>4)zoom(base.zoom*distance/base.distance);return;}
  if(!active||active.pointer!==e.pointerId)return;
  if(active.kind==='pan'){
    scroll.scrollLeft=active.sx+active.start[0]-e.clientX;
    scroll.scrollTop=active.sy+active.start[1]-e.clientY;
    return;
  }
  active.end=mouse(e);ghost=active.kind==='node'?{vertex:active.id,pos:active.end}:active.kind==='handle'?{edge:active.id,pos:active.end}:null;draw();
 });
 function release(e,cancel=false){
  pointers.delete(e.pointerId);if(pointers.size<2)base=null;
  if(!active||active.pointer!==e.pointerId)return;const op=active;active=null;ghost=null;const g=o.graph();
  if(!cancel&&g){
   if(op.kind==='node'){if(Math.hypot(op.start[0]-op.end[0],op.start[1]-op.end[1])>.004)change(()=>o.model.moveVertex(g.id,op.id,...op.end));o.selectNode?.(op.id);}
   if(op.kind==='bounds'||op.kind==='text_bounds'){
     const a=op.start,b=op.end,box=[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];
     if(box[2]-box[0]>.01 && box[3]-box[1]>.01){
       if(op.kind==='bounds')change(()=>o.model.setGraphBounds(g.id,box));
       else{
         s.textRegion=[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]];
         s.mode='select';regionMode.value='';status.textContent='文字区域已限定，可点击“识别所选文字”。';
       }
     }
   }
   if(op.kind==='handle'){const edge=g.edges.find(x=>x.id===op.id),a=g.vertices.find(x=>x.id===edge?.from),b=g.vertices.find(x=>x.id===edge?.to);if(a&&b&&unit(a.x)&&unit(a.y)&&unit(b.x)&&unit(b.y))change(()=>o.model.setEdgePath(g.id,op.id,[[a.x,a.y],op.end,[b.x,b.y]]));else status.textContent='请先校准这条边的两个端点';}
  }draw();
 }
 svg.addEventListener('pointerup',e=>release(e));svg.addEventListener('pointercancel',e=>release(e,true));
 scroll.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();zoom(s.zoom*(e.deltaY>0?0.9:1.1));},{passive:false});
 image.onload=()=>{w=image.naturalWidth||1000;h=image.naturalHeight||1000;svg.setAttribute('viewBox','0 0 '+w+' '+h);draw();};
 image.onerror=()=>{status.textContent='原图未能显示，可使用下方结构编辑';};image.src=o.originalUrl;zoom(s.zoom);draw();
 return {refresh:draw,state:s,destroy(){image.onload=null;image.onerror=null;host.replaceChildren();}};
}
root.DMateGraphOverlay={mount};if(typeof module!=='undefined'&&module.exports)module.exports={mount};
})(typeof window!=='undefined'?window:globalThis);