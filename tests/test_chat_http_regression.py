"""Real Flask HTTP regression for university chat outage (no external LLM).

A previous code change accessed current_user_content before initializing it
whenever normal clients omitted question_context. Python py_compile succeeded,
but every ordinary POST /chat returned default HTML HTTP500.

This test exercises the *real* Flask view with a stubbed model answer.
"""
import unittest
from unittest.mock import patch


class LiveFlaskChatRegressionTests(unittest.TestCase):
    def setUp(self):
        import app
        self.server=app
        self.client=app.app.test_client()

    def _post(self,text,kind=None):
        payload={"messages":[{"role":"user","content":text}]}
        if kind: payload["request_kind"]=kind
        with patch.object(self.server,"_check_rate_limit",return_value=True), \
             patch.object(self.server,"ask_ai",return_value={
                "ok":True,"reply":"这两式逻辑等价，因为蕴含可转换为析取。"
             }):
            return self.client.post("/chat",json=payload)

    def test_ordinary_math_without_question_context_is_not_http500(self):
        response=self._post("请直接给出最终答案并简要解释。命题 (p→q) 与 (¬p∨q) 是否逻辑等价？")
        self.assertNotEqual(response.status_code,500,response.get_data(as_text=True)[:800])
        self.assertTrue(response.is_json,response.get_data(as_text=True)[:800])
        self.assertEqual(response.status_code,200,response.get_json())

    def test_ordinary_graph_question_without_pinned_metadata(self):
        response=self._post("请直接给出答案。路径P5有多少条边？")
        self.assertNotEqual(response.status_code,500,response.get_data(as_text=True)[:800])
        self.assertTrue(response.is_json)

if __name__=="__main__":
    unittest.main()
