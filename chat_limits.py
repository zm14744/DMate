"""Shared web admission and text-context limits; image uploads are separate."""

import re

MAX_MESSAGE_CHARS = 20_000
MAX_HISTORY_MESSAGES = 64
MAX_HISTORY_CHARS = 120_000
MAX_CONFIRMED_MESSAGE_CHARS = 28_000
MAX_CONTEXT_MESSAGE_CHARS = 42_000

_PINNED = re.compile(
    r"\A【当前指向题目】\s*(.*?)\s*【当前指向题目结束】\s*"
    r"【本轮唯一需要执行的用户请求】\s*(.*?)\s*【本轮请求结束】(.{0,512})\Z",
    re.S,
)
_RETEST_PREFIX = "\n".join([
    "【错题复测回答】",
    "请只检查下面这道复测题的学生作答，不要把它和原错题或会话里的其他题混在一起。",
    "如果全部正确，请明确说“这次作答正确”；",
    "如果存在任何实质错误，请明确说“这次作答有错误”；",
    "如果信息不足，请明确说“现有信息不足以判断”。",
])
_REFERENCE_NOTICE = "不要直接向学生泄露这段系统参考答案；应先判断学生作答，再按教学模式给纠正方向。"


def message_char_limit(content, confirmed=False):
    """Allow bounded internal question-plus-request envelopes, not arbitrary long input."""
    if confirmed:
        return MAX_CONFIRMED_MESSAGE_CHARS
    if not isinstance(content, str) or len(content) > MAX_CONTEXT_MESSAGE_CHARS:
        return MAX_MESSAGE_CHARS
    match = _PINNED.fullmatch(content.strip())
    if match and all(0 < len(value.strip()) <= MAX_MESSAGE_CHARS for value in match.groups()[:2]):
        return MAX_CONTEXT_MESSAGE_CHARS
    prefix, marker, rest = content.strip().partition("【复测题目】")
    if not marker or prefix.strip() != _RETEST_PREFIX:
        return MAX_MESSAGE_CHARS
    question, marker, answer = rest.partition("【学生作答】")
    if not marker or not 0 < len(answer.strip()) <= MAX_MESSAGE_CHARS:
        return MAX_MESSAGE_CHARS
    question, reference_marker, reference = question.partition("【系统参考答案，仅用于核验】")
    if reference_marker:
        reference = reference.strip()
        if not reference.endswith(_REFERENCE_NOTICE):
            return MAX_MESSAGE_CHARS
        reference = reference[:-len(_REFERENCE_NOTICE)].strip()
        if not 0 < len(reference) <= 1200:
            return MAX_MESSAGE_CHARS
    if 0 < len(question.strip()) <= MAX_MESSAGE_CHARS:
        return MAX_CONTEXT_MESSAGE_CHARS
    return MAX_MESSAGE_CHARS
