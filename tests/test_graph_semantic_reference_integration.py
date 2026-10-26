"""Advisory side-channel integration; synthetic providers, no live requests."""
import copy

import pytest

from graph_agent_runtime import AgentBudget
from graph_semantic_pipeline import recognize_semantic
from test_graph_semantic_pipeline import (Reader, document, original,
    install_semantic_worker_fixtures, structural_roles)
from vision_provider import VisionProvider


@pytest.fixture(autouse=True)
def isolated_workers(monkeypatch, tmp_path):
    install_semantic_worker_fixtures(monkeypatch, lock_root=tmp_path)
    monkeypatch.setattr(VisionProvider, 'available', lambda self: False)


def run(reader, **kwargs):
    return recognize_semantic(original(), provider=reader,
        budget=AgentBudget(seconds=30, calls=16), **kwargs)


def test_failed_reference_start_does_not_fail_or_remove_the_graph(monkeypatch):
    import graph_semantic_question_reference as reference
    def failed(*args, **kwargs):
        raise TimeoutError('synthetic reference startup failure')
    monkeypatch.setattr(reference, 'start_question_reference', failed)
    reader = Reader()
    result = run(reader, question_completion=object())
    assert result['complete'] is True
    assert len(result['graphs'][0]['vertices']) == 3
    assert len(result['graphs'][0]['edges']) == 3
    assert result['semantic_workflow']['question_reference']['status'] == 'unavailable'


def test_reference_is_parallel_optional_and_cannot_filter_content(monkeypatch):
    import graph_semantic_question_reference as reference
    import graph_semantic_geometry as geometry
    events, closed = [], []
    reader = Reader()
    real_geometry = geometry.prepare_semantic_geometry
    def recorded_geometry(*args, **kwargs):
        if kwargs.get('draft') is not None:
            events.append('geometry_with_nodes')
        return real_geometry(*args, **kwargs)
    def start(*args, **kwargs):
        events.append('reference_started')
        return object()
    advice = {'status': 'ready', 'advisory_only': True, 'non_authoritative': True,
        'cannot_drop_content': True,
        'focus': [{'question': '关注顶点v₅，颜色可能只是装饰，仍须核对原图'}]}
    def ready(*args, **kwargs):
        # The source reader proceeds while the reference is still pending.
        return copy.deepcopy(advice) if any(r['role'] == 'semantic_edges' for r in reader.requests) else None
    monkeypatch.setattr(geometry, 'prepare_semantic_geometry', recorded_geometry)
    monkeypatch.setattr(reference, 'start_question_reference', start)
    monkeypatch.setattr(reference, 'get_ready_question_reference', ready)
    monkeypatch.setattr(reference, 'question_reference_for_document',
        lambda value, *args, **kwargs: copy.deepcopy(value) if value.get('status') == 'ready' else None)
    monkeypatch.setattr(reference, 'close_question_reference', lambda handle: closed.append(handle))
    result = run(reader, question_completion=object())
    assert events.index('reference_started') < events.index('geometry_with_nodes')
    source = next(r for r in reader.requests if r['role'] == 'semantic_edges')
    assert 'question_reference' not in source
    review = next(r for r in reader.requests if r['role'] == 'semantic_review')
    assert review['question_reference']['advisory_only'] is True
    assert len(result['graphs'][0]['vertices']) == 3
    assert len(result['graphs'][0]['edges']) == 3
    assert result['graphs'][0]['edges'][0]['color'] == 'blue'
    assert result['complete'] is True and len(closed) == 1


@pytest.mark.parametrize('failure_boundary', ['read', 'close'])
def test_reference_read_and_cleanup_errors_never_erase_recognition(monkeypatch, failure_boundary):
    import graph_semantic_question_reference as reference
    monkeypatch.setattr(reference, 'start_question_reference', lambda *a, **kw: object())
    def failure(*args, **kwargs):
        raise RuntimeError('synthetic optional side-channel failure')
    monkeypatch.setattr(reference, 'get_ready_question_reference',
        failure if failure_boundary == 'read' else lambda *a, **kw: None)
    monkeypatch.setattr(reference, 'close_question_reference',
        failure if failure_boundary == 'close' else lambda *a, **kw: None)
    result = run(Reader(), question_completion=object())
    assert result['complete'] is True
    assert len(result['graphs']) == 1
    assert result['semantic_workflow']['question_reference']['status'] == 'unavailable'


def test_withdrawn_review_does_not_invoke_whole_graph_repair():
    reader = Reader({'semantic_review': {'issues': [
        {'verdict': 'withdrawn', 'scope': 'document', 'message': '原有差异已撤回'},
        {'verdict': 'confirmed', 'scope': 'graph', 'graph_id': 'G1',
         'field': 'edges', 'message': '已核对无误'}]}})
    result = run(reader)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review']
    assert result['complete'] is True


def test_lone_low_confidence_marker_does_not_trigger_body_reread(monkeypatch):
    import graph_semantic_text as text
    real_prepare = text.prepare_semantic_text
    def noise(*args, **kwargs):
        value = real_prepare(*args, **kwargs)
        value['text_hints'] = [{'text': 'X', 'role_hint': 'body', 'confidence': .483}]
        return value
    monkeypatch.setattr(text, 'prepare_semantic_text', noise)
    whole = document()
    whole['body_text'] = ''
    reader = Reader(source_document=whole)
    result = run(reader)
    assert not any(r['role'] in ('semantic_body', 'semantic_body_glm') for r in reader.requests)
    assert result['body_text'] == '' and result['complete'] is True
