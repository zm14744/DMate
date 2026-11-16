"""Notebook analysis is bound to the selected snapshot and action cardinality."""
import copy
import json
import unittest
from unittest.mock import Mock

from concept_notebook import NotebookError, analyze_notebook, normalize_request


def note(index):
    return {"id": f"selected-{index}", "title": f"Concept {index}", "content": f"Original note {index}"}


class NotebookSelectionTests(unittest.TestCase):
    def test_explanation_requires_exactly_one_before_contacting_provider(self):
        for count in (0, 2, 12, 13):
            for language in ("zh-CN", "en"):
                with self.subTest(count=count, language=language):
                    completion = Mock(side_effect=AssertionError("The provider must not be called"))
                    with self.assertRaises(NotebookError) as error:
                        analyze_notebook({"action": "explain", "notes": [note(i) for i in range(count)],
                                          "language": language}, completion=completion)
                    self.assertEqual(error.exception.code, "single_explanation_required")
                    self.assertEqual(error.exception.status, 400)
                    self.assertEqual(error.exception.message,
                                     "Select exactly one concept note for AI explanation." if language == "en"
                                     else "AI解释需要恰好选择一条概念笔记。")
                    completion.assert_not_called()

    def test_single_explanation_uses_only_selected_source_and_preserves_digest(self):
        for language in ("zh-CN", "en"):
            with self.subTest(language=language):
                selected = note("b")
                request = {"action": "explain", "notes": [selected], "question": "Explain this one",
                           "language": language}
                original = copy.deepcopy(request)
                _, digest = normalize_request(request)
                observed = {}

                def completion(messages, **kwargs):
                    observed.update(messages=messages, **kwargs)
                    return {"ok": True, "content": json.dumps({
                        "explanations": [{"note_id": selected["id"], "explanation": "Explanation of the selected source"}],
                        "relations": [], "summary": "Selected concept explanation"})}

                result = analyze_notebook({**request, "notes_digest": digest}, completion=completion)
                self.assertEqual(request, original)
                self.assertEqual(result["action"], "explain")
                self.assertEqual(result["notes_digest"], digest)
                self.assertEqual([row["note_id"] for row in result["explanations"]], [selected["id"]])
                self.assertEqual(result["relations"], [])
                source = json.loads(observed["messages"][1]["content"])
                self.assertEqual(source["notes"], [selected])
                self.assertEqual(source["question"], request["question"])
                self.assertEqual(source["language"], language)
                self.assertIn("the single selected concept" if language == "en" else "唯一选中的这一条概念",
                              observed["messages"][0]["content"])

    def test_single_explanation_rejects_unselected_source_in_reply(self):
        response = {"explanations": [{"note_id": "unselected-open-note", "explanation": "Wrong source"}],
                    "relations": [], "summary": "Wrong source"}
        with self.assertRaises(NotebookError) as error:
            analyze_notebook({"action": "explain", "notes": [note("b")]},
                             completion=lambda *args, **kwargs: {"ok": True, "content": json.dumps(response)})
        self.assertEqual(error.exception.code, "invalid_notebook_analysis")

    def test_relationship_analysis_retains_two_to_twelve_selection_contract(self):
        for count in (2, 12):
            with self.subTest(count=count):
                records = [note(i) for i in range(count)]
                source, _ = normalize_request({"action": "relations", "notes": records})
                self.assertEqual(source["notes"], records)
        for count, code in ((0, "invalid_note_selection"), (1, "not_enough_notes"),
                            (13, "invalid_note_selection")):
            with self.subTest(count=count):
                completion = Mock(side_effect=AssertionError("The provider must not be called"))
                with self.assertRaises(NotebookError) as error:
                    analyze_notebook({"action": "relations", "notes": [note(i) for i in range(count)]},
                                     completion=completion)
                self.assertEqual(error.exception.code, code)
                completion.assert_not_called()


if __name__ == "__main__":
    unittest.main()
