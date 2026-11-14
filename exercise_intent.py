"""Local exercise intent rules shared with the browser, without model calls.

Only explicit generation/continuation commands select exercise mode. Quoted
examples and discussions are excluded; a later cancellation can revoke an
earlier command. Difficulty restrictions are not cancellations.
"""

import json
import re
import unicodedata
from pathlib import Path


EXERCISE_INTENT_RULES = json.loads(
    (Path(__file__).parent / "static" / "exercise-intent-rules.json").read_text(encoding="utf-8")
)
_COMPILED = {
    key: [re.compile(pattern) for pattern in EXERCISE_INTENT_RULES[key]]
    for key in ("ignored_spans", "whole_reject", "reject", "negative", "positive", "implicit")
}
_SEPARATOR = re.compile(EXERCISE_INTENT_RULES["clause_separator"])
_NORMALIZATIONS = [
    (re.compile(item["pattern"]), re.sub(r"\$(\d+)", r"\\g<\1>", item["replacement"]))
    for item in EXERCISE_INTENT_RULES["normalization"]["replacements"]
]
_ALIASES = sorted(
    EXERCISE_INTENT_RULES["normalization"]["aliases"].items(),
    key=lambda item: len(item[0]), reverse=True,
)
_GENERIC_CONTINUATION = [re.compile(pattern) for pattern in EXERCISE_INTENT_RULES.get("generic_continuation", [])]
_CONVERSATION_TASK = [re.compile(pattern, re.I) for pattern in EXERCISE_INTENT_RULES.get("conversation_task", [])]


def is_generic_continuation(text):
    """A noun-free continuation needs the preceding task to establish intent."""
    value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")).lower())
    clauses = [part for part in re.split(r"[，,。.;；!?！？]+", value) if part]
    generic = lambda part: any(pattern.fullmatch(part) for pattern in _GENERIC_CONTINUATION)
    return bool(clauses and generic(clauses[0]) and not any(
        classify_exercise_request(part)["is_exercise"] and not generic(part) for part in clauses[1:]
    ))


def resolve_exercise_request(text, messages=None):
    """Resolve ambiguous "another one" against the most recent substantive task.

    Text-only classification remains available to existing callers. Explicit
    question/exercise commands never depend on this conversational disambiguation.
    """
    intent = classify_exercise_request(text)
    if not is_generic_continuation(text):
        return intent
    history = list(messages) if isinstance(messages, (list, tuple)) else []
    latest = str(text or "").strip()
    if history and isinstance(history[-1], dict) and history[-1].get("role") == "user":
        content = str(history[-1].get("content", history[-1].get("text", ""))).strip()
        if content == latest:
            history.pop()
    for item in reversed(history):
        if not isinstance(item, dict) or item.get("role") != "user" or item.get("isError") or item.get("isNotice"):
            continue
        previous = str(item.get("content", item.get("text", ""))).strip()
        wrapped = re.search(r"【本轮唯一需要执行的用户请求】\s*(.*?)\s*【本轮请求结束】", previous, re.S)
        if wrapped:
            previous = wrapped.group(1)
        if not previous or is_generic_continuation(previous) or re.match(
            r"^(?:继续|然后呢|下一步|这一步|这个|这里|刚才|上面|上述|前面|按上|按照上|以后|今后|从现在|请记住|保持|还是|不对|不是|更正|纠正|改成|改用|用中文|用英文|只给|不要|别|"
            r"(?:请|帮我)?(?:证明|解释|说明|检查|展开|重写)(?:一下)?(?:这个|这一步|上述|上面|前面)|"
            r"continue\b|go on\b|that\b|this\b|the above\b|as before\b|from now on\b|keep\b|actually\b|instead\b|(?:explain|prove|rewrite|check) (?:it|this|that|the above)\b)",
            previous, re.I
        ):
            continue
        previous_intent = classify_exercise_request(previous)
        concrete_problem = re.match(
            r"^(?:设(?!计|置)|已知|给定|若|求(?:解|值|证)?|证明|计算|判断|let\b|given\b|suppose\b|find\b|compute\b|prove\b|show\s+that\b)",
            previous, re.I
        )
        if previous_intent["is_exercise"] or concrete_problem or item.get("manualIsQuestion") is True:
            return {"is_exercise": True, "explicit": False, "blocked": False}
        if any(pattern.search(previous) for pattern in _CONVERSATION_TASK):
            return {"is_exercise": False, "explicit": False, "blocked": False}
        # Intermediate corrections and format requests are evidence about the
        # task, not a new task merely because their wording is unfamiliar.
    return {"is_exercise": False, "explicit": False, "blocked": False}


def classify_exercise_request(text):
    """Return exercise intent, explicit-generation status and rejection status.

    Bare 下一题 is an implicit continuation so history navigation can resolve it
    first. A positive command after a refusal is allowed; a later cancellation
    wins. ``blocked`` lets the API reject stale clients' incorrect exercise hints.
    """
    value = unicodedata.normalize("NFKC", str(text or "")).lower().strip()
    if not value or len(value) > EXERCISE_INTENT_RULES["max_length"]:
        return {"is_exercise": False, "explicit": False, "blocked": False}

    for pattern, replacement in _NORMALIZATIONS:
        value = pattern.sub(replacement, value)
    for original, replacement in _ALIASES:
        value = value.replace(original, replacement)

    rejected = False
    for pattern in _COMPILED["ignored_spans"]:
        value, count = pattern.subn("", value)
        rejected = rejected or bool(count)

    if any(pattern.search(value) for pattern in _COMPILED["whole_reject"]):
        return {"is_exercise": False, "explicit": False, "blocked": True}

    is_exercise = explicit = False
    for clause in _SEPARATOR.split(value):
        if not clause:
            continue
        if any(pattern.search(clause) for pattern in _COMPILED["reject"]):
            rejected = True
            continue
        if any(pattern.search(clause) for pattern in _COMPILED["negative"]):
            is_exercise = explicit = False
            rejected = True
        elif any(pattern.search(clause) for pattern in _COMPILED["positive"]):
            is_exercise = explicit = True
        elif any(pattern.search(clause) for pattern in _COMPILED["implicit"]):
            is_exercise = True
            explicit = False

    return {
        "is_exercise": is_exercise,
        "explicit": explicit,
        "blocked": not is_exercise and rejected,
    }
