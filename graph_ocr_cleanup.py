"""Filter standalone graph labels from OCR *question prose*, not from graph data.

This is a presentation-only filter for images positively identified as graphs.
It deliberately does not infer any missing exercise text or edge topology.
"""
from __future__ import annotations

import re

# Single vertex/edge names, small OCR scraps, and empty-circle glyphs are not
# independent question text. Preserve figure captions and full questions.
_LABEL = re.compile(
    r"(?:[a-zA-Z](?:[_-]?[0-9]{1,2})?|[uv][0-9]{1,2}|"
    r"[eE][0-9]{1,2}|[gG][0-9]{1,2}|[0-9]{1,3}|"
    r"[○●□☐◯√+\-–—.()（）]+|[a-zA-Z]{2,4}[0-9]{0,2})",
    re.I,
)
_FIGURE = re.compile(
    r"^(?:(?:图|图号)\s*[0-9０-９]+(?:\s*[.．]\s*[0-9０-９]+)?"
    r"|fig(?:ure)?\s*[0-9]+(?:\s*[:：].*)?"
    r"|problem\s*[0-9]+|课堂测试.{0,8}|课后作业.{0,8})\s*[:：]?$",
    re.I,
)
_EXERCISE = re.compile(
    r"求|判断|证明|证实|计算|哪些|哪一个|下列|是否|图中|连通|同构|欧拉|"
    r"哈密顿|生成树|基本回路|路径|度数|矩阵|"
    r"determin|prove|find|which|isomorph|euler|graph\s+(?:is|are)",
    re.I,
)


def clean_graph_question_text(text, *, has_graph=False):
    """Keep credible question prose/captions; omit obvious isolated OCR labels.

    Use only after graph evidence has been established independently; non-graph
    uploads are unchanged. This cannot repair incorrectly recognized prose.
    """
    source = str(text or "").strip()
    if not has_graph or not source:
        return source
    lines = [line.strip() for line in source.replace("\r", "\n").split("\n") if line.strip()]
    label_lines = sum(bool(_LABEL.fullmatch(line)) for line in lines)
    # On a real paragraph, a solitary variable/number may be part of a formula.
    # Require sustained evidence of a graph-label dump before filtering.
    if label_lines < 3:
        return source

    retained = []
    for line in lines:
        if _FIGURE.fullmatch(line) or _EXERCISE.search(line):
            retained.append(line)
        elif not _LABEL.fullmatch(line):
            # Unrecognized prose is left intact: no fabricated corrections.
            retained.append(line)
    return "\n".join(retained).strip()


__all__ = ["clean_graph_question_text"]
