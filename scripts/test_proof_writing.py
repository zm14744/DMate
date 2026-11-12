"""Regression tests for DMate's shared proof-writing policy."""

import unittest

from teaching import teaching_prompt

from proof_writing_extended import PROOF_DOMAINS, PROOF_GLOSSARY, PROOF_METHODS, PROOF_SOURCES, proof_coverage_prompt

from proof_writing import (
    PROOF_WRITING_STANDARD_EN,
    PROOF_WRITING_STANDARD_ZH,
    proof_writing_prompt,
)


class ProofWritingPolicyTests(unittest.TestCase):
    def test_chinese_policy_covers_core_logic_and_language(self):
        for phrase in ("任取", "存在", "逆否命题", "反证法", "当且仅当",
                       "归纳假设", "最早出现的实质性错误", "不强迫所有题目套用同一个模板"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, PROOF_WRITING_STANDARD_ZH)

    def test_english_policy_covers_same_core_requirements(self):
        for phrase in ("arbitrary object", "witness", "contrapositive",
                       "contradiction", "induction hypothesis",
                       "earliest substantive error", "rigid template"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, PROOF_WRITING_STANDARD_EN)

    def test_language_selector_returns_consistent_policy(self):
        self.assertIn(PROOF_WRITING_STANDARD_ZH, proof_writing_prompt("zh-CN"))
        self.assertIn(PROOF_WRITING_STANDARD_EN, proof_writing_prompt("en"))
        self.assertIn(PROOF_WRITING_STANDARD_EN, proof_writing_prompt("en-US"))


    def test_proof_exercises_store_a_complete_hidden_proof(self):
        chinese = teaching_prompt({"mode": "exercise", "response_language": "zh-CN"})
        english = teaching_prompt({"mode": "exercise", "response_language": "en"})
        self.assertIn("完整、可独立检查的规范证明", chinese)
        self.assertIn("complete, independently checkable proof", english)

    def test_bilingual_method_coverage_has_same_ids_and_source_evidence(self):
        ids = [row[0] for row in PROOF_DOMAINS]
        self.assertGreaterEqual(len(ids), 35)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(PROOF_SOURCES), 8)
        for key, zh_title, en_title, zh_rule, en_rule, sources in PROOF_DOMAINS:
            with self.subTest(method=key):
                self.assertTrue(zh_title.strip() and en_title.strip())
                self.assertTrue(zh_rule.strip() and en_rule.strip())
                self.assertGreaterEqual(len(sources), 1)
                self.assertTrue(all(source in PROOF_SOURCES for source in sources))
                self.assertIn(zh_title, proof_coverage_prompt("zh-CN"))
                self.assertIn(en_title, proof_coverage_prompt("en"))
        method_ids = [row[0] for row in PROOF_METHODS]
        self.assertGreaterEqual(len(method_ids), 20)
        self.assertEqual(len(method_ids), len(set(method_ids)))
        for key, zh, en, caution_zh, caution_en in PROOF_METHODS:
            with self.subTest(method=key):
                self.assertTrue(all(x.strip() for x in (zh, en, caution_zh, caution_en)))
                self.assertIn(zh, proof_coverage_prompt("zh"))
                self.assertIn(en, proof_coverage_prompt("en"))
        for key, zh, en, caution_zh, caution_en in PROOF_GLOSSARY:
            with self.subTest(terminology=key):
                self.assertTrue(all(x.strip() for x in (zh, en, caution_zh, caution_en)))
                self.assertIn(zh, proof_coverage_prompt("zh"))
                self.assertIn(en, proof_coverage_prompt("en"))
        for source in PROOF_SOURCES.values():
            self.assertTrue(source["url"].startswith("https://"))
            self.assertTrue(source["name"] and source["role"])

    def test_full_chinese_and_english_prompts_share_all_domains(self):
        chinese = proof_writing_prompt("zh-CN")
        english = proof_writing_prompt("en-US")
        self.assertIn("【分领域证明核对要求", chinese)
        self.assertIn("[Domain-specific proof checks", english)
        for _, zh_title, en_title, _, _, _ in PROOF_DOMAINS:
            self.assertEqual(chinese.count(zh_title), 1)
            self.assertEqual(english.count(en_title), 1)
        for _, zh, en, _, _ in PROOF_METHODS:
            self.assertIn(zh, chinese)
            self.assertIn(en, english)
        self.assertIn("only if Q", english)
        self.assertIn("仅当 Q", chinese)
        self.assertIn("without circularity", english)
        self.assertIn("不能循环论证", chinese)

    def test_non_english_language_defaults_to_chinese(self):
        self.assertIn(PROOF_WRITING_STANDARD_ZH, proof_writing_prompt("zh-Hans"))


if __name__ == "__main__":
    unittest.main()
