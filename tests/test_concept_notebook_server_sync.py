"""Older clients must not erase notes they cannot represent in their snapshot."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from test_ocr_application_contract import application


class SyncRows:
    def __init__(self):
        self.rows = {
            1: {'data': {'learning': {'conceptNotebook': {'notes': [
                {'id': 'set', 'title': '集合', 'content': '确定的对象组成的整体。', 'updatedAt': 10}], 'deleted': {}}}}, 'revision': 6},
            2: {'data': {'learning': {'conceptNotebook': {'notes': [
                {'id': 'private', 'title': '另一账号', 'content': '私有内容', 'updatedAt': 5}], 'deleted': {}}}}, 'revision': 2},
        }
        self.queries = []
        self.result = None
        self.writes = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def execute(self, query, params):
        query = ' '.join(query.split())
        self.queries.append((query, deepcopy(params)))
        if query.startswith('INSERT'):
            self.rows.setdefault(params[0], {'data': {}, 'revision': 0})
            self.result = None
        elif query.startswith('SELECT'):
            self.result = deepcopy(self.rows.get(params[0]))
        elif query.startswith('UPDATE'):
            data, owner, expected = params
            if self.rows[owner]['revision'] != expected:
                self.result = None
                return
            self.rows[owner] = {'data': deepcopy(data), 'revision': expected + 1,
                                'updated_at': datetime.now(timezone.utc)}
            self.result = deepcopy(self.rows[owner])
            self.writes += 1
        else:
            raise AssertionError(query)

    def fetchone(self):
        return deepcopy(self.result)

    def rollback(self):
        pass


@pytest.fixture
def sync_endpoint(application, monkeypatch):
    module, client, _ = application
    rows = SyncRows()
    monkeypatch.setattr(module, 'AUTH_CONFIGURED', True)
    monkeypatch.setattr(module, '_ensure_auth_schema', lambda: True)
    monkeypatch.setattr(module, '_current_auth_user', lambda: {'id': 1})
    monkeypatch.setattr(module, '_auth_connect', lambda: rows)
    monkeypatch.setattr(module, 'Jsonb', lambda value: value)
    return module, client, rows


@pytest.mark.parametrize('incoming', [{'sessions': {}}, {'learning': {'events': []}}])
def test_legacy_snapshot_keeps_current_owners_notebook_under_row_lock(sync_endpoint, incoming):
    _, client, rows = sync_endpoint
    before = deepcopy(rows.rows)
    result = client.put('/sync', json={'baseRevision': 6, 'data': incoming})
    assert result.status_code == 200, result.get_json()
    assert rows.rows[1]['data']['learning']['conceptNotebook'] == before[1]['data']['learning']['conceptNotebook']
    assert rows.rows[2] == before[2]
    assert rows.writes == 1 and rows.rows[1]['revision'] == 7
    locked = next(i for i, (query, _) in enumerate(rows.queries) if 'FOR UPDATE' in query)
    written = next(i for i, (query, _) in enumerate(rows.queries) if query.startswith('UPDATE'))
    assert locked < written
    assert all(params[-1] == 1 for query, params in rows.queries if query.startswith('SELECT'))


def test_explicit_notebook_deletion_is_not_replaced_with_previous_notes(sync_endpoint):
    _, client, rows = sync_endpoint
    empty = {'notes': [], 'deleted': {'set': 20}}
    result = client.put('/sync', json={'baseRevision': 6, 'data': {'learning': {'conceptNotebook': empty}}})
    assert result.status_code == 200
    assert rows.rows[1]['data']['learning']['conceptNotebook'] == empty


def test_old_revision_cannot_restore_or_replace_current_notebook(sync_endpoint):
    _, client, rows = sync_endpoint
    before = deepcopy(rows.rows)
    result = client.put('/sync', json={'baseRevision': 5, 'data': {'learning': {}}})
    assert result.status_code == 409 and result.get_json()['conflict'] is True
    assert rows.rows == before and rows.writes == 0
    assert result.get_json()['data'] == before[1]['data']


def test_preserving_unknown_notes_still_respects_complete_snapshot_capacity(sync_endpoint, monkeypatch):
    module, client, rows = sync_endpoint
    monkeypatch.setattr(module, 'MAX_SYNC_JSON_BYTES', 30)
    before = deepcopy(rows.rows)
    result = client.put('/sync', json={'baseRevision': 6, 'data': {'learning': {}}})
    assert result.status_code == 413
    assert rows.rows == before and rows.writes == 0
