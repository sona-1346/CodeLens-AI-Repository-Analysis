"""
Unit and Integration Tests for Phase 6: Deep Static Code Analysis (AST).
Verifies:
- Python AST extraction (classes, inheritance, functions, methods, decorators, imports)
- Java AST extraction via javalang (packages, classes, interfaces, methods, modifiers)
- Dependency categorization (standard library vs external third party)
- Architectural relationship modeling (inherits_from, contains_method, imports)
- Entry point detection (main blocks, main() functions)
- Full knowledge object aggregation and disk persistence
- API endpoints: POST /api/repositories/ast-analysis, GET /api/repositories/ast-analysis/<owner>/<name>
"""

import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app import create_app
from services.ast_service import (
    PythonAstExtractor,
    JavaAstExtractor,
    DeepCodeAnalysisService,
)


class AstAnalysisTestCase(unittest.TestCase):
    """Test suite for Phase 6 AST structural extraction and knowledge graph modeling."""

    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        self.test_dir = tempfile.mkdtemp(prefix="codelens_test_ast_")

    def tearDown(self):
        self.app_context.pop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_python_ast_extractor(self):
        """Verify Python AST extraction of classes, functions, methods, imports, and relationships."""
        py_code = '''
import os
import sys
from flask import Flask, request
from .local_module import helper

@decorator_a
class BaseHandler:
    """Base docstring."""
    pass

class WebHandler(BaseHandler):
    """WebHandler docstring."""
    
    @classmethod
    def create(cls, config):
        return cls()
        
    def handle_request(self, path: str, timeout: int = 30):
        return "ok"

def standalone_func(x, y=10, *args, **kwargs):
    """Standalone docstring."""
    return x + y

if __name__ == "__main__":
    print("Running standalone")
'''
        res = PythonAstExtractor.extract(py_code, "src/handler.py")

        # 1. Classes
        classes = res["classes"]
        self.assertEqual(len(classes), 2)
        base_cls = next(c for c in classes if c["name"] == "BaseHandler")
        web_cls = next(c for c in classes if c["name"] == "WebHandler")

        self.assertEqual(base_cls["bases"], [])
        self.assertEqual(web_cls["bases"], ["BaseHandler"])
        self.assertEqual(web_cls["docstring"], "WebHandler docstring.")
        self.assertIn("create", web_cls["methods"])
        self.assertIn("handle_request", web_cls["methods"])

        # 2. Functions
        functions = res["functions"]
        self.assertEqual(len(functions), 1)
        f = functions[0]
        self.assertEqual(f["name"], "standalone_func")
        self.assertIn("x", f["args"])
        self.assertIn("y", f["args"])
        self.assertIn("*args", f["args"])
        self.assertIn("**kwargs", f["args"])

        # 3. Methods
        methods = res["methods"]
        self.assertEqual(len(methods), 2)
        m_names = [m["name"] for m in methods]
        self.assertIn("create", m_names)
        self.assertIn("handle_request", m_names)

        # 4. Imports & Dependency Classification
        imports = res["imports"]
        self.assertGreaterEqual(len(imports), 4)

        os_imp = next(i for i in imports if i["root_module"] == "os")
        flask_imp = next(i for i in imports if i["root_module"] == "flask")

        self.assertTrue(os_imp["is_standard_library"])
        self.assertFalse(os_imp["is_external"])

        self.assertFalse(flask_imp["is_standard_library"])
        self.assertTrue(flask_imp["is_external"])

        # 5. Entry Points
        entry_points = res["entry_points"]
        self.assertTrue(any(e["type"] == "main_block" for e in entry_points))

        # 6. Relationships
        rels = res["relationships"]
        self.assertTrue(any(r["relation"] == "inherits_from" and r["source"] == "WebHandler" and r["target"] == "BaseHandler" for r in rels))
        self.assertTrue(any(r["relation"] == "contains_method" and r["source"] == "WebHandler" and r["target"] == "create" for r in rels))
        self.assertTrue(any(r["relation"] == "imports" and r["target"] == "flask" for r in rels))

    def test_java_ast_extractor(self):
        """Verify Java AST extraction of packages, classes, interfaces, methods, and entry points."""
        java_code = '''
package com.codelens.demo;

import java.util.List;
import org.springframework.stereotype.Service;

public class OrderService extends BaseService implements Processable {
    private String serviceId;

    public static void main(String[] args) {
        System.out.println("Started");
    }

    public boolean processOrder(Long orderId, String status) {
        return true;
    }
}
'''
        res = JavaAstExtractor.extract(java_code, "src/main/OrderService.java")

        # Classes
        classes = res["classes"]
        self.assertEqual(len(classes), 1)
        c = classes[0]
        self.assertEqual(c["name"], "OrderService")
        self.assertEqual(c["package"], "com.codelens.demo")
        self.assertIn("BaseService", c["bases"])
        self.assertIn("Processable", c["interfaces"])

        # Methods
        methods = res["methods"]
        m_names = [m["name"] for m in methods]
        self.assertIn("main", m_names)
        self.assertIn("processOrder", m_names)

        # Imports
        imports = res["imports"]
        std_imp = next(i for i in imports if "java.util" in i["module"])
        ext_imp = next(i for i in imports if "springframework" in i["module"])
        self.assertTrue(std_imp["is_standard_library"])
        self.assertTrue(ext_imp["is_external"])

        # Entry Point
        entry_points = res["entry_points"]
        self.assertTrue(any(e["type"] == "main_method" for e in entry_points))

        # Relationships
        rels = res["relationships"]
        self.assertTrue(any(r["relation"] == "inherits_from" and r["source"] == "OrderService" for r in rels))
        self.assertTrue(any(r["relation"] == "implements" and r["source"] == "OrderService" for r in rels))

    def test_deep_code_analysis_pipeline_and_cache(self):
        """Verify full repository code analysis pipeline across multiple files, stats, and cache."""
        root = Path(self.test_dir)

        # Create Python and Java source files
        (root / "app.py").write_text('''
import os
import requests

class ServerApp:
    def start(self):
        pass

def bootstrap():
    app = ServerApp()
    app.start()

if __name__ == "__main__":
    bootstrap()
''', encoding="utf-8")

        (root / "Client.java").write_text('''
package com.client;

import java.io.File;
import org.apache.commons.io.FileUtils;

public class Client {
    public void connect(String host) {}
}
''', encoding="utf-8")

        owner = "testowner"
        name = "testast"

        # 1. Execute analysis
        res1 = DeepCodeAnalysisService.analyze_codebase(
            owner=owner,
            name=name,
            repo_path=root,
            force_refresh=True,
        )

        self.assertTrue(res1["success"])
        self.assertFalse(res1["is_cached"])

        stats = res1["statistics"]
        self.assertGreaterEqual(stats["classes_count"], 2)  # ServerApp + Client
        self.assertGreaterEqual(stats["functions_count"], 1)  # bootstrap
        self.assertGreaterEqual(stats["methods_count"], 2)  # start + connect
        self.assertGreaterEqual(stats["imports_count"], 4)  # os, requests, File, FileUtils
        self.assertGreaterEqual(stats["external_dependencies_count"], 2)  # requests + org.apache.commons.io

        # 2. Check persistence
        k_file = DeepCodeAnalysisService.get_knowledge_file_path(owner, name)
        self.assertTrue(k_file.is_file())

        # 3. Test cache hit on second run
        res2 = DeepCodeAnalysisService.analyze_codebase(
            owner=owner,
            name=name,
            repo_path=root,
            force_refresh=False,
        )
        self.assertTrue(res2["success"])
        self.assertTrue(res2["is_cached"])
        self.assertEqual(res2["statistics"]["classes_count"], stats["classes_count"])

        # Cleanup cache file
        if k_file.is_file():
            k_file.unlink()

    def test_api_ast_analysis_endpoint(self):
        """Test POST /api/repositories/ast-analysis endpoint."""
        # Non-existent repository returns 400
        res = self.client.post(
            "/api/repositories/ast-analysis",
            json={"repo": "nonexistent/repo12345"},
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])

    def test_api_get_ast_analysis_404(self):
        """Test GET /api/repositories/ast-analysis/<owner>/<name> returns 404 when unanalyzed."""
        res = self.client.get("/api/repositories/ast-analysis/unknown_owner/unknown_repo")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data["success"])


if __name__ == "__main__":
    unittest.main()
