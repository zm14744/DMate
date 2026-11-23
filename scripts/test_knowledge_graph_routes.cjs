'use strict';
// Pure geometry checks; no browser, server or model request is needed.
const assert = require('node:assert/strict');
require('../static/knowledge-graph-labels.js');
const routes = globalThis.DMateKnowledgeGraphLabels;

function sample(start, segment, t) {
  const u = 1 - t;
  return [0, 1].map(axis => u ** 3 * start[axis] + 3 * u * u * t * segment[axis]
    + 3 * u * t * t * segment[axis + 2] + t ** 3 * segment[axis + 4]);
}

function check(name, positions, start, end, width, height, crossSize, vertical = false) {
  const route = routes.routeConnection('from', 'to', start, end, positions, width, height, crossSize, vertical);
  assert.equal(route.type, 'curves', name);
  assert.ok(route.segments.length > 0, name + ': an edge is retained');
  const commands = routes.routeSvgD(route).match(/[MLCQAHVSTZ]/g);
  assert.deepEqual(commands, ['M', ...route.segments.map(() => 'C')], name + ': no straight SVG commands');
  let previous = [start.x, start.y];
  for (const segment of route.segments) {
    assert.equal(segment.length, 6); assert.ok(segment.every(Number.isFinite));
    const chord = [segment[4] - previous[0], segment[5] - previous[1]];
    const cross = index => chord[0] * (segment[index + 1] - previous[1]) - chord[1] * (segment[index] - previous[0]);
    assert.ok(Math.max(Math.abs(cross(0)), Math.abs(cross(2))) > 1e-6,
      name + ': every cubic has genuine curvature instead of collinear control points');
    for (let step = 1; step < 200; step++) {
      const point = sample(previous, segment, step / 200);
      assert.ok((vertical ? point[0] : point[1]) >= -.001
        && (vertical ? point[0] : point[1]) <= crossSize + .001, name + ': curve remains in its cross-axis viewport');
      for (const [id, node] of positions) {
        assert.ok(!(point[0] > node.x + .001 && point[0] < node.x + width - .001
          && point[1] > node.y + .001 && point[1] < node.y + height - .001),
        name + ': curve avoids node ' + id);
      }
    }
    previous = segment.slice(4);
  }
  assert.deepEqual(previous, [end.x, end.y], name + ': preserve exact ports');
  const calls = [];
  routes.strokeCanvasRoute({beginPath(){},moveTo(...point){calls.push(point);},
    bezierCurveTo(...segment){calls.push(segment);},stroke(){}}, route);
  assert.deepEqual(calls, [[start.x,start.y], ...route.segments], name + ': PNG and SVG use identical cubic geometry');
  console.log('PASS ' + name + ': ' + route.segments.length + ' genuinely curved cubics, clear nodes, exact ports and Canvas parity');
}

check('horizontal aligned', new Map([['from',{x:20,y:40}],['to',{x:300,y:40}]]),
  {x:164,y:60}, {x:300,y:60}, 144, 40, 160);
check('horizontal detour', new Map([['from',{x:20,y:100}],['middle',{x:260,y:100}],['to',{x:500,y:100}]]),
  {x:164,y:120}, {x:500,y:120}, 144, 40, 260);
check('horizontal diagonal obstacle', new Map([['from',{x:20,y:20}],['middle',{x:260,y:100}],['to',{x:500,y:180}]]),
  {x:164,y:40}, {x:500,y:200}, 144, 40, 300);
check('vertical top to bottom', new Map([['from',{x:40,y:20}],['to',{x:40,y:300}]]),
  {x:112,y:60}, {x:112,y:300}, 144, 40, 300, true);
check('vertical bottom to top', new Map([['from',{x:40,y:300}],['to',{x:40,y:20}]]),
  {x:112,y:300}, {x:112,y:60}, 144, 40, 300, true);
check('vertical detour', new Map([['from',{x:40,y:20}],['middle',{x:40,y:160}],['to',{x:40,y:340}]]),
  {x:112,y:60}, {x:112,y:340}, 144, 40, 300, true);
const crowded = new Map([['from',{x:218,y:20}],['to',{x:218,y:900}]]);
for (let row = 0; row < 6; row++) for (let column = 0; column < 3; column++)
  crowded.set('middle-' + row + '-' + column, {x:38 + column * 180,y:140 + row * 110});
check('long three-column mobile detour', crowded, {x:290,y:60}, {x:290,y:900}, 144, 40, 588, true);
