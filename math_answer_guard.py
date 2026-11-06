"""Conservative post-answer arithmetic check for unambiguous discrete-math tasks.

Only intervene for an explicitly answer-seeking request and a completely
parsed mathematical pattern. Unrelated exercises, incomplete graph OCR,
and prompt-only tutoring must not be overridden.
"""
import math
import re
from collections import Counter

from server_i18n import localized, normalize_language

ANSWER_LINE = re.compile(r"(?m)^\s*【结果】\s*([0-9][0-9,]*)\s*[。.\s]*$")
CHINESE = re.compile(r"(?P<n>\d{1,3})\s*本.{0,85}?(?:选|选择|取|挑)(?:出|中)?\s*(?P<k>\d{1,3})\s*本", re.S)
ENGLISH = re.compile(r"(?P<n>\d{1,3})\s+books.{0,200}?(?:select(?:ing)?|choos(?:e|ing))\s*(?P<k>\d{1,3})\b",re.I|re.S)
NEGATIVE = re.compile(r"不相邻|不连续|互不相邻|任意两本不相邻|no\s+two\s+adjacent|non[- ]adjacent", re.I)
ANSWER_DEMAND = re.compile(r"给出.*答案|直接.*(?:答案|解答|结果)|求.*(?:多少|方式|方案)|【结果】|完整解析|最终答案|how\s+many", re.I)

# A closed-form answer must not replace an otherwise correct model answer when
# the question includes conditions that the parser did not understand. Remove
# only known wording; any remaining word/number makes the checker abstain.
_COUNT_PUNCTUATION = re.compile(r"[\s，。；：、！？,.!?:;()（）\[\]{}\"'“”‘’*_`$-]*\Z")
_REQUEST_WORDS = (
    "请直接给出最终答案并简要解释", "请给出答案并说明理由", "直接给出答案并解析",
    "直接给出答案", "请给出最终答案", "请给出答案", "最终答案", "完整解析",
    "并简要解释", "说明理由", "直接回答", "给出答案", "请计算", "求出", "计算", "请", "求",
)


def _known_count_wording(question, phrases, english_words, spans=()):
    if "【" in question or "】" in question:
        return False
    residue = list(question)
    for start, end in spans:
        residue[start:end] = " " * (end - start)
    residue = "".join(residue)
    # Word boundaries keep e.g. 'not' from being consumed as part of a longer
    # unsupported condition. Chinese phrases are matched longest first.
    alternatives = sorted(set((*_REQUEST_WORDS, *phrases)), key=len, reverse=True)
    residue = re.sub("|".join(re.escape(value) for value in alternatives), " ", residue)
    residue = re.sub(r"\b(?:" + "|".join(english_words) + r")\b", " ", residue, flags=re.I)
    return bool(_COUNT_PUNCTUATION.fullmatch(residue))


def _plain_book_selection(question, match):
    if not re.search(r"排成一[行排]|排[在成]一列|连续排列|排成一条直线|(?:in\s+a\s+row|on\s+a\s+(?:book)?shelf)", question, re.I):
        return False
    return _known_count_wording(question, (
        "互不相同的", "各不相同的", "不同的", "互不相同", "各不相同", "不同",
        "任意两本选中的书不相邻", "任意两本选中的书都不相邻", "任意两本不相邻",
        "所选的书互不相邻", "所选书互不相邻", "选中的书互不相邻", "互不相邻", "不相邻", "不连续",
        "共有多少种选法", "共有多少种方法", "共有多少种方案", "有多少种选法", "有多少种方法",
        "有多少种方案", "多少种选法", "多少种方法", "多少种方案", "求方案数", "求选法数",
        "在书架上", "书架上", "排成一条直线", "排成一行", "排成一排", "排在一列", "排成一列", "连续排列",
        "从这些书中", "从中", "现有", "设有", "选取", "选择", "选出", "挑选", "取出",
        "要求", "使得", "其中", "本书", "本", "书", "的", "有", "选", "取", "且", "从", "中",
    ), (
        "there", "are", "is", "the", "a", "in", "on", "of", "from", "them", "these",
        "books", "book", "shelf", "bookshelf", "row", "distinct", "different", "arranged",
        "choose", "choosing", "select", "selecting", "chosen", "selected", "so", "that",
        "no", "two", "adjacent", "non", "nonadjacent", "how", "many", "ways", "to", "can", "be",
        "please", "give", "final", "answer", "directly", "and", "explain", "briefly",
    ), (match.span("n"), match.span("k")))


def _plain_letter_permutation(question, word):
    text = re.sub(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", " ", question)
    return _known_count_wording(text, (
        "所有字母", "全部字母", "单词", "字母", "中的", "重新排列", "不同排列", "不同的排列",
        "全排列", "排列", "共有多少种", "有多少种", "多少种", "有多少个", "多少个",
        "不同的", "不同", "方式", "方法", "可以", "进行", "全部", "所有", "的", "种",
    ), (
        "the", "a", "all", "letters", "letter", "word", "of", "in", "row", "how", "many", "different",
        "ways", "can", "be", "arrange", "arranged", "arranging", "rearranged", "permutations", "permutation",
        "are", "there", "please", "give", "final", "answer", "directly", "and", "explain", "briefly",
    ))

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
    if not m or not _plain_book_selection(q, m):
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
    if not _plain_letter_permutation(q, word):
        return None
    # Other requirements, such as adjacent identical letters or fixed
    # placements, make the usual multiset formula inapplicable.
    if re.search(r"相邻|不得相邻|not\s+adjacent|fixed\s+position|首字母|元音", q, re.I):
        return None
    counts=Counter(word)
    result=math.factorial(len(word))//math.prod(math.factorial(n) for n in counts.values())
    return word,counts,result


def audit_letter_arrangement_answer(question, reply, *, language='zh-CN'):
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
    if normalize_language(language) == 'en':
        return (f"Independent count of letters and repetitions: {word} has {len(word)} letters; "
                + ", ".join(f"{symbol} occurs {n} times" for symbol,n in sorted(counts.items()))
                + f". The number of distinct arrangements is {len(word)}!÷({denominator})={result}."
                + f"\n【结果】{result}")
    return (f"独立复核字母数与重复次数：{word} 共 {len(word)} 个字母，"
            + "，".join(f"{symbol} 出现 {n} 次" for symbol,n in sorted(counts.items()))
            + f"。不同排列的数量应为 {len(word)}!÷({denominator})={result}。"
            + f"\n【结果】{result}")


def audit_explicit_count_answer(question, reply, *, language='zh-CN'):
    """Return original reply when unsure; correct proven wrong standalone count.

    If the model has included a wrong final result, replace it with a short
    recomputation, rather than leaving contradicting calculations in place.
    """
    text=str(reply or "")
    parsed=separate_selection_value(question)
    if not parsed:
        return audit_letter_arrangement_answer(question, text, language=language)
    if not ANSWER_DEMAND.search(question):
        return text
    observed=_last_answer_integer(text)
    if observed is None:
        return text  # do not inject a full solution into a hint
    n,k,expected=parsed
    if observed==expected:
        return text
    proof=localized(f"独立计数核验：从连续排列的 {n} 本书选 {k} 本，"
           f"每两本选中书之间至少留一本未选。"
           f"先预留 {k-1} 个必须空出的相邻间隔，"
           f"相当于从 {n-k+1} 个位置选出 {k} 个。\n"
           f"因此方案数为 C({n-k+1},{k})={expected}。",
           f"Independent count: choose {k} of {n} books in a row, leaving at least one unselected book "
           f"between successive selected books. Reserve the {k-1} required gaps. "
           f"This is equivalent to choosing {k} of {n-k+1} positions.\n"
           f"The number of selections is C({n-k+1},{k})={expected}.", language)
    # This is an actual mathematical correction: returning the originally
    # wrong derivation would be worse than giving a verified concise one.
    if re.search(r"\(a\).*\(b\)|（a）.*（b）",question,re.S|re.I):
        proof=localized("（a）对符合条件的选书方案，将前 k-1 本选中书后面"
               "必须空出的相邻位置与这 k-1 本合并，得到长度"
               f"{n-k+1}、含 {k} 个选中标记的二元序列。"
               "反向恢复也唯一，因此构成双射。\n\n"
               "（b）"+proof,
               "(a) In each valid selection, merge each of the first k-1 selected books with its required "
               f"following unselected position. This produces a binary sequence of length {n-k+1} "
               f"with {k} selected positions. The reverse construction is unique, so this is a bijection.\n\n"
               "(b) "+proof, language)
    return proof+f"\n【结果】{expected}"
