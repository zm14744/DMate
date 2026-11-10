"""Conservative, deterministic checks for small explicit finite relations.

Unrecognized notation returns None instead of guessing. No model/network calls.
"""

import re


def _small_finite_relation(question):
    source = (str(question or "")
              .replace(r"\{", "{").replace(r"\}", "}")
              .replace(r"\left", "").replace(r"\right", "")
              .replace(r"\,", ""))
    universe = re.search(r"(?<![A-Za-z0-9_])A\s*=\s*\{([^{}]{1,90})\}", source, re.I)
    relation = re.search(r"(?<![A-Za-z0-9_])R\s*=\s*\{([^{}]{1,300})\}", source, re.I)
    if not universe or not relation:
        return None
    numbers = universe.group(1)
    if re.sub(r"[\d,\s]", "", numbers):
        return None
    vertices = [int(part.strip()) for part in numbers.split(",") if part.strip()]
    if not 1 <= len(vertices) <= 8 or len(vertices) != len(set(vertices)):
        return None

    pairs_source = relation.group(1)
    pair_pattern = r"\(\s*(\d+)\s*,\s*(\d+)\s*\)"
    matches = re.findall(pair_pattern, pairs_source)
    if not matches or re.sub(pair_pattern + r"|[\s,]", "", pairs_source):
        return None
    if len(matches) > 32:
        return None
    edges = {(int(a), int(b)) for a, b in matches}
    return set(vertices), edges


def _closure_question_part(question):
    """Return the numbered part that requests closure cardinality, if present."""
    text = str(question or "")
    if not re.search(r"传递闭包|transitive\s+closure", text, re.I):
        return None
    if not re.search(r"有序对|个数|数量|多少|数目|ordered\s+pairs?|cardinality", text, re.I):
        return None
    markers = list(re.finditer(r"(?m)^[ \t]*[（(]\s*(\d{1,2})\s*[)）]", text))
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        part = text[marker.end():end]
        if re.search(r"传递闭包|transitive\s+closure", part, re.I) and re.search(
                r"有序对|个数|数量|多少|数目|ordered\s+pairs?|cardinality", part, re.I):
            return marker.group(1)
    return "" if not markers else None


def _explicit_closure_count(answer, number):
    """Read a cardinality only when it is unambiguous; no free digit guessing."""
    text = str(answer or "").strip()
    if number:
        markers = list(re.finditer(r"(?m)^[ \t]*[（(]\s*(\d{1,2})\s*[)）]", text))
        for index, marker in enumerate(markers):
            if marker.group(1) != number:
                continue
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            text = text[marker.end():end].strip().lstrip("：:").strip()
            break
        else:
            return None
    # Examples: 16, "共有 16 个有序对", "个数为 16".
    plain = re.fullmatch(r"\$?\s*(\d{1,3})\s*(?:个(?:有序对)?|对)?[。.!！]?\s*\$?", text)
    if plain:
        return int(plain.group(1))
    patterns = (
        r"(?:个数|数量|总数|数目|cardinality)\s*(?:为|是|等于|共有|[:：=])?\s*(\d{1,3})",
        r"(?:共有|共|总共|有)\s*(\d{1,3})\s*(?:个)?有序对",
        r"(?:closure\s+(?:contains|has)|there\s+are)\s*(\d{1,3})\s*(?:ordered\s+pairs?)?",
    )
    found = [int(m.group(1)) for expr in patterns for m in re.finditer(expr, text, re.I)]
    return found[0] if found and len(set(found)) == 1 else None


def verify_relation_closure_count(question, answer):
    """Return False for a provably wrong closure count, True if exact, else None.

    Only applies to explicit A={numbers}, R={(i,j),...} questions that ask
    for the number of pairs in the transitive closure. Unknown formats are
    left to normal validation rather than incorrectly rejected.
    """
    part = _closure_question_part(question)
    if part is None:
        return None
    parsed = _small_finite_relation(question)
    if parsed is None:
        return None
    vertices, edges = parsed
    if any(a not in vertices or b not in vertices for a, b in edges):
        return False
    observed = _explicit_closure_count(answer, part)
    if observed is None:
        return None
    closure = set(edges)
    for middle in vertices:
        for start in vertices:
            if (start, middle) in closure:
                for end in vertices:
                    if (middle, end) in closure:
                        closure.add((start, end))
    return observed == len(closure)


def is_routine_small_relation_question(question, subquestion_count=0):
    """Avoid calling small, direct matrix/property/closure drills 'hard'."""
    parsed = _small_finite_relation(question)
    if parsed is None:
        return False
    vertices, edges = parsed
    if len(vertices) > 5 or len(edges) > 12 or not 2 <= subquestion_count <= 3:
        return False
    source = str(question or "").lower()
    if not ("关系矩阵" in source and "闭包" in source
            and any(term in source for term in ("自反", "对称", "传递"))):
        return False
    if re.search(r"(?:证明|求证|构造|推广|一般情形|任意\s*n|所有方案|枚举所有|"
                 r"极值|最大|最小|最多|最少|至少|至多|恰好|分类讨论|"
                 r"特征值|矩阵树定理|群同态)", source):
        return False
    return all(a in vertices and b in vertices for a, b in edges)
