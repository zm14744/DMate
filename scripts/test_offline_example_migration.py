#!/usr/bin/env python3
"""Keep reviewed example exercises reproducible without losing source material."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from migrate_concept_examples import (
    apply_migration,
    migration_targets,
    validate_example_migration,
)
from offline_translations import compile_translations, source_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = "offline-content/example-practice-migration.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_digest(value):
    return text_digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def file_snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


class ExamplePracticeMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.concepts = read_json(ROOT / "offline-content/concepts.zh-CN.json")
        cls.questions = read_json(ROOT / "offline-content/questions.zh-CN.json")
        cls.graph = read_json(ROOT / "knowledge_graph.json")
        cls.manifest = read_json(ROOT / MANIFEST_PATH)
        cls.translations = compile_translations(ROOT, cls.concepts, cls.questions)
        cls.concepts_by_id = {row["id"]: row for row in cls.concepts["concepts"]}
        cls.questions_by_id = {row["id"]: row for row in cls.questions["questions"]}
        cls.nodes_by_id = {row["id"]: row for row in cls.graph["nodes"]}

    def validate(self, concepts=None, questions=None, translations=None, manifest=None):
        validate_example_migration(
            self.concepts if concepts is None else concepts,
            self.questions if questions is None else questions,
            self.translations if translations is None else translations,
            self.manifest if manifest is None else manifest,
        )

    def temporary_source_tree(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        shutil.copytree(ROOT / "offline-content", root / "offline-content")
        shutil.copy2(ROOT / "knowledge_graph.json", root / "knowledge_graph.json")
        return root

    def test_reviewed_release_has_one_stable_question_per_concept(self):
        self.validate()
        self.assertEqual(len(self.concepts["concepts"]), 356)
        self.assertEqual(len(self.concepts_by_id), 356)
        self.assertEqual(set(self.manifest["examples"]), set(self.concepts_by_id))
        self.assertEqual(self.manifest["schema_version"], 1)
        for pack in (self.concepts, self.questions):
            self.assertEqual(pack["pack_version"], self.manifest["target_pack_version"])

        ids = [row["id"] for row in self.questions["questions"]]
        self.assertEqual(len(ids), len(set(ids)), "question records must not duplicate IDs")
        migrated = {qid for qid in ids if qid.startswith("q-example-")}
        self.assertEqual(migrated, {"q-example-" + cid for cid in self.concepts_by_id})
        self.assertEqual(set(ids), set(self.manifest["legacy_question_ids"]) | migrated)
        self.assertEqual(len(ids), 561 + 356)

    def test_original_chinese_and_english_answers_are_preserved_verbatim(self):
        for cid, concept in self.concepts_by_id.items():
            with self.subTest(concept=cid):
                entry = self.manifest["examples"][cid]
                question = self.questions_by_id["q-example-" + cid]
                english_concept = self.translations["concepts"][cid]
                english_question = self.translations["questions"][question["id"]]
                origin = question["source"]["migrated_from"]
                for source, translated, hash_key in (
                    (concept, question, "example_sha256"),
                    (english_concept, english_question, "english_example_sha256"),
                ):
                    self.assertEqual(entry[hash_key], text_digest(source["example"]))
                    self.assertEqual(origin[hash_key], text_digest(source["example"]))
                    self.assertEqual(translated["answer_text"], source["example"])
                    self.assertIn(source["example"], translated["explanation"])
                    self.assertIn(source["explanation"], translated["explanation"])
                self.assertEqual(origin["kind"], "concept_example")
                self.assertEqual(origin["concept_id"], cid)

    def test_prompts_are_reviewed_questions_and_not_the_old_worked_answers(self):
        for cid, concept in self.concepts_by_id.items():
            with self.subTest(concept=cid):
                entry = self.manifest["examples"][cid]
                question = self.questions_by_id[entry["question_id"]]
                english_concept = self.translations["concepts"][cid]
                english_question = self.translations["questions"][question["id"]]
                for translated, original, key in (
                    (question, concept, "statement_zh"),
                    (english_question, english_concept, "statement_en"),
                ):
                    self.assertTrue(translated["statement"].strip())
                    self.assertEqual(translated["statement"], entry[key])
                    self.assertNotEqual(translated["statement"].strip(), original["example"].strip())
                self.assertTrue(entry["difficulty_reason_zh"].strip())
                self.assertEqual(question["source"]["difficulty_rationale"], entry["difficulty_reason_zh"])

    def test_difficulty_category_and_bidirectional_navigation_are_complete(self):
        for cid, concept in self.concepts_by_id.items():
            with self.subTest(concept=cid):
                question = self.questions_by_id["q-example-" + cid]
                node = self.nodes_by_id[concept["graph_node_id"]]
                self.assertIn(question["difficulty"], {"简单", "中等", "困难"})
                self.assertIn(question["type"], {"计算", "简答", "证明"})
                self.assertEqual(question["category"], concept["category"])
                self.assertEqual(question["category"], node["category"])
                self.assertEqual(question["knowledge_points"], [cid])
                self.assertEqual(question["graph_node_ids"], [node["id"]])
                self.assertEqual(concept["related_questions"].count(question["id"]), 1)
                self.assertEqual(question["source"]["references"], concept["references"])
                for row in (question, self.translations["questions"][question["id"]]):
                    self.assertTrue(row["grading_criteria"].strip())

    def test_all_561_legacy_records_keep_their_full_metadata(self):
        legacy = self.manifest["legacy_question_ids"]
        hashes = self.manifest["legacy_question_sha256"]
        english_hashes = self.manifest["legacy_english_question_sha256"]
        self.assertEqual(len(legacy), 561)
        self.assertEqual(len(set(legacy)), 561)
        self.assertEqual(set(legacy), set(hashes))
        self.assertEqual(set(legacy), set(english_hashes))
        self.assertFalse(any(qid.startswith("q-example-") for qid in legacy))
        for qid in legacy:
            with self.subTest(question=qid):
                self.assertIn(qid, self.questions_by_id)
                self.assertEqual(record_digest(self.questions_by_id[qid]), hashes[qid])
                self.assertIn(qid, self.translations["questions"])
                self.assertEqual(record_digest(self.translations["questions"][qid]), english_hashes[qid])

    def test_modified_legacy_record_is_rejected(self):
        questions = deepcopy(self.questions)
        qid = self.manifest["legacy_question_ids"][0]
        question = next(row for row in questions["questions"] if row["id"] == qid)
        question["source"]["note"] = "Unreviewed metadata change"
        with self.assertRaisesRegex(ValueError, "legacy question changed"):
            self.validate(questions=questions)

    def test_modified_english_legacy_record_is_rejected(self):
        translations = deepcopy(self.translations)
        qid = self.manifest["legacy_question_ids"][0]
        translations["questions"][qid]["grading_criteria"] = "Unreviewed grading change"
        with self.assertRaisesRegex(ValueError, "legacy English question changed"):
            self.validate(translations=translations)

    def test_duplicate_concept_or_question_entities_are_rejected(self):
        concepts = deepcopy(self.concepts)
        concepts["concepts"].append(deepcopy(concepts["concepts"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.validate(concepts=concepts)
        questions = deepcopy(self.questions)
        questions["questions"].append(deepcopy(questions["questions"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.validate(questions=questions)

    def test_missing_or_unstable_migration_entry_is_rejected(self):
        cid = next(iter(self.concepts_by_id))
        manifest = deepcopy(self.manifest)
        del manifest["examples"][cid]
        with self.assertRaisesRegex(ValueError, "cover every concept"):
            self.validate(manifest=manifest)
        manifest = deepcopy(self.manifest)
        manifest["examples"][cid]["question_id"] = "unreviewed-renamed-question"
        with self.assertRaisesRegex(ValueError, "unstable migrated question ID"):
            self.validate(manifest=manifest)

    def test_old_answer_cannot_be_reviewed_as_a_question_in_either_language(self):
        cid = next(iter(self.concepts_by_id))
        for key, source in (
            ("statement_zh", self.concepts_by_id[cid]),
            ("statement_en", self.translations["concepts"][cid]),
        ):
            with self.subTest(field=key):
                manifest = deepcopy(self.manifest)
                manifest["examples"][cid][key] = source["example"]
                with self.assertRaisesRegex(ValueError, "answer used as question"):
                    self.validate(manifest=manifest)

    def test_new_exercises_reject_legacy_difficulty_aliases(self):
        cid = next(iter(self.concepts_by_id))
        for difficulty in ("基础", "进阶", "提高"):
            with self.subTest(difficulty=difficulty):
                manifest = deepcopy(self.manifest)
                manifest["examples"][cid]["difficulty"] = difficulty
                with self.assertRaisesRegex(ValueError, "noncanonical migrated difficulty"):
                    self.validate(manifest=manifest)

    def test_changed_chinese_source_requires_a_new_migration_review(self):
        concepts = deepcopy(self.concepts)
        concepts["concepts"][0]["example"] += " 变更后的例子。"
        with self.assertRaisesRegex(ValueError, "source example changed"):
            self.validate(concepts=concepts)

    def test_changed_english_source_requires_a_new_migration_review(self):
        translations = deepcopy(self.translations)
        cid = next(iter(self.concepts_by_id))
        translations["concepts"][cid]["example"] += " Revised example."
        with self.assertRaisesRegex(ValueError, "English source example changed"):
            self.validate(translations=translations)

    def test_lost_answers_or_question_drift_are_rejected_in_both_languages(self):
        cid = next(iter(self.concepts_by_id))
        qid = "q-example-" + cid
        for field in ("answer_text", "explanation", "statement"):
            with self.subTest(language="zh-CN", field=field):
                questions = deepcopy(self.questions)
                question = next(row for row in questions["questions"] if row["id"] == qid)
                question[field] = "Changed without review"
                with self.assertRaisesRegex(ValueError, "differs from reviewed manifest"):
                    self.validate(questions=questions)
            with self.subTest(language="en", field=field):
                translations = deepcopy(self.translations)
                translations["questions"][qid][field] = "Changed without review"
                with self.assertRaisesRegex(ValueError, "English migrated exercise differs"):
                    self.validate(translations=translations)

    def test_regeneration_from_legacy_only_inputs_is_pure_and_idempotent(self):
        root = self.temporary_source_tree()
        release = file_snapshot(root)
        concepts_path = root / "offline-content/concepts.zh-CN.json"
        questions_path = root / "offline-content/questions.zh-CN.json"
        concepts = read_json(concepts_path)
        questions = read_json(questions_path)
        legacy = set(self.manifest["legacy_question_ids"])
        questions["questions"] = [row for row in questions["questions"] if row["id"] in legacy]
        concepts["pack_version"] = questions["pack_version"] = "0.3.0"
        for concept in concepts["concepts"]:
            concept["related_questions"] = [qid for qid in concept["related_questions"] if qid in legacy]
        write_json(concepts_path, concepts)
        write_json(questions_path, questions)
        folder = root / "offline-content/i18n/en"
        for index in range(4):
            path = folder / f"part-{index}.json"
            shard = read_json(path)
            shard["questions"] = {qid: row for qid, row in shard["questions"].items() if qid in legacy}
            write_json(path, shard)
        write_json(folder / "source-manifest.json", source_manifest(concepts, questions))
        before = file_snapshot(root)

        targets = migration_targets(root)
        self.assertEqual(targets, migration_targets(root))
        self.assertEqual(file_snapshot(root), before, "planning must not write source files")
        with self.assertRaisesRegex(ValueError, "need syncing"):
            apply_migration(root, check=True)
        self.assertEqual(file_snapshot(root), before, "--check must not repair its inputs")
        self.assertTrue(apply_migration(root))
        regenerated = file_snapshot(root)
        self.assertEqual(regenerated, release, "legacy-only inputs must reproduce the reviewed release bytes")
        self.assertEqual(apply_migration(root), [])
        self.assertEqual(apply_migration(root, check=True), [])
        self.assertEqual(file_snapshot(root), regenerated)

    def test_translation_review_does_not_bypass_stale_migration_manifest(self):
        root = self.temporary_source_tree()
        path = root / "offline-content/concepts.zh-CN.json"
        concepts = read_json(path)
        concepts["concepts"][0]["example"] += " 变更后的例子。"
        write_json(path, concepts)
        # Simulate a separate translation review; the migration review is still stale.
        write_json(root / "offline-content/i18n/en/source-manifest.json",
                   source_manifest(concepts, self.questions))
        before = file_snapshot(root)
        for check in (True, False):
            with self.subTest(check=check):
                with self.assertRaisesRegex(ValueError, "source example changed"):
                    apply_migration(root, check=check)
                self.assertEqual(file_snapshot(root), before)

    def test_english_source_change_cannot_silently_regenerate_answer(self):
        root = self.temporary_source_tree()
        path = root / "offline-content/i18n/en/part-0.json"
        shard = read_json(path)
        cid = next(iter(shard["concepts"]))
        shard["concepts"][cid]["example"] += " Revised example."
        write_json(path, shard)
        before = file_snapshot(root)
        for check in (True, False):
            with self.subTest(check=check):
                with self.assertRaisesRegex(ValueError, "English source example changed"):
                    apply_migration(root, check=check)
                self.assertEqual(file_snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
