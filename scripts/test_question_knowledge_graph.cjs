/* The focused course graph uses real edges and preserves every involved seed. */
'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {build, MAX_CONNECTOR_EDGES} = require('../static/question-knowledge-graph.js');
const course = require('../knowledge_graph.json').nodes;
const ids = result => result.nodes.map(node => node.id);
const edges = result => result.edges.map(edge => [edge.from, edge.to]);
const node = (id, prerequisites = [], category = 'fixture') => ({id, name:id, prerequisites, category});
const deepFreeze = value => {
  if (value && typeof value === 'object') { Object.freeze(value); Object.values(value).forEach(deepFreeze); }
  return value;
};

test('a single set question retains its four directly related course nodes across modules', () => {
  const result = build(course, {focusPoints:['集合运算'], knowledgePoints:['集合运算']});
  assert.deepEqual(ids(result), ['set_operation','relation_cartesian','function_mapping','count_inclusion']);
  assert.deepEqual(result.seedIds, ['set_operation']);
  assert.deepEqual(edges(result), [
    ['set_operation','relation_cartesian'], ['set_operation','function_mapping'], ['set_operation','count_inclusion']
  ]);
  assert.deepEqual(result.components, [ids(result)]);
  assert.deepEqual(result.connectorIds, []);
  assert.deepEqual(new Set(result.nodes.map(node => node.category)), new Set(['集合与关系','函数','计数与组合']));
});

test('all explicit core and support concepts survive without the old ten-seed cap', () => {
  const input = Array.from({length:16}, (_, index) => node('n'+index, [], 'module-'+index));
  const result = build(input, {focusPoints:['n15'], knowledgePoints:input.slice(0,7).map(n => n.name),
    prerequisitePoints:input.slice(7,11).map(n => n.name), knowledgePath:input.slice(11,15).map(n => n.name)});
  assert.deepEqual(ids(result), input.map(n => n.id));
  assert.deepEqual(result.seedIds, ids(result));
  assert.equal(result.components.length, 16, 'unrecorded relationships are not invented to connect seeds');
  assert.deepEqual(result.edges, []);
});

test('the real order/topological relation and logic/induction relations cross module boundaries', () => {
  const result = build(course, {focusPoints:['偏序关系','数学归纳法'], knowledgePoints:['拓扑排序','命题推理']});
  assert.ok(result.seedIds.includes('relation_order') && result.seedIds.includes('graph_topological'));
  assert.ok(result.seedIds.includes('logic_reasoning') && result.seedIds.includes('proof_induction'));
  assert.ok(edges(result).some(([from,to]) => from==='relation_order' && to==='graph_topological'));
  assert.ok(edges(result).some(([from,to]) => from==='logic_reasoning' && to==='proof_induction'));
  assert.equal(result.components.length, 2, 'the two distinct recorded curriculum branches stay separate');
});

test('explicit related concepts are retained as supporting seeds across modules', () => {
  const result = build(course, {focusPoints:['集合运算'], relatedPoints:['函数与映射','鸽巢原理']});
  assert.deepEqual(result.seedIds, ['set_operation','function_mapping','count_pigeonhole']);
  assert.ok(ids(result).includes('count_basic'), 'an involved related concept keeps its actual prerequisite');
  assert.ok(edges(result).some(([from,to]) => from==='set_operation' && to==='function_mapping'));
  assert.ok(edges(result).some(([from,to]) => from==='count_basic' && to==='count_pigeonhole'));
});

test('unknown focus metadata falls back to every recognized knowledge point', () => {
  const result = build(course, {focusPoints:['not in the course'], knowledgePoints:['集合运算','数学归纳法']});
  assert.ok(ids(result).includes('function_mapping'));
  assert.ok(ids(result).includes('proof_strong_induction'));
  assert.deepEqual(result.seedIds, ['proof_induction','set_operation']);
});

test('support-only metadata does not expand unrelated successor lessons', () => {
  const result = build(course, {relatedPoints:['函数与映射']});
  assert.deepEqual(ids(result), ['set_operation','function_mapping']);
  assert.deepEqual(result.seedIds, ['function_mapping']);
  assert.deepEqual(edges(result), [['set_operation','function_mapping']]);
});

test('a three-edge real path supplies only the missing connector and preserves edge direction', () => {
  const input = [node('a'),node('b',['a']),node('c',['b']),node('d',['c'])];
  const result = build(input, {focusPoints:['d'], knowledgePoints:['a','d']});
  assert.deepEqual(ids(result), ['a','b','c','d']);
  assert.deepEqual(result.seedIds, ['a','d']);
  assert.deepEqual(result.connectorIds, ['b']);
  assert.deepEqual(edges(result), [['a','b'],['b','c'],['c','d']]);
  assert.equal(result.components.length, 1);
  assert.equal(MAX_CONNECTOR_EDGES, 3);
});

test('shared prerequisites connect branches without pretending that sibling concepts imply one another', () => {
  const input = [node('root'),node('left',['root']),node('middle',['root']),node('right',['middle'])];
  const result = build(input, {focusPoints:['right'], knowledgePoints:['left','right']});
  assert.deepEqual(ids(result), ['root','left','middle','right']);
  assert.deepEqual(edges(result), [['root','left'],['root','middle'],['middle','right']]);
  assert.equal(result.components.length, 1);
  assert.equal(result.edges.some(edge => edge.from==='left' && edge.to==='right'), false);
});

test('distant paths do not drag unrelated intermediate modules into the question', () => {
  const input = [node('a'),node('b',['a']),node('c',['b']),node('d',['c']),node('e',['d']),node('f',['e'])];
  const result = build(input, {focusPoints:['a','f']});
  assert.deepEqual(ids(result), ['a','b','e','f']);
  assert.deepEqual(result.components, [['a','b'],['e','f']]);
  assert.deepEqual(result.connectorIds, []);
  assert.deepEqual(edges(result), [['a','b'],['e','f']]);
});

test('shortest-path ties follow source graph order, independent of seed array order', () => {
  const input = [node('a'),node('b',['a']),node('alternate',['a']),node('d',['b','alternate']),node('e',['d'])];
  const first = build(input, {focusPoints:['e'], knowledgePoints:['a','e']});
  const second = build(input, {focusPoints:['e'], knowledgePoints:['e','a']});
  assert.deepEqual(first, second);
  assert.ok(first.connectorIds.includes('b'));
  assert.equal(first.connectorIds.includes('alternate'), false, 'only one equally short bridge is needed');
});

test('cycles terminate and duplicate or unknown concepts never create extra nodes or edges', () => {
  const input = [node('a',['c','c','missing']),node('b',['a']),node('c',['b']),node('unused')];
  const result = build(input, {focusPoints:['a','a','missing'], knowledgePoints:['c', null, '']});
  assert.deepEqual(ids(result), ['a','b','c']);
  assert.deepEqual(result.seedIds, ['a','c']);
  assert.deepEqual(edges(result), [['c','a'],['a','b'],['b','c']]);
  assert.equal(result.components.length, 1);
  assert.deepEqual(build(course, {focusPoints:['unrecognized concept']}).nodes, []);
  assert.deepEqual(build(null, null), {nodes:[],edges:[],seedIds:[],connectorIds:[],components:[]});
});

test('graph and teaching metadata are read-only, while all output edges come from course prerequisites', () => {
  const input = deepFreeze(JSON.parse(JSON.stringify(course)));
  const context = deepFreeze({focusPoints:['生成函数'], knowledgePoints:['递推关系建模','排列与组合'],
    knowledgePath:['二项式定理'], prerequisitePoints:['基本计数原理']});
  const before = JSON.stringify({input,context});
  const result = build(input, context);
  assert.equal(JSON.stringify({input,context}), before);
  for (const edge of result.edges) {
    const previous = course.find(n => n.id===edge.from), next = course.find(n => n.id===edge.to);
    assert.ok(next.prerequisites.includes(previous.name), 'rendered edges must be recorded, directed prerequisites');
  }
  assert.ok(result.seedIds.includes('recurrence_model') && result.seedIds.includes('count_perm_comb'));
  assert.ok(result.nodes.every(n => input.includes(n)), 'original canonical node metadata remains available to renderers');
});
