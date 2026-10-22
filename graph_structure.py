"""Shared bounded representation of graph geometry evidence.

Pixel traces are hypotheses and MUST NOT be inserted as confirmed graph edges.
This module has no model-provider dependencies.
"""
from __future__ import annotations

import json


def compact_line_evidence(cv_result, *, max_graphs=8, max_per_graph=18, max_chars=3000):
    """Compact candidate path traces for an existing Qwen multimodal request."""
    if not isinstance(cv_result, dict):
        return []
    output = []
    for panel in (cv_result.get('line_path_evidence') or [])[:max_graphs]:
        if not isinstance(panel, dict):
            continue
        paths = []
        for trace in (panel.get('paths') or [])[:max_per_graph]:
            if not isinstance(trace, dict):
                continue
            a, b = trace.get('from'), trace.get('to')
            if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
                continue
            path = trace.get('path') or []
            try:
                score = round(float(trace.get('score', 0)), 3)
            except (TypeError, ValueError):
                continue
            paths.append({
                'from': a, 'to': b, 'score': score,
                'path_samples': path[::max(1, len(path) // 5)][:6],
                'candidate_only': True,
            })
        if not paths:
            continue
        item = {'id': str(panel.get('id') or ''), 'paths': paths}
        candidate = output + [item]
        if len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
            break
        output = candidate
    return output


__all__ = ['compact_line_evidence']
