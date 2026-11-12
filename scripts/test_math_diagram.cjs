'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const api = require('../static/math-diagram.js');

(async () => {
  const vendorPath = path.join(__dirname, '..', 'static', 'vendor', 'viz-js-3.31.0', 'viz-global.js');
  const vendorBytes = fs.readFileSync(vendorPath);
  const sri = 'sha256-' + crypto.createHash('sha256').update(vendorBytes).digest('base64');
  assert.equal(sri, 'sha256-yeCzEPmIORDgHGYFS0i3/0vj2GlRQRFmNecrCvFSaS4=',
    'The vendored Graphviz bundle must match its verified upstream bytes.');

  const Viz = require(vendorPath);
  const viz = await Viz.instance();
  assert.ok(viz.graphvizVersion, 'The vendored layout engine should report its Graphviz version.');

  const graphDocument = {
    body_text: '',
    graphs: [{
      id: 'G1', name: '测试图', directed: false, weighted: false,
      vertices: [{id: 'v1', label: '甲'}, {id: 'v2', label: '乙'}],
      edges: [{id: 'e1', from: 'v1', to: 'v2', direction: 'undirected'}]
    }]
  };
  const dot = api.buildDot(graphDocument, 'graph');
  assert.match(dot, /graph DMate/);
  assert.match(dot, /甲/);
  assert.match(dot, /"v1" -- "v2"/);

  const plain = [
    'graph 1 2 2',
    'node v1 0 0 0.4 0.4 A solid circle black white',
    'node v2 2 2 0.4 0.4 B solid circle black white',
    'stop'
  ].join('\n');
  const positions = api.parsePlain(plain);
  assert.deepEqual(positions.get('v1'), [0, 0]);
  assert.deepEqual(positions.get('v2'), [2, 2]);
  assert.deepEqual(api.parsePlain('node "vertex-1" 0.25 0.75 0.4 0.4 A solid circle black white').get('vertex-1'), [0.25, 0.75]);

  const laidOut = await api.layoutDocument(graphDocument, 'graph', viz);
  assert.equal(laidOut.engine, 'neato');
  for (const vertex of laidOut.document.graphs[0].vertices) {
    assert.ok(Number.isFinite(vertex.x) && vertex.x >= 0 && vertex.x <= 1);
    assert.ok(Number.isFinite(vertex.y) && vertex.y >= 0 && vertex.y <= 1);
  }
  const hyphenDocument = JSON.parse(JSON.stringify(graphDocument));
  hyphenDocument.graphs[0].vertices[0].id = 'vertex-1';
  hyphenDocument.graphs[0].edges[0].from = 'vertex-1';
  const hyphenLayout = await api.layoutDocument(hyphenDocument, 'graph', viz);
  assert.equal(hyphenLayout.document.graphs[0].vertices[0].id, 'vertex-1');
  assert.ok(Number.isFinite(hyphenLayout.document.graphs[0].vertices[0].x), 'Valid hyphenated IDs must survive real Graphviz output');

  const hasseDocument = {
    body_text: '',
    graphs: [{
      id: 'G1', name: '哈斯图', directed: false, weighted: false,
      vertices: [
        {id: 'v1', label: '1'}, {id: 'v2', label: '2'}, {id: 'v3', label: '4'}
      ],
      edges: [
        {id: 'e1', from: 'v1', to: 'v2', direction: 'undirected'},
        {id: 'e2', from: 'v2', to: 'v3', direction: 'undirected'}
      ]
    }]
  };
  const hasse = await api.layoutDocument(hasseDocument, 'hasse', viz);
  assert.equal(hasse.engine, 'dot');
  assert.equal(hasse.document.graphs[0].vertices.length, 3);

  const cayleyDocument = {
    body_text: '',
    graphs: [{
      id: 'G1', name: 'Z4 Cayley 图', directed: true, weighted: false,
      vertices: [0, 1, 2, 3].map(value => ({id: 'v' + value, label: String(value)})),
      edges: [0, 1, 2, 3].map(value => ({
        id: 'e' + value, from: 'v' + value, to: 'v' + ((value + 1) % 4),
        direction: 'forward', edge_label: '+1'
      }))
    }]
  };
  const cayley = await api.layoutDocument(cayleyDocument, 'cyclic_cayley', viz);
  assert.equal(cayley.engine, 'circo');
  assert.equal(cayley.document.graphs[0].vertices.length, 4);

  // A valid Hasse cover used to be drawn straight through an unrelated vertex
  // after throwing away Graphviz's spline. Keep its actual routed geometry.
  const covers = [[0,1],[1,2],[1,4],[2,3],[2,5],[3,6],[3,7],[3,11],
    [4,8],[4,9],[5,7],[5,8],[6,10],[8,11],[9,10],[9,11]];
  const routedInput = {body_text:'', graphs:[{id:'G1', name:'Hasse routing', directed:false, weighted:false,
    vertices:Array.from({length:12}, (_, i) => ({id:'v' + i, label:String(i)})),
    edges:covers.map(([from,to], i) => ({id:'e' + i, from:'v' + from, to:'v' + to, direction:'undirected'}))}]};
  const routed = (await api.layoutDocument(routedInput, 'hasse', viz)).document;
  const routedGraph = routed.graphs[0], obstacle = routedGraph.vertices.find(vertex => vertex.id === 'v7');
  const routedEdge = routedGraph.edges.find(edge => edge.id === 'e7');
  const segmentDistance = (point, from, to) => {
    const dx=to[0]-from[0], dy=to[1]-from[1], length=dx*dx+dy*dy;
    const t=length ? Math.max(0,Math.min(1,((point.x-from[0])*dx+(point.y-from[1])*dy)/length)) : 0;
    return Math.hypot(point.x-from[0]-t*dx,point.y-from[1]-t*dy);
  };
  assert.ok(segmentDistance(obstacle,routedEdge.path[0],routedEdge.path.at(-1)) < .002, 'Dropping the route would create a false incidence');
  assert.ok(Math.min(...routedEdge.path.slice(1).map((point,i) => segmentDistance(obstacle,routedEdge.path[i],point))) > .03,
    'The routed edge must clear the unrelated vertex');
  for (const edge of routedGraph.edges) {
    assert.ok(edge.path.length >= 2 && edge.path.length <= 128);
    assert.ok(edge.path.every(point => point.every(value => Number.isFinite(value) && value >= 0 && value <= 1)));
  }
  const model = require('../static/graph-editor-model.js');
  const imported = model.importDocument(routed);
  assert.deepEqual(model.validateDocument(imported), []);
  assert.deepEqual(imported.graphs[0].edges.map(edge => edge.path), routedGraph.edges.map(edge => edge.path),
    'Importing a generated diagram must preserve all editable edge routes');

  const originalFetch = global.fetch;
  try {
    global.fetch = async () => ({ok:true, json:async () => null});
    await assert.rejects(api.generate('Draw a graph', 'en'), /invalid response/i);
    await assert.rejects(api.generate('画图', 'zh-CN'), /返回内容无效/);
    global.fetch = async () => ({ok:true, json:async () => { throw new SyntaxError('bad JSON'); }});
    await assert.rejects(api.generate('Draw a graph', 'en'), /invalid response/i);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(api.generate('Draw a graph', 'en', controller.signal), {name:'AbortError'});
  } finally { global.fetch = originalFetch; }

  console.log('PASS real Graphviz WASM layout, pinned bundle integrity, Hasse and Cayley layouts');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
