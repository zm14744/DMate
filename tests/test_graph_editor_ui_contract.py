"""Cheap source contracts for OCR graph editor's actual controls and behavior."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GraphEditorUiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.editor = (ROOT / "static/graph-editor.js").read_text()
        cls.overlay = (ROOT / "static/graph-editor-overlay.js").read_text()
        cls.style = (ROOT / "static/graph-editor.css").read_text()
        cls.page = (ROOT / "templates/index.html").read_text()
        cls.client = (ROOT / "static/script.js").read_text()

    def test_question_selector_survives_edit_and_reaches_ocr_message(self):
        self.assertIn("row.setAttribute('role', 'radiogroup')", self.editor)
        self.assertIn("row.setAttribute('aria-label', '识别内容是否为题目')", self.editor)
        self.assertIn("let isQuestion = options.isQuestion !== false", self.editor)
        self.assertIn("options.onQuestionChange?.(isQuestion)", self.editor)
        self.assertIn("options.onConfirm(model.getDocument(), isQuestion)", self.editor)
        self.assertIn("isQuestion: task.isQuestion !== false", self.client)
        self.assertIn("ocrIsQuestion: task.isQuestion !== false", self.client)
        self.assertIn("onQuestionChange: flag => { task.isQuestion = flag; }", self.client)
        self.assertIn("isQuestion: true", self.client)

    def test_close_red_dot_and_only_bottom_right_save(self):
        self.assertNotIn("button('稍后继续'", self.editor)
        self.assertIn("button(saving ? '正在保存…' : '保存并确认'", self.editor)
        self.assertIn(".dge-footer { position:static", self.style)
        self.assertIn("border:0; background:transparent; box-shadow:none;", self.style)
        self.assertNotIn(".dge-footer { bottom:-1px;", self.style)
        self.assertIn('class="graph-editor-close-dot"', self.page)
        self.assertIn('aria-label="关闭图形识别编辑器"', self.page)
        self.assertIn('closeButton.addEventListener("click", requestClose)', self.client)
        self.assertIn("if (task.confirming) event.preventDefault()", self.client)

    def test_editor_does_not_show_unreadable_ocr_input_lock_hint(self):
        self.assertNotIn("正在核对图片，保存或关闭编辑器后可继续输入", self.client)
        self.assertNotIn("正在核对图片…", self.client)
        self.assertIn("if (!ocrReviewInProgress && typingNow)", self.client)
        self.assertIn("else if (!ocrReviewInProgress && waitingReply)", self.client)
        # Modal input blocking still works, without the extra blue text row.
        self.assertIn("input.disabled = hardBlocked || ocrReviewInProgress", self.client)
        self.assertIn('inputLockHint.classList.toggle("hidden", !statusText)', self.client)

    def test_auto_graph_request_has_no_manual_global_direction_or_weight(self):
        self.assertNotIn("const dir=select(", self.overlay)
        self.assertNotIn("图形方向", self.overlay)
        self.assertNotIn("图形权值", self.overlay)
        self.assertNotIn("无向图", self.overlay)
        self.assertNotIn("无权图", self.overlay)
        self.assertNotIn("dir.value=", self.overlay)
        self.assertNotIn("weight.value=", self.overlay)
        self.assertIn('formData.append("workflow", "auto_graph")', self.client)
        self.assertNotIn('formData.append("workflow", "manual_graph")', self.client)
        server = (ROOT / "app.py").read_text()
        self.assertIn('request.form.get("workflow") == "auto_graph"', server)
        self.assertIn('pipeline=active_pipeline()', server)

    def test_zoom_out_is_not_blocked_by_css_minwidth(self):
        self.assertIn("MIN_ZOOM=25,MAX_ZOOM=400", self.overlay)
        self.assertIn("Math.max(MIN_ZOOM,Math.min(MAX_ZOOM", self.overlay)
        self.assertIn("button('适应','zoom-fit',fitImage)", self.overlay)
        self.assertIn(".dge-overlay-stage{position:relative;width:100%;min-width:0;", self.style)
        self.assertNotIn("min-width:100%;margin:0 auto;background:white", self.style)


if __name__ == "__main__":
    unittest.main()
