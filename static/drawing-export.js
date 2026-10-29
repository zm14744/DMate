(function(root){
 'use strict';
 async function pngBlob(svg, options={}){
  if(!svg || svg.localName!=='svg')throw new Error('画板暂未准备完成，请稍后重试。');
  const doc=svg.ownerDocument, copy=svg.cloneNode(true), win=doc.defaultView;
  const box=(copy.getAttribute('viewBox')||'0 0 1000 700').split(/[\s,]+/).map(Number);
  if(box.length!==4||box.some(n=>!Number.isFinite(n))||box[2]<=0||box[3]<=0)throw new Error('绘图尺寸无效。');
  const maxSide=4096,scale=Math.min(2,maxSide/Math.max(box[2],box[3]));
  const width=Math.max(1,Math.round(box[2]*scale)),height=Math.max(1,Math.round(box[3]*scale));
  copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width',String(width));copy.setAttribute('height',String(height));
  const data=new win.XMLSerializer().serializeToString(copy),url=win.URL.createObjectURL(new Blob([data],{type:'image/svg+xml;charset=utf-8'}));
  try{
   const image=new win.Image();
   await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error('绘图转换失败，请重试。'));image.src=url;});
   const canvas=doc.createElement('canvas');canvas.width=width;canvas.height=height;
   const ctx=canvas.getContext('2d');if(!ctx)throw new Error('浏览器无法导出图片。');
   ctx.fillStyle=options.background||'#ffffff';ctx.fillRect(0,0,width,height);ctx.drawImage(image,0,0,width,height);
   return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('图片导出失败，请重试。')),'image/png'));
  }finally{win.URL.revokeObjectURL(url);}
 }
 function download(blob,name,doc=root.document){
  const win=doc.defaultView,url=win.URL.createObjectURL(blob),link=doc.createElement('a');
  link.href=url;link.download=String(name||'我的绘图').replace(/[\\/:*?"<>|]/g,'_').slice(0,100)+'.png';link.hidden=true;doc.body.append(link);link.click();link.remove();
  win.setTimeout(()=>win.URL.revokeObjectURL(url),1000);
 }
 function documentForImage(document,svg){
  if(!svg||svg.localName!=='svg')throw new Error('画板暂未准备完成，请稍后重试。');
  const box=(svg.getAttribute('viewBox')||'').split(/[\s,]+/).map(Number);
  let geometry;try{geometry=JSON.parse(svg.getAttribute('data-drawing-geometry')||'null');}catch(_){}
  if(!geometry&&svg.exportVertexPositions){const graphId=Object.keys(svg.exportVertexPositions)[0];geometry={graphId,vertices:svg.exportVertexPositions[graphId],width:Number(svg.getAttribute('data-source-width')),height:Number(svg.getAttribute('data-source-height'))};}
  if(!geometry||!Number.isFinite(geometry.width)||!Number.isFinite(geometry.height)||typeof geometry.graphId!=='string'||box.length!==4||box.some(v=>!Number.isFinite(v))||box[2]<=0||box[3]<=0)
   throw new Error('绘图坐标尚未准备完成，请稍后重试。');
  const result=JSON.parse(JSON.stringify(document)),point=p=>[(p[0]*geometry.width-box[0])/box[2],(p[1]*geometry.height-box[1])/box[3]];
  result.graphs=result.graphs.filter(g=>g.id===geometry.graphId);
  if(result.graphs.length!==1)throw new Error('当前绘图不存在，请重新打开。');
  for(const graph of result.graphs){
   for(const vertex of graph.vertices){const p=geometry.vertices?.[vertex.id]||[vertex.x,vertex.y];if(!p.every(Number.isFinite))throw new Error('绘图顶点位置无效。');[vertex.x,vertex.y]=point(p);}
   for(const edge of graph.edges)if(Array.isArray(edge.path))edge.path=edge.path.map(point);
   graph.bbox=[0,0,1,1];delete graph.region_polygon;
  }
  return result;
 }
 root.DMateDrawingExport={pngBlob,download,documentForImage};
})(typeof window!=='undefined'?window:globalThis);
