"""
Semantic Code Graph Generation Service for CodeLens AI.

Constructs a directed semantic graph (using NetworkX) representing:
- Hierarchy: Repository -> Directories -> Files -> Classes -> Methods / Functions (CONTAINS)
- Inheritance: Subclass -> Base Class (INHERITS)
- Modules & Dependencies: File -> Imported Module / Package (IMPORTS, DEPENDS_ON)
- Definitions: File -> Class / Function (DEFINES)
- Validated relationships with stable unique IDs.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from models.knowledge import SharedRepositoryKnowledge
from services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class SemanticCodeGraphService:
    """
    Constructs, validates, serializes, and caches the Semantic Code Graph
    using NetworkX.
    """

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    GRAPHS_DIR = DATA_DIR / "graphs"

    VALID_NODE_TYPES = {
        "repository",
        "directory",
        "file",
        "class",
        "function",
        "method",
        "dependency",
    }

    VALID_EDGE_TYPES = {
        "CONTAINS",
        "DEFINES",
        "INHERITS",
        "IMPORTS",
        "DEPENDS_ON",
        "CALLS",
    }

    @classmethod
    def get_graph_file_path(cls, owner: str, name: str) -> Path:
        """Return the target path for the saved graph JSON."""
        cls.GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
        return cls.GRAPHS_DIR / f"{owner}_{name}_graph.json"

    @classmethod
    def load_cached_graph(cls, owner: str, name: str) -> Optional[Dict[str, Any]]:
        """Load cached graph JSON if it exists."""
        path = cls.get_graph_file_path(owner, name)
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["is_cached"] = True
                    return data
            except Exception as err:
                logger.warning(f"Failed to load cached graph from {path}: {err}")
        return None

    @classmethod
    def build_graph(
        cls,
        knowledge: SharedRepositoryKnowledge,
        max_nodes_per_category: Optional[int] = None,
    ) -> Tuple[nx.DiGraph, Dict[str, Any]]:
        """
        Build a NetworkX DiGraph from SharedRepositoryKnowledge.

        Nodes:
        - repository:<owner>/<repo>
        - directory:<path>
        - file:<path>
        - class:<file>:<class_name>
        - function:<file>:<function_name>
        - method:<file>:<class_name>:<method_name>
        - dependency:<name>

        Edges:
        - CONTAINS (Hierarchy)
        - DEFINES (File -> Class/Function)
        - INHERITS (Class -> Base Class)
        - IMPORTS (File -> Module/Package)
        - DEPENDS_ON (File -> External Dependency)
        - CALLS (Only if detected in static analysis)
        """
        G = nx.DiGraph()
        repo = knowledge.repository
        repo_id = f"repository:{repo.owner}/{repo.name}"

        # 1. Root Repository Node
        G.add_node(
            repo_id,
            id=repo_id,
            type="repository",
            name=repo.name,
            label=repo.name,
            owner=repo.owner,
            full_name=repo.full_name,
            url=repo.url,
            language=repo.primary_language,
        )

        # 2. Directory Nodes & Hierarchy
        # Map directory path -> node_id
        dir_node_map: Dict[str, str] = {}
        # Keep track of directories created
        for d in knowledge.directories:
            d_path = d.path.replace("\\", "/").strip("/")
            if not d_path or d_path == ".":
                continue
            d_id = f"directory:{d_path}"
            dir_node_map[d_path] = d_id
            G.add_node(
                d_id,
                id=d_id,
                type="directory",
                name=d.name or d_path.split("/")[-1],
                label=d.name or d_path.split("/")[-1],
                path=d_path,
            )

        # Connect Directory Hierarchy (CONTAINS)
        for d_path, d_id in dir_node_map.items():
            if "/" in d_path:
                parent_path = d_path.rsplit("/", 1)[0]
                if parent_path in dir_node_map:
                    G.add_edge(dir_node_map[parent_path], d_id, type="CONTAINS", label="contains")
                else:
                    G.add_edge(repo_id, d_id, type="CONTAINS", label="contains")
            else:
                # Top-level directory connects to repository
                G.add_edge(repo_id, d_id, type="CONTAINS", label="contains")

        # 3. File Nodes
        file_node_map: Dict[str, str] = {}
        for f in knowledge.files:
            f_path = f.path.replace("\\", "/").strip("/")
            if not f_path:
                continue
            f_id = f"file:{f_path}"
            file_node_map[f_path] = f_id
            G.add_node(
                f_id,
                id=f_id,
                type="file",
                name=f.name,
                label=f.name,
                path=f_path,
                extension=f.extension,
                language=f.language,
                size=f.size,
            )

            # Connect File to parent Directory or Repository
            if "/" in f_path:
                parent_dir = f_path.rsplit("/", 1)[0]
                if parent_dir in dir_node_map:
                    G.add_edge(dir_node_map[parent_dir], f_id, type="CONTAINS", label="contains")
                else:
                    # Create parent dir node if not present
                    p_id = f"directory:{parent_dir}"
                    if not G.has_node(p_id):
                        G.add_node(p_id, id=p_id, type="directory", name=parent_dir.split("/")[-1], path=parent_dir)
                        G.add_edge(repo_id, p_id, type="CONTAINS", label="contains")
                        dir_node_map[parent_dir] = p_id
                    G.add_edge(p_id, f_id, type="CONTAINS", label="contains")
            else:
                # Root file connects to repository
                G.add_edge(repo_id, f_id, type="CONTAINS", label="contains")

        # 4. Class Nodes & File->Class (CONTAINS & DEFINES)
        class_node_map: Dict[str, str] = {}  # "file:name" -> id
        class_name_map: Dict[str, str] = {}  # "name" -> id (for simple inheritance matching)
        for c in knowledge.classes:
            c_file = c.file.replace("\\", "/").strip("/")
            c_id = f"class:{c_file}:{c.name}"
            class_node_map[f"{c_file}:{c.name}"] = c_id
            class_name_map[c.name] = c_id

            G.add_node(
                c_id,
                id=c_id,
                type="class",
                name=c.name,
                label=c.name,
                file=c_file,
                module=c.module,
                language=c.language,
                docstring=c.docstring,
                line_start=c.line_start,
                line_end=c.line_end,
                methods_count=len(c.methods),
                base_classes=c.base_classes,
            )

            # Link File -> Class
            f_id = file_node_map.get(c_file)
            if f_id and G.has_node(f_id):
                G.add_edge(f_id, c_id, type="CONTAINS", label="contains")
                G.add_edge(f_id, c_id, type="DEFINES", label="defines")
            elif not f_id:
                # Ensure synthetic file node exists
                f_id = f"file:{c_file}"
                G.add_node(f_id, id=f_id, type="file", name=c_file.split("/")[-1], path=c_file)
                file_node_map[c_file] = f_id
                G.add_edge(repo_id, f_id, type="CONTAINS", label="contains")
                G.add_edge(f_id, c_id, type="CONTAINS", label="contains")
                G.add_edge(f_id, c_id, type="DEFINES", label="defines")

        # 5. Method Nodes & Class->Method (CONTAINS)
        for m in knowledge.methods:
            m_file = m.file.replace("\\", "/").strip("/")
            m_id = f"method:{m_file}:{m.class_name}:{m.name}"

            G.add_node(
                m_id,
                id=m_id,
                type="method",
                name=m.name,
                label=f"{m.class_name}.{m.name}()",
                file=m_file,
                class_name=m.class_name,
                parameters=m.parameters,
                return_type=m.return_type,
                line_start=m.line_start,
            )

            # Connect Class -> Method
            parent_c_id = class_node_map.get(f"{m_file}:{m.class_name}") or class_name_map.get(m.class_name)
            if parent_c_id and G.has_node(parent_c_id):
                G.add_edge(parent_c_id, m_id, type="CONTAINS", label="contains")

        # 6. Function Nodes & File->Function (CONTAINS & DEFINES)
        for fn in knowledge.functions:
            fn_file = fn.file.replace("\\", "/").strip("/")
            fn_id = f"function:{fn_file}:{fn.name}"

            G.add_node(
                fn_id,
                id=fn_id,
                type="function",
                name=fn.name,
                label=f"{fn.name}()",
                file=fn_file,
                module=fn.module,
                parameters=fn.parameters,
                decorators=fn.decorators,
                docstring=fn.docstring,
                is_async=fn.is_async,
                line_start=fn.line_start,
            )

            # Link File -> Function
            f_id = file_node_map.get(fn_file)
            if f_id and G.has_node(f_id):
                G.add_edge(f_id, fn_id, type="CONTAINS", label="contains")
                G.add_edge(f_id, fn_id, type="DEFINES", label="defines")
            else:
                f_id = f"file:{fn_file}"
                if not G.has_node(f_id):
                    G.add_node(f_id, id=f_id, type="file", name=fn_file.split("/")[-1], path=fn_file)
                    G.add_edge(repo_id, f_id, type="CONTAINS", label="contains")
                    file_node_map[fn_file] = f_id
                G.add_edge(f_id, fn_id, type="CONTAINS", label="contains")
                G.add_edge(f_id, fn_id, type="DEFINES", label="defines")

        # 7. Inheritance Edges (INHERITS)
        for c in knowledge.classes:
            c_file = c.file.replace("\\", "/").strip("/")
            c_id = class_node_map.get(f"{c_file}:{c.name}")
            if not c_id:
                continue

            for base in c.base_classes:
                # Clean base class name (e.g. "object", "Exception", "models.Model")
                base_clean = base.strip()
                if not base_clean:
                    continue

                # Check if base class exists in the codebase
                base_target_id = class_name_map.get(base_clean)
                if not base_target_id:
                    # If base has dot (e.g. pkg.BaseClass), check last segment
                    last_seg = base_clean.split(".")[-1]
                    base_target_id = class_name_map.get(last_seg)

                if base_target_id and G.has_node(base_target_id) and base_target_id != c_id:
                    G.add_edge(c_id, base_target_id, type="INHERITS", label="inherits")
                else:
                    # External / built-in base class node (e.g. class:external:BaseModel)
                    ext_base_id = f"class:external:{base_clean}"
                    if not G.has_node(ext_base_id):
                        G.add_node(
                            ext_base_id,
                            id=ext_base_id,
                            type="class",
                            name=base_clean,
                            label=base_clean,
                            is_external=True,
                        )
                    G.add_edge(c_id, ext_base_id, type="INHERITS", label="inherits")

        # 8. Dependency & Import Edges (DEPENDS_ON & IMPORTS)
        dep_node_map: Dict[str, str] = {}
        for dep in knowledge.dependencies:
            dep_name = dep.name
            if not dep_name:
                continue
            dep_id = f"dependency:{dep_name}"
            dep_node_map[dep_name] = dep_id

            if not G.has_node(dep_id):
                G.add_node(
                    dep_id,
                    id=dep_id,
                    type="dependency",
                    name=dep_name,
                    label=dep_name,
                    category=dep.type,
                    occurrences=dep.occurrences,
                    is_standard_library=(dep.type == "standard_library"),
                )

            # Connect files that use this dependency
            for f_path in dep.files:
                f_path_clean = f_path.replace("\\", "/").strip("/")
                f_id = file_node_map.get(f_path_clean)
                if f_id and G.has_node(f_id):
                    edge_type = "DEPENDS_ON" if dep.type != "standard_library" else "IMPORTS"
                    G.add_edge(f_id, dep_id, type=edge_type, label=edge_type.lower())

        # 9. Additional Explicit Relationships from Phase 6 (CALLS, DEFINES, IMPORTS)
        for r in knowledge.relationships:
            rel_type = r.relation.upper()
            if rel_type not in cls.VALID_EDGE_TYPES:
                # Map common variants
                if rel_type == "CONTAINS_METHOD":
                    rel_type = "CONTAINS"
                elif rel_type == "INHERITS_FROM":
                    rel_type = "INHERITS"
                else:
                    continue

            # Resolve source and target IDs
            src_id = cls._resolve_entity_id(r.source, r.source_type, class_name_map, file_node_map)
            tgt_id = cls._resolve_entity_id(r.target, r.target_type, class_name_map, file_node_map)

            if src_id and tgt_id and G.has_node(src_id) and G.has_node(tgt_id) and src_id != tgt_id:
                if not G.has_edge(src_id, tgt_id):
                    G.add_edge(src_id, tgt_id, type=rel_type, label=rel_type.lower())

        # 10. Validate and compute statistics
        validation_report = cls.validate_graph(G, repo.full_name)
        stats = cls.calculate_statistics(G)

        return G, {"validation": validation_report, "statistics": stats}

    @classmethod
    def _resolve_entity_id(
        cls,
        name: str,
        entity_type: str,
        class_name_map: Dict[str, str],
        file_node_map: Dict[str, str],
    ) -> Optional[str]:
        """Resolve a raw name and type to a node ID in the graph."""
        if not name:
            return None
        clean_name = name.replace("\\", "/").strip("/")

        if entity_type == "file":
            return file_node_map.get(clean_name) or f"file:{clean_name}"
        elif entity_type == "class":
            return class_name_map.get(name) or f"class:external:{name}"
        elif entity_type == "dependency" or entity_type == "package":
            return f"dependency:{name}"
        return None

    @classmethod
    def validate_graph(cls, G: nx.DiGraph, expected_repo_name: str) -> Dict[str, Any]:
        """
        Validate graph integrity:
        - Unique node IDs
        - Edges refer to existing nodes
        - Valid node and edge types
        - Repository identity preserved
        """
        issues: List[str] = []

        # 1. Verify Repository node exists
        repo_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "repository"]
        if not repo_nodes:
            issues.append("Missing root repository node")

        # 2. Check node types
        invalid_node_types = []
        for n, d in G.nodes(data=True):
            ntype = d.get("type")
            if ntype not in cls.VALID_NODE_TYPES:
                invalid_node_types.append(f"Node {n} has invalid type '{ntype}'")

        if invalid_node_types:
            issues.extend(invalid_node_types[:5])

        # 3. Check edges refer to valid existing nodes
        dangling_edges = []
        for u, v, d in G.edges(data=True):
            if not G.has_node(u):
                dangling_edges.append((u, v, "source missing"))
            if not G.has_node(v):
                dangling_edges.append((u, v, "target missing"))

            etype = d.get("type")
            if etype not in cls.VALID_EDGE_TYPES:
                issues.append(f"Edge ({u} -> {v}) has invalid type '{etype}'")

        if dangling_edges:
            # Clean up dangling edges gracefully
            for u, v, _ in dangling_edges:
                if G.has_edge(u, v):
                    G.remove_edge(u, v)
            issues.append(f"Removed {len(dangling_edges)} dangling edges.")

        is_valid = len(issues) == 0
        if not is_valid:
            logger.info(f"Graph validation found {len(issues)} items for {expected_repo_name}: {issues[:3]}")

        return {
            "is_valid": is_valid,
            "issues_count": len(issues),
            "issues": issues[:10],
            "total_nodes": G.number_of_nodes(),
            "total_edges": G.number_of_edges(),
        }

    @classmethod
    def calculate_statistics(cls, G: nx.DiGraph) -> Dict[str, int]:
        """Calculate detailed counts for all node and edge types."""
        node_counts = {
            "repository": 0,
            "directory": 0,
            "file": 0,
            "class": 0,
            "function": 0,
            "method": 0,
            "dependency": 0,
        }
        for _, d in G.nodes(data=True):
            ntype = d.get("type")
            if ntype in node_counts:
                node_counts[ntype] += 1

        edge_counts = {
            "CONTAINS": 0,
            "DEFINES": 0,
            "INHERITS": 0,
            "IMPORTS": 0,
            "DEPENDS_ON": 0,
            "CALLS": 0,
        }
        for _, _, d in G.edges(data=True):
            etype = d.get("type")
            if etype in edge_counts:
                edge_counts[etype] += 1

        return {
            "total_nodes": G.number_of_nodes(),
            "total_edges": G.number_of_edges(),
            "repository_nodes": node_counts["repository"],
            "directory_nodes": node_counts["directory"],
            "file_nodes": node_counts["file"],
            "class_nodes": node_counts["class"],
            "function_nodes": node_counts["function"],
            "method_nodes": node_counts["method"],
            "dependency_nodes": node_counts["dependency"],
            "contains_edges": edge_counts["CONTAINS"],
            "defines_edges": edge_counts["DEFINES"],
            "inherits_edges": edge_counts["INHERITS"],
            "imports_edges": edge_counts["IMPORTS"],
            "depends_on_edges": edge_counts["DEPENDS_ON"],
            "calls_edges": edge_counts["CALLS"],
        }

    @classmethod
    def serialize_graph(
        cls,
        G: nx.DiGraph,
        knowledge: SharedRepositoryKnowledge,
        validation: Dict[str, Any],
        statistics: Dict[str, int],
    ) -> Dict[str, Any]:
        """
        Convert NetworkX DiGraph into a serializable JSON dictionary.
        """
        nodes_list = []
        for n_id, data in G.nodes(data=True):
            node_dict = {
                "id": n_id,
                "type": data.get("type", "unknown"),
                "name": data.get("name", n_id),
                "label": data.get("label", data.get("name", n_id)),
            }
            # Add other optional attributes
            for k in [
                "path", "file", "language", "class_name", "extension",
                "size", "parameters", "docstring", "line_start", "line_end",
                "is_async", "is_external", "category",
            ]:
                if k in data and data[k] is not None:
                    node_dict[k] = data[k]
            nodes_list.append(node_dict)

        edges_list = []
        for u, v, data in G.edges(data=True):
            edges_list.append({
                "source": u,
                "target": v,
                "type": data.get("type", "RELATED_TO"),
                "label": data.get("label", data.get("type", "")),
            })

        return {
            "repository": knowledge.repository.to_dict(),
            "nodes": nodes_list,
            "edges": edges_list,
            "statistics": statistics,
            "validation": validation,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def get_or_create_graph(
        cls,
        owner: str,
        name: str,
        repo_path: Optional[Path] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Main public interface:
        1. Checks cache for data/graphs/{owner}_{name}_graph.json
        2. If missing or force_refresh, retrieves Shared Knowledge
        3. Builds NetworkX DiGraph
        4. Validates and saves to disk
        5. Returns serializable dictionary
        """
        # 1. Check Cache
        if not force_refresh:
            cached = cls.load_cached_graph(owner, name)
            if cached:
                return {
                    "success": True,
                    "is_cached": True,
                    "message": f"Loaded cached Semantic Code Graph for {owner}/{name}",
                    "graph": cached,
                }

        # 2. Get Shared Knowledge
        knowledge = KnowledgeService.get_shared_knowledge(
            owner=owner,
            name=name,
            repo_path=repo_path,
            force_refresh=force_refresh,
        )

        # 3. Build Graph
        G, meta = cls.build_graph(knowledge)

        # 4. Serialize
        graph_dict = cls.serialize_graph(
            G=G,
            knowledge=knowledge,
            validation=meta["validation"],
            statistics=meta["statistics"],
        )

        # 5. Persist to disk
        try:
            out_path = cls.get_graph_file_path(owner, name)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(graph_dict, f, indent=2)
            logger.info(f"Persisted Semantic Code Graph to {out_path}")
        except Exception as err:
            logger.warning(f"Failed to persist graph file: {err}")

        return {
            "success": True,
            "is_cached": False,
            "message": f"Successfully generated Semantic Code Graph for {owner}/{name}",
            "graph": graph_dict,
        }
