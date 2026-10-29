(function(root){
'use strict';
const NS='http://www.w3.org/2000/svg',clamp=x=>Math.max(0,Math.min(1,x)),unit=x=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=1;
const E=(d,t,a={})=>{const n=d.createElementNS(NS,t);for(const [k,v] of Object.entries(a))n.setAttribute(k,String(v));return n;};
const regionSignedArea=points=>points.reduce((sum,p,i)=>{const q=points[(i+1)%points.length];return sum+p[0]*q[1]-q[0]*p[1];},0)/2;
function regionIsSimple(points){
 const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
 const on=(a,b,p)=>Math.abs(cross(a,b,p))<1e-10&&p[0]>=Math.min(a[0],b[0])-1e-10&&p[0]<=Math.max(a[0],b[0])+1e-10&&p[1]>=Math.min(a[1],b[1])-1e-10&&p[1]<=Math.max(a[1],b[1])+1e-10;
 for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
  if(j===i+1||i===0&&j===points.length-1)continue;
  const a=points[i],b=points[(i+1)%points.length],c=points[j],d=points[(j+1)%points.length];
  const x=cross(a,b,c),y=cross(a,b,d),u=cross(c,d,a),v=cross(c,d,b);
  if(x*y<0&&u*v<0||on(a,b,c)||on(a,b,d)||on(c,d,a)||on(c,d,b))return false;
 }
 return true;
}
function elasticRegionStart(points,anchor,metric){
 // Parameterise the actual closed outline in screen pixels. A whole band
 // follows the finger; arbitrary source vertices do not become edit handles.
 const original=points.map(p=>[...p]),clean=[];
 for(const p of points)if(!clean.length||Math.hypot(p[0]-clean.at(-1)[0],p[1]-clean.at(-1)[1])>1e-9)clean.push([...p]);
 if(clean.length>3&&Math.hypot(clean[0][0]-clean.at(-1)[0],clean[0][1]-clean.at(-1)[1])<1e-9)clean.pop();
 const sx=metric[0],sy=metric[1],screen=clean.map(p=>[p[0]*sx,p[1]*sy]),lengths=[],cumulative=[0];
 for(let i=0;i<screen.length;i++){const a=screen[i],b=screen[(i+1)%screen.length];lengths.push(Math.hypot(b[0]-a[0],b[1]-a[1]));cumulative.push(cumulative.at(-1)+lengths.at(-1));}
 const perimeter=cumulative.at(-1);
 if(clean.length<3||perimeter<=0||!regionIsSimple(clean))return null;
 let anchorArc=0,nearest=Infinity;
 for(let i=0;i<screen.length;i++){
  const a=screen[i],b=screen[(i+1)%screen.length],dx=b[0]-a[0],dy=b[1]-a[1],len=lengths[i];
  const t=len?Math.max(0,Math.min(1,((anchor[0]*sx-a[0])*dx+(anchor[1]*sy-a[1])*dy)/(len*len))):0;
  const distance=Math.hypot(anchor[0]*sx-a[0]-t*dx,anchor[1]*sy-a[1]-t*dy);
  if(distance<nearest){nearest=distance;anchorArc=cumulative[i]+t*len;}
 }
 // Preserve meaningful corners while filling the smooth stretches uniformly.
 // Include the exact grabbed position even when it was midway along an edge.
 const corners=clean.map((p,i)=>{
  const before=screen[(i+screen.length-1)%screen.length],here=screen[i],after=screen[(i+1)%screen.length];
  const ax=here[0]-before[0],ay=here[1]-before[1],bx=after[0]-here[0],by=after[1]-here[1];
  return {arc:cumulative[i],bend:Math.acos(Math.max(-1,Math.min(1,(ax*bx+ay*by)/(Math.hypot(ax,ay)*Math.hypot(bx,by)||1))))};
 }).filter(c=>c.bend>.35).sort((a,b)=>b.bend-a.bend).slice(0,30);
 const extrema=[0,1].flatMap(axis=>[clean.reduce((best,p,i)=>p[axis]<clean[best][axis]?i:best,0),clean.reduce((best,p,i)=>p[axis]>clean[best][axis]?i:best,0)]);
 const mandatory=[anchorArc%perimeter,...corners.map(c=>c.arc),...extrema.map(i=>cumulative[i])].sort((a,b)=>a-b);
 const arcs=mandatory.filter((a,i)=>!i||a-mandatory[i-1]>1e-6),slots=64-arcs.length;
 for(let i=0;i<slots;i++)arcs.push(i*perimeter/slots);
 arcs.sort((a,b)=>a-b);
 const ordered=arcs.filter((a,i)=>!i||a-arcs[i-1]>1e-6),radius=Math.max(perimeter*.18,Math.min(72,perimeter*.24));
 const sample=arc=>{let i=0;while(i<lengths.length-1&&cumulative[i+1]<arc)i++;const t=(arc-cumulative[i])/(lengths[i]||1),a=clean[i],b=clean[(i+1)%clean.length];return[a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])];};
 const samples=ordered.map(sample),weights=ordered.map(arc=>{const along=Math.abs(arc-anchorArc),distance=Math.min(along,perimeter-along);if(distance>=radius)return 0;const t=distance/radius;return(1-t*t)**2;});
 return {original,start:[...anchor],samples,weights,orientation:Math.sign(regionSignedArea(clean)),minimumArea:Math.max(.00002,Math.abs(regionSignedArea(clean))*.08)};
}
function elasticRegionPoints(gesture,end){
 if(!gesture)return null;
 const dx=end[0]-gesture.start[0],dy=end[1]-gesture.start[1];
 if(Math.abs(dx)+Math.abs(dy)<1e-12)return gesture.original.map(p=>[...p]);
 let maximum=1;
 for(let i=0;i<gesture.samples.length;i++)for(const [axis,delta]of [[0,dx],[1,dy]]){
  const move=delta*gesture.weights[i];if(!move)continue;
  maximum=Math.min(maximum,move>0?(1-gesture.samples[i][axis])/move:-gesture.samples[i][axis]/move);
 }
 const candidate=factor=>gesture.samples.map((p,i)=>[p[0]+dx*gesture.weights[i]*factor,p[1]+dy*gesture.weights[i]*factor]);
 const valid=points=>regionSignedArea(points)*gesture.orientation>=gesture.minimumArea&&regionIsSimple(points);
 let factor=Math.max(0,maximum),points=candidate(factor);
 if(!valid(points)){
  let low=0,high=factor;
  for(let i=0;i<12;i++){const mid=(low+high)/2;if(valid(candidate(mid)))low=mid;else high=mid;}
  factor=low;points=candidate(factor);
 }
 // At a hard image boundary an impossible pull is a no-op, not a new ROI.
 return factor<.001?gesture.original.map(p=>[...p]):points.map(p=>p.map(clamp));
}
function mount(host,o){
 const d=host.ownerDocument,s=o.state||{mode:'select',zoom:100,visible:true,start:null};
 s.polygonDraft ||= [];
 if(o.drawingOnly){s.visible=true;if(!['select','vertex','edge'].includes(s.mode))s.mode='select';}
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
  const shift=[(oldLeft-world.left)*scale,(oldTop-world.top)*scale*h/w];
  scroll.scrollLeft+=shift[0];scroll.scrollTop+=shift[1];
  return shift;
 };
 const regionPoint=p=>p.map(clamp);
 const previewRegion=points=>o.previewRegion?.(points);
 const root=d.createElement('section'),bar=d.createElement('div'),scroll=d.createElement('div'),stage=d.createElement('div'),image=d.createElement('img'),svg=E(d,'svg',{viewBox:'0 0 1000 1000',role:'group','aria-label':'图形原图描绘层'}),status=d.createElement('span');
 root.className='dge-overlay';bar.className='dge-overlay-tools';scroll.className='dge-overlay-viewport';stage.className='dge-overlay-stage';image.className='dge-overlay-image';image.alt='原图';svg.classList.add('dge-overlay-svg');status.className='dge-overlay-status';
 if(o.scanOnly){root.classList.add('dge-scan-only');svg.setAttribute('aria-label','原图框选层');}
 const palette=d.createElement(o.drawingOnly?'details':'section');palette.className='dge-tool-palette';
 if(o.drawingOnly){palette.open=s.toolsOpen!==false;palette.addEventListener('toggle',()=>{s.toolsOpen=palette.open;});}
 if(o.textOnly)svg.setAttribute('aria-label','文字框选层');
 const paletteTitle=d.createElement(o.drawingOnly?'summary':'h3');paletteTitle.textContent=o.scanOnly?'框选':o.textOnly?'文字工具':'绘图工具';palette.append(paletteTitle,bar);
 const viewControls=d.createElement('div');viewControls.className='dge-view-controls';viewControls.setAttribute('aria-label','视图控制');
 stage.append(image,svg);scroll.append(stage);root.append(viewControls,palette,scroll);host.append(root);
 const button=(label,key,fn,parent=bar)=>{const b=d.createElement('button');b.type='button';b.textContent=label;b.dataset.overlayTool=key;b.addEventListener('click',event=>{event.stopPropagation();if(!o.disabled?.())fn();});parent.append(b);return b;};
 for(const [key,label] of (o.scanOnly?[['select','选择 / 平移'],['bounds','图形框选'],['text_rect','文字框选']]:o.textOnly?[['select','选择 / 移动'],['text_rect','框选文字']]:o.drawingOnly?[['select','选择 / 移动'],['vertex','添加顶点'],['edge','添加边']]:[['select','选择 / 移动'],['vertex','添加顶点'],['edge','添加边'],['bounds','框选图形']])){
  button(label,key,()=>{s.mode=o.scanOnly&&s.irregular?(key==='bounds'?'graph_poly':key==='text_rect'?'text_poly':key):key;s.start=null;o.clearSelection?.();draw();});
 }
 const regionMode=d.createElement('select');
 regionMode.setAttribute('aria-label','选区方式');
 for(const [key,label] of (o.scanOnly?[['','矩形框选'],['irregular','不规则框选']]:[['','框选方式'],o.textOnly?['text_poly','不规则框选']:['graph_poly','不规则框选']])){
   const item=d.createElement('option');item.value=key;item.textContent=label;regionMode.append(item);
 }
 regionMode.addEventListener('change',()=>{
   if(o.disabled?.())return;
   if(o.scanOnly){s.irregular=regionMode.value==='irregular';const text=['text_rect','text_poly'].includes(s.mode);s.mode=text?(s.irregular?'text_poly':'text_rect'):(s.irregular?'graph_poly':'bounds');}
   else s.mode=regionMode.value||'select';s.start=null;s.polygonDraft=[];o.clearSelection?.();draw();
 });
 if(!o.drawingOnly)bar.append(regionMode);
 const commitRegion=(points,polygon)=>{
   let id;
   change(()=>{id=o.createRegion?.(points,polygon);},'region');
   if(id)void scanFigureType(points,id);
 };
 // Each independently segmented graph receives its own direction and weight
 // from OCR + visual edge evidence. Do not override this with toolbar labels.
 // Edge-level corrections in the advanced editor remain available.
 const visible=o.textOnly||o.scanOnly||o.drawingOnly?null:button('隐藏描绘','visibility',()=>{s.visible=!s.visible;draw();},viewControls);
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
 if(o.drawingOnly){originalButton.remove();opacityControl.remove();image.alt='空白画板';}
 if(o.scanOnly){originalButton.remove();opacityControl.remove();s.originalVisible=true;s.originalOpacity=1;}
 syncOriginal();
 if(o.textOnly)button('清空文字框','clear-text-region',()=>{s.textRegion=null;s.polygonDraft=[];o.selectionChanged?.(null);draw();});
 bar.append(status); // Actionable feedback appears with the tools, never below the photo.
 if(o.scanOnly){status.classList.add('dgs-source-status');status.setAttribute('role','status');}
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
 const boxOf=points=>{const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];};
 const boxPoints=b=>[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]];
 const graphPoints=g=>g.region_polygon?.length>=3?g.region_polygon:g.bbox?.length===4?boxPoints(g.bbox):null;
 const screenPoint=p=>{const scale=Math.max(1,scroll.clientWidth)*(s.zoom||100)/100;return [p[0]*scale,p[1]*scale*h/w];};
 const distance=(a,b)=>{const p=screenPoint(a),q=screenPoint(b);return Math.hypot(p[0]-q[0],p[1]-q[1]);};
 const area=points=>Math.abs(points.reduce((sum,p,i)=>{const q=points[(i+1)%points.length];return sum+p[0]*q[1]-q[0]*p[1];},0))/2;
 function simplifyStroke(points){
  // Simplify a continuous stroke in screen pixels, retaining the schema's
  // compact polygon representation without displaying editable vertices.
  const source=points.map(screenPoint);source.push(source[0]);
  let tolerance=1.5,result;
  do{
   const keep=new Set([0,source.length-1]),stack=[[0,source.length-1]];
   while(stack.length){
    const [a,b]=stack.pop(),p=source[a],q=source[b],dx=q[0]-p[0],dy=q[1]-p[1],len=dx*dx+dy*dy;
    let max=tolerance*tolerance,index=-1;
    for(let i=a+1;i<b;i++){
     const v=source[i],t=len?Math.max(0,Math.min(1,((v[0]-p[0])*dx+(v[1]-p[1])*dy)/len)):0;
     const dist=(v[0]-p[0]-t*dx)**2+(v[1]-p[1]-t*dy)**2;
     if(dist>max){max=dist;index=i;}
    }
    if(index>=0){keep.add(index);stack.push([a,index],[index,b]);}
   }
   result=[...keep].sort((a,b)=>a-b).filter(i=>i<points.length).map(i=>points[i]);
   tolerance*=1.5;
  }while(result.length>64);
  return result;
 }
 function resizeSides(points,p){
  const b=boxOf(points),scale=Math.max(1,scroll.clientWidth)*(s.zoom||100)/100;
  const sides=[['left',Math.abs(p[0]-b[0])*scale],['right',Math.abs(p[0]-b[2])*scale],
   ['top',Math.abs(p[1]-b[1])*scale*h/w],['bottom',Math.abs(p[1]-b[3])*scale*h/w]].sort((a,b)=>a[1]-b[1]);
  const chosen=[sides[0][0]],second=sides.find(row=>['left','right'].includes(row[0])!==['left','right'].includes(chosen[0]));
  if(second && sides[0][1]<12 && second[1]<12)chosen.push(second[0]);
  return chosen;
 }
 function resizedPoints(op){
  if(op.polygon)return elasticRegionPoints(op.elastic,op.end)||op.points;
  const b=boxOf(op.points),next=[...b],dx=op.end[0]-op.start[0],dy=op.end[1]-op.start[1],min=.012;
  if(op.sides.includes('left'))next[0]=Math.max(0,Math.min(b[2]-min,b[0]+dx));
  if(op.sides.includes('right'))next[2]=Math.min(1,Math.max(b[0]+min,b[2]+dx));
  if(op.sides.includes('top'))next[1]=Math.max(0,Math.min(b[3]-min,b[1]+dy));
  if(op.sides.includes('bottom'))next[3]=Math.min(1,Math.max(b[1]+min,b[3]+dy));
  return op.points.map(p=>[clamp(next[0]+(p[0]-b[0])/(b[2]-b[0])*(next[2]-next[0])),clamp(next[1]+(p[1]-b[1])/(b[3]-b[1])*(next[3]-next[1]))]);
 }
 function draw(){
  // A modal is mounted while hidden. Tool state must already be correct
  // before its first layout/image event, including on a cached-image reopen.
  if(visible)visible.textContent=s.visible?'隐藏描绘':'显示描绘';svg.classList.toggle('is-hidden',!s.visible);svg.dataset.mode=s.mode;
  svg.classList.toggle('is-deforming',active?.kind==='resize'&&active.polygon);
  regionMode.value=o.scanOnly?(s.irregular?'irregular':''):['graph_poly','text_poly'].includes(s.mode)?s.mode:'';
  for(const b of bar.querySelectorAll('[data-overlay-tool]')){const key=b.dataset.overlayTool,active=Boolean(key===s.mode||o.scanOnly&&(key==='bounds'&&s.mode==='graph_poly'||key==='text_rect'&&s.mode==='text_poly'));b.classList.toggle('is-active',active);if(['select','pan','vertex','edge','bounds','text_rect'].includes(key))b.setAttribute('aria-pressed',String(active));}
  if(!scroll.clientWidth)return;
  const g=o.textOnly||o.scanOnly?{id:o.graph?.()?.id,vertices:[],edges:[]}:o.graph()||{vertices:[],edges:[]};
  if(g)for(const v of g.vertices)if(finite(v.x)&&finite(v.y))expandWorld(v.x,v.y);
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
  const frame=(points,css,id,isText,current,irregular)=>{
    const preview=active?.kind==='resize'&&active.id===id&&active.isText===isText?resizedPoints(active):points;
    const shape=E(d,'polygon',{points:preview.map(p=>px(p).join(',')).join(' '),class:css+' dge-frame-hit'+(current?' is-current':''),'vector-effect':'non-scaling-stroke'});
    shape.dataset[isText?'textRegionId':'graphId']=id;svg.append(shape);
    const hit=E(d,'polygon',{points:preview.map(p=>px(p).join(',')).join(' '),class:'dge-frame-edge-hit'+(irregular?' dge-frame-elastic-hit':''),'vector-effect':'non-scaling-stroke'});
    hit.dataset[isText?'textRegionId':'graphId']=id;hit.dataset.frameResize='true';
    hit.style.strokeWidth=touch?'24px':'14px';svg.append(hit);
    return preview;
  };
  for(const region of o.textOnly||o.drawingOnly?[]:o.model.getDocument().graphs){
    const points=graphPoints(region);if(!points)continue;
    const preview=frame(points,region.region_polygon?.length>=3?'dge-overlay-polygon':'dge-overlay-bbox',region.id,false,region.id===g.id,region.region_polygon?.length>=3);
    if(o.scanOnly){const b=boxOf(preview),label=E(d,'text',{x:b[0]*w+6/scale,y:b[1]*h+17/scale,class:'dge-text-frame-number dge-graph-frame-number','data-frame-label-id':region.id});
      label.textContent='图形 '+String(region.id).replace(/^g/,'');label.style.fontSize=labelSize+'px';label.style.strokeWidth=4/scale+'px';svg.append(label);}
  }
  if(o.textOnly||o.scanOnly)for(const region of s.regions||[]){
    const points=frame(region.polygon,'dge-overlay-text-region'+(['empty','error'].includes(region.status)?' is-error':''),String(region.id),true,s.selectedId===region.id,region.irregular);
    const b=boxOf(points),label=E(d,'text',{x:b[0]*w+6/scale,y:b[1]*h+17/scale,class:'dge-text-frame-number'});
    label.textContent=String(region.id);label.style.fontSize=labelSize+'px';label.style.strokeWidth=4/scale+'px';svg.append(label);
  }
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
  if(active?.kind==='freehand')svg.append(E(d,'polyline',{
    points:active.points.map(p=>px(p).join(',')).join(' '),class:'dge-freehand-draft','vector-effect':'non-scaling-stroke'}));
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
  const hit=e.target.closest('[data-frame-resize]'),graphId=e.target.closest('[data-graph-id]')?.dataset.graphId,
        textId=e.target.closest('[data-text-region-id]')?.dataset.textRegionId;
  if(hit && (o.scanOnly?s.mode==='select':['select','bounds','graph_poly','text_rect','text_poly'].includes(s.mode)) && !e.shiftKey){
    const isText=o.textOnly||o.scanOnly&&!!textId;
    const region=isText?s.regions?.find(r=>r.id===Number(textId)):o.model.getDocument().graphs.find(r=>r.id===graphId);
    const points=isText?region?.polygon:region&&graphPoints(region);
    if(points){active={kind:'resize',pointer:e.pointerId,id:isText?textId:graphId,isText:!!isText,
      polygon:isText?!!region.irregular:!!region.region_polygon,start:p,end:p,points:points.map(p=>[...p]),sides:resizeSides(points,p)};
      if(active.polygon){const scale=Math.max(1,scroll.clientWidth)*(s.zoom||100)/100;active.elastic=elasticRegionStart(points,p,[scale,scale*h/w]);}
      e.preventDefault();svg.setPointerCapture?.(e.pointerId);return;}
  }
  if(s.mode==='graph_poly'||s.mode==='text_poly'){
    active={kind:'freehand',pointer:e.pointerId,start:p,end:p,points:[regionPoint(p)],graphId,textId};
    e.preventDefault();svg.setPointerCapture?.(e.pointerId);draw();return;
  }
  if(s.mode==='vertex'&&g&&!node){e.preventDefault();change(()=>o.model.addVertex(g.id,'',...p),'vertex');return;}
  if(s.mode==='edge'&&g&&node){if(!s.start){s.start=node;draw();}else{const from=s.start;s.start=null;change(()=>o.model.addEdge(g.id,{from,to:node,direction:g.directed===true?'forward':'undirected'}));}return;}
  if(s.mode==='text_rect')active={kind:'text_bounds',pointer:e.pointerId,start:p,end:p,textId};
  else if(s.mode==='pan'||(s.mode==='select'&&e.shiftKey))active={kind:'pan',pointer:e.pointerId,start:[e.clientX,e.clientY],sx:scroll.scrollLeft,sy:scroll.scrollTop};
  else if(s.mode==='bounds')active={kind:'bounds',pointer:e.pointerId,start:p,end:p,graphId};
  else if(s.mode==='select'&&handle)active={kind:'handle',pointer:e.pointerId,id:handle,start:p,end:p};
  else if(s.mode==='select'&&node)active={kind:'node',pointer:e.pointerId,id:node,start:p,end:p};
  else if(s.mode==='select'&&edge){const item=g.edges.find(e=>e.id===edge);active={kind:'edge',pointer:e.pointerId,id:edge,from:item.from,to:item.to,start:p,end:p};}
  else if(s.mode==='select')active={kind:'pan',pointer:e.pointerId,start:[e.clientX,e.clientY],sx:scroll.scrollLeft,sy:scroll.scrollTop,graphId,textId};
  if(active){e.preventDefault();svg.setPointerCapture?.(e.pointerId);}
 });
 svg.addEventListener('pointermove',e=>{
  if(pointers.has(e.pointerId))pointers.set(e.pointerId,[e.clientX,e.clientY]);
  if(base&&pointers.size>=2){const a=[...pointers.values()],distance=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]);if(base.distance>4)zoom(base.zoom*distance/base.distance);return;}
  if(!active||active.pointer!==e.pointerId)return;
  if(active.kind==='pan'){
    // A click or small finger/mouse tremor must only select. In particular,
    // it must not expand a fitted world whose left/top bounds are fractional.
    if(!active.dragging&&Math.hypot(e.clientX-active.start[0],e.clientY-active.start[1])<4)return;
    active.dragging=true;
    let x=active.sx+active.start[0]-e.clientX,y=active.sy+active.start[1]-e.clientY;
    if(x<0){const shift=expandWorld(world.left-1,world.top);active.sx+=shift[0];active.sy+=shift[1];x+=shift[0];y+=shift[1];}
    if(y<0){const shift=expandWorld(world.left,world.top-1);active.sx+=shift[0];active.sy+=shift[1];x+=shift[0];y+=shift[1];}
    if(x+scroll.clientWidth>=stage.offsetWidth)expandWorld(world.right+1,world.top);
    if(y+scroll.clientHeight>=stage.offsetHeight)expandWorld(world.left,world.bottom+1);
    scroll.scrollLeft=x;scroll.scrollTop=y;
    return;
  }
  active.end=mouse(e);
  if(active.kind==='freehand'){
    const events=e.getCoalescedEvents?.();
    for(const event of events?.length?events:[e]){
      const point=regionPoint(mouse(event));
      if(distance(active.points[active.points.length-1],point)>=2)active.points.push(point);
    }
    if(active.points.length>2048)active.points=active.points.filter((_,i)=>i%2===0);
    draw();return;
  }
  if(active.kind==='bounds'){const a=regionPoint(active.start),b=regionPoint(active.end);previewRegion([[Math.min(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.max(a[1],b[1])],[Math.min(a[0],b[0]),Math.max(a[1],b[1])]]);}
  ghost=active.kind==='node'?{vertex:active.id,pos:active.end}:active.kind==='handle'?{edge:active.id,pos:active.end}:null;draw();
 });
 function release(e,cancel=false){
  pointers.delete(e.pointerId);if(pointers.size<2)base=null;
  if(!active||active.pointer!==e.pointerId)return;const op=active;active=null;ghost=null;const g=o.graph();
  if(!cancel){
   const choose=()=>{if(op.graphId)o.selectGraph?.(op.graphId);else if(op.textId)o.selectTextRegion?.(Number(op.textId));};
   if(op.kind==='resize'){
    if(distance(op.start,op.end)>3){
      const points=resizedPoints(op);
      if(points.length===op.points.length&&points.every((p,i)=>p.every((value,j)=>Math.abs(value-op.points[i][j])<1e-10)))return draw();
      if(op.isText)o.resizeTextRegion?.(Number(op.id),points);
      else {change(()=>o.resizeRegion?.(op.id,points,op.polygon),'region');
        const owner=o.model.getDocument().graphs.find(r=>r.id===op.id);if(owner&&!owner.edges.length)void scanFigureType(points,op.id);}
    }else if(op.isText)o.selectTextRegion?.(Number(op.id));else o.selectGraph?.(op.id);
   }
   if(op.kind==='freehand'){
    op.points.push(regionPoint(mouse(e)));
    const points=simplifyStroke(op.points);
    if(points.length>=3 && area(points)>=.00002){
      if(o.textOnly||o.scanOnly&&s.mode==='text_poly'){o.selectionChanged?.(points,true);status.textContent='已框选文字范围';}else commitRegion(points,true);
    }else if(distance(op.start,op.end)<4)choose();
    else status.textContent='请用一笔画出有面积的闭合范围';
   }
   if(op.kind==='pan'&&Math.hypot(e.clientX-op.start[0],e.clientY-op.start[1])<4){if(op.graphId||op.textId)choose();else o.clearSelection?.();}
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
         o.selectionChanged?.(s.textRegion,false);status.textContent='已框选文字范围';
       }
     }else if(distance(op.start,op.end)<4)choose();
   }
   if(op.kind==='handle'&&g){const edge=g.edges.find(x=>x.id===op.id),a=g.vertices.find(x=>x.id===edge?.from),b=g.vertices.find(x=>x.id===edge?.to);if(a&&b&&finite(a.x)&&finite(a.y)&&finite(b.x)&&finite(b.y))change(()=>o.model.setEdgePath(g.id,op.id,[[a.x,a.y],op.end,[b.x,b.y]]),'geometry');else status.textContent='请先校准这条边的两个端点';}
  }draw();
 }
 svg.addEventListener('pointerup',e=>release(e));svg.addEventListener('pointercancel',e=>release(e,true));
 scroll.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();zoom(s.zoom*(e.deltaY>0?0.9:1.1));},{passive:false});
 image.onload=()=>{w=image.naturalWidth||1000;h=image.naturalHeight||1000;loaded=true;fitImage();syncOriginal();buildSampler();draw();};
 image.onerror=()=>{status.textContent='原图未能显示，可使用下方结构编辑';};image.src=o.originalUrl;zoom(s.zoom);draw();
 const observer=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(loaded&&!autoFitted)fitImage();else layoutWorld();draw();}):null;observer?.observe(scroll);observer?.observe(viewControls);
 const resetInteraction=()=>{active=null;ghost=null;base=null;pointers.clear();s.start=null;s.polygonDraft=[];scanSequence++;draw();};
 svg.addEventListener('keydown',e=>{if(e.key==='Escape')resetInteraction();});
 function getDrawingSvg(){
  // Serialize only the drawing, independently from the source photo, camera,
  // selection hit areas and editor controls. Inline computed SVG paint so the
  // exported image does not depend on this page's styles or theme.
  const output=E(d,'svg',{xmlns:NS,role:'img','aria-label':'绘图','data-source-width':w,'data-source-height':h}),defs=svg.querySelector('defs');
  const graph=o.graph?.();output.exportVertexPositions=graph?{[graph.id]:Object.fromEntries(graph.vertices.map((vertex,index)=>[vertex.id,pos(vertex,index,graph)]))}:{};
  if(defs)output.append(defs.cloneNode(true));
  const shapes=svg.querySelectorAll('.dge-overlay-edge,.dge-overlay-node');
  const bounds=[];
  const properties=['fill','stroke','stroke-width','stroke-dasharray','stroke-linecap','stroke-linejoin','paint-order','font-family','font-size','font-weight','text-anchor','opacity'];
  for(const original of shapes){
   try{const b=original.getBBox();if(b.width||b.height)bounds.push(b);}catch(_){}
   const clone=original.cloneNode(true),source=[original,...original.querySelectorAll('*')],copies=[clone,...clone.querySelectorAll('*')];
   copies.forEach((node,index)=>{const style=d.defaultView.getComputedStyle(source[index]);for(const name of properties)node.style.setProperty(name,style.getPropertyValue(name));node.removeAttribute('tabindex');node.removeAttribute('data-vertex-id');node.removeAttribute('data-edge-id');});
   clone.querySelectorAll('.dge-overlay-hit,.dge-overlay-node-hit,.dge-overlay-handle').forEach(node=>node.remove());
   output.append(clone);
  }
  let x=0,y=0,width=1000,height=700;
  if(bounds.length){const scale=Math.max(.0001,svg.getBoundingClientRect().width/((world.right-world.left)*w)),padding=32/scale;
   x=Math.min(...bounds.map(b=>b.x))-padding;y=Math.min(...bounds.map(b=>b.y))-padding;
   width=Math.max(64,Math.max(...bounds.map(b=>b.x+b.width))-x+padding);height=Math.max(64,Math.max(...bounds.map(b=>b.y+b.height))-y+padding);}
  output.setAttribute('viewBox',[x,y,width,height].join(' '));output.setAttribute('width',String(Math.ceil(width)));output.setAttribute('height',String(Math.ceil(height)));
  const background=E(d,'rect',{x,y,width,height,fill:'#ffffff'});output.insertBefore(background,output.firstChild);
  return output;
 }
 return {refresh:draw,resetInteraction,state:s,getDrawingSvg,destroy(){observer?.disconnect();image.onload=null;image.onerror=null;host.replaceChildren();}};
}
root.DMateGraphOverlay={mount,elasticRegionStart,elasticRegionPoints};if(typeof module!=='undefined'&&module.exports)module.exports={mount,elasticRegionStart,elasticRegionPoints};
})(typeof window!=='undefined'?window:globalThis);
