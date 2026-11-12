import json
import unittest

from math_diagram import MathDiagramError, build_document, generate_diagram


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

if __name__ == "__main__":
    unittest.main()
