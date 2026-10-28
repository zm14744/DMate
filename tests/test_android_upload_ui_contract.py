"""Fast, dependency-free checks for APK image picker and OCR task UI."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AndroidUploadUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.java = (ROOT / "android/app/src/main/java/app/dmate/client/MainActivity.java").read_text()
        cls.html = (ROOT / "templates/index.html").read_text()
        cls.js = (ROOT / "static/script.js").read_text()

    def test_native_documents_fallback_and_webview_callback(self):
        self.assertIn("Intent.ACTION_OPEN_DOCUMENT", self.java)
        self.assertIn("Intent.ACTION_GET_CONTENT", self.java)
        self.assertIn('Intent.createChooser(intent, "选择图片")', self.java)
        self.assertIn("SystemClock.elapsedRealtime() - filePickerLaunchedAt < 450", self.java)
        self.assertIn("launchImagePicker(true)", self.java)
        self.assertIn("Intent.EXTRA_ALLOW_MULTIPLE", self.java)
        self.assertIn("callback.onReceiveValue(result)", self.java)
        manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text()
        self.assertNotIn("NativeUpdateManager", self.java)
        self.assertNotIn('REQUEST_INSTALL_PACKAGES', manifest)
        self.assertNotIn('FileProvider', manifest)
        self.assertFalse((ROOT / "android/app/src/main/java/app/dmate/client/NativeUpdateManager.java").exists())
        self.assertNotIn("FileChooserParams.parseResult(resultCode, data)", self.java)
        self.assertIn("filePathCallback.onReceiveValue(null)", self.java)

    def test_file_input_and_independent_question_selector(self):
        self.assertIn("input.showPicker()", self.js)
        self.assertIn('id="imagePickerWrap"', self.html)
        self.assertIn("pointer-events:auto !important", self.html)
        self.assertIn('imagePickerWrap.hidden = visibleMode !== "idle"', self.js)
        self.assertIn("manualQuestion.hidden = hasImages", self.js)
        self.assertIn("composerWrap.hidden = hasImages", self.js)
        self.assertIn('id="ocrUploadStage"', self.html)
        self.assertIn('id="ocrUploadActions"', self.html)
        self.assertIn("uploadActions.appendChild(picker)", self.js)
        self.assertIn("normalComposer.insertBefore(picker", self.js)
        self.assertIn('<h2 id="ocrTaskTitle">图片</h2>', self.html)
        self.assertIn('>上传图片</button>', self.html)
        self.assertEqual(self.html.count('id="imageInput"'), 1)
        self.assertIn('<input id="imageInput" type="file" accept="image/*" multiple tabindex="-1" aria-label="选择图片">', self.html)
        self.assertIn('<p class="ocr-task-panel-hint">最多4张</p>', self.html)

    def test_no_visible_ocr_task_count_or_timing(self):
        self.assertNotIn('id="ocrTaskCount"', self.html)
        self.assertNotIn('ocr-task-time', self.html)
        self.assertNotIn('ocrTaskCount', self.js)
        self.assertNotIn('ocr-task-time', self.js)
        self.assertIn('ocr-task-panel-hint">最多4张', self.html)

    def test_existing_client_web_features_do_not_force_an_apk(self):
        workflow = (ROOT / ".github/workflows/build-android-release.yml").read_text()
        update_manifest = (ROOT / "static/client-updates.json").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("gh release upload", workflow)
        self.assertNotIn("    branches: [main]", workflow)
        self.assertIn('"published": false', update_manifest)
        self.assertIn('GitCode · " + displayName', self.js)
        self.assertIn('GitHub · " + displayName', self.js)
        self.assertIn('text:"选择 APK 下载源"', self.js)
        self.assertNotIn('GitHub · APK（新版）', self.js)
        self.assertNotIn('GitCode · APK（请核对版本）', self.js)
        self.assertNotIn('/static/client-update.js?v=', self.html)
        self.assertIn('imageInput.multiple = false;', self.js)
        self.assertIn('DMateAndroid\\/1\\.0\\.[0-4]', self.js)
        self.assertIn('imageInput.addEventListener("input", handleImageSelected)', self.js)

    def test_solid_selection_and_compact_red_remove(self):
        self.assertIn(".ocr-question-choice input[type=\"radio\"]:checked", self.html)
        self.assertIn("ocr-task-remove", self.html)
        self.assertIn("remove.dataset.ocrAction", self.js)
        self.assertNotIn('button("移除", "remove")', self.js)


if __name__ == "__main__":
    unittest.main()
