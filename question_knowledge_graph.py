"""Source-bound topic usage for one problem, independent of the course graph.

The catalog supplies names and aliases only. Its prerequisite edges are never
read here: co-occurrence, a shared module, and topic order do not prove that one
step of a particular solution depends on another.
"""
from __future__ import annotations

import re
from functools import lru_cache


# These broad words describe a setting, not the more specific catalog topic.
# More specific aliases and mathematical structure can still identify the topic.
_SETTING_WORDS = frozenset({
    "集合", "子集", "函数", "映射", "关系", "图论", "图", "像", "计数", "递推", "命题", "真值",
})
_NEGATIVE_USAGE = re.compile(
    r"(?:不(?:需要|涉及|使用|采用|考(?:查|察)?|必)|不能(?:够)?(?:使用|采用|用)|不可(?:使用|采用|用)|"
    r"禁止(?:使用|采用|用)|无需|无须|不用|不要|未(?:涉及|使用)|无关|不相关|不适用|"
    r"\b(?:not\s+(?:needed|used?|using|involved|involving|required|requiring)|do(?:es)?\s+not|without|unrelated|"
    r"cannot\s+(?:use|apply)|must\s+not\s+(?:use|apply))\b)", re.I,
)
_BACKGROUND = re.compile(
    r"拓展|延伸|额外练习|另一个例子|举例|例如|比如|假如|上一题|上道题|前一道题|昨天.{0,12}做过|"
    r"\b(?:extension|further\s+(?:reading|study)|for\s+example|e\.g\.|suppose\s+instead)\b", re.I,
)
_CLAUSE = re.compile(r"[^。！？!?；;\n]+(?:[。！？!?；;\n]|$)")
_USE = r"(?:利用|使用|采用|根据|借助|通过|由|\busing\b|\buse\b|\bapply\b|\bapplying\b|\bbased\s+on\b)"
_GOAL = r"(?:求(?:出|解)?|计算|判断|证明|验证|得到|推得|推出|构造|确定|解(?:出)?|\b(?:to\s+)?(?:find|compute|calculate|prove|determine|derive|obtain|solve|construct)\b)"
_CONTRAST = re.compile(r"但是|然而|而是|不过|但|\b(?:but|however|instead)\b", re.I)
_CAUSAL = re.compile(r"^\s*(?:由此|据此|因此|从而|进而|利用上述结果|根据上述结果|"
                     r"(?:thus|hence|thereby|using\s+(?:this|that|the\s+result))\b)", re.I)
MAX_EVIDENCE_CHARS = 512
_EXCLUDED_AFTER = re.compile(
    r"^\s*(?:不是|并非|不属于|不算)(?:本题|该题|这道题|当前题|题目)?(?:的)?"
    r"(?:考点|知识点|考查内容|考察内容|所需|需要|涉及|方法|内容)|"
    r"^\s*(?:与本题无关|不需要|不适用|没有使用|未使用)")
_OPTIONAL_METHOD = re.compile(r"可(?:以)?(?:用|选)|任选|任意选|任选一种|任一(?:种)?方法|"
                              r"\b(?:may\s+use|either|choose\s+(?:one|any))\b", re.I)


def _excluded_mentions(analyzed, mentions):
    """Exclude the mentioned method, without erasing its actual proof target."""
    excluded = set()
    for start, end, name in mentions:
        before, after = analyzed[:start], analyzed[end:end + 56]
        negative = list(_NEGATIVE_USAGE.finditer(before))
        if _EXCLUDED_AFTER.search(after):
            excluded.add(name)
        elif negative:
            between = before[negative[-1].end():]
            if len(between) <= 100 and not re.search(_GOAL, between, re.I):
                excluded.add(name)
    return excluded


@lru_cache(maxsize=8)
def _canonical_english_patterns(labels):
    patterns = []
    for name, label in labels:
        if not label or label == name or not re.search(r"[A-Za-z]", label):
            continue
        label = re.sub(r"^the\s+", "", label.strip(), flags=re.I)
        words = re.split(r"(\s+|[–—-]|['’])", label)
        def word_pattern(word):
            if word.isspace():
                return r"\s+"
            if word in "–—-":
                return r"[–—-]"
            if word in ("'", "’"):
                return r"['’]"
            # Canonical display labels often use plural nouns. Keep ordinary
            # singular forms without replacing a full phrase by generic words.
            if re.fullmatch(r"[A-Za-z]{4,}", word):
                if word.endswith("ies"):
                    return re.escape(word[:-3]) + r"(?:y|ies)"
                if word.endswith(("ches", "shes", "xes", "zes", "sses")):
                    return re.escape(word[:-2]) + r"(?:es)?"
                if word.endswith("s") and not word.endswith(("ss", "us", "is", "ics")):
                    return re.escape(word[:-1]) + "s?"
            return re.escape(word)
        expression = "".join(word_pattern(word) for word in words if word)
        patterns.append((name, re.compile(r"(?<![A-Za-z])(?:the\s+)?" + expression + r"(?![A-Za-z])", re.I)))
    return patterns


def _canonical_topic_spans(text, patterns):
    matches = [(match.start(), match.end(), name) for name, pattern in patterns
               for match in pattern.finditer(text)]
    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0], item[2]))
    chosen = []
    for item in matches:
        if not any(item[0] < other[1] and other[0] < item[1] for other in chosen):
            chosen.append(item)
    return chosen


def _canonical_topic_text(text, patterns):
    """Recognize full original labels before generic 'sets/functions' aliases."""
    for start, end, name in sorted(_canonical_topic_spans(text, patterns), reverse=True):
        text = text[:start] + name + text[end:]
    return text


def _usage_units(clause, protected=()):
    """Comma clauses are independent; commas inside mathematical data are not."""
    brackets, dollar, start = [], False, 0
    boundaries = []
    pairs = {")": "(", "]": "[", "}": "{", "）": "（"}
    for index, char in enumerate(clause):
        if char == "$" and (not index or clause[index - 1] != "\\"):
            dollar = not dollar
        if dollar:
            continue
        if char in "([{（":
            brackets.append(char)
        elif char in pairs and brackets and brackets[-1] == pairs[char]:
            brackets.pop()
        elif char in ",，" and not brackets:
            if any(left <= index < right for left, right, _name in protected):
                continue
            if char == "," and index and index + 1 < len(clause) and clause[index - 1].isdigit() and clause[index + 1].isdigit():
                continue
            boundaries.append((start, index))
            start = index + 1
    boundaries.append((start, len(clause)))
    for start, end in boundaries:
        # A contrast explicitly ends the preceding negative/background scope.
        cuts = [start, *(start + match.start() for match in _CONTRAST.finditer(clause[start:end])
                         if match.start()), end]
        for left, right in zip(cuts, cuts[1:]):
            text = clause[left:right]
            if text.strip():
                yield left, right, text.strip(), bool(_CONTRAST.match(text.lstrip()))


def _windows(text):
    """Bound each literal evidence span without cutting all long-source usage."""
    for start in range(0, len(text), MAX_EVIDENCE_CHARS - 128):
        quote = text[start:start + MAX_EVIDENCE_CHARS].strip()
        if quote:
            yield quote
        if start + MAX_EVIDENCE_CHARS >= len(text):
            break


def _dependencies(analyzed, mentions):
    for index, (start, end, left) in enumerate(mentions):
        for target_start, target_end, right in mentions[index + 1:]:
            if left == right or target_start - end > 180:
                continue
            before = analyzed[max(0, start - 48):start]
            between = analyzed[end:target_start]
            after = analyzed[target_end:target_end + 48]
            # The goal must directly target the next named concept. An earlier
            # "compute" followed by an independent "then discuss B" proves no
            # A -> B relationship, even if no comma was written.
            if re.search(_USE + r"(?:\s+(?:the|a|an))?\s*$", before, re.I) and re.search(
                    _GOAL + r"(?:\s+(?:the|a|an))?\s*$", between, re.I):
                yield left, right
            elif re.search(r"(?:依赖|需要先(?:求|用)?|\bdepends?\s+on\b|\brequires?\b)\s*$", between, re.I):
                yield right, left
            elif re.search(r"(?:是|作为)\s*$", between) and re.match(r"(?:的)?(?:前提|依据|基础|必要步骤)", after):
                yield left, right


def _mentions(text, aliases, catalog_by_name, categories):
    """Match maximal aliases, avoiding 'tree' inside 'spanning tree', etc."""
    matches = []
    for name, words in aliases.items():
        for word in words:
            if not word or word in _SETTING_WORDS:
                continue
            # Short aliases are often shared with a different mathematical
            # setting (graph/algebra isomorphism, a ring/necklace, etc.). Use
            # the source's own classification, never a catalog neighbor.
            if word != name and len(word) <= 2 and word not in {"整除", "素数", "质数", "因数", "因子", "约数", "互质"} and categories is not None \
                    and catalog_by_name[name].get("category") not in categories:
                continue
            pattern = re.escape(word)
            if re.search(r"[A-Za-z]", word):
                pattern = r"(?<![A-Za-z])" + pattern + r"(?![A-Za-z])"
            for match in re.finditer(pattern, text, re.I):
                if word == "域" and match.start() and text[match.start() - 1] in "论义值陪体":
                    continue
                if word == "环" and text[match.end():match.end() + 1] == "节":
                    continue
                matches.append((match.start(), match.end(), name))
    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0], item[2]))
    chosen = []
    for item in matches:
        if any(item[0] < other[1] and other[0] < item[1] for other in chosen):
            continue
        chosen.append(item)
    return sorted(chosen)


def build_question_graph(question_text, solution_text, catalog, aliases, structural_evidence, translate,
                         context_categories=None, canonical_labels=None, task_structural_evidence=None):
    """Return only literal-source-backed nodes and explicit step dependencies.

    ``structural_evidence`` recognizes mathematical notation through the same
    general classifier used by the app, and returns catalog topic names. Quotes
    always come from the original source, never translated or generated text.
    """
    sources = {"question": str(question_text or ""), "solution": str(solution_text or "")}
    by_name = {node["name"]: node for node in catalog
               if isinstance(node, dict) and isinstance(node.get("id"), str)
               and isinstance(node.get("name"), str)}
    aliases = {name: sorted(set([name, *aliases.get(name, [])]), key=lambda value: (-len(value), value))
               for name in by_name}
    english_patterns = _canonical_english_patterns(tuple(sorted((canonical_labels or {}).items())))
    analyze = lambda text: translate(_canonical_topic_text(text, english_patterns))
    evidence_by_name = {}
    task_evidence_by_name = {}
    edges = {}
    forbidden, optional, used, assessed = set(), set(), set(), set()
    for source, text in sources.items():
        source_categories = context_categories(analyze(text)) if context_categories else None
        for found in _CLAUSE.finditer(text):
            for _start, _end, unit, _contrast in _usage_units(found.group(), _canonical_topic_spans(found.group(), english_patterns)):
                analyzed = analyze(unit)
                categories = source_categories
                mentions = _mentions(analyzed, aliases, by_name, categories)
                excluded = _excluded_mentions(analyzed, mentions)
                if source == "question":
                    forbidden.update(excluded)
                    method_choice = _OPTIONAL_METHOD.search(analyzed)
                    if method_choice:
                        goal = re.search(_GOAL, analyzed[method_choice.end():], re.I)
                        limit = method_choice.end() + goal.start() if goal else len(analyzed)
                        optional.update(name for start, _end, name in mentions if start < limit)
                    elif not _BACKGROUND.search(analyzed):
                        assessed.update(name for name in [*structural_evidence(analyzed), *structural_evidence(unit)] if name not in excluded)
                elif not _BACKGROUND.search(analyzed):
                    used.update(name for _start, _end, name in mentions if name not in excluded)
                    used.update(name for name in [*structural_evidence(analyzed), *structural_evidence(unit)] if name not in excluded)
    excluded_names = forbidden | (optional - used - assessed)

    for source, text in sources.items():
        source_categories = context_categories(analyze(text)) if context_categories else None
        positive_units = []
        clauses = [part for found in _CLAUSE.finditer(text)
                   for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", found.group())]
        for clause in clauses:
            background, previous = False, None
            for start, end, unit, contrast in _usage_units(clause, _canonical_topic_spans(clause, english_patterns)):
                analyzed = analyze(unit)
                if contrast:
                    background, previous = False, None
                if _BACKGROUND.search(analyzed) or _BACKGROUND.search(unit):
                    background = True
                categories = source_categories
                mentions = _mentions(analyzed, aliases, by_name, categories)
                unit_excluded = _excluded_mentions(analyzed, mentions) | excluded_names
                negative = _NEGATIVE_USAGE.search(analyzed)
                # A prohibition concerns its named method. Mathematical goals
                # later in the same unit still describe actual assessed topics.
                only_negative = negative and not _excluded_mentions(analyzed, mentions) \
                    and not re.search(_GOAL, analyzed[negative.end():], re.I)
                if background or only_negative:
                    previous = None
                    continue
                positive_units.append(unit)
                mentions = [item for item in mentions if item[2] not in unit_excluded]
                for quote in _windows(unit):
                    window = analyze(quote)
                    local_mentions = _mentions(window, aliases, by_name, categories)
                    evidence = {"source": source, "quote": quote}
                    names = {name for _left, _right, name in local_mentions}
                    names.update(name for name in structural_evidence(window) if name in by_name)
                    names.update(name for name in structural_evidence(quote) if name in by_name)
                    names.difference_update(unit_excluded)
                    task_names = (set([*task_structural_evidence(window), *task_structural_evidence(quote)])
                                  if task_structural_evidence else set()).intersection(by_name) - unit_excluded
                    names.update(task_names)
                    for name in names:
                        records = evidence_by_name.setdefault(name, [])
                        if evidence not in records and len(records) < 8:
                            records.append(evidence)
                    for name in task_names:
                        records = task_evidence_by_name.setdefault(name, [])
                        if evidence not in records and len(records) < 8:
                            records.append(evidence)
                    for pair in _dependencies(window, [item for item in local_mentions if item[2] not in unit_excluded]):
                        records = edges.setdefault(pair, [])
                        if evidence not in records and len(records) < 8:
                            records.append(evidence)

                # Crossing a comma requires an explicit causal reference to the
                # previous result, not merely another instruction afterwards.
                if previous and mentions and _CAUSAL.match(analyzed):
                    prior_start, prior_text, prior_mentions = previous
                    span = clause[prior_start:end].strip()
                    if prior_mentions and len(span) <= MAX_EVIDENCE_CHARS:
                        point_start, _point_end, left = prior_mentions[-1]
                        prefix = prior_text[:point_start]
                        prior_is_result = re.search(_GOAL + r"(?:\s+(?:the|a|an))?\s*$", prefix, re.I)
                        prior_is_method = len(prior_mentions) == 1 and re.search(
                            _USE + r"(?:\s+(?:the|a|an))?\s*$", prefix, re.I)
                        if prior_is_result or prior_is_method:
                            for point_start, _point_end, right in mentions:
                                if left != right and re.search(_GOAL + r"(?:\s+(?:the|a|an))?\s*$", analyzed[:point_start], re.I):
                                    evidence = {"source": source, "quote": span}
                                    records = edges.setdefault((left, right), [])
                                    if evidence not in records and len(records) < 8:
                                        records.append(evidence)
                previous = (start, analyzed, mentions)

        # Definitions and the mathematical task often occupy different clauses.
        # Recognize their combined structure without adding course neighbors.
        complete = " ".join(positive_units)
        contextual = set([*structural_evidence(analyze(complete)), *structural_evidence(complete)]) - excluded_names
        contextual_tasks = (set([*task_structural_evidence(analyze(complete)), *task_structural_evidence(complete)])
                            if task_structural_evidence else set()).intersection(by_name) - excluded_names
        contextual.update(contextual_tasks)
        contextual_ids = {by_name[name].get("id") for name in contextual if name in by_name}
        predicate_task = "predicate_quantifier" in contextual_ids
        relation_task = "relation_property" in contextual_ids
        specific_logic = (predicate_task and not re.search(r"(?<![A-Za-z])[pqr](?![A-Za-z(])", text, re.I)) \
            or (relation_task and not re.search(r"(?<![A-Za-z])[pq](?![A-Za-z(])", text, re.I))
        if specific_logic:
            for name, node in by_name.items():
                if node.get("id") in {"logic_connectives", "logic_equivalence"}:
                    evidence_by_name.pop(name, None)
                    task_evidence_by_name.pop(name, None)
                    contextual.discard(name)
                    contextual_tasks.discard(name)
        for name in contextual.intersection(by_name):
            if name in evidence_by_name and name not in contextual_tasks:
                continue
            if len(text) <= MAX_EVIDENCE_CHARS:
                quotes = [text.strip()] if text.strip() else []
            else:
                # Keep literal pieces from both definition and task rather than
                # manufacture one quote by concatenating separate source spans.
                quotes = list(_windows(positive_units[0]))[:1] + list(_windows(positive_units[-1]))[-1:] if positive_units else []
            records = [{"source": source, "quote": quote} for quote in dict.fromkeys(quotes)]
            if name not in evidence_by_name:
                evidence_by_name[name] = records
            if name in contextual_tasks:
                task_records = task_evidence_by_name.setdefault(name, [])
                task_records.extend(record for record in records if record not in task_records)

    def node_evidence(name):
        records = []
        for record in [*task_evidence_by_name.get(name, []), *evidence_by_name[name]]:
            if record not in records:
                records.append(record)
        return records[:8]

    return {
        "version": 1,
        "sources": sources,
        "nodes": [{"id": node["id"], "evidence": node_evidence(node["name"]),
                   "origin": "task_structure" if task_evidence_by_name.get(node["name"]) else "term_candidate"}
                  for node in catalog if node.get("name") in evidence_by_name],
        "edges": [{"from": by_name[left]["id"], "to": by_name[right]["id"], "evidence": evidence}
                  for (left, right), evidence in edges.items() if left in evidence_by_name and right in evidence_by_name],
    }
