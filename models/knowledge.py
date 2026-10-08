"""
Knowledge models representing the centralized Shared Repository Knowledge layer.

This structured representation decouples static analysis (Phase 5 & 6) from
downstream consumers: Semantic Code Graph (Phase 7), Architecture Analysis,
RAG, AI Chatbots, and Report Generators.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional


@dataclass
class RepositoryInfo:
    """Metadata regarding the analyzed repository."""
    name: str
    owner: str
    url: str
    full_name: str = ""
    branch: Optional[str] = None
    commit: Optional[str] = None
    description: Optional[str] = None
    primary_language: Optional[str] = None
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not self.full_name:
            self.full_name = f"{self.owner}/{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DirectoryInfo:
    """Directory node within the codebase hierarchy."""
    path: str
    name: str
    parent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FileInfo:
    """Source, documentation, or config file in the codebase."""
    path: str
    name: str
    extension: str
    language: Optional[str] = None
    size: Optional[int] = None
    classes_count: int = 0
    functions_count: int = 0
    methods_count: int = 0
    imports_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClassInfo:
    """Extracted class definition and its inheritance."""
    name: str
    file: str
    id: str = ""
    module: Optional[str] = None
    language: str = "Python"
    base_classes: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    methods_count: int = 0
    methods: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.file}:{self.name}"
        if not self.module:
            self.module = self.file.replace("\\", "/").replace("/", ".").rsplit(".", 1)[0]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionInfo:
    """Extracted top-level function definition."""
    name: str
    file: str
    id: str = ""
    module: Optional[str] = None
    language: str = "Python"
    parameters: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    is_async: bool = False
    is_method: bool = False
    class_name: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.file}:{self.name}"
        if not self.module:
            self.module = self.file.replace("\\", "/").replace("/", ".").rsplit(".", 1)[0]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MethodInfo:
    """Extracted method bound to a class."""
    name: str
    class_name: str
    file: str
    id: str = ""
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)
    language: str = "Python"
    docstring: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.file}:{self.class_name}.{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ImportInfo:
    """Import declaration within a source file."""
    source_file: str
    imported_module: str
    imported_symbol: Optional[str] = None
    alias: Optional[str] = None
    is_standard_library: bool = False
    is_external: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DependencyInfo:
    """Consolidated package dependency."""
    name: str
    type: str  # 'standard_library' or 'external_package'
    occurrences: int = 1
    files: List[str] = field(default_factory=list)
    files_count: int = 0

    def __post_init__(self):
        if not self.files_count:
            self.files_count = len(self.files)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntryPointInfo:
    """Identified execution bootstrap point."""
    file: str
    symbol: str
    detection_reason: str  # 'main_block', 'main_method', etc.
    line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RelationshipInfo:
    """Semantic relationship between code entities."""
    source: str
    relation: str  # 'CONTAINS', 'IMPORTS', 'DEFINES', 'INHERITS', 'DEPENDS_ON', 'CALLS'
    target: str
    source_type: str = ""
    target_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SharedRepositoryKnowledge:
    """
    Centralized, graph-ready structured knowledge object for a repository.
    Acts as the single source of truth for graphs, AI comprehension, and reporting.
    """
    repository: RepositoryInfo
    directories: List[DirectoryInfo] = field(default_factory=list)
    files: List[FileInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    methods: List[MethodInfo] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    dependencies: List[DependencyInfo] = field(default_factory=list)
    entry_points: List[EntryPointInfo] = field(default_factory=list)
    relationships: List[RelationshipInfo] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert full knowledge object to dictionary."""
        return {
            "repository": self.repository.to_dict(),
            "directories": [d.to_dict() if hasattr(d, "to_dict") else d for d in self.directories],
            "files": [f.to_dict() if hasattr(f, "to_dict") else f for f in self.files],
            "classes": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.classes],
            "functions": [f.to_dict() if hasattr(f, "to_dict") else f for f in self.functions],
            "methods": [m.to_dict() if hasattr(m, "to_dict") else m for m in self.methods],
            "imports": [i.to_dict() if hasattr(i, "to_dict") else i for i in self.imports],
            "dependencies": [d.to_dict() if hasattr(d, "to_dict") else d for d in self.dependencies],
            "entry_points": [e.to_dict() if hasattr(e, "to_dict") else e for e in self.entry_points],
            "relationships": [r.to_dict() if hasattr(r, "to_dict") else r for r in self.relationships],
            "statistics": self.statistics,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize knowledge to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SharedRepositoryKnowledge":
        """Reconstruct SharedRepositoryKnowledge from dictionary."""
        repo_data = data.get("repository", {})
        repo_info = RepositoryInfo(
            name=repo_data.get("name", "unknown"),
            owner=repo_data.get("owner", "unknown"),
            url=repo_data.get("url", ""),
            full_name=repo_data.get("full_name", f"{repo_data.get('owner', '')}/{repo_data.get('name', '')}"),
            branch=repo_data.get("branch"),
            commit=repo_data.get("commit"),
            description=repo_data.get("description"),
            primary_language=repo_data.get("primary_language"),
            analyzed_at=repo_data.get("analyzed_at", datetime.now(timezone.utc).isoformat()),
        )

        directories = []
        for d in data.get("directories", []):
            if isinstance(d, str):
                d_name = d.split("/")[-1] if "/" in d else d
                parent = d.rsplit("/", 1)[0] if "/" in d else None
                directories.append(DirectoryInfo(path=d, name=d_name, parent=parent))
            elif isinstance(d, dict):
                directories.append(DirectoryInfo(
                    path=d.get("path", ""),
                    name=d.get("name", ""),
                    parent=d.get("parent"),
                ))

        files = []
        for f in data.get("files", []):
            files.append(FileInfo(
                path=f.get("path", ""),
                name=f.get("name", ""),
                extension=f.get("extension", ""),
                language=f.get("language"),
                size=f.get("size"),
                classes_count=f.get("classes_count", 0),
                functions_count=f.get("functions_count", 0),
                methods_count=f.get("methods_count", 0),
                imports_count=f.get("imports_count", 0),
            ))

        classes = []
        for c in data.get("classes", []):
            classes.append(ClassInfo(
                name=c.get("name", ""),
                file=c.get("file", ""),
                id=c.get("id", f"{c.get('file', '')}:{c.get('name', '')}"),
                module=c.get("module"),
                language=c.get("language", "Python"),
                base_classes=c.get("bases") or c.get("base_classes") or [],
                interfaces=c.get("interfaces", []),
                decorators=c.get("decorators", []),
                docstring=c.get("docstring"),
                line_start=c.get("line_start"),
                line_end=c.get("line_end"),
                methods_count=c.get("methods_count", len(c.get("methods", []))),
                methods=c.get("methods", []),
            ))

        functions = []
        for f in data.get("functions", []):
            functions.append(FunctionInfo(
                name=f.get("name", ""),
                file=f.get("file", ""),
                id=f.get("id", f"{f.get('file', '')}:{f.get('name', '')}"),
                module=f.get("module"),
                language=f.get("language", "Python"),
                parameters=f.get("args") or f.get("parameters") or [],
                decorators=f.get("decorators", []),
                docstring=f.get("docstring"),
                is_async=f.get("is_async", False),
                is_method=f.get("is_method", False),
                class_name=f.get("class_name"),
                line_start=f.get("line_start"),
                line_end=f.get("line_end"),
            ))

        methods = []
        for m in data.get("methods", []):
            methods.append(MethodInfo(
                name=m.get("name", ""),
                class_name=m.get("class_name", ""),
                file=m.get("file", ""),
                id=m.get("id", f"{m.get('file', '')}:{m.get('class_name', '')}.{m.get('name', '')}"),
                parameters=m.get("args") or m.get("parameters") or [],
                return_type=m.get("return_type"),
                decorators=m.get("decorators", []),
                modifiers=m.get("modifiers", []),
                language=m.get("language", "Python"),
                docstring=m.get("docstring"),
                line_start=m.get("line_start"),
                line_end=m.get("line_end"),
            ))

        imports = []
        for i in data.get("imports", []):
            imports.append(ImportInfo(
                source_file=i.get("file") or i.get("source_file", ""),
                imported_module=i.get("module") or i.get("imported_module", ""),
                imported_symbol=i.get("imported_name") or i.get("imported_symbol"),
                alias=i.get("alias"),
                is_standard_library=i.get("is_standard_library", False),
                is_external=i.get("is_external", False),
            ))

        dependencies = []
        for d in data.get("dependencies", []):
            dep_type = "standard_library" if d.get("is_standard_library") else "external_package"
            dependencies.append(DependencyInfo(
                name=d.get("name") or d.get("target", ""),
                type=d.get("type", dep_type),
                occurrences=d.get("occurrences", 1),
                files=d.get("files", []),
                files_count=d.get("files_count", len(d.get("files", []))),
            ))

        entry_points = []
        for e in data.get("entry_points", []):
            entry_points.append(EntryPointInfo(
                file=e.get("file", ""),
                symbol=e.get("symbol", ""),
                detection_reason=e.get("type") or e.get("detection_reason", "main"),
                line=e.get("line"),
            ))

        relationships = []
        for r in data.get("relationships", []):
            relationships.append(RelationshipInfo(
                source=r.get("source", ""),
                relation=r.get("relation", ""),
                target=r.get("target", ""),
                source_type=r.get("source_type", ""),
                target_type=r.get("target_type", ""),
            ))

        statistics = data.get("statistics", {})

        return cls(
            repository=repo_info,
            directories=directories,
            files=files,
            classes=classes,
            functions=functions,
            methods=methods,
            imports=imports,
            dependencies=dependencies,
            entry_points=entry_points,
            relationships=relationships,
            statistics=statistics,
        )
