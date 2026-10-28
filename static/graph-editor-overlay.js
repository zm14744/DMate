(function(root){
'use strict';
const NS='http://www.w3.org/2000/svg',clamp=x=>Math.max(0,Math.min(1,x)),unit=x=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=1;
const E=(d,t,a={})=>{const n=d.createElementNS(NS,t);for(const [k,v] of Object.entries(a))n.setAttribute(k,String(v));return n;};
function mount(host,o){
 const d=host.ownerDocument,s=o.state||{mode:'select',zoom:100,visible:true,start:null};
 s.polygonDraft ||= [];
 s.originalVisible = s.originalVisible !== false;
 s.originalOpacity = Number.isFinite(s.originalOpacity)
   ? Math.max(0,Math.min(1,s.originalOpacity)) : 1;
 let w=1000,h=1000,active=null,ghost=null,base=null,scanSequence=0;
 let sampleCanvas=d.createElement('canvas'),sampleCtx=null,loaded=false,autoFitted=false;
 const pointers=new Map();
 const world={left:0,top:0,right:1,bottom:1};
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 const layoutWorld=()=>{
  if(!scroll.clientWidth)return;
  const controlsHeight=viewControls.offsetHeight;
  palette.style.top=(controlsHeight+12)+'px';
  root.closest('.dge-workspace,.dge-text-workspace')?.style.setProperty('--dge-viewbar-height',controlsHeight+'px');
  const scale=Math.max(1,scroll.clientWidth)*(s.zoom||100)/100;
  world.right=Math.max(world.right,world.left+Math.max(1,scroll.clientWidth)/scale);
  world.bottom=Math.max(world.bottom,world.top+Math.max(1,scroll.clientHeight)/(scale*h/w));
  stage.style.width=(world.right-world.left)*scale+'px';
  stage.style.height=(world.bottom-world.top)*scale*h/w+'px';
  image.style.position='absolute';image.style.width=scale+'px';
  image.style.left=-world.left*scale+'px';image.style.top=-world.top*scale*h/w+'px';
  svg.setAttribute('viewBox',[world.left*w,world.top*h,(world.right-world.left)*w,(world.bottom-world.top)*h].join(' '));
 };
 const expandWorld=(x,y)=>{
  const oldLeft=world.left,oldTop=world.top;
  if(x<world.left)world.left=Math.floor(x)-1;if(x>world.right)world.right=Math.ceil(x)+1;
  if(y<world.top)world.top=Math.floor(y)-1;if(y>world.bottom)world.bottom=Math.ceil(y)+1;
  layoutWorld();
  const scale=Math.max(1,scroll.clientWidth)*(s.zoom||100)/100;
  scroll.scrollLeft+=(oldLeft-world.left)*scale;scroll.scrollTop+=(oldTop-world.top)*scale*h/w;
 };
 const regionPoint=p=>p.map(clamp);
 const previewRegion=points=>o.previewRegion?.(points);
 const root=d.createElement('section'),bar=d.createElement('div'),scroll=d.createElement('div'),stage=d.createElement('div'),image=d.createElement('img'),svg=E(d,'svg',{viewBox:'0 0 1000 1000',role:'group','aria-label':'图形原图描绘层'}),status=d.createElement('span');
 root.className='dge-overlay';bar.className='dge-overlay-tools';scroll.className='dge-overlay-viewport';stage.className='dge-overlay-stage';image.className='dge-overlay-image';image.alt='原图';svg.classList.add('dge-overlay-svg');status.className='dge-overlay-status';
 const palette=d.createElement('section');palette.className='dge-tool-palette';
 if(o.textOnly)svg.setAttribute('aria-label','文字框选层');
 const paletteTitle=d.createElement('h3');paletteTitle.textContent=o.textOnly?'文字工具':'绘图工具';palette.append(paletteTitle,bar);
 const viewControls=d.createElement('div');viewControls.className='dge-view-controls';viewControls.setAttribute('aria-label','视图控制');
 stage.append(image,svg);scroll.append(stage);root.append(viewControls,palette,scroll);host.append(root);
 const button=(label,key,fn,parent=bar)=>{const b=d.createElement('button');b.type='button';b.textContent=label;b.dataset.overlayTool=key;b.addEventListener('click',()=>{if(!o.disabled?.())fn();});parent.append(b);return b;};
 for(const [key,label] of (o.textOnly?[['select','选择 / 移动'],['text_rect','框选文字']]:[['select','选择 / 移动'],['vertex','添加顶点'],['edge','添加边'],['bounds','框选图形']])){
  button(label,key,()=>{s.mode=key;s.start=null;o.clearSelection?.();draw();});
 }
 const regionMode=d.createElement('select');
 regionMode.setAttribute('aria-label','选区方式');
 for(const [key,label] of [['','更多框选方式'],o.textOnly?['text_poly','不规则框选文字']:['graph_poly','不规则框选图形']]){
   const item=d.createElement('option');item.value=key;item.textContent=label;regionMode.append(item);
 }
 regionMode.addEventListener('change',()=>{
   if(o.disabled?.())return;
   s.mode=regionMode.value||'select';s.start=null;s.polygonDraft=[];o.clearSelection?.();draw();
 });
 bar.append(regionMode);
 const commitRegion=(points,polygon)=>{
   let id;
   change(()=>{id=o.createRegion?.(points,polygon);},'region');
   if(id)void scanFigureType(points,id);
 };
 const finishPolygon=()=>{
   if(!['graph_poly','text_poly'].includes(s.mode)||s.polygonDraft.length<3)return;
   const points=s.polygonDraft.map(p=>[...p]);s.polygonDraft=[];
   if(o.textOnly){s.textRegion=points;o.selectionChanged?.(points);}else commitRegion(points,true);draw();
 };
 const finishButton=button('完成轮廓','finish-polygon',finishPolygon);
 // Each independently segmented graph receives its own direction and weight
 // from OCR + visual edge evidence. Do not override this with toolbar labels.
 // Edge-level corrections in the advanced editor remain available.
 const visible=o.textOnly?null:button('隐藏描绘','visibility',()=>{s.visible=!s.visible;draw();},viewControls);
 const MIN_ZOOM=.01,MAX_ZOOM=400;
 const zoom=x=>{
   const previous=s.zoom||100;
   const cx=scroll.scrollLeft+scroll.clientWidth/2,cy=scroll.scrollTop+scroll.clientHeight/2;
   s.zoom=Math.max(MIN_ZOOM,Math.min(MAX_ZOOM,Math.round(x*100)/100));
   layoutWorld();value.textContent=s.zoom+'%';
   const ratio=s.zoom/previous;
   scroll.scrollLeft=cx*ratio-scroll.clientWidth/2;
   scroll.scrollTop=cy*ratio-scroll.clientHeight/2;
 };
 // 100% fills the viewport width. "Fit" also accounts for tall images.
 const fitImage=()=>{
   if(!loaded||scroll.clientWidth<=0||scroll.clientHeight<=0)return;
   autoFitted=true;
   const win=d.defaultView;
   const viewportWidth=Math.max(1,scroll.clientWidth);
   const viewportHeight=Math.max(1,scroll.clientHeight);
   const originalHeightAt100=viewportWidth*h/Math.max(1,w);
   zoom(Math.min(100,(viewportHeight-4)/Math.max(1,originalHeightAt100)*100));
   const scale=viewportWidth*s.zoom/100;
   const padX=Math.max(0,(viewportWidth/scale-1)/2);
   const padY=Math.max(0,(viewportHeight/(scale*h/w)-1)/2);
   world.left=Math.min(world.left,-padX);world.top=Math.min(world.top,-padY);
   world.right=Math.max(world.right,1+padX);world.bottom=Math.max(world.bottom,1+padY);
   layoutWorld();
   scroll.scrollLeft=(.5-world.left)*scale-viewportWidth/2;
   scroll.scrollTop=(.5-world.top)*scale*h/w-viewportHeight/2;
 };
 button('－','zoom-out',()=>zoom(s.zoom/1.25),viewControls).setAttribute('aria-label','缩小原图');
 const value=d.createElement('span');value.className='dge-overlay-zoom';viewControls.append(value);
 button('＋','zoom-in',()=>zoom(s.zoom*1.25),viewControls).setAttribute('aria-label','放大原图');
 button('适应','zoom-fit',fitImage,viewControls);
 // Hide the source photo independently from the drawing layer.
 // visibility:hidden preserves its dimensions and all source coordinates.
 const syncOriginal=()=>{
  image.style.visibility=s.originalVisible?'visible':'hidden';
  image.style.opacity=String(s.originalOpacity);
  originalButton.textContent=s.originalVisible?'隐藏原图':'显示原图';
 };
 const originalButton=button(s.originalVisible?'隐藏原图':'显示原图','original-visibility',()=>{
  s.originalVisible=!s.originalVisible;syncOriginal();draw();
 },viewControls);
 const opacityControl=d.createElement('label');opacityControl.className='dge-overlay-opacity-control';
 const opacityTitle=d.createElement('span');opacityTitle.textContent='原图透明度';
 const opacityRange=d.createElement('input');opacityRange.type='range';
 opacityRange.min='0';opacityRange.max='100';opacityRange.step='1';
 opacityRange.value=String(Math.round(s.originalOpacity*100));
 opacityRange.setAttribute('aria-label','原图透明度');
 const opacityValue=d.createElement('output');opacityValue.className='dge-overlay-opacity-value';
 opacityValue.textContent=opacityRange.value+'%';
 opacityRange.addEventListener('input',()=>{
  s.originalOpacity=Math.max(0,Math.min(1,Number(opacityRange.value)/100));
  opacityValue.textContent=opacityRange.value+'%';
  image.style.opacity=String(s.originalOpacity);draw();
 });
 opacityControl.append(opacityTitle,opacityRange,opacityValue);viewControls.append(opacityControl);
 syncOriginal();
 if(o.textOnly)button('清除文字框','clear-text-region',()=>{s.textRegion=null;s.polygonDraft=[];o.selectionChanged?.(null);draw();});
 bar.append(status); // Actionable feedback appears with the tools, never below the photo.
 const change=(fn,kind)=>{try{fn();o.changed?.(kind);draw();}catch(e){status.textContent=e?.message||'修改失败';}};
 async function scanFigureType(polygon,graphId){
  if(typeof o.recognizeGraphType!=='function')return;
  const sequence=++scanSequence;
  status.textContent='正在快速判断箭头与权值…';draw();
  try{
   const result=await o.recognizeGraphType(polygon.map(p=>[...p]),graphId);
   if(sequence!==scanSequence)return;
   if(result?.stale){status.textContent='图形选区已更改，忽略旧的扫描结果';return;}
   const directed=result?.directed===true?'有向':result?.directed===false?'无向':'方向待核对';
   const weighted=result?.weighted===true?'带权':result?.weighted===false?'无权':'权值待核对';
   status.textContent=(result?.recognition_status==='complete'?'识别完成：':'扫描完成：')+directed+' · '+weighted;
   if(result?.warning)status.textContent+='；'+result.warning;
  }catch(error){
   if(sequence===scanSequence)status.textContent=error?.message||'4秒内未能确定图类型，可手动核对';
  }finally{if(sequence===scanSequence)draw();}
 }
 const buildSampler=()=>{
  sampleCtx=null;
  try{
   const ratio=Math.min(1,1400/Math.max(1,w,h));
   sampleCanvas.width=Math.max(1,Math.round(w*ratio));
   sampleCanvas.height=Math.max(1,Math.round(h*ratio));
   sampleCtx=sampleCanvas.getContext('2d',{willReadFrequently:true});
   sampleCtx.drawImage(image,0,0,sampleCanvas.width,sampleCanvas.height);
   // A cross-origin source may taint the canvas. Detect once and fall back safely.
   sampleCtx.getImageData(0,0,1,1);
  }catch(_){sampleCtx=null;}
 };
 const pixelLuminance=pixel=>{
  const alpha=pixel[3]/255*s.originalOpacity;
  const channels=[0,1,2].map(i=>(pixel[i]*alpha+255*(1-alpha))/255);
  const linear=v=>v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);
  return .2126*linear(channels[0])+.7152*linear(channels[1])+.0722*linear(channels[2]);
 };
 const localLuminance=point=>{
  if(!s.originalVisible||!unit(point?.[0])||!unit(point?.[1]))return 1;
  if(!sampleCtx||!Array.isArray(point)||point.length!==2)return null;
  const x=Math.round(clamp(point[0])*Math.max(0,sampleCanvas.width-1));
  const y=Math.round(clamp(point[1])*Math.max(0,sampleCanvas.height-1));
  try{
   const x0=Math.max(0,x-1),y0=Math.max(0,y-1);
   const x1=Math.min(sampleCanvas.width,x+2),y1=Math.min(sampleCanvas.height,y+2);
   const data=sampleCtx.getImageData(x0,y0,x1-x0,y1-y0).data,values=[];
   for(let i=0;i<data.length;i+=4)values.push(pixelLuminance(data.subarray(i,i+4)));
   values.sort((a,b)=>a-b);
   const median=values[Math.floor(values.length/2)]??.5;
   const center=pixelLuminance(sampleCtx.getImageData(x,y,1,1).data);
   // Centre sampling catches thin strokes/shadows; median suppresses local noise.
   return Math.max(0,Math.min(1,center*.72+median*.28));
  }catch(_){return null;}
 };
 const inkAt=point=>{
  const light=localLuminance(point);
  // Choose black on light paper and white on dark ink/shadows.
  // The complementary halo keeps a stroke visible across mixed backgrounds.
  return light===null||light>.179?'#111827':'#ffffff';
 };
 const oppositeInk=ink=>ink==='#ffffff'?'#111827':'#ffffff';
 const pointsPath=points=>'M '+points.map(point=>point.join(' ')).join(' L ');
 const quadraticPoints=(a,c,b,steps=24)=>{
  const out=[];
  for(let i=0;i<=steps;i++){
   const t=i/steps,u=1-t;
   out.push([u*u*a[0]+2*u*t*c[0]+t*t*b[0],
             u*u*a[1]+2*u*t*c[1]+t*t*b[1]]);
  }
  return out;
 };
 const cubicPoints=(a,c1,c2,b,steps=24)=>{
  const out=[];
  for(let i=0;i<=steps;i++){
   const t=i/steps,u=1-t;
   out.push([u*u*u*a[0]+3*u*u*t*c1[0]+3*u*t*t*c2[0]+t*t*t*b[0],
             u*u*u*a[1]+3*u*u*t*c1[1]+3*u*t*t*c2[1]+t*t*t*b[1]]);
  }
  return out;
 };
 const pos=(v,i,g)=>{
  if(active?.kind==='edge' && [active.from,active.to].includes(v.id)&&finite(v.x)&&finite(v.y))return [v.x+active.end[0]-active.start[0],v.y+active.end[1]-active.start[1]];
  if(ghost?.vertex===v.id)return ghost.pos;
  if(finite(v.x)&&finite(v.y))return [v.x,v.y];
  const b=g.bbox?.length===4?g.bbox:[0,0,1,1],a=i*Math.PI*2/Math.max(1,g.vertices.length)-Math.PI/2;
  return [clamp((b[0]+b[2])/2+(b[2]-b[0])*.34*Math.cos(a)),clamp((b[1]+b[3])/2+(b[3]-b[1])*.34*Math.sin(a))];
 };
 const px=p=>[p[0]*w,p[1]*h],mouse=e=>{const r=svg.getBoundingClientRect();return [world.left+(e.clientX-r.left)/Math.max(1,r.width)*(world.right-world.left),world.top+(e.clientY-r.top)/Math.max(1,r.height)*(world.bottom-world.top)];};
 function draw(){
  if(!scroll.clientWidth)return;
  const g=o.textOnly?{vertices:[],edges:[]}:o.graph();
  if(g)for(const v of g.vertices)if(finite(v.x)&&finite(v.y))expandWorld(v.x,v.y);
  if(visible)visible.textContent=s.visible?'隐藏描绘':'显示描绘';svg.classList.toggle('is-hidden',!s.visible);svg.dataset.mode=s.mode;
  regionMode.value=['graph_poly','text_poly'].includes(s.mode)?s.mode:'';
  finishButton.hidden=!['graph_poly','text_poly'].includes(s.mode);
  finishButton.disabled=s.polygonDraft.length<3||Boolean(o.disabled?.());
  for(const b of bar.querySelectorAll('[data-overlay-tool]')){const active=b.dataset.overlayTool===s.mode;b.classList.toggle('is-active',active);if(['select','pan','vertex','edge','bounds'].includes(b.dataset.overlayTool))b.setAttribute('aria-pressed',String(active));}
  svg.replaceChildren();if(!g||!s.visible)return;
  // The mathematical path is in original-image coordinates. Input targets
  // and labels instead use a constant on-screen size, including at 400% zoom.
  const radius=Math.max(5,Math.min(w,h)*.008);
  const scale=Math.max(.0001,svg.getBoundingClientRect().width/((world.right-world.left)*w));
  const browser = d.defaultView;
  const touch=Boolean(browser?.navigator?.maxTouchPoints
      || browser?.matchMedia?.('(pointer: coarse)')?.matches);
  const hitRadius=Math.max(radius*2.6,(touch?22:12)/scale);
  const dotRadius=Math.max(1.5,4.5/scale);
  const handleRadius=Math.max(radius*1.1,(touch?15:8)/scale);
  const labelSize=Math.max(3,Math.min(80,13/scale));
  const labelOffset=Math.max(radius*1.25,11/scale);
  const defs=E(d,'defs');
  for(const [name,fill,stroke] of [['dark','#111827','#ffffff'],['light','#ffffff','#111827']]){
   const mark=E(d,'marker',{id:o.instance+'-arrow-'+name,viewBox:'0 0 10 10',
      refX:8,refY:5,markerWidth:7,markerHeight:7,orient:'auto',markerUnits:'strokeWidth'});
   mark.append(E(d,'path',{d:'M0 0 L10 5 L0 10z',fill,stroke,'stroke-width':1.1,
      'stroke-linejoin':'round'}));defs.append(mark);
  }
  svg.append(defs);
  const coords=new Map(g.vertices.map((v,i)=>[v.id,pos(v,i,g)]));
  const outline=(points,cssClass)=>{
    if(Array.isArray(points)&&points.length){
      const polygon=E(d,'polygon',{points:points.map(p=>px(p).join(',')).join(' '),class:cssClass});
      svg.append(polygon);
      if(cssClass.includes('draft'))for(const p of points){
        const ink=inkAt(p),dot=E(d,'circle',{cx:p[0]*w,cy:p[1]*h,r:hitRadius*.45,class:'dge-overlay-draft-dot'});
        dot.style.fill=ink;dot.style.stroke=oppositeInk(ink);svg.append(dot);
      }
    }
  };
  for(const region of o.textOnly?[]:o.model.getDocument().graphs){
    let frame;
    if(region.region_polygon?.length>=3)frame=E(d,'polygon',{points:region.region_polygon.map(p=>px(p).join(',')).join(' '),class:'dge-overlay-polygon'});
    else if(region.bbox?.length===4){const b=region.bbox;frame=E(d,'rect',{x:b[0]*w,y:b[1]*h,width:(b[2]-b[0])*w,height:(b[3]-b[1])*h,class:'dge-overlay-bbox'});}
    if(frame){frame.dataset.graphId=region.id;frame.classList.add('dge-frame-hit');if(region.id===g.id)frame.classList.add('is-current');svg.append(frame);}
  }

  outline(s.textRegion,'dge-overlay-text-region');
  const pairs=new Map();for(const e of g.edges){const key=[e.from,e.to].sort().join('/');if(!pairs.has(key))pairs.set(key,[]);pairs.get(key).push(e);}
  for(const edges of pairs.values())for(const [i,e] of edges.entries()){
   if(!coords.has(e.from)||!coords.has(e.to))continue;
   const a=px(coords.get(e.from)),b=px(coords.get(e.to)),pts=Array.isArray(e.path)&&e.path.length>=2&&e.path.every(p=>Array.isArray(p)&&p.length===2&&p.every(finite))?e.path:null;
   let line,center,drawPoints;
   if(ghost?.edge===e.id){
    center=px(ghost.pos);drawPoints=[a,center,b];
   }else if(pts){
    drawPoints=pts.map(p=>px(active?.kind==='edge'&&active.id===e.id?[p[0]+active.end[0]-active.start[0],p[1]+active.end[1]-active.start[1]]:p));drawPoints[0]=a;drawPoints[drawPoints.length-1]=b;
    center=drawPoints[Math.floor(drawPoints.length/2)];
   }else if(e.from===e.to){
    const r=radius*(5+i*2);
    const p0=[a[0]-r*.3,a[1]-r*.3],p1=[a[0]-2*r,a[1]-2*r],
          p2=[a[0]+2*r,a[1]-2*r],p3=[a[0]+r*.3,a[1]-r*.3];
    drawPoints=cubicPoints(p0,p1,p2,p3);
    center=[a[0],a[1]-r*1.5];
   }else{
    const mid=[(a[0]+b[0])/2,(a[1]+b[1])/2],
          len=Math.hypot(b[0]-a[0],b[1]-a[1])||1,
          k=(i-(edges.length-1)/2)*radius*3,
          c=[mid[0]-(b[1]-a[1])*k/len,mid[1]+(b[0]-a[0])*k/len];
    drawPoints=quadraticPoints(a,c,b);
    center=drawPoints[Math.floor(drawPoints.length/2)];
   }
   line=pointsPath(drawPoints);
   const chosen=o.edgeSelected?.()===e.id,
         group=E(d,'g',{'data-edge-id':e.id,class:'dge-overlay-edge'+(chosen?' is-selected':'')+(e.direction==='unknown'?' is-uncertain':'')});
   const hit=E(d,'path',{d:line,class:'dge-overlay-hit'});
   hit.style.strokeWidth=(touch?44:18)/scale+'px';group.append(hit);
   for(let j=0;j<drawPoints.length-1;j++){
    const from=drawPoints[j],to=drawPoints[j+1],
          segment='M '+from.join(' ')+' L '+to.join(' '),
          midpoint=[(from[0]+to[0])/(2*w),(from[1]+to[1])/(2*h)],
          ink=inkAt(midpoint),halo=E(d,'path',{d:segment,class:'dge-overlay-contrast-halo'});
    halo.dataset.ink=oppositeInk(ink);halo.style.stroke=oppositeInk(ink);
    halo.style.strokeWidth=(chosen?6.2:4.8)/scale+'px';
    if(e.style==='dashed')halo.setAttribute('stroke-dasharray','9 6');
    if(e.style==='dotted')halo.setAttribute('stroke-dasharray','2 5');
    group.append(halo);
    const att={d:segment,class:'dge-overlay-stroke'};
    if(e.direction==='forward'&&j===drawPoints.length-2)
      att['marker-end']='url(#'+o.instance+'-arrow-'+(ink==='#ffffff'?'light':'dark')+')';
    if(e.style==='dashed')att['stroke-dasharray']='9 6';
    if(e.style==='dotted')att['stroke-dasharray']='2 5';
    const stroke=E(d,'path',att);
    stroke.dataset.ink=ink;stroke.style.stroke=ink;
    stroke.style.strokeWidth=(chosen?3.6:2.1)/scale+'px';
    group.append(stroke);
   }
   const label=[e.edge_label,e.weight==null?'':String(e.weight)].filter(Boolean).join(' · ');if(label){
     const t=E(d,'text',{x:center[0],y:center[1]-labelOffset,class:'dge-overlay-label','text-anchor':'middle'});
     t.textContent=label;t.style.fontSize=labelSize+'px';
     const labelInk=inkAt([center[0]/w,center[1]/h]);
     t.style.fill=labelInk;t.style.stroke=oppositeInk(labelInk);t.style.strokeWidth=(4/scale)+'px';
     group.append(t);
   }
   if(chosen&&e.from!==e.to&&s.mode==='select')group.append(E(d,'circle',{cx:center[0],cy:center[1],r:handleRadius,class:'dge-overlay-handle','data-handle-id':e.id}));svg.append(group);
  }
  for(const [i,v] of g.vertices.entries()){
   const p=px(coords.get(v.id)),normalized=[p[0]/w,p[1]/h],ink=inkAt(normalized),
         haloInk=oppositeInk(ink),
         gNode=E(d,'g',{'data-vertex-id':v.id,class:'dge-overlay-node'+(!finite(v.x)||!finite(v.y)?' is-estimated':'')+(o.nodeSelected?.().has(v.id)?' is-selected':'')});
   gNode.append(E(d,'circle',{cx:p[0],cy:p[1],r:hitRadius,class:'dge-overlay-node-hit'}));
   const halo=E(d,'circle',{cx:p[0],cy:p[1],r:dotRadius+2/scale,class:'dge-overlay-dot-halo'});
   halo.style.fill='none';halo.style.stroke=haloInk;halo.style.strokeWidth=(3/scale)+'px';gNode.append(halo);
   const dot=E(d,'circle',{cx:p[0],cy:p[1],r:dotRadius,class:'dge-overlay-dot'});
   dot.dataset.ink=ink;dot.style.fill=ink;dot.style.stroke=haloInk;
   dot.style.strokeWidth=(o.nodeSelected?.().has(v.id)?3:2)/scale+'px';gNode.append(dot);
   const t=E(d,'text',{x:p[0]+labelOffset,y:p[1]-labelOffset,class:'dge-overlay-label'});
   t.textContent=v.label||v.display_label||'未命名'+(i+1);t.style.fontSize=labelSize+'px';
   t.style.fill=ink;t.style.stroke=haloInk;t.style.strokeWidth=(4/scale)+'px';
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
  if(o.disabled?.()||!s.visible)return;
  if(s.mode==='vertex'&&!o.graph())o.ensureGraph?.();
  pointers.set(e.pointerId,[e.clientX,e.clientY]);
  if(pointers.size===2){const a=[...pointers.values()];base={distance:Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]),zoom:s.zoom};active=null;ghost=null;return;}if(pointers.size>2)return;
  const node=e.target.closest('[data-vertex-id]')?.dataset.vertexId,edge=e.target.closest('[data-edge-id]')?.dataset.edgeId,handle=e.target.closest('[data-handle-id]')?.dataset.handleId,p=mouse(e),g=o.graph();
  if(s.mode==='graph_poly'||s.mode==='text_poly'){
    if(s.polygonDraft.length>=64){status.textContent='轮廓最多64个角点';return;}
    s.polygonDraft.push(regionPoint(p));draw();return;
  }
  if(s.mode==='vertex'&&g&&!node){e.preventDefault();change(()=>o.model.addVertex(g.id,'',...p),'vertex');return;}
  if(s.mode==='edge'&&g&&node){if(!s.start){s.start=node;draw();}else{const from=s.start;s.start=null;change(()=>o.model.addEdge(g.id,{from,to:node,direction:g.directed===true?'forward':'undirected'}));}return;}
  if(s.mode==='text_rect')active={kind:'text_bounds',pointer:e.pointerId,start:p,end:p};
  else if(s.mode==='pan'||(s.mode==='select'&&e.shiftKey))active={kind:'pan',pointer:e.pointerId,start:[e.clientX,e.clientY],sx:scroll.scrollLeft,sy:scroll.scrollTop};
  else if(s.mode==='bounds')active={kind:'bounds',pointer:e.pointerId,start:p,end:p};
  else if(s.mode==='select'&&handle)active={kind:'handle',pointer:e.pointerId,id:handle,start:p,end:p};
  else if(s.mode==='select'&&node)active={kind:'node',pointer:e.pointerId,id:node,start:p,end:p};
  else if(s.mode==='select'&&edge){const item=g.edges.find(e=>e.id===edge);active={kind:'edge',pointer:e.pointerId,id:edge,from:item.from,to:item.to,start:p,end:p};}
  else if(s.mode==='select')active={kind:'pan',pointer:e.pointerId,start:[e.clientX,e.clientY],sx:scroll.scrollLeft,sy:scroll.scrollTop,graphId:e.target.closest('[data-graph-id]')?.dataset.graphId};
  if(active){e.preventDefault();svg.setPointerCapture?.(e.pointerId);}
 });
 svg.addEventListener('pointermove',e=>{
  if(pointers.has(e.pointerId))pointers.set(e.pointerId,[e.clientX,e.clientY]);
  if(base&&pointers.size>=2){const a=[...pointers.values()],distance=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]);if(base.distance>4)zoom(base.zoom*distance/base.distance);return;}
  if(!active||active.pointer!==e.pointerId)return;
  if(active.kind==='pan'){
    let x=active.sx+active.start[0]-e.clientX,y=active.sy+active.start[1]-e.clientY;
    const scale=Math.max(1,scroll.clientWidth)*(s.zoom||100)/100;
    if(x<0){expandWorld(world.left-1,world.top);active.sx+=2*scale;x+=2*scale;}
    if(y<0){expandWorld(world.left,world.top-1);active.sy+=2*scale*h/w;y+=2*scale*h/w;}
    if(x+scroll.clientWidth>=stage.offsetWidth)expandWorld(world.right+1,world.top);
    if(y+scroll.clientHeight>=stage.offsetHeight)expandWorld(world.left,world.bottom+1);
    scroll.scrollLeft=x;scroll.scrollTop=y;
    return;
  }
  active.end=mouse(e);
  if(active.kind==='bounds'){const a=regionPoint(active.start),b=regionPoint(active.end);previewRegion([[Math.min(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.max(a[1],b[1])],[Math.min(a[0],b[0]),Math.max(a[1],b[1])]]);}
  ghost=active.kind==='node'?{vertex:active.id,pos:active.end}:active.kind==='handle'?{edge:active.id,pos:active.end}:null;draw();
 });
 function release(e,cancel=false){
  pointers.delete(e.pointerId);if(pointers.size<2)base=null;
  if(!active||active.pointer!==e.pointerId)return;const op=active;active=null;ghost=null;const g=o.graph();
  if(!cancel){
   if(op.kind==='pan'&&Math.hypot(e.clientX-op.start[0],e.clientY-op.start[1])<4){if(op.graphId)o.selectGraph?.(op.graphId);else o.clearSelection?.();}
   if(op.kind==='edge'&&g){const dx=op.end[0]-op.start[0],dy=op.end[1]-op.start[1];
     if(Math.hypot(dx,dy)>.004)change(()=>o.model.moveEdge(g.id,op.id,dx,dy),'geometry');o.selectEdge?.(op.id);}
   if(op.kind==='node'&&g){if(Math.hypot(op.start[0]-op.end[0],op.start[1]-op.end[1])>.004)change(()=>o.model.moveVertex(g.id,op.id,...op.end),'geometry');o.selectNode?.(op.id);}
   if(op.kind==='bounds'||op.kind==='text_bounds'){
     const a=regionPoint(op.start),b=regionPoint(op.end),box=[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];
     if(box[2]-box[0]>.01 && box[3]-box[1]>.01){
       if(op.kind==='bounds'){
         commitRegion([[box[0],box[1]],[box[2],box[1]],
             [box[2],box[3]],[box[0],box[3]]],false);
       }
       else{
         s.textRegion=[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]];
         o.selectionChanged?.(s.textRegion);status.textContent='已框选文字范围';
       }
     }
   }
   if(op.kind==='handle'&&g){const edge=g.edges.find(x=>x.id===op.id),a=g.vertices.find(x=>x.id===edge?.from),b=g.vertices.find(x=>x.id===edge?.to);if(a&&b&&finite(a.x)&&finite(a.y)&&finite(b.x)&&finite(b.y))change(()=>o.model.setEdgePath(g.id,op.id,[[a.x,a.y],op.end,[b.x,b.y]]),'geometry');else status.textContent='请先校准这条边的两个端点';}
  }draw();
 }
 svg.addEventListener('pointerup',e=>release(e));svg.addEventListener('pointercancel',e=>release(e,true));
 scroll.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();zoom(s.zoom*(e.deltaY>0?0.9:1.1));},{passive:false});
 image.onload=()=>{w=image.naturalWidth||1000;h=image.naturalHeight||1000;loaded=true;fitImage();syncOriginal();buildSampler();draw();};
 image.onerror=()=>{status.textContent='原图未能显示，可使用下方结构编辑';};image.src=o.originalUrl;zoom(s.zoom);draw();
 const observer=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(loaded&&!autoFitted)fitImage();else layoutWorld();draw();}):null;observer?.observe(scroll);observer?.observe(viewControls);
 return {refresh:draw,state:s,destroy(){observer?.disconnect();image.onload=null;image.onerror=null;host.replaceChildren();}};
}
root.DMateGraphOverlay={mount};if(typeof module!=='undefined'&&module.exports)module.exports={mount};
})(typeof window!=='undefined'?window:globalThis);
