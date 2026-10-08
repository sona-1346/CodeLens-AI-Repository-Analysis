"""
Unit and integration tests for Phase 8:
Whole Repository Architecture Explorer, Hierarchical Levels, Cycle Detection,
Connected Hubs Analysis, and API Endpoints.
"""

import json
from pathlib import Path
import tempfile
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
from services.architecture_service import ArchitectureService
from services.knowledge_service import KnowledgeService


class ArchitectureTestCase(unittest.TestCase):
    """Test suite for Phase 8 Whole Repository Architecture Explorer."""

    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()

        # Build mock repository knowledge with clear hierarchy and entry points
        self.mock_repo = RepositoryInfo(
            name="archtest",
            owner="testowner",
            url="https://github.com/testowner/archtest",
            description="Test repo for architecture explorer",
            primary_language="Python",
        )

        self.mock_knowledge = SharedRepositoryKnowledge(
            repository=self.mock_repo,
            directories=[
                DirectoryInfo(path="core", name="core"),
                DirectoryInfo(path="core/sub", name="sub", parent="core"),
                DirectoryInfo(path="tests", name="tests"),
            ],
            files=[
                FileInfo(path="main.py", name="main.py", extension=".py", language="Python", size=3000),
                FileInfo(path="core/engine.py", name="engine.py", extension=".py", language="Python", size=4500),
                FileInfo(path="core/sub/worker.py", name="worker.py", extension=".py", language="Python", size=2000),
                FileInfo(path="tests/test_main.py", name="test_main.py", extension=".py", language="Python", size=1500),
            ],
            classes=[
                ClassInfo(
                    name="EngineCore",
                    file="core/engine.py",
                    base_classes=["object"],
                    methods=["start", "stop"],
                    docstring="Core engine controller.",
                ),
                ClassInfo(
                    name="TaskWorker",
                    file="core/sub/worker.py",
                    base_classes=["EngineCore"],
                    methods=["execute"],
                    docstring="Worker executing tasks.",
                ),
            ],
            functions=[
                FunctionInfo(name="bootstrap", file="main.py", parameters=["args"]),
                FunctionInfo(name="run_tests", file="tests/test_main.py", parameters=[]),
            ],
            methods=[
                MethodInfo(name="start", class_name="EngineCore", file="core/engine.py"),
                MethodInfo(name="stop", class_name="EngineCore", file="core/engine.py"),
                MethodInfo(name="execute", class_name="TaskWorker", file="core/sub/worker.py"),
            ],
            dependencies=[
                DependencyInfo(name="requests", type="external_package", occurrences=3, files=["core/engine.py"]),
                DependencyInfo(name="sys", type="standard_library", occurrences=2, files=["main.py"]),
            ],
            relationships=[
                # main.py imports core/engine.py
                RelationshipInfo(source="main.py", relation="imports", target="core/engine.py", source_type="file", target_type="file"),
                # core/engine.py imports core/sub/worker.py
                RelationshipInfo(source="core/engine.py", relation="imports", target="core/sub/worker.py", source_type="file", target_type="file"),
                # TaskWorker inherits EngineCore
                RelationshipInfo(source="TaskWorker", relation="inherits_from", target="EngineCore", source_type="class", target_type="class"),
                # TaskWorker calls EngineCore.start
                RelationshipInfo(source="TaskWorker", relation="calls", target="start", source_type="class", target_type="method"),
            ],
            imports=[
                ImportInfo(source_file="main.py", imported_module="core.engine", imported_symbol=None),
                ImportInfo(source_file="core/engine.py", imported_module="core.sub.worker", imported_symbol=None),
                ImportInfo(source_file="core/engine.py", imported_module="requests", imported_symbol=None, is_standard_library=False),
                ImportInfo(source_file="main.py", imported_module="sys", imported_symbol=None, is_standard_library=True),
            ],
            entry_points=[
                EntryPointInfo(
                    file="main.py",
                    line=42,
                    symbol="main",
                    detection_reason="main_block",
                )
            ],
        )

        # Store knowledge in KnowledgeService cache
        KnowledgeService.save_knowledge("testowner", "archtest", self.mock_knowledge)

    def test_architecture_data_generation(self):
        """Test full architecture data model generation from shared knowledge."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=True)

        self.assertIsNotNone(data)
        self.assertEqual(data["repository"]["name"], "archtest")
        self.assertEqual(data["repository"]["owner"], "testowner")

        # Verify statistics
        stats = data["statistics"]
        self.assertEqual(stats["total_files"], 4)
        self.assertEqual(stats["total_directories"], 3)
        self.assertEqual(stats["total_classes"], 2)
        self.assertEqual(stats["total_functions"], 2)
        self.assertEqual(stats["total_methods"], 3)
        self.assertEqual(stats["entry_points_count"], 1)

    def test_four_hierarchical_levels(self):
        """Test that all 4 hierarchical levels are accurately populated."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=False)
        levels = data["levels"]

        # Level 1: Overview
        l1 = levels["level_1"]
        self.assertEqual(l1["root"]["name"], "archtest")
        self.assertTrue(len(l1["major_directories"]) >= 2)
        root_file_names = [f["name"] for f in l1["root_files"]]
        self.assertIn("main.py", root_file_names)

        # Level 2: Directory Level
        l2 = levels["level_2"]
        dir_paths = [d["path"] for d in l2["directories"]]
        self.assertIn("core", dir_paths)
        self.assertIn("tests", dir_paths)

        # Level 3: File Level
        l3 = levels["level_3"]
        file_paths = [f["path"] for f in l3["files"]]
        self.assertIn("core/engine.py", file_paths)
        engine_file = next(f for f in l3["files"] if f["path"] == "core/engine.py")
        self.assertEqual(len(engine_file["classes"]), 1)
        self.assertEqual(engine_file["classes"][0]["name"], "EngineCore")

        # Level 4: Entity Level
        l4 = levels["level_4"]
        node_ids = [n["id"] for n in l4["nodes"]]
        self.assertIn("class:EngineCore", node_ids)
        self.assertIn("class:TaskWorker", node_ids)
        self.assertTrue(len(l4["edges"]) > 0)

    def test_dependency_cycle_detection_clean_dag(self):
        """Test that acyclic graph returns 0 cycles and is_acyclic=True."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=False)
        self.assertTrue(data["is_acyclic"])
        self.assertEqual(data["statistics"]["cycles_count"], 0)
        self.assertEqual(len(data["cycles"]), 0)

    def test_dependency_cycle_detection_with_cycle(self):
        """Test circular dependency detection when a cycle is injected."""
        # Inject circular imports: main.py -> core/engine.py -> core/sub/worker.py -> main.py
        cyclic_knowledge = SharedRepositoryKnowledge.from_dict(self.mock_knowledge.to_dict())
        cyclic_knowledge.repository.name = "cycletest"
        cyclic_knowledge.imports = [
            ImportInfo(source_file="main.py", imported_module="core.engine", imported_symbol=None),
            ImportInfo(source_file="core/engine.py", imported_module="core.sub.worker", imported_symbol=None),
            ImportInfo(source_file="core/sub/worker.py", imported_module="main", imported_symbol=None),
        ]
        KnowledgeService.save_knowledge("testowner", "cycletest", cyclic_knowledge)

        data = ArchitectureService.get_architecture_data("testowner", "cycletest", force_refresh=True)
        self.assertFalse(data["is_acyclic"])
        self.assertGreaterEqual(data["statistics"]["cycles_count"], 1)
        self.assertTrue(any("main.py" in c for c in data["cycles"]))

    def test_highly_connected_hubs_and_centrality(self):
        """Test identification and ranking of architectural hubs with centrality scores."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=True)
        hubs = data["highly_connected_components"]

        self.assertIsInstance(hubs, list)
        self.assertTrue(len(hubs) > 0)

        top_hub = hubs[0]
        self.assertIn("id", top_hub)
        self.assertIn("name", top_hub)
        self.assertIn("total_connections", top_hub)
        self.assertIn("centrality_score", top_hub)
        self.assertIn("role_tag", top_hub)
        self.assertIn("explanation", top_hub)
        self.assertGreaterEqual(top_hub["centrality_score"], 0.0)

    def test_search_index_generation(self):
        """Test that rapid search index contains directories, files, classes, and routines."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=False)
        search_index = data["search_index"]

        types = {item["type"] for item in search_index}
        self.assertIn("directory", types)
        self.assertIn("file", types)
        self.assertIn("class", types)
        self.assertIn("function", types)

        names = [item["name"] for item in search_index]
        self.assertIn("main.py", names)
        self.assertIn("EngineCore", names)
        self.assertIn("bootstrap()", names)

    def test_deterministic_summary_dossier(self):
        """Test deterministic summary bullets synthesized from static metrics."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=True)
        summary = data["summary"]

        bullets = summary["overview_bullets"] if isinstance(summary, dict) else summary
        self.assertIsInstance(bullets, list)
        self.assertGreaterEqual(len(bullets), 4)

        # Check title and bullet contents
        title = summary.get("title", "") if isinstance(summary, dict) else ""
        self.assertIn("testowner/archtest", title)
        joined = " ".join(bullets)
        self.assertIn("Python", joined)
        self.assertIn("cycles", joined.lower())

    def test_api_architecture_post_endpoint(self):
        """Test POST /api/repositories/architecture endpoint."""
        response = self.client.post(
            "/api/repositories/architecture",
            json={"repo": "testowner/archtest", "force_refresh": False},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["repository"]["name"], "archtest")

    def test_api_architecture_get_endpoint(self):
        """Test GET /api/repositories/architecture/<owner>/<name> endpoint."""
        response = self.client.get("/api/repositories/architecture/testowner/archtest")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["statistics"]["total_files"], 4)

    def test_api_cycles_get_endpoint(self):
        """Test GET /api/repositories/architecture/<owner>/<name>/cycles endpoint."""
        response = self.client.get("/api/repositories/architecture/testowner/archtest/cycles")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["cycles_detected"])
        self.assertEqual(data["cycles_count"], 0)

    def test_architecture_html_page_route(self):
        """Test GET /architecture renders HTML template successfully."""
        response = self.client.get("/architecture?repo=testowner/archtest")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Whole Repository Architecture Explorer", html)
        self.assertIn("arch-canvas", html)
        self.assertIn("Dependency Cycle Analysis", html)
    def test_component_categorization(self):
        """Test evidence-based component categorization without artificial invention."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=True)
        major_dirs = data["levels"]["level_1"]["major_directories"]

        # 'tests' directory should be categorized as 'Tests'
        tests_dir = next(d for d in major_dirs if d["name"] == "tests")
        self.assertEqual(tests_dir["category"], "Tests")

        # 'core' directory should be categorized as 'Core Modules'
        core_dir = next(d for d in major_dirs if d["name"] == "core")
        self.assertEqual(core_dir["category"], "Core Modules")

    def test_modules_tree_generation(self):
        """Test hierarchical modules tree (Repo -> Dirs -> Files -> Classes -> Methods)."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=False)
        tree = data["modules_tree"]

        self.assertIsNotNone(tree)
        self.assertEqual(tree["type"], "repo")
        self.assertEqual(tree["name"], "archtest")
        self.assertTrue(len(tree["children"]) > 0)

        # Look for core directory and its files
        core_node = next(n for n in tree["children"] if n.get("name") == "core")
        self.assertEqual(core_node["type"], "directory")

    def test_aggregated_directory_dependencies(self):
        """Test directory-level dependency flow aggregation from actual imports."""
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=True)
        dep_analysis = data["dependency_analysis"]

        self.assertIn("aggregated_directory_dependencies", dep_analysis)
        flows = dep_analysis["aggregated_directory_dependencies"]
        self.assertIsInstance(flows, list)

        # main.py in (root) imports core/engine.py in core
        root_to_core = next((f for f in flows if f["source_directory"] == "(root)" and f["target_directory"] == "core"), None)
        self.assertIsNotNone(root_to_core)
        self.assertGreaterEqual(root_to_core["relationship_count"], 1)

    def test_semantic_code_graph_route(self):
        """Test that GET /graph renders the dedicated Semantic Code Graph technical page."""
        response = self.client.get("/graph?repo=testowner/archtest")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Semantic Code Graph", html)
        self.assertIn("semantic-graph-canvas", html)

    def test_verification_flow_direction_and_type(self):
        """Test that test relationships are categorized as verification flows and production does not depend on tests."""
        # Add dependency between tests and core
        self.mock_knowledge.imports.append(
            ImportInfo(source_file="tests/test_main.py", imported_module="core.engine", is_external=False)
        )
        data = ArchitectureService.get_architecture_data("testowner", "archtest", force_refresh=True)
        flows = data.get("component_flows", [])
        
        for fl in flows:
            # If flow connects tests and a production component, tests must be source or flow_type must be verification
            if "test" in fl["source"].lower() or "test" in fl["target"].lower():
                self.assertEqual(fl.get("flow_type"), "verification")
                self.assertTrue("test" in fl["source"].lower())


if __name__ == "__main__":
    unittest.main()

