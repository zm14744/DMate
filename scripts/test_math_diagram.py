import json
import unittest

from math_diagram import MathDiagramError, build_document, generate_diagram, _require_discrete_scope
from finite_algebra_diagrams import AlgebraStructureError, group_structure, ring_structure, ideal_structure, semigroup_cayley_structure


class MathDiagramStructureTests(unittest.TestCase):
    def test_hasse_reduces_transitive_relations(self):
        document, kind = build_document({
            "kind": "hasse",
            "title": "Divisibility",
            "vertices": [
                {"id": "v1", "label": "1"},
                {"id": "v2", "label": "2"},
                {"id": "v3", "label": "4"},
            ],
            "order_relations": [["v1", "v2"], ["v2", "v3"], ["v1", "v3"]],
        })
        self.assertEqual(kind, "hasse")
        edges = {(edge["from"], edge["to"]) for edge in document["graphs"][0]["edges"]}
        self.assertEqual(edges, {("v1", "v2"), ("v2", "v3")})
        self.assertTrue(all(edge["direction"] == "undirected" for edge in document["graphs"][0]["edges"]))

    def test_hasse_rejects_cycle(self):
        with self.assertRaises(MathDiagramError):
            build_document({
                "kind": "hasse", "title": "bad",
                "vertices": [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}],
                "order_relations": [["a", "b"], ["b", "a"]],
            })

    def test_cyclic_cayley_builds_directed_cycle(self):
        document, kind = build_document({
            "kind": "cyclic_cayley", "title": "Cayley graph of Z4",
            "modulus": 4, "generators": [1],
        })
        graph = document["graphs"][0]
        self.assertEqual(kind, "cyclic_cayley")
        self.assertTrue(graph["directed"])
        self.assertEqual(len(graph["vertices"]), 4)
        self.assertEqual(len(graph["edges"]), 4)

    def test_symmetric_cayley_generators_build_undirected_graph(self):
        document, _ = build_document({
            "kind": "cyclic_cayley", "title": "Cayley graph of Z4",
            "modulus": 4, "generators": [1, 3],
        })
        graph = document["graphs"][0]
        self.assertFalse(graph["directed"])
        self.assertEqual(len(graph["edges"]), 4)

    def test_cyclic_generators_must_generate_group(self):
        with self.assertRaises(MathDiagramError):
            build_document({
                "kind": "cyclic_cayley", "title": "bad",
                "modulus": 8, "generators": [2],
            })

    def test_cyclic_subgroup_lattice_z12(self):
        document, kind = build_document({
            "kind": "cyclic_subgroup_lattice", "title": "Subgroup lattice of Z12",
            "modulus": 12,
        })
        graph = document["graphs"][0]
        self.assertEqual(kind, "hasse")
        self.assertEqual({vertex["label"] for vertex in graph["vertices"]},
                         {"⟨1⟩", "⟨2⟩", "⟨3⟩", "⟨4⟩", "⟨6⟩", "⟨12⟩"})
        self.assertEqual(len(graph["edges"]), 7)

    def test_ideal_lattice_z12(self):
        document, kind = build_document({
            "kind": "ideal_lattice_zn", "title": "Ideal lattice of Z12",
            "modulus": 12,
        })
        graph = document["graphs"][0]
        self.assertEqual(kind, "hasse")
        self.assertEqual({vertex["label"] for vertex in graph["vertices"]},
                         {"(1)", "(2)", "(3)", "(4)", "(6)", "(12)"})
        self.assertEqual(len(graph["edges"]), 7)

    def test_zero_divisor_graph_z6(self):
        document, kind = build_document({
            "kind": "zero_divisor_graph", "title": "Zero-divisor graph of Z6",
            "modulus": 6,
        })
        graph = document["graphs"][0]
        self.assertEqual(kind, "zero_divisor_graph")
        self.assertEqual({vertex["label"] for vertex in graph["vertices"]}, {"2", "3", "4"})
        self.assertEqual(
            {(edge["from"], edge["to"]) for edge in graph["edges"]},
            {("v2", "v3"), ("v3", "v4")},
        )

    def test_zero_divisor_graph_rejects_prime_modulus(self):
        with self.assertRaises(MathDiagramError):
            build_document({"kind": "zero_divisor_graph", "title": "bad", "modulus": 7})

    def test_graph_rejects_unknown_endpoint(self):
        with self.assertRaises(MathDiagramError):
            build_document({
                "kind": "graph", "title": "bad", "directed": False, "weighted": False,
                "vertices": [{"id": "v1", "label": "A"}],
                "edges": [{"from": "v1", "to": "v2"}],
            })


    def test_complete_graph_is_checked(self):
        document, kind = build_document({
            "kind": "graph", "graph_family": "complete", "title": "K3",
            "directed": False, "weighted": False,
            "vertices": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}, {"from": "b", "to": "c"}],
        })
        self.assertEqual(kind, "graph")
        self.assertEqual(len(document["graphs"][0]["edges"]), 3)

    def test_complete_graph_rejects_missing_edge(self):
        with self.assertRaises(MathDiagramError):
            build_document({
                "kind": "graph", "graph_family": "complete", "title": "not K3",
                "directed": False, "weighted": False,
                "vertices": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
            })

    def test_tree_rejects_disconnected_structure(self):
        with self.assertRaises(MathDiagramError):
            build_document({
                "kind": "graph", "graph_family": "tree", "title": "not a tree",
                "directed": False, "weighted": False,
                "vertices": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
                "edges": [{"from": "a", "to": "b"}],
            })

    def test_bipartite_rejects_odd_cycle(self):
        with self.assertRaises(MathDiagramError):
            build_document({
                "kind": "graph", "graph_family": "bipartite", "title": "not bipartite",
                "directed": False, "weighted": False,
                "vertices": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "a"}],
            })

    def test_generate_diagram_uses_json_mode_and_validates_output(self):
        response_spec = {
            "kind": "graph", "graph_family": "tree", "title": "A three-node tree",
            "directed": False, "weighted": False,
            "vertices": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        }
        observed = {}
        def completion(messages, **kwargs):
            observed.update(kwargs)
            return {"ok": True, "content": json.dumps(response_spec), "choice": {"finish_reason": "stop"}}
        result = generate_diagram({"requirement": "生成一棵三个顶点的树", "language": "zh-CN"}, completion=completion)
        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "graph")
        self.assertEqual(observed["response_format"], {"type": "json_object"})
        self.assertEqual(len(result["document"]["graphs"][0]["edges"]), 2)


class MathDiagramRequirementTests(unittest.TestCase):
    @staticmethod
    def graph_spec(count, pairs, family="general"):
        return {
            "kind": "graph", "graph_family": family, "title": "Generated graph",
            "directed": False, "weighted": False,
            "vertices": [{"id": f"v{index}", "label": str(index)} for index in range(count)],
            "edges": [{"from": f"v{left}", "to": f"v{right}"} for left, right in pairs],
        }

    @staticmethod
    def generate(requirement, spec, language="zh-CN"):
        def completion(messages, **kwargs):
            return {"ok": True, "content": json.dumps(spec), "choice": {"finish_reason": "stop"}}
        return generate_diagram({"requirement": requirement, "language": language}, completion=completion)

    def assert_mismatch(self, requirement, spec, language="zh-CN"):
        with self.assertRaises(MathDiagramError) as caught:
            self.generate(requirement, spec, language)
        self.assertEqual(caught.exception.code, "math_diagram_requirement_mismatch")
        self.assertEqual(caught.exception.status, 502)
        return caught.exception.message

    def test_requested_k5_cannot_be_replaced_with_k3(self):
        triangle = self.graph_spec(3, [(0, 1), (0, 2), (1, 2)], "complete")
        for requirement in ("画一个完全图K5", "K_5", "请绘制 $K_{5}$。", "Draw the complete graph K5."):
            with self.subTest(requirement=requirement):
                self.assert_mismatch(requirement, triangle)

    def test_complete_graph_checks_actual_edges_and_requested_count(self):
        complete = self.graph_spec(5, [(left, right) for left in range(5) for right in range(left + 1, 5)])
        for requirement in ("生成有五个顶点的完全图", "Draw a complete graph on 5 vertices", "Create a 5-vertex complete graph", "K5"):
            with self.subTest(requirement=requirement):
                self.assertTrue(self.generate(requirement, complete)["ok"])
        path = self.graph_spec(5, [(index, index + 1) for index in range(4)])
        self.assert_mismatch("画K5", path)
        self.assert_mismatch("Draw a complete graph with 6 nodes", complete)

    def test_tree_path_cycle_use_actual_structure_even_when_model_says_general(self):
        path = self.graph_spec(5, [(index, index + 1) for index in range(4)])
        cycle = self.graph_spec(5, [(index, (index + 1) % 5) for index in range(5)])
        for requirement, spec in (
            ("画一棵有5个顶点的树", path), ("生成五个顶点的路径", path),
            ("画5顶点回路", cycle), ("Draw a tree with 5 vertices", path),
            ("Create a 5-vertex path", path), ("Generate a cycle on 5 nodes", cycle),
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(self.generate(requirement, spec)["ok"])
        triangle = self.graph_spec(3, [(0, 1), (1, 2), (2, 0)])
        self.assert_mismatch("画一棵有5个顶点的树", triangle)
        self.assert_mismatch("Draw a tree with 5 vertices", cycle)
        self.assert_mismatch("Draw a path on 5 vertices", cycle)
        self.assert_mismatch("画五个顶点的环", path)
        branching_tree = self.graph_spec(5, [(0, 1), (0, 2), (0, 3), (3, 4)])
        self.assert_mismatch("Draw a 5-vertex path", branching_tree)

    def test_complete_bipartite_graph_checks_both_partition_sizes(self):
        bipartite = self.graph_spec(5, [(left, right) for left in range(2) for right in range(2, 5)])
        star = self.graph_spec(5, [(0, index) for index in range(1, 5)], "complete_bipartite")
        for requirement in ("画完全二部图K_{2,3}", "K_3,2", "Draw the complete bipartite graph K2,3"):
            with self.subTest(requirement=requirement):
                self.assertTrue(self.generate(requirement, bipartite)["ok"])
                self.assert_mismatch(requirement, star)
        self.assert_mismatch("画K_{2,3}", self.graph_spec(5, [(0, 2), (1, 3), (1, 4)]))

    def test_zn_constraints_check_modulus_and_structure_type(self):
        requests = (
            ("cyclic_cayley", "画循环群Z12的Cayley图", "Draw the Cayley graph of the cyclic group Z_12"),
            ("cyclic_subgroup_lattice", "画循环群Z12的子群格", "Draw the subgroup lattice of Z_{12}"),
            ("ideal_lattice_zn", "生成环Z_12的理想格", "Create the ideal lattice of the ring Z12"),
            ("zero_divisor_graph", "画Z₁₂的零因子图", "Draw a zero-divisor graph of Z12"),
        )
        for kind, chinese, english in requests:
            spec = {"kind": kind, "title": "Z12", "modulus": 12}
            if kind == "cyclic_cayley":
                spec["generators"] = [1]
            for requirement in (chinese, english):
                with self.subTest(kind=kind, requirement=requirement):
                    self.assertTrue(self.generate(requirement, spec)["ok"])
                    self.assert_mismatch(requirement, dict(spec, modulus=6))
                    wrong_kind = "ideal_lattice_zn" if kind != "ideal_lattice_zn" else "cyclic_subgroup_lattice"
                    self.assert_mismatch(requirement, {"kind": wrong_kind, "title": "Z12", "modulus": 12})

    def test_mismatch_error_follows_ui_language(self):
        spec = {"kind": "cyclic_subgroup_lattice", "title": "Z6", "modulus": 6}
        chinese = self.assert_mismatch("画循环群Z12的子群格", spec)
        english = self.assert_mismatch("画循环群Z12的子群格", spec, "en")
        self.assertIn("不符合请求", chinese)
        self.assertIn("does not match", english)
        self.assertNotIn("生成", english)

    def test_complex_or_negative_requests_are_not_assigned_guessed_constraints(self):
        # These phrases require interpretation beyond the deliberately small
        # grammar. Their model output still undergoes ordinary structure checks.
        path = self.graph_spec(3, [(0, 1), (1, 2)])
        for requirement in (
            "把K5删去一条边", "不要画K5，画一条三顶点路径", "画K3和K5", "比较K3与K4",
            "画Z12的子群格，但只保留两个子群", "Draw K5 minus one edge",
            "Compare K3 and K5", "Draw a tree and a cycle on 5 vertices",
            "Draw a spanning tree of K5", "Draw a graph labelled 'cycle on 5 vertices'",
            "Do not draw K5; draw a path", "Change the subgroup lattice of Z12 into the ideal lattice of Z6",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(self.generate(requirement, path)["ok"])

class FiniteAlgebraDiagramTests(unittest.TestCase):
    @staticmethod
    def build(kind, **fields):
        return build_document({"kind": kind, "title": "Finite structure", **fields})

    def test_known_noncyclic_subgroup_lattices(self):
        for group, count, covers in (
            ({"family": "klein"}, 5, 6),
            ({"family": "symmetric", "parameter": 3}, 6, 8),
            ({"family": "quaternion"}, 6, 7),
            ({"family": "dihedral", "parameter": 4}, 10, 15),
            ({"family": "symmetric", "parameter": 4}, 30, 66),
        ):
            with self.subTest(group=group):
                document, kind = self.build("finite_subgroup_lattice", group=group)
                graph = document["graphs"][0]
                self.assertEqual(kind, "hasse")
                self.assertEqual(len(graph["vertices"]), count)
                self.assertEqual(len(graph["edges"]), covers)

    def test_cayley_named_generators_use_actual_group_operation(self):
        for group, generators, order in (
            ({"family": "symmetric", "parameter": 3}, ["(12)", "(123)"], 6),
            ({"family": "dihedral", "parameter": 4}, ["r", "s"], 8),
            ({"family": "klein"}, ["a", "b"], 4),
            ({"family": "quaternion"}, ["i", "j"], 8),
            ({"family": "product_cyclic", "moduli": [2, 4]}, ["(1,0)", "(0,1)"], 8),
        ):
            with self.subTest(group=group):
                table, labels, identity = group_structure(group)
                document, kind = self.build("finite_group_cayley", group=group, generators=generators)
                graph = document["graphs"][0]
                self.assertEqual(kind, "finite_group_cayley")
                self.assertEqual(len(graph["vertices"]), order)
                self.assertEqual(len(graph["edges"]), order * len(generators))
                self.assertTrue(graph["directed"])
                for edge in graph["edges"]:
                    left, right = int(edge["from"][1:]), int(edge["to"][1:])
                    self.assertEqual(table[left][labels.index(edge["edge_label"])], right)

    def test_cayley_rejects_proper_subgroup_generators_or_unknown_labels(self):
        for group, generators in (
            ({"family": "symmetric", "parameter": 3}, ["(123)"]),
            ({"family": "quaternion"}, ["i"]),
            ({"family": "dihedral", "parameter": 4}, ["x", "s"]),
            ({"family": "klein"}, ["a", "a"]),
        ):
            with self.subTest(group=group, generators=generators), self.assertRaises(MathDiagramError):
                self.build("finite_group_cayley", group=group, generators=generators)

    def test_generator_matching_preserves_exact_labels_and_rejects_ambiguous_normalization(self):
        group = {"family": "table", "multiplication_table": [[0, 1], [1, 0]], "labels": ["ab", "a b"]}
        # The exact identity label must never select the distinct element whose
        # label differs by internal whitespace.
        for generators in (["ab"], ["a  b"]):
            with self.subTest(generators=generators), self.assertRaises(MathDiagramError):
                self.build("finite_group_cayley", group=group, generators=generators)
        document, _ = self.build("finite_group_cayley", group=group, generators=["a b"])
        self.assertEqual([(edge["from"], edge["to"], edge["edge_label"])
                          for edge in document["graphs"][0]["edges"]],
                         [("v0", "v1", "a b"), ("v1", "v0", "a b")])

    def test_quaternion_and_permutation_tables_obey_noncommutative_laws(self):
        table, labels, identity = group_structure({"family": "quaternion"})
        self.assertEqual(labels[identity], "1")
        self.assertEqual(labels[table[labels.index("i")][labels.index("j")]], "k")
        self.assertEqual(labels[table[labels.index("j")][labels.index("i")]], "−k")
        self.assertEqual(labels[table[labels.index("i")][labels.index("i")]], "−1")
        table, labels, identity = group_structure({"family": "symmetric", "parameter": 3})
        transposition = labels.index("(1 2)")
        cycle = labels.index("(1 2 3)")
        self.assertNotEqual(table[transposition][cycle], table[cycle][transposition])

    def test_ring_ideals_are_not_all_additive_subgroups(self):
        ring = {"family": "product_zn", "moduli": [2, 2]}
        document, kind = self.build("finite_ideal_lattice", ring=ring)
        graph = document["graphs"][0]
        self.assertEqual(kind, "hasse")
        self.assertEqual(len(graph["vertices"]), 4)
        self.assertEqual(len(graph["edges"]), 4)
        subgroup, _ = self.build("finite_subgroup_lattice", group={"family": "product_cyclic", "moduli": [2, 2]})
        self.assertEqual(len(subgroup["graphs"][0]["vertices"]), 5)

    def test_ring_zero_divisors_have_witnesses_and_correct_edges(self):
        for ring in ({"family": "product_zn", "moduli": [2, 3]}, {"family": "zn", "parameter": 12}):
            with self.subTest(ring=ring):
                _, multiplication, labels, zero = ring_structure(ring)
                document, kind = self.build("finite_zero_divisor_graph", ring=ring)
                graph = document["graphs"][0]
                vertices = {vertex["id"]: labels.index(vertex["label"]) for vertex in graph["vertices"]}
                members = set(vertices.values())
                expected = {item for item in range(len(labels)) if item != zero
                            and any(other != zero and multiplication[item][other] == zero for other in range(len(labels)))}
                self.assertEqual(members, expected)
                actual_edges = {frozenset((vertices[edge["from"]], vertices[edge["to"]])) for edge in graph["edges"]}
                expected_edges = {frozenset((a, b)) for a in members for b in members if a != b and multiplication[a][b] == zero}
                self.assertEqual(actual_edges, expected_edges)

    def test_explicit_group_tables_validate_closure_identity_inverse_and_associativity(self):
        good = [[(a + b) % 5 for b in range(5)] for a in range(5)]
        self.assertEqual(group_structure({"family": "table", "multiplication_table": good})[2], 0)
        closure = [row[:] for row in good]
        closure[1][2] = 9
        no_identity = [[1 - ((a + b) % 2) for b in range(2)] for a in range(2)]
        no_identity[0][0] = 0
        no_inverse = [[0, 1], [1, 1]]
        nonassociative = [row[:] for row in good]
        nonassociative[1][2], nonassociative[1][3] = nonassociative[1][3], nonassociative[1][2]
        for table in (closure, no_identity, no_inverse, nonassociative, [[0], [1, 0]]):
            with self.subTest(table=table), self.assertRaises(AlgebraStructureError):
                group_structure({"family": "table", "multiplication_table": table})
        with self.assertRaises(AlgebraStructureError):
            group_structure({"family": "table", "multiplication_table": [[0, 1], [1, 0]], "labels": ["e", " e"]})

    def test_explicit_ring_tables_check_distributivity_identity_and_commutativity(self):
        addition = [[(a + b) % 3 for b in range(3)] for a in range(3)]
        multiplication = [[(a * b) % 3 for b in range(3)] for a in range(3)]
        ring_structure({"family": "table", "addition_table": addition, "multiplication_table": multiplication})
        # Additive operation used as multiplication remains associative,
        # commutative and unital, but fails distributivity.
        for bad_multiplication in (addition, [[0] * 3 for _ in range(3)]):
            with self.assertRaises(AlgebraStructureError):
                ring_structure({"family": "table", "addition_table": addition, "multiplication_table": bad_multiplication})

    def test_standard_lattice_counts_and_cover_orientation(self):
        for lattice, size, covers in (
            ({"family": "boolean", "parameter": 3}, 8, 12),
            ({"family": "boolean", "parameter": 5}, 32, 80),
            ({"family": "divisors", "parameter": 12}, 6, 7),
            ({"family": "diamond"}, 5, 6),
            ({"family": "pentagon"}, 5, 5),
        ):
            with self.subTest(lattice=lattice):
                document, kind = self.build("standard_lattice", lattice=lattice)
                graph = document["graphs"][0]
                self.assertEqual(kind, "hasse")
                self.assertEqual(len(graph["vertices"]), size)
                self.assertEqual(len(graph["edges"]), covers)
                # Every deterministic family's least element is index 0.
                self.assertFalse(any(edge["to"] == "v0" for edge in graph["edges"]))

    def test_poset_cannot_claim_to_be_lattice_without_unique_meets_and_joins(self):
        for count, pairs in ((3, [(0, 1), (0, 2)]), (4, [(0, 2), (0, 3), (1, 2), (1, 3)])):
            spec = {"vertices": [{"id": "v" + str(i), "label": str(i)} for i in range(count)],
                    "order_relations": [["v" + str(a), "v" + str(b)] for a, b in pairs]}
            # They are valid posets, but not lattices.
            self.build("hasse", **spec)
            with self.assertRaises(MathDiagramError) as caught:
                self.build("lattice", **spec)
            self.assertEqual(caught.exception.code, "invalid_finite_lattice")

    def test_explicit_names_cannot_be_replaced_with_other_group_ring_or_lattice(self):
        cases = (
            ("画S3的子群格", {"kind": "finite_subgroup_lattice", "group": {"family": "cyclic", "parameter": 6}}),
            ("Draw the Cayley graph of S3", {"kind": "finite_group_cayley", "group": {"family": "cyclic", "parameter": 6}, "generators": [1]}),
            ("生成环Z2×Z2的理想格", {"kind": "finite_subgroup_lattice", "group": {"family": "klein"}}),
            ("画布尔格B3的哈斯图", {"kind": "standard_lattice", "lattice": {"family": "boolean", "parameter": 2}}),
            ("Draw the divisor lattice of 12", {"kind": "standard_lattice", "lattice": {"family": "divisors", "parameter": 6}}),
        )
        for requirement, fields in cases:
            with self.subTest(requirement=requirement):
                MathDiagramRequirementTests().assert_mismatch(requirement, {"title": "Wrong structure", **fields})

    def test_legacy_named_zn_requests_accept_equivalent_general_algebra_builders(self):
        for requirement, fields in (
            ("画循环群Z6的子群格", {"kind": "finite_subgroup_lattice", "group": {"family": "cyclic", "parameter": 6}}),
            ("画循环群Z6的Cayley图", {"kind": "finite_group_cayley", "group": {"family": "cyclic", "parameter": 6}, "generators": ["1"]}),
            ("画环Z6的理想格", {"kind": "finite_ideal_lattice", "ring": {"family": "zn", "parameter": 6}}),
            ("画Z6的零因子图", {"kind": "finite_zero_divisor_graph", "ring": {"family": "zn", "parameter": 6}}),
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(MathDiagramRequirementTests.generate(requirement, {"title": "Z6", **fields})["ok"])

    def test_nondiscrete_requests_rejected_before_call_even_if_model_would_return_graph(self):
        for requirement in (
            "画正弦函数曲线", "太阳系示意图", "画一只猫", "Plot y = x^2", "Draw a solar system relation graph",
            "Draw the graph y=x^2 on the finite interval [-1,1]", "Draw a bar chart for a finite data set",
            "Draw a flowchart for a finite graph traversal",
            "Plot the graph of x^2", "Graph sin(x)",
            "Draw the graph of sin(x)", "Draw graph y=x over the real numbers", "Draw graph y=e^x",
        ):
            with self.subTest(requirement=requirement):
                def completion(*args, **kwargs):
                    self.fail("Out-of-scope requests must not invoke the model")
                with self.assertRaises(MathDiagramError) as caught:
                    generate_diagram({"requirement": requirement}, completion=completion)
                self.assertIn(caught.exception.code, ("outside_discrete_math_scope", "excluded_math_diagram"))
                self.assertEqual(caught.exception.status, 422)

    def test_explicit_adjacency_remains_in_scope(self):
        path = MathDiagramRequirementTests.graph_spec(3, [(0, 1), (1, 2)])
        for requirement in ("A -> B -> C", "画三个点和两条边"):
            with self.subTest(requirement=requirement):
                self.assertTrue(MathDiagramRequirementTests.generate(requirement, path)["ok"])

    def test_common_discrete_graph_names_are_not_blocked_by_scope_gate(self):
        graph = MathDiagramRequirementTests.graph_spec(3, [(0, 1), (1, 2)])
        for requirement in ("画一棵5阶树", "画五阶树", "画彼得森图", "画欧拉图", "画一个平面图"):
            with self.subTest(requirement=requirement):
                # Structure-specific checks still apply after scope admission;
                # this test is specifically about not rejecting course terms.
                _require_discrete_scope(requirement)

    def test_limits_and_blank_requirements_are_rejected(self):
        for spec in (
            {"kind": "finite_subgroup_lattice", "group": {"family": "symmetric", "parameter": 5}},
            {"kind": "finite_ideal_lattice", "ring": {"family": "product_zn", "moduli": [5, 6]}},
            {"kind": "standard_lattice", "lattice": {"family": "boolean", "parameter": 6}},
        ):
            with self.subTest(spec=spec), self.assertRaises(MathDiagramError):
                build_document({"title": "Too large", **spec})
        for requirement in (None, "", " \n "):
            with self.subTest(requirement=requirement), self.assertRaises(MathDiagramError) as caught:
                generate_diagram({"requirement": requirement}, completion=lambda *a, **k: self.fail("No model call"))
            self.assertEqual(caught.exception.code, "empty_math_diagram_request")


class ExtendedDiscreteDiagramTests(unittest.TestCase):
    def test_excluded_diagrams_reject_before_model_even_when_finite(self):
        cases = ("画有限映射 A={1,2} 到 B={a,b}，1映到a，2映到b", "Draw a finite mapping f(x)=x mod 3",
                 "画函数的有向图", "Generate a truth table for p and q", "画Z4的乘法表", "画Venn diagram",
                 "画集合A和B的韦恩图", "画邻接矩阵", "根据给定乘法表画Cayley图，并附上乘法表",
                 "Draw a Cayley graph using a multiplication table and include the table", "画function graph",
                 "画mapping graph", "画table graph", "画sin(x)的graph")
        for requirement in cases:
            with self.subTest(requirement=requirement), self.assertRaises(MathDiagramError) as error:
                generate_diagram({"requirement": requirement}, completion=lambda *a, **k: self.fail("No model call"))
            self.assertIn(error.exception.code, ("excluded_math_diagram", "outside_discrete_math_scope"))

    def test_algebra_and_adjacency_tables_are_still_allowed_as_source_data(self):
        for requirement in ("根据给定乘法表画Cayley图", "给定邻接矩阵，画无向图", "使用下面的关系矩阵画关系图",
                            "Draw a Cayley graph from the given multiplication table",
                            "Draw the two-sided ideal lattice of the matrix ring M2(F2)", "不要韦恩图，画布尔格B3",
                            "Draw K5, no functions or tables", "画K5，不要函数、表格和韦恩图"):
            with self.subTest(requirement=requirement):
                _require_discrete_scope(requirement)

    def test_model_numeric_ids_are_canonicalized_in_every_reference_field(self):
        vertices = [{"id": str(index), "label": str(index)} for index in (1, 2, 3)]
        cases = (("画有向图1到2到3", {"kind": "graph", "graph_family": "general", "directed": True, "weighted": False,
                                     "edges": [{"from": "1", "to": "2"}, {"from": "2", "to": "3"}]}, 2),
                 ("画整除关系哈斯图", {"kind": "hasse", "order_relations": [["1", "2"], ["2", "3"], ["1", "3"]]}, 2),
                 ("画根为1的根树", {"kind": "rooted_tree", "root": "1", "directed": True, "weighted": False,
                                    "edges": [{"from": "1", "to": "2"}, {"from": "1", "to": "3"}]}, 2),
                 ("画有限关系的传递闭包", {"kind": "relation_graph", "relation_pairs": [["1", "2"], ["2", "3"]], "relation_closure": "transitive"}, 3))
        for requirement, fields, edge_count in cases:
            with self.subTest(kind=fields["kind"]):
                graph = MathDiagramRequirementTests.generate(requirement, {**fields, "vertices": vertices, "title": "Numeric elements"})["document"]["graphs"][0]
                self.assertEqual([row["label"] for row in graph["vertices"]], ["1", "2", "3"])
                self.assertEqual({row["id"] for row in graph["vertices"]}, {"v0", "v1", "v2"})
                self.assertEqual(len(graph["edges"]), edge_count)
        duplicate = {"kind": "graph", "title": "Bad", "vertices": [{"id": "1", "label": "A"}, {"id": "1", "label": "B"}], "edges": []}
        with self.assertRaises(MathDiagramError):
            MathDiagramRequirementTests.generate("画有向图", duplicate)
        with self.assertRaises(MathDiagramError):
            MathDiagramRequirementTests.generate("画有向图", {**duplicate, "vertices": vertices, "edges": [{"from": "1", "to": "missing"}]})

    def test_numeric_relation_ids_are_reindexed_without_changing_elements(self):
        spec = {"kind": "relation_graph", "title": "R+", "vertices": [{"id": str(i), "label": str(i)} for i in (1, 2, 3)],
                "relation_pairs": [["1", "2"], ["2", "3"]], "relation_closure": "transitive"}
        document, kind = build_document(spec)
        graph = document["graphs"][0]
        self.assertEqual(kind, "relation_graph")
        self.assertEqual([row["label"] for row in graph["vertices"]], ["1", "2", "3"])
        self.assertEqual({(edge["from"], edge["to"]) for edge in graph["edges"]}, {("r0", "r1"), ("r1", "r2"), ("r0", "r2")})
        for change in ({"relation_pairs": [["1", "missing"]]}, {"vertices": [{"id": "1", "label": "A"}, {"id": "1", "label": "B"}]}):
            with self.subTest(change=change), self.assertRaises(MathDiagramError):
                build_document({**spec, **change})

    def test_relation_closures_preserve_reflexive_cycles_and_equivalence_components(self):
        base = {"kind": "relation_graph", "title": "R", "vertices": [{"id": i, "label": i} for i in "abc"],
                "relation_pairs": [["a", "b"], ["b", "a"]]}
        for closure, expected in (("none", {("a", "b"), ("b", "a")}),
                                  ("transitive", {("a", "b"), ("b", "a"), ("a", "a"), ("b", "b")}),
                                  ("equivalence", {("a", "b"), ("b", "a"), ("a", "a"), ("b", "b"), ("c", "c")})):
            with self.subTest(closure=closure):
                graph = build_document({**base, "relation_closure": closure})[0]["graphs"][0]
                self.assertEqual({(edge["from"], edge["to"]) for edge in graph["edges"]}, expected)

    def test_new_model_schema_constructs_actual_standard_and_course_structures(self):
        cases = (("画完全图K5", "standard_graph", {"family": "complete", "order": 5}, 5, 10),
                 ("画彼得森图", "standard_graph", {"family": "petersen"}, 10, 15),
                 ("画超立方体Q3", "standard_graph", {"family": "hypercube", "dimension": 3}, 8, 12),
                 ("画星图S4", "standard_graph", {"family": "star", "order": 5}, 5, 4),
                 ("画轮图W4", "standard_graph", {"family": "wheel", "order": 5}, 5, 8),
                 ("画高度3的满二叉树", "full_mary_tree", {"branching": 2, "height": 3}, 15, 14),
                 ("画120的素因数分解树", "factor_tree", {"number": 120}, 9, 8),
                 ("画选择树", "choice_tree", {"choices": [["a", "b"], ["1", "2", "3"]]}, 9, 8),
                 ("画T(8)每次二分且有两个子问题的递归树", "recursion_tree", {"initial": 8, "branching": 2, "divisor": 2, "base": 1}, 15, 14),
                 ("画三进制串禁用子串22的状态转移图", "word_transition_graph", {"alphabet": ["0", "1", "2"], "forbidden": ["22"]}, 2, 5))
        for requirement, kind, structure, nodes, edges in cases:
            with self.subTest(kind=kind, requirement=requirement):
                result = MathDiagramRequirementTests.generate(requirement, {"kind": kind, "title": "结构图", "structure": structure})
                graph = result["document"]["graphs"][0]
                self.assertEqual((len(graph["vertices"]), len(graph["edges"])), (nodes, edges))
        for requirement, spec in (("画彼得森图", {"kind": "standard_graph", "structure": {"family": "cycle", "order": 10}}),
                                  ("画超立方体Q3", {"kind": "standard_graph", "structure": {"family": "hypercube", "dimension": 2}})):
            MathDiagramRequirementTests().assert_mismatch(requirement, {**spec, "title": "Wrong"})

    def test_rooted_trees_have_unique_reachable_parent_and_can_orient_given_undirected_edges(self):
        spec = {"kind": "rooted_tree", "title": "Tree", "root": "b", "directed": False, "weighted": False,
                "vertices": [{"id": i, "label": i} for i in "abc"], "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}]}
        document, kind = build_document(spec)
        self.assertEqual(kind, "rooted_tree")
        self.assertEqual({(edge["from"], edge["to"]) for edge in document["graphs"][0]["edges"]}, {("b", "a"), ("a", "c")})
        for change in ({"root": "missing"}, {"root": []}, {"edges": spec["edges"] + [{"from": "c", "to": "b"}]}):
            with self.subTest(change=change), self.assertRaises(MathDiagramError):
                build_document({**spec, **change})

    def test_logic_expression_tree_is_parsed_before_model_edges(self):
        result = MathDiagramRequirementTests.generate("画命题公式¬p∧(q∨r)的语法树", {"kind": "logic_tree", "title": "Logic", "expression": "¬p∧(q∨r)"})
        graph = result["document"]["graphs"][0]
        self.assertEqual(result["kind"], "rooted_tree")
        self.assertEqual((len(graph["vertices"]), len(graph["edges"])), (6, 5))
        self.assertEqual({vertex["label"] for vertex in graph["vertices"]}, {"¬", "p", "∧", "q", "∨", "r"})

    def test_trivial_groups_and_zero_ring_have_single_vertex_not_a_fabricated_loop(self):
        for spec in ({"kind": "finite_group_cayley", "group": {"family": "cyclic", "parameter": 1}, "generators": []},
                     {"kind": "finite_subgroup_lattice", "group": {"family": "table", "multiplication_table": [[0]]}},
                     {"kind": "finite_ideal_lattice", "ring": {"family": "zn", "parameter": 1}}):
            with self.subTest(spec=spec):
                graph = build_document({**spec, "title": "Singleton"})[0]["graphs"][0]
                self.assertEqual((len(graph["vertices"]), len(graph["edges"])), (1, 0))

    def test_semigroup_and_monoid_do_not_incorrectly_require_inverses(self):
        graph = build_document({"kind": "monoid_cayley", "title": "M4", "semigroup": {"family": "modular_multiplication", "parameter": 4}, "generators": ["0", "2", "3"]})[0]["graphs"][0]
        self.assertEqual((len(graph["vertices"]), len(graph["edges"])), (4, 12))
        self.assertTrue(any(edge["from"] == edge["to"] == "v0" for edge in graph["edges"]))
        semigroup_cayley_structure({"family": "left_zero", "parameter": 2}, [0, 1])
        with self.assertRaises(AlgebraStructureError):
            semigroup_cayley_structure({"family": "left_zero", "parameter": 2}, [0, 1], require_identity=True)

    def test_finite_fields_are_not_modular_integer_rings_of_composite_order(self):
        for order in (4, 8, 9, 16):
            with self.subTest(order=order):
                _, multiplication, labels, zero = ring_structure({"family": "finite_field", "parameter": order})
                one = labels.index("1")
                self.assertTrue(all(any(multiplication[item][other] == one for other in range(order)) for item in range(order) if item != zero))
                self.assertEqual(len(ideal_structure({"family": "finite_field", "parameter": order})[0]), 2)
        self.assertEqual(len(ideal_structure({"family": "zn", "parameter": 4})[0]), 3)
        MathDiagramRequirementTests().assert_mismatch("画有限域F4的理想格", {"kind": "finite_ideal_lattice", "title": "Wrong", "ring": {"family": "zn", "parameter": 4}})

    def test_noncommutative_matrix_ring_ideals_use_both_sides(self):
        bits = lambda value: [(value >> index) & 1 for index in range(4)]
        def product(left, right):
            a, b = bits(left), bits(right)
            c = [(a[0]*b[0]+a[1]*b[2]) % 2, (a[0]*b[1]+a[1]*b[3]) % 2,
                 (a[2]*b[0]+a[3]*b[2]) % 2, (a[2]*b[1]+a[3]*b[3]) % 2]
            return sum(value << index for index, value in enumerate(c))
        ring = {"family": "table", "addition_table": [[a ^ b for b in range(16)] for a in range(16)],
                "multiplication_table": [[product(a, b) for b in range(16)] for a in range(16)]}
        self.assertNotEqual(product(1, 2), product(2, 1))
        self.assertEqual(len(ideal_structure(ring)[0]), 2)
        with self.assertRaises(MathDiagramError):
            build_document({"kind": "finite_zero_divisor_graph", "title": "Ambiguous", "ring": ring})


if __name__ == "__main__":
    unittest.main()
