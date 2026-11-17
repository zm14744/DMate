"""Inspect an actual Docker COPY without downloading dependencies or models."""
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("docker"), "Docker is required to inspect the production build context")
class DockerContextTest(unittest.TestCase):
    def test_web_runtime_is_complete_without_native_or_authoring_trees(self):
        tag = "dmate-context-test:" + uuid.uuid4().hex
        container = None
        try:
            with tempfile.TemporaryDirectory(prefix="dmate-context-") as directory:
                recipe = Path(directory) / "Dockerfile"
                recipe.write_text("FROM scratch\nCOPY . /app/\n", encoding="utf-8")
                subprocess.run(["docker", "build", "--network=none", "--file", str(recipe),
                                "--tag", tag, str(ROOT)], check=True, capture_output=True, text=True)
                container = subprocess.check_output(["docker", "create", tag, "/unused"], text=True).strip()
                archive = Path(directory) / "context.tar"
                subprocess.run(["docker", "export", "--output", str(archive), container], check=True)
                with tarfile.open(archive) as exported:
                    files = {item.name.removeprefix("./") for item in exported if item.isfile()}
                required = {
                    "app/app.py", "app/requirements.txt", "app/requirements-agents.txt",
                    "app/knowledge_graph.json", "app/templates/index.html", "app/templates/_favicon_links.html",
                    "app/static/script.js", "app/static/offline.html", "app/static/offline-service-worker.js",
                    "app/static/offline-content/concepts.zh-CN.json", "app/static/offline-content/questions.zh-CN.json",
                    "app/static/icons/dmate-brand-v52.svg", "app/static/icons/dmate-app-v52.ico",
                    "app/scripts/generate_icons.py", "app/scripts/prepare_ocr_model_cache.py",
                    "app/scripts/ocr-model-lock.json",
                }
                required.update("app/" + path.name for path in ROOT.glob("*.py"))
                self.assertFalse(required - files, "Runtime files missing from image: " + str(required - files))
                forbidden = ("app/android/", "app/desktop/", "app/browser-extension/", "app/offline-content/",
                             "app/.git/", "app/.github/", "app/.venv/", "app/node_modules/", "app/scripts/native/")
                self.assertFalse({name for name in files if name.startswith(forbidden)})
                self.assertNotIn("app/.env", files)
                self.assertFalse({name for name in files if name.startswith("app/scripts/test_")})
        finally:
            if container:
                subprocess.run(["docker", "rm", "--force", container], check=False, capture_output=True)
            subprocess.run(["docker", "image", "rm", "--force", tag], check=False, capture_output=True)


if __name__ == "__main__":
    unittest.main()
