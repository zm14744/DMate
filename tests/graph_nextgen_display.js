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
console.log('Canonical graph card checks passed');
