#!/usr/bin/env python3
"""Regression checks for curriculum gaps, broken links, and license mistakes."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from sync_offline_content import prepare


ROOT = Path(__file__).resolve().parents[1]


class CurriculumIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = [json.loads((ROOT / name).read_text(encoding="utf-8")) for name in (
            "knowledge_graph.json", "offline-content/concepts.zh-CN.json",
            "offline-content/questions.zh-CN.json", "offline-content/references.zh-CN.json")]

    def setUp(self):
        self.graph, self.concepts, self.questions, self.references = deepcopy(self.original)

    def validate(self):
        return prepare(self.graph, self.concepts, self.questions, self.references)

    def test_current_curriculum(self):
        concepts, questions = self.validate()
        self.assertEqual(concepts, self.concepts)
        self.assertEqual(questions, self.questions)

    def test_missing_topic_overview_is_rejected(self):
        topic = self.graph["nodes"][-1]["id"]
        self.concepts["concepts"] = [c for c in self.concepts["concepts"] if c["id"] != topic]
        with self.assertRaisesRegex(ValueError, "missing topic overview"):
            self.validate()

    def test_unknown_concept_reference_is_rejected(self):
        self.questions["questions"][-1]["knowledge_points"] = ["missing-concept"]
        with self.assertRaisesRegex(ValueError, "unknown concept reference"):
            self.validate()

    def test_a_detail_without_exercises_is_rejected(self):
        child = next(c for c in self.concepts["concepts"] if c["id"] != c["graph_node_id"])
        for question in self.questions["questions"]:
            question["knowledge_points"] = list(dict.fromkeys(
                child["graph_node_id"] if ref == child["id"] else ref for ref in question["knowledge_points"]))
        with self.assertRaisesRegex(ValueError, "has no exercise"):
            self.validate()

    def test_broken_graph_prerequisite_is_rejected(self):
        self.graph["nodes"][-1]["prerequisites"] = ["已更名但未更新的知识点"]
        with self.assertRaisesRegex(ValueError, "unknown graph prerequisite"):
            self.validate()

    def test_concept_prerequisite_cycle_is_rejected(self):
        children = [c for c in self.concepts["concepts"] if c["id"] != c["graph_node_id"]]
        children[0]["prerequisites"] = [children[1]["id"]]
        children[1]["prerequisites"] = [children[0]["id"]]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.validate()

    def test_nonexistent_choice_answer_is_rejected(self):
        question = next(q for q in self.questions["questions"] if q["type"] == "单项选择")
        question["answer"] = ["不存在的选项"]
        with self.assertRaisesRegex(ValueError, "invalid choice answers"):
            self.validate()

    def test_noncommercial_license_is_rejected_even_with_wrong_permission_flag(self):
        self.references["sources"][0]["license"] = "CC-BY-NC-SA-4.0"
        with self.assertRaisesRegex(ValueError, "noncommercial license"):
            self.validate()

    def test_unpinned_reference_is_rejected(self):
        self.concepts["concepts"][0]["references"][0]["url"] = "https://example.org/unversioned"
        with self.assertRaisesRegex(ValueError, "immutable revision"):
            self.validate()

    def test_legacy_practice_ids_cannot_disappear(self):
        self.questions["questions"] = [q for q in self.questions["questions"] if q["id"] != "q01"]
        with self.assertRaisesRegex(ValueError, "legacy question IDs"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
