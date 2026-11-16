"""Parse a finite propositional formula into its actual, ordered syntax tree.

This constructs a parse tree only. It does not assert that a formula or a proof
is true. Iterative parsing also handles deeply nested parentheses safely.
"""
from __future__ import annotations

import re

from discrete_structure_diagrams import DiscreteStructureError


_OPERATORS = {
    "¬": "¬", "!": "¬", "not": "¬",
    "∧": "∧", "&": "∧", "and": "∧",
    "∨": "∨", "|": "∨", "or": "∨",
    "⊕": "⊕", "^": "⊕", "xor": "⊕",
    "→": "→", "->": "→", "implies": "→",
    "↔": "↔", "<->": "↔", "iff": "↔",
}
_PRECEDENCE = {"¬": 6, "∧": 5, "⊕": 4, "∨": 3, "→": 2, "↔": 1}
_TOKEN = re.compile(r"<->|->|[()¬!∧&∨|⊕^→↔⊤⊥]|[A-Za-z_][A-Za-z0-9_]*")


def _tokens(expression):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 500:
        raise DiscreteStructureError("specify a propositional formula of at most500 characters")
    result, position, nodes = [], 0, 0
    while position < len(expression):
        if expression[position].isspace():
            position += 1
            continue
        match = _TOKEN.match(expression, position)
        if match is None:
            raise DiscreteStructureError("unknown propositional formula token")
        token = match.group()
        position = match.end()
        normalized = token.lower()
        if token in ("(", ")"):
            result.append(token)
            continue
        nodes += 1
        if nodes > 80:
            raise DiscreteStructureError("logic tree exceeds vertex limit")
        if normalized in _OPERATORS:
            result.append(("operator", _OPERATORS[normalized]))
        else:
            result.append(("atom", "⊤" if normalized == "true" else "⊥" if normalized == "false" else token))
    return result


def _parse(expression):
    values, operators, iff_frames = [], [], [False]
    expecting_operand = True

    def reduce_operator():
        operator = operators.pop()
        arity = 1 if operator == "¬" else 2
        if len(values) < arity:
            raise DiscreteStructureError("propositional operator has missing operands")
        operands = values[-arity:]
        del values[-arity:]
        values.append((operator, operands))

    for token in _tokens(expression):
        if token == "(":
            if not expecting_operand:
                raise DiscreteStructureError("missing operator before parenthesis")
            operators.append("(")
            iff_frames.append(False)
        elif token == ")":
            if expecting_operand or len(iff_frames) == 1:
                raise DiscreteStructureError("empty or unbalanced parentheses")
            while operators and operators[-1] != "(":
                reduce_operator()
            if not operators:
                raise DiscreteStructureError("unbalanced parentheses")
            operators.pop()
            iff_frames.pop()
            expecting_operand = False
        elif token[0] == "atom":
            if not expecting_operand:
                raise DiscreteStructureError("missing propositional operator")
            values.append((token[1], []))
            expecting_operand = False
        elif token[1] == "¬":
            if not expecting_operand:
                raise DiscreteStructureError("negation must precede its operand")
            operators.append("¬")
        else:
            operator = token[1]
            if expecting_operand:
                raise DiscreteStructureError("binary operator has a missing operand")
            if operator == "↔":
                if iff_frames[-1]:
                    raise DiscreteStructureError("parenthesize chained biconditionals explicitly")
                iff_frames[-1] = True
            while (operators and operators[-1] != "("
                   and (_PRECEDENCE[operators[-1]] > _PRECEDENCE[operator]
                        or _PRECEDENCE[operators[-1]] == _PRECEDENCE[operator] and operator != "→")):
                reduce_operator()
            operators.append(operator)
            expecting_operand = True
    if expecting_operand or len(iff_frames) != 1:
        raise DiscreteStructureError("incomplete formula or unbalanced parentheses")
    while operators:
        reduce_operator()
    if len(values) != 1:
        raise DiscreteStructureError("invalid propositional formula")
    return values[0]


def construct_logic_tree(expression):
    tree = _parse(expression)
    vertices, edges, pending = [], [], [(tree, None, None)]
    while pending:
        (label, children), parent, position = pending.pop(0)
        vertex_id = "v" + str(len(vertices))
        if len(vertices) >= 80 or len(label) > 80:
            raise DiscreteStructureError("logic tree exceeds label or vertex limit")
        vertices.append({"id": vertex_id, "label": label})
        if parent is not None:
            edge = {"id": "e" + str(len(edges)), "from": parent, "to": vertex_id, "direction": "forward"}
            if position is not None:
                edge["edge_label"] = str(position)
            edges.append(edge)
        pending.extend((child, vertex_id, index + 1 if len(children) == 2 else None)
                       for index, child in enumerate(children))
    return True, vertices, edges, "rooted_tree"
