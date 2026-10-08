import unittest
from app import create_app


class BasicAppTestCase(unittest.TestCase):
    """Test suite for Phase 1 of CodeLens AI."""

    def setUp(self):
        """Configure test client before each test."""
        self.app = create_app("testing")
        self.client = self.app.test_client()

    def test_health_endpoint(self):
        """Verify the healthcheck endpoint responds with status 200."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data.get("status"), "online")
        self.assertEqual(json_data.get("project"), "CodeLens AI")

    def test_home_page_loads(self):
        """Verify home page loads successfully with 200 and required content."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Verify title and subtitle
        self.assertIn("CodeLens AI", html)
        self.assertIn("AI-Powered Multi-Agent System for Open Source Project Analysis", html)

        # Verify description
        self.assertIn(
            "CodeLens AI helps developers understand unfamiliar GitHub repositories",
            html,
        )

        # Verify Section 1: GitHub Repository URL
        self.assertIn("GitHub Repository URL", html)
        self.assertIn("repo-url", html)

        # Verify Section 2: Keyword Repository Search
        self.assertTrue("Search GitHub Repositories" in html or "Keyword Repository Search" in html)
        self.assertTrue("keyword-input" in html or "search-query" in html)

    def test_static_css_loads(self):
        """Verify the stylesheet is served properly."""
        response = self.client.get("/static/css/style.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.content_type)
        self.assertIn("CodeLens AI", response.get_data(as_text=True))
        response.close()

    def test_static_js_loads(self):
        """Verify the JavaScript file is served properly."""
        response = self.client.get("/static/js/main.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("CodeLens AI", response.get_data(as_text=True))
        response.close()

    def test_404_handler(self):
        """Verify a non-existent route returns 404 cleanly."""
        response = self.client.get("/non-existent-route-xyz")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
