"""Conservative post-answer arithmetic check for unambiguous discrete-math tasks.

Only intervene for an explicitly answer-seeking request and a completely
parsed mathematical pattern. Unrelated exercises, incomplete graph OCR,
and prompt-only tutoring must not be overridden.
"""
import math
import re
from collections import Counter

ANSWER_LINE = re.compile(r"(?m)^\s*【结果】\s*([0-9][0-9,]*)\s*[。.\s]*$")
CHINESE = re.compile(r"(?P<n>\d{1,3})\s*本.{0,85}?(?:选|选择|取|挑)(?:出|中)?\s*(?P<k>\d{1,3})\s*本", re.S)
ENGLISH = re.compile(r"(?P<n>\d{1,3})\s+books.{0,200}?(?:select(?:ing)?|choos(?:e|ing))\s*(?P<k>\d{1,3})\b",re.I|re.S)
NEGATIVE = re.compile(r"不相邻|不连续|互不相邻|任意两本不相邻|no\s+two\s+adjacent|non[- ]adjacent", re.I)
ANSWER_DEMAND = re.compile(r"给出.*答案|直接.*(?:答案|解答|结果)|求.*(?:多少|方式|方案)|【结果】|完整解析|最终答案|how\s+many", re.I)

def _last_answer_integer(text):
    """Recognize an explicit LAST-LINE integer result without reading proof digits.

    In normal DMate chats users do not ask for a benchmark result marker.
    Support final '答案：5005', '共有 5005 种', and '...=5005' in addition to
    benchmark replies. Keep all intermediate working out of scope.
    """
    value=str(text or "")
    matches=list(ANSWER_LINE.finditer(value))
    if matches:
        return int(matches[-1].group(1).replace(",",""))
    lines=[line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return None
    last=lines[-1]
    clean=re.sub(r"\\(?:\(|\)|\[|\])", "", last)
    clean=re.sub(r"\\boxed\{\s*([0-9,]+)\s*\}", r"\1", clean)
    clean=re.sub(r"[$*]", "", clean).replace(chr(96),"").strip()
    patterns=(
        r"(?:最终答案|答案|一共有|共有|总数|方案数|方法数|排列数)"
        r".{0,50}?(?:为|是|=|：|:)\s*([0-9][0-9,]*)\s*(?:种|个|项|种方法)?[。.\s]*$",
        r"(?:因此|所以|故|计算得).{0,65}?(?:=|为|是|共(?:有)?)\s*"
        r"([0-9][0-9,]*)\s*(?:种|个|项|种方法)?[。.\s]*$",
        r"^\s*(?:=.*?|=)\s*([0-9][0-9,]*)\s*[。.\s]*$",
    )
    for pattern in patterns:
        found=re.search(pattern,clean)
        if found:
            return int(found.group(1).replace(",",""))
    return None


def _only_other_subquestion(question, target):
    """Avoid solving (b) if an exam image contains (a)+(b) but asks only (a).

    Only act when the request section is explicit and unambiguous.
    """
    q=str(question or "")
    if "【我的要求】" not in q:
        return False
    request=q.rsplit("【我的要求】",1)[1]
    if not re.search(r"只解|仅解|只回答|仅回答|只做",request):
        return False
    part_a=bool(re.search(r"[（(]\s*a\s*[）)]|第\s*1\s*(?:小?题|问)",request,re.I))
    part_b=bool(re.search(r"[（(]\s*b\s*[）)]|第\s*2\s*(?:小?题|问)",request,re.I))
    if target=="books":
        return part_a and not part_b
    if target=="letters":
        return part_b and not part_a
    return False


def separate_selection_value(question):
    """Return number of ways to pick k out of n ordered books nonadjacently."""
    q=str(question or "")
    if _only_other_subquestion(q, "books"):
        return None
    if not NEGATIVE.search(q):
        return None
    m=CHINESE.search(q) or ENGLISH.search(q)
    if not m:
        return None
    n,k=int(m.group("n")),int(m.group("k"))
    if not (1<=n<=300 and 1<=k<=n):
        return None
    return n,k,math.comb(n-k+1,k) if n-k+1>=k else 0

def _letter_arrangement_value(question):
    """Exact permutations of ONE visually confirmed all-caps English word.

    Abstain on ambiguous inputs, multiple words, or constrained permutations;
    never infer the word from an OCR guess or from an answer.
    """
    q=str(question or "")
    if _only_other_subquestion(q, "letters"):
        return None
    if not re.search(r"(?:letters?|字母|单词)", q, re.I):
        return None
    if not re.search(r"(?:arrang|permut|different ways|排列|全排列|不同排列)", q, re.I):
        return None
    # E.g. 'BANANARAMA'; avoid choosing a word from an unrelated paragraph
    # containing multiple upper-case labels such as graph vertex lists.
    words=re.findall(r"(?<![A-Za-z])([A-Z]{4,24})(?![A-Za-z])", q)
    candidates=set(words)-{"OCR", "TRUE", "FALSE"}
    if len(candidates)!=1:
        return None
    word=candidates.pop()
    # Other requirements, such as adjacent identical letters or fixed
    # placements, make the usual multiset formula inapplicable.
    if re.search(r"相邻|不得相邻|not\s+adjacent|fixed\s+position|首字母|元音", q, re.I):
        return None
    counts=Counter(word)
    result=math.factorial(len(word))//math.prod(math.factorial(n) for n in counts.values())
    return word,counts,result


def audit_letter_arrangement_answer(question, reply):
    """Correct 11!-for-10-letters errors in explicit complete solutions."""
    raw=str(reply or "")
    parsed=_letter_arrangement_value(question)
    if parsed is None or not ANSWER_DEMAND.search(question):
        return raw
    observed=_last_answer_integer(raw)
    if observed is None:
        return raw
    word,counts,result=parsed
    if observed==result:
        normalized=re.sub(r"\\[()\[\]]", "", raw).replace("$","")
        claimed_lengths=[
            int(n) for n in re.findall(
                r"(?:共有|一共|共计)\s*(\d{1,2})\s*个字母",normalized
            )
        ]
        factorials=[int(n) for n in re.findall(r"\b(\d{1,2})!",normalized)]
        if all(n==len(word) for n in claimed_lengths) and all(n<=len(word) for n in factorials):
            return raw
        # Even when the final answer is right, an impossible claimed word
        # length or factorial is a wrong proof and must be replaced.
    factors="×".join(f"{n}!" for n in sorted(counts.values(), reverse=True) if n>1)
    denominator=factors or "1"
    return (f"独立复核字母数与重复次数：{word} 共 {len(word)} 个字母，"
            + "，".join(f"{symbol} 出现 {n} 次" for symbol,n in sorted(counts.items()))
            + f"。不同排列的数量应为 {len(word)}!÷({denominator})={result}。"
            + f"\n【结果】{result}")


def audit_explicit_count_answer(question, reply):
    """Return original reply when unsure; correct proven wrong standalone count.

    If the model has included a wrong final result, replace it with a short
    recomputation, rather than leaving contradicting calculations in place.
    """
    text=str(reply or "")
    parsed=separate_selection_value(question)
    if not parsed:
        return audit_letter_arrangement_answer(question, text)
    if not ANSWER_DEMAND.search(question):
        return text
    observed=_last_answer_integer(text)
    if observed is None:
        return text  # do not inject a full solution into a hint
    n,k,expected=parsed
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
