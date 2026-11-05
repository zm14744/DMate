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
