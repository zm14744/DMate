#!/usr/bin/env python3
"""Regression checks for curriculum gaps, broken links, and license mistakes."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from sync_offline_content import prepare
from offline_question_classification import record_digest, validate_classification_manifest


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
        sibling = next(c for c in self.concepts["concepts"]
                       if c["graph_node_id"] == child["graph_node_id"]
                       and c["id"] not in {child["id"], child["graph_node_id"]})
        for question in self.questions["questions"]:
            question["knowledge_points"] = list(dict.fromkeys(
                sibling["id"] if ref == child["id"] else ref for ref in question["knowledge_points"]))
        with self.assertRaisesRegex(ValueError, "has no exercise"):
            self.validate()

    def test_a_topic_overview_cannot_be_an_exercise_concept(self):
        self.questions["questions"][-1]["knowledge_points"] = [self.graph["nodes"][-1]["id"]]
        with self.assertRaisesRegex(ValueError, "detailed concepts, not topic overviews"):
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


class QuestionClassificationAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_concepts = json.loads((ROOT / "offline-content/concepts.zh-CN.json").read_text(encoding="utf-8"))
        cls.original_questions = json.loads((ROOT / "offline-content/questions.zh-CN.json").read_text(encoding="utf-8"))
        cls.original_manifest = json.loads((ROOT / "offline-content/question-concept-classification.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.concepts = deepcopy(self.original_concepts)
        self.questions = deepcopy(self.original_questions)
        self.manifest = deepcopy(self.original_manifest)

    def validate(self):
        validate_classification_manifest(self.concepts, self.questions, self.manifest)

    def test_reviewed_associations_retain_archived_original_records(self):
        self.validate()
        self.assertTrue(self.manifest["assignments"])
        questions = {row["id"]: row for row in self.questions["questions"]}
        for qid, entry in self.manifest["assignments"].items():
            with self.subTest(question=qid):
                original = deepcopy(questions[qid])
                original["knowledge_points"] = entry["previous_concept_ids"]
                self.assertEqual(record_digest(original), entry["original_record_sha256"])

    def test_rehashing_a_changed_question_cannot_override_its_original(self):
        qid, entry = next(iter(self.manifest["assignments"].items()))
        question = next(row for row in self.questions["questions"] if row["id"] == qid)
        question["statement"] += " 这个题目被额外修改了。"
        entry["classified_record_sha256"] = record_digest(question)
        with self.assertRaisesRegex(ValueError, "changed beyond concept associations"):
            self.validate()

    def test_reviewed_assignments_cannot_link_back_to_an_overview(self):
        qid, entry = next(iter(self.manifest["assignments"].items()))
        concepts = {row["id"]: row for row in self.concepts["concepts"]}
        topic = concepts[entry["concept_ids"][0]]["graph_node_id"]
        entry["concept_ids"] = [topic]
        question = next(row for row in self.questions["questions"] if row["id"] == qid)
        question["knowledge_points"] = [topic]
        entry["classified_record_sha256"] = record_digest(question)
        with self.assertRaisesRegex(ValueError, "must contain distinct detailed concepts"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
