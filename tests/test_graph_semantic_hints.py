"""Model-input hygiene without changing OCR evidence or acceptance outcomes."""
from copy import deepcopy

import pytest

from graph_semantic_hints import project_ocr_hints


def hint(text, *, hid='h1', box=(100, 100, 200, 130), role='body', **extra):
    return {'id': hid, 'text': text, 'bbox': list(box) if box else None,
            'coordinate_space': 'original_1000', 'role_hint': role, **extra}


def project(rows, role='semantic_review', **kwargs):
    return project_ocr_hints({'text_hints': rows}, role=role, **kwargs)


@pytest.mark.parametrize('role', ['semantic_review', 'semantic_repair', 'semantic_verify', 'semantic_body'])
def test_review_cannot_turn_mispartitioned_node_ocr_into_body_or_topology(role):
    rows = [hint(text, hid=str(i), box=(i*100, 300, i*100+30, 330),
                 role='body', confidence=.999)
            for i, text in enumerate(['a', 'V7', '√2', 'es', 'O'])]
    result = project(rows, role)
    assert result['candidates'] == []
    assert result['body_text_hint'] == ''
    assert result['policy']['graph_label_ocr_excluded']


def test_question_and_semantically_relevant_legend_remain_located_suggestions():
    rows = [hint('判断图是否有欧拉回路。'),
            hint('虚线表示非树边。', hid='legend', box=(100, 400, 500, 440)),
            hint('Find the shortest path.', hid='english', box=(100, 600, 500, 640)),
            hint('v7', hid='label', box=(600, 700, 640, 740), role='graph_label')]
    result = project(rows)
    assert [x['id'] for x in result['candidates']] == ['h1', 'legend', 'english']
    assert all(x['authoritative'] is False for x in result['candidates'])
    assert 'v7' not in result['body_text_hint']


@pytest.mark.parametrize('text', ['设G=(V,E)', 'Let G=(V,E).'])
def test_short_mathematical_setup_is_still_a_body_reading_candidate(text):
    assert project([hint(text)])['candidates'][0]['text'] == text


def test_unlocated_prose_cannot_be_presented_as_a_located_body_region():
    row = hint('求该图的最小生成树。', box=None)
    assert project([row])['candidates'] == []
    assert project([row], 'inventory')['candidates'][0]['text'] == row['text']


def test_scalar_formula_in_a_located_question_run_is_retained_without_graph_labels():
    rows = [hint('已知条件如下：', box=(100, 100, 300, 125)),
            hint('x=2', hid='formula', box=(110, 140, 160, 165)),
            hint('e2', hid='label', box=(120, 140, 150, 165), role='graph_label'),
            hint('V8', hid='far', box=(600, 700, 650, 730))]
    result = project(rows, body_regions=[{'bbox': [90, 90, 320, 180]}])
    assert [row['id'] for row in result['candidates']] == ['h1', 'formula']


def test_whole_page_layout_does_not_promote_distant_short_labels_to_body():
    rows = [hint('求下图的距离。'), hint('q', hid='label', box=(600, 700, 630, 730))]
    result = project(rows, body_regions=[{'bbox': [0, 0, 1000, 1000]}])
    assert [row['id'] for row in result['candidates']] == ['h1']


def test_overlapping_duplicate_is_one_hint_not_an_extra_vote():
    rows = [hint('q2', role='graph_label'),
            hint('q2', hid='enhanced', box=(102, 101, 202, 131), role='graph_label'),
            hint('q2', hid='another_panel', box=(700, 700, 800, 730), role='graph_label')]
    result = project(rows, 'semantic_extract')
    assert [row['id'] for row in result['candidates']] == ['h1', 'another_panel']
    assert result['audit']['overlapping_duplicates'] == [{'kept_id': 'h1', 'omitted_id': 'enhanced'}]
    assert 'overlapping_duplicates' not in result['policy']


def test_conflicting_readings_are_not_case_folded_or_selected_as_truth():
    rows = [hint('q2', role='graph_label'), hint('Q2', hid='other', role='graph_label')]
    assert [x['text'] for x in project(rows, 'semantic_edges')['candidates']] == ['q2', 'Q2']


def test_inventory_does_not_republish_a_wrong_paddle_body_partition():
    candidate = project([hint('q4', role='body')], 'semantic_extract')['candidates'][0]
    assert candidate['role_hint'] == 'graph_text_candidate'
    assert candidate['usage'] == 'graph_text_reading_candidate'


def test_round_ocr_over_marker_is_not_a_printed_label_hint_but_adjacent_zero_survives():
    rows = [hint('O', box=(100, 100, 120, 120)),
            hint('0', hid='weight', box=(150, 100, 170, 120)),
            hint('O', hid='letter', box=(200, 100, 220, 120), role='graph_label')]
    marker = {'position': [110, 110], 'radius_x': 8, 'radius_y': 8, 'confidence': .95}
    result = project(rows, 'inventory', marker_candidates=[marker])
    assert [x['id'] for x in result['candidates']] == ['weight', 'letter']
    assert result['audit']['omitted_counts']['point_or_round_marker_candidate'] == 1


def test_marker_near_a_label_does_not_remove_the_label():
    marker = {'position': [90, 110], 'radius_x': 8, 'radius_y': 8, 'confidence': .95}
    row = hint('O', box=(100, 100, 120, 120))
    assert project([row], 'inventory', marker_candidates=[marker])['candidates']


@pytest.mark.parametrize('text', ['0', 'O', 'o'])
@pytest.mark.parametrize('role', ['semantic_extract', 'semantic_edges'])
def test_small_real_glyph_inside_a_hollow_node_survives_as_a_text_candidate(text, role):
    row = hint(text, box=(100, 100, 112, 116), role='graph_label')
    original = deepcopy(row)
    marker = {'position': [106, 108], 'radius_x': 25, 'radius_y': 25,
              'confidence': .95, 'kind': 'hollow'}
    result = project([row], role, marker_candidates=[marker])
    assert [candidate['text'] for candidate in result['candidates']] == [text]
    assert 'point_or_round_marker_candidate' not in result['audit']['omitted_counts']
    assert row == original


def test_a_narrow_character_is_not_removed_by_a_large_marker_on_only_one_axis():
    # The OCR box may span much of the circle's height while remaining a
    # character inside it, rather than a transcription of the whole outline.
    row = hint('0', box=(100, 90, 112, 126), role='graph_label')
    marker = {'position': [106, 108], 'radius_x': 25, 'radius_y': 18,
              'confidence': .99, 'kind': 'hollow'}
    assert project([row], 'inventory', marker_candidates=[marker])['candidates']


def test_raw_string_and_noise_partitions_cannot_be_flattened_back_into_body():
    result = project_ocr_hints({'text': '√9\nO\nq4',
                               'text_evidence': {'body': [{'content': '√9'}]},
                               'text_hints': []}, role='semantic_extract')
    assert result['body_text_hint'] == ''


def test_graph_window_only_filters_located_outside_candidates():
    rows = [hint('q1'), hint('q2', hid='out', box=(600, 600, 700, 630))]
    result = project(rows, 'semantic_edges', graph={'bbox': [0, 0, 400, 400]})
    assert [x['id'] for x in result['candidates']] == ['h1']


def test_projection_never_mutates_or_promotes_raw_ocr_evidence():
    raw = {'text': 'raw labels', 'text_hints': [hint('a', role='graph_label',
            authoritative=True, confidence=.999, verdict='this is certain')],
           'diagnostics': {'actual_inference_completed': True}}
    before = deepcopy(raw)
    result = project_ocr_hints(raw, role='inventory')
    assert raw == before
    assert result['candidates'][0]['authoritative'] is False
    assert 'verdict' not in result['candidates'][0]
    assert 'confidence' not in result['candidates'][0]
    assert result['audit']['raw_ocr_unchanged']


def test_capacity_keeps_whole_candidates_and_does_not_terminate_on_a_large_one():
    rows = [hint('abcdefghij'), hint('a', hid='short')]
    result = project(rows, 'inventory', max_characters=3)
    assert [x['text'] for x in result['candidates']] == ['a']
    assert result['audit']['omitted_counts']['capacity'] == 1


@pytest.mark.parametrize('limits', [{'max_items': -1}, {'max_items': True}, {'max_characters': 25_000}])
def test_invalid_capacity_is_explicit(limits):
    with pytest.raises(ValueError, match='capacity'):
        project([], **limits)
def test_rejected_arrow_wings_do_not_become_visual_direction_suggestions():
    from copy import deepcopy
    from graph_semantic_hints import project_connection_hints
    geometry = [{'graph_id': 'g', 'candidates': [
        {'from': 'left', 'to': 'right', 'path_hint': [[10, 30], [90, 30]],
         'arrow_measurement': {'confirmed': False, 'score': .5, 'from': 'left', 'to': 'right'}},
        {'from': 'upper', 'to': 'lower', 'arrow_measurement': {
            'confirmed': True, 'score': .95, 'from': 'lower', 'to': 'upper'}}]}]
    original = deepcopy(geometry)
    projected = project_connection_hints(geometry)
    assert 'arrow_measurement' not in projected[0]['candidates'][0]
    assert projected[0]['candidates'][0]['path_hint'] == [[10, 30], [90, 30]]
    assert projected[0]['candidates'][1]['arrow_measurement']['from'] == 'lower'
    assert geometry == original


def test_inventory_location_cannot_leak_an_untested_connection_claim():
    from graph_semantic_hints import spatial_position_hint
    assert spatial_position_hint('左侧中间，连接上方和右侧') == '左侧中间'
    assert spatial_position_hint('upper left, connected to three nodes') == 'upper left'
    assert spatial_position_hint('外环右下角') == '外环右下角'
    assert spatial_position_hint([140, 310]) == [140, 310]
