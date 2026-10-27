"""Opt-in actual Chromium four-file upload and editing/confirmation contract."""
import os

import pytest

from scripts.verify_editable_batch_ui import child_environment, fixture_document, run


def test_synthetic_batch_child_keeps_production_credentials_out(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY', 'not-for-this-test')
    monkeypatch.setenv('DATABASE_URL', 'not-for-this-test')
    env = child_environment(tmp_path)
    assert 'ZHIPU_API_KEY' not in env and 'DATABASE_URL' not in env
    assert env['DMATE_GRAPH_PIPELINE'] == 'agent-tools'
    assert env['DMATE_GRAPH_CONFIRMATION_DB'] == str(tmp_path/'confirmations.sqlite3')
    assert fixture_document('A') != fixture_document('B')


def test_actual_four_file_edit_confirm_solve_browser_contract():
    browser = os.environ.get('DMATE_BROWSER_EXECUTABLE')
    cache = os.environ.get('DMATE_BROWSER_CDN_CACHE')
    output = os.environ.get('DMATE_EDITABLE_BATCH_OUTPUT')
    if not browser or not cache or not output:
        pytest.skip('Set Chromium, verified CDN cache and a new private editable-batch artifact directory')
    pytest.importorskip('playwright.sync_api')
    report = run(output, browser, cache)
    assert report['status'] == 'pass', report['errors']
    assert report['fixture_only'] is True and report['recognition_accuracy_test'] is False
    assert report['production_performance_test'] is False and report['external_model_sends'] == 0
