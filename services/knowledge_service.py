"""
Centralized Shared Repository Knowledge Service for CodeLens AI.

Provides a unified structured knowledge layer combining:
- Phase 5: File & Directory hierarchy, Language identification, Codebase metrics.
- Phase 6: AST-extracted Classes, Functions, Methods, Imports, Dependencies, Entry points, Relationships.

Serves as the single source of truth for:
- Semantic Code Graph (Phase 7)
- Architecture Graph & Clustering
- RAG & Vector indexing (Future)
- AI Comprehension Agents (Future)
- Automatic Report Generation (Future)
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from models.knowledge import (
    DirectoryInfo,
    FileInfo,
    RepositoryInfo,
    SharedRepositoryKnowledge,
)
from services.ast_service import DeepCodeAnalysisService

logger = logging.getLogger(__name__)


class KnowledgeService:
    """Manages the centralized Shared Repository Knowledge representations."""

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    ANALYSIS_DIR = DATA_DIR / "analysis"
    REPOSITORIES_DIR = DATA_DIR / "repositories"

    @classmethod
    def get_knowledge_file_path(cls, owner: str, name: str) -> Path:
        """Return path to saved knowledge JSON."""
        cls.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        return cls.ANALYSIS_DIR / f"{owner}_{name}_knowledge.json"

    @classmethod
    def get_phase5_analysis_path(cls, owner: str, name: str) -> Path:
        """Return path to saved Phase 5 file analysis JSON."""
        return cls.ANALYSIS_DIR / f"{owner}_{name}_analysis.json"

    @classmethod
    def save_knowledge(cls, owner: str, name: str, knowledge: SharedRepositoryKnowledge) -> Path:
        """Persist SharedRepositoryKnowledge object to disk JSON."""
        k_file = cls.get_knowledge_file_path(owner, name)
        with open(k_file, "w", encoding="utf-8") as f:
            f.write(knowledge.to_json())
        return k_file

    @classmethod
    def get_shared_knowledge(
        cls,
        owner: str,
        name: str,
        repo_path: Optional[Path] = None,
        force_refresh: bool = False,
    ) -> SharedRepositoryKnowledge:
        """
        Retrieve or build the centralized SharedRepositoryKnowledge object.
        Reuses cached AST knowledge if available.
        """
        k_file = cls.get_knowledge_file_path(owner, name)

        raw_data: Optional[Dict[str, Any]] = None

        if not force_refresh and k_file.is_file():
            try:
                with open(k_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                logger.info(f"Loaded existing Shared Knowledge for {owner}/{name} from cache.")
            except Exception as ex:
                logger.warning(f"Error loading knowledge cache from {k_file}: {ex}")

        if not raw_data:
            logger.info(f"Generating new AST knowledge for {owner}/{name}...")
            ast_res = DeepCodeAnalysisService.analyze_codebase(
                owner=owner,
                name=name,
                repo_path=repo_path,
                force_refresh=force_refresh,
            )
            raw_data = ast_res

        # Reconstruct typed SharedRepositoryKnowledge
        knowledge = SharedRepositoryKnowledge.from_dict(raw_data)

        # Merge with Phase 5 metadata if available to ensure directory and file completeness
        cls._enrich_from_phase5(knowledge, owner, name)

        return knowledge

    @classmethod
    def _enrich_from_phase5(cls, knowledge: SharedRepositoryKnowledge, owner: str, name: str) -> None:
        """Enrich knowledge with file sizes, languages, and directory tree from Phase 5."""
        p5_file = cls.get_phase5_analysis_path(owner, name)
        if not p5_file.is_file():
            return

        try:
            with open(p5_file, "r", encoding="utf-8") as f:
                p5_data = json.load(f)

            # Enrich repository primary language and stats if missing
            if not knowledge.repository.primary_language and p5_data.get("primary_language"):
                knowledge.repository.primary_language = p5_data["primary_language"]

            # Map existing file paths for fast lookup
            file_map = {f.path: f for f in knowledge.files}

            p5_files = p5_data.get("files", [])
            for pf in p5_files:
                p_path = pf.get("path")
                if not p_path:
                    continue

                if p_path in file_map:
                    # Update file size and language if present in Phase 5
                    target_file = file_map[p_path]
                    if pf.get("size_bytes") and not target_file.size:
                        target_file.size = pf["size_bytes"]
                    if pf.get("language") and not target_file.language:
                        target_file.language = pf["language"]
                else:
                    # Add non-source file (config, docs, markdown, etc.)
                    new_file = FileInfo(
                        path=p_path,
                        name=pf.get("name", p_path.split("/")[-1]),
                        extension=pf.get("extension", ""),
                        language=pf.get("language"),
                        size=pf.get("size_bytes"),
                    )
                    knowledge.files.append(new_file)
                    file_map[p_path] = new_file

            # Enrich directories if needed
            known_dirs = {d.path for d in knowledge.directories}
            p5_dirs = p5_data.get("directories", [])
            for d in p5_dirs:
                d_path = d.get("path") if isinstance(d, dict) else str(d)
                if d_path and d_path not in known_dirs:
                    d_name = d.get("name", d_path.split("/")[-1]) if isinstance(d, dict) else d_path.split("/")[-1]
                    parent = d_path.rsplit("/", 1)[0] if "/" in d_path else None
                    knowledge.directories.append(DirectoryInfo(path=d_path, name=d_name, parent=parent))
                    known_dirs.add(d_path)

        except Exception as ex:
            logger.debug(f"Could not merge Phase 5 analysis into Shared Knowledge: {ex}")
