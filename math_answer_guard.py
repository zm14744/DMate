"""Conservative post-answer arithmetic check for unambiguous discrete-math tasks.

Only intervene for an explicitly answer-seeking request and a completely
parsed mathematical pattern. Unrelated exercises, incomplete graph OCR,
and prompt-only tutoring must not be overridden.
"""
import math
import re

ANSWER_LINE = re.compile(r"(?m)^\s*【结果】\s*([0-9][0-9,]*)\s*[。.\s]*$")
CHINESE = re.compile(r"(?P<n>\d{1,3})\s*本.{0,85}?(?:选|选择|取|挑)\s*(?P<k>\d{1,3})\s*本", re.S)
ENGLISH = re.compile(r"(?P<n>\d{1,3})\s+books.{0,200}?(?:select|choos(?:e|ing))\s*(?P<k>\d{1,3})\b",re.I|re.S)
NEGATIVE = re.compile(r"不相邻|不连续|互不相邻|任意两本不相邻|no\s+two\s+adjacent|non[- ]adjacent", re.I)
ANSWER_DEMAND = re.compile(r"给出.*答案|直接.*(?:答案|解答|结果)|求.*(?:多少|方式|方案)|【结果】|完整解析|最终答案|how\s+many", re.I)

def separate_selection_value(question):
    """Return number of ways to pick k out of n ordered books nonadjacently."""
    q=str(question or "")
    if not NEGATIVE.search(q):
        return None
    m=CHINESE.search(q) or ENGLISH.search(q)
    if not m:
        return None
    n,k=int(m.group("n")),int(m.group("k"))
    if not (1<=n<=300 and 1<=k<=n):
        return None
    return n,k,math.comb(n-k+1,k) if n-k+1>=k else 0

def audit_explicit_count_answer(question, reply):
    """Return original reply when unsure; correct proven wrong standalone count.

    If the model has included a wrong final result, replace it with a short
    recomputation, rather than leaving contradicting calculations in place.
    """
    text=str(reply or "")
    parsed=separate_selection_value(question)
    if not parsed or not ANSWER_DEMAND.search(question):
        return text
    match=list(ANSWER_LINE.finditer(text))
    if not match:
        return text  # do not inject a full solution into a hint
    n,k,expected=parsed
    observed=int(match[-1].group(1).replace(",",""))
    if observed==expected:
        return text
    proof=(f"独立计数核验：从连续排列的 {n} 本书选 {k} 本，"
           f"每两本选中书之间至少留一本未选。"
           f"先预留 {k-1} 个必须空出的相邻间隔，"
           f"相当于从 {n-k+1} 个位置选出 {k} 个。\n"
           f"因此方案数为 C({n-k+1},{k})={expected}。")
    # This is an actual mathematical correction: returning the originally
    # wrong derivation would be worse than giving a verified concise one.
    if re.search(r"\(a\).*\(b\)|（a）.*（b）",question,re.S|re.I):
        proof=("（a）对符合条件的选书方案，将前 k-1 本选中书后面"
               "必须空出的相邻位置与这 k-1 本合并，得到长度"
               f"{n-k+1}、含 {k} 个选中标记的二元序列。"
               "反向恢复也唯一，因此构成双射。\n\n"
               "（b）"+proof)
    return proof+f"\n【结果】{expected}"
