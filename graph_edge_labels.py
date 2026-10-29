"""Keep a numeric weight separate from an independently printed edge name."""
from __future__ import annotations

import math
import re
import unicodedata
from fractions import Fraction

_DECIMAL = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?'
_NUMBER = re.compile(r'(?:' + _DECIMAL + r'|[+-]?\d+/[+-]?\d+)\Z')


def numeric_annotation(value):
    """Only literal decimal/fraction equality, never evaluate a formula."""
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, float) and not math.isfinite(value):
        return None
    raw = str(value)
    # Circled indexes are distinct printed names, not ordinary weight text.
    if any(character in '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳' for character in raw):
        return None
    text = unicodedata.normalize('NFKC', raw).strip().replace('−', '-').replace('⁄', '/')
    if len(text) > 256:
        return None
    latex = re.fullmatch(r'\\(?:d?frac)\{([+-]?\d+)\}\{([+-]?\d+)\}', text)
    if latex:
        text = latex[1] + '/' + latex[2]
    text = re.sub(r'\s*/\s*', '/', text)
    if not _NUMBER.fullmatch(text):
        return None
    exponent = re.search(r'[eE]([+-]?\d+)', text)
    if exponent and abs(int(exponent[1])) > 308:
        return None
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def separate_weight_and_edge_label(edge, *, weighted=False):
    """Remove only an unsupported duplicate; never invent or move a weight.

    Real independently printed numeric names may match a weight, but they
    need the explicit visual distinction recorded by the recognizer/user.
    """
    if edge.get('edge_label_is_explicit') is True or not (weighted is True or edge.get('weight') is not None):
        return False
    label, weight = numeric_annotation(edge.get('edge_label')), numeric_annotation(edge.get('weight'))
    if label is None or weight is None or label != weight:
        return False
    edge['edge_label'] = None
    return True


def separate_graph_edge_labels(graph):
    """Normalize a graph in place and return an audit of changed names only."""
    changes = []
    for edge in graph.get('edges', []):
        previous = edge.get('edge_label')
        if separate_weight_and_edge_label(edge, weighted=graph.get('weighted')):
            changes.append({'kind': 'duplicate_weight_edge_label_removed',
                            'edge_id': edge.get('id'), 'previous_edge_label': previous})
    return changes
