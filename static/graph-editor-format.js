(function(root){
'use strict';
const literal=v=>String(v??'');
const safe=v=>literal(v).replace(/([\\`*_{}#+!|])/g,'\\$1')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const subs='₀₁₂₃₄₅₆₇₈₉';
const markName=v=>literal(v).replace(/\d/g,n=>subs[Number(n)]);
const circles='①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
function graphLabels(graph){
 const vertices=Array.isArray(graph?.vertices)?graph.vertices:[];
 const used=new Set(vertices.map(v=>v?.label||v?.display_label).filter(Boolean));
 let next=1;const mapping=new Map();
 for(const v of vertices){
  if(!v||v.id===undefined)continue;
  if(v.label){mapping.set(String(v.id),literal(v.label));continue;}
  if(v.display_label){mapping.set(String(v.id),literal(v.display_label));continue;}
  let candidate;
  do {candidate=next<=20?circles[next-1]:'未命名'+next;next++;} while(used.has(candidate));
  used.add(candidate);mapping.set(String(v.id),candidate);
 }
 return mapping;
}
function graphRows(graph,index){
 const vertices=Array.isArray(graph?.vertices)?graph.vertices:[],edges=Array.isArray(graph?.edges)?graph.edges:[];
 const labels=graphLabels(graph),get=id=>labels.get(String(id))||String(id??'?');
 const named=edges.filter(e=>e?.edge_label!=null&&String(e.edge_label).trim());
 const relations=edges.map(e=>{
  const middle=e.direction==='forward'?'→':e.direction==='undirected'?'—':'？';
  const prefix=e.edge_label!=null&&String(e.edge_label).trim()?literal(e.edge_label)+'：':'';
  const weight=e.weight===null||e.weight===undefined||String(e.weight).trim()===''?'': '（权值：'+literal(e.weight)+'）';
  const pending=e.direction==='unknown'?'（方向待核对）':'';
  const missing=graph.weighted===true&&!weight?'（权值待核对）':'';
  return {id:e.id,txt:prefix+get(e.from)+middle+get(e.to)+weight+pending+missing};
 });
 const orientation=graph.direction_mode==='mixed'?'混合方向':graph.directed===true?'有向':graph.directed===false?'无向':'方向待核对';
 const weighted=graph.weighted===true?'带权':graph.weighted===false?'无权':'权值待核对';
 const graphName=literal(graph.name||graph.id||'G'+(index+1));
 const title=/^G\d+$/i.test(graphName)?'图 '+markName(graphName):'图 '+(index+1)+'（'+graphName+'）';
 return {title,type:orientation+' · '+weighted,vertices:vertices.map(v=>get(v.id)),
         named:named.map(e=>literal(e.edge_label)),relations,
         description:typeof graph.visual_description==='string'?graph.visual_description.trim():''};
}
function toPlain(graphs){
 if(!Array.isArray(graphs))return '';
 return graphs.map((g,index)=>{
  const row=graphRows(g,index),lines=[row.title+'    '+row.type,'','点：'+(row.vertices.join('、')||'无')];
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
  const row=graphRows(g,index),lines=['### '+safe(row.title),'*'+safe(row.type)+'*','',
    '**点：** '+row.vertices.map(safe).join('、')];
  if(row.named.length)lines.push('**边：** '+row.named.map(safe).join('、'));
  lines.push('','**关系：**');
  lines.push(...(row.relations.length?row.relations.map(e=>'- '+safe(e.txt)):['无']));
  if(row.description)lines.push('','**图形描述：**',safe(row.description));
  return lines.join('\n');
 }).join('\n\n---\n\n');
}
const api={graphLabels,graphRows,toPlain,toMarkdown};
root.DMateGraphFormat=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);