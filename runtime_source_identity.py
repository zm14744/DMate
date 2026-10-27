"""A read-only byte identity for the application source loaded at startup.

This is a source snapshot, not a claim about Git history, installed packages,
model weights, runtime mutation or recognition accuracy. Generated icons,
root uploads, credentials, environment values and root caches are excluded.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = 'dmate.runtime-source/1'
SCOPE = 'python_knowledge_web_sources_and_dependency_specs'
TEXT_SUFFIXES = frozenset(('.js', '.css', '.html', '.htm', '.json', '.xml', '.txt'))
TEMPLATE_SUFFIXES = TEXT_SUFFIXES | frozenset(('.jinja', '.jinja2', '.j2'))
REQUIRED = ('app.py', 'runtime_source_identity.py', 'knowledge_graph.json',
            'requirements.txt', 'requirements-agents.txt',
            'static/script.js', 'templates/index.html')


def _source_paths(root):
    selected = set(REQUIRED)
    selected.update(path.name for path in root.glob('*.py'))
    for name, suffixes in (('static', TEXT_SUFFIXES), ('templates', TEMPLATE_SUFFIXES)):
        base = root / name
        if base.is_symlink() or not base.is_dir():
            raise ValueError('invalid_web_source_directory')
        pending = [base]
        while pending:
            for path in pending.pop().iterdir():
                if path.name.startswith('.') or (name == 'static' and path == base / 'icons'):
                    continue
                if path.is_symlink():
                    raise ValueError('symlink_in_source_inventory')
                if path.is_dir():
                    pending.append(path)
                elif path.suffix.lower() in suffixes:
                    selected.add(path.relative_to(root).as_posix())
    return sorted(selected)


def compute_runtime_source(root):
    """Return (public summary, canonical private manifest), without writes."""
    public = {'schema': SCHEMA, 'algorithm': 'sha256', 'scope': SCOPE,
              'snapshot': 'process_start', 'status': 'unavailable',
              'manifest_sha256': None, 'file_count': 0}
    try:
        root = Path(root).resolve(strict=True)
        rows = []
        for relative in _source_paths(root):
            path = root / relative
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                raise ValueError('invalid_source_file')
            raw = path.read_bytes()
            rows.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        manifest = {'schema': SCHEMA, 'files': rows}
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        public.update(status='ok', manifest_sha256=hashlib.sha256(encoded).hexdigest(),
                      file_count=len(rows))
        return public, manifest
    except (OSError, ValueError):
        # Public health must never leak a filesystem path or prevent startup.
        return public, None


def configured_recognition_budget():
    """Expose bounded settings, without constructing a provider or using keys."""
    from graph_pipeline_version import active_pipeline
    if active_pipeline() == 'agent-tools':
        from graph_fast_pipeline import configured_fast_budget, PERFORMANCE_TARGET_SECONDS
        budget = configured_fast_budget()
        return {'seconds': round(budget.deadline-budget.started),
                'performance_target_seconds': PERFORMANCE_TARGET_SECONDS,
                'total_remote_calls': budget.initial_calls, 'per_call_seconds': budget.call_seconds,
                'remote_concurrency': 1, 'max_concurrent_images': 4,
                'network_recoveries': budget.max_network_recoveries,
                'json_recoveries': budget.max_json_format_recoveries,
                'recoveries_share_total_budget': True}
    from graph_agent_runtime import AgentBudget
    budget = AgentBudget.configured()
    return {'seconds': round(budget.deadline-budget.started),
            'total_remote_calls': budget.initial_calls, 'per_call_seconds': budget.call_seconds,
            'remote_concurrency': 2, 'network_recoveries': budget.max_network_recoveries,
            'json_recoveries': budget.max_json_format_recoveries,
            'recoveries_share_total_budget': True}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    public, manifest = compute_runtime_source(args.root)
    print(json.dumps({'runtime_source': public, 'manifest': manifest}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if public['status'] == 'ok' else 2)
