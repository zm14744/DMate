"""Cold layout startup gets time without bypassing upload and worker limits."""
import math
from unittest.mock import Mock

import pytest

import graph_semantic_layout as module
from test_graph_semantic_layout import Budget, isolate, model_layout, picture, png


@pytest.mark.parametrize('setting,minimum,maximum', [
    (None, 29., 30.), ('32', 31., 32.), ('1000', 34., 35.),
    ('nan', 29., 30.), ('inf', 29., 30.), ('invalid', 29., 30.),
])
def test_configured_allowance_reaches_real_worker_boundary(setting, minimum, maximum, monkeypatch):
    import ocr_runtime
    if setting is None:
        monkeypatch.delenv('DMATE_LAYOUT_SECONDS', raising=False)
    else:
        monkeypatch.setenv('DMATE_LAYOUT_SECONDS', setting)
    worker = Mock(return_value=(model_layout(), {'stage': 'layout', 'status': 'ok',
        'seconds': 24., 'rss_observed': True, 'completion_validated': True}))
    monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    result = module.prepare_semantic_layout(png(picture()), budget=Budget(seconds=90), run_layout=True)
    assert worker.call_count == 1
    actual = worker.call_args.kwargs['timeout']
    assert minimum < actual <= maximum
    assert result['layout']['status'] == 'ok'
    assert result['diagnostics']['layout_model_executed_this_call']


def test_worker_allowance_is_still_clipped_to_upload_deadline(monkeypatch):
    import ocr_runtime
    monkeypatch.setenv('DMATE_LAYOUT_SECONDS', '35')
    worker = Mock(return_value=(None, {'stage': 'layout', 'status': 'timeout',
                                    'phase_peaks': [{'phase': 'layout_init'}]}))
    monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    result = module.prepare_semantic_layout(png(picture()), budget=Budget(seconds=7), run_layout=True)
    assert 0 < worker.call_args.kwargs['timeout'] <= 5
    assert result['layout']['status'] == 'unavailable'
    assert result['resource_metrics'][-1]['status'] == 'timeout'
    assert result['panels'] and result['images']
    assert not result['diagnostics']['layout_model_executed_this_call']


@pytest.mark.parametrize('value', [0, 35.1, True, math.inf, math.nan])
def test_invalid_explicit_allowance_never_starts_a_worker(value, monkeypatch):
    import ocr_runtime
    worker = Mock()
    monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    with pytest.raises(ValueError, match='invalid_layout_budget'):
        module.prepare_semantic_layout(png(picture()), budget=Budget(), run_layout=True, layout_timeout=value)
    worker.assert_not_called()
