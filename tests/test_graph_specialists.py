"""Budget, non-regression and evidence-contract checks, not OCR accuracy."""
import copy
import json
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from graph_attribute_review import AttributeReview
from graph_topology_review import TopologyReview
from graph_relation import recover_relations
from graph_staged import Budget, recognize_staged
from vision_provider import VisionError


class Provider:
    def __init__(self, name, result=None, fail=None):
        self.name = name
        self.model = 'glm-5.3-flash' if name == 'glm' else 'qwen3-vl-plus'
        self.thinking = name == 'glm'
        self.reasoning_effort = 'low' if name == 'glm' else None
        self.retries = 0
        self.result, self.fail, self.calls = result, fail, []

    def available(self): return True

    def __call__(self, prompt, images, budget):
        seconds = budget.take()
        self.calls.append((prompt, images, seconds))
        if self.fail:
            raise VisionError(self.fail)
        return copy.deepcopy(self.result)


def scene(*, weighted=True, directed=False, arrow=None):
    path = [[.1, .5], [.9, .5]]
    source = {'id': 'G1', 'bbox': [0, 0, 1, 1], 'directed': directed,
        'weighted': weighted, 'multigraph': True, 'node_complete': True,
        'vertices': [{'id': 'a', 'x': .1, 'y': .5}, {'id': 'b', 'x': .9, 'y': .5}],
        'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'path': path,
            'direction': 'forward' if directed else 'undirected', 'weight': None,
            'evidence': [{'source': 'node_read', 'vertex': v} for v in ('a', 'b')]}]}
    trace = {'from': 'a', 'to': 'b', 'path': path, 'score': 1, 'method': 'unit_fixture'}
    if arrow: trace['arrow_candidate'] = arrow
    ctx = {'graph': source, 'traces': [trace], 'review': {}}
    graph = recover_relations(source, [trace])
    image = Image.new('RGB', (400, 400), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((40, 200, 360, 200), fill='black', width=2)
    draw.text((198, 208), '5', fill='black')
    return graph, image, {'G1': ctx}


def observation(**fields):
    return {'attributes': [{'graph_id': 'G1', 'edge_id': 'e1',
        'weight': 5, 'weight_text': '5', 'weight_position': [.5, .535], **fields}]}


def test_weight_specialist_fills_only_missing_attribute_and_keeps_topology():
    g, image, _ = scene()
    before = copy.deepcopy(g)
    p = Provider('glm', observation(direction='reverse', visible=False))
    reviewer = AttributeReview(p)
    budget = Budget()
    output = reviewer.apply([g], image, budget)
    e = output[0]['edges'][0]
    assert e['weight'] == 5 and e['direction'] == 'undirected'
    assert (e['id'], e['from'], e['to']) == ('e1', 'a', 'b')
    assert output[0]['vertices'] == g['vertices'] and output[0]['directed'] is False
    assert e['status'] == 'accepted' and output[0]['complete'] is False
    assert g == before and budget.remaining == 6 and len(p.calls) == 1
    assert p.calls[0][2] <= 20
    question = json.loads(p.calls[0][0].split('\n')[-1])['questions'][0]
    assert question['fields'] == ['weight'] and 'weight' not in question and 'direction' not in question


@pytest.mark.parametrize('fields', [
    {'weight_position': [0, 0]}, {'weight_position': [.1, .5]},
    {'weight_text': 'e5'}, {'weight_text': '6'}, {'weight': True},
    {'weight': 'NaN'}, {'weight_text': '1/0'},
])
def test_unbound_or_invalid_weight_never_overwrites_primary(fields):
    g, image, _ = scene()
    reviewer = AttributeReview(Provider('glm', observation(**fields)))
    assert reviewer.apply([g], image, Budget())[0]['edges'][0]['weight'] is None


def test_existing_weight_is_not_sent_to_or_overwritten_by_specialist():
    g, image, _ = scene()
    g['edges'][0]['weight'] = 9
    p = Provider('glm', observation())
    assert AttributeReview(p).apply([g], image, Budget()) == [g]
    assert not p.calls


def test_decimal_weight_preserves_numerical_format():
    g, image, _ = scene()
    p = Provider('glm', observation(weight=5.5, weight_text='5.5'))
    assert AttributeReview(p).apply([g], image, Budget())[0]['edges'][0]['weight'] == 5.5


def test_direction_requires_independent_pixels_and_cannot_flip_known_direction():
    arrow = {'from': 'b', 'to': 'a', 'score': .8}
    g, image, _ = scene(weighted=False, directed=True, arrow=arrow)
    assert g['edges'][0]['direction'] == 'unknown'
    p = Provider('glm', observation(direction='reverse', arrow_tip=[.5, .5]))
    e = AttributeReview(p).apply([g], image, Budget())[0]['edges'][0]
    assert (e['from'], e['to'], e['direction']) == ('b', 'a', 'forward')
    g['edges'][0]['direction'] = 'forward'
    p = Provider('glm', observation(direction='reverse', arrow_tip=[.5, .5]))
    assert AttributeReview(p).apply([g], image, Budget()) == [g] and not p.calls


@pytest.mark.parametrize('kind', ['transport_failed', 'http_error'])
def test_failed_specialist_retains_actual_primary_without_retry(kind):
    g, image, _ = scene()
    p = Provider('glm', fail=kind)
    reviewer = AttributeReview(p)
    assert reviewer.apply([g], image, Budget()) == [g]
    assert len(p.calls) == 1 and reviewer.events[-1]['status'] == 'failed'
    assert reviewer.events[-1]['primary_result_retained']


def test_no_secondary_after_primary_failure_or_exhausted_budget():
    g, image, _ = scene()
    for kwargs, budget in [({'primary_ok': False}, Budget()), ({}, Budget(calls=0))]:
        p = Provider('glm', observation())
        reviewer = AttributeReview(p)
        assert reviewer.apply([g], image, budget, **kwargs) == [g] and not p.calls
        assert reviewer.primary_graphs == [g]


def type_observation(**options):
    return {'graph_id': 'G1', 'directed': False,
        'decisions': [{'id': 'e1', 'visible': True, 'direction': 'undirected'}], **options}


def test_qwen_can_correct_glm_type_only_after_complete_independent_panel_review():
    g, image, ctx = scene(weighted=False, directed=True)
    p = Provider('qwen', type_observation())
    reviewer = TopologyReview(p)
    out = reviewer.apply([g], image, Budget(), context=ctx)
    assert out[0]['directed'] is False and out[0]['edges'][0]['direction'] == 'undirected'
    assert out[0]['vertices'] == g['vertices']
    assert [e['id'] for e in out[0]['edges']] == ['e1']
    assert g['directed'] is True and reviewer.events[-1]['type_change']['observed'] is False
    payload = json.loads(p.calls[0][0].split('\n')[-1])
    assert 'directed' not in payload and 'direction' not in payload['candidates'][0]


def test_positive_arrow_pixels_prevent_graph_type_downgrade():
    g, image, ctx = scene(weighted=False, directed=True,
        arrow={'from': 'a', 'to': 'b', 'score': .8})
    reviewer = TopologyReview(Provider('qwen', type_observation()))
    out = reviewer.apply([g], image, Budget(), context=ctx)
    assert out[0]['directed'] is True
    assert 'type_change' not in reviewer.events[-1]


def test_unknown_candidate_ids_reject_entire_specialist_response():
    g, image, ctx = scene(weighted=False, directed=True)
    result = type_observation(decisions=[{'id': 'invented', 'visible': True, 'direction': 'undirected'}])
    reviewer = TopologyReview(Provider('qwen', result))
    assert reviewer.apply([g], image, Budget(), context=ctx) == [g]
    assert reviewer.events[-1]['status'] == 'failed'


def test_glm_weighted_panels_stay_on_primary_and_cannot_be_replaced_by_qwen():
    g, image, ctx = scene()
    p = Provider('qwen', type_observation())
    assert TopologyReview(p).apply([g], image, Budget(), context=ctx) == [g] and not p.calls


def test_primary_roles_and_glm_effort_must_be_explicit_before_image_or_api():
    a, b = AttributeReview(Provider('glm')), TopologyReview(Provider('qwen'))
    a.validate_primary(Provider('qwen')); b.validate_primary(Provider('glm'))
    with pytest.raises(ValueError): a.validate_primary(Provider('glm'))
    with pytest.raises(ValueError): b.validate_primary(Provider('qwen'))
    with pytest.raises(ValueError): recognize_staged(b'not-an-image', provider=Provider('glm'), specialist=a)
    bad = Provider('glm'); bad.reasoning_effort = 'high'
    with pytest.raises(ValueError): AttributeReview(bad)
    with pytest.raises(ValueError): b.validate_primary(bad)


def test_report_scores_retained_primary_but_counts_secondary_failure_and_usage_once(tmp_path):
    from graph_ab_metrics import compare_graphs
    from scripts.benchmark_graph_specialists import write_reports
    g, _, _ = scene()
    metric = compare_graphs([g], [g])
    rows = []
    for p in ('qwen', 'glm'):
        rows.append({'case_id': 'original', 'sha256': 'fixture', 'primary': p,
            'primary_status': 'success', 'status': 'degraded_specialist_failure',
            'seconds': 30, 'primary_seconds': 20,
            'requests': [{'status': 200, 'http_status': 200, 'seconds': 20,
                'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}},
                {'status': 'transport_failed', 'error': 'transport_failed',
                 'seconds': 10, 'confirmed_timeout': True}],
            'specialist_events': [{'routed': True, 'status': 'failed'}],
            **{k: metric for k in ('baseline_metrics', 'metrics', 'baseline_accepted_metrics', 'accepted_metrics')}})
    write_reports(tmp_path, rows, {})
    report = json.loads((tmp_path/'comparison.json').read_text())
    assert report['common_completed_case_ids'] == ['original']
    assert report['all_actual_operations']['attempted_requests'] == 4
    assert report['all_actual_operations']['total_tokens'] == 60
    assert report['all_actual_operations']['usage_reported_requests'] == 2
    for p in ('qwen', 'glm'):
        assert report['paired_scores'][p]['metrics']['scored'] == 1
        assert report['operations'][p]['specialist_failed_cases'] == 1
    rows[1].update(primary_status='transport_failed', status='primary_failure')
    write_reports(tmp_path, rows, {})
    assert json.loads((tmp_path/'comparison.json').read_text())['common_completed_case_ids'] == []
