"""
Unit and Integration Tests for Phase 3: Keyword-Based GitHub Repository Discovery.
Covers:
1. Keyword search with "Python", "Machine Learning", "Django"
2. Empty keyword rejection
3. No search results handling
4. Invalid token handling (HTTP 401)
5. GitHub API failures (HTTP 403 Rate Limit, 500)
6. Network failure handling (URLError / Connection error)
7. API endpoints (GET and POST /api/repositories/search)
"""

import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
from app import create_app
from services.github_service import GitHubService


class SearchTestCase(unittest.TestCase):
    """Test suite for GitHub repository keyword discovery."""

    def setUp(self):
        """Configure test client."""
        self.app = create_app("testing")
        self.client = self.app.test_client()

    # ==========================================================================
    # 1. TEST KEYWORDS: Python, Machine Learning, Django
    # ==========================================================================
    def test_search_python_keyword(self):
        """Test search service with keyword 'Python'."""
        result = GitHubService.search_repositories("Python", per_page=5)
        if not result["success"] and result.get("status_code") == 403:
            self.assertIn("rate limit", result["error"].lower())
            return

        self.assertTrue(result["success"])
        self.assertGreater(result["count"], 0)
        self.assertGreater(result["total_count"], 0)

        first_repo = result["repositories"][0]
        self.assertIn("name", first_repo)
        self.assertIn("owner", first_repo)
        self.assertIn("url", first_repo)
        self.assertIn("description", first_repo)
        self.assertIn("language", first_repo)
        self.assertIn("stars", first_repo)
        self.assertIn("topics", first_repo)
        self.assertIn("fork_status", first_repo)
        self.assertTrue(first_repo["url"].startswith("https://github.com/"))

    def test_search_machine_learning_keyword(self):
        """Test search service with keyword 'Machine Learning'."""
        result = GitHubService.search_repositories("Machine Learning", per_page=3)
        if not result["success"] and result.get("status_code") == 403:
            self.assertIn("rate limit", result["error"].lower())
            return

        self.assertTrue(result["success"])
        self.assertGreater(result["count"], 0)
        self.assertEqual(len(result["repositories"]), 3)

    def test_search_django_keyword(self):
        """Test search service with keyword 'Django'."""
        result = GitHubService.search_repositories("Django", per_page=3)
        if not result["success"] and result.get("status_code") == 403:
            self.assertIn("rate limit", result["error"].lower())
            return

        self.assertTrue(result["success"])
        self.assertGreater(result["count"], 0)

    # ==========================================================================
    # 2. EMPTY KEYWORD
    # ==========================================================================
    def test_empty_keyword_service(self):
        """Test service rejection of empty, whitespace, and None keywords."""
        empty_cases = [None, "", "   ", "\t\n"]
        for empty_kw in empty_cases:
            result = GitHubService.search_repositories(empty_kw)
            self.assertFalse(result["success"])
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["status_code"], 400)
            self.assertIn("cannot be empty", result["error"].lower())

    def test_empty_keyword_api(self):
        """Test POST /api/repositories/search returns 400 for empty keyword."""
        response = self.client.post(
            "/api/repositories/search",
            json={"q": ""},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("cannot be empty", data["error"].lower())
        response.close()

    # ==========================================================================
    # 3. NO SEARCH RESULTS
    # ==========================================================================
    def test_no_search_results(self):
        """Test handling when query yields 0 results."""
        obscure_query = "xyzabc123nonexistentrepository9876543210qwerty"
        result = GitHubService.search_repositories(obscure_query)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(len(result["repositories"]), 0)
        self.assertIn("no public repositories found", result["message"].lower())

    # ==========================================================================
    # 4. INVALID TOKEN (HTTP 401)
    # ==========================================================================
    def test_invalid_token_handling(self):
        """Test handling of invalid GITHUB_TOKEN triggering HTTP 401."""
        invalid_token = "ghp_invalid_token_1234567890abcdef"
        result = GitHubService.search_repositories("Python", per_page=1, token=invalid_token)
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 401)
        self.assertIn("bad credentials", result["error"].lower())
        self.assertIn("github_token", result["error"].lower())

    # ==========================================================================
    # 5. GITHUB API FAILURE (Mocked 403 Rate Limit and 500 Server Error)
    # ==========================================================================
    @patch("urllib.request.urlopen")
    def test_api_rate_limit_403(self, mock_urlopen):
        """Test graceful handling of GitHub API HTTP 403 rate limit."""
        error_response = json.dumps({"message": "API rate limit exceeded"}).encode("utf-8")
        mock_err = urllib.error.HTTPError(
            url="https://api.github.com/search/repositories",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=MagicMock(read=lambda: error_response),
        )
        mock_urlopen.side_effect = mock_err

        result = GitHubService.search_repositories("Python")
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 403)
        self.assertIn("rate limit exceeded", result["error"].lower())

    @patch("urllib.request.urlopen")
    def test_api_server_error_500(self, mock_urlopen):
        """Test graceful handling of GitHub API internal 500 error."""
        error_response = json.dumps({"message": "Internal Server Error"}).encode("utf-8")
        mock_err = urllib.error.HTTPError(
            url="https://api.github.com/search/repositories",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=MagicMock(read=lambda: error_response),
        )
        mock_urlopen.side_effect = mock_err

        result = GitHubService.search_repositories("Python")
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 500)
        self.assertIn("500", result["error"])

    # ==========================================================================
    # 6. NETWORK FAILURE
    # ==========================================================================
    @patch("urllib.request.urlopen")
    def test_network_failure(self, mock_urlopen):
        """Test graceful handling of network disconnection / DNS failure."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused / Name resolution failed")

        result = GitHubService.search_repositories("Python")
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 503)
        self.assertIn("network error", result["error"].lower())
        self.assertIn("internet connection", result["error"].lower())

    # ==========================================================================
    # 7. API ENDPOINTS (GET and POST /api/repositories/search)
    # ==========================================================================
    def test_api_search_get(self):
        """Test GET /api/repositories/search?q=Django."""
        response = self.client.get("/api/repositories/search?q=Django&per_page=2")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertGreater(len(data["repositories"]), 0)
        response.close()

    def test_api_search_post(self):
        """Test POST /api/repositories/search with JSON body."""
        response = self.client.post(
            "/api/repositories/search",
            json={"q": "Flask", "per_page": 2},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["keyword"], "Flask")
        self.assertGreater(len(data["repositories"]), 0)
        response.close()


if __name__ == "__main__":
    unittest.main()
