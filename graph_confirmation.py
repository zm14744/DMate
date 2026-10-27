"""User-confirmed, source-bound semantic snapshots shared by web workers.

The registry stores only identities and digests. It never stores photographs,
question text or model credentials, and confirmation never calls a model.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from jsonschema import Draft202012Validator

VERSION = 'dmate.confirmed/1'
COOKIE_NAME = 'dm_graph_owner'
MAX_BYTES = 200_000
TTL_SECONDS = 7 * 24 * 60 * 60
_ID = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': r'\S'}
_TEXT = {'type': ['string', 'null'], 'maxLength': 256}
_COORD = {'type': 'number', 'minimum': 0, 'maximum': 1}
_POINT = {'type': 'array', 'prefixItems': [_COORD, _COORD], 'minItems': 2, 'maxItems': 2}
_BBOX = {'type': 'array', 'prefixItems': [_COORD, _COORD, _COORD, _COORD], 'minItems': 4, 'maxItems': 4}
_EDGE = {'type': 'object', 'required': ['id', 'from', 'to', 'direction'], 'properties': {
    'id': _ID, 'from': _ID, 'to': _ID, 'direction': {'enum': ['forward', 'undirected']},
    'weight': {'type': ['number', 'string', 'null'], 'maxLength': 256},
    'edge_label': _TEXT, 'style': {'type': ['string', 'null'], 'maxLength': 64},
    'color': {'type': ['string', 'null'], 'maxLength': 64}, 'multiplicity': {'const': 1},
    'path': {'type': 'array', 'items': _POINT, 'maxItems': 128}}}
DOCUMENT_SCHEMA = {'type': 'object', 'required': ['body_text', 'graphs'], 'properties': {
    'body_text': {'type': 'string', 'maxLength': 24000},
    'graphs': {'type': 'array', 'maxItems': 64, 'items': {
        'type': 'object', 'required': ['id', 'vertices', 'edges'], 'properties': {
            'id': _ID, 'name': _TEXT, 'bbox': _BBOX,
            'anon_next': {'type': 'integer', 'minimum': 1, 'maximum': 10000},
            'vertices': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {
                'type': 'object', 'required': ['id'], 'properties': {
                    'id': _ID, 'label': _TEXT, 'display_label': {'type': 'string', 'maxLength': 16},
                    'x': {'anyOf': [_COORD, {'type': 'null'}]},
                    'y': {'anyOf': [_COORD, {'type': 'null'}]}}}},
            'edges': {'type': 'array', 'maxItems': 300, 'items': _EDGE}}}}}}


class ConfirmationError(ValueError):
    def __init__(self, code, message, *, status=400, issues=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.issues = issues or []


def _json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ConfirmationError('invalid_document', '图结构包含无效数据。') from exc
    if len(encoded.encode()) > MAX_BYTES:
        raise ConfirmationError('document_too_large', '题目结构过大，请拆成较小的题目。')
    return encoded


def document_digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def confirmation_owner():
    """A per-browser secret, additionally separated by the signed login ID."""
    from flask import g, request, session
    token = request.cookies.get(COOKIE_NAME)
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
        token = getattr(g, '_graph_owner_cookie', None) or secrets.token_hex(32)
        g._graph_owner_cookie = token
    principal = session.get('user_id')
    principal = str(principal) if type(principal) is int else 'guest'
    return hashlib.sha256((token + ':' + principal).encode()).hexdigest()


def attach_confirmation_cookie(response):
    from flask import g, request
    token = getattr(g, '_graph_owner_cookie', None)
    if token:
        response.set_cookie(COOKIE_NAME, token, max_age=TTL_SECONDS, httponly=True,
                            secure=request.is_secure, samesite='Lax')
    return response


@contextmanager
def _connection():
    path = Path(os.environ.get('DMATE_GRAPH_CONFIRMATION_DB') or
                Path(tempfile.gettempdir()) / 'dmate-graph-confirmations.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    # SQLite transactions coordinate all Gunicorn workers. No process-local
    # "latest graph" can select another image or undo a newer confirmation.
    connection = sqlite3.connect(str(path), timeout=5)
    os.chmod(path, 0o600)
    try:
        with connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS graph_confirmations (
                owner TEXT NOT NULL, request_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0, document_sha256 TEXT, token_sha256 TEXT,
                expires REAL NOT NULL, PRIMARY KEY(owner, request_id))''')
            connection.execute('DELETE FROM graph_confirmations WHERE expires < ?', (time.time(),))
            yield connection
    finally:
        connection.close()


def _identity(request_id, source_sha256):
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request_id):
        raise ConfirmationError('invalid_request_id', '识别任务标识无效，请重新选择原图。')
    if not isinstance(source_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', source_sha256):
        raise ConfirmationError('invalid_source_sha256', '原图标识无效，请重新选择原图。')


def register_recognition(owner, request_id, source_sha256):
    """Called after /ocr receives the original bytes, including failed reads."""
    _identity(request_id, source_sha256)
    with _connection() as connection:
        row = connection.execute('SELECT source_sha256 FROM graph_confirmations WHERE owner=? AND request_id=?',
                                 (owner, request_id)).fetchone()
        if row and row[0] != source_sha256:
            raise ConfirmationError('task_source_mismatch', '该任务对应的原图已改变，请新建识别任务。', status=409)
        connection.execute('''INSERT INTO graph_confirmations(owner,request_id,source_sha256,expires)
            VALUES(?,?,?,?) ON CONFLICT(owner,request_id) DO UPDATE SET expires=excluded.expires''',
                           (owner, request_id, source_sha256, time.time() + TTL_SECONDS))


def validate_document(value):
    """Validate the edited graph, then derive redundant display/type fields."""
    _json(value)
    issues = [{'path': list(error.absolute_path), 'message': error.message}
              for error in Draft202012Validator(DOCUMENT_SCHEMA).iter_errors(value)]
    if issues:
        raise ConfirmationError('invalid_document', '请先修正题目结构中标出的字段。', issues=issues[:30])
    graph_ids = set()
    for graph in value['graphs']:
        if graph['id'] in graph_ids:
            issues.append({'graph_id': graph['id'], 'message': '子图标识重复。'})
        graph_ids.add(graph['id'])
        nodes, edges = [v['id'] for v in graph['vertices']], [e['id'] for e in graph['edges']]
        box = graph.get('bbox')
        if box is not None and not (box[0] < box[2] and box[1] < box[3]):
            issues.append({'graph_id': graph['id'], 'message': '图形框选范围无效。'})
        for vertex in graph['vertices']:
            if (vertex.get('x') is None) != (vertex.get('y') is None):
                issues.append({'graph_id': graph['id'], 'vertex_id': vertex['id'], 'message': '顶点坐标必须成对提供。'})
        if len(set(nodes)) != len(nodes) or len(set(edges)) != len(edges):
            issues.append({'graph_id': graph['id'], 'message': '节点或边的标识重复。'})
        for edge in graph['edges']:
            if edge['from'] not in nodes or edge['to'] not in nodes:
                issues.append({'graph_id': graph['id'], 'edge_id': edge['id'], 'message': '边的端点必须属于当前子图。'})
        if any(graph.get(key) for key in ('unresolved_edges', 'unresolved_vertices', 'uncertain_edges')):
            issues.append({'graph_id': graph['id'], 'message': '请先处理未确定的节点或边，再确认。'})
    if value.get('uncertainties'):
        issues.append({'message': '请先处理仍待核对的内容，再确认。'})
    from graph_semantic_solver import _safe_text_context
    valid_context, context = _safe_text_context(value.get('text_context'), graph_ids)
    if not valid_context:
        issues.append({'message': '图例或图注引用了不存在的子图。'})
    if issues:
        raise ConfirmationError('invalid_document', '请先修正题目结构。', issues=issues[:30])
    from graph_semantic_schema import normalize_semantic_document
    normalized = normalize_semantic_document(value, reviewed=True)
    if normalized['semantic_issues']:
        raise ConfirmationError('invalid_document', '请先补全题干与图结构。', issues=normalized['semantic_issues'])
    from graph_schema import display_graph
    document = {'body_text': normalized['body_text'], 'graphs': []}
    for graph in normalized['graphs']:
        clean = display_graph(graph)
        clean.pop('schema_version', None)
        document['graphs'].append(clean)
    if context is not None:
        document['text_context'] = context
    from graph_semantic_tools import inspect_semantic_graphs
    inspection = inspect_semantic_graphs(document)
    if inspection['issues']:
        raise ConfirmationError('structure_validation_failed', '结构检查未通过，请核对后再确认。',
                                issues=inspection['issues'], status=422)
    _json(document)
    return document, inspection


def _drawing_document(edited, document):
    """Keep image positions separate from verified math and chat snapshots.

    The submitted fields were validated in validate_document; only known
    graph/vertex/edge IDs can receive geometry. Do not copy model proofs.
    """
    drawing = copy.deepcopy(document)
    sources = {g['id']: g for g in edited['graphs']}
    for graph in drawing['graphs']:
        source = sources.get(graph['id'])
        if source is None:
            continue
        for key in ('bbox', 'anon_next'):
            if key in source:
                graph[key] = copy.deepcopy(source[key])
        by_vertex = {v['id']: v for v in source['vertices']}
        by_edge = {e['id']: e for e in source['edges']}
        for node in graph['vertices']:
            v = by_vertex.get(node['id'], {})
            if v.get('display_label'):
                node['display_label'] = v['display_label']
            if v.get('x') is not None and v.get('y') is not None:
                node['x'], node['y'] = v['x'], v['y']
        for edge in graph['edges']:
            source_edge = by_edge.get(edge['id'], {})
            if source_edge.get('path'):
                edge['path'] = copy.deepcopy(source_edge['path'])
    _json(drawing)
    return drawing


def _context(document, request_id, source_sha256, token, revision):
    from graph_schema import describe_graphs
    visual = describe_graphs(document['graphs'])
    text = document['body_text']
    # The complete edge table always stays in document and the editor. A
    # compact prose anchor avoids duplicating large graphs into chat history.
    display_visual = visual
    if len(text) + len(visual) > 22000:
        display_visual = '\n'.join(f"{g['name']}：{len(g['vertices'])} 个顶点，{len(g['edges'])} 条边；完整边表见已确认图结构。"
                                   for g in document['graphs'])
    question = ('【题目文字】\n' + text if text else '')
    if display_visual:
        question += ('\n\n' if question else '') + '【图形信息】\n' + display_visual
    if len(question) > 24000:
        raise ConfirmationError('question_too_large', '题干过长，请拆分后确认。')
    context = {'document': copy.deepcopy(document), 'source_sha256': source_sha256,
            'question_text': question, 'rendered_question_text': question,
            'confirmation_token': token, 'document_sha256': document_digest(document),
            'revision': revision, 'request_id': request_id, 'profile': 'editable-v1'}
    _json(context)
    return context, visual


def confirm_document(owner, payload):
    if not isinstance(payload, dict) or payload.get('confirmed') is not True:
        raise ConfirmationError('confirmation_required', '请先核对并确认当前题目结构。')
    request_id, sha = payload.get('request_id'), payload.get('source_sha256')
    _identity(request_id, sha)
    edited = payload.get('document')
    document, inspection = validate_document(edited)
    drawing_document = _drawing_document(edited, document)
    token, digest = secrets.token_hex(32), document_digest(document)
    with _connection() as connection:
        row = connection.execute('SELECT source_sha256,revision FROM graph_confirmations WHERE owner=? AND request_id=?',
                                 (owner, request_id)).fetchone()
        if row is None or row[0] != sha:
            raise ConfirmationError('unknown_source_task', '该原图任务已失效，请重新选择原图。', status=409)
        revision = row[1] + 1
        context, visual = _context(document, request_id, sha, token, revision)
        connection.execute('''UPDATE graph_confirmations SET revision=?,document_sha256=?,token_sha256=?,expires=?
            WHERE owner=? AND request_id=?''', (revision, digest, hashlib.sha256(token.encode()).hexdigest(),
            time.time() + TTL_SECONDS, owner, request_id))
    return {'document': document, 'drawing_document': drawing_document,
            'drawing_sha256': document_digest(drawing_document),
            'semantic_context': context, 'confirmation_token': token,
            'document_sha256': digest, 'revision': revision, 'request_id': request_id,
            'source_sha256': sha, 'graph_display_data': document['graphs'], 'visual_text': visual,
            'validation': {'status': 'valid', 'schema': VERSION, 'tool_audit': inspection['tool_audit'],
                           'user_confirmed': True, 'image_accuracy_certified': False}}


def resolve_confirmed_context(owner, payload):
    """Return the exact confirmed content, or None for an older legacy context."""
    if not isinstance(payload, dict):
        return None
    request_id, sha, token = payload.get('request_id'), payload.get('source_sha256'), payload.get('confirmation_token')
    required = (payload.get('profile') == 'editable-v1' or any(
        key in payload for key in ('confirmation_token', 'document_sha256', 'revision', 'request_id')))
    with _connection() as connection:
        row = connection.execute('''SELECT request_id,source_sha256,revision,document_sha256,token_sha256
            FROM graph_confirmations WHERE owner=? AND (request_id=? OR source_sha256=?)
            ORDER BY request_id=? DESC LIMIT 1''', (owner, request_id, sha, request_id)).fetchone()
        if not required and row is None:
            return None
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
            raise ConfirmationError('confirmation_required', '请先核对并确认本张图片的题目结构。', status=409)
        if (row is None or row[0] != request_id or row[1] != sha
                or type(payload.get('revision')) is not int or row[2] != payload['revision']
                or not row[4] or not hmac.compare_digest(row[4], hashlib.sha256(token.encode()).hexdigest())):
            raise ConfirmationError('confirmation_stale', '这份确认已失效或不属于当前图片，请重新确认。', status=409)
        digest = document_digest(payload.get('document'))
        if not hmac.compare_digest(row[3] or '', digest) or payload.get('document_sha256') != digest:
            raise ConfirmationError('confirmation_changed', '题目结构已修改，请重新确认后解题。', status=409)
    context, _ = _context(payload['document'], request_id, sha, token, row[2])
    if any(payload.get(key) != context[key] for key in ('question_text', 'rendered_question_text')):
        raise ConfirmationError('confirmation_changed', '题目文字已修改，请重新确认后解题。', status=409)
    return context
