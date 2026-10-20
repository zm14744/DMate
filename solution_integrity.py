"""Conservative exact checks for discrete-math questions that can be verified
without another model call.

Work from CURRENT USER QUESTION, never from AI-derived intermediate reasoning.
Only dispatch after the entire pattern is parsed. Unrecognized or ambiguous
questions keep their original AI output. Return None on abstention.
"""
from __future__ import annotations
import itertools
import re
from collections import Counter

NO_ANSWER = re.compile(r"不要.{0,8}答案|只.{0,4}提示|仅.{0,4}提示|不要.{0,8}解答|先不给答案")
MARKED = re.compile(r"【题目文字】|【我的要求】|【当前指向题目】")
LOGIC_EQ = re.compile(r"(?:(?:命题|判断)\s*)?(.{2,140}?)\s*(?:与|和)\s*(.{2,140}?)\s*(?:是否|是不是|可否)\s*逻辑等价")


def _active_question(question):
    """Separate image/previous-answer metadata, refuse complex mixed exercises."""
    text = str(question or "").strip()
    if "【题目文字】" in text:
        text = text.split("【题目文字】", 1)[1].split("【图形信息】", 1)[0].split("【我的要求】", 1)[0].strip()
    if "【我的要求】" in question and NO_ANSWER.search(question.rsplit("【我的要求】", 1)[1]):
        return ""
    if NO_ANSWER.search(question):
        return ""
    text=re.sub(r"^(?:请直接给出最终答案并简要解释|请给出答案并说明理由|直接给出答案并解析)[。.!！]?\s*", "", text)
    return text


def _prop_eval(formula, env):
    """Recursive descent parser: ¬ ! ~ > &, |, ->, ↔ and parentheses.

    Formula MUST be fully consumed. Unknown syntax cannot be interpreted
    as true; throw ValueError and abstain.
    """
    compact = str(formula).replace(" ", "").replace("（", "(").replace("）", ")")
    compact = compact.replace("&&", "∧").replace("||", "∨")
    compact = compact.replace("⇒", "→").replace("->", "→").replace("↔", "≡")
    compact = compact.replace("∼", "¬").replace("!", "¬")
    tokens = re.findall(r"[a-z]|[()¬~∧&∨|→≡]", compact, re.I)
    if "".join(tokens) != compact or not tokens or len(tokens) > 70:
        raise ValueError("unsupported expression")
    pos = 0
    def peek():
        return tokens[pos] if pos<len(tokens) else None
    def take(t):
        nonlocal pos
        if peek()==t:
            pos+=1
            return True
        return False
    def atom():
        nonlocal pos
        if take("¬") or take("~"):
            return not atom()
        if take("("):
            v=bicond()
            if not take(")"):
                raise ValueError("unclosed expression")
            return v
        t=peek()
        if t is None or not re.fullmatch(r"[a-z]",t,re.I):
            raise ValueError("bad atom")
        pos+=1
        return env[t]
    def conj():
        v=atom()
        while peek() in ("∧","&"):
            take(peek())
            y=atom()
            v=v and y
        return v
    def disj():
        v=conj()
        while peek() in ("∨","|"):
            take(peek())
            y=conj()
            v=v or y
        return v
    def impl():
        v=disj()
        if take("→"):
            y=impl()  # implication associates to the right
            return not v or y
        return v
    def bicond():
        v=impl()
        while take("≡"):
            v=v==impl()
        return v
    result=bicond()
    if pos!=len(tokens):
        raise ValueError("unparsed symbols")
    return result


def _split_formula_pair(q):
    # Restrict to explicit two proposition formulas near an equivalence request
    # (do not pull expressions out of multi-part exams).
    if not re.search(r"是否逻辑等价|是不是逻辑等价|逻辑等价吗|是否等值",q):
        return None
    text=q.split("是否逻辑等价")[0].split("是不是逻辑等价")[0].strip()
    text=re.sub(r"^(?:判断|命题|请判断|判断下列命题)\s*[:：]?\s*","",text)
    if "\n" in text or "【" in text or len(text)>160:
        return None
    match=re.fullmatch(r"\s*(.+?)\s*(?:与|和)\s*(.+?)\s*", text)
    if not match:
        return None
    left,right=match.groups()
    if not re.fullmatch(r"[a-zA-Z¬~!∧&∨|→⇒↔≡()\s]+",left+right):
        return None
    return left,right


def verify_proposition_equivalence(question):
    q=_active_question(question)
    pair=_split_formula_pair(q)
    if pair is None:
        return None
    left,right=pair
    symbols=sorted(set(re.findall(r"[a-z]",left+right,re.I)))
    if not (1<=len(symbols)<=5):
        return None
    rows=[]
    try:
        for bits in itertools.product((False,True),repeat=len(symbols)):
            env=dict(zip(symbols,bits))
            a,b=_prop_eval(left,env),_prop_eval(right,env)
            rows.append((env,a,b))
    except ValueError:
        return None
    mismatch=next(((e,a,b) for e,a,b in rows if a!=b),None)
    if mismatch is None:
        return ("这两个命题**逻辑等价**。对涉及的 "
                + "、".join(symbols) + " 的全部 " + str(len(rows))
                + " 组真值赋值，两个公式的值均相同。"
                + "\n结论：**逻辑等价**。")
    env,a,b=mismatch
    witness="，".join(f"{s}={'真' if env[s] else '假'}" for s in symbols)
    return ("这两个命题**不逻辑等价**。存在反例赋值："
            + witness + f"；第一个公式为{'真' if a else '假'}，"
            + f"第二个公式为{'真' if b else '假'}。")


def verify_only_if_symbolization(question):
    q=_active_question(question)
    # For the standard "only if" meaning. Never trigger if no exact p/q
    # meanings are explicitly given or if a different sentence was requested.
    if not re.search(r"将.{0,40}只有下雨我才带伞.{0,30}符号化|只有下雨我才带伞.{0,15}(?:符号化|表示成命题)",q):
        return None
    if not re.search(r"p\s*表示\s*下雨",q,re.I) or not re.search(r"q\s*表示\s*带伞",q,re.I):
        return None
    return ("“只有下雨我才带伞”表示：**带伞是下雨的充分条件，下雨是带伞的必要条件**。\n"
            "所以符号化为 $q\\to p$。\n"
            "其逆否命题为 $\\neg p\\to\\neg q$，二者逻辑等价。")


def _selection_parse(question):
    q=_active_question(question)
    # Generalize the actual tested structure to 3-8 named persons, any k.
    head=re.search(r"([A-H](?:[、,，]\s*[A-H]){2,7})\s*中\s*选\s*(\d+)\s*人",q)
    if not head or not re.search(r"共有多少种|多少种符合|多少种选派|多少种方案",q):
        return None
    people=[x.strip() for x in re.split(r"[、,，]",head.group(1))]
    k=int(head.group(2))
    if len(set(people))!=len(people) or k<1 or k>len(people):
        return None
    tail=q[head.end():]
    # Accept only the three supported logically independent templates,
    # and refuse unexplained additional constraints.
    rules=[
        (re.compile(r"若\s*([A-H])\s*去\s*[，,]\s*则\s*([A-H])\s*和\s*([A-H])\s*中至少去\s*1\s*人"),"implies_any"),
        (re.compile(r"([A-H])\s*和\s*([A-H])\s*不能同时去"),"not_both"),
        (re.compile(r"([A-H])\s*去\s*则\s*([A-H])\s*不去"),"implies_not")
    ]
    matched=[]
    for pattern,kind in rules:
        hits=list(pattern.finditer(tail))
        if len(hits)!=1:
            return None
        matched.append((kind,hits[0].groups(),hits[0].span()))
    # Refuse if extra unknown rule is present. Only question text may remain.
    residue=list(tail)
    for _,_,(start,end) in matched:
        for p in range(start,end):residue[p]=" "
    rest="".join(residue)
    rest=re.sub(r"共有多少种符合条件的选派[？?]?|共有多少种(?:方案|选派)[？?]?|出差|[。；;，,\s？?]+", "",rest)
    if rest:
        return None
    if any(name not in people for _,names,_ in matched for name in names):
        return None
    return people,k,matched


def verify_finite_selection(question):
    parsed=_selection_parse(question)
    if parsed is None:
        return None
    people,k,rules=parsed
    valid=[]
    for combination in itertools.combinations(people,k):
        selected=set(combination)
        ok=True
        for kind,names,_ in rules:
            if kind=="implies_any":
                a,b,c=names
                ok=ok and (a not in selected or b in selected or c in selected)
            elif kind=="not_both":
                a,b=names
                ok=ok and not (a in selected and b in selected)
            elif kind=="implies_not":
                a,b=names
                ok=ok and not (a in selected and b in selected)
        if ok:
            valid.append("".join(combination))
    return ("按题目给出的全部限制逐一检验，不额外增加条件。\n"
            "符合条件的选派：" + ("、".join(valid) if valid else "无") + "。\n"
            f"因此共有 **{len(valid)} 种**。")


def verify_finite_relation(question):
    q=_active_question(question)
    match=re.search(
        r"(?:在\s*)?A\s*=\s*\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}"
        r".{0,100}x\s*R\s*y\s*当且仅当\s*x\s*\+\s*y\s*(?:≠|!=)\s*(\d+)",q)
    if not match or not re.search(r"是不是等价关系|是否.*等价关系",q):
        return None
    universe=[int(x) for x in match.group(1,2,3)]
    threshold=int(match.group(4))
    if len(set(universe))!=len(universe):
        return None
    rel={(x,y) for x in universe for y in universe if x+y!=threshold}
    refl=all((x,x) in rel for x in universe)
    symm=all((y,x) in rel for x,y in rel)
    counter=next(((x,y,z) for x in universe for y in universe for z in universe
                 if (x,y) in rel and (y,z) in rel and (x,z) not in rel),None)
    trans=counter is None
    ans=("是" if refl and symm and trans else "不是")
    pieces=[
        f"逐对计算题设关系，结论：**{ans}等价关系**。",
        "自反性：" + ("成立" if refl else "不成立") + "。",
        "对称性：" + ("成立" if symm else "不成立") + "。",
        "传递性：" + ("成立" if trans else "不成立") + "。"
    ]
    if counter:
        x,y,z=counter
        pieces.append(f"反例：({x},{y})∈R、({y},{z})∈R，但({x},{z})∉R。")
    return "\n".join(pieces)


def verify_exact_question(question, reply=None):
    """Return proof-quality deterministic answer for supported *whole* questions.

    Do not evaluate just an AI-suggested subquestion. Unknown patterns are left
    untouched. No-answer teaching requests are never overridden.
    """
    if not isinstance(question,str) or not question.strip():
        return None
    for verifier in (
        verify_finite_selection,
        verify_proposition_equivalence,
        verify_only_if_symbolization,
        verify_finite_relation,
    ):
        verified=verifier(question)
        if verified is not None:
            return verified
    return None
