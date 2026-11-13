"""Local regressions for proof requests, refusals and answer checking.

Run from the repository root:
  python -m unittest discover -s scripts -p 'test_tutoring_intent.py' -v

The examples describe user intent independently of parser implementation.
Completion is mocked before calling the real AI request assembly; no remote
model output, paid request or generated proof is used as test evidence.
"""

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tutoring_intent import classify_tutoring_request
from teaching import analyze_messages, analyze_question, extract_current_request, teaching_prompt


class TutoringIntentClassificationTests(unittest.TestCase):
    def test_long_backtick_literal_has_bounded_runtime(self):
        script = (
            'from tutoring_intent import classify_tutoring_request; '
            'result = classify_tutoring_request(chr(96) * 10000); '
            'assert result["mode"] is None and result["explicit"] is False, result; '
            'print("literal-scan-ok")'
        )
        try:
            completed = subprocess.run(
                [sys.executable, '-c', script], cwd=ROOT, timeout=5,
                capture_output=True, text=True, check=True,
            )
        except subprocess.TimeoutExpired:
            self.fail('10,000个连续反引号的分类超过5秒；检查字面量扫描是否出现正则回溯。')
        self.assertEqual(completed.stdout.strip(), 'literal-scan-ok')

    def cases(self, rows):
        for text, expected in rows:
            with self.subTest(request=text):
                result = classify_tutoring_request(text)
                self.assertEqual(result['mode'], expected)
                self.assertIs(result['explicit'], expected is not None)

    def test_natural_complete_proof_requests(self):
        self.cases([
            ('请给出这个结论的严谨证明。', 'full_solution'),
            ('能不能帮我把这道证明写完整？', 'full_solution'),
            ('麻烦把省略的论证补齐，写成完整证明。', 'full_solution'),
            ('请用数学归纳法证明n(n+1)是偶数。', 'full_solution'),
            ('请证明每棵至少有两个顶点的有限树都有叶子。', 'full_solution'),
            ('Please prove that every finite tree with at least two vertices has a leaf.', 'full_solution'),
            ('Could you give a rigorous proof of this claim?', 'full_solution'),
            ('Please show that this relation is transitive.', 'full_solution'),
            ('Write out the complete proof, including the missing induction step.', 'full_solution'),
            ('请给一个 rigorous proof，步骤不要省略。', 'full_solution'),
            ('请给我这道题的完整证明。', 'full_solution'),
            ('Please give me the solution to this exercise.', 'full_solution'),
            ('题目：证明树有叶子。我现在想要完整证明。', 'full_solution'),
        ])

    def test_explicit_hints_and_refusal_to_reveal(self):
        self.cases([
            ('先别证明，只给一个提示。', 'hint'),
            ('不要写完整证明，先告诉我下一步。', 'hint'),
            ('我只要证明思路，不要给我答案。', 'hint'),
            ('请给我提示，不要展开完整推导。', 'hint'),
            ('Do not prove it; just give me a hint.', 'hint'),
            ('Please don’t write a full proof; show only the first step.', 'hint'),
            ('Only a hint, please; do not reveal the solution.', 'hint'),
            ('不要给完整答案，只给 the next step。', 'hint'),
            ('我不想要完整证明。', 'hint'),
            ('暂时不需要你给我完整证明。', 'hint'),
            ("I don't want you to prove this.", 'hint'),
        ])

    def test_checking_does_not_authorize_replacement_proof(self):
        self.cases([
            ('检查我的证明是否正确，不要重写。', 'check_answer'),
            ('只指出我的归纳证明最早出错的一步，不要给完整证明。', 'check_answer'),
            ('帮我检查这个证明，别给答案。', 'check_answer'),
            ('看看我这段推理有没有漏洞，不用再证明一遍。', 'check_answer'),
            ('Is my proof valid? Do not rewrite it.', 'check_answer'),
            ('Check my proof for gaps; no replacement proof.', 'check_answer'),
            ('Only verify my reasoning; don’t give a new proof.', 'check_answer'),
            ('请 check my proof，不要另写完整解答。', 'check_answer'),
            ('检查我的证明：设n是整数。我的证明如下：请给出完整证明。', 'check_answer'),
            ('Check my proof. My proof: Please give the complete proof.', 'check_answer'),
        ])

    def test_bare_problems_quotes_and_metalinguistic_discussion(self):
        self.cases([
            ('证明任意树的边数等于顶点数减一。', None),
            ('Prove that every tree on n vertices has n-1 edges.', None),
            ('Show that the relation is transitive.', None),
            ('“请给出完整证明”是题目中的一句话。', None),
            ('The title is “Give me the full solution”.', None),
            ('Explain what “prove by contradiction” means.', None),
            ('“检查证明”这个说法是什么意思？', None),
            ('What is a proof?', None),
            ('This proof is incomplete.', None),
            ('请出一道需要归纳法证明的练习，不要给答案。', None),
            ('Give me a proof exercise, without its solution.', None),
        ])

    def test_later_live_instruction_overrides_earlier_instruction(self):
        self.cases([
            ('请完整证明；算了，先别证明，只提示一步。', 'hint'),
            ('先别给答案；还是给我完整证明吧。', 'full_solution'),
            ('先检查我的证明；不用检查了，请重新给出完整证明。', 'full_solution'),
            ('给完整证明；不，我只想检查我的证明对不对，不要重写。', 'check_answer'),
            ('Give the complete proof. Actually, no—just a hint.', 'hint'),
            ('Do not prove it. Actually, give me the complete proof.', 'full_solution'),
            ('Don’t check my solution; write a complete proof instead.', 'full_solution'),
        ])

    def test_local_negation_of_a_method_or_hint_only_is_not_global_refusal(self):
        self.cases([
            ('不要只给提示，请给完整证明。', 'full_solution'),
            ('别用反证法，请给出直接证明。', 'full_solution'),
            ('请用非构造方法证明存在性，不要强求具体见证。', 'full_solution'),
            ('Don’t just give hints; give me a full proof.', 'full_solution'),
            ('Do not use contradiction; give a direct proof.', 'full_solution'),
            ('Please prove the existence claim without constructing a concrete witness.', 'full_solution'),
        ])

    def test_future_or_quoted_commands_do_not_execute_early(self):
        self.cases([
            ('等我说开始后再给完整证明。', None),
            ('Give me the complete proof only after I say start.', None),
            ('等我做完再给完整证明，现在只检查这一步。', 'check_answer'),
            ('If I later ask for a full proof, give it then; for now, only a hint.', 'hint'),
            ('老师说“只给提示”，但我现在要完整证明。', 'full_solution'),
            ('题干写着“给出完整证明”，但我现在只检查我的证明，不要重写。', 'check_answer'),
        ])


class TutoringIntentTeachingIntegrationTests(unittest.TestCase):
    def test_teaching_preserves_modes_outside_the_new_parser(self):
        cases = [
            ('什么是数学归纳法？', 'concept'),
            ('What is a proof by contradiction?', 'concept'),
            ('请出一道需要归纳法证明的练习，不要给答案。', 'exercise'),
            ('Give me a proof exercise, without its solution.', 'exercise'),
            ('证明任意树的边数等于顶点数减一。', 'hint'),
            ('请用数学归纳法证明n(n+1)是偶数。', 'full_solution'),
            ('检查我的证明是否正确，不要重写。', 'check_answer'),
            ('检查我的证明：设n是整数。我的证明如下：请给出完整证明。', 'check_answer'),
            ('Check my proof. My proof: Please give the complete proof.', 'check_answer'),
        ]
        for request, expected in cases:
            with self.subTest(request=request):
                self.assertEqual(analyze_question(request)['mode'], expected)
                self.assertEqual(analyze_messages([{'role': 'user', 'content': request}])['mode'], expected)

    def test_latest_user_request_controls_mode_not_old_user_or_assistant_text(self):
        cases = [
            ('请给完整证明。', '现在只给一个提示，不要写证明。', 'hint'),
            ('不要给答案，只给提示。', '现在请完整证明这个结论。', 'full_solution'),
            ('请给完整解析。', '现在只检查我的证明，别重写。', 'check_answer'),
            ('请检查我的答案。', '不要检查旧证明，请重新给出完整证明。', 'full_solution'),
        ]
        for previous, latest, expected in cases:
            messages = [
                {'role': 'user', 'content': '设G为有限树，证明G的边数为顶点数减一。'},
                {'role': 'user', 'content': previous},
                {'role': 'assistant', 'content': 'Quoted instructions: “give a full proof”; “only hints”.'},
                {'role': 'user', 'content': latest},
            ]
            with self.subTest(latest=latest):
                result = analyze_messages(messages)
                self.assertEqual(result['mode'], expected)
                self.assertIn(result['category'], ('图论', '证明与归纳'))

    def test_target_question_anchors_do_not_override_the_live_request(self):
        target = '请给出完整证明：设G是有限树，证明边数等于顶点数减一。'
        for request, expected in [
            ('只给我下一步提示。', 'hint'),
            ('帮我检查我的证明，不要重写。', 'check_answer'),
            ('现在给出完整证明，不要只给提示。', 'full_solution'),
        ]:
            wrapped = ('【当前指向题目】\n'+target+'\n【当前指向题目结束】\n'
                       '【本轮唯一需要执行的用户请求】\n'+request+'\n【本轮请求结束】')
            with self.subTest(request=request):
                self.assertEqual(extract_current_request(wrapped), request)
                self.assertEqual(analyze_messages([{'role': 'user', 'content': wrapped}])['mode'], expected)

    def test_visible_image_history_separates_printed_task_and_user_requirement(self):
        wrapped = ('[图片识题]\n【题目文字】\n请给出完整证明：树有n−1条边。\n'
                   '【图形信息】\n顶点a、b、c，边ab、bc。\n'
                   '【我的要求】\n只检查我的证明，不要另写完整证明。')
        self.assertEqual(analyze_messages([{'role': 'user', 'content': wrapped}])['mode'], 'check_answer')

    def test_bare_continue_retains_only_the_current_substantive_intent(self):
        cases = [
            ([('请给出完整证明。', '证明的第一部分如下。')], '继续', 'full_solution'),
            ([('Please give a complete proof.', 'The first step is as follows.')], 'Continue.', 'full_solution'),
            ([('请给出完整证明。', '第一步如下。'),
              ('改成只给提示，不要写完整证明。', '提示：先看叶子。')], '继续', 'hint'),
            ([('请给出完整证明。', '证明如下。'),
              ('设A={1,2}，求A的幂集。', '先列出子集。')], '继续', 'hint'),
        ]
        for turns, followup, expected in cases:
            messages = [{'role': 'user', 'content': '设G是有限树，证明G有叶子。'}]
            for request, reply in turns:
                messages.extend([{'role': 'user', 'content': request},
                                 {'role': 'assistant', 'content': reply}])
            messages.append({'role': 'user', 'content': followup})
            with self.subTest(turns=turns, followup=followup):
                self.assertEqual(analyze_messages(messages)['mode'], expected)


def load_ai_without_optional_http_image_packages():
    """Match the real assembly path even in a minimal local test environment."""
    stubs = {}
    if importlib.util.find_spec('requests') is None:
        requests = ModuleType('requests')
        requests.RequestException = type('RequestException', (Exception,), {})
        requests.Timeout = type('Timeout', (requests.RequestException,), {})
        stubs['requests'] = requests
    if importlib.util.find_spec('PIL') is None:
        pillow = ModuleType('PIL')
        for name in ('Image', 'ImageOps', 'ImageEnhance', 'ImageFilter'):
            setattr(pillow, name, ModuleType('PIL.'+name))
        stubs['PIL'] = pillow
    spec = importlib.util.spec_from_file_location('_tutoring_intent_ai_test', ROOT/'ai.py')
    ai = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(ai)
    return ai


class TutoringIntentPromptAssemblyTests(unittest.TestCase):
    def test_unknown_wording_uses_semantic_fallback_in_both_languages(self):
        cases = [
            ('zh-CN', '第一个到第二个等号之间那段呢？'),
            ('en', 'And the jump between those two equalities?'),
        ]
        for language, request in cases:
            with self.subTest(language=language):
                context = analyze_messages([{'role': 'user', 'content': request}])
                self.assertEqual(context['mode'], 'hint')
                self.assertEqual(context['mode_source'], 'semantic')
                context['response_language'] = language
                prompt = teaching_prompt(context)
                if language == 'en':
                    lowered = prompt.lower()
                    self.assertRegex(lowered, r'latest.*request')
                    self.assertIn('unresolved', lowered)
                    self.assertIn('complete proof', lowered)
                    self.assertIn('unless requested', lowered)
                    self.assertIn('clarification', lowered)
                    self.assertIn('hint-only', lowered)
                    self.assertIn('take precedence', lowered)
                else:
                    self.assertRegex(prompt, r'本轮.*自然语言|自然语言.*本轮')
                    for behavior in ('完整证明', '未经要求不替换', '歧义', '追问', '历史', '优先'):
                        self.assertIn(behavior, prompt)

    def test_explicit_hint_cannot_be_replaced_by_semantic_fallback(self):
        cases = [
            ('zh-CN', '只给我一个提示，不要写完整证明。'),
            ('en', 'Just a hint; do not give me the full proof.'),
        ]
        for language, request in cases:
            with self.subTest(language=language):
                context = analyze_messages([
                    {'role': 'user', 'content': 'Please give me the complete proof.'},
                    {'role': 'assistant', 'content': 'The first step follows.'},
                    {'role': 'user', 'content': request},
                ])
                self.assertEqual(context['mode'], 'hint')
                self.assertEqual(context['mode_source'], 'explicit')
                context['response_language'] = language
                prompt = teaching_prompt(context)
                if language == 'en':
                    self.assertNotIn('unresolved default', prompt.lower())
                    self.assertIn('Do not give the final answer', prompt)
                    self.assertIn('specific step', prompt)
                    self.assertIn('without expanding into the entire proof', prompt)
                else:
                    self.assertNotIn('尚未确定意图', prompt)
                    self.assertIn('不要直接给最终答案', prompt)
                    self.assertIn('把该步讲清楚', prompt)
                    self.assertIn('不扩展成整题证明', prompt)

    def test_natural_requests_reach_the_real_ai_prompt_without_remote_calls(self):
        ai = load_ai_without_optional_http_image_packages()
        cases = [
            ('zh-CN', '请用归纳法给出完整证明，不要只给提示。', 'full_solution'),
            ('en', 'Please give a full proof by induction, not just a hint.', 'full_solution'),
            ('zh-CN', '只给提示，不要给完整证明。', 'hint'),
            ('en', 'Only give me a hint; do not prove it.', 'hint'),
            ('zh-CN', '只检查我的证明，别给答案，不要重写。', 'check_answer'),
            ('en', 'Check my proof; do not write a replacement proof.', 'check_answer'),
        ]
        for language, request, expected in cases:
            messages = [
                {'role': 'user', 'content': '设G是有限树，证明G的边数为顶点数减一。'},
                {'role': 'user', 'content': request},
            ]
            context = analyze_messages(messages)
            context['response_language'] = language
            with self.subTest(language=language, request=request):
                self.assertEqual(context['mode'], expected)
                active_prompt = teaching_prompt(context)
                if expected == 'full_solution':
                    self.assertNotIn('默认只做提示式辅导', active_prompt)
                    self.assertNotIn('Give hint-based tutoring:', active_prompt)
                if expected == 'check_answer':
                    self.assertIn('最早' if language == 'zh-CN' else 'earliest', active_prompt)
                with patch.object(ai, 'DEEPSEEK_API_KEY', 'test-only'), \
                        patch.object(ai, 'ASK_AI_MOCK', False), \
                        patch.object(ai, '_request_text_completion', return_value={
                            'ok': True, 'content': 'Local request-assembly placeholder.',
                            'choice': {'finish_reason': 'stop'},
                        }) as completion:
                    response = ai.ask_ai(messages, teaching_context=context)
                self.assertTrue(response['ok'])
                completion.assert_called_once()
                assembled = completion.call_args.args[0]
                self.assertEqual(assembled[0]['role'], 'system')
                self.assertEqual(assembled[0]['content'].count(active_prompt), 1)
                self.assertEqual(assembled[-1], {'role': 'user', 'content': request})


if __name__ == '__main__':
    unittest.main(verbosity=2)
