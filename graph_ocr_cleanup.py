"""Presentation-only selection of exercise prose for graph photographs.

Question OCR and the mathematical graph payload must be independent. Never
alter graph edges, the source OCR audit trail, or AI safety decisions here.
"""
from __future__ import annotations
import re

# These standalone labels belong to the drawing, not to its question sentence.
_VERTEX = re.compile(r"(?:[A-Za-z](?:_?[0-9]{1,3})?|[A-Za-z]_[A-Za-z0-9]{1,8}|[A-Za-z]{1,3}[0-9]{1,3}|[uUvVeE][₀-₉]+)")
_FIGURE = re.compile(
    r"(?:(?:图|图号)\\s*[0-9０-９]+(?:\\s*[.．]\\s*[0-9０-９]+)?"
    r"|(?:fig(?:ure)?|图)\\s*[:：]?\\s*[0-9]+"
    r"|G\\s*_?\\s*[0-9]+"
    r"|[（(]\\s*[a-zA-Z0-9]{1,2}\\s*[）)])", re.I
)
_SUBFIGURE = re.compile(r"^(?:\\(\\s*[a-zA-Z0-9]\\s*\\)|（\\s*[a-zA-Z0-9]\\s*）)$")
_FIGURE_LINE = re.compile(
    r"^(?:(?:图|图号)\\s*[0-9０-９]+(?:\\s*[.．]\\s*[0-9０-９]+)?"
    r"|figure\\s*[0-9]+"
    r"|G\\s*_?\\s*[0-9]+(?:\\s*[（(]\\s*[a-zA-Z0-9]+\\s*[）)])?)\\s*[:：]?$", re.I
)
_EDGE_NUMBER = re.compile(r"^(?:[0-9０-９]+(?:\\.[0-9]+)?|[○●□☐◯]+|[√\\'.,+_\\-–—\\s]+)$")
_EXERCISE = re.compile(
    r"求|判断|证明|证实|计算|哪些|哪一个|下列|是否|图中|连通|同构|欧拉|"
    r"哈密顿|生成树|基本回路|路径|度数|矩阵|题|课堂测试|课后作业|"
    r"determin|prove|find|which|isomorph|euler|graph\\s+(?:is|are)|problem\\s*\\d+",
    re.I,
)
_SENTENCE = re.compile(r"[。？！?：:；;，,]|[a-zA-Z]+\\s+[a-zA-Z]+", re.I)
_METADATA = re.compile(
    r"^(?:【.*?(?:核对|候选|识别).*?】|"
    r"识别说明.*|状态\\s*[:：].*|首次识别.*|\\[.*?(?:待核对|识别不清楚).*?\\])$", re.I
)


def _lines(text):
    return [s.strip() for s in str(text or "").replace("\\r", "\\n").splitlines()
            if s.strip()]


def _is_diagram_label(line):
    source = str(line).strip()
    if _FIGURE_LINE.fullmatch(source) or _SUBFIGURE.fullmatch(source):
        return True
    if _VERTEX.fullmatch(source) or _EDGE_NUMBER.fullmatch(source):
        return True
    # OCR may insert spaces between standalone graph labels ("v 1", "e 4").
    compact = re.sub(r"\\s+", "", source)
    return bool(_VERTEX.fullmatch(compact) or _EDGE_NUMBER.fullmatch(compact))


def _is_prose(line):
    return bool(_EXERCISE.search(line) or
                (len(line) >= 12 and _SENTENCE.search(line) and
                 not re.match(r"^(?:[A-Za-z0-9_\\s,，.．]+)$", line)))


def clean_graph_question_text(text, *, has_graph=False):
    """Remove graph-only labels/captions; retain meaningful exercise sentences.

    Conservative when text is not graph-related. No labels are removed from
    within actual prose; e.g. "求 G1 中 v2 的度" stays intact.
    """
    source = str(text or "").strip()
    if not has_graph or not source:
        return source
    rows = _lines(source)
    kept = []
    for line in rows:
        if _METADATA.fullmatch(line) or _is_diagram_label(line):
            continue
        if _is_prose(line):
            kept.append(line)
            continue
        # Long English math context can be genuine question prose.
        # Short OCR scraps (including reversed-page characters) are not.
        if len(line) >= 24 and (
            len(re.findall(r"[\\u4e00-\\u9fff]", line)) >= 8 or
            len(line.split()) >= 4
        ) and _SENTENCE.search(line):
            kept.append(line)
    return "\\n".join(kept).strip()


def select_graph_question_text(ocr_text, corrected_text, *, has_graph=False):
    """Prefer image-grounded *question-only* Vision read, not a whole-page OCR dump."""
    if not has_graph:
        return str(corrected_text or ocr_text or "").strip()
    corrected = clean_graph_question_text(corrected_text, has_graph=True)
    if corrected:
        return corrected
    return clean_graph_question_text(ocr_text, has_graph=True)


def ocr_is_label_dominated(text):
    lines = _lines(text)
    if len(lines) < 4 or any(_EXERCISE.search(line) for line in lines):
        return False
    label_count = sum(_is_diagram_label(s) for s in lines)
    return label_count >= 3 and label_count * 10 >= 5 * len(lines)


__all__ = ["clean_graph_question_text", "select_graph_question_text", "ocr_is_label_dominated"]
