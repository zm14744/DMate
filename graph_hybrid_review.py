"""Explicit, bounded review routing experiment; never selected by environment.

Replace at most one existing Qwen REVIEW slot. NODE/EDGE, TRACE/RELATE and
subsequent reviews stay on the caller's original pipeline. No extra call or
automatic cross-provider retry is added on failure.
"""
from __future__ import annotations
from collections import Counter
import time

PROFILE = 'qwen-glm-review-v1'


class _ReviewBudget:
    def __init__(self, parent, seconds):
        self.parent = parent
        self.deadline = min(parent.deadline, time.monotonic() + seconds)
        self.metrics = parent.metrics

    def take(self):
        remaining = self.deadline - time.monotonic()
        if remaining < 3:
            raise TimeoutError('hybrid_review_budget')
        return min(self.parent.take(), remaining)


class HybridReview:
    def __init__(self, provider, *, seconds=25, candidate_limit=24):
        if (getattr(provider, 'name', None) != 'glm'
                or getattr(provider, 'model', None) != 'glm-4.6v'
                or getattr(provider, 'thinking', None) is not False
                or getattr(provider, 'retries', None) != 0):
            raise ValueError('Hybrid experiment requires paid GLM, thinking off, no retries')
        if not 3 <= seconds <= 45 or not 1 <= candidate_limit <= 48:
            raise ValueError('Invalid hybrid review budget')
        self.provider = provider
        self.seconds = seconds
        self.candidate_limit = candidate_limit
        self.used = False
        self.events = []

    def select(self, jobs, related, budget):
        """Use only inference uncertainty, never image identity or reference data."""
        if self.used:
            return False
        count = sum(len(j.get('candidates', [])) for j in jobs)
        if not count or count > self.candidate_limit:
            self.events.append({'routed': False, 'reason': 'candidate_budget', 'candidates': count})
            return False
        if budget.remaining < 1 or budget.deadline - time.monotonic() < 8:
            self.events.append({'routed': False, 'reason': 'remaining_budget'})
            return False
        reasons = set()
        by_id = {g['id']: g for g in related}
        for job in jobs:
            candidates = job.get('candidates', [])
            sources = {item.get('source') for e in candidates
                       for item in e.get('evidence', []) if isinstance(item, dict)}
            pairs = Counter(tuple(sorted((e['from'], e['to']))) for e in candidates)
            if job.get('directed') is not False and (
                    any(e.get('direction') == 'unknown' for e in candidates)
                    or sources & {'direction_conflict', 'arrow_pixels', 'graph_direction_conflict'}):
                reasons.add('arrow_uncertainty')
            if job.get('multigraph') is True or any(n > 1 for n in pairs.values()):
                reasons.add('parallel_routes')
            if job.get('weighted') is True and (
                    any(e.get('weight') is None for e in candidates) or 'attribute_conflict' in sources):
                reasons.add('weight_uncertainty')
            graph = by_id.get(job.get('graph_id'), {})
            if any(a.get('conflicts') or a.get('blocked_by_vertex')
                   for a in graph.get('relation_audit', [])):
                reasons.add('route_conflicts')
        if not reasons:
            self.events.append({'routed': False, 'reason': 'no_targeted_uncertainty', 'candidates': count})
            return False
        self.used = True
        self.events.append({'routed': True, 'reasons': sorted(reasons), 'candidates': count,
                            'graph_ids': [j['graph_id'] for j in jobs], 'seconds_cap': self.seconds})
        return True

    def __call__(self, prompt, images, budget):
        from graph_glm_adapter import STABLE_REVIEW_HINT
        return self.provider(prompt + STABLE_REVIEW_HINT, images,
                             _ReviewBudget(budget, self.seconds))
