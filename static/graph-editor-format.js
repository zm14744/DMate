(function(root){
'use strict';
const literal=v=>String(v??'');
const safe=v=>literal(v).replace(/([\\`*_{}#+!|])/g,'\\$1')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const subs='₀₁₂₃₄₅₆₇₈₉';
const markName=v=>literal(v).replace(/\d/g,n=>subs[Number(n)]);
const circles='①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
const hasLabel=v=>v?.label!=null&&String(v.label).trim()!=='';
const displayNumber=value=>{
 const text=typeof value==='string'?value.trim():'';
 if(text.length===1&&circles.includes(text))return String(circles.indexOf(text)+1);
 const legacy=/^未命名([0-9]+)$/.exec(text);return legacy?String(Number(legacy[1])):text;
};
function numericAnnotation(value){
 if(value==null||typeof value==='boolean'||!['string','number'].includes(typeof value)||typeof value==='number'&&!Number.isFinite(value))return null;
 const raw=String(value);if(/[①-⑳]/.test(raw))return null;
 let text=raw.normalize('NFKC').trim().replace(/−/g,'-').replace(/⁄/g,'/');if(text.length>256)return null;
 const latex=/^\\(?:d?frac)\{([+-]?\d+)\}\{([+-]?\d+)\}$/.exec(text);if(latex)text=latex[1]+'/'+latex[2];
 text=text.replace(/\s*\/\s*/g,'/');
 const fraction=/^([+-]?\d+)\/([+-]?\d+)$/.exec(text);
 if(fraction){const denominator=BigInt(fraction[2]);return denominator===0n?null:[BigInt(fraction[1]),denominator];}
 const decimal=/^([+-]?)(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d{1,3}))?$/.exec(text);if(!decimal)return null;
 const exponent=Number(decimal[3]||0);if(Math.abs(exponent)>308)return null;
 const parts=decimal[2].split('.'),scale=(parts[1]||'').length-exponent;
 let numerator=BigInt(parts.join(''));if(decimal[1]==='-')numerator=-numerator;
 return scale>=0?[numerator,10n**BigInt(scale)]:[numerator*10n**BigInt(-scale),1n];
}
function edgeName(edge){
 const label=edge?.edge_label;if(label==null||!String(label).trim())return null;
 if(edge.edge_label_is_explicit===true)return literal(label);
 const name=numericAnnotation(label),weight=numericAnnotation(edge.weight);
 return name&&weight&&name[0]*weight[1]===weight[0]*name[1]?null:literal(label);
}
function titleIncludesType(name,graph){
 let kind=String(name).replace(/\s/g,'');
 if(graph.direction_mode==='mixed'){
  if(!/混合(?:方向|图)/.test(kind))return false;
 }else if(graph.directed===false){if(!/(?:无向图|无向)/.test(kind))return false;}
 else if(graph.directed===true){if(/无向/.test(kind)||!/有向/.test(kind))return false;}
 else return false;
 return graph.weighted===true?/(?:带权|加权|有权)/.test(kind)&&!/无权/.test(kind)
  :graph.weighted===false?/无权/.test(kind):false;
}
function graphLabels(graph){
 const vertices=(Array.isArray(graph?.vertices)?graph.vertices:[]).filter(Boolean).map(v=>({...v}));
 const used=new Set(vertices.filter(hasLabel).map(v=>String(v.label))),existing=new Set();
 for(const v of vertices){
  if(hasLabel(v))continue;
  const display=displayNumber(v.display_label);
  if(display&&display.length<=16&&!used.has(display)&&!existing.has(display)){
   v.display_label=display;existing.add(display);
  }else delete v.display_label;
 }
 for(const display of existing)used.add(display);
 let next=Number.isInteger(graph?.anon_next)&&graph.anon_next>=1&&graph.anon_next<=10000?graph.anon_next:1;const mapping=new Map();
 for(const name of used){
  if(/^[0-9]{1,5}$/.test(String(name))&&Number(name)>=1&&Number(name)<=10000)next=Math.max(next,Number(name)+1);
 }
 // Old records without persisted display labels still use identity order,
 // so reordering the vertex table cannot change the name of a point.
 for(const v of [...vertices].sort((a,b)=>String(a?.id)<String(b?.id)?-1:String(a?.id)>String(b?.id)?1:0)){
  if(!v||v.id===undefined)continue;
  if(hasLabel(v)){mapping.set(String(v.id),literal(v.label));continue;}
  if(v.display_label){mapping.set(String(v.id),literal(v.display_label));continue;}
  let candidate;
  do {candidate=String(next++);} while(used.has(candidate));
  used.add(candidate);mapping.set(String(v.id),candidate);
 }
 return mapping;
}
function graphRows(graph,index){
 const vertices=Array.isArray(graph?.vertices)?graph.vertices:[],edges=Array.isArray(graph?.edges)?graph.edges:[];
 const labels=graphLabels(graph),get=id=>labels.get(String(id))||String(id??'?');
 const named=edges.map(edgeName).filter(value=>value!==null);
 const relations=edges.map(e=>{
  const middle=e.direction==='forward'?'→':e.direction==='undirected'?'—':'？';
  const name=edgeName(e),prefix=name!==null?name+'：':'';
  const weight=e.weight===null||e.weight===undefined||String(e.weight).trim()===''?'': '（权值：'+literal(e.weight)+'）';
  const pending=e.direction==='unknown'?'（方向待核对）':'';
  const missing=graph.weighted===true&&!weight?'（权值待核对）':'';
  return {id:e.id,txt:prefix+get(e.from)+middle+get(e.to)+weight+pending+missing};
 });
 const orientation=graph.direction_mode==='mixed'?'混合方向':graph.directed===true?'有向':graph.directed===false?'无向':'方向待核对';
 const weighted=graph.weighted===true?'带权':graph.weighted===false?'无权':'权值待核对';
 const graphName=literal(graph.name||graph.id||'G'+(index+1));
 const title=/^G\d+$/i.test(graphName)?'图 '+markName(graphName):'图 '+(index+1)+'（'+graphName+'）';
 const positions=vertices.filter(v=>!hasLabel(v)||typeof v.position_description==='string'&&v.position_description.trim())
  .map(v=>({id:v.id,label:get(v.id),txt:get(v.id)+'：'+(typeof v.position_description==='string'&&v.position_description.trim()||'位置未记录')}));
 return {title,type:orientation+' · '+weighted,showType:!titleIncludesType(graphName,graph),vertices:vertices.map(v=>get(v.id)),
         named,relations,positions,
         anonymousNote:'',
         description:typeof graph.visual_description==='string'?graph.visual_description.trim():''};
}
function toPlain(graphs){
 if(!Array.isArray(graphs))return '';
 return graphs.map((g,index)=>{
  const row=graphRows(g,index),lines=[row.title+(row.showType?'    '+row.type:''),'','点：'+(row.vertices.join('、')||'无')];
  if(row.anonymousNote)lines.push(row.anonymousNote);
  if(row.positions.length)lines.push('','顶点位置：',...row.positions.map(v=>v.txt));
  if(row.named.length)lines.push('边：'+row.named.join('、'));
  lines.push('','关系：');
  lines.push(...(row.relations.length?row.relations.map(e=>e.txt):['无']));
  if(row.description)lines.push('','图形描述：',row.description);
  return lines.join('\n');
 }).join('\n\n');
}
function toMarkdown(graphs){
 if(!Array.isArray(graphs))return '';
 return graphs.map((g,index)=>{
  const row=graphRows(g,index),lines=['### '+safe(row.title),...(row.showType?['*'+safe(row.type)+'*']:[]),'',
    '**点：** '+row.vertices.map(safe).join('、')];
  if(row.anonymousNote)lines.push(safe(row.anonymousNote));
  if(row.positions.length)lines.push('','**顶点位置：**',...row.positions.map(v=>'- '+safe(v.txt)));
  if(row.named.length)lines.push('**边：** '+row.named.map(safe).join('、'));
  lines.push('','**关系：**');
  lines.push(...(row.relations.length?row.relations.map(e=>'- '+safe(e.txt)):['无']));
  if(row.description)lines.push('','**图形描述：**',safe(row.description));
  return lines.join('\n');
 }).join('\n\n---\n\n');
}
const api={graphLabels,graphRows,toPlain,toMarkdown,edgeName};
root.DMateGraphFormat=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
