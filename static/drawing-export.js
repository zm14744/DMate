(function(root){
 'use strict';
const uiText=(source,english)=>root.DMateI18n?.t?.(source,english)??source;
 async function pngBlob(svg, options={}){
  if(!svg || svg.localName!=='svg')throw new Error(uiText('画板暂未准备完成，请稍后重试。'));
  const doc=svg.ownerDocument, copy=svg.cloneNode(true), win=doc.defaultView;
  const box=(copy.getAttribute('viewBox')||'0 0 1000 700').split(/[\s,]+/).map(Number);
  if(box.length!==4||box.some(n=>!Number.isFinite(n))||box[2]<=0||box[3]<=0)throw new Error(uiText('绘图尺寸无效。'));
  const maxSide=4096,scale=Math.min(2,maxSide/Math.max(box[2],box[3]));
  const width=Math.max(1,Math.round(box[2]*scale)),height=Math.max(1,Math.round(box[3]*scale));
  copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width',String(width));copy.setAttribute('height',String(height));
  const data=new win.XMLSerializer().serializeToString(copy),url=win.URL.createObjectURL(new Blob([data],{type:'image/svg+xml;charset=utf-8'}));
  try{
   const image=new win.Image();
   await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error(uiText('绘图转换失败，请重试。')));image.src=url;});
   const canvas=doc.createElement('canvas');canvas.width=width;canvas.height=height;
   const ctx=canvas.getContext('2d');if(!ctx)throw new Error(uiText('浏览器无法导出图片。'));
   ctx.fillStyle=options.background||'#ffffff';ctx.fillRect(0,0,width,height);ctx.drawImage(image,0,0,width,height);
   return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error(uiText('图片导出失败，请重试。'))),'image/png'));
  }finally{win.URL.revokeObjectURL(url);}
 }
 function pngFilename(name){
  const value=String(name||uiText('我的绘图','My drawing')).replace(/[\\/:*?"<>|]/g,'_').replace(/(?:\.png)+$/i,'').slice(0,96);
  return (value||uiText('我的绘图','My drawing'))+'.png';
 }
 function download(blob,name,doc=root.document){
  const win=doc.defaultView,url=win.URL.createObjectURL(blob),link=doc.createElement('a');
  link.href=url;link.download=pngFilename(name);link.hidden=true;doc.body.append(link);link.click();link.remove();
  win.setTimeout(()=>win.URL.revokeObjectURL(url),1000);
 }
 const galleryChannels=new WeakMap();
 function galleryChannel(bridge){
  let channel=galleryChannels.get(bridge);if(channel)return channel;
  const pending=new Map(),previous=bridge.onmessage;
  const listener=event=>{
   let response;try{response=JSON.parse(event.data);}catch(_){}
   if(response&&pending.has(response.id))pending.get(response.id)({ok:response.ok===true,message:String(response.message||'')});
   if(!events&&typeof previous==='function')previous.call(bridge,event);
  };
  const events=typeof bridge.addEventListener==='function';
  if(events)bridge.addEventListener('message',listener);else bridge.onmessage=listener;
  channel={pending,release(){
   if(pending.size)return;
   if(events)bridge.removeEventListener?.('message',listener);else if(bridge.onmessage===listener)bridge.onmessage=previous;
   galleryChannels.delete(bridge);
  }};
  galleryChannels.set(bridge,channel);return channel;
 }
 function saveToGallery(blob,name,doc=root.document){
  const win=doc.defaultView,bridge=win.DMateGallery;
  if(!bridge||typeof bridge.postMessage!=='function')return Promise.resolve(null);
  if(!blob||blob.size>20*1024*1024)return Promise.resolve({ok:false,message:uiText('图片超出安装版可保存的大小（20 MB）','The image exceeds the app’s 20 MB limit.')});
  return new Promise(resolve=>{
   const channel=galleryChannel(bridge),id='png-'+Date.now()+'-'+Math.random().toString(36).slice(2);
   let completed=false;
   const finish=result=>{if(completed)return;completed=true;win.clearTimeout(timer);channel.pending.delete(id);channel.release();resolve(result);};
   const timer=win.setTimeout(()=>finish({ok:false,message:uiText('相册保存超时，请重试','Saving to Photos timed out. Try again.')}),30000);
   channel.pending.set(id,finish);
   const reader=new win.FileReader();
   reader.onerror=()=>finish({ok:false,message:uiText('无法读取图片','The image could not be read.')});
   reader.onload=()=>{
    if(completed)return;
    const base64=String(reader.result||'').split(',')[1];
    if(!base64){finish({ok:false,message:uiText('图片为空','The image is empty.')});return;}
    try{bridge.postMessage(JSON.stringify({id,filename:pngFilename(name),base64}));}
    catch(_){finish({ok:false,message:uiText('无法发送图片至安装版','The image could not be sent to the app.')});}
   };
   try{reader.readAsDataURL(blob);}catch(_){finish({ok:false,message:uiText('无法读取图片','The image could not be read.')});}
  });
 }
 function isMobileDevice(win=root){
  const nav=win.navigator;
  return /Android|iPhone|iPad|iPod/i.test(nav?.userAgent||'')||(nav?.platform==='MacIntel'&&nav.maxTouchPoints>1);
 }
 const previews=new WeakMap();
 function showSavePreview(blob,name,doc=root.document,onStatus){
  previews.get(doc)?.();
  const win=doc.defaultView,url=win.URL.createObjectURL(blob),dialog=doc.createElement('dialog'),panel=doc.createElement('div');
  const previous=doc.activeElement;
  dialog.className='dmate-png-save-dialog';dialog.setAttribute('aria-label',uiText('保存图片','Save image'));
  Object.assign(dialog.style,{boxSizing:'border-box',border:'0',padding:'0',margin:'0',width:'100vw',height:'100dvh',maxWidth:'none',maxHeight:'none'});
  panel.className='dmate-png-save-panel';
  const title=doc.createElement('strong');title.textContent=uiText('图片已生成','Image ready');
  const tip=doc.createElement('p');tip.textContent=uiText('网页无法直接写入手机相册。请长按图片保存，或选择系统分享/保存。','A website cannot write directly to Photos. Touch and hold the image to save it, or choose system share/save.');
  const image=doc.createElement('img');image.className='dmate-png-save-preview';image.src=url;image.alt=uiText('导出的图片，长按可保存','Exported image; touch and hold to save');
  const actions=doc.createElement('div');actions.className='dmate-png-save-actions';
  const link=doc.createElement('a');link.dataset.imageExport='download';link.href=url;link.download=pngFilename(name);link.textContent=uiText('下载图片','Download image');
  link.addEventListener('click',()=>onStatus?.(uiText('已发起图片下载，请查看浏览器下载记录','Image download started. Check your browser’s downloads.')));
  actions.append(link);
  if(typeof win.File==='function'&&typeof win.navigator.share==='function'){
   const file=new win.File([blob],pngFilename(name),{type:'image/png'});
   let supported=true;try{supported=typeof win.navigator.canShare!=='function'||win.navigator.canShare({files:[file]});}catch(_){supported=false;}
   if(supported){
    const share=doc.createElement('button');share.type='button';share.dataset.imageExport='share';share.textContent=uiText('系统分享/保存','System share/save');
    share.addEventListener('click',async()=>{
     try{await win.navigator.share({files:[file]});onStatus?.(uiText('请在系统操作中选择保存位置','Choose a save location in the system options.'));}
     catch(error){if(error?.name!=='AbortError')onStatus?.(uiText('系统分享不可用，请长按图片保存','System sharing is unavailable. Touch and hold the image to save it.'));}
    });actions.append(share);
   }
  }
  const close=doc.createElement('button');close.type='button';close.dataset.imageExport='close';close.textContent=uiText('关闭','Close');
  let dismissed=false;
  const dismiss=()=>{
   if(dismissed)return;dismissed=true;previews.delete(doc);
   if(dialog.open)dialog.close();dialog.remove();win.URL.revokeObjectURL(url);
   if(previous?.isConnected)previous.focus?.({preventScroll:true});
  };
  close.addEventListener('click',dismiss);dialog.addEventListener('cancel',event=>{event.preventDefault();dismiss();});dialog.addEventListener('close',dismiss);
  dialog.addEventListener('click',event=>{if(event.target===dialog)dismiss();});
  actions.append(close);panel.append(title,tip,image,actions);dialog.append(panel);doc.body.append(dialog);previews.set(doc,dismiss);dialog.showModal();close.focus({preventScroll:true});
  return dismiss;
 }
 async function save(blob,name,options={}){
  const doc=options.document||root.document,filename=pngFilename(name);
  if(!blob||blob.type!=='image/png'||!blob.size)throw new Error(uiText('图片尚未准备完成，请重试。','The image is not ready. Try again.'));
  let result;
  if(doc.defaultView.DMateGallery?.postMessage){
   const saved=await saveToGallery(blob,filename,doc);
   if(!saved?.ok)throw new Error(saved?.message||uiText('保存到相册失败，请重试','Saving to Photos failed. Try again.'));
   result={destination:'gallery',filename,message:saved.message||uiText('图片已保存到相册','Image saved to Photos')};
  }else if(isMobileDevice(doc.defaultView)){
   if(typeof options.mobilePreview==='function')options.mobilePreview(blob,filename);
   else showSavePreview(blob,filename,doc,options.onStatus);
   result={destination:'preview',filename,message:uiText('图片已生成，请选择保存方式','Image ready. Choose how to save it.')};
  }else{
   root.DMateDrawingExport.download(blob,filename,doc);
   result={destination:'download',filename,message:uiText('已发起图片下载','Image download started')};
  }
  options.onStatus?.(result.message);return result;
 }
 function documentForImage(document,svg){
  if(!svg||svg.localName!=='svg')throw new Error(uiText('画板暂未准备完成，请稍后重试。'));
  const box=(svg.getAttribute('viewBox')||'').split(/[\s,]+/).map(Number);
  let geometry;try{geometry=JSON.parse(svg.getAttribute('data-drawing-geometry')||'null');}catch(_){}
  if(!geometry&&svg.exportVertexPositions){const graphId=Object.keys(svg.exportVertexPositions)[0];geometry={graphId,vertices:svg.exportVertexPositions[graphId],width:Number(svg.getAttribute('data-source-width')),height:Number(svg.getAttribute('data-source-height'))};}
  if(!geometry||!Number.isFinite(geometry.width)||!Number.isFinite(geometry.height)||typeof geometry.graphId!=='string'||box.length!==4||box.some(v=>!Number.isFinite(v))||box[2]<=0||box[3]<=0)
   throw new Error(uiText('绘图坐标尚未准备完成，请稍后重试。'));
  const result=JSON.parse(JSON.stringify(document)),point=p=>[(p[0]*geometry.width-box[0])/box[2],(p[1]*geometry.height-box[1])/box[3]];
  result.graphs=result.graphs.filter(g=>g.id===geometry.graphId);
  if(result.graphs.length!==1)throw new Error(uiText('当前绘图不存在，请重新打开。'));
  for(const graph of result.graphs){
   for(const vertex of graph.vertices){const p=geometry.vertices?.[vertex.id]||[vertex.x,vertex.y];if(!p.every(Number.isFinite))throw new Error(uiText('绘图顶点位置无效。'));[vertex.x,vertex.y]=point(p);}
   for(const edge of graph.edges)if(Array.isArray(edge.path))edge.path=edge.path.map(point);
   graph.bbox=[0,0,1,1];delete graph.region_polygon;
  }
  return result;
 }
 root.DMateDrawingExport={pngBlob,download,save,saveToGallery,isMobileDevice,showSavePreview,pngFilename,documentForImage};
})(typeof window!=='undefined'?window:globalThis);
