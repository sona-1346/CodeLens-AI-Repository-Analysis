"""
Whole Repository Architecture Explorer Service for CodeLens AI (Phase 8).

Consumes the centralized Shared Repository Knowledge (Phase 7) and Semantic Code Graph.
Generates:
- Multi-level hierarchical architecture (Repository -> Directories -> Files -> Classes -> Methods/Functions)
- Entity search index
- Internal vs External dependency analysis
- Dependency cycle detection
- Important / Highly connected components with explainable metrics
- Deterministic architecture summary dossier
"""

from datetime import datetime, timezone
import itertools
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from models.knowledge import SharedRepositoryKnowledge
from services.graph_service import SemanticCodeGraphService
from services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class ArchitectureService:
    """
    Constructs, caches, and provides the Whole Repository Architecture representation.
    """

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    ARCHITECTURE_DIR = DATA_DIR / "architecture"

    @classmethod
    def get_architecture_file_path(cls, owner: str, name: str) -> Path:
        """Return the path to the cached architecture JSON."""
        cls.ARCHITECTURE_DIR.mkdir(parents=True, exist_ok=True)
        return cls.ARCHITECTURE_DIR / f"{owner}_{name}_architecture.json"

    @classmethod
    def _sanitize_flows(cls, flows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sanitize flows to ensure test suites verify core code rather than core depending on tests."""
        sanitized = []
        for fl in flows:
            s_name = fl.get("source", "")
            t_name = fl.get("target", "")
            is_test_s = "test" in s_name.lower()
            is_test_t = "test" in t_name.lower()
            if is_test_t and not is_test_s:
                fl_copy = dict(fl)
                fl_copy["source"] = t_name
                fl_copy["target"] = s_name
                fl_copy["flow_type"] = "verification"
                fl_copy["flow_label"] = f"{t_name} -> {s_name} (verifies/exercises)"
                fl_copy["sample_connection"] = "Test suite exercises and verifies core production modules"
                fl_copy["description"] = f"{t_name} exercises and verifies {s_name} (verification relationship, not a production runtime dependency)"
                sanitized.append(fl_copy)
            else:
                sanitized.append(fl)
        return sanitized

    @classmethod
    def load_cached_architecture(cls, owner: str, name: str) -> Optional[Dict[str, Any]]:
        """Load cached architecture JSON if available."""
        path = cls.get_architecture_file_path(owner, name)
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["is_cached"] = True
                    if "component_flows" in data:
                        data["component_flows"] = cls._sanitize_flows(data["component_flows"])
                    if "levels" in data and "component_flows" in data["levels"]:
                        data["levels"]["component_flows"] = cls._sanitize_flows(data["levels"]["component_flows"])
                    return data
            except Exception as ex:
                logger.warning(f"Failed to load cached architecture from {path}: {ex}")
        return None

    @classmethod
    def get_architecture_data(
        cls,
        owner: str,
        name: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Main public interface:
        Retrieves or builds the complete multi-level architecture explorer model.
        """
        # 1. Check Cache
        if not force_refresh:
            cached = cls.load_cached_architecture(owner, name)
            if cached:
                return {
                    "success": True,
                    "is_cached": True,
                    "message": f"Loaded cached Architecture for {owner}/{name}",
                    **cached,
                }

        # 2. Get Shared Knowledge & Graph from Phase 7 (No re-parsing)
        knowledge = KnowledgeService.get_shared_knowledge(owner, name)
        graph_res = SemanticCodeGraphService.get_or_create_graph(owner, name, force_refresh=force_refresh)
        graph_data = graph_res.get("graph", {})

        # Reconstruct NetworkX DiGraph for graph algorithms
        G, _ = SemanticCodeGraphService.build_graph(knowledge)

        # 3. Dependency Analysis (Internal vs External)
        dependency_analysis = cls._analyze_dependencies(knowledge)

        # 4. Build Multi-Level Hierarchy & Major Subsystems
        levels = cls._build_architecture_levels(knowledge, dependency_analysis=dependency_analysis)

        # 5. Dependency Cycle Detection
        cycles = cls._detect_dependency_cycles(knowledge)

        # 6. Highly Connected Components (Centrality & Degree)
        connected_components = cls._identify_highly_connected(G, knowledge)

        # 7. Search Index
        search_index = cls._build_search_index(knowledge)

        # 8. Entry Points
        entry_points = cls._format_entry_points(knowledge)

        # 9. Deterministic Architecture Summary
        summary = cls._generate_architecture_summary(
            knowledge=knowledge,
            levels=levels,
            cycles=cycles,
            connected_components=connected_components,
            dependency_analysis=dependency_analysis,
        )

        architecture_payload = {
            "repository": knowledge.repository.to_dict(),
            "statistics": {
                "total_files": len(knowledge.files),
                "total_directories": len(knowledge.directories),
                "total_classes": len(knowledge.classes),
                "total_functions": len(knowledge.functions),
                "total_methods": len(knowledge.methods),
                "total_dependencies": len(knowledge.dependencies),
                "entry_points_count": len(knowledge.entry_points),
                "cycles_count": len(cycles),
                "graph_nodes": G.number_of_nodes(),
                "graph_edges": G.number_of_edges(),
            },
            "levels": levels,
            "major_subsystems": levels.get("major_subsystems", []),
            "subsystems": levels.get("major_subsystems", []),
            "component_flows": levels.get("component_flows", []),
            "modules_tree": levels.get("modules_tree", {}),
            "dependency_analysis": dependency_analysis,
            "cycles": cycles,
            "cycles_detected": len(cycles) > 0,
            "is_acyclic": len(cycles) == 0,
            "highly_connected": connected_components,
            "highly_connected_components": connected_components,
            "search_index": search_index,
            "entry_points": entry_points,
            "summary": summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # 10. Persist to data/architecture/
        try:
            out_file = cls.get_architecture_file_path(owner, name)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(architecture_payload, f, indent=2)
            logger.info(f"Persisted Phase 8 Architecture model to {out_file}")
        except Exception as err:
            logger.warning(f"Could not persist architecture model: {err}")

        return {
            "success": True,
            "is_cached": False,
            "message": f"Successfully generated Architecture Explorer model for {owner}/{name}",
            **architecture_payload,
        }

    @classmethod
    def _build_architecture_levels(
        cls,
        knowledge: SharedRepositoryKnowledge,
        dependency_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Construct structured data for the 4 exploration levels:
        Level 1: Repository Overview (Repo -> Major dirs -> Root files)
        Level 2: Directory breakdown (Dir -> Files -> Class/Fn counts)
        Level 3: File breakdown (File -> Classes -> Functions -> Methods -> Imports)
        Level 4: Entity details (Classes/Functions/Methods with relationships)
        """
        # Map directory -> files
        dir_files_map: Dict[str, List[Dict[str, Any]]] = {}
        # Root-level files
        root_files: List[Dict[str, Any]] = []

        # Map file -> classes, functions, methods, imports
        file_classes_map: Dict[str, List[Dict[str, Any]]] = {}
        file_functions_map: Dict[str, List[Dict[str, Any]]] = {}
        file_methods_map: Dict[str, List[Dict[str, Any]]] = {}
        file_imports_map: Dict[str, List[Dict[str, Any]]] = {}

        for c in knowledge.classes:
            f_norm = c.file.replace("\\", "/").strip("/")
            file_classes_map.setdefault(f_norm, []).append(c.to_dict())

        for fn in knowledge.functions:
            f_norm = fn.file.replace("\\", "/").strip("/")
            file_functions_map.setdefault(f_norm, []).append(fn.to_dict())

        for m in knowledge.methods:
            f_norm = m.file.replace("\\", "/").strip("/")
            file_methods_map.setdefault(f_norm, []).append(m.to_dict())

        for imp in knowledge.imports:
            f_norm = imp.source_file.replace("\\", "/").strip("/")
            file_imports_map.setdefault(f_norm, []).append(imp.to_dict())

        for f in knowledge.files:
            f_path = f.path.replace("\\", "/").strip("/")
            file_info_dict = {
                "id": f"file:{f_path}",
                "name": f.name,
                "path": f_path,
                "extension": f.extension,
                "language": f.language,
                "size": f.size,
                "classes_count": len(file_classes_map.get(f_path, [])),
                "functions_count": len(file_functions_map.get(f_path, [])),
                "methods_count": len(file_methods_map.get(f_path, [])),
                "imports_count": len(file_imports_map.get(f_path, [])),
            }

            if "/" in f_path:
                parent_dir = f_path.rsplit("/", 1)[0]
                dir_files_map.setdefault(parent_dir, []).append(file_info_dict)
            else:
                root_files.append(file_info_dict)

        # 1. Level 1: Major Directories & Root Files
        level_1_dirs = []
        top_dirs_set = set()
        for d in knowledge.directories:
            d_path = d.path.replace("\\", "/").strip("/")
            if not d_path or d_path == ".":
                continue
            # Get top level segment
            top_seg = d_path.split("/")[0]
            top_dirs_set.add(top_seg)

        for top_dir in sorted(list(top_dirs_set)):
            # Aggregate files in this top-level directory branch
            contained_files = []
            for d_path, f_list in dir_files_map.items():
                if d_path == top_dir or d_path.startswith(f"{top_dir}/"):
                    contained_files.extend(f_list)

            category = cls._categorize_component(top_dir, contained_files)

            level_1_dirs.append({
                "id": f"directory:{top_dir}",
                "name": top_dir,
                "path": top_dir,
                "category": category,
                "files_count": len(contained_files),
                "classes_count": sum(f["classes_count"] for f in contained_files),
                "functions_count": sum(f["functions_count"] for f in contained_files),
            })

        # 2. Level 2: Directory breakdown
        level_2_directories: Dict[str, Any] = {}
        for d in knowledge.directories:
            d_path = d.path.replace("\\", "/").strip("/")
            if not d_path or d_path == ".":
                continue
            f_list = dir_files_map.get(d_path, [])
            category = cls._categorize_component(d.name, f_list)
            level_2_directories[d_path] = {
                "id": f"directory:{d_path}",
                "name": d.name,
                "path": d_path,
                "parent": d.parent,
                "category": category,
                "files": f_list,
                "files_count": len(f_list),
            }

        # 3. Level 3: Files with detailed symbols
        level_3_files: Dict[str, Any] = {}
        for f in knowledge.files:
            f_path = f.path.replace("\\", "/").strip("/")
            level_3_files[f_path] = {
                "id": f"file:{f_path}",
                "name": f.name,
                "path": f_path,
                "language": f.language,
                "size": f.size,
                "classes": file_classes_map.get(f_path, []),
                "functions": file_functions_map.get(f_path, []),
                "methods": file_methods_map.get(f_path, []),
                "imports": file_imports_map.get(f_path, []),
            }

        # 4. Level 4: Entity relationships
        level_4_nodes = []
        for c in knowledge.classes:
            f_norm = c.file.replace("\\", "/").strip("/")
            level_4_nodes.append({
                "id": f"class:{c.name}",
                "name": c.name,
                "label": c.name,
                "type": "class",
                "file": f_norm,
                "docstring": c.docstring,
            })
        for fn in knowledge.functions:
            f_norm = fn.file.replace("\\", "/").strip("/")
            level_4_nodes.append({
                "id": f"function:{fn.name}",
                "name": fn.name,
                "label": f"{fn.name}()",
                "type": "function",
                "file": f_norm,
                "docstring": fn.docstring,
            })

        level_4_edges = []
        for r in knowledge.relationships:
            level_4_edges.append({
                "source": r.source,
                "target": r.target,
                "type": r.relation,
                "source_type": r.source_type,
                "target_type": r.target_type,
            })

        # 5. Expandable Hierarchical Modules Tree
        modules_tree = cls._build_modules_tree(
            repo_name=knowledge.repository.name,
            knowledge=knowledge,
            dir_files_map=dir_files_map,
            root_files=root_files,
            file_classes_map=file_classes_map,
            file_functions_map=file_functions_map,
            file_methods_map=file_methods_map,
        )

        # 6. Build Clean High-Level Subsystems with Key Files and Flows (5-10 components)
        major_subsystems, component_flows = cls._build_major_subsystems(
            knowledge=knowledge,
            dir_files_map=dir_files_map,
            root_files=root_files,
            level_1_dirs=level_1_dirs,
            dependency_analysis=dependency_analysis,
            file_classes_map=file_classes_map,
            file_functions_map=file_functions_map,
            file_imports_map=file_imports_map,
        )

        return {
            "level_1": {
                "repository": knowledge.repository.name,
                "root": {
                    "id": f"repo:{knowledge.repository.name}",
                    "name": knowledge.repository.name,
                    "type": "repo",
                },
                "major_directories": level_1_dirs,
                "major_subsystems": major_subsystems,
                "subsystems": major_subsystems,
                "component_flows": component_flows,
                "root_files": root_files,
            },
            "level_2": {
                "directories": list(level_2_directories.values()),
            },
            "level_3": {
                "files": list(level_3_files.values()),
            },
            "level_4": {
                "nodes": level_4_nodes,
                "edges": level_4_edges,
            },
            "major_subsystems": major_subsystems,
            "subsystems": major_subsystems,
            "component_flows": component_flows,
            "level_2_directories": level_2_directories,
            "level_3_files": level_3_files,
            "modules_tree": modules_tree,
        }

    @classmethod
    def _build_major_subsystems(
        cls,
        knowledge: SharedRepositoryKnowledge,
        dir_files_map: Dict[str, List[Dict[str, Any]]],
        root_files: List[Dict[str, Any]],
        level_1_dirs: List[Dict[str, Any]],
        dependency_analysis: Optional[Dict[str, Any]] = None,
        file_classes_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        file_functions_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        file_imports_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Synthesize clean, human-readable high-level architectural subsystems (5-10 components)
        from actual repository evidence.
        Each subsystem includes key files, contained modules, classes, functions, and flows.
        """
        entry_point_files = {e.file.replace("\\", "/").strip("/") for e in knowledge.entry_points}
        classes_map = file_classes_map or {}
        functions_map = file_functions_map or {}
        imports_map = file_imports_map or {}

        def score_file(f_item: Dict[str, Any]) -> int:
            p = f_item.get("path", "")
            return (
                f_item.get("classes_count", 0) * 4
                + f_item.get("functions_count", 0) * 2
                + f_item.get("methods_count", 0)
                + (15 if p in entry_point_files else 0)
                + min(f_item.get("imports_count", 0), 5)
                + (2 if any(k in f_item.get("name", "").lower() for k in ["api", "core", "client", "app", "session", "model", "server"]) else 0)
            )

        def format_key_files(files_subset: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            sorted_f = sorted(files_subset, key=lambda f: (score_file(f), f.get("size") or 0), reverse=True)
            result = []
            for f in sorted_f[:5]:
                c_cnt = f.get("classes_count", 0)
                fn_cnt = f.get("functions_count", 0)
                badge = f"{c_cnt} classes, {fn_cnt} fns" if (c_cnt or fn_cnt) else (f.get("language") or "source")
                fp = f.get("path", "")
                is_ep = fp in entry_point_files
                why_imp = "Application entry point" if is_ep else f"High symbol density ({c_cnt} classes, {fn_cnt} functions)"
                result.append({
                    "id": f.get("id") or f"file:{fp}",
                    "name": f.get("name"),
                    "path": fp,
                    "extension": f.get("extension", ""),
                    "language": f.get("language", ""),
                    "size": f.get("size", 0),
                    "classes_count": c_cnt,
                    "functions_count": fn_cnt,
                    "methods_count": f.get("methods_count", 0),
                    "is_entry_point": is_ep,
                    "badge": badge,
                    "role": "Entry Point" if is_ep else ("Core Module" if c_cnt > 0 else "Utility"),
                    "why_important": why_imp,
                })
            return result

        def extract_component_symbols(files_subset: List[Dict[str, Any]]) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
            # Folders / submodules
            sub_folders = sorted(list({f.get("path", "").rsplit("/", 1)[0] for f in files_subset if "/" in f.get("path", "")}))
            
            # Classes
            sub_classes = []
            seen_cls = set()
            for f in files_subset:
                fp = f.get("path", "")
                for c in classes_map.get(fp, []):
                    cname = c.get("name")
                    if cname and cname not in seen_cls:
                        seen_cls.add(cname)
                        methods = c.get("methods", [])
                        sub_classes.append({
                            "name": cname,
                            "file": fp,
                            "docstring": (c.get("docstring") or "")[:120],
                            "methods_count": len(methods) if isinstance(methods, list) else 0,
                        })
            
            # Functions
            sub_functions = []
            seen_fn = set()
            for f in files_subset:
                fp = f.get("path", "")
                for fn in functions_map.get(fp, []):
                    fnname = fn.get("name")
                    if fnname and fnname not in seen_fn:
                        seen_fn.add(fnname)
                        sub_functions.append({
                            "name": fnname,
                            "file": fp,
                            "parameters": fn.get("parameters", []),
                            "is_async": fn.get("is_async", False),
                        })
            
            # Dependencies
            sub_deps_set = set()
            for f in files_subset:
                fp = f.get("path", "")
                for imp in imports_map.get(fp, []):
                    mod = imp.get("imported_module", "").split(".")[0]
                    if mod and mod not in {"__future__", "."}:
                        sub_deps_set.add(mod)
            sub_deps = sorted(list(sub_deps_set))

            return sub_folders, sub_classes[:12], sub_functions[:12], sub_deps[:15]

        subsystems: List[Dict[str, Any]] = []

        # 1. Evaluate major directories
        for d in level_1_dirs:
            d_path = d["path"]
            contained = []
            for dp, flist in dir_files_map.items():
                if dp == d_path or dp.startswith(f"{d_path}/"):
                    contained.extend(flist)

            cat = d.get("category") or cls._categorize_component(d["name"], contained)
            if not cat:
                asset_exts = {".png", ".jpg", ".jpeg", ".svg", ".ai", ".ico", ".gif", ".webp", ".bmp", ".tiff", ".psd"}
                code_exts = {".py", ".java", ".js", ".ts", ".c", ".cpp", ".cs", ".go", ".rs", ".rb", ".php"}
                has_code = any(f.get("extension", "").lower() in code_exts for f in contained)
                if not has_code and contained:
                    cat = "Assets & Media" if any(f.get("extension", "").lower() in asset_exts for f in contained) else "Documentation"
                else:
                    cat = "Source Code"
            name_clean = d["name"]

            # Friendly Subsystem Name and Icon
            icon = "📦"
            priority = 50
            desc = f"Subsystem organizing files within the '{d_path}' directory path."

            role_type = "production"
            if cat == "API Modules" or "api" in name_clean.lower() or "route" in name_clean.lower():
                display_name = f"API & Routing Layer ({name_clean})"
                icon = "🌐"
                priority = 100
                desc = "Handles external request routing, HTTP endpoints, client interfaces, and protocol dispatching."
                role_type = "production"
            elif cat == "Core Modules" or any(k in name_clean.lower() for k in ["core", "engine", "base", "kernel"]):
                display_name = f"Core Logic & Engine ({name_clean})"
                icon = "⚙️"
                priority = 90
                desc = "Implements core domain models, internal state processing, execution engine, and session management."
                role_type = "production"
            elif cat == "Source Code" or name_clean.lower() in ["src", "app", "lib"]:
                display_name = f"Core Application Source ({name_clean})"
                icon = "⚙️"
                priority = 88
                desc = "Primary application source tree housing core functional abstractions and domain routines."
                role_type = "production"
            elif cat == "Utilities" or any(k in name_clean.lower() for k in ["util", "helper", "common", "shared"]):
                display_name = f"Utilities & Helpers ({name_clean})"
                icon = "🛠️"
                priority = 70
                desc = "Provides shared helper functions, formatters, compatibility adapters, and internal utility routines."
                role_type = "production"
            elif cat == "Tests" or "test" in name_clean.lower():
                display_name = f"Automated Test Suite ({name_clean})"
                icon = "🧪"
                priority = 60
                desc = "Automated unit tests, integration test fixtures, mock scenarios, and verification suites."
                role_type = "verification"
            elif cat == "Documentation" or "doc" in name_clean.lower():
                display_name = f"Documentation & Guides ({name_clean})"
                icon = "📚"
                priority = 40
                desc = "Developer guides, architectural specifications, user tutorials, and reference documentation."
                role_type = "supporting"
            elif cat == "Scripts" or "bin" in name_clean.lower():
                display_name = f"Build & Scripts ({name_clean})"
                icon = "🔧"
                priority = 35
                desc = "Automation scripts, CLI runners, and build orchestration tools."
                role_type = "supporting"
            elif cat == "Configuration" or "config" in name_clean.lower():
                display_name = f"Configuration & Settings ({name_clean})"
                icon = "📋"
                priority = 30
                desc = "Project configuration manifests, dependencies specifications, and build metadata."
                role_type = "supporting"
            elif cat in {"Assets & Media", "Project Assets"} or name_clean.lower() in {"ext", "assets", "media", "artwork"}:
                display_name = f"Project Assets ({name_clean})"
                icon = "🎨"
                priority = 25
                desc = "Brand logos, images, vector graphics, and non-executable project media."
                role_type = "supporting"
            else:
                display_name = f"Module Subsystem ({name_clean})"
                icon = "📁"
                priority = 50
                role_type = "production"

            sub_folders, sub_classes, sub_functions, sub_deps = extract_component_symbols(contained)

            subsystems.append({
                "id": f"subsystem:{d_path}",
                "name": display_name,
                "short_name": name_clean,
                "category": cat,
                "role_type": role_type,
                "path": d_path,
                "icon": icon,
                "priority": priority,
                "description": desc,
                "files_count": len(contained),
                "classes_count": sum(f.get("classes_count", 0) for f in contained),
                "functions_count": sum(f.get("functions_count", 0) for f in contained),
                "key_files": format_key_files(contained),
                "submodules": sub_folders,
                "classes": sub_classes,
                "functions": sub_functions,
                "dependencies": sub_deps,
                "inbound_flows": [],
                "outbound_flows": [],
            })

        # 2. Evaluate Root Files as a distinct Subsystem if substantial
        if root_files:
            root_code_files = [f for f in root_files if f.get("classes_count", 0) > 0 or f.get("functions_count", 0) > 0 or f.get("path") in entry_point_files]
            if root_code_files or len(root_files) > 0:
                has_major_root = any(f.get("classes_count", 0) >= 3 for f in root_files)
                sub_folders, sub_classes, sub_functions, sub_deps = extract_component_symbols(root_files)
                subsystems.append({
                    "id": "subsystem:root",
                    "name": "Core Application Module (Root)" if has_major_root else "Entry Points & Root Files",
                    "short_name": "Root Modules",
                    "category": "Core Modules" if has_major_root else "Root Modules",
                    "role_type": "production" if has_major_root else "supporting",
                    "path": "(root)",
                    "icon": "🚀",
                    "priority": 85 if has_major_root else 45,
                    "description": "Top-level application entry points, primary module definitions, and package bootstrap logic.",
                    "files_count": len(root_files),
                    "classes_count": sum(f.get("classes_count", 0) for f in root_files),
                    "functions_count": sum(f.get("functions_count", 0) for f in root_files),
                    "key_files": format_key_files(root_files),
                    "submodules": ["(root)"],
                    "classes": sub_classes,
                    "functions": sub_functions,
                    "dependencies": sub_deps,
                    "inbound_flows": [],
                    "outbound_flows": [],
                })

        # Sort by priority descending and cap at 8 subsystems (5-10 range)
        subsystems.sort(key=lambda s: (s["priority"], s["classes_count"] + s["functions_count"]), reverse=True)
        final_subsystems = subsystems[:8]

        # 3. Inter-component Flows
        # Map directory flows to subsystems
        dir_to_sub = {}
        for sub in final_subsystems:
            p = sub["path"]
            dir_to_sub[p] = sub["name"]

        component_flows: List[Dict[str, Any]] = []
        seen_flows: Set[Tuple[str, str]] = set()

        raw_flows = dependency_analysis.get("aggregated_directory_dependencies", []) if dependency_analysis else []
        for rf in raw_flows:
            s_dir = rf.get("source_directory")
            t_dir = rf.get("target_directory")
            s_sub = dir_to_sub.get(s_dir)
            t_sub = dir_to_sub.get(t_dir)

            if s_sub and t_sub and s_sub != t_sub:
                is_test_s = "test" in s_sub.lower() or (s_dir and "test" in s_dir.lower())
                is_test_t = "test" in t_sub.lower() or (t_dir and "test" in t_dir.lower())
                is_doc_s = "doc" in s_sub.lower() or (s_dir and "doc" in s_dir.lower())
                is_doc_t = "doc" in t_sub.lower() or (t_dir and "doc" in t_dir.lower())

                # Architectural boundary check:
                # Production core NEVER depends on the test suite at runtime.
                # The test suite exercises and verifies the core source code.
                if is_test_s or is_test_t:
                    flow_src = s_sub if is_test_s else t_sub
                    flow_tgt = t_sub if is_test_s else s_sub
                    flow_type = "verification"
                    flow_lbl = f"{flow_src} -> {flow_tgt} (verifies/exercises)"
                    sample_conn = "Test suite exercises and verifies core production modules"
                    desc = f"{flow_src} exercises and verifies {flow_tgt} (verification relationship, not a production runtime dependency)"
                elif is_doc_t and not is_doc_s:
                    flow_src = s_sub
                    flow_tgt = t_sub
                    flow_type = "documentation"
                    flow_lbl = f"{flow_src} -> {flow_tgt} (documented by)"
                    sample_conn = "Documentation references public API and module specifications"
                    desc = f"{flow_tgt} provides documentation and reference guides for {flow_src}"
                else:
                    flow_src = s_sub
                    flow_tgt = t_sub
                    flow_type = "runtime"
                    flow_lbl = f"{s_sub} -> {t_sub}"
                    samples = rf.get("sample_connections", [])
                    sample_conn = samples[0] if samples else f"{s_sub} -> {t_sub}"
                    desc = f"{s_sub} interacts directly with {t_sub}"

                flow_pair = (flow_src, flow_tgt)
                if flow_pair not in seen_flows:
                    seen_flows.add(flow_pair)
                    component_flows.append({
                        "source": flow_src,
                        "target": flow_tgt,
                        "relationship_count": rf.get("relationship_count", 1),
                        "sample_connection": sample_conn,
                        "flow_label": flow_lbl,
                        "flow_type": flow_type,
                        "description": desc,
                    })

        # If few cross-subsystem flows, check internal dependencies
        if len(component_flows) < 2 and dependency_analysis:
            internal_deps = dependency_analysis.get("internal_dependencies", [])
            for idep in internal_deps[:50]:
                s_file = idep.get("source_file", "")
                t_file = idep.get("target_file", "")
                s_part = s_file.split("/")[0] if "/" in s_file else "(root)"
                t_part = t_file.split("/")[0] if "/" in t_file else "(root)"
                s_sub = dir_to_sub.get(s_part)
                t_sub = dir_to_sub.get(t_part)
                if s_sub and t_sub and s_sub != t_sub:
                    is_test_s = "test" in s_sub.lower() or "test" in s_part.lower()
                    is_test_t = "test" in t_sub.lower() or "test" in t_part.lower()
                    is_doc_s = "doc" in s_sub.lower() or "doc" in s_part.lower()
                    is_doc_t = "doc" in t_sub.lower() or "doc" in t_part.lower()

                    if is_test_s or is_test_t:
                        flow_src = s_sub if is_test_s else t_sub
                        flow_tgt = t_sub if is_test_s else s_sub
                        flow_type = "verification"
                        flow_lbl = f"{flow_src} -> {flow_tgt} (verifies/exercises)"
                        sample_conn = f"{s_file} (test fixture) verifies {flow_tgt}"
                        desc = f"{flow_src} exercises and verifies {flow_tgt} (verification relationship, not a production runtime dependency)"
                    elif is_doc_t and not is_doc_s:
                        flow_src = s_sub
                        flow_tgt = t_sub
                        flow_type = "documentation"
                        flow_lbl = f"{flow_src} -> {flow_tgt} (documented by)"
                        sample_conn = f"{t_file} documents {s_file}"
                        desc = f"{flow_tgt} provides documentation for {flow_src}"
                    else:
                        flow_src = s_sub
                        flow_tgt = t_sub
                        flow_type = "runtime"
                        flow_lbl = f"{s_sub} -> {t_sub}"
                        sample_conn = f"{s_file} -> {t_file}"
                        desc = f"{s_sub} interacts with {t_sub}"

                    flow_pair = (flow_src, flow_tgt)
                    if flow_pair not in seen_flows:
                        seen_flows.add(flow_pair)
                        component_flows.append({
                            "source": flow_src,
                            "target": flow_tgt,
                            "relationship_count": 1,
                            "sample_connection": sample_conn,
                            "flow_label": flow_lbl,
                            "flow_type": flow_type,
                            "description": desc,
                        })
                if len(component_flows) >= 8:
                    break

        # Attach directional flows to each component
        for sub in final_subsystems:
            sub["inbound_flows"] = [f for f in component_flows if f["target"] == sub["name"]]
            sub["outbound_flows"] = [f for f in component_flows if f["source"] == sub["name"]]

        return final_subsystems, component_flows

    @classmethod
    def _categorize_component(cls, dir_name: str, files: List[Dict[str, Any]]) -> Optional[str]:
        """
        Identify useful structural categories strictly from actual repository evidence.
        Returns category name or None if uncertain, adhering to the principle:
        'Never pretend that static analysis has discovered an architectural layer when it has only discovered a folder.'
        """
        low = dir_name.lower().strip()
        
        # Test detection
        if low in {"test", "tests", "testing", "spec", "specs"} or any("test" in f["name"].lower() for f in files):
            return "Tests"
        
        # Documentation detection
        if low in {"doc", "docs", "documentation"} or (files and all(f.get("extension", "") in {".md", ".rst", ".txt", ".png", ".jpg", ".svg", ".css", ".html"} for f in files)):
            return "Documentation"

        # Media & Assets detection
        asset_exts = {".png", ".jpg", ".jpeg", ".svg", ".ai", ".ico", ".gif", ".webp", ".bmp", ".tiff", ".psd"}
        if low in {"ext", "assets", "asset", "media", "images", "img", "static", "artwork", "logo", "logos", "icons"}:
            return "Assets & Media"
        if files and all(f.get("extension", "").lower() in asset_exts or f.get("name", "").upper() in {"LICENSE", "NOTICE", "COPYING"} for f in files):
            return "Assets & Media"
            
        # Scripts detection
        if low in {"scripts", "script", "bin", "tools"} or any(f.get("extension", "") in {".sh", ".bat", ".ps1"} for f in files):
            return "Scripts"
            
        # Examples detection
        if low in {"example", "examples", "samples", "sample", "demo", "demos", "tutorial", "tutorials"}:
            return "Examples"
            
        # Utilities detection
        if low in {"util", "utils", "utility", "utilities", "helpers", "helper", "common", "shared"}:
            return "Utilities"
            
        # API Modules detection
        if low in {"api", "routes", "endpoints", "controllers", "rest", "graphql"}:
            return "API Modules"
            
        # Core Modules detection
        if low in {"core", "engine", "kernel", "base"}:
            return "Core Modules"
            
        # Configuration detection
        if low in {"config", "configs", "configuration", "settings", "conf"}:
            return "Configuration"
            
        # Source Code detection (src, lib, app, or directories dominated by code files)
        if low in {"src", "app", "lib", "source", "sources"}:
            return "Source Code"
            
        return None

    @classmethod
    def _build_modules_tree(
        cls,
        repo_name: str,
        knowledge: SharedRepositoryKnowledge,
        dir_files_map: Dict[str, List[Dict[str, Any]]],
        root_files: List[Dict[str, Any]],
        file_classes_map: Dict[str, List[Dict[str, Any]]],
        file_functions_map: Dict[str, List[Dict[str, Any]]],
        file_methods_map: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Build an expandable hierarchical tree data structure:
        Repository -> Directory -> Subdirectory -> File -> Class (with Methods) -> Functions
        """
        def format_file_node(f_dict: Dict[str, Any]) -> Dict[str, Any]:
            f_path = f_dict["path"]
            classes_in_file = file_classes_map.get(f_path, [])
            functions_in_file = file_functions_map.get(f_path, [])
            
            children = []
            for c in classes_in_file:
                c_methods = [
                    {
                        "id": f"method:{f_path}:{c['name']}:{m['name']}",
                        "name": f"{m['name']}()",
                        "type": "method",
                        "path": f_path,
                        "class_name": c["name"],
                        "return_type": m.get("return_type"),
                        "args": m.get("args", []),
                        "line": m.get("line_start"),
                        "children": [],
                    }
                    for m in file_methods_map.get(f_path, [])
                    if m.get("class_name") == c["name"]
                ]
                children.append({
                    "id": f"class:{f_path}:{c['name']}",
                    "name": c["name"],
                    "type": "class",
                    "path": f_path,
                    "bases": c.get("bases", []),
                    "line": c.get("line_start"),
                    "children": c_methods,
                })
            
            for fn in functions_in_file:
                children.append({
                    "id": f"function:{f_path}:{fn['name']}",
                    "name": f"{fn['name']}()",
                    "type": "function",
                    "path": f_path,
                    "args": fn.get("args", []),
                    "line": fn.get("line_start"),
                    "children": [],
                })

            return {
                "id": f"file:{f_path}",
                "name": f_dict["name"],
                "type": "file",
                "path": f_path,
                "language": f_dict.get("language", ""),
                "size": f_dict.get("size", 0),
                "classes_count": len(classes_in_file),
                "functions_count": len(functions_in_file),
                "methods_count": len(file_methods_map.get(f_path, [])),
                "children": children,
            }

        dir_paths = sorted([d.path.replace("\\", "/").strip("/") for d in knowledge.directories if d.path and d.path != "."])
        tree_nodes: Dict[str, Dict[str, Any]] = {}

        for d in knowledge.directories:
            d_path = d.path.replace("\\", "/").strip("/")
            if not d_path or d_path == ".":
                continue
            f_list = dir_files_map.get(d_path, [])
            f_nodes = [format_file_node(f) for f in f_list]
            tree_nodes[d_path] = {
                "id": f"directory:{d_path}",
                "name": d.name or d_path.split("/")[-1],
                "type": "directory",
                "path": d_path,
                "parent": d.parent,
                "children": f_nodes,
            }

        top_level_children = []
        for d_path in dir_paths:
            node = tree_nodes.get(d_path)
            if not node:
                continue
            parent_path = node.get("parent")
            if parent_path and parent_path in tree_nodes:
                tree_nodes[parent_path]["children"].append(node)
            elif "/" in d_path:
                parent_prefix = d_path.rsplit("/", 1)[0]
                if parent_prefix in tree_nodes:
                    tree_nodes[parent_prefix]["children"].append(node)
                else:
                    top_level_children.append(node)
            else:
                top_level_children.append(node)

        for rf in root_files:
            top_level_children.append(format_file_node(rf))

        return {
            "id": f"repo:{repo_name}",
            "name": repo_name,
            "type": "repo",
            "children": top_level_children,
        }

    @classmethod
    def _analyze_dependencies(cls, knowledge: SharedRepositoryKnowledge) -> Dict[str, Any]:
        """
        Categorize internal dependencies (file -> file) and external dependencies (file -> package).
        Calculates aggregated directory-to-directory dependency flows from actual internal imports.
        """
        internal_deps: List[Dict[str, Any]] = []
        external_deps: List[Dict[str, Any]] = []
        stdlib_deps: List[Dict[str, Any]] = []

        all_file_paths = {f.path.replace("\\", "/").strip("/") for f in knowledge.files}
        # Build map of module name candidates (e.g. "bottle" -> "bottle.py")
        mod_to_file = {}
        for fp in all_file_paths:
            base_no_ext = os.path.splitext(fp)[0].replace("/", ".")
            mod_to_file[base_no_ext] = fp
            mod_to_file[os.path.splitext(os.path.basename(fp))[0]] = fp

        seen_internal = set()
        dir_flow_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for imp in knowledge.imports:
            src = imp.source_file.replace("\\", "/").strip("/")
            mod = imp.imported_module

            # Check if this import refers to another file in the project
            target_file = mod_to_file.get(mod) or mod_to_file.get(mod.split(".")[0])
            if target_file and target_file != src:
                pair_key = (src, target_file)
                if pair_key not in seen_internal:
                    seen_internal.add(pair_key)
                    internal_deps.append({
                        "source_file": src,
                        "target_file": target_file,
                        "imported_module": mod,
                        "imported_symbol": imp.imported_symbol,
                        "type": "internal",
                    })

                    # Aggregate directory-to-directory flow
                    src_dir = src.split("/")[0] if "/" in src else "(root)"
                    tgt_dir = target_file.split("/")[0] if "/" in target_file else "(root)"
                    if src_dir != tgt_dir:
                        flow_key = (src_dir, tgt_dir)
                        if flow_key not in dir_flow_map:
                            dir_flow_map[flow_key] = {
                                "source_directory": src_dir,
                                "target_directory": tgt_dir,
                                "relationship_count": 0,
                                "source_files": set(),
                                "target_files": set(),
                                "sample_pairs": [],
                            }
                        entry = dir_flow_map[flow_key]
                        entry["relationship_count"] += 1
                        entry["source_files"].add(src)
                        entry["target_files"].add(target_file)
                        if len(entry["sample_pairs"]) < 6:
                            entry["sample_pairs"].append(f"{src} → {target_file}")
            else:
                if imp.is_standard_library:
                    stdlib_deps.append({
                        "source_file": src,
                        "module": mod,
                        "type": "standard_library",
                    })
                else:
                    external_deps.append({
                        "source_file": src,
                        "package": mod.split(".")[0],
                        "type": "external_third_party",
                    })

        aggregated_directory_flows = []
        for (s_dir, t_dir), info in dir_flow_map.items():
            aggregated_directory_flows.append({
                "source_directory": s_dir,
                "target_directory": t_dir,
                "relationship_count": info["relationship_count"],
                "source_files_count": len(info["source_files"]),
                "target_files_count": len(info["target_files"]),
                "sample_connections": info["sample_pairs"],
            })
        aggregated_directory_flows.sort(key=lambda x: x["relationship_count"], reverse=True)

        return {
            "internal_count": len(internal_deps),
            "external_count": len(knowledge.dependencies),
            "internal_dependencies": internal_deps,
            "external_packages": [d.to_dict() for d in knowledge.dependencies if d.type != "standard_library"],
            "standard_library_modules": [d.to_dict() for d in knowledge.dependencies if d.type == "standard_library"],
            "aggregated_directory_dependencies": aggregated_directory_flows,
        }

    @classmethod
    def _detect_dependency_cycles(cls, knowledge: SharedRepositoryKnowledge) -> List[List[str]]:
        """
        Detect possible circular dependencies between repository source files.
        Builds a file-to-file directed graph from import relationships and finds simple cycles.
        """
        G_dep = nx.DiGraph()

        all_file_paths = {f.path.replace("\\", "/").strip("/") for f in knowledge.files}
        mod_to_file = {}
        for fp in all_file_paths:
            base_no_ext = os.path.splitext(fp)[0].replace("/", ".")
            mod_to_file[base_no_ext] = fp
            mod_to_file[os.path.splitext(os.path.basename(fp))[0]] = fp

        # Add nodes
        for fp in all_file_paths:
            G_dep.add_node(fp)

        # Add dependency edges
        for imp in knowledge.imports:
            src = imp.source_file.replace("\\", "/").strip("/")
            mod = imp.imported_module
            target_file = mod_to_file.get(mod) or mod_to_file.get(mod.split(".")[0])

            if target_file and target_file != src and target_file in all_file_paths:
                G_dep.add_edge(src, target_file)

        # Detect cycles with limit to avoid exponential explosion
        cycles: List[List[str]] = []
        try:
            # Check if DAG first
            if not nx.is_directed_acyclic_graph(G_dep):
                # Extract up to 20 simple cycles
                cycle_gen = nx.simple_cycles(G_dep)
                for cycle in itertools.islice(cycle_gen, 20):
                    # Represent as closed loop: A -> B -> C -> A
                    closed_loop = cycle + [cycle[0]]
                    cycles.append(closed_loop)
        except Exception as err:
            logger.debug(f"Cycle detection encountered non-fatal notice: {err}")

        return cycles

    @classmethod
    def _identify_highly_connected(
        cls,
        G: nx.DiGraph,
        knowledge: SharedRepositoryKnowledge,
    ) -> List[Dict[str, Any]]:
        """
        Compute node degree centrality and identify the top highly connected architectural components.
        Provides explainable, factual descriptions of why each component is central.
        """
        repo_prefix = f"repository:{knowledge.repository.owner}/{knowledge.repository.name}"
        components = []

        # Find entry points files for matching
        entry_point_files = {e.file.replace("\\", "/").strip("/") for e in knowledge.entry_points}

        for node_id, data in G.nodes(data=True):
            if node_id == repo_prefix:
                continue  # Skip root repository node

            in_deg = G.in_degree(node_id)
            out_deg = G.out_degree(node_id)
            total_deg = in_deg + out_deg

            if total_deg == 0:
                continue

            ntype = data.get("type", "entity")
            name = data.get("name", node_id)
            file_loc = data.get("file") or data.get("path") or ""

            # Formulate factual, measurable explanation
            explanation_parts = []
            explanation_parts.append(f"High connectivity: {total_deg} relationships ({in_deg} incoming, {out_deg} outgoing)")

            if file_loc in entry_point_files:
                explanation_parts.append("Identified execution entry point")

            if ntype == "file":
                c_cnt = data.get("classes_count", 0)
                f_cnt = data.get("functions_count", 0)
                if c_cnt or f_cnt:
                    explanation_parts.append(f"Contains {c_cnt} classes and {f_cnt} functions")
            elif ntype == "class":
                m_cnt = data.get("methods_count", 0)
                if m_cnt:
                    explanation_parts.append(f"Defines {m_cnt} class methods")

            max_deg = max([G.degree(n) for n in G.nodes() if n != repo_prefix] or [1])
            centrality_score = round(total_deg / max(max_deg, 1), 3)

            if in_deg > out_deg * 2:
                role_tag = "Shared Dependency / Utility Hub"
            elif out_deg > in_deg * 2:
                role_tag = "Coordinator / High Orchestrator"
            else:
                role_tag = "Architectural Backbone / Core Hub"

            components.append({
                "id": node_id,
                "name": name,
                "type": ntype,
                "file": file_loc,
                "in_degree": in_deg,
                "out_degree": out_deg,
                "total_degree": total_deg,
                "total_connections": total_deg,
                "centrality_score": centrality_score,
                "role_tag": role_tag,
                "explanation": " • ".join(explanation_parts),
            })

        # Sort by total connections descending
        components.sort(key=lambda x: x["total_connections"], reverse=True)
        return components[:15]  # Top 15 highly connected components

    @classmethod
    def _build_search_index(cls, knowledge: SharedRepositoryKnowledge) -> List[Dict[str, Any]]:
        """
        Build a flat, rapid search index across all architectural entities.
        """
        index = []

        for d in knowledge.directories:
            d_path = d.path.replace("\\", "/").strip("/")
            if d_path and d_path != ".":
                index.append({
                    "id": f"directory:{d_path}",
                    "name": d.name or d_path.split("/")[-1],
                    "type": "directory",
                    "path": d_path,
                    "subtitle": f"Directory in {d.parent or 'root'}",
                })

        for f in knowledge.files:
            f_path = f.path.replace("\\", "/").strip("/")
            index.append({
                "id": f"file:{f_path}",
                "name": f.name,
                "type": "file",
                "path": f_path,
                "subtitle": f"{f.language or 'File'} ({f.classes_count} classes, {f.functions_count} functions)",
            })

        for c in knowledge.classes:
            f_path = c.file.replace("\\", "/").strip("/")
            index.append({
                "id": f"class:{f_path}:{c.name}",
                "name": c.name,
                "type": "class",
                "path": f_path,
                "subtitle": f"Class in {f_path} ({len(c.methods)} methods)",
            })

        for fn in knowledge.functions:
            f_path = fn.file.replace("\\", "/").strip("/")
            index.append({
                "id": f"function:{f_path}:{fn.name}",
                "name": f"{fn.name}()",
                "type": "function",
                "path": f_path,
                "subtitle": f"Function in {f_path}",
            })

        for m in knowledge.methods:
            f_path = m.file.replace("\\", "/").strip("/")
            index.append({
                "id": f"method:{f_path}:{m.class_name}:{m.name}",
                "name": f"{m.class_name}.{m.name}()",
                "type": "method",
                "path": f_path,
                "subtitle": f"Method in {c.name if 'c' in locals() else m.class_name}",
            })

        for dep in knowledge.dependencies:
            index.append({
                "id": f"dependency:{dep.name}",
                "name": dep.name,
                "type": "dependency",
                "path": "",
                "subtitle": f"{'Standard Library' if dep.type == 'standard_library' else 'Third-Party Package'} ({dep.occurrences} imports)",
            })

        return index

    @classmethod
    def _format_entry_points(cls, knowledge: SharedRepositoryKnowledge) -> List[Dict[str, Any]]:
        """
        Format detected entry points with factual static-analysis evidence.
        """
        formatted = []
        for ep in knowledge.entry_points:
            reason = "Contains executable startup logic."
            if ep.detection_reason == "main_block":
                reason = "Detected 'if __name__ == \"__main__\":' startup execution block."
            elif ep.detection_reason == "main_method":
                reason = "Detected standard 'public static void main' entry point method."
            elif ep.detection_reason == "main_function":
                reason = "Detected top-level 'main()' application bootstrap function."

            formatted.append({
                "file": ep.file,
                "symbol": ep.symbol,
                "type": ep.detection_reason,
                "line": ep.line,
                "reason": reason,
            })
        return formatted

    @classmethod
    def _generate_architecture_summary(
        cls,
        knowledge: SharedRepositoryKnowledge,
        levels: Dict[str, Any],
        cycles: List[List[str]],
        connected_components: List[Dict[str, Any]],
        dependency_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a deterministic, factual architecture summary dossier from actual data.
        """
        repo = knowledge.repository
        major_dirs = levels["level_1"]["major_directories"]

        # Determine primary language accurately (avoid Multi-language when one language dominates)
        primary_lang = repo.primary_language
        if not primary_lang or primary_lang.lower() in {"multi-language", "unknown", "none"}:
            lang_counts: Dict[str, int] = {}
            for f in knowledge.files:
                if f.language and f.language not in {"Unknown", "Text"}:
                    lang_counts[f.language] = lang_counts.get(f.language, 0) + 1
            if lang_counts:
                primary_lang = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)[0][0]
        primary_lang = primary_lang or "Python"

        # Bullets for summary
        bullets = [
            f"Codebase spans {len(knowledge.files)} files organized across {len(knowledge.directories)} directory paths.",
            f"Primary programming language: {primary_lang}.",
            f"Syntactic analysis extracted {len(knowledge.classes)} classes, {len(knowledge.functions)} top-level functions, and {len(knowledge.methods)} methods.",
            f"Dependency analysis identified {dependency_analysis['internal_count']} internal file dependencies and {dependency_analysis['external_count']} external/standard package imports.",
        ]

        if cycles:
            bullets.append(f"Static cycle detection identified {len(cycles)} potential circular dependency loops.")
        else:
            bullets.append("The analyzed dependency graph contains no detected dependency cycles.")

        if knowledge.entry_points:
            bullets.append(f"Detected {len(knowledge.entry_points)} application execution bootstrap entry points.")

        # Identify production architectural hubs only (exclude test files and test classes)
        def is_test_component(c: Dict[str, Any]) -> bool:
            c_name = (c.get("name") or "").lower()
            c_file = (c.get("file") or "").lower()
            if any(k in c_file for k in ["/test", "test/", "tests/", "spec/"]):
                return True
            if c_name.startswith("test") or c_name.startswith("test_") or c_file.endswith(("_test.py", "_test.js", "test.py")):
                return True
            return False

        prod_components = [c for c in connected_components if not is_test_component(c)]
        top_hubs = []
        for c in prod_components:
            h_name = c.get("file") or c.get("name")
            if h_name and h_name not in top_hubs:
                top_hubs.append(h_name)
            if len(top_hubs) >= 3:
                break

        if top_hubs:
            bullets.append(f"Key production architectural hubs with highest connectivity: {', '.join(top_hubs)}.")

        return {
            "title": f"Architecture Overview for {repo.full_name}",
            "overview_bullets": bullets,
            "major_directories": [d["name"] for d in major_dirs[:8]],
            "cycle_status": f"{len(cycles)} cycles detected" if cycles else "Clean (No cycles detected)",
        }
