"""Detect unresolved cross-question references before asking the AI to invent data.

Only catches a narrow class of isolated short follow-ups. Complete exercises
and normal multi-turn conversations are intentionally not intercepted.
"""
import re

CROSS_QUESTION = re.compile(
    r"^\s*(?:在\s*)?(?:上一(?:道|个)?题|前一(?:道|个)?题)"
    r"(?:的|中|里|所给的)?(?:条件|数据|背景|基础|前提|已知)?",
    re.I
)

def missing_previous_problem(messages):
    if not isinstance(messages,list):
        return False
    cleaned=[m for m in messages if isinstance(m,dict) and
             m.get("role") in ("user","assistant") and
             str(m.get("content") or "").strip()]
    if len(cleaned)!=1 or cleaned[0].get("role")!="user":
        return False
    content=str(cleaned[0]["content"]).strip()
    if len(content)>165 or not CROSS_QUESTION.match(content):
        return False
    # "上一题给出的 P=0.3, ... P=0.9, ...": explicit numerical data
    # may be sufficient to solve without hidden conversation context.
    numeric=re.findall(r"(?<![a-zA-Z])\d+(?:\.\d+)?%?",content)
    if len(numeric)>=3:
        return False
    return True
