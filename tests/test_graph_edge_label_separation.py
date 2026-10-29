"""Printed edge names stay distinct from weights throughout review and display."""
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from graph_edge_labels import separate_graph_edge_labels, separate_weight_and_edge_label
from graph_qwen_targeted import validate_draft
from graph_qwen_targeted_review import merge_source_review, plan_reviews
from graph_schema import canonical_graph, display_graph
from graph_semantic_schema import normalize_semantic_document
from test_ocr_application_contract import application


ROOT = Path(__file__).resolve().parents[1]


def graph(label='200', weight=200, *, explicit=None, name='带权无向图'):
    edge = {'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'undirected',
            'edge_label': label, 'weight': weight, 'status': 'accepted'}
    if explicit is not None:
        edge['edge_label_is_explicit'] = explicit
    return {'id': 'G1', 'name': name, 'weighted': True, 'directed': False, 'multigraph': False,
            'complete': True,
            'vertices': [{'id': 'a', 'label': 'A', 'x': .2, 'y': .2},
                         {'id': 'b', 'label': 'B', 'x': .8, 'y': .8}], 'edges': [edge]}


@pytest.mark.parametrize('label,weight', [('200', 200), ('200.0', '2e2'), (0, '0.00'),
    ('−1/2', '-0.5'), ('1 / 2', .5), ('\\frac{1}{2}', '0.50'), ('0.1', '1/10'), ('２００', 200)])
def test_repeated_weight_is_removed_as_a_name_without_changing_any_edge_fact(label, weight):
    sample = graph(label, weight)
    before = copy.deepcopy(sample)
    changed = separate_graph_edge_labels(sample)
    assert sample['edges'][0]['edge_label'] is None
    assert changed == [{'kind': 'duplicate_weight_edge_label_removed', 'edge_id': 'e1', 'previous_edge_label': label}]
    before['edges'][0]['edge_label'] = None
    assert sample == before


@pytest.mark.parametrize('label,weight,explicit', [('e₁', 200, None), ('A', 200, None),
    ('2', 200, None), ('200', 200, True), ('①', 1, None), ('1+1', 2, None),
    ('zero', 0, None), ('0', None, None), ('1/0', 0, None), ('1e9999999999', 0, None)])
def test_real_names_and_unresolved_nonliteral_text_are_not_guessed_away(label, weight, explicit):
    sample = graph(label, weight, explicit=explicit)
    before = copy.deepcopy(sample)
    assert separate_weight_and_edge_label(sample['edges'][0], weighted=sample['weighted']) is False
    assert sample == before


@pytest.mark.parametrize('explicit', [None, False, True])
def test_draft_semantic_and_public_projection_use_the_same_name_weight_separation(explicit):
    sample = graph(explicit=explicit)
    expected = '200' if explicit is True else None
    draft = validate_draft({'body_text': '', 'graphs': [copy.deepcopy(sample)]})['graphs'][0]
    canonical = canonical_graph(copy.deepcopy(sample))
    semantic = normalize_semantic_document({'body_text': '', 'graphs': [copy.deepcopy(sample)]}, reviewed=True)
    assert not semantic['semantic_issues']
    for current in (draft, canonical, display_graph(canonical), semantic['graphs'][0], display_graph(semantic['graphs'][0])):
        edge = current['edges'][0]
        assert edge['edge_label'] == expected
        assert edge['weight'] == 200 and edge['from'] == 'a' and edge['to'] == 'b'
        assert len(current['edges']) == 1
        if explicit is not None:
            assert edge['edge_label_is_explicit'] is explicit
    if explicit is not True:
        assert any(note['kind'] == 'duplicate_weight_edge_label_removed' for note in semantic['normalization_notes'])


def review_source(explicit=None):
    rows = []
    for source, target, flow, label in [('a', 'c', 'out', '200'), ('c', 'a', 'in', '200.0')]:
        edge = {'to': target, 'flow': flow, 'weight': 200, 'edge_label': label}
        if explicit is not None:
            edge['edge_label_is_explicit'] = explicit
        rows.append({'source_id': source, 'complete': True, 'edges': [edge]})
    return {'graphs': [{'graph_id': 'G1', 'reads': rows}]}


@pytest.mark.parametrize('explicit', [None, True])
def test_two_endpoint_review_does_not_reintroduce_a_weight_as_an_unnamed_edge(explicit):
    from test_qwen_targeted import graph as original, evidence
    sample = original()
    updated, issues, _ = merge_source_review([sample], plan_reviews([sample], evidence(sample)), review_source(explicit))
    assert not issues
    edge = next(edge for edge in updated[0]['edges'] if edge['id'] == 'r1')
    assert edge['weight'] == 200
    assert edge['edge_label'] == ('200' if explicit is True else None)
    if explicit is True:
        assert edge['edge_label_is_explicit'] is True
    assert len(updated[0]['edges']) == 2


def test_numeric_name_needs_independent_support_at_both_reviewed_endpoints():
    from test_qwen_targeted import graph as original, evidence
    sample = original()
    reply = review_source(True)
    reply['graphs'][0]['reads'][1]['edges'][0].pop('edge_label_is_explicit')
    updated, issues, _ = merge_source_review([sample], plan_reviews([sample], evidence(sample)), reply)
    assert updated[0]['edges'] == sample['edges']
    assert any(issue['kind'] == 'endpoint_reading_disagreement' for issue in issues)


def test_formatter_legacy_dedup_and_type_visibility_preserve_the_original_object():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node unavailable')
    script = r'''
const assert=require('node:assert/strict'),fmt=require('./static/graph-editor-format.js');
const graph=JSON.parse(process.argv[1]),before=JSON.stringify(graph),row=fmt.graphRows(graph,0);
assert.equal(JSON.stringify(graph),before); // A stored signed snapshot must stay unchanged.
assert.deepEqual(row.named,[]);assert.equal(row.relations[0].txt,'A—B（权值：200）');
assert.equal(row.showType,false);assert.equal(row.type,'无向 · 带权');
assert(!fmt.toMarkdown([graph]).includes('*无向 · 带权*'));
assert(!fmt.toPlain([graph]).includes('    无向 · 带权'));
for(const name of ['G1','无向图','有向带权图']){
 assert.equal(fmt.graphRows({...graph,name},0).showType,true);
}
assert.equal(fmt.graphRows({...graph,name:'无向无权图',weighted:false},0).showType,false);
assert.equal(fmt.graphRows({...graph,name:'无向带权图',directed:true},0).showType,true);
assert.equal(fmt.edgeName({...graph.edges[0],edge_label:'200.0',weight:'2e2'}),null);
assert.equal(fmt.edgeName({...graph.edges[0],edge_label:'1/2',weight:'.5'}),null);
assert.equal(fmt.edgeName({...graph.edges[0],edge_label:'0',weight:0}),null);
assert.equal(fmt.edgeName({...graph.edges[0],edge_label:'e₁'}),'e₁');
assert.equal(fmt.edgeName({...graph.edges[0],edge_label:'9007199254740993',weight:'9007199254740992'}),'9007199254740993');
assert.equal(fmt.edgeName({...graph.edges[0],edge_label_is_explicit:true}),'200');
assert.deepEqual(fmt.graphRows({...graph,edges:[{...graph.edges[0],edge_label_is_explicit:true}]},0).named,['200']);
'''
    subprocess.run([node, '-e', script, json.dumps(graph(), ensure_ascii=False)], cwd=ROOT,
                   check=True, capture_output=True, text=True)


@pytest.mark.parametrize('explicit', [None, True])
def test_confirmed_signed_document_and_browser_snapshot_keep_actual_edge_name_semantics(application, monkeypatch, tmp_path, explicit):
    import hashlib
    from graph_confirmation import COOKIE_NAME, register_recognition
    from test_semantic_chat_snapshot_frontend import run_js
    _, client, _ = application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path / 'edge-name-confirm.sqlite3'))
    client.get('/graph/session')
    owner = hashlib.sha256((client.get_cookie(COOKIE_NAME).value + ':guest').encode()).hexdigest()
    register_recognition(owner, 'edge-names', 'a' * 64)
    result = client.post('/graph/confirm', json={'confirmed': True, 'request_id': 'edge-names',
        'source_sha256': 'a' * 64, 'document': {'body_text': '', 'graphs': [graph(explicit=explicit)]}})
    assert result.status_code == 200, result.get_json()
    context = result.get_json()['semantic_context']
    sanitized = run_js({'operation': 'sanitize', 'context': context})
    assert sanitized['document'] == context['document']
    edge = sanitized['document']['graphs'][0]['edges'][0]
    assert edge['edge_label'] == ('200' if explicit is True else None)
    assert edge['weight'] == 200
