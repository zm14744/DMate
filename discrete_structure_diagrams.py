"""Deterministic finite graph and tree constructions for the drawing workspace.

Natural language parsing belongs to the caller. This module only accepts the
explicit structural parameters, and computes every vertex, edge and weight.
"""
from __future__ import annotations

import heapq
import itertools
import math
from fractions import Fraction


MAX_VERTICES = 80
MAX_EDGES = 240


class DiscreteStructureError(ValueError):
    pass


def _integer(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise DiscreteStructureError("invalid integer parameter")
    return value


def _text(value, *, limit=40):
    if (not isinstance(value, str) or not value.strip() or len(value.strip()) > limit
            or any(ord(char) < 32 for char in value)):
        raise DiscreteStructureError("invalid structural label")
    return value.strip()


def _fields(structure, allowed, required=()):
    if not isinstance(structure, dict) or set(structure) - set(allowed) or any(key not in structure for key in required):
        raise DiscreteStructureError("invalid structural parameters")


class _Diagram:
    def __init__(self, *, directed):
        self.directed = directed
        self.vertices = []
        self.edges = []

    def vertex(self, label):
        if len(self.vertices) >= MAX_VERTICES:
            raise DiscreteStructureError("diagram exceeds vertex limit")
        vertex_id = "v" + str(len(self.vertices))
        self.vertices.append({"id": vertex_id, "label": _text(label, limit=80)})
        return vertex_id

    def edge(self, source, target, label=None):
        if len(self.edges) >= MAX_EDGES:
            raise DiscreteStructureError("diagram exceeds edge limit")
        row = {"id": "e" + str(len(self.edges)), "from": source, "to": target,
               "direction": "forward" if self.directed else "undirected"}
        if label is not None:
            row["edge_label"] = _text(label, limit=80)
        self.edges.append(row)

    def result(self, layout):
        return self.directed, self.vertices, self.edges, layout


def _standard_graph(structure):
    _fields(structure, ("family", "order", "parts", "dimension"), ("family",))
    family = structure["family"]
    diagram = _Diagram(directed=False)
    if family in ("complete_bipartite", "complete_multipartite"):
        if "order" in structure or "dimension" in structure:
            raise DiscreteStructureError("multipartite graphs use explicit part sizes")
        parts = structure.get("parts")
        if not isinstance(parts, list) or not 2 <= len(parts) <= 16 or family == "complete_bipartite" and len(parts) != 2:
            raise DiscreteStructureError("invalid multipartite parts")
        parts = [_integer(value, 1, MAX_VERTICES) for value in parts]
        if sum(parts) > MAX_VERTICES:
            raise DiscreteStructureError("diagram exceeds vertex limit")
        groups = [[diagram.vertex(f"{chr(65 + index)}{offset + 1}") for offset in range(size)]
                  for index, size in enumerate(parts)]
        for left, right in itertools.combinations(groups, 2):
            for source in left:
                for target in right:
                    diagram.edge(source, target)
        return diagram.result("graph")
    if family == "hypercube":
        if "parts" in structure or "order" in structure:
            raise DiscreteStructureError("hypercubes use dimension")
        dimension = _integer(structure.get("dimension"), 0, 6)
        vertices = [diagram.vertex(format(value, f"0{dimension}b") if dimension else "∅")
                    for value in range(2 ** dimension)]
        for value, source in enumerate(vertices):
            for bit in range(dimension):
                other = value ^ (1 << bit)
                if value < other:
                    diagram.edge(source, vertices[other])
        return diagram.result("graph")
    if family == "petersen":
        if "parts" in structure or "dimension" in structure:
            raise DiscreteStructureError("the Petersen graph has ten vertices")
        _integer(structure.get("order", 10), 10, 10)
        vertices = [diagram.vertex(str(value)) for value in range(10)]
        for index in range(5):
            diagram.edge(vertices[index], vertices[(index + 1) % 5])
            diagram.edge(vertices[index], vertices[index + 5])
            diagram.edge(vertices[index + 5], vertices[(index + 2) % 5 + 5])
        return diagram.result("graph")
    if family not in ("complete", "cycle", "path", "star", "wheel") or "parts" in structure or "dimension" in structure:
        raise DiscreteStructureError("unsupported standard graph family")
    order = _integer(structure.get("order"), 4 if family == "wheel" else 3 if family == "cycle" else 1, MAX_VERTICES)
    vertices = [diagram.vertex(str(value)) for value in range(order)]
    if family == "complete":
        for source, target in itertools.combinations(vertices, 2):
            diagram.edge(source, target)
    elif family in ("cycle", "path"):
        for index in range(order - 1):
            diagram.edge(vertices[index], vertices[index + 1])
        if family == "cycle":
            diagram.edge(vertices[-1], vertices[0])
    elif family == "star":
        for target in vertices[1:]:
            diagram.edge(vertices[0], target)
    else:
        for index in range(1, order):
            diagram.edge(vertices[0], vertices[index])
            diagram.edge(vertices[index], vertices[index + 1 if index + 1 < order else 1])
    return diagram.result("graph")


def _full_mary_tree(structure):
    _fields(structure, ("branching", "height"), ("branching", "height"))
    branching = _integer(structure["branching"], 2, 8)
    height = _integer(structure["height"], 0, 6)
    if sum(branching ** level for level in range(height + 1)) > MAX_VERTICES:
        raise DiscreteStructureError("diagram exceeds vertex limit")
    diagram = _Diagram(directed=True)
    level = [diagram.vertex("r")]
    for _ in range(height):
        children = []
        for source in level:
            for index in range(branching):
                target = diagram.vertex(str(len(diagram.vertices)))
                diagram.edge(source, target, str(index + 1))
                children.append(target)
        level = children
    return diagram.result("rooted_tree")


def _weight_text(value):
    # JSON decimal weights have denominators containing only factors2 and5.
    # Construct exact finite decimal/scientific labels without float rounding.
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise DiscreteStructureError("nondecimal weight")
    scale = max(twos, fives)
    digits = str(value.numerator * 2 ** (scale - twos) * 5 ** (scale - fives))
    if not scale:
        plain = digits
    elif len(digits) > scale:
        plain = digits[:-scale] + "." + digits[-scale:]
    else:
        plain = "0." + "0" * (scale - len(digits)) + digits
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    if len(plain) <= 40:
        return plain
    coefficient = digits.rstrip("0")
    scientific = coefficient[0] + ("." + coefficient[1:] if len(coefficient) > 1 else "") + "e" + str(len(digits) - scale - 1)
    if len(scientific) > 50:
        raise DiscreteStructureError("exact weight label exceeds diagram limit")
    return scientific


def _huffman_tree(structure):
    _fields(structure, ("frequencies",), ("frequencies",))
    frequencies = structure["frequencies"]
    if not isinstance(frequencies, list) or not 2 <= len(frequencies) <= 32:
        raise DiscreteStructureError("specify two to32 weighted symbols")
    diagram = _Diagram(directed=True)
    pending, symbols = [], set()
    serial = itertools.count()
    for row in frequencies:
        _fields(row, ("symbol", "weight"), ("symbol", "weight"))
        symbol = _text(row["symbol"], limit=24)
        raw = row["weight"]
        if (symbol in symbols or isinstance(raw, bool) or not isinstance(raw, (int, float))
                or isinstance(raw, float) and not math.isfinite(raw) or raw <= 0
                or isinstance(raw, int) and raw.bit_length() > 6500):
            raise DiscreteStructureError("invalid Huffman symbol or weight")
        symbols.add(symbol)
        weight = Fraction(str(raw))
        vertex = diagram.vertex(symbol + ": " + _weight_text(weight))
        heapq.heappush(pending, (weight, next(serial), vertex))
    while len(pending) > 1:
        left, right = heapq.heappop(pending), heapq.heappop(pending)
        weight = left[0] + right[0]
        parent = diagram.vertex(_weight_text(weight))
        diagram.edge(parent, left[2], "0")
        diagram.edge(parent, right[2], "1")
        heapq.heappush(pending, (weight, next(serial), parent))
    return diagram.result("rooted_tree")


def _factor_tree(structure):
    _fields(structure, ("number",), ("number",))
    initial = _integer(structure["number"], 2, 1_000_000_000)
    diagram = _Diagram(directed=True)
    pending = [(initial, diagram.vertex(str(initial)))]
    while pending:
        number, source = pending.pop()
        divisor = 2
        while divisor * divisor <= number and number % divisor:
            divisor = 3 if divisor == 2 else divisor + 2
        if divisor * divisor > number:
            continue
        quotient = number // divisor
        left, right = diagram.vertex(str(divisor)), diagram.vertex(str(quotient))
        diagram.edge(source, left)
        diagram.edge(source, right)
        pending.append((quotient, right))
    return diagram.result("rooted_tree")


def _choice_tree(structure):
    _fields(structure, ("choices", "root_label"), ("choices",))
    choices = structure["choices"]
    if not isinstance(choices, list) or len(choices) > 6:
        raise DiscreteStructureError("specify at most six choice levels")
    levels, count, product = [], 1, 1
    for values in choices:
        if not isinstance(values, list) or not 1 <= len(values) <= 16:
            raise DiscreteStructureError("invalid choices")
        values = [_text(value, limit=80) for value in values]
        if len(set(values)) != len(values):
            raise DiscreteStructureError("choices must be distinct within a level")
        levels.append(values)
        product *= len(values)
        count += product
        if count > MAX_VERTICES:
            raise DiscreteStructureError("diagram exceeds vertex limit")
    diagram = _Diagram(directed=True)
    level = [diagram.vertex(_text(structure.get("root_label", "∅"), limit=80))]
    for values in levels:
        children = []
        for source in level:
            for value in values:
                target = diagram.vertex(value)
                diagram.edge(source, target, value)
                children.append(target)
        level = children
    return diagram.result("rooted_tree")


def _recursion_tree(structure):
    _fields(structure, ("initial", "branching", "divisor", "base"), ("initial", "branching", "divisor", "base"))
    initial = _integer(structure["initial"], 1, 1_000_000_000)
    branching = _integer(structure["branching"], 1, 8)
    divisor = _integer(structure["divisor"], 2, 8)
    base = _integer(structure["base"], 1, 1_000_000_000)
    diagram = _Diagram(directed=True)
    pending = [(initial, diagram.vertex(str(initial)))]
    while pending:
        size, source = pending.pop()
        if size <= base:
            continue
        if size % divisor:
            raise DiscreteStructureError("recursion requires an explicit rounding convention")
        next_size = size // divisor
        for _ in range(branching):
            target = diagram.vertex(str(next_size))
            diagram.edge(source, target)
            pending.append((next_size, target))
    return diagram.result("rooted_tree")


def _word_transition_graph(structure):
    _fields(structure, ("alphabet", "forbidden"), ("alphabet", "forbidden"))
    alphabet, forbidden = structure["alphabet"], structure["forbidden"]
    if not isinstance(alphabet, list) or not 2 <= len(alphabet) <= 8:
        raise DiscreteStructureError("invalid finite alphabet")
    alphabet = [_text(symbol, limit=1) for symbol in alphabet]
    if len(set(alphabet)) != len(alphabet):
        raise DiscreteStructureError("alphabet symbols must be distinct")
    if not isinstance(forbidden, list) or len(forbidden) > 8:
        raise DiscreteStructureError("invalid forbidden words")
    forbidden = [_text(word, limit=6) for word in forbidden]
    if len(set(forbidden)) != len(forbidden) or any(char not in alphabet for word in forbidden for char in word):
        raise DiscreteStructureError("forbidden words must be distinct and use the alphabet")
    prefixes = {""} | {word[:length] for word in forbidden for length in range(1, len(word))}
    states = sorted((prefix for prefix in prefixes if not any(word in prefix for word in forbidden)), key=lambda value: (len(value), value))
    diagram = _Diagram(directed=True)
    vertices = {state: diagram.vertex("⟨" + state + "⟩") for state in states}
    suffixes = sorted(states, key=len, reverse=True)
    for state in states:
        for symbol in alphabet:
            appended = state + symbol
            if any(word in appended for word in forbidden):
                continue
            target = next(prefix for prefix in suffixes if appended.endswith(prefix))
            diagram.edge(vertices[state], vertices[target], symbol)
    return diagram.result("graph")


def construct_discrete_structure(kind, structure):
    if not isinstance(kind, str):
        raise DiscreteStructureError("unsupported discrete structure")
    builders = {"standard_graph": _standard_graph, "full_mary_tree": _full_mary_tree,
                "huffman_tree": _huffman_tree, "factor_tree": _factor_tree,
                "choice_tree": _choice_tree, "recursion_tree": _recursion_tree,
                "word_transition_graph": _word_transition_graph}
    builder = builders.get(kind)
    if builder is None:
        raise DiscreteStructureError("unsupported discrete structure")
    return builder(structure)
