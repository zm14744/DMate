/* Shared label measurement and edge geometry for the online/offline graph and PNG painter. */
(function(root){
"use strict";
const documents=new WeakMap();
const connectionPaths=new Map();
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
 const doc=options.document||root.document;
 const layoutOptions={...options,document:doc,fontScale:options.fontScale??fontScale(doc),fontFamily:options.fontFamily||fontFamily(doc)};
 const layouts=new Map();let height=options.minHeight||0;
 for(const node of nodes){const value=layout(options.label(node),options.badge?.(node)||'',layoutOptions);layouts.set(node.id,value);height=Math.max(height,value.height);}
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
// Keep the desktop rank membership and original in-rank data order in every
// orientation. Mobile changes the reading direction, not the graph structure.
function groupRanks(nodes,levels){
 const orderedNodes=nodes.slice(),columns=new Map();
 for(const node of orderedNodes){
  const level=levels.get(node.id)||0;
  if(!columns.has(level))columns.set(level,[]);
  columns.get(level).push(node);
 }
 return {orderedNodes,columns,columnKeys:[...columns.keys()].sort((a,b)=>a-b)};
}
// Route in a horizontal coordinate system. For a vertical graph crossSize is
// the stage width; the normal nodeWidth/nodeHeight arguments remain unchanged.
// Reflecting the main axis also supports both top-to-bottom and bottom-to-top.
function createRoutingSession(){return {cells:new Map()};}
function routeConnection(fromId,toId,start,end,positions,nodeWidth,nodeHeight,crossSize,vertical=false,session=null){
 const main=point=>vertical?point.y:point.x;
 const sign=main(end)<main(start)?-1:1;
 const point=point=>[sign*main(point),vertical?point.x:point.y];
 const restore=([x,y])=>vertical?[y,sign*x]:[sign*x,y];
 const width=vertical?nodeHeight:nodeWidth,height=vertical?nodeWidth:nodeHeight;
 const first=point(start),last=point(end),limit=Math.max(24,Number(crossSize)||24);
 const rectangles=[];
 for(const [id,pos] of positions){
  const axis=vertical?pos.y:pos.x,cross=vertical?pos.x:pos.y;
  const left=sign>0?axis:-(axis+width);
  const own=id===fromId||id===toId,padding=own?0:5;
  const rect={left:left-padding,right:left+width+padding,top:cross-padding,bottom:cross+height+padding};
  rectangles.push(rect);
 }
 const between=(a,b,t)=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];
 const split=(a,b,c,d)=>{
  const ab=between(a,b,.5),bc=between(b,c,.5),cd=between(c,d,.5);
  const abc=between(ab,bc,.5),bcd=between(bc,cd,.5),mid=between(abc,bcd,.5);
  return [[a,ab,abc,mid],[mid,bcd,cd,d]];
 };
 const curveBounds=([a,b,c,d])=>({
  left:Math.min(a[0],b[0],c[0],d[0]),right:Math.max(a[0],b[0],c[0],d[0]),
  top:Math.min(a[1],b[1],c[1],d[1]),bottom:Math.max(a[1],b[1],c[1],d[1])
 });
 const overlaps=(bounds,rect)=>bounds.right>rect.left+.001&&bounds.left<rect.right-.001
  &&bounds.bottom>rect.top+.001&&bounds.top<rect.bottom-.001;
 // Recursive control-hull bounds conservatively certify the entire curve,
 // rather than missing a narrow obstacle between a handful of samples.
 const hits=(curve,rect,depth,bounds=curveBounds(curve))=>{
  if(!overlaps(bounds,rect))return false;
  if(depth>=12)return true;
  const halves=split(...curve);
  return hits(halves[0],rect,depth+1)||hits(halves[1],rect,depth+1);
 };
 const clearCurve=curve=>{
  const bounds=curveBounds(curve);
  return bounds.top>=0&&bounds.bottom<=limit&&!rectangles.some(rect=>hits(curve,rect,0,bounds));
 };
 const clearRoute=(segments,origin=first)=>{
  let previous=origin;
  for(const segment of segments){
   const curve=[previous,segment.slice(0,2),segment.slice(2,4),segment.slice(4,6)];
   if(!clearCurve(curve))return false;
   previous=curve[3];
  }
  return true;
 };
 const sampleRoute=segments=>{
  const samples=[];let previous=first,total=0;
  for(const segment of segments){
   const b=segment.slice(0,2),c=segment.slice(2,4),d=segment.slice(4,6);
   const length=Math.hypot(b[0]-previous[0],b[1]-previous[1])+Math.hypot(c[0]-b[0],c[1]-b[1])+Math.hypot(d[0]-c[0],d[1]-c[1]);
   const steps=Math.max(2,Math.ceil(length/8));
   for(let index=samples.length?1:0;index<=steps;index++){
    const t=index/steps,u=1-t;
    const p=[u*u*u*previous[0]+3*u*u*t*b[0]+3*u*t*t*c[0]+t*t*t*d[0],u*u*u*previous[1]+3*u*u*t*b[1]+3*u*t*t*c[1]+t*t*t*d[1]];
    const derivative=[3*u*u*(b[0]-previous[0])+6*u*t*(c[0]-b[0])+3*t*t*(d[0]-c[0]),3*u*u*(b[1]-previous[1])+6*u*t*(c[1]-b[1])+3*t*t*(d[1]-c[1])];
    const size=Math.hypot(...derivative)||1,world=restore(p);
    const tangent=vertical?[derivative[1]/size,sign*derivative[0]/size]:[sign*derivative[0]/size,derivative[1]/size];
    const prior=samples.at(-1),px=prior?.x??world[0],py=prior?.y??world[1];
    const step=Math.hypot(world[0]-px,world[1]-py);
    total+=step;samples.push({x:world[0],y:world[1],px,py,tx:tangent[0],ty:tangent[1],distance:total,step});
   }
   previous=d;
  }
  // Short, unavoidable port fan-out is not a shared routing corridor.
  return samples.filter(sample=>sample.distance>12&&sample.distance<total-12);
 };
 const key=(x,y)=>Math.floor(x/8)+','+Math.floor(y/8);
 // An edge scores several candidates against the same already-routed edges.
 const nearbyCells=new Map();
 const nearby=(x,y)=>{
  const cell=x+','+y;
  if(nearbyCells.has(cell))return nearbyCells.get(cell);
  const lists=[];
  for(let dx=-2;dx<=2;dx++)for(let dy=-2;dy<=2;dy++){
   const list=session.cells.get((x+dx)+','+(y+dy));
   if(list)lists.push(list);
  }
  nearbyCells.set(cell,lists);
  return lists;
 };
 const occupied=samples=>{
  if(!session?.cells?.size)return 0;
  let score=0;const runs=[0,0,0],limits=[6,1,.4],weights=[1,20,1000];
  for(const sample of samples){
   let nearest=Infinity;
   const x=Math.floor(sample.x/8),y=Math.floor(sample.y/8);
   for(const list of nearby(x,y)){
    for(const previous of list){
     if(Math.abs(sample.tx*previous.tx+sample.ty*previous.ty)<.99756||!previous.step)continue;
     const vx=previous.x-previous.px,vy=previous.y-previous.py;
     const t=Math.max(0,Math.min(1,((sample.x-previous.px)*vx+(sample.y-previous.py)*vy)/(previous.step*previous.step)));
     nearest=Math.min(nearest,Math.hypot(sample.x-previous.px-t*vx,sample.y-previous.py-t*vy));
    }
   }
   // A shared centerline costs much more than a brief crossing or two
   // distinguishable nearby curves. Use segment distances, not sample phase.
   if(nearest<6)score+=sample.step*.12;
   for(let i=0;i<limits.length;i++){
    runs[i]=nearest<limits[i]?runs[i]+sample.step:0;
    if(runs[i]>24)score+=sample.step*weights[i];
   }
  }
  return score;
 };
 const finish=(segments,samples)=>{
  if(session?.cells){
   for(const sample of samples||sampleRoute(segments)){
    const cell=key((sample.x+sample.px)/2,(sample.y+sample.py)/2),list=session.cells.get(cell)||[];
    list.push(sample);session.cells.set(cell,list);
   }
  }
  return {type:'curves',x1:start.x,y1:start.y,segments:segments.map(segment=>[
   ...restore(segment.slice(0,2)),...restore(segment.slice(2,4)),...restore(segment.slice(4,6))
  ])};
 };
 let bestRoute=null,bestScore=Infinity,bestSamples=null;
 const scoreCandidate=(segments,shapeCost)=>{
  const samples=session?.cells?.size?sampleRoute(segments):null;
  const score=shapeCost+occupied(samples||[]);
  if(score<bestScore){bestRoute=segments;bestScore=score;bestSamples=samples;}
  return score<.001;
 };
 const consider=(segments,shapeCost=0)=>shapeCost<bestScore&&segments.length>0
  &&clearRoute(segments)&&scoreCandidate(segments,shapeCost);
 // Short relations follow one bend. Keep the control points in order on
 // the main axis so a connection always advances toward the next level.
 const connect=(a,b,arc=0,curvature=.42,skew=0)=>{
  const distance=b[0]-a[0],reach=distance*curvature,shift=distance*skew;
  return [a[0]+reach+shift,a[1]+arc,b[0]-reach+shift,b[1]+arc,...b];
 };
 const shallow=Math.abs(last[1]-first[1])<12;
 const direct=[connect(first,last,shallow?2.5:0)];
 if(consider(direct))return finish(bestRoute,bestSamples);
 // Only crowded direct paths need a different handle length or one shallow
 // arch. All controls stay ordered; no local bows or backwards twists appear.
 if(session?.cells?.size){
  for(const [index,curvature] of [.32,.5,.24].entries())consider([connect(first,last,shallow?2.5:0,curvature)],1+index);
  // Moving both handles along the main axis separates broad sideways sweeps
  // without adding a bend or reversing the relation's reading direction.
  for(const [index,skew] of [.12,-.12,.22,-.22,.32,-.32].entries())
   consider([connect(first,last,shallow?2.5:0,.42,skew)],1+index*.25);
 }
 if(shallow){
  const arcs=session?.cells?.size?[-2.5,10.5,-10.5,18.5,-18.5,26.5,-26.5]:[-2.5];
  for(const arc of arcs)consider([connect(first,last,arc)],Math.abs(arc)*.15);
 }
 // A clear single curve stays a single curve. A brief acute crossing must
 // never send a relation out to a distant corridor and back again.
 if(bestRoute)return finish(bestRoute,bestSamples);

 // A blocked relation changes lanes in the two rank gaps next to its
 // endpoints. Between them it follows one clear channel, past any number
 // of ranks, without weaving around their individual cards.
 const distance=last[0]-first[0];
 const entryLimit=Math.max(first[0],...rectangles.map(rect=>rect.right)
  .filter(x=>x>first[0]&&x<last[0]));
 const exitLimit=Math.min(last[0],...rectangles.map(rect=>rect.left)
  .filter(x=>x>first[0]&&x<last[0]));
 const depart=first[0]+Math.min(distance*.4,exitLimit-first[0]);
 const arrive=last[0]-Math.min(distance*.4,last[0]-entryLimit);
 const center=(first[1]+last[1])/2;
 const baseLanes=[6,limit-6,center,...rectangles.flatMap(rect=>[rect.top-6,rect.bottom+6])];
 const offsets=session?.cells?.size?[0,-8,8,-16,16,-24,24]:[0];
 const lanes=[...new Set(baseLanes.flatMap(lane=>offsets.map(offset=>lane+offset)))]
  .filter(y=>y>=4&&y<=limit-4)
  .sort((a,b)=>Math.abs(a-first[1])+Math.abs(a-last[1])-Math.abs(b-first[1])-Math.abs(b-last[1])
   ||Math.abs(a-center)-Math.abs(b-center));
 const join=(a,b)=>a[0]<b[0]?[connect(a,b,a[1]===b[1]?.5:0)]:[];
 const through=lane=>{
  const startLane=lane===first[1]?first:[depart,lane];
  const endLane=lane===last[1]?last:[arrive,lane];
  return [...join(first,startLane),...join(startLane,endLane),...join(endLane,last)];
 };
 const minCross=Math.min(first[1],last[1]),maxCross=Math.max(first[1],last[1]);
 const excursion=lane=>Math.max(minCross-lane,lane-maxCross,0);
 let channel;
 for(const lane of lanes){
  const shapeCost=8+excursion(lane)*.1+Math.abs(lane-center)*.002;
  // Only the first clear lane is needed for the fallback. After it,
  // ignore candidates whose shape cost alone cannot beat the best route.
  if(channel!==undefined&&session?.cells?.size&&shapeCost>=bestScore)continue;
  const candidate=through(lane);
  if(!clearRoute(candidate))continue;
  if(channel===undefined)channel=lane;
  if(candidate.length)scoreCandidate(candidate,shapeCost);
  if(!session?.cells?.size&&excursion(lane)<=height)return finish(candidate);
 }

 // A staggered row can close an interior channel. Allow one lane change
 // between ranks if that avoids sending the whole relation around the rim.
 const maxExcursion=channel===undefined?Infinity:excursion(channel);
 const openings=lanes.filter(lane=>excursion(lane)+height/4<maxExcursion);
 let furthest=depart;
 let best=null,bestShift=2*maxExcursion+maxCross-minCross;
 for(const rect of rectangles.slice().sort((a,b)=>a.left-b.left)){
  const gapEnd=Math.min(rect.left,arrive);
  if(gapEnd-furthest>=16){
   const before=openings.map(lane=>{
    const enter=[furthest,lane];
    const segments=[...join(first,[depart,lane]),...join([depart,lane],enter)];
    return {enter,segments};
   }).filter(({segments})=>clearRoute(segments));
   const after=openings.map(lane=>{
    const leave=[gapEnd,lane];
    const segments=[...join(leave,[arrive,lane]),...join([arrive,lane],last)];
    return {leave,segments};
   }).filter(({leave,segments})=>clearRoute(segments,leave));
   for(const left of before)for(const right of after){
    const shift=Math.abs(left.enter[1]-first[1])+Math.abs(right.leave[1]-left.enter[1])+Math.abs(last[1]-right.leave[1]);
    if(shift>=bestShift)continue;
    const middle=join(left.enter,right.leave);
    if(!clearRoute(middle,left.enter))continue;
    best=[...left.segments,...middle,...right.segments];
    bestShift=shift;
   }
  }
  furthest=Math.max(furthest,rect.right);
  if(furthest>=arrive)break;
 }
 if(best)consider(best,10+bestShift*.1);
 if(bestRoute)return finish(bestRoute,bestSamples);
 // Preserve the relation even if a custom layout has no usable rank gap.
 return finish(direct);
}
function routeSvgD(route){
 return `M ${route.x1} ${route.y1} `+route.segments.map(segment=>`C ${segment.slice(0,2).join(' ')} ${segment.slice(2,4).join(' ')} ${segment.slice(4,6).join(' ')}`).join(' ');
}
function strokeCanvasRoute(ctx,route){
 ctx.beginPath();ctx.moveTo(route.x1,route.y1);
 for(const segment of route.segments)ctx.bezierCurveTo(...segment);
 ctx.stroke();
}

function routeGraphConnections(nodes,positions,nodeWidth,nodeHeight,crossSize,vertical=false){
 const byName=new Map(nodes.map(node=>[node.name,node.id]));
 const edges=[],outgoing=new Map(),incoming=new Map();
 for(const node of nodes){
  if(!positions.has(node.id))continue;
  for(const name of new Set(node.prerequisites||[])){
   const from=byName.get(name);
   if(!positions.has(from))continue;
   const edge={from,to:node.id};
   edges.push(edge);
   if(!outgoing.has(from))outgoing.set(from,[]);
   if(!incoming.has(node.id))incoming.set(node.id,[]);
   outgoing.get(from).push(edge);
   incoming.get(node.id).push(edge);
  }
 }
 const cross=vertical?'x':'y',main=vertical?'y':'x';
 const crossSizeOfNode=vertical?nodeWidth:nodeHeight;
 const inset=Math.min(12,crossSizeOfNode/4);
 const assignPorts=(groups,other,side)=>{
  const depth=side==='start'?(vertical?nodeHeight:nodeWidth):0;
  for(const [id,group] of groups){
   group.sort((a,b)=>{
    const first=positions.get(a[other]),second=positions.get(b[other]);
    return first[cross]-second[cross]||first[main]-second[main];
   });
   const pos=positions.get(id);
   const step=Math.min(12,(crossSizeOfNode-2*inset)/Math.max(1,group.length-1));
   group.forEach((edge,index)=>{
    const offset=crossSizeOfNode/2+(index-(group.length-1)/2)*step;
    edge[side]=vertical?{x:pos.x+offset,y:pos.y+depth}:{x:pos.x+depth,y:pos.y+offset};
   });
  }
 };
 assignPorts(outgoing,'to','start');
 assignPorts(incoming,'from','end');
 const session=createRoutingSession();
 return edges.map(({from,to,start,end})=>({
  from,to,route:routeConnection(from,to,start,end,positions,nodeWidth,nodeHeight,crossSize,vertical,session)
 }));
}
function appendGraphConnections(svg,nodes,positions,nodeWidth,nodeHeight,crossSize,vertical=false){
 const key=JSON.stringify([vertical,nodeWidth,nodeHeight,crossSize,
  nodes.map(node=>[node.id,node.name,node.prerequisites]),
  Array.from(positions,([id,point])=>[id,point.x,point.y])]);
 let paths=connectionPaths.get(key);
 if(paths){
  connectionPaths.delete(key);
 }else{
  paths=routeGraphConnections(nodes,positions,nodeWidth,nodeHeight,crossSize,vertical)
   .map(({from,to,route})=>({from,to,d:routeSvgD(route)}));
  if(connectionPaths.size>=16)connectionPaths.delete(connectionPaths.keys().next().value);
 }
 connectionPaths.set(key,paths);
 const className=vertical?'kg-mobile-edge':'kg-edge';
 for(const {from,to,d} of paths){
  const path=svg.ownerDocument.createElementNS(svg.namespaceURI,'path');
  path.setAttribute('class',className);
  path.setAttribute('data-from',from);
  path.setAttribute('data-to',to);
  path.setAttribute('d',d);
  svg.appendChild(path);
 }
}
root.DMateKnowledgeGraphLabels={layout,prepare,applySvg,applyHtml,paint,fontScale,fontFamily,groupRanks,createRoutingSession,routeConnection,routeSvgD,strokeCanvasRoute,routeGraphConnections,appendGraphConnections};
})(typeof window!=='undefined'?window:globalThis);
