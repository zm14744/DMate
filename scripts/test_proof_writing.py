"""Regression tests for DMate's shared proof-writing policy."""

import unittest

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

    def test_non_english_language_defaults_to_chinese(self):
        self.assertIn(PROOF_WRITING_STANDARD_ZH, proof_writing_prompt("zh-Hans"))


if __name__ == "__main__":
    unittest.main()
