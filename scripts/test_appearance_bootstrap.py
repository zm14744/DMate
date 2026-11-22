"""The first-paint appearance hint belongs only to the verified current user."""
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AppearanceBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No network")):
            cls.runtime = importlib.import_module("app")

    def render_home(self, user=None, error=None):
        with patch.object(self.runtime, "_current_auth_user", return_value=user, side_effect=error):
            response = self.runtime.app.test_client().get("/")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        return response.get_data(as_text=True)

    def test_only_verified_username_is_exposed_and_html_escaped(self):
        html = self.render_home({"username": '甲"<appearance>', "email": "private-owner-817@example.test"})
        self.assertIn('data-owner="甲&#34;&lt;appearance&gt;"', html)
        self.assertNotIn("private-owner-817@example.test", html)
        self.assertLess(html.index('id="dmateAppearanceBootstrap"'),
                        html.index('<link rel="stylesheet" href="/static/dmate-main.css?'))

    def test_logged_out_page_has_no_account_hint(self):
        self.assertIn('data-scope="online" data-owner=""', self.render_home())

    def test_unavailable_auth_does_not_expose_an_unverified_owner(self):
        html = self.render_home(error=self.runtime.AuthBackendUnavailable())
        self.assertIn('data-scope="online" data-owner=""', html)


if __name__ == "__main__":
    unittest.main()
