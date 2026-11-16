"""Grammar, ordered-operand and size checks for actual formula syntax trees."""
import itertools
import unittest

from discrete_structure_diagrams import DiscreteStructureError
from logic_structure_diagrams import construct_logic_tree


def as_tree(expression):
    directed, vertices, edges, layout = construct_logic_tree(expression)
    assert directed is True and layout == "rooted_tree"
    assert len(edges) == len(vertices) - 1
    by_id = {row["id"]: row["label"] for row in vertices}
    children = {}
    for edge in edges:
        assert edge["direction"] == "forward"
        children.setdefault(edge["from"], []).append((int(edge.get("edge_label", "1")), edge["to"]))
    def read(vertex_id):
        return (by_id[vertex_id], tuple(read(child) for _, child in sorted(children.get(vertex_id, []))))
    return read(vertices[0]["id"])


def atom(name):
    return name, ()


def op(name, *children):
    return name, children


class LogicStructureTests(unittest.TestCase):
    def test_screenshot_example_is_actual_six_node_parse_tree(self):
        expression = "¬p∧(q∨r)"
        self.assertEqual(as_tree(expression), op("∧", op("¬", atom("p")), op("∨", atom("q"), atom("r"))))
        _, vertices, edges, _ = construct_logic_tree(expression)
        self.assertEqual((len(vertices), len(edges)), (6, 5))

    def test_all_spellings_normalize_to_the_same_operators(self):
        equivalents = (
            ("¬p", "!p", "not p"),
            ("p∧q", "p&q", "p and q"),
            ("p∨q", "p|q", "p or q"),
            ("p⊕q", "p^q", "p xor q"),
            ("p→q", "p->q", "p implies q"),
            ("p↔q", "p<->q", "p iff q"),
        )
        for spellings in equivalents:
            with self.subTest(spellings=spellings):
                self.assertTrue(all(as_tree(value) == as_tree(spellings[0]) for value in spellings))

    def test_precedence_and_associativity_are_explicit(self):
        self.assertEqual(as_tree("not p and q xor r or s implies t iff u"),
            op("↔", op("→", op("∨", op("⊕", op("∧", op("¬", atom("p")), atom("q")), atom("r")), atom("s")), atom("t")), atom("u")))
        self.assertEqual(as_tree("p -> q -> r"), op("→", atom("p"), op("→", atom("q"), atom("r"))))
        for spelling, label in (("and", "∧"), ("or", "∨"), ("xor", "⊕")):
            self.assertEqual(as_tree(f"p {spelling} q {spelling} r"), op(label, op(label, atom("p"), atom("q")), atom("r")))

    def test_biconditional_chains_require_parenthesized_grouping(self):
        for expression in ("p iff q iff r", "p↔q→r↔s", "p↔(q)↔r"):
            with self.subTest(expression=expression), self.assertRaises(DiscreteStructureError):
                construct_logic_tree(expression)
        self.assertEqual(as_tree("(p↔q)↔r"), op("↔", op("↔", atom("p"), atom("q")), atom("r")))
        self.assertEqual(as_tree("p↔(q↔r)"), op("↔", atom("p"), op("↔", atom("q"), atom("r"))))

    def test_constants_identifier_boundaries_and_repeated_leaf_occurrences(self):
        self.assertEqual(as_tree("TRUE and false"), op("∧", atom("⊤"), atom("⊥")))
        self.assertEqual(as_tree("⊤∨⊥"), op("∨", atom("⊤"), atom("⊥")))
        self.assertEqual(as_tree("notable and p_1"), op("∧", atom("notable"), atom("p_1")))
        self.assertEqual(as_tree("p∧p"), op("∧", atom("p"), atom("p")))
        _, vertices, edges, _ = construct_logic_tree("p∧p")
        self.assertEqual(len({row["id"] for row in vertices}), 3)
        self.assertEqual([row["edge_label"] for row in edges], ["1", "2"])

    def test_negation_and_parentheses_preserve_scope(self):
        self.assertEqual(as_tree("not not (p or q)"), op("¬", op("¬", op("∨", atom("p"), atom("q")))))
        self.assertEqual(as_tree("(" * 249 + "p" + ")" * 249), atom("p"))

    def test_unknown_missing_and_unbalanced_syntax_rejects(self):
        for expression in (None, "", " ", "p q", "p(q)", "()", "(p", "p)", "p∧", "∧p", "p!q", "p&&q", "p + q", "p=1", "p;import os", "1", "α∧β"):
            with self.subTest(expression=expression), self.assertRaises(DiscreteStructureError):
                construct_logic_tree(expression)

    def test_expression_node_and_label_limits(self):
        for expression in ("(" * 250 + "p" + ")" * 250, "!" * 80 + "p", "p" * 81):
            with self.subTest(expression=expression[:30]), self.assertRaises(DiscreteStructureError):
                construct_logic_tree(expression)
        _, vertices, _, _ = construct_logic_tree("!" * 79 + "p")
        self.assertEqual(len(vertices), 80)

    def test_implication_operand_order_matches_all_truth_assignments(self):
        def evaluate(tree, environment):
            label, children = tree
            if not children:
                return environment[label]
            values = [evaluate(child, environment) for child in children]
            return {"¬": lambda: not values[0], "∧": lambda: values[0] and values[1],
                    "∨": lambda: values[0] or values[1], "→": lambda: not values[0] or values[1]}[label]()
        tree = as_tree("p -> q -> not r")
        for values in itertools.product((False, True), repeat=3):
            p, q, r = values
            self.assertEqual(evaluate(tree, dict(zip("pqr", values))), (not p) or ((not q) or (not r)))


if __name__ == "__main__":
    unittest.main()
