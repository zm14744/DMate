/* Question graphs must never turn course proximity into question evidence. */
'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {build} = require('../static/question-knowledge-graph.js');
const course = require('../knowledge_graph.json').nodes;
const ids = result => result.nodes.map(node => node.id);
const edges = result => result.edges.map(edge => [edge.from, edge.to]);
const node = (id, prerequisites = [], category = 'fixture') => ({id, name:id, prerequisites, category});
const evidence = (quote, source = 'question') => [{source, quote}];
const record = (id, quote = id, source = 'question') => ({id, evidence:evidence(quote, source)});
const relation = (from, to, quote, source = 'question') => ({from, to, evidence:evidence(quote, source)});
const context = (nodes, relations = [], questionText = nodes.join(' '), solutionText = '') => ({
  questionText, solutionText,
  questionGraph:{version:1, nodes:nodes.map(id => record(id)), edges:relations}
});
const empty = {nodes:[],edges:[],seedIds:[],connectorIds:[],components:[]};
const deepFreeze = value => {
  if (value && typeof value === 'object') { Object.freeze(value); Object.values(value).forEach(deepFreeze); }
  return value;
};

test('every catalog concept can be a standalone question without any course neighbor', () => {
  for (const concept of course) {
    const result = build(course, {questionText:concept.name,
      questionGraph:{version:1, nodes:[record(concept.id, concept.name)], edges:[]}});
    assert.deepEqual(ids(result), [concept.id], concept.name + ': no implicit prerequisite or successor');
    assert.deepEqual(result.nodes[0].prerequisites, [], concept.name + ': no inherited course edge');
    assert.deepEqual(result.edges, []);
    assert.deepEqual(result.components, [[concept.id]]);
    assert.deepEqual(result.connectorIds, []);
  }
});

test('every course edge remains absent unless that particular question evidences it', () => {
  const byName = new Map(course.map(concept => [concept.name, concept]));
  for (const next of course) for (const previousName of next.prerequisites) {
    const previous = byName.get(previousName);
    if (!previous) continue;
    const quote = previous.name + ' and ' + next.name;
    const result = build(course, {questionText:quote, questionGraph:{version:1,
      nodes:[record(previous.id, previous.name),record(next.id, next.name)], edges:[]}});
    assert.equal(result.nodes.length, 2);
    assert.deepEqual(result.edges, [], quote + ': co-occurrence does not prove a dependency');
    assert.ok(result.nodes.every(concept => concept.prerequisites.length === 0));
    assert.equal(result.components.length, 2);
  }
});

test('the same concepts have different prerequisites and successors for different questions', () => {
  const input = [node('a'),node('b',['a']),node('c',['b'])];
  const first = build(input, context(['a','c'], [relation('a','c','a c')]));
  const second = build(input, context(['a','c'], [relation('c','a','a c')]));
  const third = build(input, context(['a','c']));
  assert.deepEqual(ids(first), ['a','c'], 'no intermediate course connector is added');
  assert.deepEqual(edges(first), [['a','c']]);
  assert.deepEqual(first.nodes.map(concept => concept.prerequisites), [[],['a']]);
  assert.deepEqual(edges(second), [['c','a']]);
  assert.deepEqual(second.nodes.map(concept => concept.prerequisites), [['c'],[]]);
  assert.deepEqual(third.nodes.map(concept => concept.prerequisites), [[],[]]);
  assert.deepEqual(third.components, [['a'],['c']]);
});

test('explicit dependencies can cross any module boundary without following course direction', () => {
  const input = Array.from({length:16}, (_, index) => node('n'+index, index ? ['n'+(index-1)] : [], 'module-'+index));
  const questionText = input.map(concept => concept.id).join(' ');
  const requested = input.map(concept => concept.id).reverse();
  const result = build(input, context(requested, [relation('n15','n0',questionText)], questionText));
  assert.deepEqual(ids(result), input.map(concept => concept.id), 'all actually involved concepts survive');
  assert.deepEqual(result.seedIds, ids(result));
  assert.deepEqual(edges(result), [['n15','n0']], 'only the evidenced per-question dependency is present');
  assert.equal(result.components.length, 15);
  assert.equal(new Set(result.nodes.map(concept => concept.category)).size, 16);
});

test('node and edge evidence must match the independently bound question or solution exactly', () => {
  const input = [node('a'),node('b',['a']),node('c',['a']),node('d')];
  const result = build(input, {questionText:'Question uses a', solutionText:'Solution derives b from a',
    questionGraph:{version:1, sources:{question:'invented c and d'}, nodes:[
      record('a','uses a'),record('b','derives b','solution'),record('c','invented c'),
      record('d','Solution derives b from a','question')
    ], edges:[relation('a','b','derives b from a','solution'),relation('b','a','not in the answer'),
      relation('a','c','uses a'),relation('a','b','Question uses a','untrusted-source')]}});
  assert.deepEqual(ids(result), ['a','b']);
  assert.deepEqual(edges(result), [['a','b']]);
  assert.deepEqual(result.nodes[1].prerequisites, ['a']);
});

test('missing, stale, malformed and course-derived legacy metadata never invent a question graph', () => {
  const legacy = {focusPoints:['集合运算'], knowledgePoints:['集合运算'], relatedPoints:['函数与映射'],
    prerequisitePoints:['基本计数原理'], knowledgePath:['集合运算','容斥原理']};
  assert.deepEqual(build(course, legacy), empty);
  assert.deepEqual(build(course, {...legacy, questionGraph:{version:1,nodes:[],edges:[]}}), empty);
  for (const questionGraph of [null, [], {}, {version:2,nodes:[],edges:[]},
    {version:1,nodes:null,edges:[]}, {version:1,nodes:[],edges:null}]) {
    assert.deepEqual(build(course, {...legacy,questionGraph}), empty);
  }
  assert.deepEqual(build(null, null), empty);
});

test('only independently verified node endpoints may participate in an evidenced edge', () => {
  const input = [node('a'),node('b'),node('c')];
  const result = build(input, {questionText:'a b', questionGraph:{version:1,
    nodes:[record('a'),record('b'),record('c'),record('unknown','a')], edges:[
      relation('a','b','a b'),relation('a','c','a b'),relation('a','unknown','a b'),
      relation('a','a','a b'),relation('b','a',' '),{from:'b',to:'a',evidence:[]} ]}});
  assert.deepEqual(ids(result), ['a','b']);
  assert.deepEqual(edges(result), [['a','b']]);
});

test('question ordering, duplicate records and cycles neither add concepts nor lose actual edges', () => {
  const input = [node('a',['c']),node('b',['a']),node('c',['b']),node('unused')];
  const questionText = 'a b c';
  const graph = {version:1,nodes:[record('c'),record('a'),record('b'),record('a')], edges:[
    relation('c','a',questionText),relation('b','c',questionText),relation('a','b',questionText),
    relation('a','b',questionText),relation('a','unused',questionText)]};
  const first = build(input,{questionText,questionGraph:graph});
  const second = build(input,{questionText,questionGraph:{...graph,nodes:graph.nodes.slice().reverse(),edges:graph.edges.slice().reverse()}});
  assert.deepEqual(first,second);
  assert.deepEqual(ids(first),['a','b','c']);
  assert.deepEqual(edges(first),[['a','b'],['b','c'],['c','a']]);
  assert.deepEqual(first.components,[['a','b','c']]);
});

test('source evidence preserves Unicode, punctuation and whitespace exactly', () => {
  const input = [node('a'),node('b')];
  const quote = '本题使用 a；同时讨论 b\nα ⊆ β';
  const valid = context(['a','b'],[],quote);
  valid.questionGraph.nodes = [record('a',quote),record('b','α ⊆ β')];
  assert.deepEqual(ids(build(input,valid)),['a','b']);
  valid.questionGraph.nodes[0] = record('a',quote.replace('使用','排除'));
  assert.deepEqual(ids(build(input,valid)),['b'], 'altered text is not silently accepted as evidence');
  valid.questionGraph.nodes[1] = record('b','α⊆β');
  assert.deepEqual(build(input,valid),empty);
});

test('source catalog and question metadata are immutable while question prerequisites replace course data', () => {
  const input = deepFreeze([node('a',['c'],'one'),node('b',['a'],'two'),node('c',[],'three')]);
  const requested = deepFreeze(context(['a','b'],[relation('b','a','a b')]));
  const before = JSON.stringify({input,requested});
  const result = build(input,requested);
  assert.equal(JSON.stringify({input,requested}),before);
  assert.deepEqual(result.nodes.map(concept => concept.prerequisites),[['b'],[]]);
  assert.ok(result.nodes.every(concept => concept !== input.find(original => original.id===concept.id)));
  assert.deepEqual(result.nodes.map(({prerequisites,...metadata}) => metadata),
    input.slice(0,2).map(({prerequisites,...metadata}) => metadata), 'canonical labels and categories remain available');
});
