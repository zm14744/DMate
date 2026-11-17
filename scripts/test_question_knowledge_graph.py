"""Problem graphs use exact source evidence, never catalog prerequisite edges."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classification_semantic import _validated_update
from question_knowledge_graph import MAX_EVIDENCE_CHARS, build_question_graph
from question_topic_structure import mathematical_text
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

    def test_unnamed_choice_and_staged_assignment_are_structural_families(self):
        for population, selected, unit in ((9, 4, "名学生"), (23, 6, "个零件"), (140, 3, "本书")):
            with self.subTest(population=population, unit=unit):
                question = f"从{population}{unit}中选出{selected}个组成不区分顺序的小组，有多少种不同选法？"
                graph = analyze_question(question)["question_graph"]
                self.assertEqual(ids(graph), {"count_perm_comb"})
                staged = question.replace("有多少种", "再从其中指定一名队长，有多少种")
                self.assertEqual(ids(analyze_question(staged)["question_graph"]), {"count_perm_comb", "count_basic"})

    def test_unnamed_mathematical_tasks_span_existing_catalog_modules(self):
        cases = [
            ("判断¬(p→q)与p∧¬q的真假是否对所有赋值始终相同", {"logic_connectives", "logic_equivalence"}),
            ("将每个整数x都存在整数y满足y>x写成符号表达式，再写出它的否定，否定号只出现在y>x之前", {"predicate_quantifier", "predicate_reasoning"}),
            ("在整数集合上定义xRy当x-y能被7整除。验证xRx、xRy推出yRx、xRy且yRz推出xRz，并写出分别满足R形成的集合", {"number_prime", "relation_property", "relation_equivalence"}),
            ("设f从整数集合映到非负整数集合，f(x)=x²。不同输入能给出相同输出吗？目标集合中的每一个数都能成为输出吗？", {"function_mapping", "function_injection"}),
            ("求所有整数x，使18x除以42的余数为12", {"number_congruence", "number_linear_congruence"}),
            ("双向道路AB、BC、CA连接几个地点。能否每条道路恰好走一次并回到出发地？", {"graph_euler"}),
            ("集合上运算a*b满足(a*b)*c=a*(b*c)，找e使e*a=a*e=a，再为每个a找b使a*b=b*a=e", {"algebra_system", "algebra_group"}),
        ]
        for question, expected in cases:
            with self.subTest(question=question):
                graph = analyze_question(question)["question_graph"]
                self.assertEqual(ids(graph), expected)
                self.assert_sourced(graph)

    def test_recurrence_notations_preserve_type_and_initial_conditions(self):
        for question in (
            "数列满足a₀=2，a₁=3，aₙ=3aₙ₋₁−2aₙ₋₂。求只含n的表达式。",
            r"给定a_{0}=2,a_{1}=3,a_{n}=3a_{n-1}-2a_{n-2}，求通项公式",
            r"a_0=2,a_1=3,a_n=3a_{n-1}-2a_{n-2}，求a_n",
        ):
            with self.subTest(question=question):
                graph = analyze_question(question)["question_graph"]
                self.assertEqual(ids(graph), {"recurrence_homogeneous", "recurrence_initial"})
                self.assert_sourced(graph)
        nonhomogeneous = analyze_question(r"a_0=1，a_n=2a_{n-1}+n，求a_n")["question_graph"]
        self.assertEqual(ids(nonhomogeneous), {"recurrence_nonhomogeneous", "recurrence_initial"})

    def test_modeling_task_joins_definition_and_goal_across_clauses(self):
        question = "长度为n的0、1字符串不允许有两个1相邻。设有aₙ个，根据末尾是0还是1，把aₙ用前面较短字符串的数量表示，并写出最初两个值"
        graph = analyze_question(question)["question_graph"]
        self.assertEqual(ids(graph), {"recurrence_model", "recurrence_initial", "count_basic"})
        self.assert_sourced(graph)

    def test_excluded_mentions_cannot_erase_actual_formula_or_create_topics(self):
        excluded = analyze_question("容斥原理不是本题的考点。计算15与35的最大公因数")["question_graph"]
        self.assertEqual(ids(excluded), {"number_gcd", "number_prime"})
        actual = analyze_question("不用真值表证明p∧q与q∧p等价")["question_graph"]
        self.assertEqual(ids(actual), {"logic_connectives", "logic_equivalence"})

    def test_optional_methods_require_actual_usage_or_independent_task_evidence(self):
        question = "本题可用容斥原理或鸽巢原理任选一种。13个人分别出生在12个月份，证明至少有两人出生在同一月份。"
        local = analyze_question(question)
        self.assertEqual(ids(local["question_graph"]), {"count_pigeonhole"})
        refined = enrich_question_graph(local, question, "使用鸽巢原理，将人分入十二个月份。至少有两人同月出生。")
        self.assertEqual(ids(refined["question_graph"]), {"count_pigeonhole"})
        self.assertNotIn("count_inclusion", ids(refined["question_graph"]))

    def test_local_results_are_catalog_bounded_and_request_semantic_review(self):
        result = analyze_question("从17名学生中选出5名组成小组，有多少种选法")
        self.assertEqual(result["category"], "计数与组合")
        self.assertEqual(result["knowledge_points"], ["排列与组合"])
        self.assertEqual(result["classification_revision"], "catalog-structure/2")
        self.assertEqual(result["classification_status"], "local")
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["question_graph"]["classifier_revision"], "catalog-structure/2")

    def test_specific_task_context_rejects_lexical_substrings_and_previous_topics(self):
        cases = [
            ("Let f: Z→{0,1,2,…} be f(x)=x². Can distinct inputs have the same output? Is every element of the target set reached? Explain where this happens.",
             {"function_mapping", "function_injection"}, {"relation_property"}),
            ("设论域非空。将(∀x P(x))∨(∃y Q(y))改写为所有∀、∃符号都在最前面的等价式，并说明变元条件。",
             {"predicate_quantifier", "predicate_prenex", "predicate_reasoning", "predicate_variable"}, {"algebra_ring_field", "logic_equivalence"}),
            ("我上一题研究过逆函数；这次不求任何逆。已知f(x)=2x+1，g(x)=x²，求g(f(x))与f(g(x))。",
             {"function_composition"}, {"function_inverse"}),
        ]
        for question, required, forbidden in cases:
            with self.subTest(question=question):
                actual = ids(analyze_question(question)["question_graph"])
                self.assertLessEqual(required, actual)
                self.assertFalse(actual & forbidden)

    def test_nonlinear_recurrence_is_not_labeled_as_linear_forcing(self):
        graph = analyze_question(r"a_0=1，a_n=a_{n-1}^2+1，求a_n")["question_graph"]
        self.assertFalse(ids(graph) & {"recurrence_homogeneous", "recurrence_nonhomogeneous"})

    def test_task_origin_is_separate_from_names_and_legacy_patterns(self):
        named = analyze_question("本题研究真值表")["question_graph"]
        self.assertEqual(named["nodes"][0]["origin"], "term_candidate")
        legacy = analyze_question("判断关系是否对称")["question_graph"]
        self.assertTrue(legacy["nodes"])
        self.assertTrue(all(node["origin"] == "term_candidate" for node in legacy["nodes"]))
        concrete = analyze_question("从19名学生中选出4人组成小组，有多少种选法")["question_graph"]
        self.assertEqual({node["id"] for node in concrete["nodes"] if node["origin"] == "task_structure"}, {"count_perm_comb"})
        self.assert_sourced(concrete)

    def test_actual_integer_divisibility_has_a_task_witness_without_ancestry(self):
        cases = (
            "在整数上定义xRy当且仅当x-y能被7整除，验证xRx。",
            "在{1,2,4,8}中定义a≼b当a整除b，判断它是否满足传递。",
            "求能同时整除105和63的最大正整数。",
        )
        for question in cases:
            with self.subTest(question=question):
                graph = analyze_question(question)["question_graph"]
                witness = next(node for node in graph["nodes"] if node["id"] == "number_prime")
                self.assertEqual(witness["origin"], "task_structure")
                self.assert_sourced(graph)
        named = analyze_question("本题研究最大公因数与欧几里得算法")["question_graph"]
        self.assertNotIn("number_prime", ids(named), "A named topic alone cannot create an ancestor fact")

    def test_declared_symbolic_coefficient_supports_linear_congruence(self):
        for question in (
            "已知u=7，求整数v使uv≡3(mod26)。",
            "给定k=-2，求整数t，使kt除以17的余数为5。",
            "e=3，求0<d<40使ed除以40余1。",
        ):
            with self.subTest(question=question):
                graph = analyze_question(question)["question_graph"]
                witness = next(node for node in graph["nodes"] if node["id"] == "number_linear_congruence")
                self.assertEqual(witness["origin"], "task_structure")
                self.assert_sourced(graph)
        assigned = analyze_question("已知u=7、v=9，验证uv除以26的余数为11。")["question_graph"]
        self.assertFalse(any(node["id"] == "number_linear_congruence" and node["origin"] == "task_structure" for node in assigned["nodes"]))

    def test_task_origin_rejects_forged_and_excluded_claims(self):
        question = "不用真值表证明p∧q与q∧p等价"
        forged = {"question_graph": {"version": 1, "nodes": [{"id": "logic_truth_table", "origin": "task_structure"}], "edges": []}}
        graph = enrich_question_graph(forged, question)["question_graph"]
        self.assertNotIn("logic_truth_table", ids(graph))
        self.assertTrue(all(node["origin"] == "task_structure" for node in graph["nodes"]))
        self.assert_sourced(graph)

    def test_unicode_powers_and_indices_keep_distinct_mathematical_roles(self):
        normalized = mathematical_text("B⁴ z⁻¹ aₙ₋₂")
        self.assertIn("b^{4}", normalized)
        self.assertIn("z^{-1}", normalized)
        self.assertIn("a_{n-2}", normalized)
        self.assertNotIn("z_{-1}", normalized)

    def test_binary_directed_table_and_monotone_expansion_use_generic_vertices(self):
        for matrix_symbol, first, middle, last in (("B", "u", "v", "w"), ("C", "r", "s", "t")):
            with self.subTest(symbol=matrix_symbol, vertices=(first, middle, last)):
                question = (
                    f"有向表{matrix_symbol}=[[0,1,0],[0,0,1],[0,0,0]]。"
                    f"第{first}行、第{middle}列为1表示{first}直接到{middle}。"
                    f"求{matrix_symbol}²，把每个正数改为1，解释两步路径的可达性。"
                    f"只许把0改为1，求最少扩充使({first}→{middle}且{middle}→{last})⇒{first}→{last}。"
                )
                graph = analyze_question(question)["question_graph"]
                tasks = {node["id"] for node in graph["nodes"] if node["origin"] == "task_structure"}
                self.assertLessEqual({"graph_adjacency", "graph_matrix", "graph_connectivity", "relation_property", "relation_closure"}, tasks)
                self.assertFalse(tasks & {"graph_shortest", "tree_matrix_tree"})
                self.assert_sourced(graph)

    def test_binary_table_requires_rectangular_data_and_edge_meaning(self):
        malformed = "表B=[[0,1],[1]]，第u行第v列为1表示u直接到v，求B²。"
        unrelated = "数据B=[[0,1],[1,0]]，第u行第v列为1表示一个人的答案正确。"
        for question in (malformed, unrelated):
            with self.subTest(question=question):
                graph = analyze_question(question)["question_graph"]
                tasks = {node["id"] for node in graph["nodes"] if node["origin"] == "task_structure"}
                self.assertFalse(tasks & {"graph_adjacency", "graph_matrix", "graph_connectivity"})

    def test_finite_operation_table_is_an_actual_task_not_a_course_ancestor(self):
        for question in (
            "Let S={id,u,v}; u sends 2 to 4 and v sends 4 to 2. Write the complete operation table on S under composition.",
            "在T={1,a,b}上定义二元运算，补全T的运算表。",
            "Let K={id,p,q}. Complete the Cayley table on K using the specified permutations.",
        ):
            with self.subTest(question=question):
                graph = analyze_question(question)["question_graph"]
                task = next(node for node in graph["nodes"] if node["id"] == "algebra_system")
                self.assertEqual(task["origin"], "task_structure")
                self.assert_sourced(graph)
        optional = analyze_question("Let S={id,u,v}. You may write an operation table on S if you wish.")["question_graph"]
        self.assertFalse(any(node["id"] == "algebra_system" and node["origin"] == "task_structure" for node in optional["nodes"]))

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
