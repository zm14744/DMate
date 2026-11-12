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

if __name__ == "__main__":
    unittest.main()
