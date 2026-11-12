"""Regression tests for DMate's shared proof-writing policy."""

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from teaching import teaching_prompt

from proof_writing_extended import PROOF_DOMAINS, PROOF_GLOSSARY, PROOF_METHODS, PROOF_SOURCES, proof_coverage_prompt

from proof_writing import (
    PROOF_WRITING_STANDARD_EN,
    PROOF_WRITING_STANDARD_ZH,
    proof_writing_prompt,
)


def load_runtime_module(name):
    """Load the real entry point without installing unused HTTP/image clients.

    Completion is replaced in these request-assembly tests. No generated proof
    is assessed, and neither network requests nor image operations run.
    """
    stubs = {}
    if importlib.util.find_spec('requests') is None:
        requests = ModuleType('requests')
        requests.RequestException = type('RequestException', (Exception,), {})
        requests.Timeout = type('Timeout', (requests.RequestException,), {})
        stubs['requests'] = requests
    if importlib.util.find_spec('PIL') is None:
        pillow = ModuleType('PIL')
        for component in ('Image', 'ImageOps', 'ImageEnhance', 'ImageFilter'):
            setattr(pillow, component, ModuleType('PIL.' + component))
        stubs['PIL'] = pillow
    path = Path(__file__).resolve().parents[1] / (name + '.py')
    spec = importlib.util.spec_from_file_location('_proof_test_' + name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


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
        self.assertGreaterEqual(len(ids), 28)
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
        self.assertGreaterEqual(len(method_ids), 23)
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

    def test_scope_is_discrete_mathematics_only(self):
        domain_ids = {row[0] for row in PROOF_DOMAINS}
        required = {
            "logic_scope", "logical_implications", "set_theory", "relations_functions",
            "induction_family", "structural_induction", "number_theory", "congruences",
            "combinatorial_structures", "inclusion_exclusion", "graph_theory",
            "graph_planarity", "trees", "graph_algorithms", "posets_lattices",
            "algebra", "boolean_algebra", "automata", "formal_languages",
            "invariants", "termination", "recursion", "asymptotic"
        }
        self.assertTrue(required.issubset(domain_ids))
        forbidden_domains = {
            "real_completeness", "sequences_series", "epsilon_delta", "continuity",
            "differentiation", "integration", "metric_topology", "linear_algebra",
            "matrices_eigen", "geometry", "optimization", "ode",
            "multivariable_calculus", "complex_analysis", "convexity_optimization"
        }
        self.assertTrue(domain_ids.isdisjoint(forbidden_domains))
        method_ids = {row[0] for row in PROOF_METHODS}
        self.assertTrue({"truth_table", "counterexample", "exhaustive"}.issubset(method_ids))
        self.assertTrue(method_ids.isdisjoint({"epsilon_delta", "sequential", "open_cover"}))
        prompt_zh = proof_coverage_prompt("zh-CN")
        prompt_en = proof_coverage_prompt("en")
        for forbidden in ("ε-δ 证明", "开覆盖证明", "实分析", "微分方程"):
            self.assertNotIn(forbidden, prompt_zh)
        for forbidden in ("epsilon-delta", "open-cover proof", "real analysis", "differential equations"):
            self.assertNotIn(forbidden, prompt_en)
        for source in ("mit_real_analysis", "mit_linear_algebra", "mit_metric", "mit_optimization"):
            self.assertNotIn(source, PROOF_SOURCES)

    def test_full_chinese_and_english_prompts_share_all_domains(self):
        chinese = proof_writing_prompt("zh-CN")
        english = proof_writing_prompt("en-US")
        self.assertIn("【离散数学分领域证明核对要求", chinese)
        self.assertIn("[Discrete-mathematics proof checks", english)
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

    def test_runtime_and_docs_limit_the_policy_to_the_discrete_curriculum(self):
        root = Path(__file__).resolve().parents[1]
        chinese = proof_writing_prompt('zh-CN')
        english = proof_writing_prompt('en')
        self.assertTrue(chinese.lstrip().startswith('【离散数学证明写作规范'))
        self.assertTrue(english.lstrip().startswith('[DMate Discrete Mathematics Proof-Writing Standard]'))
        self.assertIn('仅适用于离散数学及其课程内紧密相关的算法、群环结构和数论应用', chinese)
        self.assertIn('only to proof tasks in discrete mathematics', english)
        self.assertIn('including algorithms, group/ring structures and number-theoretic applications', english)
        self.assertIn('不为微积分、实分析、一般拓扑、微分方程、连续优化等其他学科建立专门证明要求', chinese)
        self.assertIn('does not introduce dedicated proof requirements for calculus', english)
        for subject in ('微积分', '实分析', '一般拓扑', '微分方程', '连续优化'):
            self.assertIn(subject, PROOF_WRITING_STANDARD_ZH.split('\n\n', 1)[0])
        for subject in ('calculus', 'real analysis', 'general topology', 'differential equations', 'continuous optimization'):
            self.assertIn(subject, PROOF_WRITING_STANDARD_EN.split('\n\n', 1)[0])
        self.assertIn('仅用于该课程范围内的相关题型', proof_coverage_prompt('zh-CN'))
        self.assertIn('only to relevant topics within that curriculum', proof_coverage_prompt('en'))
        chinese_docs = (root / 'docs/PROOF_WRITING_STANDARD.md').read_text(encoding='utf-8')
        english_docs = (root / 'docs/PROOF_WRITING_STANDARD.en.md').read_text(encoding='utf-8')
        self.assertIn('仅用于上述离散数学课程范围', chinese_docs)
        self.assertIn('only within the discrete-mathematics curriculum above', english_docs)

    def test_existence_rules_allow_both_methods_without_forcing_a_witness(self):
        chinese = proof_writing_prompt('zh-CN')
        english = proof_writing_prompt('en')
        for rule in ('明确见证或构造并逐项核验', '完整、有效的非构造存在性论证',
                     '遵循题目或用户指定的证明方法', '非构造证明不必强行给出具体见证'):
            self.assertIn(rule, chinese)
        for rule in ('provide and verify a witness or construction',
                     'complete, valid nonconstructive existence argument',
                     'Follow the method specified by the problem or user',
                     'a nonconstructive proof need not supply a concrete witness'):
            self.assertIn(rule, english)
        self.assertNotIn('给出明确对象或构造，并逐项验证它满足要求', chinese)
        self.assertNotIn('To prove existence, construct or specify a witness and verify it.', english)

    def test_chat_requests_include_the_correct_policy_and_preserve_requested_method(self):
        ai = load_runtime_module('ai')
        requests = {
            'zh-CN':'请用概率方法给出非构造存在性证明，不构造具体图。',
            'en':'Use a probabilistic, nonconstructive existence proof; do not construct a concrete graph.',
        }
        for language, request in requests.items():
            with self.subTest(language=language), patch.object(ai, 'DEEPSEEK_API_KEY', 'test-only'), \
                    patch.object(ai, 'ASK_AI_MOCK', False), patch.object(ai, '_request_text_completion',
                    return_value={'ok':True, 'content':'Proof placeholder.', 'choice':{'finish_reason':'stop'}}) as completion:
                result = ai.ask_ai([{'role':'user', 'content':request}],
                                   teaching_context={'mode':'full_solution', 'response_language':language})
                self.assertTrue(result['ok'])
                completion.assert_called_once()
                messages = completion.call_args.args[0]
                self.assertEqual(messages[-1], {'role':'user', 'content':request})
                self.assertEqual(messages[0]['role'], 'system')
                self.assertEqual(messages[0]['content'].count(proof_writing_prompt(language)), 1)

    def test_notebook_requests_include_the_same_policy_and_preserve_requested_method(self):
        notebook = load_runtime_module('concept_notebook')
        answer = {'explanations':[{'note_id':'probability', 'explanation':'Explanation placeholder.'}],
                  'relations':[], 'summary':'Summary placeholder.'}
        questions = {'zh-CN':'请使用非构造证明，不要强求具体见证。',
                     'en':'Use a nonconstructive proof; do not construct a witness.'}
        for language, question in questions.items():
            with self.subTest(language=language):
                request = {'action':'explain', 'language':language,
                           'notes':[{'id':'probability', 'title':'Existence', 'content':'Probabilistic method'}],
                           'question':question}
                completion = Mock(return_value={'ok':True, 'content':json.dumps(answer)})
                result = notebook.analyze_notebook(request, completion=completion)
                self.assertTrue(result['ok'])
                completion.assert_called_once()
                messages = completion.call_args.args[0]
                self.assertEqual(messages[0]['role'], 'system')
                self.assertEqual(messages[0]['content'].count(proof_writing_prompt(language)), 1)
                self.assertEqual(json.loads(messages[1]['content'])['question'], request['question'])


if __name__ == "__main__":
    unittest.main()
