"""
Unit and Integration Tests for Phase 2: GitHub Repository URL Input & Validation.
Covers all required test scenarios:
1. One valid URL
2. Multiple valid URLs (1-10)
3. Invalid URL (non-GitHub, malformed, subpaths, reserved words)
4. Empty URL (None, blank, empty batch)
5. Duplicate URL (exact match, case insensitivity, .git normalization)
6. More than 10 URLs (boundary enforcement)
"""

import unittest
from app import create_app
from services.github_service import GitHubService
from utils.validators import validate_github_url, validate_repository_batch


class ValidationTestCase(unittest.TestCase):
    """Test suite for URL validation logic and API endpoints."""

    def setUp(self):
        """Configure test client."""
        self.app = create_app("testing")
        self.client = self.app.test_client()

    # ==========================================================================
    # 1. ONE VALID URL
    # ==========================================================================
    def test_single_valid_url_service(self):
        """Test validator and service with a single valid GitHub URL."""
        url = "https://github.com/psf/requests"
        result = GitHubService.validate_url(url)

        self.assertTrue(result["valid"])
        self.assertIsNone(result["error"])
        self.assertIsNotNone(result["repository"])
        self.assertEqual(result["repository"]["owner"], "psf")
        self.assertEqual(result["repository"]["name"], "requests")
        self.assertEqual(result["repository"]["url"], "https://github.com/psf/requests")

    def test_single_valid_url_variations(self):
        """Test valid URL variations: trailing slash, .git suffix, www subdomain."""
        variations = [
            ("https://github.com/pallets/flask/", "pallets", "flask"),
            ("https://github.com/django/django.git", "django", "django"),
            ("http://www.github.com/tiangolo/fastapi", "tiangolo", "fastapi"),
        ]
        for url, expected_owner, expected_name in variations:
            is_valid, data, error = validate_github_url(url)
            self.assertTrue(is_valid, f"Failed on valid variation: {url}")
            self.assertIsNone(error)
            self.assertEqual(data["owner"], expected_owner)
            self.assertEqual(data["name"], expected_name)
            self.assertEqual(data["url"], f"https://github.com/{expected_owner}/{expected_name}")

    def test_single_valid_url_api(self):
        """Test POST /api/repositories/validate endpoint with valid URL."""
        response = self.client.post(
            "/api/repositories/validate",
            json={"url": "https://github.com/psf/requests"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["repository"]["owner"], "psf")
        self.assertEqual(data["repository"]["name"], "requests")
        response.close()

    # ==========================================================================
    # 2. MULTIPLE VALID URLS
    # ==========================================================================
    def test_multiple_valid_urls_service(self):
        """Test batch validation with 3 valid repository URLs."""
        urls = [
            "https://github.com/psf/requests",
            "https://github.com/django/django",
            "https://github.com/pallets/flask",
        ]
        result = GitHubService.validate_batch(urls)

        self.assertTrue(result["valid"])
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["repositories"]), 3)
        self.assertEqual(result["repositories"][0]["owner"], "psf")
        self.assertEqual(result["repositories"][1]["owner"], "django")
        self.assertEqual(result["repositories"][2]["owner"], "pallets")

    def test_multiple_valid_urls_api_validate_batch(self):
        """Test POST /api/repositories/validate-batch endpoint."""
        urls = [
            "https://github.com/psf/requests",
            "https://github.com/django/django",
        ]
        response = self.client.post(
            "/api/repositories/validate-batch",
            json={"urls": urls},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["count"], 2)
        response.close()

    def test_multiple_valid_urls_api_analyze_staging(self):
        """Test POST /api/repositories/analyze stages the repository list."""
        repos = [
            {"url": "https://github.com/psf/requests"},
            {"url": "https://github.com/django/django"},
        ]
        response = self.client.post(
            "/api/repositories/analyze",
            json={"repositories": repos},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["stage"], "staged_for_analysis")
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["repositories"]), 2)
        response.close()

    # ==========================================================================
    # 3. INVALID URL
    # ==========================================================================
    def test_invalid_urls(self):
        """Test rejection of non-GitHub, malformed, and invalid URLs."""
        invalid_cases = [
            ("https://gitlab.com/psf/requests", "not a GitHub URL"),
            ("https://bitbucket.org/owner/repo", "not a GitHub URL"),
            ("not-a-valid-url", "Invalid URL protocol"),
            ("ftp://github.com/owner/repo", "Invalid URL protocol"),
            ("https://github.com/", "missing repository path"),
            ("https://github.com/onlyowner", "missing repository name"),
            ("https://github.com/owner/repo/pull/12", "URL points to a sub-page"),
            ("https://github.com/settings/repo", "reserved GitHub system endpoint"),
        ]

        for url, expected_error_substring in invalid_cases:
            is_valid, data, error = validate_github_url(url)
            self.assertFalse(is_valid, f"Should reject invalid URL: {url}")
            self.assertIsNone(data)
            self.assertIn(
                expected_error_substring.lower(),
                error.lower(),
                f"Error message mismatch for: {url}",
            )

    def test_invalid_url_api(self):
        """Test POST /api/repositories/validate returns 400 for non-GitHub URL."""
        response = self.client.post(
            "/api/repositories/validate",
            json={"url": "https://gitlab.com/psf/requests"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["valid"])
        self.assertIn("not a GitHub URL", data["error"])
        response.close()

    # ==========================================================================
    # 4. EMPTY URL
    # ==========================================================================
    def test_empty_url_handling(self):
        """Test handling of None, empty string, and whitespace-only URLs."""
        empty_cases = [None, "", "   ", "\t\n"]

        for item in empty_cases:
            is_valid, data, error = validate_github_url(item)
            self.assertFalse(is_valid)
            self.assertIsNone(data)
            self.assertIn("cannot be empty", error.lower())

    def test_empty_url_api(self):
        """Test POST /api/repositories/validate returns 400 for empty URL."""
        response = self.client.post(
            "/api/repositories/validate",
            json={"url": ""},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["valid"])
        self.assertIn("cannot be empty", data["error"].lower())
        response.close()

    def test_empty_batch_api(self):
        """Test POST /api/repositories/validate-batch returns 400 for empty list."""
        response = self.client.post(
            "/api/repositories/validate-batch",
            json={"urls": []},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["valid"])
        self.assertIn("at least 1", data["error"].lower())
        response.close()

    # ==========================================================================
    # 5. DUPLICATE URL
    # ==========================================================================
    def test_duplicate_urls_service(self):
        """Test duplicate rejection including case-insensitivity and .git normalization."""
        # Exact duplicate
        exact_dupes = [
            "https://github.com/psf/requests",
            "https://github.com/psf/requests",
        ]
        is_valid, repos, errors = validate_repository_batch(exact_dupes)
        self.assertFalse(is_valid)
        self.assertTrue(any("duplicate" in err.lower() for err in errors))

        # Case-insensitive duplicate
        case_dupes = [
            "https://github.com/psf/requests",
            "https://github.com/PSF/Requests",
        ]
        is_valid, repos, errors = validate_repository_batch(case_dupes)
        self.assertFalse(is_valid)
        self.assertTrue(any("duplicate" in err.lower() for err in errors))

        # Normalization duplicate (.git vs no .git)
        git_dupes = [
            "https://github.com/psf/requests",
            "https://github.com/psf/requests.git/",
        ]
        is_valid, repos, errors = validate_repository_batch(git_dupes)
        self.assertFalse(is_valid)
        self.assertTrue(any("duplicate" in err.lower() for err in errors))

    def test_duplicate_urls_api(self):
        """Test POST /api/repositories/validate-batch rejects duplicates with 400."""
        response = self.client.post(
            "/api/repositories/validate-batch",
            json={
                "urls": [
                    "https://github.com/psf/requests",
                    "https://github.com/psf/requests",
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("duplicate" in err.lower() for err in data["errors"]))
        response.close()

    # ==========================================================================
    # 6. MORE THAN 10 URLS
    # ==========================================================================
    def test_more_than_10_urls_service(self):
        """Test boundary limit rejecting more than 10 URLs."""
        eleven_urls = [f"https://github.com/owner/repo{i}" for i in range(1, 12)]
        self.assertEqual(len(eleven_urls), 11)

        is_valid, repos, errors = validate_repository_batch(eleven_urls, max_limit=10)
        self.assertFalse(is_valid)
        self.assertTrue(
            any("maximum of 10" in err.lower() for err in errors),
            f"Expected max limit error, got: {errors}",
        )

    def test_exactly_10_urls_accepted(self):
        """Test boundary limit accepting exactly 10 valid URLs."""
        ten_urls = [f"https://github.com/owner{i}/repo{i}" for i in range(1, 11)]
        self.assertEqual(len(ten_urls), 10)

        is_valid, repos, errors = validate_repository_batch(ten_urls, max_limit=10)
        self.assertTrue(is_valid, f"10 URLs should be accepted, but got errors: {errors}")
        self.assertEqual(len(repos), 10)

    def test_more_than_10_urls_api(self):
        """Test POST /api/repositories/validate-batch returns 400 for 11 URLs."""
        eleven_urls = [f"https://github.com/owner/repo{i}" for i in range(1, 12)]
        response = self.client.post(
            "/api/repositories/validate-batch",
            json={"urls": eleven_urls},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["valid"])
        self.assertIn("maximum of 10", data["error"].lower())
        response.close()


if __name__ == "__main__":
    unittest.main()
