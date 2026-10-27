"""Unordered local route groups select original pixels, never directions."""
import base64
import copy
import hashlib
import io
import json
import math
import time

import pytest
from PIL import Image, ImageDraw

import graph_semantic_arrow_views as arrow
from dmate_tool_registry import ToolContext
from graph_agent_runtime import AgentCancelled


class Budget:
    def __init__(self, raw=None):
        self.deadline = time.monotonic() + 60
        self.source_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
        self.error = None

    def check(self):
        if self.error:
            raise self.error
        if time.monotonic() >= self.deadline:
            raise TimeoutError('task_deadline')


def png(image):
    stream = io.BytesIO(); image.save(stream, 'PNG'); return stream.getvalue()


def decode(value):
    return Image.open(io.BytesIO(base64.b64decode(value.split(',', 1)[1]))).convert('RGB')


def group(gid='G1', left=(300, 400), right=(700, 400), bend=90):
    graph = {'id': gid, 'vertices': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'b'}],
             'edges': [{'id': 'edge1', 'from': 'a', 'to': 'b', 'direction': 'forward'},
                       {'id': 'edge2', 'from': 'b', 'to': 'a', 'direction': 'forward'}]}
    endpoints = [{'vertex_id': v, 'marker_id': 'marker_'+v, 'position': list(p),
                  'association': 'unique_close_marker'} for v, p in [('a', left), ('b', right)]]
    rows = []
    for index, offset in enumerate((-bend, bend), 1):
        rows.append({'instance_id': gid+':route'+str(index), 'from': 'a', 'to': 'b',
                     'source': 'opencv', 'coordinate_space': 'original_1000', 'unmapped': False,
                     'endpoints': copy.deepcopy(endpoints), 'proposal_only': True,
                     'path_hint': [list(left), [(left[0]+right[0])/2, (left[1]+right[1])/2+offset], list(right)]})
    return graph, {'graph_id': gid, 'candidates': rows}


def fixture(groups=None, size=(800, 600)):
    groups = groups or [group()]
    image = Image.new('RGB', size, (240, 250, 245))
    draw = ImageDraw.Draw(image)
    for index, (_, local) in enumerate(groups):
        for route in local['candidates']:
            points = [(round(x*(size[0]-1)/1000), round(y*(size[1]-1)/1000))
                      for x, y in route['path_hint']]
            draw.line(points, fill=(20+index*20, 30, 180), width=3)
            draw.text((points[1][0]+3, points[1][1]-15), 'edge label', fill=(180, 15, 10))
    raw = png(image)
    draft = {'body_text': 'unchanged', 'graphs': [g for g, _ in groups]}
    geometry = {'source_sha256': hashlib.sha256(raw).hexdigest(), 'graphs': [g for _, g in groups]}
    overview = arrow.prepare_arrow_views(raw, budget=Budget(raw))
    return image, raw, draft, geometry, overview


def prepare(raw, draft, geometry, overview, budget=None):
    return arrow.prepare_direction_views(raw, draft=draft, geometry=geometry,
                                         overview_views=overview, budget=budget or Budget(raw))


def test_pair_unions_every_route_and_preserves_exact_original_pixels_and_inputs():
    image, raw, draft, geometry, overview = fixture()
    before = json.dumps([draft, geometry, overview], sort_keys=True)
    result = prepare(raw, draft, geometry, overview)
    assert result['images'][0] == overview['images'][0] and len(result['images']) == 5
    assert result['image_quality']['direction_pair_status'] == 'cropped'
    metadata = result['view_metadata'][1]
    assert metadata['view_kind'] == 'endpoint_pair' and metadata['graph_id'] == 'G1'
    assert metadata['vertex_ids'] == ['a', 'b'] and metadata['candidate_count'] == 2
    assert metadata['edge_ids'] == ['edge1', 'edge2']
    assert metadata['directions_used'] is False and metadata['route_coverage_certified'] is False
    box = metadata['source_box']; crop = image.crop(box); output = decode(result['images'][1])
    assert metadata['source_pixel_sha256'] == hashlib.sha256(crop.tobytes()).hexdigest()
    assert output.tobytes() == crop.resize(output.size, Image.Resampling.NEAREST).tobytes()
    assert metadata['resampling'] == 'nearest'
    assert output.width <= crop.width*6 and output.height <= crop.height*6
    assert max(output.size) <= arrow.CROP_SIDE
    for route in geometry['graphs'][0]['candidates']:
        for x, y in route['path_hint']:
            px, py = x*(image.width-1)/1000, y*(image.height-1)/1000
            assert box[0] <= px-24 and box[2] >= px+24
            assert box[1] <= py-24 and box[3] >= py+24
    assert metadata['original_bbox'] == [round(box[i]*1000/image.size[i % 2], 6) for i in range(4)]
    assert [m['image_number'] for m in result['view_metadata']] == [1, 2, 3, 4, 5]
    assert result['image_quality']['output_pixels'] == sum(math.prod(m['output_size']) for m in result['view_metadata'])
    audit = result['tool_audit'][-1]
    assert audit['tool'] == 'image.direction_pair_views' and audit['status'] == 'success'
    assert audit['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert 'data:image' not in json.dumps(result['tool_audit'])
    assert json.dumps([draft, geometry, overview], sort_keys=True) == before


def test_direction_endpoint_order_path_order_and_arrow_hints_cannot_change_crop():
    _, raw, draft, geometry, overview = fixture()
    expected = prepare(raw, draft, geometry, overview)
    for edge in draft['graphs'][0]['edges']:
        edge['from'], edge['to'] = edge['to'], edge['from']
        edge.update(direction='undirected', edge_label='DO NOT DRAW THIS', weight='999')
    for row in geometry['graphs'][0]['candidates']:
        row['from'], row['to'] = row['to'], row['from']
        row['path_hint'].reverse(); row['endpoints'].reverse()
        row['arrow_measurement'] = {'from': 'b', 'to': 'a', 'score': 1, 'confirmed': True}
    actual = prepare(raw, draft, geometry, overview)
    assert actual['images'] == expected['images']
    assert actual['view_metadata'] == expected['view_metadata']
    assert 'DO NOT DRAW THIS' not in json.dumps(actual['view_metadata'])


def test_same_direction_parallel_edges_get_same_union_as_opposite_arcs():
    _, raw, draft, geometry, overview = fixture()
    before = prepare(raw, draft, geometry, overview)
    draft['graphs'][0]['edges'][1].update(**{'from': 'a', 'to': 'b'})
    after = prepare(raw, draft, geometry, overview)
    assert after['images'] == before['images']


def test_two_panels_with_same_vertex_ids_never_share_paths_or_positions():
    groups = [group('left', (100, 200), (300, 200), 45),
              group('right', (700, 750), (900, 750), 45)]
    image, raw, draft, geometry, overview = fixture(groups, size=(1000, 800))
    result = prepare(raw, draft, geometry, overview)
    metadata = [m for m in result['view_metadata'] if m.get('view_kind') == 'endpoint_pair']
    assert [m['graph_id'] for m in metadata] == ['left', 'right']
    assert metadata[0]['source_box'][2] < image.width/2
    assert metadata[1]['source_box'][0] > image.width/2
    assert metadata[0]['candidate_ids'] == ['left:route1', 'left:route2']
    assert metadata[1]['candidate_ids'] == ['right:route1', 'right:route2']


@pytest.mark.parametrize('problem', ['absent', 'wrong_source', 'no_routes', 'unmapped', 'ambiguous_position',
    'different_marker', 'invalid_path', 'wrong_path_endpoint', 'duplicate_graph', 'duplicate_vertex',
    'duplicate_candidate', 'shared_marker', 'coordinate_space', 'one_semantic_edge'])
def test_missing_untrusted_or_ambiguous_pair_geometry_retains_every_original_view(problem):
    _, raw, draft, geometry, overview = fixture()
    row = geometry['graphs'][0]['candidates'][0]
    if problem == 'absent': geometry = None
    elif problem == 'wrong_source': geometry['source_sha256'] = '0'*64
    elif problem == 'no_routes': geometry['graphs'][0]['candidates'] = []
    elif problem == 'unmapped': row['endpoints'][0]['association'] = 'unmapped'
    elif problem == 'ambiguous_position': row['endpoints'][0]['position'][0] += 20
    elif problem == 'different_marker': row['endpoints'][0]['marker_id'] = 'different_marker'
    elif problem == 'invalid_path': row['path_hint'][1] = [float('nan'), 10]
    elif problem == 'wrong_path_endpoint': row['path_hint'][0] = [20, 20]
    elif problem == 'duplicate_graph': geometry['graphs'].append(copy.deepcopy(geometry['graphs'][0]))
    elif problem == 'duplicate_vertex': draft['graphs'][0]['vertices'].append(copy.deepcopy(draft['graphs'][0]['vertices'][0]))
    elif problem == 'duplicate_candidate': geometry['graphs'][0]['candidates'][1]['instance_id'] = row['instance_id']
    elif problem == 'shared_marker': row['endpoints'][1]['marker_id'] = row['endpoints'][0]['marker_id']
    elif problem == 'coordinate_space': row['coordinate_space'] = 'work_pixels'
    elif problem == 'one_semantic_edge': draft['graphs'][0]['edges'].pop()
    result = prepare(raw, draft, geometry, overview)
    assert result['images'] == overview['images'] and len(result['images']) == 5
    assert result['view_metadata'] == overview['view_metadata']
    assert result['image_quality']['direction_pair_status'] == 'fallback_overviews'
    assert result['image_quality']['direction_pair_reason']
    assert result['tool_audit'][-1]['tool'] == 'image.direction_pair_views'


def test_three_pair_cap_is_visible_and_preserves_full_overview_and_pixel_limit():
    groups = [group('G'+str(i), (150, 100+i*200), (850, 100+i*200), 30) for i in range(4)]
    _, raw, draft, geometry, overview = fixture(groups, size=(1000, 1000))
    result = prepare(raw, draft, geometry, overview)
    assert len(result['images']) == 5 and result['images'][0] == overview['images'][0]
    assert result['image_quality']['direction_pair_crops'] == 3
    assert result['image_quality']['direction_pair_groups'] == 4
    assert result['image_quality']['direction_pair_omitted_count'] == 1
    assert result['image_quality']['direction_pair_omissions'] == [
        {'graph_id': 'G3', 'vertex_ids': ['a', 'b'], 'reason': 'pair_crop_capacity'}]
    assert result['image_quality']['output_pixels'] <= arrow.MAX_TOTAL_PIXELS


def test_geometry_capacity_is_not_silently_truncated_to_a_selected_arc():
    _, raw, draft, geometry, overview = fixture()
    row = geometry['graphs'][0]['candidates'][0]
    geometry['graphs'][0]['candidates'] = [copy.deepcopy(row) for _ in range(arrow.MAX_PAIR_CANDIDATES+1)]
    result = prepare(raw, draft, geometry, overview)
    assert result['images'] == overview['images']
    assert result['image_quality']['direction_pair_reason'] == 'geometry_candidate_capacity'


def test_wrong_overview_source_is_rebuilt_from_actual_raw_not_reused():
    image, raw, draft, geometry, _ = fixture()
    foreign = arrow.prepare_arrow_views(png(Image.new('RGB', image.size, 'red')), budget=Budget())
    result = prepare(raw, draft, geometry, foreign)
    assert decode(result['images'][0]).tobytes() == image.tobytes()
    assert len(result['images']) == 5
    assert result['image_quality']['direction_pair_reason'] == 'overview_source_mismatch'


def test_local_crop_failure_keeps_all_views_but_cancellation_propagates(monkeypatch):
    _, raw, draft, geometry, overview = fixture()
    original_encode = arrow._encode
    monkeypatch.setattr(arrow, '_encode', lambda image: (_ for _ in ()).throw(RuntimeError('private contents')))
    result = prepare(raw, draft, geometry, overview)
    assert result['images'] == overview['images'] and result['tool_audit'][-1]['status'] == 'failed'
    assert 'private contents' not in json.dumps(result)
    budget = Budget(raw); error = AgentCancelled('upload_cancelled')
    def cancel(image):
        value = original_encode(image); budget.error = error; return value
    monkeypatch.setattr(arrow, '_encode', cancel)
    with pytest.raises(AgentCancelled) as caught:
        prepare(raw, draft, geometry, overview, budget)
    assert caught.value is error


def test_deadline_and_cancel_before_selection_do_not_return_successful_fallback(monkeypatch):
    _, raw, draft, geometry, overview = fixture()
    budget = Budget(raw); budget.error = AgentCancelled('upload_cancelled')
    with pytest.raises(AgentCancelled): prepare(raw, draft, geometry, overview, budget)
    budget.error = None
    original_resize = arrow._resize
    def expire(*args, **kwargs):
        result = original_resize(*args, **kwargs); budget.deadline = time.monotonic()-1; return result
    monkeypatch.setattr(arrow, '_resize', expire)
    with pytest.raises(TimeoutError, match='task_deadline'):
        prepare(raw, draft, geometry, overview, budget)


def test_registered_pair_tool_does_not_accept_model_crop_or_unrelated_role():
    registry = arrow._build_direction_registry()
    context = ToolContext(source_sha256='a'*64)
    assert registry.call('image.direction_pair_views', {'bbox': [0, 0, 1000, 1000]},
                         role='semantic_review', context=context)['error']['code'] == 'invalid_arguments'
    assert registry.call('image.direction_pair_views', {}, role='connections', context=context)['status'] == 'denied'
