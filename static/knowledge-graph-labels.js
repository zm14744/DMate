/* Shared label measurement and edge geometry for the online/offline graph and PNG painter. */
(function(root){
"use strict";
const documents=new WeakMap();
function context(doc=root.document){
 if(documents.has(doc))return documents.get(doc);
 const canvas=doc.createElement('canvas'),ctx=canvas.getContext('2d');
 const probe=doc.createElement('div');probe.setAttribute('aria-hidden','true');probe.setAttribute('data-i18n-content','');
 probe.style.cssText='position:fixed;left:-100000px;top:0;visibility:hidden;pointer-events:none;width:max-content;height:auto;';
 const span=doc.createElement('span');span.style.cssText='display:block;position:relative;width:max-content;white-space:pre;padding:0;border:0;margin:0;';
 const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width','1');svg.setAttribute('height','1');
 const text=doc.createElementNS(svg.namespaceURI,'text');text.setAttribute('x','0');text.setAttribute('y','0');text.setAttribute('text-anchor','start');svg.append(text);probe.append(span,svg);doc.body.append(probe);
 const value={doc,ctx,span,text,cache:new Map()};documents.set(doc,value);
 doc.fonts?.addEventListener?.('loadingdone',()=>value.cache.clear());
 return value;
}
function fontScale(doc=root.document){return parseFloat(doc.defaultView.getComputedStyle(doc.documentElement).getPropertyValue('--font-scale'))||1;}
function fontFamily(doc=root.document){return doc.defaultView.getComputedStyle(doc.body).fontFamily||'system-ui, sans-serif';}
function fontStyle(element,font){
 // The probe is measured at 1x; preserve the same glyph advances in a zoomed SVG.
 if(element.namespaceURI==='http://www.w3.org/2000/svg')element.style.textRendering='geometricPrecision';
 for(const [key,value] of Object.entries({'font-family':font.family,'font-size':font.size+'px','font-weight':String(font.weight),'font-style':'normal','font-kerning':'normal','letter-spacing':'0px','line-height':font.lineHeight+'px','text-transform':'none'}))element.style.setProperty(key,value,'important');
}
function measure(value,font,doc){
 const c=context(doc),key=[font.family,font.size,font.weight,font.lineHeight,value].join('\u0001');
 if(c.cache.has(key))return c.cache.get(key);
 if(!value)return {advance:0,width:0,canvas:{x:0,y:0,width:0,height:0},svg:{x:0,y:0,width:0,height:0},html:{x:0,y:0,width:0,height:0}};
 c.ctx.font=`${font.weight} ${font.size}px ${font.family}`;c.ctx.textAlign='left';c.ctx.textBaseline='alphabetic';c.ctx.fontKerning='normal';
 const metric=c.ctx.measureText(value),ascent=Number.isFinite(metric.actualBoundingBoxAscent)?metric.actualBoundingBoxAscent:font.size*.8,descent=Number.isFinite(metric.actualBoundingBoxDescent)?metric.actualBoundingBoxDescent:0;
 fontStyle(c.span,font);fontStyle(c.text,font);c.span.textContent=value;c.text.textContent=value;
 const range=doc.createRange();range.selectNodeContents(c.span);const html=range.getBoundingClientRect(),box=c.span.getBoundingClientRect(),svg=c.text.getBBox();range.detach();
 const result={advance:metric.width,
  canvas:{x:-(metric.actualBoundingBoxLeft||0),y:-ascent,width:(metric.actualBoundingBoxLeft||0)+(Number.isFinite(metric.actualBoundingBoxRight)?metric.actualBoundingBoxRight:metric.width),height:ascent+descent},
  svg:{x:svg.x,y:svg.y,width:svg.width,height:svg.height},
  html:{x:html.x-box.x,y:html.y-box.y,width:html.width,height:html.height}};
 result.width=Math.max(result.advance,result.canvas.width,result.svg.width,result.html.width);
 c.cache.set(key,result);return result;
}
function graphemes(text,locale){return root.Intl?.Segmenter?[...new Intl.Segmenter(locale,{granularity:'grapheme'}).segment(text)].map(s=>s.segment):Array.from(text);}
function words(text,locale){
 if(/^en(?:-|$)/i.test(locale))return text.match(/\s+|\S+/gu)||[];
 const segments=root.Intl?.Segmenter?[...new Intl.Segmenter(locale,{granularity:'word'}).segment(text)].map(s=>s.segment):text.match(/\s+|[A-Za-z0-9]+(?:[’'_-][A-Za-z0-9]+)*|[^\s]/gu)||[];
 const result=[];
 for(const token of segments){
  if(/^[,.;:!?，。；：！？、)\]】}”’]+$/u.test(token)&&result.length&&!/^\s+$/u.test(result[result.length-1]))result[result.length-1]+=token;
  else result.push(token);
 }
 return result;
}
function wrap(value,font,maxWidth,doc,locale){
 const lines=[];
 for(const paragraph of String(value||'').replace(/\r\n?/g,'\n').split('\n')){
  let line='',space='';
  const flush=()=>{if(line)lines.push(line);line='';space='';};
  for(const token of words(paragraph.trim(),locale)){
   if(/^\s+$/u.test(token)){if(line)space=' ';continue;}
   const candidate=line+space+token;
   if(measure(candidate,font,doc).width<=maxWidth){line=candidate;space='';continue;}
   flush();
   if(measure(token,font,doc).width<=maxWidth){line=token;continue;}
   for(const glyph of graphemes(token,locale)){
    if(line&&measure(line+glyph,font,doc).width>maxWidth)flush();
    line+=glyph;
   }
  }
  flush();
 }
 return lines.length?lines:[''];
}
function block(lines,font,kind){
 const rects=lines.map(line=>line.metrics[kind]);
 const top=Math.min(...rects.map((r,i)=>i*font.lineHeight+r.y));
 const bottom=Math.max(...rects.map((r,i)=>i*font.lineHeight+r.y+r.height));
 return {height:bottom-top,lines:lines.map((line,i)=>({...line,x:-(rects[i].x+rects[i].width/2),y:i*font.lineHeight-top}))};
}
function layout(label,badge='',options={}){
 const doc=options.document||root.document,scale=options.fontScale??fontScale(doc),family=options.fontFamily||fontFamily(doc);
 const width=options.width||144,paddingX=(options.paddingX??10)*scale,paddingY=(options.paddingY??10)*scale,gap=(options.gap??5)*scale;
 const title={size:(options.titleSize||13)*scale,weight:options.weight||600,family};title.lineHeight=Math.ceil(title.size*1.3);
 const badgeFont={size:(options.badgeSize||10)*scale,weight:options.badgeWeight||500,family};badgeFont.lineHeight=Math.ceil(badgeFont.size*1.3);
 const available=Math.max(12,width-2*paddingX),locale=options.language||doc.documentElement.lang||'zh-CN';
 const measuredLines=(value,font)=>{
  const strings=wrap(value,font,available,doc,locale);
  let lines=strings.map(text=>({text,metrics:measure(text,font,doc)}));
  const lineHeight=Math.ceil(Math.max(font.lineHeight,...lines.flatMap(line=>['svg','html','canvas'].map(kind=>line.metrics[kind].height+2*scale))));
  if(lineHeight!==font.lineHeight){font.lineHeight=lineHeight;lines=strings.map(text=>({text,metrics:measure(text,font,doc)}));}
  return lines;
 };
 const titleLines=measuredLines(label,title);
 const badgeLines=badge?measuredLines(badge,badgeFont):[];
 const result={label:String(label||''),badge:String(badge||''),width,paddingX,paddingY,gap,title,badgeFont,lines:titleLines.map(l=>l.text),badgeLines:badgeLines.map(l=>l.text)};
 for(const kind of ['svg','html','canvas']){
  const main=block(titleLines,title,kind),secondary=badgeLines.length?block(badgeLines,badgeFont,kind):{height:0,lines:[]};
  result[kind]={height:main.height+(badgeLines.length?gap+secondary.height:0),title:main.lines,badge:secondary.lines.map(line=>({...line,y:line.y+main.height+gap}))};
 }
 result.height=Math.ceil(Math.max(options.minHeight||0,...['svg','html','canvas'].map(kind=>result[kind].height+2*paddingY)));
 return result;
}
function prepare(nodes,options){
 const layouts=new Map();let height=options.minHeight||0;
 for(const node of nodes){const value=layout(options.label(node),options.badge?.(node)||'',options);layouts.set(node.id,value);height=Math.max(height,value.height);}
 return {width:options.width,height,layouts};
}
function metadata(node,value){node.dataset.label=value.label;node.dataset.badge=value.badge;node.dataset.labelLines=JSON.stringify(value.lines);}
function applySvg(group,value,options={}){
 const doc=group.ownerDocument,width=options.width||value.width,height=options.height||value.height,top=(height-value.svg.height)/2;
 metadata(group,value);
 for(const [kind,lines,font,color] of [['label',value.svg.title,value.title,options.titleColor||'#f8fafc'],['badge',value.svg.badge,value.badgeFont,options.badgeColor||'#e2e8f0']]){
  if(!lines.length)continue;
  const text=doc.createElementNS('http://www.w3.org/2000/svg','text');text.setAttribute('class','kg-node-'+kind);text.setAttribute('fill',color);text.setAttribute('data-i18n-content','');text.setAttribute('text-anchor','start');text.style.setProperty('text-anchor','start','important');fontStyle(text,font);
  for(const line of lines){const span=doc.createElementNS(text.namespaceURI,'tspan');span.setAttribute('x',String(width/2+line.x));span.setAttribute('y',String(top+line.y));span.textContent=line.text;text.append(span);}
  group.append(text);
 }
}
function applyHtml(button,value){
 const doc=button.ownerDocument,wrapper=doc.createElement('span');wrapper.className='kg-mobile-node-labels';wrapper.style.cssText=`position:absolute;left:0;right:0;top:50%;height:${value.html.height}px;transform:translateY(-50%);pointer-events:none;`;
 metadata(button,value);button.style.padding='0';
 for(const [kind,lines,font] of [['name',value.html.title,value.title],['badge',value.html.badge,value.badgeFont]]){
  if(!lines.length)continue;
  const container=doc.createElement('span');container.className='kg-mobile-node-'+kind;container.setAttribute('data-i18n-content','');container.style.cssText='position:absolute;inset:0;overflow:visible!important;white-space:pre!important;text-overflow:clip!important;word-break:normal!important;';fontStyle(container,font);
  for(const line of lines){const span=doc.createElement('span');span.className='kg-label-line';span.textContent=line.text;span.style.cssText=`position:absolute;display:block;left:50%;top:${line.y}px;margin-left:${line.x}px;width:max-content;max-width:none;white-space:pre;line-height:${font.lineHeight}px;`;fontStyle(span,font);container.append(span);}
  wrapper.append(container);
 }
 button.append(wrapper);
}
function paint(ctx,value,x,y,options={}){
 const width=options.width||value.width,height=options.height||value.height,top=y+(height-value.canvas.height)/2;
 ctx.save();ctx.textAlign='left';ctx.textBaseline='alphabetic';ctx.fontKerning='normal';
 for(const [lines,font,color] of [[value.canvas.title,value.title,options.titleColor||'#ffffff'],[value.canvas.badge,value.badgeFont,options.badgeColor||'#e2e8f0']]){
  ctx.font=`${font.weight} ${font.size}px ${font.family}`;ctx.fillStyle=color;
  for(const line of lines)ctx.fillText(line.text,x+width/2+line.x,top+line.y);
 }
 ctx.restore();
}
// Route in a horizontal coordinate system. For a vertical graph crossSize is
// the stage width; the normal nodeWidth/nodeHeight arguments remain unchanged.
// Reflecting the main axis also supports both top-to-bottom and bottom-to-top.
function routeConnection(fromId,toId,start,end,positions,nodeWidth,nodeHeight,crossSize,vertical=false){
 const main=point=>vertical?point.y:point.x;
 const sign=main(end)<main(start)?-1:1;
 const point=point=>[sign*main(point),vertical?point.x:point.y];
 const restore=([x,y])=>vertical?[y,sign*x]:[sign*x,y];
 const width=vertical?nodeHeight:nodeWidth,height=vertical?nodeWidth:nodeHeight;
 const first=point(start),last=point(end),limit=Math.max(24,Number(crossSize)||24);
 const rectangles=[];
 let source=null,target=null;
 for(const [id,pos] of positions){
  const axis=vertical?pos.y:pos.x,cross=vertical?pos.x:pos.y;
  const left=sign>0?axis:-(axis+width);
  const own=id===fromId||id===toId,padding=own?0:5;
  const rect={left:left-padding,right:left+width+padding,top:cross-padding,bottom:cross+height+padding};
  rectangles.push(rect);
  if(id===fromId)source=rect;
  if(id===toId)target=rect;
 }
 const startDirection=source&&Math.abs(first[0]-source.left)<Math.abs(first[0]-source.right)?-1:1;
 const endDirection=target&&Math.abs(last[0]-target.right)<Math.abs(last[0]-target.left)?1:-1;
 const between=(a,b,t)=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];
 const split=(a,b,c,d)=>{
  const ab=between(a,b,.5),bc=between(b,c,.5),cd=between(c,d,.5);
  const abc=between(ab,bc,.5),bcd=between(bc,cd,.5),mid=between(abc,bcd,.5);
  return [[a,ab,abc,mid],[mid,bcd,cd,d]];
 };
 const overlaps=(a,b,c,d,rect)=>{
  const xs=[a[0],b[0],c[0],d[0]],ys=[a[1],b[1],c[1],d[1]];
  return Math.max(...xs)>rect.left+.001&&Math.min(...xs)<rect.right-.001
   &&Math.max(...ys)>rect.top+.001&&Math.min(...ys)<rect.bottom-.001;
 };
 // Recursive control-hull bounds conservatively certify the entire curve,
 // rather than missing a narrow obstacle between a handful of samples.
 const hits=(curve,rect,depth=0)=>{
  if(!overlaps(...curve,rect))return false;
  if(depth>=12)return true;
  const halves=split(...curve);
  return hits(halves[0],rect,depth+1)||hits(halves[1],rect,depth+1);
 };
 const clearCurve=curve=>{
  const ys=curve.map(point=>point[1]);
  return Math.min(...ys)>=0&&Math.max(...ys)<=limit
   &&!rectangles.some(rect=>hits(curve,rect));
 };
 const clearRoute=segments=>{
  let previous=first;
  for(const segment of segments){
   const curve=[previous,segment.slice(0,2),segment.slice(2,4),segment.slice(4,6)];
   if(!clearCurve(curve))return false;
   previous=curve[3];
  }
  return true;
 };
 const finish=segments=>({type:'curves',x1:start.x,y1:start.y,segments:segments.map(segment=>[
  ...restore(segment.slice(0,2)),...restore(segment.slice(2,4)),...restore(segment.slice(4,6))
 ])});
 const bow=(a,b,amount)=>{
  const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
  if(length<.0001)return [];
  const along=[dx/length,dy/length],normal=[-along[1],along[0]];
  const mid=[(a[0]+b[0])/2+normal[0]*amount,(a[1]+b[1])/2+normal[1]*amount];
  const handle=length*.25;
  return [[a[0]+along[0]*handle,a[1]+along[1]*handle,mid[0]-along[0]*handle,mid[1]-along[1]*handle,...mid],
   [mid[0]+along[0]*handle,mid[1]+along[1]*handle,b[0]-along[0]*handle,b[1]-along[1]*handle,...b]];
 };
 const dx=last[0]-first[0],dy=last[1]-first[1],bend=Math.max(16,Math.abs(dx)*.42);
 if(Math.abs(dy)>=10){
  const direct=[[first[0]+startDirection*bend,first[1],last[0]+endDirection*bend,last[1],...last]];
  if(clearRoute(direct))return finish(direct);
 }
 if(startDirection===1&&endDirection===-1&&dx>0){
  const amplitude=Math.min(22,Math.max(8,dx*.1));
  for(const direction of [1,-1]){
   const direct=bow(first,last,amplitude*direction);
   if(clearRoute(direct))return finish(direct);
  }
 }

 // Search clear orthogonal corridors, then round every corner and bow every
 // corridor span. The orthogonal scaffold never reaches SVG or Canvas.
 const stub=Math.min(12,Math.max(4,Math.abs(dx)*.2));
 const from=[first[0]+startDirection*stub,first[1]],to=[last[0]+endDirection*stub,last[1]];
 const xs=[from[0],to[0]],ys=[from[1],to[1],6,limit-6];
 for(const rect of rectangles){
  xs.push(rect.left-10,rect.right+10);
  for(const y of [rect.top-10,rect.bottom+10])if(y>1&&y<limit-1)ys.push(y);
 }
 const unique=values=>[...new Set(values)].sort((a,b)=>a-b);
 const xx=unique(xs),yy=unique(ys),nx=xx.length,ny=yy.length;
 const sourceIndex=yy.indexOf(from[1])*nx+xx.indexOf(from[0]);
 const targetIndex=yy.indexOf(to[1])*nx+xx.indexOf(to[0]);
 const distances=new Float64Array(nx*ny*3).fill(Infinity),prior=new Int32Array(nx*ny*3).fill(-1),heap=[];
 const push=(cost,id)=>{
  let index=heap.length;
  const entry={cost,id};
  heap.push(entry);
  while(index){
   const parent=(index-1)>>1;
   if(heap[parent].cost<=cost)break;
   heap[index]=heap[parent];
   index=parent;
  }
  heap[index]=entry;
 };
 const pop=()=>{
  const firstEntry=heap[0],lastEntry=heap.pop();
  if(!heap.length)return firstEntry;
  let index=0;
  while(index*2+1<heap.length){
   let child=index*2+1;
   if(child+1<heap.length&&heap[child+1].cost<heap[child].cost)child++;
   if(lastEntry.cost<=heap[child].cost)break;
   heap[index]=heap[child];
   index=child;
  }
  heap[index]=lastEntry;
  return firstEntry;
 };
 const clearLine=(a,b)=>!rectangles.some(rect=>a[0]===b[0]
  ?a[0]>rect.left+.001&&a[0]<rect.right-.001&&Math.max(a[1],b[1])>rect.top+.001&&Math.min(a[1],b[1])<rect.bottom-.001
  :a[1]>rect.top+.001&&a[1]<rect.bottom-.001&&Math.max(a[0],b[0])>rect.left+.001&&Math.min(a[0],b[0])<rect.right-.001);
 distances[sourceIndex*3]=0;push(0,sourceIndex*3);
 let found=-1;
 while(heap.length){
  const entry=pop(),id=entry.id;if(entry.cost>distances[id]+.001)continue;
  const group=Math.floor(id/3),direction=id%3,x=group%nx,y=Math.floor(group/nx);
  if(group===targetIndex){found=id;break;}
  for(const [sx,sy,nextDirection] of [[-1,0,1],[1,0,1],[0,-1,2],[0,1,2]]){
   const ax=x+sx,ay=y+sy;if(ax<0||ay<0||ax>=nx||ay>=ny)continue;
   const nextGroup=ay*nx+ax;
   if((group===sourceIndex&&sx*startDirection<0)||(nextGroup===targetIndex&&sx*endDirection>0))continue;
   const a=[xx[x],yy[y]],b=[xx[ax],yy[ay]];
   if(!clearLine(a,b))continue;
   const next=nextGroup*3+nextDirection,distance=Math.abs(b[0]-a[0])+Math.abs(b[1]-a[1]);
   const cost=entry.cost+distance+(direction&&direction!==nextDirection?22:0)+(sx<0?distance*.15:0);
   if(cost>=distances[next]-.001)continue;
   distances[next]=cost;prior[next]=id;push(cost,next);
  }
 }
 let points=[];
 if(found>=0){
  for(let id=found;id>=0;id=prior[id]){const group=Math.floor(id/3);points.push([xx[group%nx],yy[Math.floor(group/nx)]]);}
  points.reverse();
 }else{
  points=[from,[from[0],6],[to[0],6],to];
 }
 points=[first,...points,last];
 const simplified=[];
 for(const current of points){
  const count=simplified.length,previous=simplified[count-1];
  if(previous&&Math.hypot(current[0]-previous[0],current[1]-previous[1])<.0001)continue;
  if(count>=2){const a=simplified[count-2],b=simplified[count-1];
   const collinear=(a[0]===b[0]&&b[0]===current[0])||(a[1]===b[1]&&b[1]===current[1]);
   if(collinear&&(b[0]-a[0])*(current[0]-b[0])+(b[1]-a[1])*(current[1]-b[1])>0){simplified[count-1]=current;continue;}
  }
  simplified.push(current);
 }
 const unit=(a,b)=>{const length=Math.hypot(b[0]-a[0],b[1]-a[1]);return [(b[0]-a[0])/length,(b[1]-a[1])/length,length];};
 for(const radius of [8,5,2,1,.25]){
  const segments=[];let previous=simplified[0],valid=true;
  const span=(a,b)=>{
   const length=Math.hypot(b[0]-a[0],b[1]-a[1]);
   if(length<.0001)return true;
   for(const amount of [Math.min(4,length*.16),Math.min(1,length*.08)])for(const side of [1,-1]){
    const curved=bow(a,b,side*amount);let p=a;
    if(curved.every(segment=>{const clear=clearCurve([p,segment.slice(0,2),segment.slice(2,4),segment.slice(4,6)]);p=segment.slice(4,6);return clear;})){
     segments.push(...curved);return true;
    }
   }
   return false;
  };
  for(let index=1;index<simplified.length-1;index++){
   const center=simplified[index],before=unit(simplified[index-1],center),after=unit(center,simplified[index+1]);
   const size=Math.min(radius,before[2]/3,after[2]/3),k=.5522847498;
   const enter=[center[0]-before[0]*size,center[1]-before[1]*size],leave=[center[0]+after[0]*size,center[1]+after[1]*size];
   if(!span(previous,enter)){valid=false;break;}
   const turn=[enter[0]+before[0]*size*k,enter[1]+before[1]*size*k,leave[0]-after[0]*size*k,leave[1]-after[1]*size*k,...leave];
   if(!clearCurve([enter,turn.slice(0,2),turn.slice(2,4),leave])){valid=false;break;}
   segments.push(turn);previous=leave;
  }
  if(valid&&span(previous,simplified[simplified.length-1])&&clearRoute(segments))return finish(segments);
 }
 // An overlapping/invalid node layout has no guaranteed clear passage. Keep a
 // genuinely curved edge visible rather than changing or omitting graph data.
 return finish(bow(first,last,Math.max(1,Math.min(8,limit/20))));
}
function routeSvgD(route){
 return `M ${route.x1} ${route.y1} `+route.segments.map(segment=>`C ${segment.slice(0,2).join(' ')} ${segment.slice(2,4).join(' ')} ${segment.slice(4,6).join(' ')}`).join(' ');
}
function strokeCanvasRoute(ctx,route){
 ctx.beginPath();ctx.moveTo(route.x1,route.y1);
 for(const segment of route.segments)ctx.bezierCurveTo(...segment);
 ctx.stroke();
}
root.DMateKnowledgeGraphLabels={layout,prepare,applySvg,applyHtml,paint,fontScale,fontFamily,routeConnection,routeSvgD,strokeCanvasRoute};
})(typeof window!=='undefined'?window:globalThis);
