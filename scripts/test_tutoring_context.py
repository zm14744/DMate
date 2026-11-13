"""Local context regressions: a new review task must not inherit an old topic.

These tests exercise deterministic question selection only; no model is called.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from teaching import (
    _active_question_from_messages,
    _extract_explicit_review_question,
    analyze_messages,
)


OLD_QUESTION = '已知整数84和30，求它们的最大公约数。'
NEW_ZH = '设T是至少含两个顶点的有限无向树，证明T至少有两个叶子。'
NEW_EN = 'Let T be a finite tree with at least two vertices. Prove that T has two leaves.'


def wrapped(request):
    return ('【当前指向题目】\n' + OLD_QUESTION + '\n【当前指向题目结束】\n'
            '【本轮唯一需要执行的用户请求】\n' + request + '\n【本轮请求结束】')


class TutoringReviewContextTests(unittest.TestCase):
    def history(self, request):
        return [{'role':'user', 'content':OLD_QUESTION},
                {'role':'assistant', 'content':'可以使用欧几里得算法。'},
                {'role':'user', 'content':request}]

    def test_complete_new_chinese_review_selects_new_problem(self):
        request = '帮我检查下面这个新证明：' + NEW_ZH + '我的证明：取最长路径，两端都是叶子。'
        self.assertEqual(_extract_explicit_review_question(request), NEW_ZH)
        selected = _active_question_from_messages(self.history(request))
        self.assertEqual(selected[0], NEW_ZH)
        result = analyze_messages(self.history(request))
        self.assertEqual(result['mode'], 'check_answer')
        self.assertEqual(result['category'], '图论')
        self.assertIn('树的基本性质', result['knowledge_points'])

    def test_complete_new_english_review_selects_new_problem(self):
        request = 'Check this new proof: ' + NEW_EN + ' My proof: take a longest path.'
        self.assertEqual(_extract_explicit_review_question(request), NEW_EN)
        result = analyze_messages(self.history(request))
        self.assertEqual(result['mode'], 'check_answer')
        self.assertEqual(result['category'], '图论')

    def test_proof_section_prose_is_excluded_from_the_selected_problem(self):
        for request, expected in (
            ('帮我检查下面这个新证明：' + NEW_ZH + '我的证明如下：先求84和30的最大公约数。', NEW_ZH),
            ('帮我检查下面这个新证明：' + NEW_ZH + '我的证明是先求一个最大公约数。', NEW_ZH),
            ('Check this new proof: ' + NEW_EN + ' My proof is to use the greatest common divisor.', NEW_EN),
            ('Check this new proof: ' + NEW_EN + ' Here is my proof: use the greatest common divisor.', NEW_EN),
        ):
            with self.subTest(request=request):
                self.assertEqual(_extract_explicit_review_question(request), expected)

    def test_explicit_new_review_overrides_a_stale_anchor_in_both_languages(self):
        for request, expected in (
            ('帮我检查下面这个新证明：' + NEW_ZH + '我的证明：取最长路径。', NEW_ZH),
            ('Check this new proof: ' + NEW_EN + ' My proof: take a longest path.', NEW_EN),
        ):
            with self.subTest(request=request):
                messages = self.history(wrapped(request))
                self.assertEqual(_active_question_from_messages(messages)[0], expected)
                result = analyze_messages(messages)
                self.assertEqual(result['mode'], 'check_answer')
                self.assertEqual(result['category'], '图论')

    def test_new_review_with_complete_correction_keeps_the_new_problem(self):
        for request, expected in (
            ('帮我检查下面这个新证明：' + NEW_ZH + '我的证明：取最长路径。\n'
             '本轮要求：先检查，再给出完整的修正证明。', NEW_ZH),
            ('Check this new proof: ' + NEW_EN + ' My proof: take a longest path.\n'
             'Request: check it first, then give a complete corrected proof.', NEW_EN),
        ):
            with self.subTest(request=request):
                messages = self.history(wrapped(request))
                self.assertEqual(_extract_explicit_review_question(wrapped(request)), expected)
                self.assertEqual(_active_question_from_messages(messages)[0], expected)
                result = analyze_messages(messages)
                self.assertEqual(result['mode'], 'full_solution')
                self.assertEqual(result['category'], '图论')

    def test_review_followups_keep_the_old_question_and_anchor(self):
        for request in ('帮我检查刚才的证明，指出第一个漏洞。',
                        'Check my proof for gaps; do not rewrite it.'):
            for current in (request, wrapped(request)):
                with self.subTest(request=current):
                    messages = self.history(current)
                    self.assertEqual(_extract_explicit_review_question(current), '')
                    self.assertEqual(_active_question_from_messages(messages)[0], OLD_QUESTION)
                    self.assertEqual(analyze_messages(messages)['category'], '初等数论')

    def test_student_proof_is_not_reclassified_as_a_new_problem(self):
        requests = (
            '帮我检查刚才的证明。我的证明：' + NEW_ZH,
            '帮我检查下面这个新证明：我的证明：' + NEW_ZH,
            'Check my proof for gaps. My proof: ' + NEW_EN,
            'Check this new proof: My proof: ' + NEW_EN,
        )
        for request in requests:
            with self.subTest(request=request):
                self.assertEqual(_extract_explicit_review_question(request), '')
                self.assertEqual(_active_question_from_messages(self.history(wrapped(request)))[0], OLD_QUESTION)

    def test_quoted_example_and_setup_without_goal_do_not_override_anchor(self):
        requests = (
            '检查我的证明，不要换题。老师的例子是“检查下面这个新证明：' + NEW_ZH + '”。',
            '帮我检查下面这个新证明：设T为有限树。我的证明：使用叶子性质。',
            'Check this new proof: Let T be a finite tree. My proof: use its leaves.',
        )
        for request in requests:
            with self.subTest(request=request):
                self.assertEqual(_extract_explicit_review_question(request), '')
                self.assertEqual(_active_question_from_messages(self.history(wrapped(request)))[0], OLD_QUESTION)

    def test_nonreview_current_actions_do_not_take_the_review_override(self):
        for request in ('只给提示，不要检查这个新证明：' + NEW_ZH,
                        'Please give the complete proof: ' + NEW_EN):
            with self.subTest(request=request):
                self.assertEqual(_extract_explicit_review_question(request), '')

    def test_a_new_review_command_in_the_old_anchor_is_not_live(self):
        target = '帮我检查下面这个新证明：' + NEW_ZH
        current = ('【当前指向题目】' + target + '【当前指向题目结束】\n'
                   '【本轮唯一需要执行的用户请求】只检查刚才的证明，不要重写。'
                   '【本轮请求结束】')
        self.assertEqual(_extract_explicit_review_question(current), '')
        self.assertEqual(_active_question_from_messages(self.history(current))[0], target)
        self.assertEqual(analyze_messages(self.history(current))['mode'], 'check_answer')


if __name__ == '__main__':
    unittest.main()
