"""Independent graph properties and arithmetic for finite structural builders."""
import itertools
import math
import unittest

import networkx as nx

from discrete_structure_diagrams import DiscreteStructureError, construct_discrete_structure


def build(kind, structure):
    directed, vertices, edges, layout = construct_discrete_structure(kind, structure)
    graph = nx.DiGraph() if directed else nx.Graph()
    graph.add_nodes_from((row["id"], {"label": row["label"]}) for row in vertices)
    graph.add_edges_from((row["from"], row["to"], {"label": row.get("edge_label")}) for row in edges)
    assert len(graph.nodes) == len(vertices)
    assert all(row["from"] in graph and row["to"] in graph for row in edges)
    assert all(row["direction"] == ("forward" if directed else "undirected") for row in edges)
    return graph, vertices, edges, layout


class StandardGraphTests(unittest.TestCase):
    def test_named_families_match_independent_networkx_constructions(self):
        for descriptor, expected in (
            ({"family": "complete", "order": 7}, nx.complete_graph(7)),
            ({"family": "complete_bipartite", "parts": [3, 5]}, nx.complete_bipartite_graph(3, 5)),
            ({"family": "complete_multipartite", "parts": [2, 3, 4]}, nx.complete_multipartite_graph(2, 3, 4)),
            ({"family": "complete_multipartite", "parts": [1] * 16}, nx.complete_graph(16)),
            ({"family": "cycle", "order": 8}, nx.cycle_graph(8)),
            ({"family": "path", "order": 7}, nx.path_graph(7)),
            ({"family": "star", "order": 7}, nx.star_graph(6)),
            ({"family": "wheel", "order": 8}, nx.wheel_graph(8)),
            ({"family": "hypercube", "dimension": 5}, nx.hypercube_graph(5)),
            ({"family": "petersen"}, nx.petersen_graph()),
        ):
            with self.subTest(descriptor=descriptor):
                graph, vertices, edges, layout = build("standard_graph", descriptor)
                self.assertTrue(nx.is_isomorphic(graph, expected))
                self.assertEqual(len(edges), expected.number_of_edges())
                self.assertEqual(layout, "graph")

    def test_singletons_and_smallest_wheel(self):
        for family in ("complete", "path", "star"):
            graph, _, edges, _ = build("standard_graph", {"family": family, "order": 1})
            self.assertEqual(len(graph), 1)
            self.assertEqual(len(edges), 0)
        graph, _, _, _ = build("standard_graph", {"family": "hypercube", "dimension": 0})
        self.assertEqual(len(graph), 1)
        graph, _, _, _ = build("standard_graph", {"family": "wheel", "order": 4})
        self.assertTrue(nx.is_isomorphic(graph, nx.complete_graph(4)))

    def test_limits_and_parameters_reject_instead_of_silent_substitution(self):
        for descriptor in (
            {"family": "complete", "order": 23}, {"family": "complete", "order": True},
            {"family": "complete_bipartite", "parts": [2, 3, 4]},
            {"family": "complete_multipartite", "parts": [40, 40]},
            {"family": "hypercube", "dimension": 7}, {"family": "petersen", "order": 11},
            {"family": "petersen", "order": 10.0},
            {"family": "cycle", "order": 2}, {"family": "wheel", "order": 3},
            {"family": "path", "order": 5, "parts": [2, 3]},
            {"family": "unrecognized", "order": 4},
        ):
            with self.subTest(descriptor=descriptor), self.assertRaises(DiscreteStructureError):
                build("standard_graph", descriptor)


class StructuralTreeTests(unittest.TestCase):
    def assert_rooted_tree(self, graph, edges):
        self.assertTrue(nx.is_arborescence(graph))
        self.assertEqual(len(edges), len(graph) - 1)
        return next(node for node in graph if graph.in_degree(node) == 0)

    def test_full_mary_tree_has_exact_depth_branches_and_leaves(self):
        for branching, height in ((2, 0), (2, 5), (3, 3), (4, 2), (8, 1)):
            graph, vertices, edges, layout = build("full_mary_tree", {"branching": branching, "height": height})
            root = self.assert_rooted_tree(graph, edges)
            self.assertEqual(len(graph), sum(branching ** depth for depth in range(height + 1)))
            self.assertEqual(max(nx.single_source_shortest_path_length(graph, root).values()), height)
            self.assertEqual(sum(graph.out_degree(node) == 0 for node in graph), branching ** height)
            self.assertTrue(all(graph.out_degree(node) in (0, branching) for node in graph))
            self.assertEqual(layout, "rooted_tree")

    def test_huffman_known_optimum_and_prefix_free_code(self):
        symbols, weights = "abcdef", [5, 9, 12, 13, 16, 45]
        graph, vertices, edges, _ = build("huffman_tree", {"frequencies": [
            {"symbol": symbol, "weight": weight} for symbol, weight in zip(symbols, weights)]})
        root = self.assert_rooted_tree(graph, edges)
        distances = nx.single_source_shortest_path_length(graph, root)
        leaves = {graph.nodes[node]["label"].split(": ", 1)[0]: node for node in graph if graph.out_degree(node) == 0}
        self.assertEqual(sum(weights[index] * distances[leaves[symbol]] for index, symbol in enumerate(symbols)), 224)
        self.assertEqual(graph.nodes[root]["label"], "100")
        codes = []
        for node in leaves.values():
            path = nx.shortest_path(graph, root, node)
            codes.append("".join(graph[left][right]["label"] for left, right in zip(path, path[1:])))
        self.assertTrue(all(not right.startswith(left) for left in codes for right in codes if left != right))
        self.assertTrue(all({graph[node][child]["label"] for child in graph.successors(node)} == {"0", "1"}
                            for node in graph if graph.out_degree(node)))

    def test_huffman_exact_decimals_and_deterministic_ties(self):
        descriptor = {"frequencies": [{"symbol": "a", "weight": .1}, {"symbol": "b", "weight": .2}]}
        graph, _, edges, _ = build("huffman_tree", descriptor)
        root = self.assert_rooted_tree(graph, edges)
        self.assertEqual(graph.nodes[root]["label"], "0.3")
        self.assertEqual(construct_discrete_structure("huffman_tree", descriptor), construct_discrete_structure("huffman_tree", descriptor))
        huge = {"frequencies": [{"symbol": "a", "weight": 1e308}, {"symbol": "b", "weight": 1e308}]}
        graph, _, edges, _ = build("huffman_tree", huge)
        root = self.assert_rooted_tree(graph, edges)
        self.assertEqual(graph.nodes[root]["label"], "2e308")

    def test_huffman_bad_weights_and_symbols_reject(self):
        for frequencies in (
            [{"symbol": "a", "weight": 0}, {"symbol": "b", "weight": 1}],
            [{"symbol": "a", "weight": True}, {"symbol": "b", "weight": 1}],
            [{"symbol": "a", "weight": float("inf")}, {"symbol": "b", "weight": 1}],
            [{"symbol": "a", "weight": float("nan")}, {"symbol": "b", "weight": 1}],
            [{"symbol": "a", "weight": 1}, {"symbol": " a ", "weight": 1}],
        ):
            with self.subTest(frequencies=frequencies), self.assertRaises(DiscreteStructureError):
                build("huffman_tree", {"frequencies": frequencies})

    def test_factor_tree_parent_products_and_prime_leaf_multiplicity(self):
        for number in (2, 13, 12, 60, 2 ** 29, 999_999_937):
            graph, _, edges, _ = build("factor_tree", {"number": number})
            root = self.assert_rooted_tree(graph, edges)
            values = {node: int(graph.nodes[node]["label"]) for node in graph}
            self.assertEqual(values[root], number)
            leaves = []
            for node in graph:
                children = list(graph.successors(node))
                if children:
                    self.assertEqual(math.prod(values[child] for child in children), values[node])
                else:
                    leaves.append(values[node])
                    self.assertFalse(any(values[node] % divisor == 0 for divisor in range(2, math.isqrt(values[node]) + 1)))
            self.assertEqual(math.prod(leaves), number)

    def test_choice_tree_paths_equal_cartesian_product(self):
        descriptor = {"choices": [["红", "蓝"], ["S", "M", "L"], ["甲", "乙"]], "root_label": "选择"}
        graph, _, edges, _ = build("choice_tree", descriptor)
        root = self.assert_rooted_tree(graph, edges)
        paths = {tuple(graph[left][right]["label"] for left, right in zip(path, path[1:]))
                 for leaf in graph if graph.out_degree(leaf) == 0 for path in [nx.shortest_path(graph, root, leaf)]}
        self.assertEqual(paths, set(itertools.product(*descriptor["choices"])))
        self.assertEqual(len(graph), 1 + 2 + 6 + 12)
        empty, _, edges, _ = build("choice_tree", {"choices": []})
        self.assertEqual(len(empty), 1, "The empty product has one empty choice path")
        self.assertEqual(edges, [])

    def test_recursion_tree_exact_sizes_and_termination(self):
        graph, _, edges, _ = build("recursion_tree", {"initial": 16, "branching": 2, "divisor": 2, "base": 1})
        root = self.assert_rooted_tree(graph, edges)
        self.assertEqual(len(graph), 31)
        self.assertEqual(sum(graph.out_degree(node) == 0 for node in graph), 16)
        for left, right in graph.edges:
            self.assertEqual(int(graph.nodes[left]["label"]), 2 * int(graph.nodes[right]["label"]))
        self.assertEqual(graph.nodes[root]["label"], "16")

    def test_tree_limits_invalid_rounding_and_duplicate_choices_reject(self):
        for kind, descriptor in (
            ("full_mary_tree", {"branching": 8, "height": 3}),
            ("choice_tree", {"choices": [["a", " a"]]}),
            ("choice_tree", {"choices": [["a", "b", "c"]] * 5}),
            ("recursion_tree", {"initial": 9, "branching": 2, "divisor": 2, "base": 1}),
            ("recursion_tree", {"initial": 128, "branching": 2, "divisor": 2, "base": 1}),
            ("factor_tree", {"number": 1}),
        ):
            with self.subTest(kind=kind, descriptor=descriptor), self.assertRaises(DiscreteStructureError):
                build(kind, descriptor)


class WordTransitionTests(unittest.TestCase):
    def test_walk_counts_match_independent_word_enumeration(self):
        for alphabet, forbidden in (("012", ["22"]), ("ab", ["aba", "bb"]), ("01", []), ("01", ["0"]), ("01", ["0", "01"])):
            graph, vertices, edges, layout = build("word_transition_graph", {"alphabet": list(alphabet), "forbidden": forbidden})
            start = next(row["id"] for row in vertices if row["label"] == "⟨⟩")
            transitions = {(row["from"], row["edge_label"]): row["to"] for row in edges}
            for length in range(6):
                actual = 0
                for letters in itertools.product(alphabet, repeat=length):
                    state = start
                    for letter in letters:
                        state = transitions.get((state, letter))
                        if state is None:
                            break
                    actual += state is not None
                expected = sum(not any(word in "".join(letters) for word in forbidden)
                               for letters in itertools.product(alphabet, repeat=length))
                self.assertEqual(actual, expected, (alphabet, forbidden, length))
            self.assertEqual(layout, "graph")

    def test_transition_parameters_reject_unknown_symbols_and_duplicates(self):
        for descriptor in (
            {"alphabet": ["a", "a"], "forbidden": []},
            {"alphabet": ["a", "b"], "forbidden": ["c"]},
            {"alphabet": ["a", "b"], "forbidden": ["ab", "ab"]},
            {"alphabet": ["a", "b"], "forbidden": [""]},
        ):
            with self.subTest(descriptor=descriptor), self.assertRaises(DiscreteStructureError):
                build("word_transition_graph", descriptor)


if __name__ == "__main__":
    unittest.main()
