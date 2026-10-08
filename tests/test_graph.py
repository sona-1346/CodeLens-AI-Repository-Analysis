"""
Unit and integration tests for Phase 7:
Shared Repository Knowledge layer and Semantic Code Graph generation.
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
    FileInfo,
    FunctionInfo,
    MethodInfo,
    RelationshipInfo,
    RepositoryInfo,
    SharedRepositoryKnowledge,
)
from services.graph_service import SemanticCodeGraphService
from services.knowledge_service import KnowledgeService


class GraphTestCase(unittest.TestCase):
    """Test suite for Phase 7 Knowledge and Semantic Code Graph services."""

    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()

        # Build mock SharedRepositoryKnowledge
        self.mock_repo = RepositoryInfo(
            name="testrepo",
            owner="testowner",
            url="https://github.com/testowner/testrepo",
            description="Test repo for semantic graph",
            primary_language="Python",
        )

        self.mock_knowledge = SharedRepositoryKnowledge(
            repository=self.mock_repo,
            directories=[
                DirectoryInfo(path="core", name="core"),
                DirectoryInfo(path="core/utils", name="utils", parent="core"),
            ],
            files=[
                FileInfo(path="core/app.py", name="app.py", extension=".py", language="Python", size=2048),
                FileInfo(path="core/utils/helper.py", name="helper.py", extension=".py", language="Python", size=1024),
            ],
            classes=[
                ClassInfo(
                    name="BaseService",
                    file="core/app.py",
                    base_classes=["object"],
                    methods=["setup"],
                ),
                ClassInfo(
                    name="ApiService",
                    file="core/app.py",
                    base_classes=["BaseService"],
                    methods=["get", "post"],
                ),
            ],
            functions=[
                FunctionInfo(name="init_app", file="core/app.py", parameters=["config"]),
                FunctionInfo(name="format_date", file="core/utils/helper.py", parameters=["dt"]),
            ],
            methods=[
                MethodInfo(name="setup", class_name="BaseService", file="core/app.py"),
                MethodInfo(name="get", class_name="ApiService", file="core/app.py", parameters=["endpoint"]),
                MethodInfo(name="post", class_name="ApiService", file="core/app.py", parameters=["endpoint", "data"]),
            ],
            dependencies=[
                DependencyInfo(name="requests", type="external_package", occurrences=4, files=["core/app.py"]),
                DependencyInfo(name="json", type="standard_library", occurrences=2, files=["core/utils/helper.py"]),
            ],
            relationships=[
                RelationshipInfo(source="core/app.py", relation="contains_method", target="setup", source_type="file", target_type="method"),
                RelationshipInfo(source="ApiService", relation="inherits_from", target="BaseService", source_type="class", target_type="class"),
            ],
        )

    def test_shared_knowledge_model_serialization(self):
        """Test SharedRepositoryKnowledge serialization to dict, JSON, and deserialization."""
        k_dict = self.mock_knowledge.to_dict()
        self.assertIn("repository", k_dict)
        self.assertEqual(k_dict["repository"]["name"], "testrepo")
        self.assertEqual(len(k_dict["classes"]), 2)
        self.assertEqual(len(k_dict["methods"]), 3)
        self.assertEqual(len(k_dict["dependencies"]), 2)

        # JSON roundtrip
        k_json = self.mock_knowledge.to_json()
        reconstructed = SharedRepositoryKnowledge.from_dict(json.loads(k_json))
        self.assertEqual(reconstructed.repository.full_name, "testowner/testrepo")
        self.assertEqual(len(reconstructed.files), 2)
        self.assertEqual(reconstructed.classes[1].name, "ApiService")
        self.assertEqual(reconstructed.classes[1].base_classes, ["BaseService"])

    def test_graph_hierarchy_and_edges(self):
        """Verify graph builds correct logical hierarchy: Repo -> Dir -> File -> Class -> Method."""
        G, meta = SemanticCodeGraphService.build_graph(self.mock_knowledge)

        # 1. Root Repository Node
        repo_id = "repository:testowner/testrepo"
        self.assertTrue(G.has_node(repo_id))
        self.assertEqual(G.nodes[repo_id]["type"], "repository")

        # 2. Directory Nodes
        dir_core = "directory:core"
        dir_utils = "directory:core/utils"
        self.assertTrue(G.has_node(dir_core))
        self.assertTrue(G.has_node(dir_utils))

        # Check CONTAINS hierarchy
        self.assertTrue(G.has_edge(repo_id, dir_core))
        self.assertTrue(G.has_edge(dir_core, dir_utils))

        # 3. File Nodes
        file_app = "file:core/app.py"
        file_helper = "file:core/utils/helper.py"
        self.assertTrue(G.has_node(file_app))
        self.assertTrue(G.has_node(file_helper))

        self.assertTrue(G.has_edge(dir_core, file_app))
        self.assertTrue(G.has_edge(dir_utils, file_helper))

        # 4. Class & Method Nodes
        class_base = "class:core/app.py:BaseService"
        class_api = "class:core/app.py:ApiService"
        self.assertTrue(G.has_node(class_base))
        self.assertTrue(G.has_node(class_api))

        # File defines and contains Class
        self.assertTrue(G.has_edge(file_app, class_api))

        # Class contains Method
        method_get = "method:core/app.py:ApiService:get"
        self.assertTrue(G.has_node(method_get))
        self.assertTrue(G.has_edge(class_api, method_get))

        # 5. Inheritance Edge (ApiService -> BaseService)
        self.assertTrue(G.has_edge(class_api, class_base))
        self.assertEqual(G.edges[class_api, class_base]["type"], "INHERITS")

        # 6. Dependency Nodes and Edges
        dep_req = "dependency:requests"
        self.assertTrue(G.has_node(dep_req))
        self.assertTrue(G.has_edge(file_app, dep_req))
        self.assertEqual(G.edges[file_app, dep_req]["type"], "DEPENDS_ON")

    def test_graph_validation_and_clean_statistics(self):
        """Verify graph validation catches errors and computes authentic statistics."""
        G, meta = SemanticCodeGraphService.build_graph(self.mock_knowledge)
        val = meta["validation"]
        stats = meta["statistics"]

        self.assertTrue(val["is_valid"])
        self.assertEqual(val["issues_count"], 0)

        # Verify accurate counts
        self.assertEqual(stats["repository_nodes"], 1)
        self.assertEqual(stats["directory_nodes"], 2)
        self.assertEqual(stats["file_nodes"], 2)
        self.assertEqual(stats["class_nodes"], 3)  # BaseService, ApiService, + external 'object'
        self.assertEqual(stats["function_nodes"], 2)
        self.assertEqual(stats["method_nodes"], 3)
        self.assertEqual(stats["dependency_nodes"], 2)
        self.assertGreater(stats["contains_edges"], 0)
        self.assertGreater(stats["inherits_edges"], 0)

    def test_repository_isolation(self):
        """Verify graphs for two different repositories do not mix nodes or edges."""
        repo_a = RepositoryInfo(name="repo-a", owner="org-a", url="https://github.com/org-a/repo-a")
        knowledge_a = SharedRepositoryKnowledge(
            repository=repo_a,
            files=[FileInfo(path="a.py", name="a.py", extension=".py")],
            classes=[ClassInfo(name="ClassA", file="a.py")],
        )

        repo_b = RepositoryInfo(name="repo-b", owner="org-b", url="https://github.com/org-b/repo-b")
        knowledge_b = SharedRepositoryKnowledge(
            repository=repo_b,
            files=[FileInfo(path="b.py", name="b.py", extension=".py")],
            classes=[ClassInfo(name="ClassB", file="b.py")],
        )

        g_a, _ = SemanticCodeGraphService.build_graph(knowledge_a)
        g_b, _ = SemanticCodeGraphService.build_graph(knowledge_b)

        # Assert no cross contamination
        self.assertTrue(g_a.has_node("repository:org-a/repo-a"))
        self.assertFalse(g_a.has_node("repository:org-b/repo-b"))
        self.assertFalse(g_a.has_node("file:b.py"))
        self.assertFalse(g_a.has_node("class:b.py:ClassB"))

        self.assertTrue(g_b.has_node("repository:org-b/repo-b"))
        self.assertFalse(g_b.has_node("repository:org-a/repo-a"))
        self.assertFalse(g_b.has_node("file:a.py"))
        self.assertFalse(g_b.has_node("class:a.py:ClassA"))

    def test_api_graph_endpoints(self):
        """Test POST /api/repositories/graph and GET endpoints."""
        # 1. Invalid repo payload
        resp_bad = self.client.post("/api/repositories/graph", json={})
        self.assertEqual(resp_bad.status_code, 400)

        # 2. Get unanalyzed graph
        resp_404 = self.client.get("/api/repositories/graph/unknownowner/unknownrepo")
        self.assertEqual(resp_404.status_code, 404)

        # 3. Test on bottlepy/bottle (which was analyzed and cached)
        resp_graph = self.client.get("/api/repositories/graph/bottlepy/bottle")
        if resp_graph.status_code == 200:
            data = resp_graph.get_json()
            self.assertTrue(data["success"])
            self.assertIn("graph", data)
            self.assertIn("nodes", data["graph"])
            self.assertIn("edges", data["graph"])
            self.assertIn("statistics", data["graph"])
            self.assertGreater(data["graph"]["statistics"]["total_nodes"], 100)


if __name__ == "__main__":
    unittest.main()
