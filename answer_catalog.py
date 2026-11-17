"""Separate private catalog judgments from an answer's public text.

This module only handles the transport envelope. Canonical topic IDs, source
quotes and mathematical scope are validated at the final response boundary.
"""

import json


CATALOG_GRAPH_OPEN = "[[DMATE_CATALOG_GRAPH]]"
CATALOG_GRAPH_CLOSE = "[[/DMATE_CATALOG_GRAPH]]"
_PRIVATE_STEM = CATALOG_GRAPH_OPEN[:-2]
_MAX_GRAPH_BYTES = 128 * 1024


def _pending_prefix_length(text):
    for size in range(min(len(text), len(_PRIVATE_STEM) - 1), 0, -1):
        if text.endswith(_PRIVATE_STEM[:size]):
            return size
    return 0


def _public_prefix(text):
    # An unfinished reserved marker is private too. A single ordinary Markdown
    # bracket is not enough to identify the machine envelope.
    size = _pending_prefix_length(text)
    return text[:-size] if size >= 2 else text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_catalog_property")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non_json_catalog_constant")


def split_catalog_answer(text):
    """Return public text and a bounded, syntactically valid raw graph.

    Once a reserved opening stem appears, everything after it stays private,
    even when the model omits a bracket, closing marker or valid JSON. Extra
    text or a second block makes the metadata invalid rather than exposing it.
    """
    if not isinstance(text, str):
        return "", None
    position = text.find(_PRIVATE_STEM)
    if position < 0:
        return _public_prefix(text), None
    public = text[:position].rstrip()
    if not text.startswith(CATALOG_GRAPH_OPEN, position):
        return public, None
    body_start = position + len(CATALOG_GRAPH_OPEN)
    closing = text.find(CATALOG_GRAPH_CLOSE, body_start)
    if closing < 0 or text[closing + len(CATALOG_GRAPH_CLOSE):].strip():
        return public, None
    body = text[body_start:closing].strip()
    if not body or len(body) > _MAX_GRAPH_BYTES:
        return public, None
    try:
        if len(body.encode("utf-8")) > _MAX_GRAPH_BYTES:
            return public, None
        raw = json.loads(body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return public, None
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list) \
            or not isinstance(raw.get("edges"), list) \
            or not isinstance(raw.get("unresolved", ""), str):
        return public, None
    return public, {"nodes": raw["nodes"], "edges": raw["edges"],
                    "unresolved": raw.get("unresolved", "")}


class CatalogAnswerDeltaFilter:
    """Publish answer deltas without retaining or exposing private metadata.

    Only a possible opening-prefix tail is buffered. Once the private stem is
    recognized, later input is discarded regardless of JSON validity or size.
    """

    def __init__(self, callback):
        self._callback = callback
        self._pending = ""
        self._private = False
        self._finished = False

    def feed(self, piece):
        if self._finished or self._private or not isinstance(piece, str) or not piece:
            return
        text = self._pending + piece
        position = text.find(_PRIVATE_STEM)
        if position >= 0:
            public = text[:position]
            self._pending = ""
            self._private = True
        else:
            size = _pending_prefix_length(text)
            public = text[:-size] if size else text
            self._pending = text[-size:] if size else ""
        if public:
            self._callback(public)

    def finish(self):
        if self._finished:
            return
        self._finished = True
        public = _public_prefix(self._pending)
        self._pending = ""
        if public and not self._private:
            self._callback(public)
