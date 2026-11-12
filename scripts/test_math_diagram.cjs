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

  const laidOut = await api.layoutDocument(graphDocument, 'graph', viz);
  assert.equal(laidOut.engine, 'neato');
  for (const vertex of laidOut.document.graphs[0].vertices) {
    assert.ok(Number.isFinite(vertex.x) && vertex.x >= 0 && vertex.x <= 1);
    assert.ok(Number.isFinite(vertex.y) && vertex.y >= 0 && vertex.y <= 1);
  }

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

  console.log('PASS real Graphviz WASM layout, pinned bundle integrity, Hasse and Cayley layouts');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
