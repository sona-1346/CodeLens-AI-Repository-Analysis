"""
Analysis Service for CodeLens AI (Phase 5).

Handles safe repository acquisition (cloning via GitPython/Git CLI),
caching, static file system scanning, language detection, directory
structure extraction, and analysis result persistence.

SAFETY GUARANTEE:
- NO repository source code is ever executed.
- Generated and dependency directories (.git, node_modules, venv, __pycache__, dist, build, etc.) are strictly ignored.
- Analysis is performed 100% statically.
"""

import os
import re
import json
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)

# Try importing GitPython, fallback gracefully if unavailable
try:
    import git
    GITPYTHON_AVAILABLE = True
except ImportError:
    git = None
    GITPYTHON_AVAILABLE = False


class RepositoryAnalysisService:
    """Service for repository acquisition and static structure analysis."""

    # Base directories (resolved relative to project root)
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    REPOSITORIES_DIR = DATA_DIR / "repositories"
    ANALYSIS_DIR = DATA_DIR / "analysis"

    # Directories strictly ignored during static analysis
    IGNORED_DIRECTORIES: Set[str] = {
        ".git",
        ".github",
        ".gitlab",
        "node_modules",
        "venv",
        ".venv",
        "env",
        ".env",
        "virtualenv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "out",
        "target",
        "bin",
        "obj",
        ".idea",
        ".vscode",
        ".eclipse",
        "eggs",
        ".eggs",
        "htmlcov",
        "coverage",
        ".nyc_output",
        "vendor",
        "bower_components",
        ".tox",
    }

    # Ignored specific file names
    IGNORED_FILES: Set[str] = {
        ".ds_store",
        "thumbs.db",
        "desktop.ini",
        ".gitkeep",
    }

    # Extension to Programming Language mapping
    LANGUAGE_EXTENSIONS: Dict[str, str] = {
        # Python
        ".py": "Python",
        ".pyw": "Python",
        ".pyi": "Python",
        # JavaScript / TypeScript / Web
        ".js": "JavaScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".jsx": "JavaScript (React)",
        ".ts": "TypeScript",
        ".tsx": "TypeScript (React)",
        ".html": "HTML",
        ".htm": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".sass": "Sass",
        ".less": "Less",
        # Systems & Compiled Languages
        ".c": "C",
        ".h": "C/C++ Header",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".hpp": "C++ Header",
        ".hh": "C++ Header",
        ".cs": "C#",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".kt": "Kotlin",
        ".kts": "Kotlin",
        ".scala": "Scala",
        ".swift": "Swift",
        ".m": "Objective-C",
        # Scripting & Backend
        ".rb": "Ruby",
        ".php": "PHP",
        ".sh": "Shell",
        ".bash": "Bash",
        ".zsh": "Zsh",
        ".ps1": "PowerShell",
        ".bat": "Batch",
        ".cmd": "Batch",
        ".lua": "Lua",
        ".r": "R",
        ".dart": "Dart",
        ".pl": "Perl",
        ".pm": "Perl",
        # Data & Query
        ".sql": "SQL",
        ".graphql": "GraphQL",
        ".gql": "GraphQL",
        ".proto": "Protocol Buffers",
    }

    # Documentation extensions
    DOC_EXTENSIONS: Set[str] = {
        ".md",
        ".markdown",
        ".mdown",
        ".rst",
        ".txt",
        ".adoc",
        ".asciidoc",
        ".pdf",
        ".doc",
        ".docx",
    }

    # Configuration and Data extensions
    CONFIG_EXTENSIONS: Set[str] = {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".xml",
        ".csv",
        ".tsv",
        ".properties",
        ".env.example",
    }

    @classmethod
    def ensure_directories(cls) -> None:
        """Ensure storage directories exist."""
        cls.REPOSITORIES_DIR.mkdir(parents=True, exist_ok=True)
        cls.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def sanitize_identifier(cls, text: str) -> str:
        """Sanitize owner or repo name for safe directory and file names."""
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", text).strip("_")

    @classmethod
    def get_repo_dir_name(cls, owner: str, name: str) -> str:
        """Generate a safe, unique directory name for a repository."""
        s_owner = cls.sanitize_identifier(owner)
        s_name = cls.sanitize_identifier(name)
        return f"{s_owner}_{s_name}"

    @classmethod
    def get_repo_local_path(cls, owner: str, name: str) -> Path:
        """Get the absolute filesystem path where the repository is cloned."""
        cls.ensure_directories()
        return cls.REPOSITORIES_DIR / cls.get_repo_dir_name(owner, name)

    @classmethod
    def get_analysis_file_path(cls, owner: str, name: str) -> Path:
        """Get the path to the cached analysis JSON file."""
        cls.ensure_directories()
        return cls.ANALYSIS_DIR / f"{cls.get_repo_dir_name(owner, name)}_analysis.json"

    @classmethod
    def is_cached(cls, owner: str, name: str) -> bool:
        """Check if an analysis result and cloned repository exist locally."""
        analysis_file = cls.get_analysis_file_path(owner, name)
        repo_dir = cls.get_repo_local_path(owner, name)
        return analysis_file.is_file() and repo_dir.is_dir()

    @classmethod
    def load_cached_analysis(cls, owner: str, name: str) -> Optional[Dict[str, Any]]:
        """Load and return cached analysis JSON if present and valid."""
        analysis_file = cls.get_analysis_file_path(owner, name)
        if analysis_file.is_file():
            try:
                with open(analysis_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["repository"]["is_cached"] = True
                    return data
            except Exception as ex:
                logger.warning(f"Error reading cached analysis {analysis_file}: {ex}")
        return None

    @classmethod
    def acquire_repository(
        cls,
        owner: str,
        name: str,
        clone_url: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Tuple[bool, str, Path]:
        """
        Safely acquire a repository by cloning it into data/repositories/
        using shallow clone (--depth 1) for speed and safety.

        Reuses existing clone if already present and force_refresh is False.

        Returns: (success: bool, message: str, local_path: Path)
        """
        cls.ensure_directories()
        local_path = cls.get_repo_local_path(owner, name)
        target_url = clone_url or f"https://github.com/{owner}/{name}.git"

        # Check if already cloned
        if local_path.is_dir() and not force_refresh:
            # Check if directory actually contains files beyond .git
            non_git_items = [p for p in local_path.iterdir() if p.name != ".git"]
            if non_git_items:
                return True, f"Reused existing local repository at {local_path.name}", local_path

        # If refresh requested and directory exists, remove it safely
        if local_path.is_dir():
            try:
                cls._safe_rmtree(local_path)
            except Exception as e:
                logger.warning(f"Failed to clear existing repo directory {local_path}: {e}")

        # Execute safe clone using GitPython or git CLI
        logger.info(f"Cloning {target_url} into {local_path} (shallow clone depth=1)")

        if GITPYTHON_AVAILABLE:
            try:
                git.Repo.clone_from(
                    url=target_url,
                    to_path=str(local_path),
                    depth=1,
                    multi_options=["--single-branch"],
                )
                return True, f"Successfully cloned {owner}/{name} using GitPython", local_path
            except Exception as ex:
                logger.warning(f"GitPython clone failed: {ex}. Falling back to git CLI.")

        # Fallback to subprocess git clone with strict safety
        import subprocess
        cmd = ["git", "clone", "--depth", "1", "--single-branch", target_url, str(local_path)]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if res.returncode == 0 and local_path.is_dir():
                return True, f"Successfully cloned {owner}/{name} using git CLI", local_path
            else:
                err_msg = res.stderr.strip() or res.stdout.strip() or f"Process returned code {res.returncode}"
                return False, f"Git clone failed: {err_msg}", local_path
        except subprocess.TimeoutExpired:
            return False, "Repository clone timed out after 90 seconds.", local_path
        except Exception as ex:
            return False, f"Failed to acquire repository: {str(ex)}", local_path

    @classmethod
    def _safe_rmtree(cls, path: Path) -> None:
        """Safely remove a directory tree, handling read-only git files on Windows."""
        import stat

        def on_rm_error(func, p, exc_info):
            try:
                os.chmod(p, stat.S_IWRITE)
                func(p)
            except Exception:
                pass

        shutil.rmtree(str(path), onerror=on_rm_error)

    @classmethod
    def classify_file(cls, filename: str, ext: str) -> Tuple[str, Optional[str]]:
        """
        Classify a file into category (source, documentation, configuration, other)
        and determine its programming language if detectable.

        Returns: (category, language)
        """
        lower_name = filename.lower()
        lower_ext = ext.lower()

        # Check special filenames first
        if lower_name in {"readme", "readme.md", "readme.rst", "readme.txt", "license", "licence", "copying", "contributing", "changelog"}:
            return "documentation", None

        if lower_name in {"dockerfile", "makefile", "vagrantfile", "gemfile", "procfile", "cmakelists.txt"}:
            return "configuration", None

        # Check programming language extensions
        if lower_ext in cls.LANGUAGE_EXTENSIONS:
            return "source", cls.LANGUAGE_EXTENSIONS[lower_ext]

        # Check documentation extensions
        if lower_ext in cls.DOC_EXTENSIONS:
            return "documentation", None

        # Check configuration extensions
        if lower_ext in cls.CONFIG_EXTENSIONS:
            return "configuration", None

        return "other", None

    @classmethod
    def format_size(cls, size_bytes: int) -> str:
        """Format byte size into human readable string (B, KB, MB)."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    @classmethod
    def analyze_repository(
        cls,
        owner: str,
        name: str,
        repo_url: Optional[str] = None,
        force_refresh: bool = False,
        repo_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Acquire (if needed) and perform basic static analysis of a repository.

        Extracts:
        - repository metadata
        - directory structure & tree
        - file list with size & classification
        - programming languages
        - file and directory counts & statistics

        Stores the result in data/analysis/{owner}_{name}_analysis.json.
        """
        cls.ensure_directories()
        canonical_url = repo_url or f"https://github.com/{owner}/{name}"

        # 1. Check local cache
        if not force_refresh:
            cached = cls.load_cached_analysis(owner, name)
            if cached:
                return {
                    "success": True,
                    "is_cached": True,
                    "message": f"Retrieved cached analysis for {owner}/{name}",
                    **cached,
                }

        # 2. Acquire / Clone repository
        if repo_path and repo_path.is_dir():
            local_path = repo_path
            acq_msg = "Analyzed provided local directory"
            acq_method = "local_path"
        else:
            success, acq_msg, local_path = cls.acquire_repository(
                owner=owner,
                name=name,
                clone_url=canonical_url,
                force_refresh=force_refresh,
            )
            if not success or not local_path.is_dir():
                return {
                    "success": False,
                    "error": acq_msg,
                    "repository": {
                        "owner": owner,
                        "name": name,
                        "full_name": f"{owner}/{name}",
                        "url": canonical_url,
                    },
                    "directories": [],
                    "files": [],
                    "languages": {},
                    "statistics": {},
                }
            acq_method = "git_clone"

        # 3. Static File System Scan
        files_list: List[Dict[str, Any]] = []
        directories_set: Set[str] = set()
        extensions_counter: Dict[str, int] = {}
        language_stats: Dict[str, Dict[str, Any]] = {}

        total_files = 0
        total_directories = 0
        source_files_count = 0
        doc_files_count = 0
        config_files_count = 0
        other_files_count = 0
        total_size_bytes = 0

        # Max file count limit to prevent memory exhaustion on giant projects
        MAX_FILES = 25000

        try:
            for root, dirs, files in os.walk(local_path):
                # Filter out ignored directories in-place to prevent os.walk from descending
                dirs[:] = [
                    d for d in dirs
                    if d.lower() not in cls.IGNORED_DIRECTORIES
                    and not d.startswith(".")
                ]

                # Relative directory path from repo root
                rel_dir = os.path.relpath(root, local_path).replace("\\", "/")
                if rel_dir != ".":
                    directories_set.add(rel_dir)

                for file_name in files:
                    lower_name = file_name.lower()
                    if lower_name in cls.IGNORED_FILES:
                        continue

                    total_files += 1
                    if total_files > MAX_FILES:
                        break

                    file_abs_path = Path(root) / file_name
                    rel_file_path = os.path.relpath(file_abs_path, local_path).replace("\\", "/")

                    # Safe file stat
                    try:
                        size_bytes = file_abs_path.stat().st_size
                    except Exception:
                        size_bytes = 0

                    total_size_bytes += size_bytes

                    ext = os.path.splitext(file_name)[1].lower()
                    if ext:
                        extensions_counter[ext] = extensions_counter.get(ext, 0) + 1

                    category, language = cls.classify_file(file_name, ext)

                    if category == "source":
                        source_files_count += 1
                        if language:
                            if language not in language_stats:
                                language_stats[language] = {"files_count": 0, "bytes": 0}
                            language_stats[language]["files_count"] += 1
                            language_stats[language]["bytes"] += size_bytes
                    elif category == "documentation":
                        doc_files_count += 1
                    elif category == "configuration":
                        config_files_count += 1
                    else:
                        other_files_count += 1

                    files_list.append({
                        "path": rel_file_path,
                        "name": file_name,
                        "directory": "" if rel_dir == "." else rel_dir,
                        "extension": ext or "none",
                        "language": language,
                        "category": category,
                        "size_bytes": size_bytes,
                        "size_formatted": cls.format_size(size_bytes),
                    })

                if total_files > MAX_FILES:
                    break
        except Exception as scan_err:
            logger.error(f"Error during static repository scan: {scan_err}")

        total_directories = len(directories_set)

        # 4. Compute Language Percentages
        total_source_bytes = sum(item["bytes"] for item in language_stats.values()) or 1
        languages_result: Dict[str, Any] = {}

        # Sort languages by byte size descending
        sorted_languages = sorted(
            language_stats.items(),
            key=lambda x: (x[1]["bytes"], x[1]["files_count"]),
            reverse=True,
        )

        for lang, stats in sorted_languages:
            pct = round((stats["bytes"] / total_source_bytes) * 100, 1)
            languages_result[lang] = {
                "files_count": stats["files_count"],
                "bytes": stats["bytes"],
                "size_formatted": cls.format_size(stats["bytes"]),
                "percentage": pct,
            }

        primary_lang = sorted_languages[0][0] if sorted_languages else "Not specified"

        # 5. Build Directory Tree Structure
        sorted_dirs = sorted(list(directories_set))
        directory_tree = cls._build_directory_tree(
            repo_name=name,
            files_list=files_list,
            directories=sorted_dirs,
        )

        # 6. Assemble Final Structured Result
        acquired_time = datetime.now(timezone.utc).isoformat()
        try:
            rel_local_path = str(local_path.relative_to(cls.BASE_DIR)).replace("\\", "/")
        except ValueError:
            rel_local_path = str(local_path).replace("\\", "/")

        structured_result: Dict[str, Any] = {
            "repository": {
                "owner": owner,
                "name": name,
                "full_name": f"{owner}/{name}",
                "url": canonical_url,
                "local_path": rel_local_path,
                "acquired_at": acquired_time,
                "acquisition_method": acq_method,
                "is_cached": False,
            },
            "directories": sorted_dirs,
            "directory_tree": directory_tree,
            "files": files_list,
            "languages": languages_result,
            "extensions": dict(sorted(extensions_counter.items(), key=lambda x: x[1], reverse=True)),
            "statistics": {
                "total_files": total_files,
                "total_directories": total_directories,
                "source_files": source_files_count,
                "doc_files": doc_files_count,
                "config_files": config_files_count,
                "other_files": other_files_count,
                "total_size_bytes": total_size_bytes,
                "total_size_formatted": cls.format_size(total_size_bytes),
                "primary_language": primary_lang,
            },
        }

        # 7. Persist Result to data/analysis/ for reuse in later phases
        try:
            analysis_file = cls.get_analysis_file_path(owner, name)
            with open(analysis_file, "w", encoding="utf-8") as f:
                json.dump(structured_result, f, indent=2)
            logger.info(f"Persisted analysis result to {analysis_file}")
        except Exception as save_err:
            logger.warning(f"Could not persist analysis file: {save_err}")

        return {
            "success": True,
            "is_cached": False,
            "message": f"Successfully analyzed {owner}/{name}",
            **structured_result,
        }

    @classmethod
    def _build_directory_tree(
        cls,
        repo_name: str,
        files_list: List[Dict[str, Any]],
        directories: List[str],
    ) -> Dict[str, Any]:
        """
        Construct a hierarchical tree dictionary suitable for interactive file tree UIs.
        """
        root_node = {
            "name": repo_name,
            "type": "directory",
            "path": "",
            "children": [],
        }

        # Lookup table for directory nodes
        dir_nodes: Dict[str, Dict[str, Any]] = {"": root_node}

        # First, ensure all directory nodes exist hierarchically
        for d in directories:
            parts = d.split("/")
            current_path = ""
            for part in parts:
                parent_path = current_path
                current_path = f"{current_path}/{part}" if current_path else part
                if current_path not in dir_nodes:
                    node = {
                        "name": part,
                        "type": "directory",
                        "path": current_path,
                        "children": [],
                    }
                    dir_nodes[current_path] = node
                    dir_nodes[parent_path]["children"].append(node)

        # Next, place files under their respective directory node
        # Cap tree files to 500 for fast UI rendering
        for f in files_list[:500]:
            parent_dir = f["directory"]
            if parent_dir in dir_nodes:
                dir_nodes[parent_dir]["children"].append({
                    "name": f["name"],
                    "type": "file",
                    "path": f["path"],
                    "extension": f["extension"],
                    "language": f["language"],
                    "category": f["category"],
                    "size_formatted": f["size_formatted"],
                })

        return root_node

    @classmethod
    def get_cached_analyses(cls) -> List[Dict[str, Any]]:
        """
        List all available cached repository analyses in data/analysis/.
        """
        cls.ensure_directories()
        cached_list = []
        if not cls.ANALYSIS_DIR.is_dir():
            return []

        for p in cls.ANALYSIS_DIR.glob("*_analysis.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    repo_info = data.get("repository", {})
                    stats = data.get("statistics", {})
                    cached_list.append({
                        "owner": repo_info.get("owner"),
                        "name": repo_info.get("name"),
                        "full_name": repo_info.get("full_name"),
                        "url": repo_info.get("url"),
                        "acquired_at": repo_info.get("acquired_at"),
                        "primary_language": stats.get("primary_language"),
                        "total_files": stats.get("total_files"),
                        "total_size_formatted": stats.get("total_size_formatted"),
                    })
            except Exception:
                continue

        return cached_list
