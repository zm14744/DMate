"""Offline tests for the private answer-catalog transport envelope."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from answer_catalog import (
    CATALOG_GRAPH_CLOSE,
    CATALOG_GRAPH_OPEN,
    CatalogAnswerDeltaFilter,
    split_catalog_answer,
)


GRAPH = {"nodes": [{"id": "set_operation", "usage": "assessed",
                    "reason": "原题要求计算集合交集",
                    "evidence": [{"source": "question", "quote": "求交集"}]}],
         "edges": [], "unresolved": ""}
PUBLIC = "交集为 $A\\cap B=\\{2\\}$\n"
BODY = json.dumps(GRAPH, ensure_ascii=False)
WIRE = PUBLIC + CATALOG_GRAPH_OPEN + BODY + CATALOG_GRAPH_CLOSE


def streamed(pieces):
    output = []
    filter_ = CatalogAnswerDeltaFilter(output.append)
    for piece in pieces:
        filter_.feed(piece)
    filter_.finish()
    filter_.finish()
    return "".join(output), filter_


class AnswerCatalogCodecTests(unittest.TestCase):
    def test_complete_envelope_separates_public_text_and_raw_graph(self):
        text, graph = split_catalog_answer(WIRE)
        self.assertEqual(text, PUBLIC.rstrip())
        self.assertEqual(graph, GRAPH)
        extra = {**GRAPH, "sources": {"question": "caller-claimed source"}}
        _, graph = split_catalog_answer(CATALOG_GRAPH_OPEN + json.dumps(extra) + CATALOG_GRAPH_CLOSE)
        self.assertEqual(graph, GRAPH, "transport metadata cannot install claimed source fields")

    def test_all_chunk_boundaries_and_character_deltas_hide_private_suffix(self):
        for boundary in range(len(WIRE) + 1):
            with self.subTest(boundary=boundary):
                actual, _ = streamed([WIRE[:boundary], WIRE[boundary:]])
                self.assertEqual(actual, PUBLIC)
        actual, _ = streamed(list(WIRE))
        self.assertEqual(actual, PUBLIC)

    def test_ordinary_markdown_math_and_brackets_remain_public(self):
        for text in ["看 [集合](#set) 与 $[0,1]$", "数组 [[1,2],[3,4]]", "方括号 [", "文本 [[other]]"]:
            with self.subTest(text=text):
                self.assertEqual(split_catalog_answer(text), (text, None))
                actual, filter_ = streamed(list(text))
                self.assertEqual(actual, text)
                filter_.feed("ignored after finish")
                self.assertEqual(filter_._pending, "")

    def test_malformed_and_truncated_suffix_never_becomes_public(self):
        stem = CATALOG_GRAPH_OPEN[:-2]
        malformed = [
            CATALOG_GRAPH_OPEN + "{broken JSON}",
            CATALOG_GRAPH_OPEN + BODY,
            CATALOG_GRAPH_OPEN + "{broken JSON}" + CATALOG_GRAPH_CLOSE,
            stem + " {missing opening brackets but private data}",
            CATALOG_GRAPH_OPEN + BODY + CATALOG_GRAPH_CLOSE + "secret trailing text",
            CATALOG_GRAPH_OPEN + BODY + CATALOG_GRAPH_CLOSE + CATALOG_GRAPH_OPEN + BODY + CATALOG_GRAPH_CLOSE,
        ]
        for suffix in malformed:
            with self.subTest(suffix=suffix):
                self.assertEqual(split_catalog_answer(PUBLIC + suffix), (PUBLIC.rstrip(), None))
                actual, _ = streamed(list(PUBLIC + suffix))
                self.assertEqual(actual, PUBLIC)
        for length in range(2, len(CATALOG_GRAPH_OPEN)):
            with self.subTest(prefix_length=length):
                suffix = CATALOG_GRAPH_OPEN[:length]
                text, graph = split_catalog_answer(PUBLIC + suffix)
                self.assertEqual(text.rstrip(), PUBLIC.rstrip())
                self.assertIsNone(graph)
                actual, _ = streamed(list(PUBLIC + suffix))
                self.assertEqual(actual, PUBLIC)

    def test_invalid_json_and_wrong_envelope_shapes_are_rejected(self):
        bodies = [
            "[]", "null", '{"nodes":[],"edges":[],"unresolved":null}',
            '{"nodes":{},"edges":[]}', '{"nodes":[],"edges":{}}',
            '{"nodes":[],"edges":[],"unresolved":"","unresolved":"second"}',
            '{"nodes":[],"edges":[],"unexpected":NaN}',
            '{"nodes":[],"edges":[],"unexpected":Infinity}',
        ]
        for body in bodies:
            with self.subTest(body=body):
                wire = PUBLIC + CATALOG_GRAPH_OPEN + body + CATALOG_GRAPH_CLOSE
                self.assertEqual(split_catalog_answer(wire), (PUBLIC.rstrip(), None))

    def test_size_limit_and_streaming_memory_bound(self):
        oversized = json.dumps({"nodes": [], "edges": [], "unresolved": "中" * (128 * 1024 // 3)})
        wire = PUBLIC + CATALOG_GRAPH_OPEN + oversized + CATALOG_GRAPH_CLOSE
        self.assertEqual(split_catalog_answer(wire), (PUBLIC.rstrip(), None))
        actual, filter_ = streamed([PUBLIC + CATALOG_GRAPH_OPEN, "private" * 100_000])
        self.assertEqual(actual, PUBLIC)
        self.assertEqual(filter_._pending, "", "private JSON is not buffered by the streaming filter")
        output = []
        filter_ = CatalogAnswerDeltaFilter(output.append)
        for _ in range(100):
            filter_.feed("visible" * 1000 + "[[DMATE_")
            self.assertLess(len(filter_._pending), len(CATALOG_GRAPH_OPEN))
        filter_.finish()
        self.assertTrue(output)


if __name__ == "__main__":
    unittest.main()
