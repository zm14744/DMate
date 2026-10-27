import copy

from test_graph_fast_pipeline import prepared


def test_default_health_reports_the_actual_fast_budget(monkeypatch):
    from runtime_source_identity import configured_recognition_budget
    from graph_fast_pipeline import configured_fast_budget
    monkeypatch.delenv('DMATE_GRAPH_PIPELINE', raising=False)
    monkeypatch.setenv('DMATE_AGENT_SECONDS', '230')
    monkeypatch.setenv('DMATE_AGENT_MAX_CALLS', '16')
    actual = configured_recognition_budget()
    budget = configured_fast_budget()
    assert actual['seconds'] == round(budget.deadline-budget.started) == 200
    assert actual['total_remote_calls'] == budget.initial_calls == 2
    assert actual['network_recoveries'] == actual['json_recoveries'] == 0
    assert actual['performance_target_seconds'] == 120
    assert actual['max_concurrent_images'] == 4


def test_fast_partial_result_is_not_a_performance_success(prepared, monkeypatch):
    import graph_fast_pipeline
    import ocr_nextgen
    raw, run, _ = prepared
    result, _ = run()
    result['body_complete'] = False
    monkeypatch.setattr(graph_fast_pipeline, 'recognize_fast', lambda *a, **kw: copy.deepcopy(result))
    rendered = ocr_nextgen.recognize_graph_document(raw, {}, graph_pipeline='agent-tools')
    assert rendered['recognition_status'] == 'partial'
    assert rendered['recognition_timing']['within_target'] is False
    assert rendered['recognition_timing']['completed'] is False
