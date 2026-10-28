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

    def test_zoom_out_is_not_blocked_by_css_minwidth(self):
        self.assertIn("MIN_ZOOM=25,MAX_ZOOM=400", self.overlay)
        self.assertIn("Math.max(MIN_ZOOM,Math.min(MAX_ZOOM", self.overlay)
        self.assertIn("button('适应','zoom-fit',fitImage)", self.overlay)
        self.assertIn(".dge-overlay-stage{position:relative;width:100%;min-width:0;", self.style)
        self.assertNotIn("min-width:100%;margin:0 auto;background:white", self.style)


if __name__ == "__main__":
    unittest.main()
