"""Measured node footprints are evidence, not a legacy native-recovery flag."""
from __future__ import annotations

import copy
from io import BytesIO
import math

import cv2
import numpy as np
import pytest

import graph_line_tracer as tracer


def graph_for(size, positions, radii=None):
    width, height = size
    graph = {'id': 'G1', 'bbox': [0, 0, 1, 1],
             'directed': 'unknown', 'weighted': 'unknown', 'multigraph': 'unknown',
             'vertices': [{'id': name, 'label': None, 'x': x/(width-1), 'y': y/(height-1)}
                          for name, x, y in positions], 'edges': []}
    if radii is not None:
        graph['measured_marker_radii'] = dict(radii)
    return graph


def hollow_nodes(size=(700, 360), positions=(('a', 100, 180), ('b', 560, 180)),
                 radii=None, *, dashed=False):
    radii = radii or {'a': 48, 'b': 80}
    image = np.full((size[1], size[0], 3), 255, np.uint8)
    (_, ax, ay), (_, bx, by) = positions
    if dashed:
        for x in range(ax, bx, 18):
            cv2.line(image, (x, ay), (min(x+9, bx), by), (0, 0, 0), 2)
    else:
        cv2.line(image, (ax, ay), (bx, by), (0, 0, 0), 3)
    for name, x, y in positions:
        cv2.circle(image, (x, y), radii[name], (255, 255, 255), -1)
        cv2.circle(image, (x, y), radii[name], (0, 0, 0), 3)
    return image, graph_for(size, positions, radii)


def test_large_unequal_hollow_nodes_retain_the_visible_connector():
    image, graph = hollow_nodes()
    original = copy.deepcopy(graph)
    paths = tracer._graph_candidates(image, graph, dense_paths=True)
    assert any({edge['from'], edge['to']} == {'a', 'b'} for edge in paths)
    assert graph == original
    assert 'node_review' not in graph and 'node_position_evidence' not in graph


@pytest.mark.parametrize('case', ['internal_numeric_junction', 'image_clipped_ring'])
def test_pixel_measured_footprints_restore_connector_without_a_rim_self_loop(case):
    from PIL import Image
    from graph_stroke_checks import StrokeEvidence
    from image_evidence import analyze_document
    if case=='internal_numeric_junction':
        size=(260,160); positions=[('a',80,80),('b',180,80)]
        radii={'a':24,'b':24}
    else:
        size=(360,240); positions=[('a',90,120),('b',338,120)]
        radii={'a':24,'b':44}
    image=np.full((size[1],size[0],3),255,np.uint8)
    cv2.line(image,positions[0][1:],positions[1][1:],(0,0,0),2,cv2.LINE_AA)
    for name,x,y in positions:
        cv2.circle(image,(x,y),radii[name],(255,255,255),-1)
        cv2.circle(image,(x,y),radii[name],(0,0,0),2,cv2.LINE_AA)
    if case=='internal_numeric_junction':
        (width,height),_=cv2.getTextSize('4',cv2.FONT_HERSHEY_SIMPLEX,.45,2)
        cv2.putText(image,'4',(80-width//2,80+height//2),cv2.FONT_HERSHEY_SIMPLEX,
                    .45,(0,0,0),2,cv2.LINE_AA)
    graph=graph_for(size,positions)
    inspector=StrokeEvidence(analyze_document(Image.fromarray(image)))
    measured={node['id']:inspector.marker_geometry(node,graph['vertices']) for node in graph['vertices']}
    graph['measured_marker_geometry']=measured
    graph['measured_marker_radii']={name:value['radius_pixels'] for name,value in measured.items()}
    paths=tracer._graph_candidates(image,graph,dense_paths=True)
    supported=[edge for edge in paths if inspector.inspect(edge,graph)['supported']]
    assert any({edge['from'],edge['to']}=={'a','b'} for edge in supported)
    assert not any(edge['from']==edge['to'] for edge in supported)


def test_straight_sampling_ignores_white_interiors_of_large_nodes():
    image, graph = hollow_nodes()
    local = [('a', 100, 180), ('b', 560, 180)]
    paths = tracer._straight_stroke_candidates(image, local, 0, 0, 13, 700, 360,
                                               node_radii=graph['measured_marker_radii'])
    assert len(paths) == 1
    assert paths[0]['style'] == 'solid'
    assert paths[0]['score'] >= .98


def test_repeated_dash_gaps_survive_large_node_footprint_sampling():
    image, graph = hollow_nodes(size=(700, 300),
                               positions=(('a', 100, 150), ('b', 600, 150)),
                               radii={'a': 80, 'b': 25}, dashed=True)
    paths = tracer._straight_stroke_candidates(image, [('a', 100, 150), ('b', 600, 150)],
                                               0, 0, 13, 700, 300,
                                               node_radii=graph['measured_marker_radii'])
    assert len(paths) == 1
    assert paths[0]['style'] == 'dashed'


def test_hough_matches_off_centre_visible_line_to_each_actual_rim():
    image = np.full((360, 650, 3), 255, np.uint8)
    local = [('a', 100, 180), ('b', 500, 180)]
    radii = {'a': 40, 'b': 65}
    left = round(100+math.sqrt(40**2-20**2))
    right = round(500-math.sqrt(65**2-20**2))
    cv2.line(image, (left, 160), (right, 160), (0, 0, 0), 3)
    for name, x, y in local:
        cv2.circle(image, (x, y), radii[name], (0, 0, 0), 3)
    paths = tracer._hough_endpoint_candidates(image, local, 0, 0, 13, 650, 360,
                                              node_radii=radii)
    assert paths
    assert any({edge['from'], edge['to']} == {'a', 'b'}
               and all(abs(point[1]*359-160) <= 4 for point in edge['path']) for edge in paths)


def test_follow_reaches_large_target_rim_even_with_closer_small_target_centre():
    skeleton = np.zeros((120, 370), np.uint8)
    cv2.line(skeleton, (73, 50), (240, 50), 255, 1)
    points = [('source', 60, 50), ('large', 300, 50), ('near_small', 270, 70)]
    target, path, _, _ = tracer._follow(skeleton, points, 0, (73, 50), 6, 500,
                                      node_radii={'source': 10, 'large': 60, 'near_small': 3})
    assert target == 1
    assert path[-1][0] >= 236


@pytest.mark.parametrize('with_loop', [False, True])
def test_measured_node_rim_is_not_loop_but_external_closed_stroke_is(with_loop):
    image = np.full((300, 330, 3), 255, np.uint8)
    if with_loop:
        points = np.array([(130, 150), (170, 100), (225, 115), (250, 170),
                           (225, 215), (170, 220), (130, 150)], np.int32)
        cv2.polylines(image, [points], False, (0, 0, 0), 3)
    cv2.circle(image, (100, 150), 30, (255, 255, 255), -1)
    cv2.circle(image, (100, 150), 30, (0, 0, 0), 3)
    graph = graph_for((330, 300), [('a', 100, 150)], {'a': 30})
    paths = tracer._graph_candidates(image, graph, dense_paths=True)
    assert any(edge['from'] == edge['to'] == 'a' for edge in paths) == with_loop


def test_missing_or_empty_mapping_preserves_legacy_small_marker_output():
    image, graph = hollow_nodes(radii={'a': 5, 'b': 5})
    graph.pop('measured_marker_radii')
    legacy = tracer._graph_candidates(image, graph, dense_paths=True)
    assert legacy
    assert tracer._graph_candidates(image, {**graph, 'measured_marker_radii': {}},
                                    dense_paths=True) == legacy


def test_invalid_mapping_values_do_not_change_legacy_behavior():
    image, graph = hollow_nodes(radii={'a': 5, 'b': 5})
    graph.pop('measured_marker_radii')
    legacy = tracer._graph_candidates(image, graph, dense_paths=True)
    for radii in ({'a': True, 'b': False}, {'a': float('nan'), 'b': -4},
                  {'a': '40', 'b': float('inf')}, {'a': 1e10}):
        assert tracer._graph_candidates(image, {**graph, 'measured_marker_radii': radii},
                                        dense_paths=True) == legacy


def test_supplied_image_pixel_radii_scale_once_with_actual_decode(monkeypatch):
    from PIL import Image
    image, graph = hollow_nodes(size=(2001, 801),
                               positions=(('a', 300, 400), ('b', 1700, 400)),
                               radii={'a': 100, 'b': 60})
    observations = []
    original_straight = tracer._straight_stroke_candidates

    def capture(*args, **kwargs):
        observations.append(dict(kwargs['node_radii']))
        return original_straight(*args, **kwargs)

    monkeypatch.setattr(tracer, '_straight_stroke_candidates', capture)
    stream = BytesIO()
    Image.fromarray(image).save(stream, format='PNG')
    result = tracer.attach_line_evidence(stream.getvalue(), {'graphs': [graph]}, dense_paths=True)
    assert result.get('line_path_evidence')
    assert observations
    scale = min(1600/2001, 640/801)
    assert observations[0]['a'] == pytest.approx(100*scale)
    assert observations[0]['b'] == pytest.approx(60*scale)
    assert graph['measured_marker_radii'] == {'a': 100, 'b': 60}
