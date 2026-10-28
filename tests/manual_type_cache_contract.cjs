'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('static/script.js', 'utf8');
const start = script.indexOf('function reuseVerifiedTypeForSameRegion(task, polygon) {');
const end = script.indexOf('\nasync function editOcrTask(id) {', start);
assert.ok(start >= 0 && end > start, 'Real production cache helper must be present');
const { reuseVerifiedTypeForSameRegion } = vm.runInNewContext(
  script.slice(start, end) + '\n({ reuseVerifiedTypeForSameRegion })');
const rectangle = [[.1,.2],[.4,.2],[.4,.7],[.1,.7]];
const figure = { id: 'G1', bbox: [.1,.2,.4,.7], directed: true, weighted: false,
  vertices: [], edges: [] };
const task = { result: { workflow_profile: 'layout_only',
    diagnostics: {type_review_calls: 1} },
  initialDocument: {graphs: [figure]} };
// An exact user rectangle needs no second paid API call.
const reused = reuseVerifiedTypeForSameRegion(task, rectangle);
assert.equal(reused?.reused_verified_original, true);
assert.equal(reused?.directed, true);
assert.equal(reused?.weighted, false);
// New or materially changed regions always require fresh visual evidence.
assert.equal(reuseVerifiedTypeForSameRegion(task,
  [[.12,.2],[.4,.2],[.4,.7],[.12,.7]]), null);
assert.equal(reuseVerifiedTypeForSameRegion(task,
  [[.1,.2],[.4,.2],[.35,.7],[.1,.7]]), null);
assert.equal(reuseVerifiedTypeForSameRegion({...task,
  result: {workflow_profile: 'layout_only', diagnostics: {type_review_calls: 0}}},
  rectangle), null);
assert.equal(reuseVerifiedTypeForSameRegion({...task,
  initialDocument: {graphs: [{...figure, weighted: undefined}]}},
  rectangle), null);
console.log('manual region type cache: correct region only, no guessed metadata');
