"""Conservative, local tutoring-mode requests; no model or network calls.

This classifier recognizes the student's requested *kind of help*, rather
than treating a mathematical exercise's imperative (``Prove that ...``) as
permission to supply its solution. Unrecognized text deliberately returns
None so the caller can keep its normal exercise/concept/semantic routing.
"""

from dataclasses import dataclass
import re
import unicodedata

from exercise_intent import classify_exercise_request


def _compile(pattern):
    return re.compile(pattern, re.IGNORECASE)


def _blank(match):
    """Keep offsets and line boundaries while excluding literal material."""
    return re.sub(r"[^\n]", " ", match.group())


_LITERALS = [
    re.compile(r"(?m)^[ \t]*>[^\n]*"),
    re.compile(r"(?m)^(?: {4}|\t)[^\n]*"),
    re.compile(r"(?s)\\begin\{((?:equation|align|aligned|gather|math|displaymath|eqnarray)\*?)\}.*?\\end\{\1\}"),
    re.compile(r"(?s)\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\\)\$(?:\\.|[^$\n])*?(?<!\\)\$"),
    re.compile(r'(?s)“[^”]*”|「[^」]*」|『[^』]*』|‘[^’]*’|"(?:\\.|[^"\\])*"'),
    # Apostrophes inside English words (don't, student's) are not quotations.
    re.compile(r"(?s)(?<!\w)'(?:\\.|[^'\\])*'(?!\w)"),
    re.compile(r"(?m)[“「『][^\n]*$"),
]
_TICKS = re.compile(r"`+")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def _mask_code(value):
    """Mask Markdown code with linear scans, including very long tick runs."""
    output = []
    fence = None
    for line in value.splitlines(keepends=True):
        marker = _FENCE.match(line)
        if fence:
            output.append(re.sub(r"[^\n]", " ", line))
            if (marker and marker.group(1)[0] == fence[0]
                    and len(marker.group(1)) >= fence[1]
                    and not line[marker.end():].strip()):
                fence = None
            continue
        if marker and line.find(marker.group(1), marker.end()) < 0:
            fence = (marker.group(1)[0], len(marker.group(1)))
            output.append(re.sub(r"[^\n]", " ", line))
            continue
        ticks = list(_TICKS.finditer(line))
        following, nearest = {}, {}
        for index in range(len(ticks) - 1, -1, -1):
            size = ticks[index].end() - ticks[index].start()
            following[index] = nearest.get(size)
            nearest[size] = index
        pieces, cursor, index = [], 0, 0
        while index < len(ticks):
            opening = ticks[index]
            closing = following[index]
            end = ticks[closing].end() if closing is not None else len(line)
            pieces.append(line[cursor:opening.start()])
            pieces.append(re.sub(r"[^\n]", " ", line[opening.start():end]))
            cursor = end
            if closing is None:
                break
            index = closing + 1
        pieces.append(line[cursor:])
        output.append("".join(pieces))
    return "".join(output)


_LABELED_PROBLEM = _compile(
    r"(?m)^\s*(?:题目|题干|原题|problem|exercise)\s*[:：][^\n]*?"
    r"(?=[。.!?;；]\s*(?:我(?:现在)?(?:想要|要|需要)|现在(?:请|只|给)|"
    r"请(?:给|写|帮)|please\b|i (?:want|need)\b)|\n|$)"
)
_EVIDENCE_LABEL = _compile(
    r"(?:我的(?:证明|论证|推导|答案)(?:如下|内容|过程)?|证明如下|"
    r"my\s+(?:proof|argument|answer|solution)(?:\s+is(?:\s+as follows)?)?)\s*[:：]"
)
_CHECK_VERB = _compile(r"检查|核对|审阅|诊断|点评|\b(?:check|verify|review|critique|assess|evaluate)\b")
_LIVE_REQUIREMENT = _compile(
    r"(?:^|\n|[。.!?;；])\s*(?:本次要求|本轮要求|我的要求|现在的要求|request|current request|instruction)\s*[:：]"
    r"|\n[ \t]*(?=请先(?:指出|检查|核对|找出)|现在请|please\s+first\b|now\s+please\b)"
)


def _mask_checking_evidence(value):
    """An explicitly labeled submitted proof is evidence, not new commands.

    Keep the checking lead-in and allow a separately labeled current request
    to resume live instructions. Do not guess where unmarked prose ends.
    """
    spans = []
    for marker in _EVIDENCE_LABEL.finditer(value):
        if not _CHECK_VERB.search(value[:marker.start()]):
            continue
        end = _LIVE_REQUIREMENT.search(value, marker.end())
        spans.append((marker.end(), end.start() if end else len(value)))
    for start, end in reversed(spans):
        value = value[:start] + re.sub(r"[^\n]", " ", value[start:end]) + value[end:]
    return value

_METHOD_RESTRICTION = _compile(
    r"(?:不要|别|不用|无需|不必)\s*(?:再)?(?:用|使用|采用)\s*"
    r"(?:反证法|归纳法|数学归纳法|直接证明|间接证明|构造法|非构造法|枚举法)"
    r"|\b(?:do not|don't|dont|avoid)\s+(?:use|using)\s+(?:a\s+)?"
    r"(?:(?:proof\s+by|method\s+of)\s+)?(?:contradiction|induction|construction|direct proof)\b"
)
_DISCUSSION = _compile(
    r"(?:是什么意思|这个词|这个说法|这句话|原话|翻译成|如何翻译|怎么翻译|的定义是什么)"
    r"|\b(?:meaning of|translate|translation|what does .{0,50} mean|"
    r"the (?:word|phrase|sentence|title|instruction) (?:is|means|says)|"
    r"(?:the )?(?:teacher|textbook|problem|exercise) (?:says|asks|requires))\b"
)
_SEPARATOR = _compile(r"[\n,，;；。.!?？！]+|\b(?:but|however|actually|instead)\b|但是|不过|而是|改成|改为")
_FUTURE = _compile(
    r"等(?:我|我们|你|做完|完成|写完|说).{0,35}(?:再|后|时)|以后|稍后|待会|之后再|下次|明天|将来"
    r"|\b(?:later|afterwards|tomorrow|next time|not yet|not now)\b"
    r"|\b(?:only\s+)?(?:after|when|once|if)\s+(?:i|we|you)\b"
)
_CONDITION = _compile(r"^(?:\s*(?:等|待))|\b(?:after|when|once|if)\s+(?:i|we|you)\b")
_NOW = _compile(r"现在|目前|这会儿|本轮|\b(?:right now|for now|now|at present)\b")

_GAP = r"(?:(?!检查|核对|解释|定义|翻译|提示|思路|不要|不用|无需|不必|不需要|别)[^\n,;。.!?]){0,28}?"
_PROOF = r"(?:证明|论证|解答|解析|推导|答案|解题过程)(?!思路|方法|题|练习|的(?:定义|提示|思路|方法))"
_EN_PROOF = r"(?:proof|solution|answer|derivation)(?!\s+(?:exercises?|problems?|questions?|hints?|tips?|ideas?|methods?)\b)"
_QUALIFIER = r"(?:complete|full|rigorous|direct|detailed|whole|entire|corrected|revised|updated|step[- ]by[- ]step)"

_POSITIVE = {
    "full_solution": [
        _compile(r"(?:给(?:我|出)?|写(?:出|成)?|提供|展示|补全|想要|需要|我要|现在要)" + _GAP + r"(?:" + _PROOF + r"|" + _EN_PROOF + r"\b)"),
        _compile(r"(?:请(?:你)?|麻烦(?:你)?|帮我|为我|替我|能否|可否|能不能|可以(?:帮我)?)" + _GAP + r"(?:证明|证出来)(?!思路|方法|题|练习|的(?:提示|思路|方法))"),
        _compile(r"(?:把|将).{0,20}(?:证明|论证|解答|推导).{0,12}(?:写|补|讲)(?:得|到)?(?:完整|齐全|清楚)"),
        _compile(r"(?:一步一步|逐步|从头到尾|从开始到结束).{0,15}(?:证出来|证明|推导|解出来|讲|说明)"),
        _compile(r"(?:完整|详细|严谨|严格|全部)(?:地)?(?:写出来|证出来|解出来|讲解)"),
        _compile(r"\b(?:write|give|provide|present|construct|show|explain)\b(?:\s+(?:me|us|out|a|an|the|this|that|new|replacement|another|of|its|please))*\s+(?:" + _QUALIFIER + r"\s+)*" + _EN_PROOF + r"\b"),
        _compile(r"\b(?:please|could you|can you|would you|will you)\s+(?:please\s+)?(?:prove|show)\b"),
        _compile(r"\bprove\s+(?:it|this)\b(?:\s+rigorously)?"),
        _compile(r"\b(?:walk|take)\s+me\s+through\s+(?:(?:the|this|a)\s+)?(?:(?:whole|entire|complete|full)\s+)?(?:proof|solution|argument)\b"),
        _compile(r"\b(?:i (?:need|want)|i would like)\s+(?:a\s+)?(?:" + _QUALIFIER + r"\s+)*" + _EN_PROOF + r"\b"),
        _compile(r"\b(?:write|work|spell)\s+(?:it|this)\s+out\s+(?:completely|in full|step by step)\b"),
    ],
    "hint": [
        _compile(r"(?:只|仅|给(?:我)?|来|要|请).{0,12}(?:提示|思路|方向|下一步|第一步|方法)(?!是什么意思)"),
        _compile(r"(?:提示一下|指(?:个|一条|一下)?方向|指点(?:一下)?|别揭底|不要揭底|别剧透|不要剧透|帮我(?:入手|开个头))"),
        _compile(r"\b(?:help me (?:get started|start)|just a nudge|only a hint|just (?:one|a) hint|no spoilers)\b"),
        _compile(r"\b(?:give|provide|offer|need|want)\b(?:\s+(?:me|us|only|just|a|one|some|the|little))*\s+(?:hints?|nudges?|pointers?|next step|first step)\b"),
        _compile(r"\b(?:only|just)\s+(?:(?:give|show|tell)\s+)?(?:me\s+)?(?:the\s+)?(?:hints?|next step|first step|method)\b"),
    ],
    "check_answer": [
        _compile(r"(?:检查|核对|检验|审阅|诊断|点评|评估|看看).{0,30}(?:证明|答案|作答|推理|推导|论证|解法|这一步|是否|哪里|漏洞|有没有错)"),
        _compile(r"(?:只|请|帮我)?(?:检查|核对)(?:一下|这一步|一下这一步)?$"),
        _compile(r"(?:指出|找出|找找).{0,25}(?:错|漏洞|不严谨|问题)|(?:哪里|哪一步|哪儿).{0,8}(?:错|不严谨|有问题)"),
        _compile(r"(?:我.{0,12}(?:证明|答案|解法|作答|推理)).{0,12}(?:对不对|是否正确|正确吗|有错吗|严谨吗|行吗)"),
        _compile(r"\b(?:check|verify|review|critique|assess|evaluate)\s+(?:only\s+)?(?:(?:whether|if)\s+)?(?:(?:this|that|my|the|our|following)\s+)?(?:(?:new|revised|updated|complete|full|draft|own|attached|proposed)\s+)*(?:proof|solution|answer|argument|reasoning|work)\b"),
        _compile(r"\bis\s+(?:this|that|my|the|our)\s+(?:proof|argument|answer|solution)\s+(?:valid|correct|sound|rigorous)\b"),
        _compile(r"\b(?:find|locate|point out)\s+(?:the\s+)?(?:flaws?|errors?|mistakes?|gaps?)\b|\bwhere\s+did\s+i\s+go\s+wrong\b"),
    ],
}

_NEGATIVE = {
    "full_solution": [
        _compile(r"(?:不要|不用|无需|不必|不需要|不想要?|不希望|禁止|不许|别|先别|暂不)\s*(?:(?:再|另|重新|先|你|给我|给|提供|写出|写|展开|完整|直接|一个|一份|新的|最终|标准|答案的|这份|full|complete|rigorous)\s*)*(?:" + _PROOF + r"|" + _EN_PROOF + r"\b|重写|证明一遍)"),
        _compile(r"\b(?:do not|don't|dont|never|without|no need to)\s+(?:(?:give|show|provide|write|rewrite|reveal|include|prove|tell|its|me|a|an|the|new|replacement|full|complete|whole|rigorous)\s+)*(?:" + _EN_PROOF + r"|prove it|rewrite it)\b"),
        _compile(r"\bno\s+(?:(?:full|complete|replacement|new)\s+)?(?:proof|solution|answer)\b(?:\s+(?:needed|required))?"),
        _compile(r"\bi\s+(?:don't|do not|dont)\s+(?:need|want)\s+(?:a\s+)?(?:(?:full|complete|new)\s+)?(?:proof|solution|answer)\b"),
        _compile(r"\b(?:don't|do not|dont)\s+(?:want|need)\s+you\s+to\s+(?:prove\s+(?:it|this|that)|(?:write|give|provide)\s+(?:a\s+)?(?:(?:complete|full)\s+)?(?:proof|solution|answer))\b"),
    ],
    "hint": [
        _compile(r"(?:不要|不用|不需要|别)\s*(?:再|只|仅|给我|给|一点|一些)*\s*(?:提示|思路|方向)"),
        _compile(r"\b(?:do not|don't|dont|never)\s+(?:(?:only|just|give|me|any)\s+)*hints?\b|\bno\s+hints?\b"),
        _compile(r"\bnot\s+(?:just|only)\s+(?:a\s+)?hints?\b"),
    ],
    "check_answer": [
        _compile(r"(?:不要|不用|不需要|别)\s*(?:再|只|仅|帮我)*\s*(?:检查|核对|审阅|诊断|点评)"),
        _compile(r"\b(?:do not|don't|dont|never|no need to)\s+(?:(?:only|just)\s+)?(?:check|verify|review|critique|assess)\b"),
    ],
}
_CANCEL = _compile(r"算了|取消刚才|先不用了|\b(?:never mind|nevermind|forget that|cancel that|scratch that)\b")


@dataclass(frozen=True)
class _Event:
    start: int
    end: int
    mode: str
    negative: bool = False


def _events(clause):
    negative = [_Event(m.start(), m.end(), mode, True)
                for mode, rules in _NEGATIVE.items() for rule in rules
                for m in rule.finditer(clause)]
    positive = []
    for mode, rules in _POSITIVE.items():
        for rule in rules:
            for match in rule.finditer(clause):
                # A forbidden action must not be rediscovered as a positive
                # command inside the same negative phrase.
                if any(n.mode == mode and match.start() < n.end and n.start < match.end() for n in negative):
                    continue
                positive.append(_Event(match.start(), match.end(), mode))
    bare = clause.strip().strip("吧呀啊，谢谢 ")
    if re.fullmatch(r"(?:完整|严谨|严格|详细)(?:的)?(?:证明|解析|解答|推导)|答案(?:和|与|及)解析|(?:a |the )?(?:full|complete|rigorous) (?:proof|solution|answer)|提示", bare):
        mode = "hint" if bare == "提示" else "full_solution"
        positive.append(_Event(0, len(clause), mode))
    # Specific diagnostic requests outrank a proof noun matched inside them.
    checks = [e for e in positive if e.mode == "check_answer"]
    positive = [e for e in positive if e.mode != "full_solution" or not any(
        e.start < c.end and c.start < e.end for c in checks)]
    return sorted(set(negative + positive), key=lambda e: (e.start, e.end, e.negative))


def _deferred(clause, event, inherited):
    before = clause[:event.start]
    future = list(_FUTURE.finditer(before))
    now = list(_NOW.finditer(before))
    if future or now:
        inherited = bool(future) and (not now or future[-1].start() > now[-1].start())
    # Postposed conditions belong to this request, not an unrelated later verb.
    after = clause[event.end:]
    suffix = _FUTURE.search(after)
    if suffix and not re.search(r"给|检查|提示|\b(?:give|check|write|show|provide)\b", after[:suffix.start()]):
        tail = after[suffix.end():]
        if not re.search(r"再(?:给|检查|提示)|\b(?:give|check|write|show|provide)\b", tail):
            inherited = True
    # A condition may begin within a verb phrase ("give ... only after ...").
    if _FUTURE.search(clause[event.start:event.end]):
        inherited = True
    return inherited


def classify_tutoring_request(text):
    """Return ``{mode, explicit}`` for a current, unquoted tutoring request.

    Later live instructions win. A refusal to reveal a proof/answer selects
    hints, but does not turn a request to *check* an existing proof into a new
    solution. Deferred instructions only revoke their corresponding current
    mode; they never grant permission to execute the future task now.
    """
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = re.sub(r"(?<=\w)[’‘](?=\w)", "'", value)
    value = _mask_code(value)
    for literal in _LITERALS:
        value = literal.sub(_blank, value)
    value = _LABELED_PROBLEM.sub(_blank, value)
    value = _mask_checking_evidence(value)
    value = _METHOD_RESTRICTION.sub(_blank, value)
    # Exercise generation has a separate router. A prohibition on attaching
    # its solution is not itself a request for tutoring hints.
    if classify_exercise_request(value)["is_exercise"]:
        return {"mode": None, "explicit": False}
    mode = None
    full_answer_requested = False
    conditional = False
    for clause in _SEPARATOR.split(value):
        if not clause.strip():
            continue
        if _DISCUSSION.search(clause):
            continue
        events = _events(clause)
        for event in events:
            if _deferred(clause, event, conditional):
                if mode == event.mode:
                    mode = None
                continue
            if event.negative:
                if event.mode == "full_solution":
                    if mode != "check_answer":
                        refused = clause[event.start:event.end]
                        if not (mode == "full_solution" and full_answer_requested
                                and re.search(r"解析|推导|过程", refused)
                                and not re.search(r"答案|证明|解答", refused)):
                            mode = "hint"
                elif mode == event.mode:
                    mode = None
            else:
                mode = event.mode
                full_answer_requested = mode == "full_solution" and bool(
                    re.search(r"答案|\banswer\b", clause[event.start:event.end]))
        cancellation = _CANCEL.search(clause)
        if cancellation and not any(e.start >= cancellation.end() for e in events):
            mode = None
        conditional = bool(_CONDITION.search(clause) and _FUTURE.search(clause) and not events)
    return {"mode": mode, "explicit": mode is not None}
