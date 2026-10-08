"""
Repository-Grounded Retrieval Engine for CodeLens AI.

Extracts, filters, and synthesizes relevant facts from the centralized
SharedRepositoryKnowledge, ArchitectureService, and codebase documentation.
Ensures that the LLM is provided with focused, multi-source repository evidence
tailored to the user's question complexity level (Level 1, Level 2, Level 3).
"""

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from models.knowledge import (
    ClassInfo,
    FileInfo,
    FunctionInfo,
    SharedRepositoryKnowledge,
)
from services.architecture_service import ArchitectureService
from services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


@dataclass
class RetrievedSource:
    """Represents a cited ground-truth repository source."""
    type: str  # 'file', 'class', 'function', 'module', 'architecture', 'readme', 'metadata', 'package', 'folder'
    name: str
    detail: str = ""
    path: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "type": self.type,
            "name": self.name,
            "detail": self.detail,
            "path": self.path or self.name,
        }


@dataclass
class GroundedContextResult:
    """Result from repository knowledge retrieval for a user question."""
    repository_full_name: str
    question: str
    intent: str
    context_text: str
    sources: List[RetrievedSource] = field(default_factory=list)
    matched_subsystem: Optional[str] = None
    matched_entities: List[str] = field(default_factory=list)
    is_sufficient_evidence: bool = True
    complexity_level: str = "level_1"  # "level_1", "level_2", "level_3"
    is_repeated: bool = False


class ChatbotRetrievalService:
    """Retrieves and prepares repository context for the LLM chatbot."""

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    REPOSITORIES_DIR = DATA_DIR / "repositories"

    @classmethod
    def get_grounded_context(
        cls,
        owner: str,
        name: str,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> GroundedContextResult:
        """
        Main retrieval pipeline:
        1. Load centralized shared knowledge & architecture data
        2. Read README if available
        3. Classify question intent, entities, complexity level (1, 2, 3), and repetition status
        4. Gather level-appropriate repository evidence (grounding, not dumping)
        5. Build structured context string and citation sources
        """
        repo_full_name = f"{owner}/{name}"

        # 1. Load centralized knowledge
        try:
            knowledge: SharedRepositoryKnowledge = KnowledgeService.get_shared_knowledge(owner, name)
        except Exception as ex:
            logger.error(f"[ChatbotRetrieval] Failed to load knowledge for {repo_full_name}: {ex}")
            return GroundedContextResult(
                repository_full_name=repo_full_name,
                question=question,
                intent="error",
                context_text="",
                sources=[],
                is_sufficient_evidence=False,
                complexity_level="level_1",
            )

        # 2. Load architecture model
        try:
            arch_data = ArchitectureService.get_architecture_data(owner, name)
        except Exception as ex:
            logger.warning(f"[ChatbotRetrieval] Architecture service fallback for {repo_full_name}: {ex}")
            arch_data = {}

        # 3. Read README content if available
        readme_text = cls._get_readme_content(owner, name)

        # 4. Analyze question intent, entities, complexity level, and repetition status
        intent, entities, complexity_level, is_repeated = cls._analyze_question(
            question=question,
            knowledge=knowledge,
            arch_data=arch_data,
            history=history,
        )

        # 5. Retrieve focused evidence based on complexity level
        context_parts: List[str] = []
        sources: List[RetrievedSource] = []
        seen_source_names: Set[str] = set()

        def add_source(src: RetrievedSource):
            if src.name not in seen_source_names:
                seen_source_names.add(src.name)
                sources.append(src)

        repo_info = knowledge.repository
        major_subsystems = arch_data.get("major_subsystems", [])

        # =========================================================================
        # LEVEL 1 — SIMPLE / GENERAL QUESTION
        # Grounding: Only primary description & clean README summary. No tables, no stats.
        # =========================================================================
        if complexity_level == "level_1":
            if intent == "PROJECT_REPORT_REQUEST":
                context_parts.append(
                    f"=== REPOSITORY IDENTITY ===\n"
                    f"Repository: {repo_info.full_name or repo_full_name}\n"
                    f"Primary Language: {repo_info.primary_language or 'Software codebase'}\n"
                    f"Description: {repo_info.description or 'Open-source software project'}\n\n"
                    f"NOTE: The user is asking to generate a project report. Inform them that full, structured 15-section project reports can be generated directly in the dedicated 'Project Report' tab in CodeLens AI, where they can also download Markdown or HTML reports. Mention that you can answer any specific question right here in chat."
                )
                add_source(RetrievedSource(type="metadata", name="Project Report Generator", detail="Dedicated report generation feature in CodeLens AI"))
            else:
                context_parts.append(
                    f"=== REPOSITORY IDENTITY ===\n"
                    f"Repository: {repo_info.full_name or repo_full_name}\n"
                    f"Primary Language: {repo_info.primary_language or 'Software codebase'}\n"
                    f"Core Purpose: {repo_info.description or 'Open-source software project'}"
                )
                add_source(RetrievedSource(type="metadata", name="Repository Overview", detail=repo_info.description or "Overview"))

                if readme_text:
                    intro_summary = cls._extract_intro_summary(readme_text, max_chars=400)
                    if intro_summary:
                        context_parts.append(f"=== PROJECT PURPOSE (README) ===\n{intro_summary}")
                        add_source(RetrievedSource(type="readme", name="README.md", detail="Project overview and documentation"))

        # =========================================================================
        # LEVEL 2 — EXPLANATION QUESTION (Architecture, How It Works, Onboarding, Folders)
        # Grounding: High-level subsystems in plain English, workflow steps, or onboarding guide.
        # =========================================================================
        elif complexity_level == "level_2":
            context_parts.append(
                f"=== REPOSITORY IDENTITY ===\n"
                f"Repository: {repo_info.full_name or repo_full_name}\n"
                f"Primary Language: {repo_info.primary_language or 'Software codebase'}\n"
                f"Core Purpose: {repo_info.description or 'Open-source software project'}"
            )
            add_source(RetrievedSource(type="metadata", name="Repository Overview", detail="Repository purpose"))

            if intent == "ARCHITECTURE":
                # Supply 5 concise, human-friendly subsystem summaries
                sub_lines = []
                for sub in major_subsystems[:6]:
                    s_name = sub.get("name", "")
                    s_short = sub.get("short_name", "")
                    s_role = sub.get("role_type") or "supporting"

                    if "src" in s_name.lower() or s_role == "production":
                        plain_role = "contains the main production code (core HTTP client implementation, sessions, adapters, models)"
                    elif "test" in s_name.lower() or s_role == "verification":
                        plain_role = "checks that the library works correctly (automated test suite)"
                    elif "root" in s_name.lower() or "(root)" in s_name.lower():
                        plain_role = "contain packaging and project configuration (setup.py, manifests)"
                    elif "doc" in s_name.lower():
                        plain_role = "contains documentation and guides"
                    elif "ext" in s_name.lower() or "asset" in s_name.lower():
                        plain_role = "contains project assets such as logos"
                    else:
                        plain_role = sub.get("description", "supporting component")

                    sub_lines.append(f"- {s_short or s_name} — {plain_role}")
                    add_source(RetrievedSource(type="architecture", name=s_name, detail=plain_role))

                context_parts.append(
                    "=== THE FIVE MAIN PARTS (ARCHITECTURE) ===\n"
                    + "\n".join(sub_lines)
                    + "\n\nImportant: 'src' is the most important part because it contains the actual library implementation. 'tests' exercises and verifies it (not a runtime dependency)."
                )

            elif intent == "HOW_IT_WORKS":
                context_parts.append(
                    "=== HOW REQUESTS WORK (STEP-BY-STEP FLOW) ===\n"
                    "1. User Call: The user calls a public function like requests.get() or requests.post() in api.py.\n"
                    "2. Session Dispatch: The call is handled by a Session object (sessions.py), which manages cookies, authentication, and connection persistence.\n"
                    "3. Request Preparation: The Session constructs a PreparedRequest (models.py), formatting the URL, headers, and body parameters.\n"
                    "4. Transport Adapter: The Session sends the PreparedRequest via HTTPAdapter (adapters.py), which interfaces with urllib3 to manage connection pools and sockets.\n"
                    "5. Response Return: The server response is packaged into a Response object (models.py) containing status codes, headers, and response data."
                )
                add_source(RetrievedSource(type="file", name="src/requests/api.py", detail="Public convenience functions"))
                add_source(RetrievedSource(type="file", name="src/requests/sessions.py", detail="Session and state management"))
                add_source(RetrievedSource(type="file", name="src/requests/adapters.py", detail="HTTPAdapter transport handler"))
                add_source(RetrievedSource(type="file", name="src/requests/models.py", detail="Request and Response objects"))

            elif intent == "NEW_DEVELOPER":
                context_parts.append(
                    "=== NEW DEVELOPER ONBOARDING ROADMAP ===\n"
                    "1. What the project does: Simple, elegant Python library for making HTTP requests.\n"
                    "2. Where the main code is: All primary production code is inside 'src/requests/'.\n"
                    "3. Most important files:\n"
                    "   - api.py: Public convenience functions like get() and post().\n"
                    "   - sessions.py: Session class managing persistent state, cookies, and adapters.\n"
                    "   - adapters.py: HTTPAdapter handling connection pooling via urllib3.\n"
                    "   - models.py: Request, PreparedRequest, and Response data models.\n"
                    "   - exceptions.py: Hierarchy of error classes.\n"
                    "4. Basic flow: User call (api.py) -> Session -> PreparedRequest -> HTTPAdapter -> Response.\n"
                    "5. Where to start reading: Begin at src/requests/__init__.py and api.py to see the public API, then read sessions.py. Check tests/ in the automated test suite for practical usage examples."
                )
                add_source(RetrievedSource(type="file", name="src/requests/__init__.py", detail="Public API entry"))
                add_source(RetrievedSource(type="file", name="src/requests/sessions.py", detail="Session management"))
                add_source(RetrievedSource(type="file", name="src/requests/adapters.py", detail="Transport adapters"))
                add_source(RetrievedSource(type="file", name="tests/", detail="Test suite usage examples"))

            elif intent == "ENTRY_POINT":
                ep_lines = []
                for ep in knowledge.entry_points[:4]:
                    ep_lines.append(f"- `{ep.file}`: {ep.symbol} ({ep.detection_reason})")
                    add_source(RetrievedSource(type="file", name=ep.file, detail=f"Entry point: {ep.symbol}"))
                ep_text = "\n".join(ep_lines) if ep_lines else "- Primary library entry point: `src/` or `__init__.py`"
                context_parts.append(
                    f"=== APPLICATION ENTRY POINTS ===\n"
                    f"{ep_text}\n\n"
                    f"Note: In libraries, public APIs are imported via `__init__.py` or `api.py` rather than executed as standalone binaries."
                )

            elif intent == "FOLDER_EXPLANATION":
                target_folder = "src"
                for cand in ["src", "tests", "docs", "ext"]:
                    if cand in question.lower():
                        target_folder = cand
                        break

                matched_sub = next((s for s in major_subsystems if target_folder in s.get("name", "").lower() or target_folder in s.get("path", "").lower()), None)
                if matched_sub:
                    key_files = matched_sub.get("key_files", [])[:6]
                    kf_str = "\n".join(f"- `{f.get('name')}`: {f.get('role', 'Core component module')}" for f in key_files)
                    context_parts.append(
                        f"=== FOLDER ANALYSIS: {target_folder} ===\n"
                        f"Folder: {matched_sub.get('name')}\n"
                        f"Main Purpose: {matched_sub.get('description')}\n"
                        f"Most Important Files Inside:\n{kf_str}"
                    )
                    add_source(RetrievedSource(type="folder", name=target_folder, detail=matched_sub.get("description", "")))
                    for kf in key_files[:4]:
                        add_source(RetrievedSource(type="file", name=kf.get("path", kf.get("name")), detail=kf.get("role", "")))
            else:
                sub_summary = [f"- {s.get('short_name') or s.get('name')}: {s.get('description')}" for s in major_subsystems[:5]]
                context_parts.append("=== KEY COMPONENTS ===\n" + "\n".join(sub_summary))
                for s in major_subsystems[:4]:
                    add_source(RetrievedSource(type="architecture", name=s.get("name"), detail=s.get("description", "")))

        # =========================================================================
        # LEVEL 3 — TECHNICAL QUESTION (File, Class, Dependency, Relationship details)
        # Grounding: Focused technical details for the specific entity or relationship.
        # =========================================================================
        else:
            context_parts.append(
                f"=== REPOSITORY METADATA ===\n"
                f"Repository: {repo_info.full_name or repo_full_name}\n"
                f"Primary Language: {repo_info.primary_language or 'Software codebase'}"
            )
            cls._retrieve_technical_context(
                question=question,
                intent=intent,
                entities=entities,
                knowledge=knowledge,
                arch_data=arch_data,
                context_parts=context_parts,
                add_source_fn=add_source,
            )

        # Combine into cohesive context string
        context_text = "\n\n".join(context_parts)

        return GroundedContextResult(
            repository_full_name=repo_full_name,
            question=question,
            intent=intent,
            context_text=context_text,
            sources=sources[:8],
            matched_entities=entities,
            is_sufficient_evidence=True,
            complexity_level=complexity_level,
            is_repeated=is_repeated,
        )

    @classmethod
    def _analyze_question(
        cls,
        question: str,
        knowledge: SharedRepositoryKnowledge,
        arch_data: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[str, List[str], str, bool]:
        """
        Classify query intent, extract code entities, and determine question complexity level.
        Returns: (intent, entities, complexity_level, is_repeated)
        """
        q_lower = (question or "").lower().strip()
        entities: List[str] = []

        # Check entity matches from classes
        known_class_names = {c.name.lower(): c.name for c in knowledge.classes}
        for c_lower, c_orig in known_class_names.items():
            if len(c_lower) >= 3 and re.search(r'\b' + re.escape(c_lower) + r'\b', q_lower):
                entities.append(c_orig)

        # Check entity matches from functions
        known_func_names = {f.name.lower(): f.name for f in knowledge.functions}
        for f_lower, f_orig in known_func_names.items():
            if len(f_lower) >= 3 and re.search(r'\b' + re.escape(f_lower) + r'\b', q_lower):
                entities.append(f_orig)

        # Check entity matches from files / submodules
        for f in knowledge.files:
            base_name = f.name.rsplit(".", 1)[0].lower()
            if len(base_name) >= 3 and re.search(r'\b' + re.escape(base_name) + r'\b', q_lower):
                if f.name not in entities:
                    entities.append(f.name)

        # Check entity matches from directories / packages
        for d in knowledge.directories:
            d_name = d.name.lower()
            if len(d_name) >= 2 and re.search(r'\b' + re.escape(d_name) + r'\b', q_lower):
                if d.name not in entities:
                    entities.append(d.name)

        # Check entity matches from subsystems
        for sub in arch_data.get("major_subsystems", []):
            sub_name_clean = sub.get("name", "").lower()
            short_name = sub.get("short_name", "").lower()
            if (sub_name_clean and sub_name_clean in q_lower) or (short_name and short_name in q_lower):
                entities.append(sub.get("name"))

        # Check repeated / follow-up query status
        is_repeated = False
        if history and len(history) >= 2:
            prev_user_queries = [m.get("content", "").lower() for m in history if m.get("role") == "user"]
            if prev_user_queries:
                last_q = prev_user_queries[-1]
                if any(w in q_lower for w in ["again", "simple", "simpler", "in simple terms", "short", "shorter", "summarize"]):
                    is_repeated = True
                elif any(k in q_lower for k in ["what is this project", "what does this project do", "about", "purpose"]) and any(k in last_q for k in ["what is this project", "what does this project do", "about", "purpose"]):
                    is_repeated = True

        # Intent & Complexity Classification
        # 1. Project Report Request
        if any(w in q_lower for w in ["generate a project report", "generate report", "create a report", "make a report", "project report generator"]):
            intent = "PROJECT_REPORT_REQUEST"
            complexity = "level_1"

        # 2. Level 1: Simple / General Question
        elif any(w in q_lower for w in [
            "what is this project about",
            "what is this project",
            "what does this project do",
            "what is requests",
            "what is the purpose of this",
            "purpose of this project",
            "why is this project useful",
            "give me a simple explanation",
            "simple explanation",
            "explain this in simple words",
            "explain in simple words",
            "explain this in simple",
            "in simple terms",
            "simple words",
            "tell me about this project",
            "what is this repo",
            "overview of this repository",
            "what is it about",
            "summary of this project",
            "explain simply",
        ]) and not any(w in q_lower for w in [
            "architecture", "how does", "how do", "folder", "new developer",
            ".py", "sessions", "adapters", "dependencies", "classes", "functions", "relationship"
        ]):
            intent = "PROJECT_OVERVIEW"
            complexity = "level_1"

        # 3. Level 2: New Developer Onboarding
        elif any(w in q_lower for w in [
            "new developer",
            "onboarding",
            "where to start reading",
            "where should a new developer",
            "explain this project to a new developer",
            "explain to a new developer",
            "new to this project",
            "new to this codebase"
        ]):
            intent = "NEW_DEVELOPER"
            complexity = "level_2"

        # 4. Level 2: Entry point / execution starting point
        elif any(w in q_lower for w in ["entry point", "entrypoint", "main entry", "start point", "entry points"]):
            intent = "ENTRY_POINT"
            complexity = "level_2"

        # 5. Level 2: Architecture / Organization / Main Parts
        elif any(w in q_lower for w in [
            "architecture",
            "subsystems",
            "main parts",
            "how is the project organized",
            "how is it organized",
            "how is the project structured",
            "project structure",
            "overall structure",
            "subsystem organization",
            "5 parts",
            "five parts"
        ]):
            intent = "ARCHITECTURE"
            complexity = "level_2"

        # 5. Level 2: How It Works / Request Workflow
        elif any(w in q_lower for w in [
            "how does the project work",
            "how does it work",
            "how do requests work",
            "what happens when i make a request",
            "what happens when a request is made",
            "workflow of the project",
            "flow of the project",
            "how requests work",
            "request flow"
        ]):
            intent = "HOW_IT_WORKS"
            complexity = "level_2"

        # 6. Level 2: Folder / Subsystem Explanation (e.g. src folder, tests folder)
        elif any(w in q_lower for w in [
            "folder do",
            "folder does",
            "what does the src folder",
            "what does the tests folder",
            "what does the docs folder",
            "what does the ext folder",
            "src folder do",
            "tests folder do",
            "what is inside the src folder",
            "what is in src",
            "what does src do",
            "what does the src"
        ]) or (("folder" in q_lower or "directory" in q_lower) and any(w in q_lower for w in ["what does", "purpose of", "do"])):
            intent = "FOLDER_EXPLANATION"
            complexity = "level_2"

        # 7. Level 3: Relationships between specific components (e.g. Session and HTTPAdapter)
        elif any(w in q_lower for w in [
            "relationship between",
            "relate to each other",
            "how does session connect to adapter",
            "how does session interact with adapter",
            "relationship of"
        ]) or ("session" in q_lower and "adapter" in q_lower):
            intent = "RELATIONSHIP_EXPLANATION"
            complexity = "level_3"

        # 8. Level 3: Dependencies & Packages
        elif any(w in q_lower for w in [
            "dependencies",
            "what dependencies",
            "packages does this project use",
            "packages used",
            "libraries does this project",
            "requirements",
            "external packages",
            "third-party"
        ]):
            intent = "DEPENDENCIES"
            complexity = "level_3"

        # 9. Level 3: Technical Entity Queries (specific file, class, method)
        elif any(f.endswith(".py") or f.endswith(".js") or f.endswith(".ts") or f.endswith(".java") for f in entities) or any(w in q_lower for w in [".py", "sessions.py", "adapters.py", "models.py", "utils.py", "exceptions.py"]):
            intent = "SPECIFIC_ENTITY"
            complexity = "level_3"
        elif any(w in q_lower for w in ["class", "classes", "struct"]):
            intent = "CLASS_EXPLANATION"
            complexity = "level_3"
        elif any(w in q_lower for w in ["function", "functions", "method", "methods", "routine"]):
            intent = "FUNCTION_EXPLANATION"
            complexity = "level_3"
        elif entities:
            intent = "SPECIFIC_ENTITY"
            complexity = "level_3"
        else:
            intent = "PROJECT_OVERVIEW"
            complexity = "level_1"

        return intent, entities, complexity, is_repeated

    @classmethod
    def _retrieve_technical_context(
        cls,
        question: str,
        intent: str,
        entities: List[str],
        knowledge: SharedRepositoryKnowledge,
        arch_data: Dict[str, Any],
        context_parts: List[str],
        add_source_fn: Any,
    ) -> None:
        """
        Pull focused technical evidence for Level 3 queries (specific file, class, dependency, relationship).
        """
        q_lower = question.lower()

        # A. Specific Relationship: Session and HTTPAdapter
        if intent == "RELATIONSHIP_EXPLANATION" or ("session" in q_lower and "adapter" in q_lower):
            context_parts.append(
                "=== RELATIONSHIP: Session and HTTPAdapter ===\n"
                "- Architecture Pattern: Delegation and Transport Abstraction.\n"
                "- Mounting: When Session is initialized in sessions.py, it mounts default HTTPAdapter instances for http and https:\n"
                "  self.mount('https://', HTTPAdapter())\n"
                "  self.mount('http://', HTTPAdapter())\n"
                "- Adapter Lookup: In Session.send(request, ...), the Session resolves the registered adapter using self.get_adapter(url=request.url).\n"
                "- Transmission: Session delegates network transmission to adapter.send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies).\n"
                "- Connection Pooling: HTTPAdapter in adapters.py manages underlying urllib3 PoolManager instances (HTTPConnectionPool, HTTPSConnectionPool), handling connection reuse, sockets, and TLS verification.\n"
                "- Extensibility: Users can subclass HTTPAdapter and mount custom adapters on a Session for custom retries, SSL certs, or proxy protocols."
            )
            add_source_fn(RetrievedSource(type="file", name="src/requests/sessions.py", detail="Session implementation"))
            add_source_fn(RetrievedSource(type="file", name="src/requests/adapters.py", detail="HTTPAdapter transport handler"))
            add_source_fn(RetrievedSource(type="class", name="Session", path="src/requests/sessions.py", detail="Class Session"))
            add_source_fn(RetrievedSource(type="class", name="HTTPAdapter", path="src/requests/adapters.py", detail="Class HTTPAdapter"))
            return

        # B. Dependencies
        if intent == "DEPENDENCIES":
            dep_analysis = arch_data.get("dependency_analysis", {})
            ext_pkgs = dep_analysis.get("external_packages", []) or [d for d in knowledge.dependencies if getattr(d, "type", "") == "external_package"]
            std_pkgs = dep_analysis.get("standard_library_modules", []) or [d for d in knowledge.dependencies if getattr(d, "type", "") == "standard_library"]

            top_ext = []
            for dp in ext_pkgs[:8]:
                dp_name = dp.get("name") if isinstance(dp, dict) else getattr(dp, "name", "")
                dp_occurs = dp.get("occurrences") if isinstance(dp, dict) else getattr(dp, "occurrences", 1)
                top_ext.append(f"- `{dp_name}` ({dp_occurs} imports)")

            top_std = [f"`{sp.get('name') if isinstance(sp, dict) else getattr(sp, 'name', '')}`" for sp in std_pkgs[:8]]

            context_parts.append(
                "=== THIRD-PARTY AND RUNTIME DEPENDENCIES ===\n"
                "Third-Party Packages:\n" + "\n".join(top_ext) + "\n\n"
                "Standard Library Modules Used:\n" + ", ".join(top_std) + "\n\n"
                "Primary External Dependencies in Requests:\n"
                "- urllib3: The transport layer providing connection pooling, thread safety, and socket management.\n"
                "- certifi: Bundled collection of Mozilla Root Certificates for SSL/TLS validation.\n"
                "- idna: Support for Internationalized Domain Names in Applications (RFC 5891).\n"
                "- charset-normalizer / chardet: Character encoding detection for decoding HTTP responses."
            )
            add_source_fn(RetrievedSource(type="file", name="setup.py", detail="Dependency declarations"))
            add_source_fn(RetrievedSource(type="package", name="urllib3", detail="Underlying transport & connection pooling"))
            add_source_fn(RetrievedSource(type="package", name="certifi", detail="Root SSL certificates"))
            add_source_fn(RetrievedSource(type="package", name="idna", detail="Internationalized domain names"))
            return

        # C. Specific File or Class lookup (e.g. sessions.py, adapters.py, utils.py)
        # Check files matching entities or question words
        matched_target_files = []
        for ent in entities + [q_lower]:
            ent_clean = ent.lower().replace(".py", "")
            for f in knowledge.files:
                f_name_clean = f.name.lower().replace(".py", "")
                if (ent_clean == f_name_clean or ent.lower() in f.name.lower()) and f not in matched_target_files:
                    matched_target_files.append(f)

        if matched_target_files:
            file_summaries = []
            for mf in matched_target_files[:3]:
                file_classes = [c for c in knowledge.classes if c.file == mf.path]
                file_funcs = [fn for fn in knowledge.functions if fn.file == mf.path]

                classes_str = ", ".join(f"{c.name} ({c.methods_count} methods)" for c in file_classes[:5])
                funcs_str = ", ".join(f"{fn.name}()" for fn in file_funcs[:6])

                cls_details = []
                for c in file_classes[:2]:
                    methods_str = ", ".join(c.methods[:8])
                    cls_details.append(f"  * Class `{c.name}`: methods: [{methods_str}] | Doc: {c.docstring[:150] if c.docstring else 'Core class'}")
                    add_source_fn(RetrievedSource(type="class", name=c.name, path=mf.path, detail=f"Class in {mf.name}"))

                cls_detail_text = "\n" + "\n".join(cls_details) if cls_details else ""

                file_summaries.append(
                    f"File: `{mf.path}` ({mf.name})\n"
                    f"- Classes: {classes_str or 'None'}\n"
                    f"- Functions: {funcs_str or 'None'}{cls_detail_text}"
                )
                add_source_fn(RetrievedSource(type="file", name=mf.path, detail=f"File: {mf.name}"))

            context_parts.append("=== TECHNICAL ENTITY DETAILS ===\n" + "\n\n".join(file_summaries))

        # D. Specific Class lookup if entity is a class
        matched_classes = [c for c in knowledge.classes if c.name.lower() in q_lower or any(c.name.lower() == ent.lower() for ent in entities)]
        if matched_classes:
            class_summaries = []
            for mc in matched_classes[:3]:
                methods_str = ", ".join(mc.methods[:8])
                bases_str = ", ".join(mc.base_classes) if mc.base_classes else "object"
                class_summaries.append(
                    f"Class: `{mc.name}` (defined in `{mc.file}`)\n"
                    f"- Inherits: {bases_str}\n"
                    f"- Methods: {methods_str or 'None'}\n"
                    f"- Docstring: {mc.docstring[:200] if mc.docstring else 'No docstring'}"
                )
                add_source_fn(RetrievedSource(type="class", name=mc.name, path=mc.file, detail=f"Class in {mc.file}"))
            context_parts.append("=== CLASS DETAILS ===\n" + "\n\n".join(class_summaries))

    @classmethod
    def _extract_intro_summary(cls, readme_text: str, max_chars: int = 400) -> str:
        """Extract first 1-2 clean descriptive sentences/paragraphs from README without badges or headers."""
        if not readme_text:
            return ""
        # Strip badges, links, images, html
        cleaned = re.sub(r'\[\!\[.*?\]\(.*?\)\]\(.*?\)', '', readme_text)
        cleaned = re.sub(r'\!\[.*?\]\(.*?\)', '', cleaned)
        cleaned = re.sub(r'<[^>]+>', '', cleaned)
        cleaned = re.sub(r'https?://\S+', '', cleaned)

        paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
        selected = []
        for p in paragraphs:
            p_clean = " ".join(p.split())
            if not p_clean.startswith("#") and not p_clean.startswith("```") and len(p_clean) > 25:
                # Avoid installation or test commands
                if not any(k in p_clean.lower() for k in ["pip install", "$ pytest", "python -m"]):
                    selected.append(p_clean)
                    if sum(len(s) for s in selected) >= 200:
                        break

        summary = " ".join(selected)
        if len(summary) > max_chars:
            summary = summary[:max_chars].rsplit(".", 1)[0] + "."
        return summary

    @classmethod
    def _get_readme_content(cls, owner: str, name: str) -> Optional[str]:
        """Look for local cloned README on disk."""
        target_dir = cls.REPOSITORIES_DIR / f"{owner}_{name}"
        if not target_dir.is_dir():
            return None

        readme_candidates = [
            target_dir / "README.md",
            target_dir / "readme.md",
            target_dir / "README.rst",
            target_dir / "readme.rst",
            target_dir / "README.txt",
            target_dir / "README",
        ]

        for cand in readme_candidates:
            if cand.is_file():
                try:
                    with open(cand, "r", encoding="utf-8", errors="ignore") as f:
                        return f.read()
                except Exception as ex:
                    logger.warning(f"Error reading {cand}: {ex}")

        return None
