"""Run each private original exactly once; never retry or select a best result.

Example (no model/API calls):
  python scripts/benchmark_graph_first_pass.py --manifest /private/manifest.json \
    --annotations /private/slides.json /private/other.json --local \
    --check-only --output /private/preflight-unique

Artifacts include private original responses and must remain outside the repo.
No gold data is passed into any recognition function, prompt, or model call.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graph_first_pass_eval import evaluate_prediction, load_annotations, prediction_digest, reference_issues, reference_text_issues


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
    entries = manifest.get('images', manifest.get('cases'))
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
    missing = [name for name in ('PIL', 'requests', 'cv2', 'networkx') if not dependencies[name]]
    blocked = mode == 'local' and (not credentials['qwen_key_present'] or bool(missing))
    return {'status': 'blocked' if blocked else 'ready', 'mode': mode, 'credentials': credentials,
            'dependencies': dependencies, 'blocking_dependencies': missing if mode == 'local' else [],
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


def local_recognition(raw, *, execution_id=None):
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


def http_recognition(raw, base_url, filename, timeout, *, execution_id=None):
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
    meta = {'status': 'completed', 'model_attempts': [], 'text_model_attempts': [], 'transport_attempts': [],
            'execution_id': execution_id, 'pipeline_contract': 'evidence-two-pass', 'server_source_verified': False}
    content = b''
    try:
        with opener.open(req, timeout=timeout) as response:
            meta['http_status'] = response.status
            content = response.read(32*1024*1024+1)
    except error.HTTPError as exc:
        meta.update(status='failed', http_status=exc.code)
        content = exc.read(32*1024*1024+1)
    except (OSError, error.URLError, TimeoutError) as exc:
        meta.update(status='failed', exception_type=type(exc).__name__)
    meta['raw_response_body'] = content.decode('utf-8', errors='replace')
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--annotations', action='append', nargs='+', required=True)
    parser.add_argument('--output', required=True, help='New private result directory outside the repository')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--local', action='store_true')
    mode.add_argument('--base-url')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--ids', nargs='+', help='Explicit subset; results never claim full-corpus acceptance')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args(argv)
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
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(output, 0o700)
    execution_mode = 'local' if args.local else 'http'
    check = preflight(rows, annotations, execution_mode)
    source = source_snapshot()
    manifest_path = Path(args.manifest).resolve()
    metadata = {'schema_version': 1, 'started_at': utc_now(), 'mode': execution_mode,
                'check_only': args.check_only, 'base_url': base_url,
                'manifest_sha256': digest(manifest_path.read_bytes()),
                'annotation_sources': [{'path': str(Path(p).resolve()), 'sha256': digest(Path(p).read_bytes())}
                                       for group in args.annotations for p in group],
                'original_manifest_count': len(manifest.get('images', manifest.get('cases', []))),
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
        write_json(output/'summary.json', {'status': check['status'], 'check_only': True, 'images_requested': len(rows),
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
            record = {'id': row['id'], 'status': 'blocked', 'reason': blocked_reason, 'actual_document_requests': 0,
                      'frontend_rendering': 'not_run', 'structure_status': 'not_certified'}
            write_json(case/'result.json', record)
            results.append(record)
            continue
        before = source_snapshot()
        if not same_source(source, before):
            blocked_reason = 'source_changed_after_run_freeze'
            record = {'id': row['id'], 'status': 'blocked', 'reason': blocked_reason,
                      'actual_document_requests': 0, 'structure_status': 'not_certified'}
            write_json(case/'result.json', record)
            results.append(record)
            continue
        raw = Path(row['path']).read_bytes()
        if digest(raw) != row['sha256']:
            blocked_reason = 'original_changed_after_preflight'
            record = {'id': row['id'], 'status': 'blocked', 'reason': blocked_reason,
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
        evidence = {**execution, 'mode': execution_mode, 'document_requests': 1, 'is_live': True,
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
                          'seconds': evidence['seconds']}, ensure_ascii=False), flush=True)
        if not evidence['source_unchanged']:
            blocked_reason = 'source_changed_during_request'
    counts = Counter(r['status'] for r in results)
    summary = {'status': 'pass' if counts.get('pass', 0) == len(rows) else 'incomplete',
               'finished_at': utc_now(), 'images_requested': len(rows),
               'actual_document_requests': sum(r.get('actual_document_requests', 0) for r in results),
               'status_counts': dict(counts), 'certified_passes': counts.get('pass', 0),
               'structure_passes': sum(r.get('structure_status') == 'pass' for r in results),
               'full_corpus_selected': len(rows) == metadata['original_manifest_count'],
               'frontend_rendering': 'not_run', 'results': [{k: r.get(k) for k in ('id', 'status', 'structure_status')} for r in results]}
    write_json(output/'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('status', 'images_requested', 'actual_document_requests', 'status_counts', 'certified_passes')}, ensure_ascii=False))
    return 0 if summary['status'] == 'pass' else 2


if __name__ == '__main__':
    raise SystemExit(main())
