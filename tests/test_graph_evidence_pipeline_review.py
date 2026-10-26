"""Independent mechanism review using invented pixels and fake model outputs.

These tests exercise evidence contracts, never real-image recognition accuracy.
No private corpus, annotations, image-name lookup, or remote request is used.
"""
from __future__ import annotations

import base64
import copy
from io import BytesIO
import json
import math

from PIL import Image, ImageDraw
import pytest

import graph_evidence_pipeline as pipeline
from graph_staged import Budget
from graph_stroke_checks import StrokeEvidence
from image_evidence import analyze_document


SIZE = 401

def _png(image):
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def _vertex(vid, x, y, size=(SIZE, SIZE)):
    return {'id': vid, 'label': vid, 'x': x / (size[0]-1) * 1000,
            'y': y / (size[1]-1) * 1000, 'isolated_confirmed': False}


def _graph(vertices, gid='G1', bbox=None, directed=False):
    return {'id': gid, 'name': gid, 'bbox': bbox or [0, 0, 1000, 1000],
            'directed': directed, 'weighted': False, 'multigraph': False,
            'node_complete': True, 'vertices': copy.deepcopy(vertices)}


def _inventory(graphs):
    return {'coordinate_space': 'original_1000', 'panels_complete': True,
            'body_text': '', 'body_complete': True, 'graphs': graphs}


def _edge(eid, source, target, path, size=(SIZE, SIZE), direction='undirected'):
    return {'id': eid, 'from': source, 'to': target, 'direction': direction,
            'style': 'solid', 'path': [[x/(size[0]-1)*1000, y/(size[1]-1)*1000]
                                      for x, y in path]}


def _review(graph, edges, *, verdicts=None, vertices=None, **extra):
    vertices = vertices if vertices is not None else graph['vertices']
    reads = [{'vertex': v['id'], 'complete': True,
              'edge_ids': [e['id'] for e in edges if v['id'] in (e['from'], e['to'])]}
             for v in vertices]
    return {'id': graph['id'], 'node_inventory_confirmed': True,
            'inventory_complete': True, 'edges': copy.deepcopy(edges),
            'reads': reads, 'candidate_verdicts': verdicts or [], **extra}


def _apply(image, graph, row, proposals=None):
    graphs = pipeline.decode_nodes(_inventory([graph]))
    response = {'coordinate_space': 'original_1000', 'panels_complete': True,
                'graphs': [row]}
    return pipeline.apply_topology(response, graphs, proposals or {},
                                   analyze_document(image), panels_complete=True)[0][0]


def _marks(draw, positions, radius=5, fill='black'):
    for x, y in positions:
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill)


def _straight_image(mode='RGB', width=3):
    image = Image.new(mode, (SIZE, SIZE), (0, 0, 0, 0) if mode == 'RGBA' else 'white')
    draw = ImageDraw.Draw(image)
    fill = (0, 0, 0, 255) if mode == 'RGBA' else 'black'
    draw.line((60, 200, 340, 200), fill=fill, width=width)
    _marks(draw, [(60, 200), (340, 200)], fill=fill)
    return image


class FakeQwen:
    name = 'qwen'
    model = 'qwen3-vl-plus'
    retries = 0

    def __init__(self, first, second):
        self.responses = [first, second]
        self.calls = []

    def available(self):
        return True

    def __call__(self, prompt, images, budget):
        budget.take()
        self.calls.append({'prompt': prompt, 'images': images})
        answer = self.responses[len(self.calls)-1]
        if isinstance(answer, Exception):
            raise answer
        return copy.deepcopy(answer)


@pytest.mark.parametrize('panel_count', [10, 12])
def test_every_panel_enters_second_request_and_shares_only_two_calls(monkeypatch, panel_count):
    size = (1001, math.ceil(panel_count/5)*250+1)
    image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    graphs, rows = [], []
    for i in range(panel_count):
        col, row = i % 5, i // 5
        x1, x2, y = 30+col*200, 170+col*200, 100+row*250
        draw.line((x1, y, x2, y), fill='black', width=3)
        _marks(draw, [(x1, y), (x2, y)])
        graph = _graph([_vertex('a', x1, y, size), _vertex('b', x2, y, size)],
                       gid=f'G{i+1}', bbox=[col*200+5, (row*250+30)/(size[1]-1)*1000,
                                            col*200+195, (row*250+180)/(size[1]-1)*1000])
        edge = _edge('new_ab', 'a', 'b', [(x1, y), (x2, y)], size=size)
        graphs.append(graph)
        rows.append(_review(graph, [edge]))
    fake = FakeQwen(_inventory(graphs), {'coordinate_space': 'original_1000',
                    'panels_complete': True, 'graphs': rows})
    monkeypatch.setattr(pipeline, 'collect_candidates', lambda doc, gs: ({g['id']: [] for g in gs}, []))
    budget = Budget(calls=20, seconds=500, call_seconds=200)
    result = pipeline.recognize_evidence(_png(image), provider=fake, budget=budget)
    assert len(fake.calls) == 2
    assert budget.remaining == 0
    request = json.loads(fake.calls[1]['prompt'].splitlines()[-1])
    assert {g['id'] for g in request['graphs']} == {g['id'] for g in graphs}
    assert {t['graph_id'] for t in request['review_tiles']} == {g['id'] for g in graphs}
    assert len(result['graphs']) == panel_count
    assert all(g['complete'] for g in result['graphs'])


def test_absent_panel_review_never_inherits_complete_state():
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    _marks(draw, [(80, 100), (320, 300)])
    g1 = _graph([_vertex('a', 80, 100)], bbox=[0, 0, 400, 450])
    g2 = _graph([_vertex('a', 320, 300)], gid='G2', bbox=[600, 550, 1000, 1000])
    graphs = pipeline.decode_nodes(_inventory([g1, g2]))
    response = {'coordinate_space': 'original_1000', 'panels_complete': True,
                'graphs': [_review(g1, [])]}
    output, diagnostics = pipeline.apply_topology(response, graphs, {}, analyze_document(image),
                                                   panels_complete=True)
    assert output[0]['complete']
    assert not output[1]['complete']
    assert 'whole_panel_review_missing' in output[1]['uncertain_edges']
    assert any('G2' in item for item in diagnostics)


def test_failed_second_call_has_no_retry_or_third_call(monkeypatch):
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    fake = FakeQwen(_inventory([graph]), TimeoutError('intentional_test_failure'))
    monkeypatch.setattr(pipeline, 'collect_candidates', lambda doc, gs: ({'G1': []}, []))
    budget = Budget(calls=30)
    with pytest.raises(TimeoutError, match='intentional_test_failure'):
        pipeline.recognize_evidence(_png(_straight_image()), provider=fake, budget=budget)
    assert len(fake.calls) == 2
    assert budget.remaining == 0


def test_new_vertex_and_position_correction_replace_old_crossing_candidate():
    image = _straight_image()
    _marks(ImageDraw.Draw(image), [(200, 200)])
    a, b, c = _vertex('a', 56, 200), _vertex('b', 340, 200), _vertex('c', 200, 200)
    graph = _graph([a, b])
    candidate = {'id': 'px_1', 'from': 'a', 'to': 'b',
                 'path': [[.14, .5], [.85, .5]], 'pixel_evidence': {'supported': False}}
    edges = [_edge('new_ac', 'a', 'c', [(60, 200), (200, 200)]),
             _edge('new_cb', 'c', 'b', [(200, 200), (340, 200)])]
    row = _review(graph, edges, vertices=[a, b, c], verdicts=[['px_1', False]],
                  node_updates=[_vertex('a', 60, 200)], new_vertices=[c])
    actual = _apply(image, graph, row, {'G1': [candidate]})
    assert actual['complete']
    assert {v['id'] for v in actual['vertices']} == {'a', 'b', 'c'}
    assert next(v for v in actual['vertices'] if v['id'] == 'a')['x'] == .15
    assert {(e['from'], e['to']) for e in actual['edges']} == {('a', 'c'), ('c', 'b')}


def test_existing_candidate_cannot_silently_change_to_new_endpoint():
    image = _straight_image()
    _marks(ImageDraw.Draw(image), [(200, 200)])
    a, b, c = _vertex('a', 60, 200), _vertex('b', 340, 200), _vertex('c', 200, 200)
    graph = _graph([a, b])
    candidate = {'id': 'px_1', 'from': 'a', 'to': 'b'}
    edges = [_edge('px_1', 'a', 'c', [(60, 200), (200, 200)])]
    row = _review(graph, edges, vertices=[a, b, c], verdicts=[['px_1', True]], new_vertices=[c])
    actual = _apply(image, graph, row, {'G1': [candidate]})
    assert not actual['complete']
    assert any('changed_candidate_endpoint_identity' in s for s in actual['uncertain_edges'])


def test_directed_candidate_can_reverse_tail_and_head_without_reassigning_identity():
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)], directed=True)
    candidate = {'id': 'px_1', 'from': 'a', 'to': 'b'}
    edge = _edge('px_1', 'b', 'a', [(340, 200), (60, 200)], direction='forward')
    row = _review(graph, [edge], verdicts=[['px_1', True]])
    actual = _apply(_straight_image(), graph, row, {'G1': [candidate]})
    assert actual['complete']
    assert (actual['edges'][0]['from'], actual['edges'][0]['to']) == ('b', 'a')


def test_alpha_white_background_reaches_both_model_calls(monkeypatch):
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    row = _review(graph, [_edge('new_ab', 'a', 'b', [(60, 200), (340, 200)])])
    fake = FakeQwen(_inventory([graph]), {'coordinate_space': 'original_1000',
                    'panels_complete': True, 'graphs': [row]})
    monkeypatch.setattr(pipeline, 'collect_candidates', lambda doc, gs: ({'G1': []}, []))
    result = pipeline.recognize_evidence(_png(_straight_image('RGBA')), provider=fake)
    assert result['graphs'][0]['complete']
    for call in fake.calls:
        original = Image.open(BytesIO(base64.b64decode(call['images'][0].split(',', 1)[1])))
        assert original.mode == 'RGB'
        assert original.getpixel((0, 0)) == (255, 255, 255)
        assert original.getpixel((200, 200)) == (0, 0, 0)


def test_independent_parallel_curves_are_preserved():
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    paths = [[(60, 200), (120, 140), (280, 140), (340, 200)],
             [(60, 200), (120, 260), (280, 260), (340, 200)]]
    for path in paths:
        draw.line(path, fill='black', width=3)
    _marks(draw, [(60, 200), (340, 200)])
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    edges = [_edge(f'new_{i}', 'a', 'b', path) for i, path in enumerate(paths)]
    actual = _apply(image, graph, _review(graph, edges))
    assert actual['complete']
    assert actual['multigraph']
    assert len(actual['edges']) == 2
    assert all(e['status'] == 'accepted' for e in actual['edges'])


def test_same_route_forward_and_backward_is_not_two_edges():
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    edges = [_edge('new_1', 'a', 'b', [(60, 200), (340, 200)]),
             _edge('new_2', 'b', 'a', [(340, 200), (60, 200)])]
    actual = _apply(_straight_image(), graph, _review(graph, edges))
    assert not actual['complete']
    assert any('duplicate_ink' in s for s in actual['uncertain_edges'])


def test_closed_self_loop_with_independent_return_stroke_is_supported():
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    path = [(200, 260), (130, 200), (150, 100), (250, 100), (270, 200), (200, 260)]
    draw.line(path, fill='black', width=3)
    _marks(draw, [(200, 260)])
    graph = _graph([_vertex('a', 200, 260)])
    edge = _edge('new_loop', 'a', 'a', path)
    actual = _apply(image, graph, _review(graph, [edge]))
    assert actual['complete']
    assert actual['edges'][0]['status'] == 'accepted'


def test_single_straight_stroke_out_and_back_is_not_a_self_loop():
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((60, 200, 340, 200), fill='black', width=3)
    _marks(draw, [(60, 200)])
    graph = _graph([_vertex('a', 60, 200)])
    edge = _edge('new_loop', 'a', 'a', [(60, 200), (340, 200), (60, 200)])
    actual = _apply(image, graph, _review(graph, [edge]))
    assert not actual['complete'], 'Out-and-back on one stroke cannot establish an independent loop.'
    assert actual['edges'][0]['status'] == 'pending'


def test_turning_at_unmarked_x_crossing_does_not_prove_wrong_endpoint_pair():
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((60, 60, 340, 340), fill='black', width=3)
    draw.line((60, 340, 340, 60), fill='black', width=3)
    positions = [('a', 60, 60), ('b', 60, 340), ('c', 340, 340), ('d', 340, 60)]
    _marks(draw, [(x, y) for _, x, y in positions])
    graph = _graph([_vertex(vid, x, y) for vid, x, y in positions])
    wrong = [_edge('new_ad', 'a', 'd', [(60, 60), (200, 200), (340, 60)]),
             _edge('new_bc', 'b', 'c', [(60, 340), (200, 200), (340, 340)])]
    actual = _apply(image, graph, _review(graph, wrong))
    assert not actual['complete'], 'Ink support alone cannot license switching strokes at an unmarked X.'


def test_two_routes_inside_one_thick_stroke_do_not_create_parallel_edges():
    image = _straight_image(width=9)
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    edges = [_edge('new_top', 'a', 'b', [(60, 200), (80, 197), (320, 197), (340, 200)]),
             _edge('new_bottom', 'a', 'b', [(60, 200), (80, 203), (320, 203), (340, 200)])]
    actual = _apply(image, graph, _review(graph, edges))
    assert not actual['complete'], 'Both sampled routes lie inside one 9px physical stroke.'
    assert any('duplicate_ink' in s for s in actual['uncertain_edges'])


def test_unmarked_x_crossing_preserves_straight_through_edges():
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    positions = [('a', 60, 60), ('b', 60, 340), ('c', 340, 340), ('d', 340, 60)]
    draw.line((60, 60, 340, 340), fill='black', width=3)
    draw.line((60, 340, 340, 60), fill='black', width=3)
    _marks(draw, [(x, y) for _, x, y in positions])
    graph = _graph([_vertex(vid, x, y) for vid, x, y in positions])
    edges = [_edge('new_ac', 'a', 'c', [(60, 60), (200, 200), (340, 340)]),
             _edge('new_bd', 'b', 'd', [(60, 340), (200, 200), (340, 60)])]
    actual = _apply(image, graph, _review(graph, edges))
    assert actual['complete']
    assert len(actual['edges']) == 2


@pytest.mark.parametrize('separation', [2, 4, 8])
def test_close_parallel_strokes_with_real_white_gap_remain_distinct(separation):
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    paths = [[(60, 200), (80, 200-separation/2), (320, 200-separation/2), (340, 200)],
             [(60, 200), (80, 200+separation/2), (320, 200+separation/2), (340, 200)]]
    for path in paths:
        draw.line(path, fill='black', width=1)
    _marks(draw, [(60, 200), (340, 200)])
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    edges = [_edge(f'new_{i}', 'a', 'b', path) for i, path in enumerate(paths)]
    actual = _apply(image, graph, _review(graph, edges))
    assert actual['complete'], actual['uncertain_edges']
    assert len(actual['edges']) == 2
    assert actual['multigraph']


def test_smooth_bent_curve_and_true_elbow_are_not_crossing_switches():
    image = Image.new('RGB', (SIZE, SIZE), 'white')
    draw = ImageDraw.Draw(image)
    curve = [(60+280*i/15, 140-60*math.sin(math.pi*i/15)) for i in range(16)]
    elbow = [(60, 260), (200, 260), (200, 320), (340, 320)]
    for path in (curve, elbow):
        draw.line(path, fill='black', width=3)
    positions = [('a', 60, 140), ('b', 340, 140), ('c', 60, 260), ('d', 340, 320)]
    _marks(draw, [(x, y) for _, x, y in positions])
    graph = _graph([_vertex(vid, x, y) for vid, x, y in positions])
    edges = [_edge('new_curve', 'a', 'b', curve), _edge('new_elbow', 'c', 'd', elbow)]
    actual = _apply(image, graph, _review(graph, edges))
    assert actual['complete'], actual['uncertain_edges']


@pytest.mark.parametrize('other_offset', [1, -1])
def test_approximate_paths_cannot_duplicate_the_same_one_pixel_stroke(other_offset):
    image = _straight_image(width=1)
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    path = [(60, 200), (80, 201), (320, 201), (340, 200)]
    other = [(60, 200), (80, 200+other_offset), (320, 200+other_offset), (340, 200)]
    edges = [_edge('new_1', 'a', 'b', path), _edge('new_2', 'a', 'b', other)]
    actual = _apply(image, graph, _review(graph, edges))
    assert not actual['complete'], 'Both accepted approximate paths refer to the same nearby thin stroke.'
    assert any('duplicate_ink' in s for s in actual['uncertain_edges'])


def test_explicitly_rejected_candidate_cannot_supply_pixels_to_another_edge_identity():
    image = _straight_image()
    graph = _graph([_vertex('a', 60, 200), _vertex('b', 340, 200)])
    route = [[.15, .5], [.85, .5]]
    document = analyze_document(image)
    canonical = pipeline.decode_nodes(_inventory([graph]))[0]
    candidate = {'id': 'px_1', 'from': 'a', 'to': 'b', 'path': route, 'style': 'solid'}
    candidate['pixel_evidence'] = StrokeEvidence(document).inspect(candidate, canonical)
    assert candidate['pixel_evidence']['supported']
    fabricated = _edge('new_elsewhere', 'a', 'b', [(60, 200), (80, 207), (320, 207), (340, 200)])
    row = _review(graph, [fabricated], verdicts=[['px_1', False]])
    actual = _apply(image, graph, row, {'G1': [candidate]})
    assert not actual['complete'], 'A negative visual verdict must not be silently undone by measured binding.'
