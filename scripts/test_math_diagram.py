import unittest

from math_diagram import MathDiagramError, build_document


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


if __name__ == "__main__":
    unittest.main()
