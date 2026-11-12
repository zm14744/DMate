'use strict';
const assert = require('node:assert/strict');
const api = require('../static/math-diagram.js');

const document = {
  body_text: '',
  graphs: [{
    id: 'G1', name: '测试图', directed: false, weighted: false,
    vertices: [{id: 'v1', label: '甲'}, {id: 'v2', label: '乙'}],
    edges: [{id: 'e1', from: 'v1', to: 'v2', direction: 'undirected'}]
  }]
};
const dot = api.buildDot(document, 'graph');
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

const fakeViz = {
  render(source, options) {
    assert.equal(options.format, 'plain');
    assert.match(source, /"v1" -- "v2"/);
    return {status: 'success', output: plain, errors: []};
  }
};
api.layoutDocument(document, 'graph', fakeViz).then(result => {
  const vertices = result.document.graphs[0].vertices;
  assert.equal(result.engine, 'neato');
  assert.deepEqual([vertices[0].x, vertices[0].y], [0.09, 0.91]);
  assert.deepEqual([vertices[1].x, vertices[1].y], [0.91, 0.09]);
  console.log('PASS math diagram DOT generation, plain parsing and editor coordinates');
}).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
