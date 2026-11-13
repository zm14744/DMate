"""Translation release checks protect IDs, choice answers and source freshness."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from offline_translations import compile_translations, source_manifest


class TranslationChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.folder = self.root / "offline-content/i18n/en"
        self.folder.mkdir(parents=True)
        self.concepts = {"concepts": [{"id":"positive_square", "title":"正数的平方", "summary":"平方为正。",
            "definition":"设x>0。", "explanation":"由x>0得到x²>0。", "notation":["x²"],
            "example":"2²=4。", "common_mistakes":["遗漏x>0。"]}]}
        self.questions = {"questions": [{"id":"positive_choice", "type":"单项选择", "title":"正平方",
            "statement":"设x>0，选择正确结论。", "options":[{"key":"A","text":"x²>0"},{"key":"B","text":"x²<0"}],
            "answer":["A"], "explanation":"正数之积为正。", "grading_criteria":"选A。"}]}
        self.shard = {"schema_version":1,"language":"en", "concepts":{"positive_square":{
            "title":"Squares of positive numbers", "summary":"The square is positive.", "definition":"Let x>0.",
            "explanation":"Since x>0, x²>0.", "notation":["x²"], "example":"2²=4.",
            "common_mistakes":["Omitting the assumption x>0."]}}, "questions":{"positive_choice":{
            "title":"Positive squares", "statement":"Let x>0. Select the correct conclusion.",
            "options":[{"key":"A","text":"x²>0"},{"key":"B","text":"x²<0"}], "answer_text":"A",
            "explanation":"The product of two positive numbers is positive.", "grading_criteria":"Select A."}}}
        for index in range(1,4):
            self.write("part-"+str(index)+".json", {"schema_version":1,"language":"en","concepts":{},"questions":{}})
        self.write("source-manifest.json", source_manifest(self.concepts,self.questions))

    def write(self, name, value):
        (self.folder/name).write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")

    def compile(self, shard=None):
        self.write("part-0.json", self.shard if shard is None else shard)
        return compile_translations(self.root,self.concepts,self.questions)

    def test_complete_english_content(self):
        value=self.compile()
        self.assertEqual(value["questions"]["positive_choice"]["answer_text"],"A")
        self.assertEqual(value["concepts"]["positive_square"]["notation"],["x²"])

    def test_missing_entry_is_rejected(self):
        shard=deepcopy(self.shard);shard["questions"].clear()
        with self.assertRaisesRegex(ValueError,"ID coverage"):
            self.compile(shard)

    def test_source_changes_require_translation_review(self):
        self.concepts["concepts"][0]["definition"]="设x<0。"
        with self.assertRaisesRegex(ValueError,"need review"):
            self.compile()

    def test_untranslated_prose_is_rejected(self):
        shard=deepcopy(self.shard);shard["concepts"]["positive_square"]["explanation"]="尚未翻译。"
        with self.assertRaisesRegex(ValueError,"untranslated Chinese"):
            self.compile(shard)

    def test_choice_keys_and_order_are_preserved(self):
        shard=deepcopy(self.shard);shard["questions"]["positive_choice"]["options"].reverse()
        with self.assertRaisesRegex(ValueError,"keys/order"):
            self.compile(shard)

    def test_wrong_answer_is_rejected(self):
        shard=deepcopy(self.shard);shard["questions"]["positive_choice"]["answer_text"]="B"
        with self.assertRaisesRegex(ValueError,"choice answer"):
            self.compile(shard)

    def test_missing_notation_is_rejected(self):
        shard=deepcopy(self.shard);shard["concepts"]["positive_square"]["notation"]=[]
        with self.assertRaisesRegex(ValueError,"changed length"):
            self.compile(shard)

    def test_overriding_canonical_identity_is_rejected(self):
        shard=deepcopy(self.shard);shard["concepts"]["positive_square"]["id"]="different"
        with self.assertRaisesRegex(ValueError,"unexpected"):
            self.compile(shard)


if __name__=="__main__":
    unittest.main()
