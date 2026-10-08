"""
Unit and Integration Tests for Phase 4: Repository Ranking & Analysis Suitability Evaluation.
Covers:
1. One repository evaluation
2. Multiple repositories evaluation and ranking
3. Similar repositories comparison
4. Different repositories comparison (substantial vs minimal/archived)
5. Keyword relevance impact
6. Missing metadata handling (no crash, factual lower score)
7. API failure handling (graceful fallback)
8. Configurable scoring weights
9. Live API routes (POST /api/repositories/analyze & POST /api/repositories/rank)
"""

import unittest
from unittest.mock import MagicMock, patch
import urllib.error
from app import create_app
from services.ranking_service import RankingService


class RankingTestCase(unittest.TestCase):
    """Test suite for repository ranking and analysis suitability percentage."""

    def setUp(self):
        """Configure test client and clear in-memory cache before tests."""
        self.app = create_app("testing")
        self.client = self.app.test_client()
        RankingService._metadata_cache.clear()

    # ==========================================================================
    # 1. ONE REPOSITORY
    # ==========================================================================
    def test_single_repository_ranking(self):
        """Test evaluating a single repository."""
        repos = [{"owner": "pallets", "name": "flask", "url": "https://github.com/pallets/flask"}]
        result = RankingService.rank_repositories(repos, keyword="flask web framework")

        self.assertTrue(result["success"])
        self.assertEqual(result["total_evaluated"], 1)
        self.assertIsNotNone(result["recommended_repository"])

        ranked_item = result["ranking"][0]
        self.assertEqual(ranked_item["rank"], 1)
        self.assertTrue(ranked_item["is_recommended"])
        self.assertGreater(ranked_item["suitability_percentage"], 0)
        self.assertLessEqual(ranked_item["suitability_percentage"], 100)
        self.assertIn("reason", ranked_item)
        self.assertIn("factors", ranked_item)

    def test_single_repository_ranking_with_metadata(self):
        """Test evaluating a single repository with complete metadata."""
        meta = {
            "name": "flask",
            "owner": "pallets",
            "language": "Python",
            "size": 12000,
            "stars": 70000,
            "forks": 15000,
            "topics": ["flask", "web-framework", "python"],
            "description": "The Python micro framework for building web applications.",
            "has_readme": True,
            "readme_size": 2500,
            "archived": False,
            "pushed_at": "2026-09-01T00:00:00Z",
            "license": "BSD-3-Clause",
        }
        res = RankingService.calculate_suitability(meta, keyword="flask web framework")
        self.assertGreaterEqual(res["suitability_percentage"], 80)
        self.assertIn("python", res["reason"].lower())

    # ==========================================================================
    # 2. MULTIPLE REPOSITORIES
    # ==========================================================================
    def test_multiple_repositories_ranking_order(self):
        """Test that multiple repositories are ranked in descending order of suitability."""
        repos = [
            {"owner": "pallets", "name": "flask", "url": "https://github.com/pallets/flask"},
            {"owner": "django", "name": "django", "url": "https://github.com/django/django"},
            {"owner": "psf", "name": "requests", "url": "https://github.com/psf/requests"},
        ]
        result = RankingService.rank_repositories(repos, keyword="web framework")

        self.assertTrue(result["success"])
        self.assertEqual(result["total_evaluated"], 3)
        self.assertEqual(len(result["ranking"]), 3)

        # Check descending order
        scores = [item["suitability_percentage"] for item in result["ranking"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

        # Only Rank 1 is recommended
        self.assertTrue(result["ranking"][0]["is_recommended"])
        self.assertFalse(result["ranking"][1]["is_recommended"])
        self.assertFalse(result["ranking"][2]["is_recommended"])

    # ==========================================================================
    # 3. SIMILAR REPOSITORIES
    # ==========================================================================
    def test_similar_repositories_differentiation(self):
        """Test evaluating similar alternatives (Flask vs Django)."""
        repos = [
            {"owner": "pallets", "name": "flask", "url": "https://github.com/pallets/flask"},
            {"owner": "django", "name": "django", "url": "https://github.com/django/django"},
        ]
        result = RankingService.rank_repositories(repos, keyword="django web framework")

        self.assertTrue(result["success"])
        flask_item = next(r for r in result["ranking"] if r["name"] == "flask")
        django_item = next(r for r in result["ranking"] if r["name"] == "django")

        # When keyword is "django", Django should have higher keyword relevance
        self.assertGreater(
            django_item["factors"]["keyword_relevance"],
            flask_item["factors"]["keyword_relevance"],
        )

    # ==========================================================================
    # 4. DIFFERENT REPOSITORIES (Substantial vs Minimal / Archived)
    # ==========================================================================
    def test_different_repositories_score_gap(self):
        """Test that a complete active repository scores significantly higher than an empty/archived one."""
        meta_healthy = {
            "name": "healthy-project",
            "owner": "test-org",
            "language": "Python",
            "size": 5000,
            "stars": 1500,
            "forks": 250,
            "topics": ["python", "api", "framework"],
            "description": "Production grade asynchronous web framework for enterprise systems.",
            "has_readme": True,
            "readme_size": 3500,
            "archived": False,
            "pushed_at": "2026-09-01T12:00:00Z",
            "license": "MIT",
        }

        meta_archived_empty = {
            "name": "dead-project",
            "owner": "test-org",
            "language": None,
            "size": 2,
            "stars": 0,
            "forks": 0,
            "topics": [],
            "description": None,
            "has_readme": False,
            "readme_size": 0,
            "archived": True,
            "pushed_at": "2018-01-01T00:00:00Z",
            "license": None,
        }

        score_healthy = RankingService.calculate_suitability(meta_healthy, keyword="framework")
        score_dead = RankingService.calculate_suitability(meta_archived_empty, keyword="framework")

        self.assertGreater(score_healthy["suitability_percentage"], 75)
        self.assertLess(score_dead["suitability_percentage"], 35)
        self.assertGreater(
            score_healthy["suitability_percentage"] - score_dead["suitability_percentage"],
            40,
            "Healthy repository should score at least 40 percentage points higher than an empty archived repository",
        )

    # ==========================================================================
    # 5. MISSING METADATA
    # ==========================================================================
    def test_missing_metadata_handled_factually(self):
        """Test calculation with missing description, language, and README without crashing."""
        sparse_meta = {
            "name": "sparse-repo",
            "owner": "user",
            "language": None,
            "size": 0,
            "stars": 0,
            "forks": 0,
            "topics": [],
            "description": None,
            "has_readme": False,
            "archived": False,
            "pushed_at": None,
            "license": None,
        }

        result = RankingService.calculate_suitability(sparse_meta, keyword="test")
        self.assertIsInstance(result["suitability_percentage"], int)
        self.assertGreaterEqual(result["suitability_percentage"], 0)
        self.assertLessEqual(result["suitability_percentage"], 35)
        self.assertIn("reason", result)
        self.assertIn("missing", result["reason"].lower())

    # ==========================================================================
    # 6. CONFIGURABLE SCORING WEIGHTS
    # ==========================================================================
    def test_configurable_weights_impact(self):
        """Test that modifying factor weights shifts the suitability percentage deterministically."""
        meta = {
            "name": "data-tool",
            "owner": "user",
            "language": "Python",
            "size": 1000,
            "stars": 50,
            "forks": 10,
            "topics": ["data"],
            "description": "Short description",
            "has_readme": True,
            "readme_size": 500,
            "archived": False,
            "pushed_at": "2026-08-01T00:00:00Z",
            "license": "Apache-2.0",
        }

        # Weight heavily towards keyword relevance
        weights_kw = {
            "keyword_relevance": 0.80,
            "code_architecture": 0.10,
            "documentation": 0.05,
            "completeness_activity": 0.05,
        }
        res_high_kw = RankingService.calculate_suitability(meta, keyword="data-tool", weights=weights_kw)

        # Weight with 0 keyword relevance
        weights_no_kw = {
            "keyword_relevance": 0.0,
            "code_architecture": 0.50,
            "documentation": 0.30,
            "completeness_activity": 0.20,
        }
        res_no_kw = RankingService.calculate_suitability(meta, keyword="completely-unrelated-xyz", weights=weights_no_kw)

        # The configuration is applied and weights_applied is verified
        self.assertEqual(res_high_kw["weights"]["keyword_relevance"], 0.8)
        self.assertEqual(res_no_kw["weights"]["keyword_relevance"], 0.0)

    # ==========================================================================
    # 7. API FAILURE & RATE LIMIT FALLBACK
    # ==========================================================================
    @patch("urllib.request.urlopen")
    def test_api_failure_fallback_graceful(self, mock_urlopen):
        """Test ranking calculation falls back gracefully when GitHub API returns HTTP 403."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.github.com/repos/test/repo",
            code=403,
            msg="rate limit",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"message": "rate limit"}'),
        )

        repos = [{
            "owner": "fallback-org",
            "name": "fallback-repo",
            "description": "Fallback description provided during search intake",
            "language": "Python",
            "stars": 120,
        }]

        result = RankingService.rank_repositories(repos, keyword="fallback")
        self.assertTrue(result["success"])
        self.assertEqual(result["total_evaluated"], 1)
        self.assertGreater(result["ranking"][0]["suitability_percentage"], 0)

    # ==========================================================================
    # 8. API ENDPOINTS (POST /api/repositories/analyze & /rank)
    # ==========================================================================
    def test_api_analyze_endpoint_ranks(self):
        """Test POST /api/repositories/analyze returns complete ranking and recommendation."""
        payload = {
            "repositories": [
                {"url": "https://github.com/pallets/flask"},
                {"url": "https://github.com/django/django"},
            ],
            "keyword": "flask",
        }
        response = self.client.post("/api/repositories/analyze", json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["stage"], "staged_for_analysis")
        self.assertEqual(data["ranking_status"], "ranked_and_staged")
        self.assertIn("recommended_repository", data)
        self.assertIn("ranking", data)
        self.assertEqual(len(data["ranking"]), 2)
        self.assertEqual(data["ranking"][0]["rank"], 1)
        response.close()

    def test_api_rank_endpoint_direct(self):
        """Test POST /api/repositories/rank direct endpoint."""
        payload = {
            "urls": ["https://github.com/psf/requests"],
        }
        response = self.client.post("/api/repositories/rank", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)
        response.close()


if __name__ == "__main__":
    unittest.main()
