"""Run each private original once; never re-upload or select a best result.

Current application capture (provider recovery stays inside its own budget):
  python scripts/benchmark_graph_first_pass.py --pipeline auto \
    --base-url http://127.0.0.1:8081 --source-root /private/frozen-source \
    --manifest /private/manifest.json --output /private/first-results

Score those exact responses later, without another model or HTTP call:
  python scripts/benchmark_graph_first_pass.py --evaluate-run /private/first-results \
    --manifest /private/manifest.json --annotations /private/gold.json \
    --output /private/first-evaluation

Manifest collections may be named images, cases or entries. With no reference,
capture remains ungraded. Reviewed semantic gold uses body_text, graphs and
explicit label/edge facts; ambiguous references never count as passes.

Example (no model/API calls):
  python scripts/benchmark_graph_first_pass.py --manifest /private/manifest.json \
    --annotations /private/slides.json /private/other.json --local \
    --check-only --output /private/preflight-unique

Artifacts include private original responses and must remain outside the repo.
No gold data is passed into any recognition function, prompt, or model call.
--local evaluates the local recognition pipeline; subsequent dialog replay is
separate. Neither mode certifies the application's /ocr enablement/dispatch,
browser upload handler, HTTP error handling or readiness. Application status
is not_run locally; an observed HTTP response is retained as not_certified for
full application acceptance even when pipeline and replay components pass.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib import error, parse, request
import uuid
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graph_first_pass_eval import (evaluate_prediction, evaluation_scope, load_annotations,
                                   prediction_digest, reference_issues, reference_text_issues,
                                   summarize_assessments)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, data):
    # Exclusive creation prevents replacing first results with a later success.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def source_snapshot():
    def git(*args):
        return subprocess.check_output(['git', '-C', str(ROOT), *args], stderr=subprocess.DEVNULL)
    try:
        head = git('rev-parse', 'HEAD').decode().strip()
        status = git('status', '--porcelain', '--untracked-files=all').decode()
        paths = sorted(set(git('ls-files', '-c', '-o', '--exclude-standard', '-z').decode().split('\0')) - {''})
        tracked = set(git('ls-files', '-z').decode().split('\0'))
        records = []
        for name in paths:
            path = ROOT/name
            if any(part in ('__pycache__', '.pytest_cache', '.mypy_cache') for part in path.parts):
                continue
            # Tracked assets/config and untracked source both affect this run.
            if name not in tracked and path.suffix not in ('.py', '.js', '.ts', '.json', '.toml', '.yaml', '.yml', '.html', '.css'):
                continue
            if path.is_file() and not path.is_symlink():
                records.append({'path': name, 'sha256': digest(path.read_bytes())})
        tree = digest(json.dumps(records, sort_keys=True, separators=(',', ':')).encode())
        return {'git_sha': head, 'dirty': bool(status.strip()), 'source_tree_sha256': tree,
                'files': records, 'captured_at': utc_now()}
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return {'git_sha': None, 'dirty': None, 'source_tree_sha256': None, 'captured_at': utc_now(), 'status': 'unavailable'}


def same_source(a, b):
    return bool(a.get('git_sha') and a.get('git_sha') == b.get('git_sha')
                and a.get('source_tree_sha256') == b.get('source_tree_sha256'))


def validate_base_url(value):
    parsed = parse.urlsplit(value)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Only a plain local HTTP(S) base URL is allowed')
    host = parsed.hostname
    try:
        loopback = host == 'localhost' or ipaddress.ip_address(host or '').is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError('Benchmark HTTP target must be a non-production loopback address')
    return value.rstrip('/')


def load_manifest(path):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    entries = manifest.get('images', manifest.get('cases', manifest.get('entries')))
    if not isinstance(entries, list) or not entries:
        raise ValueError('Manifest has no original images')
    rows, identifiers = [], set()
    for item in entries:
        cid = item.get('id')
        if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', cid) or cid in identifiers:
            raise ValueError('Invalid or duplicate manifest ID')
        identifiers.add(cid)
        raw_path = item.get('path', item.get('image'))
        if not isinstance(raw_path, str):
            raise ValueError('Missing original image path: '+cid)
        image = Path(raw_path)
        image = (path.parent/image).resolve() if not image.is_absolute() else image.resolve()
        if not image.is_file():
            raise ValueError('Missing original image: '+cid)
        actual = digest(image.read_bytes())
        if item.get('sha256') != actual:
            raise ValueError('Original digest mismatch: '+cid)
        from PIL import Image
        with Image.open(image) as original:
            width, height = original.size
            if (item.get('width', width), item.get('height', height)) != (width, height):
                raise ValueError('Original dimensions mismatch: '+cid)
        rows.append({**item, 'path': str(image), 'width': width, 'height': height})
    return manifest, rows


def preflight(rows, annotations, mode):
    records = []
    for row in rows:
        gold = annotations.get(row['id'])
        issues = reference_issues(gold)
        if gold and gold.get('sha256') != row['sha256']:
            issues.append('reference_original_digest_mismatch')
        text_issues = reference_text_issues(gold)
        records.append({'id': row['id'], 'reference_status': 'ready' if not issues else 'not_certified',
                        'reference_scope': 'graph_structure', 'issues': issues,
                        'text_reference_status': 'ready' if not text_issues else 'not_certified',
                        'text_issues': text_issues})
    credentials = {'qwen_key_present': bool((os.environ.get('DASHSCOPE_API_KEY') or os.environ.get('DASHSCOPE_VISION_API_KEY') or '').strip()),
                   'deepseek_key_present': bool((os.environ.get('DEEPSEEK_API_KEY') or '').strip())}
    dependencies = {name: importlib.util.find_spec(name) is not None for name in ('PIL', 'requests', 'cv2', 'networkx', 'paddleocr', 'paddle')}
    missing = [name for name, available in dependencies.items() if not available]
    missing_credentials = [name for name, present in credentials.items() if not present]
    vision_enabled = os.environ.get('VISION_ANALYSIS_ENABLED', '1').strip().lower() not in {'0', 'false', 'off', 'no'}
    blocked = mode == 'local' and bool(missing_credentials or missing or not vision_enabled)
    return {'status': 'blocked' if blocked else 'ready', 'mode': mode, 'credentials': credentials,
            'dependencies': dependencies, 'blocking_dependencies': missing if mode == 'local' else [],
            'blocking_credentials': missing_credentials if mode == 'local' else [],
            'vision_enabled': vision_enabled,
            'blocking_configuration': ['VISION_ANALYSIS_ENABLED'] if mode == 'local' and not vision_enabled else [],
            'reference_records': records, 'reference_ready_count': sum(r['reference_status'] == 'ready' for r in records),
            'reference_not_certified_count': sum(r['reference_status'] != 'ready' for r in records),
            'reference_text_ready_count': sum(r['text_reference_status'] == 'ready' for r in records),
            'full_reference_ready_count': sum(r['reference_status'] == r['text_reference_status'] == 'ready' for r in records),
            'api_calls_made': 0,
            'notes': ['HTTP credentials/source identity belong to the local server and are not established by this preflight'] if mode == 'http' else []}


def _payload_evidence(payload):
    texts, images = [], []
    for message in payload.get('messages') or []:
        if not isinstance(message, dict):
            continue
        content = message.get('content')
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get('type') == 'text' and isinstance(item.get('text'), str):
                    texts.append(item['text'])
                elif item.get('type') == 'image_url':
                    value = item.get('image_url') or {}
                    url = value.get('url') if isinstance(value, dict) else None
                    if isinstance(url, str) and url.startswith('data:image/') and ';base64,' in url:
                        images.append(digest(base64.b64decode(url.split(',', 1)[1], validate=True)))
    return {'prompt_sha256': digest(texts[0].encode()) if len(texts) == 1 else None,
            'image_sha256': images}


@contextmanager
def capture_model_transports(records, *, execution_id=None):
    """Observe sends and their actual Qwen/text call boundaries separately.

    Payload hashes come from PreparedRequest bytes, independently of provider
    self-reported metrics. No authorization headers enter this private ledger.
    """
    import requests
    import ai
    original = requests.sessions.Session.send
    original_text = ai._request_text_completion
    original_qwen = ai._request_qwen_completion
    execution_id = execution_id or uuid.uuid4().hex
    state = {'text_call': 0, 'qwen_call': 0, 'active': None, 'text_model_attempts': [],
             'execution_id': execution_id}

    def qwen_call(*args, **kwargs):
        state['qwen_call'] += 1
        previous = state['active']
        state['active'] = {'provider': 'qwen', 'logical_call': state['qwen_call'], 'attempts': 0}
        try:
            return original_qwen(*args, **kwargs)
        finally:
            state['active'] = previous

    def text_call(*args, **kwargs):
        # The benchmark policy forbids automatic retries for text as well as
        # vision. Bind rather than adding a possibly duplicate positional arg.
        bound = inspect.signature(original_text).bind_partial(*args, **kwargs)
        bound.arguments['retries'] = 0
        state['text_call'] += 1
        previous = state['active']
        state['active'] = {'provider': 'text', 'logical_call': state['text_call'], 'attempts': 0}
        metric = {'provider': 'text', 'logical_call': state['text_call'], 'attempt': 1,
                  'execution_id': execution_id, 'started_at_unix': time.time(),
                  'configured_retries': 0}
        try:
            result = original_text(*bound.args, **bound.kwargs)
            metric['status'] = 200 if isinstance(result, dict) and result.get('ok') is True else 'failed'
            if isinstance(result, dict):
                metric['model'] = result.get('model')
                metric['finish_reason'] = (result.get('choice') or {}).get('finish_reason')
                # This benchmark ledger is private, like the Qwen raw-content
                # capture. Preserve the actual text response so rejected edits
                # and malformed JSON can be diagnosed without another API call.
                metric['raw_content'] = result.get('content')
                if isinstance(metric['raw_content'], str):
                    metric['raw_content_sha256'] = digest(metric['raw_content'].encode())
            return result
        except Exception as exc:
            metric.update(status='failed', exception_type=type(exc).__name__)
            raise
        finally:
            sent = [r for r in records if r.get('provider') == 'text' and r.get('logical_call') == metric['logical_call']]
            if len(sent) == 1:
                metric.update(transport_id=sent[0]['transport_id'], http_status=sent[0].get('http_status'))
                metric['model'] = metric.get('model') or sent[0]['model']
            metric['seconds'] = round(time.time()-metric['started_at_unix'], 6)
            state['text_model_attempts'].append(metric)
            state['active'] = previous
    def send(session, prepared, **kwargs):
        body = prepared.body
        try:
            payload = json.loads(body.decode() if isinstance(body, bytes) else body)
        except (TypeError, ValueError, UnicodeError):
            payload = {}
        if not isinstance(payload, dict) or not payload.get('model'):
            return original(session, prepared, **kwargs)
        host = parse.urlsplit(prepared.url).hostname
        number = len(records)+1
        observation = {'model': payload['model'], 'host': host, 'started_at_unix': time.time(),
                       'method': prepared.method, 'execution_id': execution_id,
                       'transport_id': execution_id+':send:'+str(number),
                       'request_body_sha256': digest(body if isinstance(body, bytes) else str(body).encode()),
                       'transport_attempt_index': number, **_payload_evidence(payload)}
        if state['active'] is not None:
            state['active']['attempts'] += 1
            observation.update(provider=state['active']['provider'], logical_call=state['active']['logical_call'],
                               attempt=state['active']['attempts'], configured_retries=0)
        else:
            observation['provider'] = 'unscoped'
        records.append(observation)
        started = time.monotonic()
        try:
            response = original(session, prepared, **kwargs)
            observation['http_status'] = response.status_code
            return response
        except Exception as exc:
            observation['exception_type'] = type(exc).__name__
            raise
        finally:
            observation['transport_seconds'] = round(time.monotonic()-started, 6)
    requests.sessions.Session.send = send
    ai._request_text_completion = text_call
    ai._request_qwen_completion = qwen_call
    try:
        yield state
    finally:
        requests.sessions.Session.send = original
        ai._request_text_completion = original_text
        ai._request_qwen_completion = original_qwen


def local_recognition(raw, *, execution_id=None, pipeline='evidence-two-pass'):
    if pipeline == 'agent-tools':
        # Use the current semantic pipeline with its own local tools and normal
        # request budget. The old two-pass transport observer changes retries
        # and is not safe for this pipeline's concurrent provider calls.
        from ocr_nextgen import recognize_graph_document
        prediction = recognize_graph_document(raw, {'text': '', 'resource_metrics': []},
            graph_pipeline=pipeline, task_id=execution_id)
        diagnostics = prediction.get('diagnostics', {})
        return prediction, {'status': 'completed', 'pipeline_contract': pipeline,
            'execution_id': execution_id, 'model_attempts': diagnostics.get('remote_metrics', []),
            'text_model_attempts': [], 'transport_attempts': [],
            'model_send_verification': 'pipeline_reported_unverified'}
    if pipeline != 'evidence-two-pass':
        raise ValueError('Unsupported pipeline')
    from vision_provider import VisionProvider
    from ocr_runtime import recognize_image
    from ocr_nextgen import recognize_graph_document
    provider = VisionProvider('qwen', retries=0, capture=True)
    if not provider.available():
        return None, {'status': 'blocked', 'reason': 'missing_or_disabled_qwen_credentials',
                      'model_attempts': [], 'text_model_attempts': [], 'transport_attempts': []}
    transports = []
    previous = os.environ.get('DMATE_GRAPH_STAGE_AUDIT')
    os.environ['DMATE_GRAPH_STAGE_AUDIT'] = '1'
    meta = {'status': 'completed', 'pipeline_contract': 'evidence-two-pass',
            'model_attempts': [], 'text_model_attempts': [], 'transport_attempts': transports}
    observed = None
    try:
        with capture_model_transports(transports, execution_id=execution_id) as observed:
            # No gold or cached prior result enters either function.
            text_result = recognize_image(raw)
            prediction = recognize_graph_document(raw, text_result, vision_provider=provider)
        meta['model_attempts'] = provider.observations
        return prediction, meta
    except Exception as exc:
        meta.update(status='failed', exception_type=type(exc).__name__,
                    model_attempts=provider.observations)
        return None, meta
    finally:
        if observed is not None:
            meta['execution_id'] = observed['execution_id']
            meta['text_model_attempts'] = observed['text_model_attempts']
            for metric in meta['model_attempts']:
                metric['execution_id'] = observed['execution_id']
                sent = [r for r in transports if r.get('provider') == 'qwen'
                        and r.get('logical_call') == metric.get('logical_call')
                        and r.get('attempt') == metric.get('attempt')]
                if len(sent) == 1:
                    metric['transport_id'] = sent[0]['transport_id']
        if previous is None:
            os.environ.pop('DMATE_GRAPH_STAGE_AUDIT', None)
        else:
            os.environ['DMATE_GRAPH_STAGE_AUDIT'] = previous


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise error.HTTPError(req.full_url, code, 'Redirect refused by private benchmark', headers, fp)


def http_recognition(raw, base_url, filename, timeout, *, execution_id=None,
                     pipeline='evidence-two-pass', response_path=None):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as original:
        mime = Image.MIME.get(original.format, 'application/octet-stream')
    boundary = 'dmate-first-pass-'+uuid.uuid4().hex
    execution_id = execution_id or uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="request_id"\r\n\r\n{execution_id}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f'Content-Type: {mime}\r\n\r\n').encode()+raw+f'\r\n--{boundary}--\r\n'.encode()
    req = request.Request(base_url+'/ocr', data=body, method='POST',
                          headers={'Content-Type': 'multipart/form-data; boundary='+boundary})
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    # Reserve the immutable observation before sending. A repeated invocation
    # for the same artifact must fail without submitting a second paid upload.
    response_stream = (os.fdopen(os.open(response_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb')
                       if response_path is not None else None)
    meta = {'status': 'completed', 'model_attempts': [], 'text_model_attempts': [], 'transport_attempts': [],
            'execution_id': execution_id, 'pipeline_contract': pipeline, 'server_source_verified': False}
    content = b''
    try:
        with opener.open(req, timeout=timeout) as response:
            meta['http_status'] = response.status
            meta['runtime_sha256'] = response.headers.get('X-DMate-Runtime-Sha256')
            content = response.read(32*1024*1024+1)
    except error.HTTPError as exc:
        meta.update(status='failed', http_status=exc.code)
        meta['runtime_sha256'] = exc.headers.get('X-DMate-Runtime-Sha256') if exc.headers else None
        content = exc.read(32*1024*1024+1)
    except (OSError, error.URLError, TimeoutError) as exc:
        meta.update(status='failed', exception_type=type(exc).__name__)
    meta['raw_response_body'] = content.decode('utf-8', errors='replace')
    meta['raw_response_sha256'] = digest(content)
    meta['raw_response_bytes'] = len(content)
    if response_stream is not None:
        # Preserve exact bytes even for HTTP errors and non-JSON responses.
        with response_stream:
            response_stream.write(content)
    if len(content) > 32*1024*1024:
        meta.update(status='failed', reason='response_too_large')
        return None, meta
    try:
        def invalid_constant(value):
            raise ValueError('Non-finite JSON number')
        result = json.loads(content, parse_constant=invalid_constant)
    except (ValueError, UnicodeError):
        return None, {**meta, 'status': 'failed', 'reason': 'invalid_response_json'}
    if not isinstance(result, dict):
        return None, {**meta, 'status': 'failed', 'reason': 'invalid_response_envelope'}
    diagnostics = result.get('diagnostics') if isinstance(result.get('diagnostics'), dict) else {}
    meta['model_attempts'] = diagnostics.get('remote_metrics', [])
    meta['text_model_attempts'] = diagnostics.get('text_model_attempts', [])
    meta['transport_attempts'] = diagnostics.get('transport_attempts', [])
    # HTTP evidence intentionally stays unverified unless the server returns an
    # explicit source digest. A local client checkout is not the server identity.
    meta['server_reported_source'] = diagnostics.get('source_snapshot')
    return result, meta


def inspect_http_service(base_url):
    """Observe the selected app, without credentials or arbitrary headers."""
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    with opener.open(base_url+'/health', timeout=10) as response:
        body = response.read(1024*1024+1)
        if len(body) > 1024*1024:
            raise ValueError('Health response exceeds limit')
        health = json.loads(body)
        runtime = health.get('runtime_source', {})
        header = response.headers.get('X-DMate-Runtime-Sha256')
    if (health.get('status') != 'ok' or runtime.get('status') != 'ok'
            or not re.fullmatch(r'[a-f0-9]{64}', str(runtime.get('manifest_sha256', '')))
            or header != runtime['manifest_sha256']):
        raise ValueError('HTTP runtime identity is unavailable or inconsistent')
    if health.get('graph_nextgen_enabled') is not True:
        raise ValueError('The HTTP service has not enabled the selected graph pipeline')
    if not isinstance(health.get('graph_nextgen_version'), str) or not health['graph_nextgen_version']:
        raise ValueError('The HTTP service pipeline version is unavailable')
    return {'runtime_source': runtime, 'runtime_sha256': header,
            'pipeline': health.get('graph_nextgen_engine'),
            'pipeline_version': health.get('graph_nextgen_version'),
            'recognition_budget': health.get('recognition_budget'),
            'health_response_sha256': digest(body)}


def _literal(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if not isinstance(value, str):
        raise ValueError('Expected a literal label or attribute')
    return unicodedata.normalize('NFC', value.strip())


def _visible_label(value):
    value = _literal(value)
    if not isinstance(value, str):
        return value
    value = value.translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789'))
    return re.sub(r'([A-Za-z])_(?:\{([0-9,]+)\}|([0-9]+))',
                  lambda match: match[1]+(match[2] or match[3]), value)


def _weight(value):
    from decimal import Decimal, InvalidOperation
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('Invalid edge weight')
    if isinstance(value, str):
        value = value.strip()
        for start, end in (('\\(', '\\)'), ('$', '$'), ('\\[', '\\]')):
            if value.startswith(start) and value.endswith(end) and len(value) > len(start)+len(end):
                value = value[len(start):-len(end)].strip()
        value = {'\\pi': 'π'}.get(value, value).replace('−', '-')
    try:
        number = Decimal(str(value))
        if number.is_finite():
            return ('number', str(number.normalize()))
    except InvalidOperation:
        pass
    return ('literal', _literal(value))


def _semantic_network(graph, *, reference=False):
    """Evaluation-only mixed multigraph; no production normalization/repair."""
    import networkx as nx
    nodes, edges = graph.get('vertices'), graph.get('edges')
    if (not isinstance(nodes, list) or not nodes or len(nodes) > 100
            or not isinstance(edges, list) or len(edges) > 300):
        raise ValueError('Invalid or oversized vertex/edge inventory')
    network = nx.MultiDiGraph()
    required = graph.get('required_attributes')
    allowed = {'direction', 'weight', 'edge_label', 'style', 'color', 'multiplicity'}
    if reference and required is not None and (not isinstance(required, list)
            or any(not isinstance(name, str) or name not in allowed for name in required)):
        raise ValueError('Invalid required semantic attribute list')
    for node in nodes:
        if (not isinstance(node, dict) or not isinstance(node.get('id'), str)
                or not node['id'] or node['id'] in network or 'label' not in node
                or not (node['label'] is None or isinstance(node['label'], str))):
            raise ValueError('Invalid vertex identity or visible label')
        network.add_node(node['id'], label=_visible_label(node['label']))
    ungraded = set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('from') not in network or edge.get('to') not in network:
            raise ValueError('Edge endpoint missing from inventory')
        direction = edge.get('direction')
        if direction not in ('forward', 'reverse', 'undirected'):
            raise ValueError('Unknown edge direction')
        multiplicity = edge.get('multiplicity', 1)
        if type(multiplicity) is not int or not 1 <= multiplicity <= 300:
            raise ValueError('Invalid edge multiplicity')
        if 'weight' not in edge or not ('edge_label' in edge or 'label' in edge):
            raise ValueError('Weights and edge labels must be explicit, including null')
        if reference and any(field not in edge for field in (required or []) if field in ('style', 'color')):
            raise ValueError('Required style/color reference annotation is missing')
        attributes = {'direction': 'undirected' if direction == 'undirected' else 'directed',
                      'weight': _weight(edge.get('weight')),
                      'edge_label': _visible_label(edge.get('edge_label', edge.get('label')))}
        for field in ('style', 'color'):
            meaningful = required is None or field in required
            if field in edge and (not reference or meaningful):
                attributes[field] = _literal(edge[field])
            elif reference:
                ungraded.add(field)
        start, end = edge['from'], edge['to']
        if direction == 'reverse':
            start, end = end, start
        for _ in range(multiplicity):
            network.add_edge(start, end, **attributes)
            if direction == 'undirected' and start != end:
                network.add_edge(end, start, **attributes)
        if network.number_of_edges() > 1200:
            raise ValueError('Expanded edge inventory exceeds comparison capacity')
    return network, ungraded


def evaluate_visible_semantics(reference, prediction, *, image_sha256=None):
    """Compare independently annotated visible content, never pixel geometry.

    Missing annotations are ungraded. Explicit null attributes mean absent;
    omitted style/color fields are not silently treated as correctness claims.
    Graph isomorphism retains duplicate/unlabeled vertices and atomic parallel
    edge attributes. This result is separate from runtime or UI certification.
    """
    result = {'scope': 'independently_annotated_visible_semantics', 'status': 'ungraded',
              'text_status': 'ungraded', 'graphs_status': 'ungraded',
              'recognition_status': prediction.get('recognition_status') if isinstance(prediction, dict) else None,
              'issues': [], 'ungraded_attributes': [], 'panel_matches': []}
    if not isinstance(reference, dict):
        result['issues'].append('missing_independent_reference')
        return result
    if 'annotation_status' in reference:
        reference = {**reference,
            'annotation_complete': reference['annotation_status'] == 'reviewed' and not reference.get('ambiguities'),
            'question_text': reference.get('body_text'),
            'question_text_complete': reference['annotation_status'] == 'reviewed' and not reference.get('ambiguities')}
        if reference.get('graphs') == []:
            reference['is_graph_theory_image'] = False
    if image_sha256 is not None and reference.get('sha256') != image_sha256:
        result['issues'].append('reference_image_digest_mismatch')
        return result
    if reference.get('annotation_complete') is not True:
        result['issues'].append('reference_not_explicitly_complete')
        return result
    if not isinstance(prediction, dict):
        result.update(status='fail', text_status='fail', graphs_status='fail')
        result['issues'].append('missing_prediction')
        return result
    if reference.get('question_text_complete') is True and isinstance(reference.get('question_text'), str):
        # Canonical Unicode and whitespace only; mathematical spelling is not
        # rewritten by a model or guessed from the expected answer.
        from graph_first_pass_eval import normalized_text
        result['text_status'] = ('pass' if isinstance(prediction.get('text'), str)
            and normalized_text(reference['question_text']) == normalized_text(prediction['text']) else 'fail')
        if result['text_status'] == 'fail':
            result['issues'].append('visible_body_text_mismatch')
    graph_field = 'graph_display_data' if 'graph_display_data' in prediction else 'graph_structures'
    result['graph_content_source'] = graph_field
    expected, actual = reference.get('graphs'), prediction.get(graph_field)
    if not isinstance(expected, list):
        result['issues'].append('reference_graph_inventory_missing')
    elif not isinstance(actual, list) or len(actual) != len(expected):
        result['graphs_status'] = 'fail'
        result['issues'].append('panel_count_mismatch')
    elif not expected:
        if reference.get('is_graph_theory_image') is False or reference.get('kind') in ('text_only', 'non_graph', 'non_graph_chart'):
            result['graphs_status'] = 'pass'
        else:
            result['issues'].append('empty_reference_not_explicitly_non_graph')
    elif len(expected) > 64:
        result['issues'].append('comparison_capacity_exceeded')
    else:
        import networkx as nx
        deadline, steps = time.monotonic()+10, [0]
        class ComparisonLimit(Exception):
            pass
        def bounded():
            steps[0] += 1
            if steps[0] > 100000 or time.monotonic() > deadline:
                raise ComparisonLimit()
        class Matcher(nx.algorithms.isomorphism.MultiDiGraphMatcher):
            def semantic_feasibility(self, first, second):
                bounded()
                return super().semantic_feasibility(first, second)
        def edge_match(gold, observed):
            # Per-edge fields stay together, including parallel-edge labels,
            # weights and styles. Missing gold style/color are explicit scope
            # limits; this matching never fills them from the prediction.
            compatibility = nx.Graph()
            for i, a in enumerate(gold.values()):
                for j, b in enumerate(observed.values()):
                    bounded()
                    if all(b.get(key) == value for key, value in a.items()):
                        compatibility.add_edge(('g', i), ('p', j))
            left = {('g', i) for i in range(len(gold))}
            compatibility.add_nodes_from(left)
            return len(gold) == len(observed) and len(nx.algorithms.bipartite.maximum_matching(
                compatibility, top_nodes=left)) == 2*len(gold)
        parsing = 'reference'
        try:
            references, predictions = [], []
            for graph in expected:
                if not isinstance(graph, dict) or graph.get('annotation_complete', True) is not True:
                    raise ValueError('Reference graph is incomplete')
                network, ungraded = _semantic_network(graph, reference=True)
                references.append(network)
                result['ungraded_attributes'].extend(ungraded)
            parsing = 'prediction'
            for graph in actual:
                if not isinstance(graph, dict):
                    raise ValueError('Invalid predicted graph')
                predictions.append(_semantic_network(graph)[0])
            compatibility = nx.Graph()
            left = {('g', i) for i in range(len(expected))}
            compatibility.add_nodes_from(left)
            for i, gold in enumerate(expected):
                for j, observed in enumerate(actual):
                    bounded()
                    name = gold.get('printed_name', gold.get('name')) if gold.get('name_required', True) else None
                    if name is not None and _visible_label(name) != _visible_label(observed.get('name')):
                        continue
                    if any(field in gold and gold[field] != observed.get(field)
                           for field in ('directed', 'weighted', 'multigraph')):
                        continue
                    matcher = Matcher(references[i], predictions[j],
                        node_match=lambda a, b: a['label'] == b['label'], edge_match=edge_match)
                    if matcher.is_isomorphic():
                        compatibility.add_edge(('g', i), ('p', j))
            matching = nx.algorithms.bipartite.maximum_matching(compatibility, top_nodes=left)
            result['panel_matches'] = [{'reference': i, 'prediction': matching[('g', i)][1]}
                                       for i in range(len(expected)) if ('g', i) in matching]
            result['graphs_status'] = 'pass' if len(matching) == 2*len(expected) else 'fail'
            if result['graphs_status'] == 'fail':
                result['issues'].append('visible_graph_semantics_mismatch')
        except ComparisonLimit:
            result['issues'].append('comparison_capacity_exceeded')
        except (ValueError, TypeError, KeyError) as exc:
            if parsing == 'prediction':
                result['graphs_status'] = 'fail'
            result['issues'].append('invalid_or_incomplete_graph_evidence:'+str(exc))
        result['ungraded_attributes'] = sorted(set(result['ungraded_attributes']))
    states = (result['text_status'], result['graphs_status'])
    result['status'] = 'fail' if 'fail' in states else 'pass' if all(x == 'pass' for x in states) else 'ungraded'
    return result


def run_selected_pipeline(args, manifest, rows, annotations, output, base_url):
    """Capture one first result per original from the actual selected engine."""
    from runtime_source_identity import compute_runtime_source
    from graph_pipeline_version import active_pipeline
    mode = 'local' if args.local else 'http'
    if args.jobs != 1 and not base_url:
        raise ValueError('Concurrent jobs require selected-pipeline HTTP capture; local observers are process-scoped')
    source_root = Path(args.source_root).resolve() if args.source_root else ROOT
    if args.source_root and args.local:
        raise ValueError('--source-root is only supported for an explicit HTTP service')
    def snapshot():
        if not args.source_root:
            return source_snapshot()
        public, _ = compute_runtime_source(source_root)
        # An archived checkout need not have Git metadata. Record its actual
        # application bytes without inventing a commit or using the harness's
        # changing checkout as the server identity.
        return {'git_sha': None, 'dirty': None, 'runtime_source': public,
                'source_tree_sha256': public.get('manifest_sha256'),
                'source_scope': public['scope'], 'source_root': str(source_root)}
    def same_snapshot(first, second):
        if not args.source_root:
            return same_source(first, second)
        return bool(first.get('source_tree_sha256') and
                    first['source_tree_sha256'] == second.get('source_tree_sha256'))
    runtime, _ = compute_runtime_source(source_root)
    if runtime['status'] != 'ok':
        raise ValueError('Local source identity cannot be established')
    service = inspect_http_service(base_url) if base_url else None
    pipeline = (service['pipeline'] if service else active_pipeline()) if args.pipeline == 'auto' else args.pipeline
    if pipeline not in ('agent-tools', 'evidence-two-pass'):
        raise ValueError('Unsupported selected pipeline')
    def service_matches(observation):
        return (observation['runtime_sha256'] == runtime['manifest_sha256']
                and observation['pipeline'] == pipeline
                and observation.get('pipeline_version') == service.get('pipeline_version'))
    if service is not None and not service_matches(service):
        raise ValueError('HTTP service source or selected pipeline differs from this checkout')
    frozen = snapshot()
    check = preflight(rows, annotations, mode)
    check['reference_scope'] = 'visible_semantics'
    check['semantic_reference_records'] = [{
        'id': row['id'],
        'reviewed': bool(annotations.get(row['id'], {}).get('annotation_status') == 'reviewed'
                         and not annotations.get(row['id'], {}).get('ambiguities')
                         and annotations.get(row['id'], {}).get('sha256') == row['sha256'])}
        for row in rows]
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = {'schema_version': 3, 'mode': mode, 'pipeline_contract': pipeline,
        'started_at': utc_now(), 'check_only': args.check_only,
        'source_snapshot': frozen, 'runtime_source': runtime, 'http_service': service,
        'manifest_sha256': digest(Path(args.manifest).read_bytes()),
        'original_manifest_count': len(manifest.get('images', manifest.get('cases', manifest.get('entries', [])))),
        'selected_image_ids': [row['id'] for row in rows],
        'annotation_sources': [{'path': str(Path(p).resolve()), 'sha256': digest(Path(p).read_bytes())}
                               for group in args.annotations for p in group],
        'policy': {'document_attempts_per_image': 1, 'automatic_document_retry': False,
                   'select_best_result': False, 'provider_policy': 'selected_application_pipeline',
                   'first_response_immutable': True, 'maximum_concurrent_document_requests': args.jobs},
        'application_certified_passes': 0, 'frontend_rendering': 'not_run'}
    write_json(output/'run.json', metadata)
    write_json(output/'preflight.json', check)
    write_json(output/'references.json', {'evaluation_only': True,
        'production_lookup_forbidden': True, 'records': [annotations.get(row['id']) for row in rows]})
    if args.check_only:
        summary = {'status': check['status'], 'check_only': True, 'pipeline': pipeline,
                   'images_requested': len(rows), 'actual_document_requests': 0,
                   'api_calls': 0, 'application_certified_passes': 0}
        write_json(output/'summary.json', summary)
        print(json.dumps(summary))
        return 2 if check['status'] == 'blocked' else 0
    from threading import Lock
    state_lock = Lock()
    state = {'blocked': 'environment_preflight_blocked' if check['status'] == 'blocked' else None}
    def block(reason=None):
        with state_lock:
            if reason and state['blocked'] is None:
                state['blocked'] = reason
            return state['blocked']
    def capture_row(row):
        blocked = block()
        folder = output/row['id']
        folder.mkdir(mode=0o700)
        before = snapshot()
        if not same_snapshot(frozen, before):
            blocked = block('source_changed_after_first_run_freeze')
        raw = Path(row['path']).read_bytes()
        if digest(raw) != row['sha256']:
            blocked = block('original_changed_after_manifest_freeze')
        current_service = None
        if not blocked and base_url:
            try:
                current_service = inspect_http_service(base_url)
                if not service_matches(current_service):
                    blocked = block('http_source_or_pipeline_changed')
            except (OSError, ValueError, error.URLError):
                blocked = block('http_source_identity_unavailable')
        # Another in-flight request may have observed an identity/deadline
        # failure during these read-only preflight checks. Never start queued
        # uploads after that signal; already-dispatched first responses drain.
        blocked = blocked or block()
        if blocked:
            record = {'id': row['id'], 'capture_status': 'blocked', 'reason': blocked,
                      'actual_document_requests': 0, 'semantic_status': 'ungraded'}
            write_json(folder/'result.json', record)
            return record
        execution_id, started, clock = uuid.uuid4().hex, utc_now(), time.monotonic()
        write_json(folder/'request.json', {'request_id': execution_id, 'image_id': row['id'],
            'image_sha256': row['sha256'], 'original_path': row['path'],
            'request_started_at': started, 'pipeline': pipeline,
            'source_snapshot': before, 'http_service': current_service, 'document_attempt': 1})
        fd = os.open(folder/'runtime.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as log:
            try:
                if args.local:
                    # These redirects mutate process globals; local inference
                    # remains sequential. HTTP workers use independent openers
                    # and never redirect another worker's streams.
                    with redirect_stdout(log), redirect_stderr(log):
                        prediction, execution = local_recognition(raw, execution_id=execution_id, pipeline=pipeline)
                else:
                    prediction, execution = http_recognition(raw, base_url, row['id']+Path(row['path']).suffix,
                        args.timeout, execution_id=execution_id, pipeline=pipeline,
                        response_path=folder/'first-response.bin')
            except Exception as exc:
                prediction, execution = None, {'status': 'failed', 'exception_type': type(exc).__name__}
                log.write(json.dumps({'exception_type': type(exc).__name__})+'\n')
        if base_url and execution.get('http_status') is None:
            block('first_request_completion_unknown')
        after = snapshot()
        unchanged = same_snapshot(before, after)
        if not unchanged:
            block('source_changed_during_first_request')
        service_after, identity, pipeline_verified = None, None, None
        if base_url:
            try:
                service_after = inspect_http_service(base_url)
                identity = (service_matches(service_after)
                            and execution.get('runtime_sha256') == runtime['manifest_sha256'])
                pipeline_verified = (isinstance(prediction, dict)
                    and prediction.get('graph_display_version') == service.get('pipeline_version'))
            except (OSError, ValueError, error.URLError):
                identity = False
            if identity is not True:
                block('http_source_identity_changed_or_unavailable')
            elif pipeline_verified is not True:
                block('first_response_pipeline_mismatch')
        evidence = {**execution, 'mode': mode, 'pipeline_contract': pipeline,
            'execution_id': execution_id, 'image_sha256': row['sha256'],
            'document_requests': 1, 'request_started_at': started, 'request_finished_at': utc_now(),
            'source_snapshot': before, 'source_unchanged': unchanged,
            'http_service_before': current_service, 'http_service_after': service_after,
            'server_source_verified': identity, 'seconds': round(time.monotonic()-clock, 6),
            'response_pipeline_verified': pipeline_verified,
            'prediction_sha256': prediction_digest(prediction),
            'model_send_verification': 'server_reported_unverified' if base_url else execution.get('model_send_verification', 'observed_transport')}
        write_json(folder/'response.json', {'prediction': prediction, 'execution_evidence': evidence})
        semantic = evaluate_visible_semantics(annotations.get(row['id']), prediction, image_sha256=row['sha256'])
        captured = (execution.get('status') == 'completed' and isinstance(prediction, dict) and unchanged
                    and (not base_url or (identity is True and pipeline_verified is True and execution.get('http_status') == 200)))
        record = {'id': row['id'], 'actual_document_requests': 1,
            'capture_status': 'captured' if captured else 'fail', 'seconds': evidence['seconds'],
            'http_status': execution.get('http_status'),
            'recognition_status': prediction.get('recognition_status') if isinstance(prediction, dict) else None,
            'semantic_status': semantic['status'], 'semantic_assessment': semantic,
            'source_unchanged': unchanged, 'server_source_verified': identity,
            'response_pipeline_verified': pipeline_verified,
            'application_certified_passes': 0, 'frontend_rendering': 'not_run'}
        write_json(folder/'result.json', record)
        if not unchanged:
            block('source_changed_during_first_request')
        elif base_url and identity is not True:
            block('http_source_identity_changed_or_unavailable')
        elif base_url and execution.get('http_status') is None:
            # No HTTP response establishes completion. Stop instead of stacking
            # more work or retrying an image whose first request may still run.
            block('first_request_completion_unknown')
        elif base_url and pipeline_verified is not True:
            block('first_response_pipeline_mismatch')
        with state_lock:
            print(json.dumps({k: record[k] for k in ('id', 'capture_status', 'recognition_status', 'semantic_status', 'seconds')}), flush=True)
        return record
    records = [None] * len(rows)
    if args.jobs == 1:
        for index, row in enumerate(rows):
            records[index] = capture_row(row)
    else:
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
        # Submit only the selected bounded batch, not the entire corpus. Each request
        # owns its opener, request ID, exact response file and per-image folder.
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            pending, next_index = {}, 0
            while next_index < len(rows) or pending:
                while next_index < len(rows) and len(pending) < args.jobs and not block():
                    future = executor.submit(capture_row, rows[next_index])
                    pending[future] = next_index
                    next_index += 1
                if not pending:
                    break
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    index = pending.pop(future)
                    records[index] = future.result()
            # A critical failure blocks only unsent images. Preserve any other
            # request that was already in flight and never retry either one.
            for index in range(next_index, len(rows)):
                records[index] = capture_row(rows[index])
    summary = {'schema_version': 3, 'finished_at': utc_now(), 'pipeline': pipeline,
        'status': 'captured' if all(r['capture_status'] == 'captured' and r['semantic_status'] != 'fail' for r in records) else 'fail',
        'scope': 'first_document_response_and_independent_visible_semantics',
        'maximum_concurrent_document_requests': args.jobs,
        'images_requested': len(rows), 'actual_document_requests': sum(r['actual_document_requests'] for r in records),
        'full_corpus_selected': len(rows) == metadata['original_manifest_count'],
        'recognition_status_counts': dict(Counter(str(r.get('recognition_status')) for r in records)),
        'semantic_status_counts': dict(Counter(r['semantic_status'] for r in records)),
        'application_certified_passes': 0, 'frontend_rendering': 'not_run', 'results': records}
    write_json(output/'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}), flush=True)
    return 0 if summary['status'] == 'captured' else 2


def evaluate_frozen_capture(args, rows, annotations, output):
    """Add a separate evaluation, never rewrite/re-upload a first response."""
    run = Path(args.evaluate_run).resolve()
    metadata = json.loads((run/'run.json').read_text())
    if metadata.get('schema_version') != 3 or metadata.get('check_only'):
        raise ValueError('Expected a completed selected-pipeline capture, not a preflight')
    if metadata.get('manifest_sha256') != digest(Path(args.manifest).read_bytes()):
        raise ValueError('Manifest differs from the frozen capture')
    if metadata.get('policy', {}).get('document_attempts_per_image') != 1:
        raise ValueError('First-document policy is unavailable')
    selected = set(metadata['selected_image_ids'])
    rows = [row for row in rows if row['id'] in selected]
    if not rows or (not args.ids and {row['id'] for row in rows} != selected):
        raise ValueError('Frozen capture image inventory is incomplete')
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    evaluator_sha = digest(Path(__file__).read_bytes())
    write_json(output/'evaluation.json', {'source_run': str(run),
        'source_run_sha256': digest((run/'run.json').read_bytes()),
        'evaluator_sha256': evaluator_sha, 'started_at': utc_now(),
        'annotation_sources': [{'path': str(Path(p).resolve()), 'sha256': digest(Path(p).read_bytes())}
                               for group in args.annotations for p in group],
        'actual_document_requests': 0, 'model_calls': 0})
    results = []
    for row in rows:
        issues, prediction = [], None
        try:
            request_record = json.loads((run/row['id']/'request.json').read_text())
            response = json.loads((run/row['id']/'response.json').read_text())
            evidence, prediction = response['execution_evidence'], response['prediction']
            if (evidence.get('document_requests') != 1 or request_record.get('document_attempt') != 1
                    or request_record.get('request_id') != evidence.get('execution_id')
                    or request_record.get('image_sha256') != row['sha256']
                    or evidence.get('image_sha256') != row['sha256']
                    or evidence.get('prediction_sha256') != prediction_digest(prediction)):
                issues.append('first_response_binding_mismatch')
            if metadata.get('mode') == 'http':
                raw = (run/row['id']/'first-response.bin').read_bytes()
                if (digest(raw) != evidence.get('raw_response_sha256')
                        or json.loads(raw) != prediction):
                    issues.append('first_http_bytes_mismatch')
                if evidence.get('server_source_verified') is not True:
                    issues.append('server_source_unverified')
                before, after = evidence.get('http_service_before') or {}, evidence.get('http_service_after') or {}
                if (not before.get('pipeline_version') or before.get('pipeline_version') != after.get('pipeline_version')
                        or not isinstance(prediction, dict)
                        or prediction.get('graph_display_version') != before.get('pipeline_version')
                        or before.get('pipeline') != metadata.get('pipeline_contract')
                        or before.get('pipeline') != after.get('pipeline')):
                    issues.append('response_pipeline_version_mismatch')
            if evidence.get('source_unchanged') is not True:
                issues.append('source_changed_during_capture')
        except (OSError, ValueError, TypeError, KeyError):
            issues.append('first_response_missing_or_invalid')
        assessment = evaluate_visible_semantics(annotations.get(row['id']), prediction, image_sha256=row['sha256'])
        result = {'id': row['id'], 'capture_integrity': 'fail' if issues else 'verified',
                  'integrity_issues': issues, 'semantic_assessment': assessment,
                  'semantic_status': assessment['status'], 'actual_document_requests': 0}
        results.append(result)
        write_json(output/(row['id']+'.json'), result)
    if digest(Path(__file__).read_bytes()) != evaluator_sha:
        raise ValueError('Evaluator changed while scoring frozen responses')
    summary = {'status': 'fail' if any(r['integrity_issues'] or r['semantic_status'] == 'fail' for r in results) else 'scored',
        'scope': 'independently_annotated_visible_semantics', 'images_evaluated': len(results),
        'semantic_status_counts': dict(Counter(r['semantic_status'] for r in results)),
        'text_status_counts': dict(Counter(r['semantic_assessment']['text_status'] for r in results)),
        'graphs_status_counts': dict(Counter(r['semantic_assessment']['graphs_status'] for r in results)),
        'recognition_status_counts': dict(Counter(str(r['semantic_assessment']['recognition_status']) for r in results)),
        'capture_integrity_counts': dict(Counter(r['capture_integrity'] for r in results)),
        'actual_document_requests': 0, 'model_calls': 0, 'application_certified_passes': 0,
        'results': results}
    write_json(output/'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}))
    return 0 if summary['status'] == 'scored' else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--annotations', action='append', nargs='+', default=[],
                        help='Independent reference files; omitted originals are captured but ungraded')
    parser.add_argument('--output', required=True, help='New private result directory outside the repository')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--local', action='store_true')
    mode.add_argument('--base-url')
    mode.add_argument('--evaluate-run', help='Score a frozen selected-pipeline run offline; never sends another OCR request')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--ids', nargs='+', help='Explicit subset; results never claim full-corpus acceptance')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--jobs', type=int, choices=(1, 2, 3, 4), default=1,
                        help='Maximum concurrent first HTTP uploads (1–4); concurrency requires --pipeline and --base-url')
    parser.add_argument('--pipeline', choices=('auto', 'agent-tools', 'evidence-two-pass'),
                        help='Select the actual engine; auto observes HTTP health or the local configured default. Omit for the legacy two-pass evaluator.')
    parser.add_argument('--source-root', help='Frozen application source directory served by --base-url; verified against /health, independent of this harness checkout')
    args = parser.parse_args(argv)
    if args.jobs != 1 and (not args.pipeline or not args.base_url):
        parser.error('Concurrent jobs require --pipeline and --base-url')
    output = Path(args.output).resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error('--output must remain outside the repository')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('--output must be new or empty; first results cannot be replaced')
    if not 1 <= args.timeout <= 1800:
        parser.error('--timeout must be between 1 and 1800 seconds')
    try:
        base_url = validate_base_url(args.base_url) if args.base_url else None
        manifest, rows = load_manifest(args.manifest)
        annotations = load_annotations([p for group in args.annotations for p in group])
        if args.ids:
            requested = set(args.ids)
            if not requested <= {row['id'] for row in rows}:
                raise ValueError('Requested image IDs missing from manifest')
            rows = [row for row in rows if row['id'] in requested]
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.evaluate_run:
        try:
            return evaluate_frozen_capture(args, rows, annotations, output)
        except (OSError, ValueError, KeyError) as exc:
            parser.error(str(exc))
    if args.pipeline:
        try:
            return run_selected_pipeline(args, manifest, rows, annotations, output, base_url)
        except (OSError, ValueError, error.URLError) as exc:
            parser.error(str(exc))
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(output, 0o700)
    execution_mode = 'local' if args.local else 'http'
    check = preflight(rows, annotations, execution_mode)
    source = source_snapshot()
    manifest_path = Path(args.manifest).resolve()
    metadata = {'schema_version': 2, **evaluation_scope(execution_mode),
                'started_at': utc_now(), 'mode': execution_mode,
                'check_only': args.check_only, 'base_url': base_url,
                'manifest_sha256': digest(manifest_path.read_bytes()),
                'annotation_sources': [{'path': str(Path(p).resolve()), 'sha256': digest(Path(p).read_bytes())}
                                       for group in args.annotations for p in group],
                'original_manifest_count': len(manifest.get('images', manifest.get('cases', manifest.get('entries', [])))),
                'selected_image_ids': [row['id'] for row in rows], 'source_snapshot': source,
                'frontend_rendering': 'not_run', 'frontend_contract': 'original_preview_and_text_cards',
                'policy': {'document_attempts_per_image': 1, 'pipeline_contract': 'evidence-two-pass',
                           'successful_qwen_sends_for_complete_certificate': 2,
                           'qwen_call_limit': 2, 'text_correction_ledger': 'separate',
                           'automatic_retry': False, 'select_best_result': False}}
    write_json(output/'run.json', metadata)
    write_json(output/'preflight.json', check)
    write_json(output/'references.json', {'evaluation_only': True, 'production_lookup_forbidden': True,
                                       'records': [annotations.get(row['id']) for row in rows]})
    if args.check_only:
        write_json(output/'summary.json', {**summarize_assessments([], execution_mode),
                                         'status': check['status'], 'check_only': True, 'images_requested': len(rows),
                                         'actual_document_requests': 0, 'certified_passes': 0,
                                         'frontend_rendering': 'not_run', 'reference_ready_count': check['reference_ready_count'],
                                         'reference_scope': 'graph_structure',
                                         'reference_text_ready_count': check['reference_text_ready_count'],
                                         'full_reference_ready_count': check['full_reference_ready_count']})
        print(json.dumps({'status': check['status'], 'check_only': True, 'images': len(rows),
                          'reference_ready': check['reference_ready_count'],
                          'full_reference_ready': check['full_reference_ready_count'], 'api_calls': 0}, ensure_ascii=False))
        return 2 if check['status'] == 'blocked' else 0
    results = []
    blocked_reason = 'environment_preflight_blocked' if check['status'] == 'blocked' else None
    for row in rows:
        case = output/row['id']
        case.mkdir(mode=0o700)
        if blocked_reason:
            record = {**evaluation_scope(execution_mode), 'id': row['id'], 'status': 'blocked', 'reason': blocked_reason, 'actual_document_requests': 0,
                      'frontend_rendering': 'not_run', 'structure_status': 'not_certified'}
            write_json(case/'result.json', record)
            results.append(record)
            continue
        before = source_snapshot()
        if not same_source(source, before):
            blocked_reason = 'source_changed_after_run_freeze'
            record = {**evaluation_scope(execution_mode), 'id': row['id'], 'status': 'blocked', 'reason': blocked_reason,
                      'actual_document_requests': 0, 'structure_status': 'not_certified'}
            write_json(case/'result.json', record)
            results.append(record)
            continue
        raw = Path(row['path']).read_bytes()
        if digest(raw) != row['sha256']:
            blocked_reason = 'original_changed_after_preflight'
            record = {**evaluation_scope(execution_mode), 'id': row['id'], 'status': 'blocked', 'reason': blocked_reason,
                      'actual_document_requests': 0, 'structure_status': 'not_certified'}
            write_json(case/'result.json', record)
            results.append(record)
            continue
        start, started, execution_id = time.monotonic(), utc_now(), uuid.uuid4().hex
        # Runtime logs may contain model text. They belong only in private files.
        logfd = os.open(case/'runtime.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(logfd, 'w', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
            try:
                if args.local:
                    prediction, execution = local_recognition(raw, execution_id=execution_id)
                else:
                    prediction, execution = http_recognition(raw, base_url, row['id']+Path(row['path']).suffix,
                                                            args.timeout, execution_id=execution_id)
            except Exception as exc:
                prediction, execution = None, {'status': 'failed', 'exception_type': type(exc).__name__, 'model_attempts': []}
        after = source_snapshot()
        evidence = {**execution, **evaluation_scope(execution_mode, http_status=execution.get('http_status')),
                    'mode': execution_mode, 'document_requests': 1, 'is_live': True,
                    'execution_id': execution_id, 'pipeline_contract': 'evidence-two-pass',
                    'image_sha256': row['sha256'], 'request_started_at': started, 'request_finished_at': utc_now(),
                    'prediction_sha256': prediction_digest(prediction),
                    'source_snapshot': {k: before[k] for k in ('git_sha', 'dirty', 'source_tree_sha256')},
                    'source_unchanged': same_source(before, after), 'seconds': round(time.monotonic()-start, 6)}
        if args.base_url and execution.get('server_reported_source'):
            reported = execution['server_reported_source']
            evidence['server_source_verified'] = isinstance(reported, dict) and same_source(before, reported)
        write_json(case/'response.json', {'prediction': prediction, 'execution_evidence': evidence})
        gold = annotations.get(row['id'])
        if gold and gold.get('sha256') != row['sha256']:
            gold = None
        assessment = evaluate_prediction(gold, prediction, run_evidence=evidence,
                                         frontend_evidence={'status': 'not_run'})
        assessment.update(id=row['id'], actual_document_requests=1,
                          execution_status=execution['status'], response_file=str(case/'response.json'))
        if execution['status'] == 'blocked':
            assessment['status'] = 'blocked'
        write_json(case/'result.json', assessment)
        results.append(assessment)
        print(json.dumps({'id': row['id'], 'status': assessment['status'],
                          'structure_status': assessment['structure_status'],
                          'pipeline_status': assessment['pipeline_status'],
                          'application_status': assessment['application_status'],
                          'seconds': evidence['seconds']}, ensure_ascii=False), flush=True)
        if not evidence['source_unchanged']:
            blocked_reason = 'source_changed_during_request'
    summary = {**summarize_assessments(results, execution_mode),
               'finished_at': utc_now(), 'images_requested': len(rows),
               'actual_document_requests': sum(r.get('actual_document_requests', 0) for r in results),
               'full_corpus_selected': len(rows) == metadata['original_manifest_count'],
               'frontend_rendering': 'not_run', 'results': [{k: r.get(k) for k in
                   ('id', 'status', 'structure_status', 'pipeline_status', 'frontend_status', 'pipeline_ui_status', 'application_status')}
                   for r in results]}
    write_json(output/'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('status', 'certification_scope', 'application_status',
        'images_requested', 'actual_document_requests', 'status_counts', 'pipeline_passes', 'pipeline_ui_passes',
        'certified_passes', 'application_certified_passes')}, ensure_ascii=False))
    return 0 if summary['status'] == 'pass' else 2


if __name__ == '__main__':
    raise SystemExit(main())
