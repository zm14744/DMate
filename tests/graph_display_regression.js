// Regression tests of actual OCR graph renderer, without a browser or AI calls.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const source = fs.readFileSync("static/script.js", "utf8");
const start = source.indexOf("function ocrReviewPlain(");
const end = source.indexOf("// OCR review displays recognized content", start);
assert(start >= 0 && end > start, "Cannot locate graph renderer");
const funcs = vm.runInNewContext(
    source.slice(start,end) +
    "\n({formatStructuredGraphReview,formatOcrReviewGraphDisplay})"
);
const graph = {
    id: "G1",
    directed: false, weighted: false, multigraph: false,
    complete: false,
    vertices: [{id:"G1_v1",x:0.111,y:0.222},{id:"G1_v2",x:0.333,y:0.444}],
    edges: [{from:"G1_v1",to:"G1_v2"}],
    uncertain_edges:["模型尚未确认端点"]
};
const rendered = funcs.formatOcrReviewGraphDisplay(
    [graph], "【图形结构待核对】\n【首次识别的图形候选，尚未经独立核对】"
);
assert(rendered.includes("顶点（2）"));
assert(rendered.includes("边（暂录 1 条）"));
assert(rendered.includes("v_{1}") && rendered.includes("v_{2}"));
for (const unwanted of [
    "图形结构待核对","结构已列出","待核对","首次识别",
    "识别说明","二次核对","0.111","0.222","尚未确认连接的顶点","状态："
]) assert(!rendered.includes(unwanted), "Leaked review/debug phrase: " + unwanted);

const fallback=funcs.formatOcrReviewGraphDisplay(
    [], "【多图边集已二次核对】\n复杂图形的独立逐边复核未完成"
);
for (const unwanted of ["多图边集","独立逐边","待核对","识别说明"]) {
    assert(!fallback.includes(unwanted), "Leaked raw fallback: "+unwanted);
}

const verified={
    ...graph,
    complete:true,
    vertices:[{id:"v1"},{id:"v2"},{id:"v3"}],
    edges:[{from:"v1",to:"v2"}]
};
const shown=funcs.formatStructuredGraphReview([verified]);
assert(shown.includes("孤立顶点"));
assert(!shown.includes("暂录"));
console.log("Graph card regression checks passed");
