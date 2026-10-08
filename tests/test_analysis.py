"""
Unit and Integration Tests for Phase 5: Repository Acquisition & Basic Analysis.
Verifies:
- File classification and programming language detection
- Safety exclusions (ignoring .git, node_modules, venv, __pycache__, dist, build)
- Static file system scanning and metric calculations
- Structured analysis result and directory tree generation
- Cache persistence and reuse
- API endpoints: /api/repositories/acquire-and-analyze, /api/repositories/analysis/cached
- UI route: GET /analysis
"""

import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app import create_app
from services.analysis_service import RepositoryAnalysisService


class AnalysisTestCase(unittest.TestCase):
    """Test suite for Phase 5 repository acquisition and static analysis."""

    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Temporary directory for mock repository testing
        self.test_dir = tempfile.mkdtemp(prefix="codelens_test_repo_")

    def tearDown(self):
        self.app_context.pop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_classify_file(self):
        """Verify file classification into source, docs, config, and language detection."""
        # Python
        cat, lang = RepositoryAnalysisService.classify_file("app.py", ".py")
        self.assertEqual(cat, "source")
        self.assertEqual(lang, "Python")

        # JavaScript & TypeScript
        cat, lang = RepositoryAnalysisService.classify_file("index.js", ".js")
        self.assertEqual(cat, "source")
        self.assertEqual(lang, "JavaScript")

        cat, lang = RepositoryAnalysisService.classify_file("app.tsx", ".tsx")
        self.assertEqual(cat, "source")
        self.assertEqual(lang, "TypeScript (React)")

        # Rust & Go
        cat, lang = RepositoryAnalysisService.classify_file("main.rs", ".rs")
        self.assertEqual(cat, "source")
        self.assertEqual(lang, "Rust")

        cat, lang = RepositoryAnalysisService.classify_file("server.go", ".go")
        self.assertEqual(cat, "source")
        self.assertEqual(lang, "Go")

        # Documentation
        cat, lang = RepositoryAnalysisService.classify_file("README.md", ".md")
        self.assertEqual(cat, "documentation")
        self.assertIsNone(lang)

        cat, lang = RepositoryAnalysisService.classify_file("LICENSE", "")
        self.assertEqual(cat, "documentation")

        # Configuration
        cat, lang = RepositoryAnalysisService.classify_file("package.json", ".json")
        self.assertEqual(cat, "configuration")

        cat, lang = RepositoryAnalysisService.classify_file("Dockerfile", "")
        self.assertEqual(cat, "configuration")

    def test_safety_ignored_directories_defined(self):
        """Verify strict safety sets ignore node_modules, .git, venv, and build directories."""
        ignored = RepositoryAnalysisService.IGNORED_DIRECTORIES
        self.assertIn(".git", ignored)
        self.assertIn("node_modules", ignored)
        self.assertIn("venv", ignored)
        self.assertIn(".venv", ignored)
        self.assertIn("__pycache__", ignored)
        self.assertIn("dist", ignored)
        self.assertIn("build", ignored)

    def test_static_scan_with_safety_exclusions(self):
        """Verify static analysis accurately counts files and strictly ignores generated directories."""
        root = Path(self.test_dir)

        # Create valid source structure
        src_dir = root / "src" / "pkg"
        src_dir.mkdir(parents=True)
        (src_dir / "main.py").write_text("print('hello')", encoding="utf-8")
        (src_dir / "utils.py").write_text("def add(a, b): return a + b", encoding="utf-8")

        # Create docs and config
        docs_dir = root / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "guide.md").write_text("# Project Guide", encoding="utf-8")
        (root / "config.json").write_text('{"version": "1.0"}', encoding="utf-8")

        # Create directories that MUST be ignored for safety
        node_dir = root / "node_modules" / "some_pkg"
        node_dir.mkdir(parents=True)
        (node_dir / "index.js").write_text("console.log('ignored');", encoding="utf-8")

        venv_dir = root / "venv" / "lib"
        venv_dir.mkdir(parents=True)
        (venv_dir / "site.py").write_text("# ignored venv file", encoding="utf-8")

        pycache_dir = src_dir / "__pycache__"
        pycache_dir.mkdir(parents=True)
        (pycache_dir / "main.cpython-311.pyc").write_bytes(b"\x00\x00")

        # Execute static scan via analyze_repository
        result = RepositoryAnalysisService.analyze_repository(
            owner="testowner",
            name="testrepo",
            repo_path=root,
            force_refresh=True,
        )

        self.assertTrue(result["success"])
        stats = result["statistics"]

        # Exactly 4 valid files: src/pkg/main.py, src/pkg/utils.py, docs/guide.md, config.json
        self.assertEqual(stats["total_files"], 4)
        self.assertEqual(stats["source_files"], 2)
        self.assertEqual(stats["doc_files"], 1)
        self.assertEqual(stats["config_files"], 1)
        self.assertEqual(stats["other_files"], 0)

        # Languages
        languages = result["languages"]
        self.assertIn("Python", languages)
        self.assertEqual(languages["Python"]["files_count"], 2)
        self.assertEqual(stats["primary_language"], "Python")

        # Directories must include 'src', 'src/pkg', 'docs', and NOT 'node_modules' or 'venv'
        dirs = result["directories"]
        self.assertIn("src", dirs)
        self.assertIn("src/pkg", dirs)
        self.assertIn("docs", dirs)
        self.assertNotIn("node_modules", dirs)
        self.assertNotIn("node_modules/some_pkg", dirs)
        self.assertNotIn("venv", dirs)

        # Directory tree root must exist
        tree = result["directory_tree"]
        self.assertEqual(tree["type"], "directory")
        self.assertEqual(tree["name"], "testrepo")

    def test_cache_persistence_and_reuse(self):
        """Verify analysis result is persisted to disk and reused when cached."""
        root = Path(self.test_dir)
        (root / "app.py").write_text("print('test')", encoding="utf-8")

        owner = "cacheowner"
        name = "cacherepo"

        # First run: analyzes and saves JSON
        res1 = RepositoryAnalysisService.analyze_repository(
            owner=owner,
            name=name,
            repo_path=root,
            force_refresh=True,
        )
        self.assertTrue(res1["success"])
        self.assertFalse(res1["is_cached"])

        # Check analysis JSON exists on disk
        analysis_path = RepositoryAnalysisService.get_analysis_file_path(owner, name)
        self.assertTrue(analysis_path.is_file())

        # Second run without force_refresh: should retrieve from cache
        res2 = RepositoryAnalysisService.analyze_repository(
            owner=owner,
            name=name,
            repo_path=root,
            force_refresh=False,
        )
        self.assertTrue(res2["success"])
        self.assertTrue(res2["is_cached"])
        self.assertEqual(res2["statistics"]["total_files"], 1)

        # Cleanup created cache file
        if analysis_path.is_file():
            analysis_path.unlink()

    def test_api_acquire_and_analyze_endpoint_invalid_input(self):
        """Test POST /api/repositories/acquire-and-analyze rejects invalid input."""
        res = self.client.post(
            "/api/repositories/acquire-and-analyze",
            json={"repo": "invalid_url"},
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])

    def test_api_cached_analyses_endpoint(self):
        """Test GET /api/repositories/analysis/cached responds with 200 and a list."""
        res = self.client.get("/api/repositories/analysis/cached")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["repositories"], list)

    def test_analysis_page_loads(self):
        """Test GET /analysis renders the Phase 5 analysis page successfully."""
        res = self.client.get("/analysis")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("Repository Acquisition & Analysis", html)
        self.assertIn("Phase 5", html)
        self.assertIn("Total Files", html)
        self.assertIn("Directory Structure & File Explorer", html)


if __name__ == "__main__":
    unittest.main()
