"""Problem graphs use exact source evidence, never catalog prerequisite edges."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classification_semantic import _validated_update
from question_knowledge_graph import MAX_EVIDENCE_CHARS, build_question_graph
from server_i18n import topic_label
from teaching import _KNOWLEDGE_GRAPH, analyze_messages, analyze_question, enrich_question_graph


def ids(graph):
    return {node["id"] for node in graph["nodes"]}


def pairs(graph):
    return {(edge["from"], edge["to"]) for edge in graph["edges"]}


class QuestionKnowledgeGraphTests(unittest.TestCase):
    def assert_sourced(self, graph):
        for record in [*graph["nodes"], *graph["edges"]]:
            self.assertTrue(record["evidence"])
            for evidence in record["evidence"]:
                self.assertIn(evidence["source"], ("question", "solution"))
                self.assertTrue(evidence["quote"].strip())
                self.assertIn(evidence["quote"], graph["sources"][evidence["source"]])

    def test_every_catalog_topic_stays_alone_without_neighbor_expansion(self):
        for node in _KNOWLEDGE_GRAPH["nodes"]:
            with self.subTest(topic=node["name"]):
                result = analyze_question("本题研究" + node["name"])
                graph = result["question_graph"]
                self.assertEqual(ids(graph), {node["id"]})
                self.assertEqual(graph["edges"], [])
                self.assertEqual(result["prerequisite_points"], [])
                self.assertEqual(result["knowledge_path"], [])
                self.assert_sourced(graph)

    def test_every_english_catalog_label_is_matched_before_generic_translation(self):
        for node in _KNOWLEDGE_GRAPH["nodes"]:
            with self.subTest(topic=node["name"]):
                label = topic_label(node["name"], "en")
                self.assertNotEqual(label, node["name"])
                graph = analyze_question("Study " + label)["question_graph"]
                self.assertEqual(ids(graph), {node["id"]})
                self.assertEqual(graph["edges"], [])
                self.assert_sourced(graph)

    def test_english_named_concepts_and_real_operation_terms_keep_actual_dependencies(self):
        for text, expected in [
            ("Use set operations to prove inclusion-exclusion", ("set_operation", "count_inclusion")),
            ("Use set operation to prove inclusion-exclusion", ("set_operation", "count_inclusion")),
            ("Using inclusion-exclusion calculate the union cardinality", ("count_inclusion", "set_operation")),
            ("Use generating function to solve nonhomogeneous recurrence", ("count_generating", "recurrence_nonhomogeneous")),
            ("Use adjacency matrix to prove Eulerian graph", ("graph_adjacency", "graph_euler")),
        ]:
            with self.subTest(text=text):
                graph = analyze_question(text)["question_graph"]
                self.assertEqual(ids(graph), set(expected))
                self.assertEqual(pairs(graph), {expected})
                self.assert_sourced(graph)

    def test_symbolic_problem_has_actual_operation_without_neighbors(self):
        graph = analyze_question(r"设 A={1,2},B={2,3}，求 A\cup B 与 A\cap B")["question_graph"]
        self.assertEqual(ids(graph), {"set_operation"})
        self.assertEqual(graph["edges"], [])
        self.assert_sourced(graph)

    def test_background_set_definition_does_not_assert_set_operations(self):
        graph = analyze_question("设集合 A={1,2,3}")["question_graph"]
        self.assertNotIn("set_operation", ids(graph))

    def test_explicit_dependencies_across_different_course_modules(self):
        for text, expected in [
            ("使用真值表验证逻辑等价", ("logic_truth_table", "logic_equivalence")),
            ("使用生成函数求解非齐次递推", ("count_generating", "recurrence_nonhomogeneous")),
            ("利用欧几里得算法求线性同余方程", ("number_gcd", "number_linear_congruence")),
            ("利用邻接矩阵计算路径与连通性", ("graph_adjacency", "graph_connectivity")),
        ]:
            with self.subTest(text=text):
                graph = analyze_question(text)["question_graph"]
                self.assertEqual(ids(graph), set(expected))
                self.assertEqual(pairs(graph), {expected})
                self.assert_sourced(graph)

    def test_arbitrary_catalog_data_uses_same_rule_without_topic_branches(self):
        catalog = [{"id": "x", "name": "概念甲", "prerequisites": ["概念乙"]},
                   {"id": "y", "name": "概念乙", "prerequisites": ["未涉及概念"]},
                   {"id": "z", "name": "未涉及概念", "prerequisites": ["概念甲"]}]
        graph = build_question_graph("利用概念甲计算概念乙", "", catalog, {}, lambda _: [], lambda x: x)
        self.assertEqual(ids(graph), {"x", "y"})
        self.assertEqual(pairs(graph), {("x", "y")})
        reversed_catalog = deepcopy(catalog)
        for node in reversed_catalog:
            node["prerequisites"] = [other["name"] for other in catalog if other["id"] != node["id"]]
        self.assertEqual(graph, build_question_graph("利用概念甲计算概念乙", "", reversed_catalog, {}, lambda _: [], lambda x: x))

    def test_cooccurrence_and_sequence_do_not_invent_dependencies(self):
        for text in ("判断二部图和欧拉图", "先求真值表，再研究逻辑等价"):
            with self.subTest(text=text):
                graph = analyze_question(text)["question_graph"]
                self.assertEqual(len(graph["nodes"]), 2)
                self.assertEqual(graph["edges"], [])

    def test_dependency_direction_comes_from_source_not_catalog(self):
        graph = analyze_question("生成函数依赖非齐次递推")["question_graph"]
        self.assertEqual(pairs(graph), {("recurrence_nonhomogeneous", "count_generating")})

    def test_actual_solution_adds_evidenced_usage_and_dependency(self):
        question = "研究逻辑等价"
        solution = "使用真值表验证逻辑等价"
        graph = enrich_question_graph(analyze_question(question), question, solution)["question_graph"]
        self.assertEqual(ids(graph), {"logic_truth_table", "logic_equivalence"})
        self.assertEqual(pairs(graph), {("logic_truth_table", "logic_equivalence")})
        self.assertEqual(graph["sources"], {"question": question, "solution": solution})
        self.assert_sourced(graph)

    def test_negated_optional_and_illustrative_topics_are_not_usage(self):
        for text in ("不用容斥原理", "本题不需要使用欧几里得算法", "拓展：函数与映射", "例如，研究最小生成树", "Do not use a truth table", "A truth table is not needed"):
            with self.subTest(text=text):
                graph = analyze_question(text)["question_graph"]
                self.assertEqual(graph["nodes"], [])
                self.assertEqual(graph["edges"], [])

    def test_maximal_topic_aliases_do_not_add_incidental_parent_topics(self):
        for text, expected in (("求最小生成树", "tree_mst"), ("求非齐次递推", "recurrence_nonhomogeneous"), ("求复合函数", "function_composition")):
            with self.subTest(text=text):
                graph = analyze_question(text)["question_graph"]
                self.assertEqual(ids(graph), {expected})

    def test_english_uses_original_quote_and_explicit_relation(self):
        text = "Using a truth table to prove logical equivalence"
        graph = analyze_question(text)["question_graph"]
        self.assertEqual(ids(graph), {"logic_truth_table", "logic_equivalence"})
        self.assertEqual(pairs(graph), {("logic_truth_table", "logic_equivalence")})
        self.assert_sourced(graph)

    def test_short_aliases_follow_actual_mathematical_context(self):
        for text, expected in (("判断两个图是否同构", "graph_isomorphism"),
                               ("判断关系是否对称", "relation_property"),
                               ("Prove G is a group", "algebra_group"),
                               ("求一条长度为3的路径", "graph_connectivity")):
            with self.subTest(text=text):
                self.assertEqual(ids(analyze_question(text)["question_graph"]), {expected})

    def test_different_question_selection_cannot_reuse_previous_graph(self):
        messages = [{"role": "user", "content": "使用真值表验证逻辑等价"},
                    {"role": "assistant", "content": "使用真值表验证逻辑等价"},
                    {"role": "user", "content": "设 A={1,2}, B={2,3}，求 A∪B"}]
        graph = analyze_messages(messages)["question_graph"]
        self.assertEqual(ids(graph), {"set_operation"})
        self.assertEqual(graph["sources"]["solution"], "")
        self.assertEqual(graph["edges"], [])

    def test_semantic_classification_cannot_supply_course_or_fake_graph_facts(self):
        text = "使用真值表验证逻辑等价"
        existing = analyze_question(text)
        result = _validated_update({"category": "图论", "knowledge_points": ["最小生成树"],
                                    "question_graph": {"nodes": [{"id": "tree_mst"}]}}, existing, text)
        self.assertEqual(ids(result["question_graph"]), {"logic_truth_table", "logic_equivalence"})
        self.assertEqual(pairs(result["question_graph"]), {("logic_truth_table", "logic_equivalence")})
        self.assertEqual(result["prerequisite_points"], [])
        self.assertEqual(result["knowledge_path"], [])

    def test_semantic_update_preserves_only_answer_bound_to_exact_question(self):
        text = "研究逻辑等价"
        solution = "使用真值表验证逻辑等价"
        existing = enrich_question_graph(analyze_question(text), text, solution)
        update = {"category": "命题逻辑", "knowledge_points": ["逻辑等价"],
                  "question_graph": {"sources": {"solution": "利用生成函数求解非齐次递推"}}}
        result = _validated_update(update, existing, text)
        self.assertEqual(result["question_graph"], existing["question_graph"])
        self.assertEqual(pairs(result["question_graph"]), {("logic_truth_table", "logic_equivalence")})
        other = _validated_update(update, existing, "求 A∪B")
        self.assertEqual(other["question_graph"]["sources"]["solution"], "")
        self.assertEqual(ids(other["question_graph"]), {"set_operation"})
        self.assertEqual(other["question_graph"]["edges"], [])

    def test_unknown_question_stays_empty(self):
        graph = analyze_question("请解释这段材料的意义")["question_graph"]
        self.assertEqual(graph["nodes"], [])
        self.assertEqual(graph["edges"], [])

    def test_negative_and_background_scope_preserves_independent_actual_usage(self):
        catalog = [{"id": "a", "name": "甲理论"}, {"id": "b", "name": "乙方法"},
                   {"id": "c", "name": "丙构造"}]
        for text, expected in [
            ("利用甲理论计算一个数，不需要使用乙方法", {"a"}),
            ("证明甲理论，例如可用乙方法", {"a"}),
            ("本题只考甲理论，不考乙方法", {"a"}),
            ("本题只需甲理论，不能使用乙方法", {"a"}),
            ("例如，研究甲理论，利用乙方法计算丙构造", set()),
            ("例如研究甲理论，但本题使用乙方法计算丙构造", {"b", "c"}),
            ("不用甲理论而是使用乙方法计算丙构造", {"b", "c"}),
        ]:
            with self.subTest(text=text):
                graph = build_question_graph(text, "", catalog, {}, lambda _: [], lambda x: x)
                self.assertEqual(ids(graph), expected)
                self.assert_sourced(graph)

    def test_goal_targets_actual_next_concept_in_the_same_usage_unit(self):
        catalog = [{"id": "a", "name": "甲理论"}, {"id": "b", "name": "乙方法"}]
        for text in ("使用甲理论计算一个数，最后讨论乙方法",
                     "使用甲理论计算一个数再讨论乙方法",
                     "使用甲理论计算一个数并说明乙方法",
                     "利用甲理论，计算乙方法"):
            with self.subTest(text=text):
                graph = build_question_graph(text, "", catalog, {}, lambda _: [], lambda x: x)
                self.assertEqual(ids(graph), {"a", "b"})
                self.assertEqual(graph["edges"], [])

    def test_cross_comma_dependency_requires_explicit_causal_reference(self):
        catalog = [{"id": "a", "name": "甲理论"}, {"id": "b", "name": "乙方法"},
                   {"id": "c", "name": "丙构造"}]
        for text, expected in [
            ("利用甲理论，据此计算乙方法", {("a", "b")}),
            ("Using 甲理论, thus compute 乙方法", {("a", "b")}),
            ("使用甲理论计算乙方法，据此证明丙构造", {("a", "b"), ("b", "c")}),
        ]:
            with self.subTest(text=text):
                graph = build_question_graph(text, "", catalog, {}, lambda _: [], lambda x: x)
                self.assertEqual(pairs(graph), expected)
                self.assert_sourced(graph)

    def test_long_source_keeps_literal_evidence_bounded_without_distant_edges(self):
        catalog = [{"id": "a", "name": "甲理论"}, {"id": "b", "name": "乙方法"}]
        text = "背景材料" * 1000 + "使用甲理论计算一个数" + "中间说明" * 1000 + "最后讨论乙方法"
        graph = build_question_graph(text, "", catalog, {}, lambda _: [], lambda x: x)
        self.assertEqual(ids(graph), {"a", "b"})
        self.assertEqual(graph["edges"], [])
        self.assert_sourced(graph)
        for node in graph["nodes"]:
            self.assertLessEqual(len(node["evidence"]), 8)
            for evidence in node["evidence"]:
                self.assertLessEqual(len(evidence["quote"]), MAX_EVIDENCE_CHARS)

    def test_reviewed_real_source_scope_and_independent_targets(self):
        for text in ("利用集合运算求 A 与 B 的并集，不需要使用函数与映射",
                     "证明集合运算的分配律，例如可用元素法",
                     "本题只考集合运算，不考容斥原理",
                     "本题只需集合运算，不能使用容斥原理"):
            with self.subTest(text=text):
                self.assertEqual(ids(analyze_question(text)["question_graph"]), {"set_operation"})
        for text in ("使用集合运算计算并集大小，最后讨论函数与映射",
                     "使用集合运算计算并集大小再讨论函数与映射",
                     "利用集合运算求并集，并比较容斥原理与函数与映射"):
            with self.subTest(text=text):
                self.assertEqual(analyze_question(text)["question_graph"]["edges"], [])


if __name__ == "__main__":
    unittest.main()
