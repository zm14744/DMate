const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/script.js','utf8');
const start=source.indexOf('function ocrReviewPlain('),end=source.indexOf('// OCR review displays recognized content',start);
const render=vm.runInNewContext(source.slice(start,end)+'\nformatStructuredGraphReview');
const g={schema_version:'dmate.graph/1',id:'G1',name:'图甲',directed:true,weighted:true,multigraph:true,complete:false,
 vertices:[{id:'v1',label:'A'},{id:'v2',label:'B'},{id:'v3',label:null,isolated_confirmed:true}],
 edges:[{id:'e1',from:'v1',to:'v2',direction:'forward',weight:0,status:'accepted',parallel_count:2},
 {id:'e2',from:'v2',to:'v1',direction:'unknown',weight:0,status:'pending',parallel_count:2}],
 relation_audit:['SECRET_DIAGNOSTIC'],uncertain_edges:['SECRET_DIAGNOSTIC']};
const text=render([g]);
assert(text.includes('e1：')&&text.includes('e2：'));
assert(text.includes('权值：0')&&text.includes('方向未确定')&&text.includes('部分内容未识别完整'));
assert(text.includes('A')&&text.includes('B')&&text.includes('孤立顶点'));
for(const bad of ['SECRET_DIAGNOSTIC','图形结构待核对','首次识别的图形候选','结构化边表尚未核实','多图边集已二次核对'])assert(!text.includes(bad));
const numbered=render([{...g,vertices:[{id:'v1',label:'v₁'},{id:'v2',label:'v12'}],
 edges:[{id:'pixel_17',from:'v1',to:'v2',direction:'forward',status:'accepted'}]}]);
assert(numbered.includes('\\(v_{1}\\)') && numbered.includes('\\(v_{12}\\)'));
assert(numbered.includes('e1：') && !numbered.includes('pixel_17'));
// Semantic graphs need no original coordinates or pixel route to render.
const semantic={schema_version:'dmate.graph/1',id:'semantic',name:'语义图',
 directed:true,weighted:true,multigraph:true,complete:true,
 vertices:[{id:'a',label:'v₂'},{id:'b',label:'V₂'}],
 edges:[{id:'internal_1',from:'a',to:'b',direction:'forward',weight:0,
   edge_label:'q₂',color:'red',style:'solid',status:'accepted',parallel_count:2},
  {id:'internal_2',from:'a',to:'b',direction:'forward',weight:3,
   edge_label:'Q₂',color:'blue',style:'dashed',status:'accepted',parallel_count:2},
  {id:'internal_3',from:'b',to:'b',direction:'forward',weight:4,
   edge_label:'r₁',color:'#2244aa',style:'dotted',status:'accepted',parallel_count:1}]};
const before=JSON.stringify(semantic),semanticText=render([semantic]);
assert(semanticText.includes('\\(v_{2}\\)') && semanticText.includes('\\(V_{2}\\)'));
assert(semanticText.includes('边名：q₂') && semanticText.includes('边名：Q₂'));
assert(semanticText.includes('权值：0') && semanticText.includes('权值：3'));
assert(semanticText.includes('实线') && semanticText.includes('虚线') && semanticText.includes('点线'));
for(const attribute of ['颜色：red','颜色：blue','颜色：\\#2244aa'])assert(semanticText.includes(attribute));
assert.equal((semanticText.match(/^- e\d+：/gm)||[]).length,3,'parallel and loop instances stay separate');
assert.equal(JSON.stringify(semantic),before,'display never mutates semantic data');
const hostile=JSON.parse(before);
hostile.edges[0].color='<b>red&[x]</b>';
hostile.edges[0].edge_label='<b>q₂&[x]</b>';
const escaped=render([hostile]);
assert(escaped.includes('颜色：&lt;b&gt;red&amp;&#91;x&#93;&lt;/b&gt;'));
assert(escaped.includes('边名：&lt;b&gt;q₂&amp;&#91;x&#93;&lt;/b&gt;'));
assert(!escaped.includes('<b>'),'color and printed labels never become HTML');
for(const color of [undefined,null,'','unknown',' UNKNOWN ']) {
 const absent=render([{...semantic,edges:[{...semantic.edges[0],color}]}]);
 assert(!absent.includes('颜色：'),'unknown color is not invented or defaulted');
}
console.log('Canonical graph card checks passed');
