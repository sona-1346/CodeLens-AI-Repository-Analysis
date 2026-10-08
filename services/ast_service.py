"""
Deep Static Code Analysis Service for CodeLens AI (Phase 6).

Extracts Abstract Syntax Tree (AST) structural knowledge:
- Python AST (modules, classes, methods, functions, arguments, decorators, inheritance, imports)
- Java AST via javalang (packages, classes, interfaces, methods, parameters, annotations, inheritance)
- JavaScript / TypeScript structural extraction (classes, functions, methods, imports)
- Dependency categorization (Standard Library vs External Third-Party)
- Entry point detection (main blocks, CLI functions)
- Architectural relationship modeling (inherits_from, contains_method, imports, defines)

SAFETY GUARANTEE:
- STRICTLY STATIC ANALYSIS: Repository source code is NEVER executed or imported.
- All files are parsed via abstract grammar / lexer trees.
"""

import os
import ast
import re
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Try importing javalang for Java AST parsing
try:
    import javalang
    JAVALANG_AVAILABLE = True
except ImportError:
    javalang = None
    JAVALANG_AVAILABLE = False


class PythonAstExtractor:
    """Extracts structural AST knowledge from Python source files."""

    # Set of Python Standard Library modules (Python 3.10+)
    STDLIB_MODULES: Set[str] = set(getattr(sys, "stdlib_module_names", {
        "os", "sys", "re", "json", "time", "datetime", "math", "random",
        "collections", "itertools", "functools", "pathlib", "typing",
        "urllib", "http", "unittest", "logging", "subprocess", "shutil",
        "io", "string", "copy", "socket", "threading", "multiprocessing",
        "hashlib", "base64", "csv", "sqlite3", "tempfile", "glob",
    }))

    @classmethod
    def extract(cls, code: str, rel_path: str) -> Dict[str, Any]:
        """
        Parse Python source code using standard library ast module.
        Returns extracted classes, functions, methods, imports, entry points, and relationships.
        """
        classes = []
        functions = []
        methods = []
        imports = []
        entry_points = []
        relationships = []

        try:
            tree = ast.parse(code, filename=rel_path)
        except (SyntaxError, UnicodeDecodeError, ValueError) as err:
            logger.debug(f"Could not parse Python AST for {rel_path}: {err}")
            return {
                "classes": classes,
                "functions": functions,
                "methods": methods,
                "imports": imports,
                "entry_points": entry_points,
                "relationships": relationships,
            }

        # Module docstring
        module_doc = ast.get_docstring(tree)

        for node in ast.iter_child_nodes(tree):
            # 1. Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    is_std = root_mod in cls.STDLIB_MODULES
                    imp_item = {
                        "file": rel_path,
                        "module": alias.name,
                        "root_module": root_mod,
                        "imported_name": alias.name,
                        "alias": alias.asname,
                        "is_standard_library": is_std,
                        "is_external": not is_std,
                        "line": node.lineno,
                    }
                    imports.append(imp_item)
                    relationships.append({
                        "source": rel_path,
                        "relation": "imports",
                        "target": root_mod,
                        "source_type": "file",
                        "target_type": "module",
                    })

            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                root_mod = mod_name.split(".")[0] if mod_name else rel_path
                is_std = root_mod in cls.STDLIB_MODULES if node.level == 0 else False
                for alias in node.names:
                    imp_item = {
                        "file": rel_path,
                        "module": mod_name,
                        "root_module": root_mod,
                        "imported_name": alias.name,
                        "alias": alias.asname,
                        "is_standard_library": is_std,
                        "is_external": (node.level == 0 and not is_std),
                        "is_relative": node.level > 0,
                        "line": node.lineno,
                    }
                    imports.append(imp_item)
                    relationships.append({
                        "source": rel_path,
                        "relation": "imports",
                        "target": root_mod if node.level == 0 else alias.name,
                        "source_type": "file",
                        "target_type": "module",
                    })

            # 2. Top-Level Classes
            elif isinstance(node, ast.ClassDef):
                cls_data, cls_methods, cls_rels = cls._extract_class(node, rel_path)
                classes.append(cls_data)
                methods.extend(cls_methods)
                relationships.extend(cls_rels)
                relationships.append({
                    "source": rel_path,
                    "relation": "defines",
                    "target": cls_data["name"],
                    "source_type": "file",
                    "target_type": "class",
                })

            # 3. Top-Level Functions
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_data = cls._extract_function(node, rel_path, is_method=False)
                functions.append(func_data)
                relationships.append({
                    "source": rel_path,
                    "relation": "defines",
                    "target": func_data["name"],
                    "source_type": "file",
                    "target_type": "function",
                })

                # Check for main or cli entry point function
                if func_data["name"] in {"main", "cli", "run", "start"}:
                    entry_points.append({
                        "file": rel_path,
                        "type": "function",
                        "symbol": func_data["name"],
                        "line": node.lineno,
                    })

            # 4. Entry point: if __name__ == '__main__':
            elif isinstance(node, ast.If):
                if cls._is_main_block(node):
                    entry_points.append({
                        "file": rel_path,
                        "type": "main_block",
                        "symbol": "__main__",
                        "line": node.lineno,
                    })

        return {
            "classes": classes,
            "functions": functions,
            "methods": methods,
            "imports": imports,
            "entry_points": entry_points,
            "relationships": relationships,
        }

    @classmethod
    def _extract_class(cls, node: ast.ClassDef, rel_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extract a class, its base classes, docstring, methods, and relationships."""
        bases = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                bases.append(f"{cls._node_to_str(b.value)}.{b.attr}")
            else:
                bases.append(cls._node_to_str(b))

        decorators = [cls._node_to_str(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)

        class_methods = []
        class_rels = []

        # Inheritance relationships
        for base in bases:
            class_rels.append({
                "source": node.name,
                "relation": "inherits_from",
                "target": base,
                "source_type": "class",
                "target_type": "class",
            })

        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m_data = cls._extract_function(child, rel_path, is_method=True, class_name=node.name)
                class_methods.append(m_data)
                class_rels.append({
                    "source": node.name,
                    "relation": "contains_method",
                    "target": m_data["name"],
                    "source_type": "class",
                    "target_type": "method",
                })

        cls_data = {
            "id": f"{rel_path}:{node.name}",
            "name": node.name,
            "file": rel_path,
            "language": "Python",
            "bases": bases,
            "decorators": decorators,
            "docstring": docstring,
            "line_start": node.lineno,
            "line_end": getattr(node, "end_lineno", node.lineno),
            "methods_count": len(class_methods),
            "methods": [m["name"] for m in class_methods],
        }

        return cls_data, class_methods, class_rels

    @classmethod
    def _extract_function(
        cls,
        node: Any,
        rel_path: str,
        is_method: bool = False,
        class_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract function or method arguments, decorators, and line numbers."""
        args_list = []
        args_node = node.args

        # Positional arguments
        for a in args_node.args:
            args_list.append(a.arg)

        # *args
        if args_node.vararg:
            args_list.append(f"*{args_node.vararg.arg}")

        # **kwargs
        if args_node.kwarg:
            args_list.append(f"**{args_node.kwarg.arg}")

        decorators = [cls._node_to_str(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)

        symbol_id = f"{rel_path}:{class_name}.{node.name}" if is_method else f"{rel_path}:{node.name}"

        return {
            "id": symbol_id,
            "name": node.name,
            "file": rel_path,
            "class_name": class_name,
            "language": "Python",
            "is_method": is_method,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "args": args_list,
            "decorators": decorators,
            "docstring": docstring,
            "line_start": node.lineno,
            "line_end": getattr(node, "end_lineno", node.lineno),
        }

    @classmethod
    def _is_main_block(cls, node: ast.If) -> bool:
        """Check if an If node is: if __name__ == '__main__':"""
        test = node.test
        if isinstance(test, ast.Compare):
            if isinstance(test.left, ast.Name) and test.left.id == "__name__":
                for comp in test.comparators:
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        return True
                    elif isinstance(comp, ast.Str) and comp.s == "__main__":
                        return True
        return False

    @classmethod
    def _node_to_str(cls, node: Any) -> str:
        """Format an AST node into a readable string."""
        if hasattr(ast, "unparse"):
            try:
                return ast.unparse(node)
            except Exception:
                pass
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{cls._node_to_str(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return f"{cls._node_to_str(node.func)}()"
        elif isinstance(node, ast.Constant):
            return repr(node.value)
        return type(node).__name__


class JavaAstExtractor:
    """Extracts structural AST knowledge from Java source files using javalang."""

    @classmethod
    def extract(cls, code: str, rel_path: str) -> Dict[str, Any]:
        """
        Parse Java source code using javalang.
        Returns extracted classes, methods, imports, packages, entry points, and relationships.
        """
        classes = []
        functions = []  # Java does not have top-level functions, all methods belong to classes
        methods = []
        imports = []
        entry_points = []
        relationships = []

        if not JAVALANG_AVAILABLE:
            logger.debug("javalang not installed; skipping deep Java AST parsing")
            return cls._fallback_java_extract(code, rel_path)

        try:
            tree = javalang.parse.parse(code)
        except Exception as err:
            logger.debug(f"Could not parse Java AST for {rel_path}: {err}. Using regex fallback.")
            return cls._fallback_java_extract(code, rel_path)

        pkg_name = tree.package.name if tree.package else ""

        # 1. Imports
        if tree.imports:
            for imp in tree.imports:
                pkg_root = imp.path.split(".")[0]
                is_std = pkg_root in {"java", "javax"}
                imports.append({
                    "file": rel_path,
                    "module": imp.path,
                    "root_module": pkg_root,
                    "imported_name": imp.path.split(".")[-1],
                    "is_static": bool(getattr(imp, "static", False)),
                    "is_wildcard": bool(getattr(imp, "wildcard", False)),
                    "is_standard_library": is_std,
                    "is_external": not is_std,
                })
                relationships.append({
                    "source": rel_path,
                    "relation": "imports",
                    "target": imp.path,
                    "source_type": "file",
                    "target_type": "package",
                })

        # 2. Type Declarations (Classes, Interfaces, Enums)
        if tree.types:
            for type_decl in tree.types:
                cls_name = getattr(type_decl, "name", "AnonymousClass")
                superclass = type_decl.extends.name if getattr(type_decl, "extends", None) else None
                raw_implements = getattr(type_decl, "implements", None) or []
                interfaces = [i.name for i in raw_implements if getattr(i, "name", None)]
                raw_modifiers = getattr(type_decl, "modifiers", None) or []
                modifiers = list(raw_modifiers)

                cls_type = "class"
                if isinstance(type_decl, javalang.tree.InterfaceDeclaration):
                    cls_type = "interface"
                elif isinstance(type_decl, javalang.tree.EnumDeclaration):
                    cls_type = "enum"

                # Relationships: Inheritance & Implements
                if superclass:
                    relationships.append({
                        "source": cls_name,
                        "relation": "inherits_from",
                        "target": superclass,
                        "source_type": "class",
                        "target_type": "class",
                    })

                for iface in interfaces:
                    relationships.append({
                        "source": cls_name,
                        "relation": "implements",
                        "target": iface,
                        "source_type": "class",
                        "target_type": "interface",
                    })

                relationships.append({
                    "source": rel_path,
                    "relation": "defines",
                    "target": cls_name,
                    "source_type": "file",
                    "target_type": "class",
                })

                # Methods inside class
                class_method_names = []
                raw_methods = getattr(type_decl, "methods", None) or []
                for m in raw_methods:
                    m_name = getattr(m, "name", "method")
                    class_method_names.append(m_name)
                    params = []
                    raw_params = getattr(m, "parameters", None) or []
                    for p in raw_params:
                        p_type = getattr(getattr(p, "type", None), "name", "Object")
                        params.append(f"{p_type} {p.name}")

                    m_modifiers = list(getattr(m, "modifiers", None) or [])
                    ret_type = getattr(getattr(m, "return_type", None), "name", "void")

                    method_item = {
                        "id": f"{rel_path}:{cls_name}.{m_name}",
                        "name": m_name,
                        "file": rel_path,
                        "class_name": cls_name,
                        "language": "Java",
                        "is_method": True,
                        "return_type": ret_type,
                        "args": params,
                        "modifiers": m_modifiers,
                        "line_start": getattr(getattr(m, "position", None), "line", 0),
                    }
                    methods.append(method_item)

                    relationships.append({
                        "source": cls_name,
                        "relation": "contains_method",
                        "target": m_name,
                        "source_type": "class",
                        "target_type": "method",
                    })

                    # Check for main entry point: public static void main(String[] args)
                    if m_name == "main" and "public" in m_modifiers and "static" in m_modifiers:
                        entry_points.append({
                            "file": rel_path,
                            "type": "main_method",
                            "symbol": f"{cls_name}.main",
                            "line": getattr(getattr(m, "position", None), "line", 0),
                        })

                # Extract fields if available
                fields = []
                for f in getattr(type_decl, "fields", []):
                    f_type = getattr(getattr(f, "type", None), "name", "Object")
                    for d in getattr(f, "declarators", []):
                        fields.append(f"{f_type} {d.name}")

                classes.append({
                    "id": f"{rel_path}:{cls_name}",
                    "name": cls_name,
                    "file": rel_path,
                    "language": "Java",
                    "class_type": cls_type,
                    "package": pkg_name,
                    "bases": [superclass] if superclass else [],
                    "interfaces": interfaces,
                    "modifiers": modifiers,
                    "fields_count": len(fields),
                    "methods_count": len(class_method_names),
                    "methods": class_method_names,
                    "line_start": getattr(getattr(type_decl, "position", None), "line", 0),
                })

        return {
            "classes": classes,
            "functions": functions,
            "methods": methods,
            "imports": imports,
            "entry_points": entry_points,
            "relationships": relationships,
        }

    @classmethod
    def _fallback_java_extract(cls, code: str, rel_path: str) -> Dict[str, Any]:
        """Regex fallback for Java when javalang cannot parse or fails on newer syntax."""
        classes = []
        methods = []
        imports = []
        entry_points = []
        relationships = []

        # Extract package
        pkg_match = re.search(r"^\s*package\s+([\w.]+);", code, re.MULTILINE)
        pkg_name = pkg_match.group(1) if pkg_match else ""

        # Extract imports
        for m in re.finditer(r"^\s*import\s+(static\s+)?([\w.*]+);", code, re.MULTILINE):
            imp_path = m.group(2)
            pkg_root = imp_path.split(".")[0]
            is_std = pkg_root in {"java", "javax"}
            imports.append({
                "file": rel_path,
                "module": imp_path,
                "root_module": pkg_root,
                "imported_name": imp_path.split(".")[-1],
                "is_standard_library": is_std,
                "is_external": not is_std,
            })

        # Extract classes
        class_regex = r"(?:public\s+|protected\s+|private\s+|abstract\s+)*class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w\s,]+))?"
        for m in re.finditer(class_regex, code):
            cls_name = m.group(1)
            superclass = m.group(2)
            interfaces = [i.strip() for i in m.group(3).split(",")] if m.group(3) else []

            classes.append({
                "id": f"{rel_path}:{cls_name}",
                "name": cls_name,
                "file": rel_path,
                "language": "Java",
                "package": pkg_name,
                "bases": [superclass] if superclass else [],
                "interfaces": interfaces,
                "methods_count": 0,
                "methods": [],
            })

            if superclass:
                relationships.append({
                    "source": cls_name,
                    "relation": "inherits_from",
                    "target": superclass,
                    "source_type": "class",
                    "target_type": "class",
                })

        # Check for main entry point
        if "public static void main" in code:
            entry_points.append({
                "file": rel_path,
                "type": "main_method",
                "symbol": "main",
            })

        return {
            "classes": classes,
            "functions": [],
            "methods": methods,
            "imports": imports,
            "entry_points": entry_points,
            "relationships": relationships,
        }


class JavaScriptStructuralExtractor:
    """Lightweight static extractor for JavaScript / TypeScript files."""

    @classmethod
    def extract(cls, code: str, rel_path: str) -> Dict[str, Any]:
        """Extract classes, functions, and imports from JS/TS files statically."""
        classes = []
        functions = []
        methods = []
        imports = []
        entry_points = []
        relationships = []

        is_ts = rel_path.endswith((".ts", ".tsx"))
        lang = "TypeScript" if is_ts else "JavaScript"

        # 1. Imports (import ... from 'package' or require('package'))
        for m in re.finditer(r"(?:import\s+(?:[\w*\s{},]+)\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))", code):
            pkg = m.group(1) or m.group(2)
            is_relative = pkg.startswith((".", "/"))
            imports.append({
                "file": rel_path,
                "module": pkg,
                "root_module": pkg.split("/")[0] if not is_relative else rel_path,
                "is_standard_library": pkg in {"fs", "path", "http", "https", "os", "crypto", "util", "events"},
                "is_external": not is_relative,
                "is_relative": is_relative,
            })

        # 2. ES6 Classes
        for m in re.finditer(r"(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?", code):
            c_name = m.group(1)
            base = m.group(2)
            classes.append({
                "id": f"{rel_path}:{c_name}",
                "name": c_name,
                "file": rel_path,
                "language": lang,
                "bases": [base] if base else [],
                "methods_count": 0,
                "methods": [],
            })
            if base:
                relationships.append({
                    "source": c_name,
                    "relation": "inherits_from",
                    "target": base,
                    "source_type": "class",
                    "target_type": "class",
                })

        # 3. Functions
        for m in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", code):
            f_name = m.group(1)
            raw_args = m.group(2).strip()
            args = [a.strip().split(":")[0].split("=")[0] for a in raw_args.split(",") if a.strip()]
            functions.append({
                "id": f"{rel_path}:{f_name}",
                "name": f_name,
                "file": rel_path,
                "language": lang,
                "args": args,
            })

        return {
            "classes": classes,
            "functions": functions,
            "methods": methods,
            "imports": imports,
            "entry_points": entry_points,
            "relationships": relationships,
        }


class DeepCodeAnalysisService:
    """
    Orchestrates deep static AST analysis across the entire repository.
    Generates a structured knowledge object with entities, dependencies, and relationships.
    """

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    REPOSITORIES_DIR = DATA_DIR / "repositories"
    ANALYSIS_DIR = DATA_DIR / "analysis"

    # Ignored directories during AST scanning
    IGNORED_DIRS: Set[str] = {
        ".git", ".github", "node_modules", "venv", ".venv", "env", ".env",
        "__pycache__", "dist", "build", "target", "bin", "obj", ".idea", ".vscode",
    }

    # Max file size to parse (1 MB) to prevent memory blowouts on bundled files
    MAX_PARSE_SIZE_BYTES = 1024 * 1024

    @classmethod
    def get_knowledge_file_path(cls, owner: str, name: str) -> Path:
        """Return path to saved knowledge JSON."""
        cls.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        return cls.ANALYSIS_DIR / f"{owner}_{name}_knowledge.json"

    @classmethod
    def load_cached_knowledge(cls, owner: str, name: str) -> Optional[Dict[str, Any]]:
        """Load and return cached knowledge JSON if available."""
        path = cls.get_knowledge_file_path(owner, name)
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["is_cached"] = True
                    return data
            except Exception as ex:
                logger.warning(f"Error loading cached knowledge from {path}: {ex}")
        return None

    @classmethod
    def analyze_codebase(
        cls,
        owner: str,
        name: str,
        repo_path: Optional[Path] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Perform deep static AST analysis on the acquired repository.

        Extracts:
        - Classes (name, bases, methods, docstring, line numbers)
        - Functions (name, args, decorators, line numbers)
        - Methods (name, class association, args, line numbers)
        - Imports (modules, standard library vs third party)
        - Dependencies (consolidated list of external libraries)
        - Entry points (main, CLI, __main__)
        - Relationships (inheritance, calls, defines, imports)
        - Full Statistics

        Stores result in data/analysis/{owner}_{name}_knowledge.json.
        """
        # 1. Check Cache
        if not force_refresh:
            cached = cls.load_cached_knowledge(owner, name)
            if cached:
                return {
                    "success": True,
                    "is_cached": True,
                    "message": f"Retrieved cached knowledge graph for {owner}/{name}",
                    **cached,
                }

        # 2. Resolve Repository Directory
        if repo_path and repo_path.is_dir():
            target_path = repo_path
        else:
            target_path = cls.REPOSITORIES_DIR / f"{owner}_{name}"

        if not target_path.is_dir():
            return {
                "success": False,
                "error": f"Repository directory not found at {target_path}. Run Phase 5 acquisition first.",
                "repository": {"owner": owner, "name": name, "full_name": f"{owner}/{name}"},
                "classes": [],
                "functions": [],
                "methods": [],
                "imports": [],
                "dependencies": [],
                "entry_points": [],
                "relationships": [],
                "statistics": {},
            }

        all_classes: List[Dict[str, Any]] = []
        all_functions: List[Dict[str, Any]] = []
        all_methods: List[Dict[str, Any]] = []
        all_imports: List[Dict[str, Any]] = []
        all_entry_points: List[Dict[str, Any]] = []
        all_relationships: List[Dict[str, Any]] = []
        analyzed_files: List[Dict[str, Any]] = []
        directories_set: Set[str] = set()

        total_files = 0
        source_files = 0

        # 3. Walk Repository Files Statically
        for root, dirs, files in os.walk(target_path):
            # Prune ignored directories in-place
            dirs[:] = [
                d for d in dirs
                if d.lower() not in cls.IGNORED_DIRS and not d.startswith(".")
            ]

            rel_dir = os.path.relpath(root, target_path).replace("\\", "/")
            if rel_dir != ".":
                directories_set.add(rel_dir)

            for file_name in files:
                total_files += 1
                abs_path = Path(root) / file_name
                rel_file_path = os.path.relpath(abs_path, target_path).replace("\\", "/")

                # Skip oversized files
                try:
                    size_bytes = abs_path.stat().st_size
                except Exception:
                    size_bytes = 0

                if size_bytes > cls.MAX_PARSE_SIZE_BYTES:
                    continue

                ext = os.path.splitext(file_name)[1].lower()

                # Dispatch AST parser according to language
                extracted: Optional[Dict[str, Any]] = None

                if ext in {".py", ".pyw"}:
                    source_files += 1
                    try:
                        code = abs_path.read_text(encoding="utf-8", errors="replace")
                        extracted = PythonAstExtractor.extract(code, rel_file_path)
                    except Exception as ex:
                        logger.debug(f"Failed to read/parse {rel_file_path}: {ex}")

                elif ext == ".java":
                    source_files += 1
                    try:
                        code = abs_path.read_text(encoding="utf-8", errors="replace")
                        extracted = JavaAstExtractor.extract(code, rel_file_path)
                    except Exception as ex:
                        logger.debug(f"Failed to read/parse {rel_file_path}: {ex}")

                elif ext in {".js", ".jsx", ".ts", ".tsx"}:
                    source_files += 1
                    try:
                        code = abs_path.read_text(encoding="utf-8", errors="replace")
                        extracted = JavaScriptStructuralExtractor.extract(code, rel_file_path)
                    except Exception as ex:
                        logger.debug(f"Failed to read/parse {rel_file_path}: {ex}")

                if extracted:
                    c_list = extracted.get("classes", [])
                    f_list = extracted.get("functions", [])
                    m_list = extracted.get("methods", [])
                    i_list = extracted.get("imports", [])
                    e_list = extracted.get("entry_points", [])
                    r_list = extracted.get("relationships", [])

                    all_classes.extend(c_list)
                    all_functions.extend(f_list)
                    all_methods.extend(m_list)
                    all_imports.extend(i_list)
                    all_entry_points.extend(e_list)
                    all_relationships.extend(r_list)

                    analyzed_files.append({
                        "path": rel_file_path,
                        "name": file_name,
                        "extension": ext,
                        "classes_count": len(c_list),
                        "functions_count": len(f_list),
                        "methods_count": len(m_list),
                        "imports_count": len(i_list),
                    })

        # 4. Consolidate Dependencies
        dep_map: Dict[str, Dict[str, Any]] = {}
        for imp in all_imports:
            root_mod = imp.get("root_module")
            if not root_mod or imp.get("is_relative"):
                continue

            # Skip self-references to repository name
            if root_mod.lower() in {name.lower(), owner.lower()}:
                continue

            if root_mod not in dep_map:
                dep_map[root_mod] = {
                    "name": root_mod,
                    "is_standard_library": imp.get("is_standard_library", False),
                    "occurrences": 0,
                    "files": set(),
                }
            dep_map[root_mod]["occurrences"] += 1
            dep_map[root_mod]["files"].add(imp["file"])

        consolidated_deps = []
        for dep in dep_map.values():
            dep["files_count"] = len(dep["files"])
            dep["files"] = sorted(list(dep["files"]))[:10]  # Cap to top 10 files
            consolidated_deps.append(dep)

        # Sort dependencies by occurrence count descending
        consolidated_deps.sort(key=lambda x: (not x["is_standard_library"], x["occurrences"]), reverse=True)

        external_deps = [d for d in consolidated_deps if not d["is_standard_library"]]

        # 5. Statistics Calculation
        statistics = {
            "total_files": total_files,
            "source_files": source_files,
            "classes_count": len(all_classes),
            "functions_count": len(all_functions),
            "methods_count": len(all_methods),
            "imports_count": len(all_imports),
            "external_dependencies_count": len(external_deps),
            "total_dependencies_count": len(consolidated_deps),
            "entry_points_count": len(all_entry_points),
            "relationships_count": len(all_relationships),
        }

        # 6. Assemble Knowledge Object
        knowledge_object = {
            "repository": {
                "owner": owner,
                "name": name,
                "full_name": f"{owner}/{name}",
                "url": f"https://github.com/{owner}/{name}",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            },
            "directories": sorted(list(directories_set)),
            "files": analyzed_files,
            "classes": all_classes,
            "functions": all_functions,
            "methods": all_methods,
            "imports": all_imports[:500],  # Cap imports preview for size
            "dependencies": consolidated_deps,
            "entry_points": all_entry_points,
            "relationships": all_relationships,
            "statistics": statistics,
        }

        # 7. Persist Knowledge Object to disk
        try:
            k_file = cls.get_knowledge_file_path(owner, name)
            with open(k_file, "w", encoding="utf-8") as f:
                json.dump(knowledge_object, f, indent=2)
            logger.info(f"Persisted Phase 6 knowledge graph to {k_file}")
        except Exception as save_err:
            logger.warning(f"Could not persist knowledge file: {save_err}")

        return {
            "success": True,
            "is_cached": False,
            "message": f"Successfully performed deep AST code analysis on {owner}/{name}",
            **knowledge_object,
        }
