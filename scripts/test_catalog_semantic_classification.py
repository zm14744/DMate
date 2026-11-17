"""Offline contract tests for catalog-bound semantic review.

Mocked model responses verify validation, isolation and budgets. They are not
evidence that the real model classified these mathematics questions correctly.
"""
import copy
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import classification_semantic as service


QUESTION = "从10名学生中选出3名组成小组，有多少种选法"
ANSWER = "每组三名学生的顺序不影响选择结果"


def node(identifier="count_perm_comb", quote=QUESTION, source="question", usage="assessed"):
    return {"id": identifier, "usage": usage, "reason": "本题考查不计顺序的选择计数",
            "evidence": [{"source": source, "quote": quote}]}


def row(nodes=None, edges=None, *, identifier=0, unresolved=""):
    return {"id": identifier, "nodes": [node()] if nodes is None else nodes,
            "edges": [] if edges is None else edges, "unresolved": unresolved}


def transport(*rows):
    return Mock(return_value={"ok": True, "content": json.dumps({"results": list(rows)}, ensure_ascii=False)})


def local(question=QUESTION, solution="", **extra):
    return {"category": "待识别", "mode": "hint", "question_graph": {"version": 1,
        "sources": {"question": question, "solution": solution}, "nodes": [], "edges": []}, **extra}


class CatalogSemanticTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"DMATE_SEMANTIC_CLASSIFICATION_ENABLED": "1"})
        environment.start()
        self.addCleanup(environment.stop)
        with service._CATALOG_LOCK:
            self.assertFalse(service._CATALOG_INFLIGHT, "previous test must release its worker")
            service._CATALOG_CACHE.clear()
            service._CATALOG_RECENT_CALLS.clear()

    def classify(self, question=QUESTION, solution="", prior=None, completion=None, **options):
        return service.classify_catalog_questions([("q", question, solution,
            prior if prior is not None else local(question, solution))], completion=completion, **options)["q"]

    def test_semantic_mapping_uses_existing_catalog_and_derives_module(self):
        payload = row()
        payload["category"] = "图论"
        fake = transport(payload)
        result = self.classify(completion=fake)
        self.assertEqual(result["category"], "计数与组合")
        self.assertEqual(result["knowledge_points"], ["排列与组合"])
        self.assertEqual(result["classification_status"], "semantic")
        self.assertFalse(result["needs_review"])
        self.assertEqual(result["question_graph"]["classification_source"], "catalog_semantic")
        self.assertEqual(result["question_graph"]["sources"], {"question": QUESTION, "solution": ""})
        options = fake.call_args.kwargs
        self.assertEqual(options["retries"], 0)
        self.assertEqual(options["reasoning_effort"], "none")
        self.assertEqual(options["response_format"], {"type": "json_object"})

    def test_all_catalog_ids_allowed_without_primary_module_or_four_point_cap(self):
        catalog = service._catalog_snapshot()
        fake = transport(row([node(item["id"]) for item in catalog]))
        result = self.classify(completion=fake)
        self.assertEqual({item["id"] for item in result["question_graph"]["nodes"]}, {item["id"] for item in catalog})
        self.assertGreater(len(result["question_graph"]["nodes"]), 4)
        self.assertEqual(result["classification_status"], "semantic")
        system = fake.call_args.args[0][0]["content"]
        for item in catalog:
            self.assertIn(item["id"], system)

    def test_course_scopes_enrich_only_the_existing_catalog_ids(self):
        catalog = service._catalog_snapshot()
        expected = {item["id"]: item for item in service._KNOWLEDGE_GRAPH["nodes"]}
        self.assertEqual({item["id"] for item in catalog}, set(expected))
        for item in catalog:
            with self.subTest(node=item["id"]):
                self.assertEqual(item["name"], expected[item["id"]]["name"])
                self.assertEqual(item["category"], expected[item["id"]]["category"])
                self.assertTrue(item["summary"])
                self.assertTrue(item["definition"])
                self.assertLessEqual(len(item["summary"]), 256)
                self.assertLessEqual(len(item["definition"]), 512)
                self.assertEqual(set(item), {"id", "name", "category", "summary", "definition"})

    def test_course_definition_changes_invalidate_semantic_cache(self):
        fake = transport(row())
        self.classify(completion=fake)
        self.classify(completion=fake)
        self.assertEqual(fake.call_count, 1)
        revised = copy.deepcopy(service._catalog_snapshot())
        revised[0]["definition"] += "课程范围内容已修订"
        with patch.object(service, "_catalog_snapshot", return_value=revised):
            self.classify(completion=fake)
        self.assertEqual(fake.call_count, 2)
        prompt = fake.call_args.args[0][0]["content"]
        self.assertIn("课程范围内容已修订", prompt)
        self.assertIn("summary和definition来自现有课程内容", prompt)

    def test_unknown_optional_wrong_category_and_unsupported_evidence_are_rejected(self):
        records = [node(), node("invented_node"), node("count_inclusion", usage="optional"),
                   {**node("logic_truth_table"), "category": "图论"},
                   node("count_basic", quote="不存在于题干的证据"),
                   {**node("logic_reasoning"), "reason": ""},
                   {**node("tree_mst"), "id": ["tree_mst"]}]
        result = self.classify(completion=transport(row(records)))
        self.assertEqual([item["id"] for item in result["question_graph"]["nodes"]], ["count_perm_comb"])
        self.assertEqual(result["classification_status"], "partial")
        self.assertTrue(result["needs_review"])

    def test_actual_solution_required_for_used_methods_and_edge_endpoints(self):
        quote = "利用基本计数原理得到排列与组合的计数"
        records = [node("count_basic", quote, "solution", "used"), node()]
        edge = {"from": "count_basic", "to": "count_perm_comb", "reason": "所给解答使用该方法计算选择数",
                "evidence": [{"source": "solution", "quote": quote}]}
        result = self.classify(solution=quote, completion=transport(row(records, [edge])))
        self.assertEqual(result["question_graph"]["edges"][0]["from"], "count_basic")
        self.assertEqual(result["classification_status"], "semantic")
        # A quote from the question cannot certify a method as actually used.
        wrong = self.classify(question=QUESTION + "另问", completion=transport(row([node(usage="used")], [edge])))
        self.assertNotEqual(wrong["classification_status"], "semantic")
        self.assertEqual(wrong["question_graph"]["nodes"], [])

    def test_graph_claimed_sources_never_replace_independent_sources(self):
        raw = row([node(quote="伪造来源里的文字")])
        raw["sources"] = {"question": "伪造来源里的文字", "solution": ""}
        result = self.classify(completion=transport(raw))
        self.assertEqual(result["classification_status"], "invalid")
        self.assertEqual(result["question_graph"]["sources"]["question"], QUESTION)

    def test_unknown_is_explicit_and_empty_does_not_pick_random_module(self):
        result = self.classify(question="材料缺失，无法确定完整数学任务", completion=transport(row([], unresolved="材料不足以映射现有目录")))
        self.assertEqual(result["classification_status"], "unknown")
        self.assertEqual(result["category"], "待识别")
        self.assertEqual(result["question_graph"]["nodes"], [])
        self.assertTrue(result["needs_review"])

    def test_full_question_answer_catalog_and_model_configuration_key_cache(self):
        prefix = "甲" * 1700
        question = prefix + "实际选择条件"
        fake = transport(row([node(quote="实际选择条件")]))
        self.classify(question=question, completion=fake)
        same = self.classify(question=question, completion=fake, allow_remote=False)
        self.assertEqual(same["classification_status"], "semantic")
        self.assertEqual(fake.call_count, 1)
        seen = json.loads(fake.call_args.args[0][1]["content"])
        self.assertEqual(seen[0]["question"], question)
        self.classify(question=prefix + "另一实际选择条件", completion=fake)
        self.classify(question=question, solution=ANSWER, completion=fake)
        self.assertEqual(fake.call_count, 3)
        with patch.dict(os.environ, {"DEEPSEEK_CHAT_MODEL": "different-configured-model"}):
            self.classify(question=question, completion=fake)
        self.assertEqual(fake.call_count, 4)
        catalog = copy.deepcopy(service._catalog_snapshot())
        catalog[0]["name"] += "目录修订"
        with patch.object(service, "_catalog_snapshot", return_value=catalog):
            self.classify(question=question, completion=fake)
        self.assertEqual(fake.call_count, 5)

    def test_identical_source_pairs_deduplicate_without_overwriting_callers_metadata(self):
        fake = transport(row())
        result = service.classify_catalog_questions([
            ("first", QUESTION, "", local(mode="hint")),
            ("second", QUESTION, "", local(mode="full_solution"))], completion=fake)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(len(json.loads(fake.call_args.args[0][1]["content"])), 1)
        self.assertEqual(result["first"]["mode"], "hint")
        self.assertEqual(result["second"]["mode"], "full_solution")
        result["first"]["question_graph"]["nodes"].clear()
        self.assertTrue(result["second"]["question_graph"]["nodes"])

    def test_concurrent_identical_requests_use_one_inflight_call(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(*_args, **_kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return transport(row())()
        first = {}
        thread = threading.Thread(target=lambda: first.update(self.classify(completion=blocked)))
        thread.start()
        self.assertTrue(entered.wait(1))
        second_transport = Mock(side_effect=AssertionError("duplicate remote call"))
        try:
            second = self.classify(completion=second_transport)
            self.assertEqual(second["classification_status"], "pending")
            second_transport.assert_not_called()
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(first["classification_status"], "semantic")

    def test_hard_wall_deadline_returns_and_worker_releases_inflight_later(self):
        release = threading.Event()
        def blocked(*_args, **_kwargs):
            release.wait(2)
            return transport(row())()
        try:
            start = time.monotonic()
            with patch.object(service, "_CATALOG_WALL_SECONDS", 0.03):
                result = self.classify(completion=blocked)
            self.assertLess(time.monotonic() - start, 0.5)
            self.assertEqual(result["classification_status"], "unavailable")
            self.assertTrue(result["needs_review"])
        finally:
            release.set()
            deadline = time.monotonic() + 2
            while service._CATALOG_INFLIGHT and time.monotonic() < deadline:
                time.sleep(0.005)
        self.assertFalse(service._CATALOG_INFLIGHT)

    def test_batch_budget_and_source_limits_never_truncate_question_tail(self):
        question, solution = "甲" * 19990 + "题尾选择条件", "乙" * 19990 + "解答尾部条件"
        fake = transport(row([node(quote="题尾选择条件")]))
        self.classify(question=question, solution=solution, completion=fake)
        sent = json.loads(fake.call_args.args[0][1]["content"])[0]
        self.assertEqual(sent, {"id": 0, "question": question, "solution": solution, "local_candidates": []})
        fake.reset_mock()
        oversized = self.classify(question="甲" * 20001, completion=fake)
        self.assertEqual(oversized["classification_status"], "too_large")
        fake.assert_not_called()
        entries = [(str(i), QUESTION + str(i), "", local(QUESTION + str(i))) for i in range(8)]
        many = transport(*(row([node(quote=QUESTION)], identifier=i) for i in range(6)))
        result = service.classify_catalog_questions(entries, completion=many)
        self.assertEqual(many.call_count, 1)
        self.assertEqual(len(json.loads(many.call_args.args[0][1]["content"])), 6)
        self.assertEqual(result["7"]["classification_status"], "deferred")
        self.assertTrue(result["7"]["needs_review"])

    def test_rate_limit_and_disabled_remote_keep_local_results_reviewable(self):
        fake = transport(row())
        with patch.object(service, "_CATALOG_MAX_CALLS_PER_MINUTE", 0):
            result = self.classify(completion=fake)
        self.assertEqual(result["classification_status"], "rate_limited")
        fake.assert_not_called()
        result = self.classify(completion=fake, allow_remote=False)
        self.assertEqual(result["classification_status"], "disabled")
        self.assertEqual(result["question_graph"]["classification_source"], "local_structure")
        self.assertTrue(result["needs_review"])

    def test_uncertain_results_can_be_reviewed_again_without_hour_long_stale_cache(self):
        fake = transport(row([node(), node("unknown_catalog_node")]))
        first = self.classify(completion=fake)
        self.assertEqual(first["classification_status"], "partial")
        self.classify(completion=fake)
        self.assertEqual(fake.call_count, 1)
        future = time.monotonic() + service._CATALOG_UNCERTAIN_SECONDS + 1
        with patch.object(service.time, "monotonic", return_value=future):
            self.classify(completion=fake)
        self.assertEqual(fake.call_count, 2)

    def test_cache_has_byte_budget_in_addition_to_entry_count(self):
        fake = transport(row())
        with patch.object(service, "_CATALOG_CACHE_MAX_BYTES", 1):
            self.classify(completion=fake)
            self.classify(completion=fake)
        self.assertEqual(fake.call_count, 2, "oversized cache entries cannot accumulate")
        self.assertEqual(len(service._CATALOG_CACHE), 0)

    def test_malformed_payload_and_unhashable_fields_fail_safely(self):
        for index, payload in enumerate([
            {"ok": True, "content": "not json"},
            transport(row([{**node(), "evidence": [{"source": [], "quote": QUESTION}]}]))(),
            transport(row([{**node(), "usage": []}]))(),
            transport(row(identifier=True))(),
            transport(row(), row())(),
        ]):
            with self.subTest(payload=index):
                result = self.classify(question=QUESTION + str(index), completion=Mock(return_value=payload))
                self.assertNotEqual(result["classification_status"], "semantic")
                self.assertTrue(result["needs_review"])

    def test_fallback_filters_invented_or_unbound_prior_graph_records(self):
        prior = local()
        prior["question_graph"]["nodes"] = [node("invented_node"), node(quote="不在来源里")]
        result = self.classify(prior=prior, allow_remote=False)
        self.assertEqual(result["question_graph"]["nodes"], [])

    def test_local_candidates_are_hints_and_are_not_blindly_unioned_into_semantic_graph(self):
        prior = local()
        prior["question_graph"]["nodes"] = [node(), node("count_inclusion"), node("invented_node")]
        fake = transport(row([node()]))
        result = self.classify(prior=prior, completion=fake)
        sent = json.loads(fake.call_args.args[0][1]["content"])[0]
        self.assertEqual({hint["id"] for hint in sent["local_candidates"]}, {"count_perm_comb", "count_inclusion"})
        self.assertEqual([record["id"] for record in result["question_graph"]["nodes"]], ["count_perm_comb"])
        prompt = fake.call_args.args[0][0]["content"]
        self.assertIn("每个小问", prompt)
        self.assertIn("不能照抄候选或与其直接取并集", prompt)

    def test_partial_validation_issues_are_fixed_codes_without_untrusted_text(self):
        broken = node("count_inclusion")
        broken["reason"] = "!!!!"
        invalid_quote = node("count_basic", quote="raw-invalid-quote-do-not-expose")
        result = self.classify(completion=transport(row([node(), broken, invalid_quote])))
        graph = result["question_graph"]
        self.assertEqual(graph["classification_status"], "partial")
        self.assertEqual(graph["validation_issues"], {"missing_node_reason": 1, "invalid_node_evidence": 1})
        self.assertNotIn("raw-invalid-quote", json.dumps(graph["validation_issues"]))

    def test_fresh_mathematical_task_facts_supplement_omitted_semantic_nodes_without_course_edges(self):
        # The model supplies a broad counting topic but omits the actual
        # unordered-selection structure. The local caller deliberately has no
        # facts, so retaining the specific point requires fresh source analysis.
        result = self.classify(completion=transport(row([node("count_basic")])))
        records = {item["id"]: item for item in result["question_graph"]["nodes"]}
        self.assertIn("count_perm_comb", records)
        self.assertEqual(records["count_perm_comb"]["origin"], "task_structure")
        self.assertTrue(records["count_perm_comb"]["reason"])
        self.assertEqual(result["question_graph"]["edges"], [])

    def test_caller_and_model_origin_fields_cannot_forge_task_structure_facts(self):
        forged = {**node("count_inclusion"), "origin": "task_structure"}
        prior = local()
        prior["question_graph"]["nodes"] = [forged]
        result = self.classify(prior=prior, completion=transport(row([node()])))
        self.assertNotIn("count_inclusion", {item["id"] for item in result["question_graph"]["nodes"]})
        fallback = service.local_catalog_classification(prior, QUESTION)
        self.assertEqual(fallback["question_graph"]["nodes"][0]["origin"], "term_candidate")
        # A model record can still be judged semantically, but its submitted
        # origin is never promoted to a positive mathematical witness.
        model = self.classify(question=QUESTION + "。", completion=transport(row([forged])))
        records = {item["id"]: item for item in model["question_graph"]["nodes"]}
        self.assertEqual(records["count_inclusion"]["origin"], "catalog_semantic")

    def test_forbidden_method_is_not_added_by_task_fact_reconciliation(self):
        question = "不用真值表证明p∧q与q∧p等价"
        result = self.classify(question=question, completion=transport(row([
            node("logic_connectives", quote=question)])))
        records = {item["id"]: item for item in result["question_graph"]["nodes"]}
        self.assertIn("logic_equivalence", records)
        self.assertNotIn("logic_truth_table", records)

    def test_task_fact_augmentation_preserves_unknown_and_partial_review_status(self):
        unknown = self.classify(completion=transport(row([], unresolved="另一个小问条件不足")))
        self.assertIn("count_perm_comb", {item["id"] for item in unknown["question_graph"]["nodes"]})
        self.assertEqual(unknown["classification_status"], "unknown")
        self.assertTrue(unknown["needs_review"])
        partial_graph = {"version": 1, "sources": {"question": QUESTION, "solution": ""},
            "nodes": [node("count_basic")], "edges": [], "classification_status": "partial",
            "needs_review": True, "validation_issues": {"invalid_node_evidence": 1}}
        replayed = service.reconcile_catalog_graph(partial_graph, QUESTION)
        self.assertEqual(replayed["classification_status"], "partial")
        self.assertTrue(replayed["needs_review"])
        self.assertIn("count_perm_comb", replayed["task_structure_ids"])
        self.assertEqual(replayed["validation_issues"]["invalid_node_evidence"], 1)

    def test_quantified_transformation_does_not_become_propositional_argument_validity(self):
        question = "将∀x(P(x)∨∃yQ(y))改写为量词全部位于最前面的等价式，并说明自由变元条件"
        graph = self.classify(question=question, completion=transport(row([
            node("logic_reasoning", quote=question), node("predicate_prenex", quote=question)])))["question_graph"]
        ids = {item["id"] for item in graph["nodes"]}
        self.assertIn("predicate_prenex", ids)
        self.assertIn("predicate_reasoning", ids)
        self.assertNotIn("logic_reasoning", ids)
        self.assertEqual(graph["scope_exclusions"]["logic_reasoning"], "quantified_transform_without_propositional_argument")

    def test_mixed_propositional_argument_and_actual_solution_method_survive_scope_reconciliation(self):
        base = "Convert ∀x(P(x) or ∃yQ(y)) to prenex form."
        for question, solution, usage, source in [
            (base + " Then decide whether premises p→q and p entail q.", "", "assessed", "question"),
            (base + " 另判断由 S→T、S 能否推出 T。", "", "assessed", "question"),
            (base, "在实际解答中，由前提p→q和p推出结论q，再继续处理量词公式。", "used", "solution"),
        ]:
            with self.subTest(usage=usage):
                quote = question if source == "question" else solution
                graph = self.classify(question=question, solution=solution, completion=transport(row([
                    node("logic_reasoning", quote=quote, source=source, usage=usage)])))["question_graph"]
                self.assertIn("logic_reasoning", {item["id"] for item in graph["nodes"]})
                self.assertNotIn("logic_reasoning", graph.get("scope_exclusions", {}))


if __name__ == "__main__":
    unittest.main()
