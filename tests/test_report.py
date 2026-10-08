"""
Unit and integration tests for AI Project Report Generator.
Verifies deterministic 22-section generation, factual data preservation,
HTML & Markdown rendering, and download API endpoints.
"""

import json
from pathlib import Path
import unittest

from app import create_app
from models.knowledge import (
    ClassInfo,
    DependencyInfo,
    DirectoryInfo,
    EntryPointInfo,
    FileInfo,
    FunctionInfo,
    ImportInfo,
    MethodInfo,
    RelationshipInfo,
    RepositoryInfo,
    SharedRepositoryKnowledge,
)
from services.knowledge_service import KnowledgeService
from services.report_service import ReportService


class ReportTestCase(unittest.TestCase):
    """Test suite for deterministic AI Project Report Generator."""

    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()

        # Build mock repository knowledge
        self.mock_repo = RepositoryInfo(
            name="reporttest",
            owner="testowner",
            url="https://github.com/testowner/reporttest",
            description="Test repository for report generator verification",
            primary_language="Python",
        )

        self.mock_knowledge = SharedRepositoryKnowledge(
            repository=self.mock_repo,
            directories=[
                DirectoryInfo(path="src", name="src"),
                DirectoryInfo(path="src/api", name="api", parent="src"),
                DirectoryInfo(path="tests", name="tests"),
            ],
            files=[
                FileInfo(path="main.py", name="main.py", extension=".py", language="Python", size=2048),
                FileInfo(path="src/api/routes.py", name="routes.py", extension=".py", language="Python", size=4096),
                FileInfo(path="tests/test_app.py", name="test_app.py", extension=".py", language="Python", size=1024),
            ],
            classes=[
                ClassInfo(
                    name="AppServer",
                    file="main.py",
                    base_classes=["BaseServer"],
                    methods=["start", "stop"],
                    methods_count=2,
                    docstring="Core HTTP application server.",
                ),
            ],
            functions=[
                FunctionInfo(
                    name="init_app",
                    file="main.py",
                    parameters=["config_path"],
                    docstring="Initialize application context.",
                ),
                FunctionInfo(
                    name="handle_request",
                    file="src/api/routes.py",
                    parameters=["req"],
                    docstring="Dispatch incoming HTTP request.",
                ),
            ],
            methods=[
                MethodInfo(name="start", class_name="AppServer", file="main.py", parameters=["self", "port"]),
                MethodInfo(name="stop", class_name="AppServer", file="main.py", parameters=["self"]),
            ],
            imports=[
                ImportInfo(source_file="main.py", imported_module="src.api.routes", imported_symbol="handle_request"),
                ImportInfo(source_file="main.py", imported_module="sys", is_standard_library=True),
                ImportInfo(source_file="src/api/routes.py", imported_module="flask", is_external=True),
            ],
            dependencies=[
                DependencyInfo(name="flask", type="external_package", occurrences=1, files=["src/api/routes.py"]),
                DependencyInfo(name="sys", type="standard_library", occurrences=1, files=["main.py"]),
            ],
            entry_points=[
                EntryPointInfo(file="main.py", symbol="__main__", detection_reason="main_block", line=45),
            ],
            relationships=[
                RelationshipInfo(source="repo:testowner/reporttest", relation="CONTAINS", target="dir:src"),
                RelationshipInfo(source="file:main.py", relation="DEFINES", target="class:main.py:AppServer"),
                RelationshipInfo(source="class:main.py:AppServer", relation="CONTAINS", target="method:main.py:AppServer.start"),
                RelationshipInfo(source="file:main.py", relation="IMPORTS", target="file:src/api/routes.py"),
            ],
            statistics={
                "total_files": 3,
                "total_directories": 3,
            },
        )

        KnowledgeService.save_knowledge("testowner", "reporttest", self.mock_knowledge)

    def test_report_generation_has_all_16_sections_and_compat(self):
        """Verify that ReportService generates all 16 required sections and backwards-compatible aliases."""
        res = ReportService.generate_report("testowner", "reporttest", force_refresh=True)
        self.assertTrue(res["success"])
        report = res["report"]

        # 16 Primary Technical Sections
        self.assertIn("project_overview", report)              # 1
        self.assertIn("repository_summary", report)          # 2
        self.assertIn("project_structure", report)            # 3
        self.assertIn("architecture_overview", report)        # 4
        self.assertIn("architecture_diagram", report)         # 5
        self.assertIn("major_components", report)             # 6
        self.assertIn("important_files", report)              # 7
        self.assertIn("classes_section", report)              # 8
        self.assertIn("functions_and_methods", report)        # 9
        self.assertIn("dependencies_and_relationships", report) # 10
        self.assertIn("entry_points_section", report)         # 11
        self.assertIn("architecture_relationships", report)   # 12
        self.assertIn("code_graph_summary", report)           # 13
        self.assertIn("project_explanation", report)          # 14
        self.assertIn("observations", report)                 # 15
        self.assertIn("conclusion", report)                   # 16

        # Human-Friendly Sections
        self.assertIn("what_project_does", report)
        self.assertIn("how_project_works", report)
        self.assertIn("for_new_developer", report)
        self.assertIn("technical_analysis", report)

        # Compatibility aliases
        self.assertIn("overview", report)
        self.assertIn("repository", report)
        self.assertIn("statistics", report)
        self.assertIn("classes", report)
        self.assertIn("functions", report)
        self.assertIn("methods", report)

    def test_human_friendly_report_structure(self):
        """Verify the 15-section human-friendly report structure and content."""
        res = ReportService.generate_report("testowner", "reporttest", force_refresh=True)
        report = res["report"]

        # Section 2: What Does This Project Do?
        what = report["what_project_does"]
        self.assertIn("problem_solved", what)
        self.assertIn("target_audience", what)
        self.assertIn("main_purpose", what)

        # Section 3: How Does the Project Work?
        how = report["how_project_works"]
        self.assertIn("flow_summary", how)
        self.assertIn("flow_diagram", how)
        self.assertIn("stages", how)
        self.assertEqual(len(how["stages"]), 5)
        self.assertEqual(how["stages"][0]["name"], "User / Application")
        self.assertEqual(how["stages"][1]["name"], "Public API")
        self.assertEqual(how["stages"][2]["name"], "Core Processing")
        self.assertEqual(how["stages"][3]["name"], "Supporting Components")
        self.assertEqual(how["stages"][4]["name"], "Output / Result")

        # Section 6: Important Files with purpose
        files = report["important_files"]["files"]
        self.assertGreater(len(files), 0)
        for f in files:
            self.assertIn("purpose", f)
            self.assertIn("role", f)

        # Section 9: Dependencies with plain English explanations
        deps = report["dependencies_and_relationships"]["external_packages"]
        self.assertGreater(len(deps), 0)
        self.assertIn("purpose", deps[0])

        # Section 11: For a New Developer
        onboarding = report["for_new_developer"]
        self.assertIn("start_here", onboarding)
        self.assertIn("reading_order", onboarding)
        self.assertIn("tests_location", onboarding)
        self.assertIn("safe_exploration", onboarding)
        self.assertGreater(len(onboarding["reading_order"]), 0)

        # Section 12: Technical Analysis
        tech = report["technical_analysis"]
        self.assertIn("metrics", tech)
        self.assertIn("languages", tech)
        self.assertIn("directory_tree", tech)


    def test_report_factual_accuracy_no_hallucinations(self):
        """Verify that reported statistics accurately reflect the extracted AST knowledge."""
        res = ReportService.generate_report("testowner", "reporttest", force_refresh=True)
        stats = res["report"]["statistics"]

        self.assertEqual(stats["total_files"], 3)
        self.assertEqual(stats["total_directories"], 3)
        self.assertEqual(stats["total_classes"], 1)
        self.assertEqual(stats["total_functions"], 2)
        self.assertEqual(stats["total_methods"], 2)
        self.assertEqual(stats["total_imports"], 3)
        self.assertEqual(stats["total_dependencies"], 2)
        self.assertEqual(stats["entry_points_count"], 1)
        self.assertEqual(stats["cycles_count"], 0)

        # Technologies detection
        techs = res["report"]["technologies"]
        tech_names = [t["name"] for t in techs]
        self.assertIn("flask", tech_names)

    def test_markdown_and_html_rendering(self):
        """Verify markdown and HTML outputs are generated properly."""
        res = ReportService.generate_report("testowner", "reporttest", force_refresh=True)
        md = res["markdown"]
        html = res["html"]

        self.assertIn("# CodeLens AI", md)
        self.assertIn("## 1. Project Overview", md)
        self.assertIn("## 16. Conclusion", md)
        self.assertIn("AppServer", md)

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("CodeLens AI", html)
        self.assertIn("AppServer", html)

    def test_api_report_post_endpoint(self):
        """Verify POST /api/repositories/report generates report via HTTP."""
        response = self.client.post(
            "/api/repositories/report",
            json={"repo": "testowner/reporttest", "force_refresh": False},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("report", data)
        self.assertEqual(data["report"]["repository"]["name"], "reporttest")

    def test_api_report_get_endpoint(self):
        """Verify GET /api/repositories/report/<owner>/<name> retrieves stored report."""
        response = self.client.get("/api/repositories/report/testowner/reporttest")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["report"]["statistics"]["total_files"], 3)

    def test_api_report_download_endpoint(self):
        """Verify GET /api/repositories/report/<owner>/<name>/download serves files."""
        # Download Markdown
        res_md = self.client.get("/api/repositories/report/testowner/reporttest/download?format=md")
        self.assertEqual(res_md.status_code, 200)
        self.assertIn(b"CodeLens AI", res_md.data)
        res_md.close()

        # Download HTML
        res_html = self.client.get("/api/repositories/report/testowner/reporttest/download?format=html")
        self.assertEqual(res_html.status_code, 200)
        self.assertIn(b"<!DOCTYPE html>", res_html.data)
        res_html.close()

    def test_multi_repo_isolation(self):
        """Verify that reports for different repos remain strictly segregated."""
        repo2 = RepositoryInfo(name="otherrepo", owner="testowner", url="https://github.com/testowner/otherrepo")
        know2 = SharedRepositoryKnowledge(
            repository=repo2,
            directories=[],
            files=[FileInfo(path="solo.py", name="solo.py", extension=".py")],
            classes=[],
            functions=[],
            methods=[],
            imports=[],
            dependencies=[],
        )
        KnowledgeService.save_knowledge("testowner", "otherrepo", know2)

        res1 = ReportService.generate_report("testowner", "reporttest")
        res2 = ReportService.generate_report("testowner", "otherrepo")

        self.assertEqual(res1["report"]["repository"]["name"], "reporttest")
        self.assertEqual(res2["report"]["repository"]["name"], "otherrepo")
        self.assertEqual(res1["report"]["statistics"]["total_files"], 3)
        self.assertEqual(res2["report"]["statistics"]["total_files"], 1)

    def test_primary_production_subsystem_wording(self):
        """Verify report uses 'Identified 1 primary production subsystem and ...' for single production core."""
        res = ReportService.generate_report("testowner", "reporttest", force_refresh=True)
        self.assertTrue(res["success"])
        bullets = res["report"]["architecture_overview"]["summary_bullets"]
        
        # Check that it uses singular 'primary production subsystem'
        matching = [b for b in bullets if "primary production subsystem" in b]
        self.assertEqual(len(matching), 1)
        self.assertIn("Identified 1 primary production subsystem and", matching[0])
        # Ensure grammatically incorrect phrasing is not present
        self.assertNotIn("Identified 1 production subsystems", " ".join(bullets))

    def test_section_10_verification_relationship(self):
        """Verify Section 10 correctly explains verification relationships and does not claim production depends on tests."""
        res = ReportService.generate_report("testowner", "reporttest", force_refresh=True)
        self.assertTrue(res["success"])
        narrative = res["report"]["architecture_relationships"]["narrative"]
        self.assertIn("The repository is organized into well-defined subsystems that separate production code, tests, documentation, packaging, and project assets", narrative)


if __name__ == "__main__":
    unittest.main()
