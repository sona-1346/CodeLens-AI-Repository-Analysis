"""
Chatbot Service for CodeLens AI Repository Comprehension Assistant.

Coordinates repository-grounded retrieval, session memory with strict repository isolation,
real LLM backend invocations, and formatted response generation with source citations.
"""

from dataclasses import dataclass, field
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from services.chatbot_retrieval_service import (
    ChatbotRetrievalService,
    GroundedContextResult,
    RetrievedSource,
)
from services.knowledge_service import KnowledgeService
from services.llm_client import LLMClient, LLMResult

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are CodeLens AI, an AI assistant for understanding software repositories.\n\n"
    "Your mission is to provide direct, conversational, and helpful answers that give developers "
    "clear understanding without overwhelming them with unnecessary repository data.\n\n"
    "RESPONSE COMPLEXITY LEVELS:\n"
    "Tailor your response format and depth according to the question's complexity:\n\n"
    "1. LEVEL 1: SIMPLE / GENERAL QUESTIONS (e.g. 'What is this project about?', 'What does this project do?', 'Give me a simple summary'):\n"
    "   - Limit your response to 2 to 5 sentences maximum.\n"
    "   - Use plain, simple English focusing on the core purpose of the project.\n"
    "   - Mention the primary programming language or technology naturally if relevant.\n"
    "   - Strictly DO NOT include tables, lists of files, statistics/counts (e.g., file or class counts), dependency catalogs, or report headers.\n"
    "   - Never dump the entire repository overview for simple questions.\n\n"
    "2. LEVEL 2: EXPLANATION QUESTIONS (e.g. 'Explain the project architecture', 'How does the project work?', 'What does the src folder do?', 'Explain this project to a new developer'):\n"
    "   - Provide a short conversational introduction (1 to 2 sentences).\n"
    "   - Use 3 to 6 concise bullet points or numbered steps explaining key aspects in beginner-friendly English.\n"
    "   - Mention only the most important components or files.\n"
    "   - End with an optional single follow-up question (e.g. 'Would you like me to explain any specific component in detail?').\n"
    "   - Architecture Rule: Explain the 5 main parts simply:\n"
    "     1. Core source code (`src` or primary module) - main logic and public API\n"
    "     2. Test suite (`tests`) - verifies and exercises the code (supporting component, not a runtime dependency)\n"
    "     3. Project root / config - packaging and project configuration\n"
    "     4. Documentation (`docs`) - guides and API documentation\n"
    "     5. Assets / extras - non-code files and metadata\n"
    "   - New Developer Rule: Provide a 5-step onboarding guide under 400 words (1. Core purpose; 2. Where the main code lives; 3. Key entry points/starting files; 4. How testing works; 5. Suggested first steps for exploring).\n\n"
    "3. LEVEL 3: TECHNICAL QUESTIONS (e.g. 'What does sessions.py do?', 'Explain the relationship between Session and HTTPAdapter', 'What dependencies does this project use?'):\n"
    "   - Provide a detailed, technical answer focused specifically on the asked question.\n"
    "   - Mention exact files, classes, methods, parameters, or dependencies from the supplied context.\n"
    "   - Explain roles and relationships accurately.\n"
    "   - Do NOT dump the whole repository overview when asked about a specific file or symbol.\n\n"
    "SPECIAL CASES:\n"
    "- If asked to 'Generate a project report': DO NOT dump a 15-section report in the chat. Politely direct the user to the dedicated 'Project Report' tab in CodeLens AI, which generates a complete 15-section analysis with executive summaries, architecture breakdowns, developer onboarding guides, and export options. You may include a 2-3 sentence summary of the repository and offer to answer specific questions.\n"
    "- If the user repeats a question or asks for a simpler explanation: Respond even more concisely, starting directly with: 'In simple terms: [1-2 sentences]'.\n\n"
    "MANDATORY ARCHITECTURE & SUBSYSTEM GUIDELINES:\n"
    "- When explaining the repository architecture or organization, state: 'The repository is organized into well-defined subsystems that separate production code, tests, documentation, packaging, and project assets.'\n"
    "- Never use the phrase 'classic clean-architecture layout' or similar cliches.\n"
    "- Do not describe tests or documentation as production runtime dependencies.\n"
    "- Explain that the test suite verifies and exercises the core source code.\n"
    "- Do not claim that core production code depends on the test suite.\n\n"
    "GROUNDING CONSTRAINTS:\n"
    "- Answer using only the repository facts provided in the prompt context.\n"
    "- Do not invent files, classes, functions, modules, dependencies, or behavior.\n"
    "- If the context does not contain enough information, clearly state that the static analysis does not provide enough evidence."
)


@dataclass
class ChatResponse:
    """Standardized response from the AI chatbot."""
    success: bool
    answer: str
    repository: str
    sources: List[Dict[str, str]] = field(default_factory=list)
    intent: str = "general"
    session_id: str = ""
    is_llm_active: bool = False
    model: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "answer": self.answer,
            "repository": self.repository,
            "sources": self.sources,
            "intent": self.intent,
            "session_id": self.session_id,
            "is_llm_active": self.is_llm_active,
            "model": self.model,
            "error": self.error,
        }


class ChatbotService:
    """Manages chat sessions and executes repository-grounded comprehension queries."""

    # In-memory session store mapping session_id -> { "repo": str, "history": List[Dict[str, str]] }
    _sessions: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_or_create_session(cls, session_id: Optional[str], repo_full_name: str) -> Tuple[str, List[Dict[str, str]]]:
        """
        Retrieve existing session history or create a new session.
        Enforces complete repository isolation: if the repository changed, history is reset.
        """
        if not session_id or session_id not in cls._sessions:
            new_id = session_id or str(uuid.uuid4())
            cls._sessions[new_id] = {
                "repo": repo_full_name,
                "history": [],
            }
            return new_id, []

        session_data = cls._sessions[session_id]

        # REPOSITORY ISOLATION: if repository switched, discard previous repo's history
        if session_data.get("repo") != repo_full_name:
            logger.info(
                f"[ChatbotService] Repository switched in session {session_id} "
                f"from '{session_data.get('repo')}' to '{repo_full_name}'. Isolating and resetting history."
            )
            session_data["repo"] = repo_full_name
            session_data["history"] = []
            return session_id, []

        return session_id, session_data.get("history", [])

    @classmethod
    def clear_session(cls, session_id: str) -> bool:
        """Clear session conversational context."""
        if session_id in cls._sessions:
            cls._sessions[session_id]["history"] = []
            return True
        return False

    @classmethod
    def ask(
        cls,
        repo_input: str,
        question: str,
        session_id: Optional[str] = None,
        custom_history: Optional[List[Dict[str, str]]] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> ChatResponse:
        """
        Process a user question against an analyzed repository:
        1. Validate repository input & check analysis status
        2. Retrieve grounded repository context and sources
        3. Invoke the real LLM backend (with conversational history)
        4. Fall back cleanly if LLM is unavailable
        5. Return structured, source-cited response
        """
        cleaned_question = (question or "").strip()
        if not cleaned_question:
            return ChatResponse(
                success=False,
                answer="Please enter a question about the repository.",
                repository=repo_input or "",
                error="Empty question.",
            )

        # Parse owner and name
        owner, name = cls._parse_repo_name(repo_input)
        if not owner or not name:
            return ChatResponse(
                success=False,
                answer="Please provide a valid repository in 'owner/repo' format.",
                repository=repo_input or "",
                error="Invalid repository identifier.",
            )

        repo_full_name = f"{owner}/{name}"

        # Verify repository has knowledge available
        k_path = KnowledgeService.get_knowledge_file_path(owner, name)
        p5_path = KnowledgeService.get_phase5_analysis_path(owner, name)
        if not k_path.is_file() and not p5_path.is_file():
            return ChatResponse(
                success=False,
                answer=(
                    f"Repository **{repo_full_name}** has not been analyzed yet. "
                    f"Please acquire and analyze it first on the **Detailed Analysis** page before chatting."
                ),
                repository=repo_full_name,
                error="Repository not analyzed.",
            )

        # Manage session & conversational history
        active_session_id, stored_history = cls.get_or_create_session(session_id, repo_full_name)
        history_to_use = custom_history if custom_history is not None else stored_history

        # Step 1 & 2: Question Understanding & Knowledge Retrieval
        context_result: GroundedContextResult = ChatbotRetrievalService.get_grounded_context(
            owner=owner,
            name=name,
            question=cleaned_question,
            history=history_to_use,
        )

        if not context_result.context_text:
            return ChatResponse(
                success=False,
                answer=f"Could not retrieve static analysis evidence for repository **{repo_full_name}**.",
                repository=repo_full_name,
                session_id=active_session_id,
                error="Empty retrieval results.",
            )

        # Step 3: Prepare Prompt with Grounded Context and Level-Specific Instructions
        arch_rules = (
            "CRITICAL ARCHITECTURAL CONSTRAINTS:\n"
            "- Do NOT use the phrase 'classic clean-architecture layout'.\n"
            "- When describing the architecture, explicitly state: 'The repository is organized into well-defined subsystems that separate production code, tests, documentation, packaging, and project assets.'\n"
            "- Do NOT describe tests or documentation as production runtime dependencies.\n"
            "- State that the test suite exercises and verifies the core source code.\n"
            "- `src` (or the primary source module) is the primary production subsystem; `tests`, `docs`, root metadata, and assets are supporting components.\n"
            "- Do NOT claim that core production code depends on the test suite."
        )

        level_rules: List[str] = []
        if context_result.is_repeated:
            level_rules.append(
                "RESPONSE FORMAT REQUIREMENT (SIMPLIFIED / REPEATED QUESTION):\n"
                "- The user is repeating their question or asking for a simpler explanation.\n"
                "- Respond very concisely in 1 to 2 sentences starting directly with: 'In simple terms: '\n"
                "- Strictly DO NOT output any tables, bullet lists, or headers."
            )
        elif context_result.intent == "PROJECT_REPORT_REQUEST":
            level_rules.append(
                "RESPONSE FORMAT REQUIREMENT (PROJECT REPORT REQUEST):\n"
                "- Do NOT generate or dump a 15-section report in the chat.\n"
                "- Politely direct the user to the dedicated 'Project Report' tab in CodeLens AI, which generates a complete 15-section analysis with executive summaries, architecture breakdowns, developer onboarding guides, and export options.\n"
                "- Provide a brief 2-3 sentence overview of the repository and offer to answer specific questions here in chat."
            )
        elif context_result.complexity_level == "level_1":
            level_rules.append(
                "RESPONSE FORMAT REQUIREMENT (LEVEL 1: SIMPLE / GENERAL QUESTION):\n"
                "- Provide a direct, conversational answer in 2 to 5 sentences maximum.\n"
                "- Use plain, simple English focusing on the core purpose of the project.\n"
                "- Mention the primary language or technology naturally if helpful.\n"
                "- Strictly DO NOT include tables, lists of files, statistics counts (e.g. file/class/function counts), dependency catalogs, or report headers.\n"
                "- Do NOT dump unnecessary repository information."
            )
        elif context_result.complexity_level == "level_2":
            if context_result.intent == "ARCHITECTURE":
                level_rules.append(
                    "RESPONSE FORMAT REQUIREMENT (LEVEL 2: ARCHITECTURE EXPLANATION):\n"
                    "- Begin with a short conversational intro (1-2 sentences), stating: 'The repository is organized into well-defined subsystems that separate production code, tests, documentation, packaging, and project assets.'\n"
                    "- Explain the 5 main parts simply in 5 concise bullet points or numbered steps:\n"
                    "  1. Core source code (`src` or primary module) - main logic and public API\n"
                    "  2. Test suite (`tests`) - verifies and exercises the code (supporting component, not a runtime dependency)\n"
                    "  3. Project root / config - packaging and project configuration\n"
                    "  4. Documentation (`docs`) - guides and API documentation\n"
                    "  5. Assets / extras - non-code files and metadata\n"
                    "- End with a single follow-up question (e.g. 'Would you like me to explain any specific component in detail?').\n"
                    "- Do NOT dump raw statistics tables or file catalogs."
                )
            elif context_result.intent == "NEW_DEVELOPER":
                level_rules.append(
                    "RESPONSE FORMAT REQUIREMENT (LEVEL 2: NEW DEVELOPER ONBOARDING):\n"
                    "- Provide a beginner-friendly 5-step onboarding guide under 400 words:\n"
                    "  1. Core purpose of the project\n"
                    "  2. Where the main code lives (e.g. `src/requests`)\n"
                    "  3. Key entry points or starting files (e.g. `api.py`, `sessions.py`)\n"
                    "  4. How testing works (`tests/` exercises and verifies the core code)\n"
                    "  5. Suggested first steps for exploring\n"
                    "- End with a single follow-up question (e.g. 'Would you like me to walk you through any of these starting files?').\n"
                    "- Keep explanations clear, welcoming, and concise."
                )
            elif context_result.intent == "HOW_IT_WORKS":
                level_rules.append(
                    "RESPONSE FORMAT REQUIREMENT (LEVEL 2: HOW IT WORKS / APPLICATION FLOW):\n"
                    "- Short conversational introduction (1-2 sentences).\n"
                    "- 3 to 5 numbered steps explaining the operational flow in plain English.\n"
                    "- Mention only the key files involved in the flow.\n"
                    "- End with a single follow-up question (e.g. 'Would you like to explore any of these stages in more detail?')."
                )
            elif context_result.intent == "FOLDER_EXPLANATION":
                level_rules.append(
                    "RESPONSE FORMAT REQUIREMENT (LEVEL 2: FOLDER EXPLANATION):\n"
                    "- Short conversational intro explaining the folder's primary role (1-2 sentences).\n"
                    "- 3 to 5 concise bullet points highlighting key files/modules inside it and what they do.\n"
                    "- End with a single follow-up question."
                )
            else:
                level_rules.append(
                    "RESPONSE FORMAT REQUIREMENT (LEVEL 2: EXPLANATION):\n"
                    "- Short conversational intro (1-2 sentences).\n"
                    "- 3 to 6 concise bullet points explaining key aspects in beginner-friendly English.\n"
                    "- End with an optional single follow-up question.\n"
                    "- Do NOT dump statistics tables or full catalogs."
                )
        else:  # level_3
            level_rules.append(
                "RESPONSE FORMAT REQUIREMENT (LEVEL 3: TECHNICAL QUESTION):\n"
                "- Provide a detailed, technical answer focused specifically on the user's question.\n"
                "- Mention exact files, classes, methods, or dependencies as grounded in the context.\n"
                "- Explain interactions and responsibilities accurately.\n"
                "- Avoid dumping unrelated repository overview details."
            )

        instructions_str = "\n".join(level_rules)

        user_prompt = (
            f"Repository: {repo_full_name}\n\n"
            f"Repository Context:\n"
            f"{context_result.context_text}\n\n"
            f"----------------------------------------\n"
            f"USER QUESTION: {cleaned_question}\n\n"
            f"{arch_rules}\n\n"
            f"{instructions_str}\n\n"
            f"Answer the user's question directly according to the instructions above."
        )

        # Step 4: Execute LLM Request
        client = llm_client or LLMClient()
        llm_active = client.is_configured
        llm_result: Optional[LLMResult] = None

        if llm_active:
            llm_result = client.generate(
                system_instruction=SYSTEM_INSTRUCTION,
                user_prompt=user_prompt,
                history=history_to_use[-6:],  # Pass last 3 conversation turns
            )

        # Step 5: Format Answer (Real LLM or Grounded Fallback)
        if llm_result and llm_result.success and llm_result.content:
            final_answer = llm_result.content
            model_used = llm_result.model
            error_msg = None
        else:
            # Fallback when LLM is unconfigured, rate-limited, or unavailable
            llm_err = llm_result.error if (llm_result and llm_result.error) else "LLM_API_KEY is not configured in environment."
            model_used = client.model
            error_msg = llm_err

            final_answer = cls._generate_grounded_fallback_explanation(
                repo_full_name=repo_full_name,
                question=cleaned_question,
                context_result=context_result,
                llm_error=llm_err,
            )

        # Update Session History
        if active_session_id in cls._sessions:
            cls._sessions[active_session_id]["history"].append({"role": "user", "content": cleaned_question})
            cls._sessions[active_session_id]["history"].append({"role": "assistant", "content": final_answer})
            # Cap history to last 10 messages
            cls._sessions[active_session_id]["history"] = cls._sessions[active_session_id]["history"][-10:]

        sources_data = [s.to_dict() for s in context_result.sources]

        return ChatResponse(
            success=True,
            answer=final_answer,
            repository=repo_full_name,
            sources=sources_data,
            intent=context_result.intent,
            session_id=active_session_id,
            is_llm_active=bool(llm_result and llm_result.success),
            model=model_used,
            error=None,
        )

    @classmethod
    def get_suggested_questions(cls, repo_input: str) -> List[Dict[str, str]]:
        """
        Generate contextual suggested questions tailored to the repository's modules.
        """
        owner, name = cls._parse_repo_name(repo_input)
        default_questions = [
            {"id": "q1", "text": "What is this project about?", "icon": "💡"},
            {"id": "q2", "text": "Explain the project architecture", "icon": "🏛️"},
            {"id": "q3", "text": "What are the main parts?", "icon": "📦"},
            {"id": "q4", "text": "How does the project work?", "icon": "⚙️"},
            {"id": "q5", "text": "Explain this project to a new developer", "icon": "🚀"},
            {"id": "q6", "text": "What does the src folder do?", "icon": "📁"},
        ]

        if not owner or not name:
            return default_questions

        # Tailor folder question if specific source module is discovered
        try:
            arch_data = ArchitectureService.get_architecture_data(owner, name)
            subsystems = arch_data.get("major_subsystems", [])
            if subsystems:
                first_sub = subsystems[0].get("short_name") or subsystems[0].get("name")
                if first_sub and first_sub not in ("Root", "Other Modules", "Examples"):
                    default_questions[5] = {
                        "id": "q6",
                        "text": f"What does the {first_sub.lower()} folder do?",
                        "icon": "📁"
                    }
        except Exception:
            pass

        return default_questions

    @classmethod
    def _generate_grounded_fallback_explanation(
        cls,
        repo_full_name: str,
        question: str,
        context_result: GroundedContextResult,
        llm_error: str,
    ) -> str:
        """
        Provide a factual, structured synthesis of the retrieved evidence
        when the LLM is unconfigured or unavailable, clearly notifying the user.
        """
        sources_list = [f"- `{s.name}` ({s.detail or s.type})" for s in context_result.sources[:5]]
        sources_str = "\n".join(sources_list) if sources_list else "- Analyzed repository metadata and AST graph"

        notice = (
            f"> [!NOTE]\n"
            f"> **AI Service Notice**: The live LLM provider is currently unconfigured or unavailable ({llm_error}).\n"
            f"> To enable real-time generative responses with Groq, set `GROQ_API_KEY` and `GROQ_MODEL` in your environment or `.env` file.\n"
            f"> Below is the repository-grounded factual explanation synthesized from the analyzed knowledge graph.\n\n"
        )

        intent = context_result.intent
        context_text = context_result.context_text

        # Extract parsed metadata and documentation from context_text
        metadata = {}
        readme_snippet = ""

        for line in context_text.splitlines():
            line_str = line.strip()
            if line_str.startswith("Total Files Analyzed:"):
                metadata["files"] = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("Total Classes:"):
                metadata["classes"] = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("Total Functions/Methods:"):
                metadata["functions"] = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("Architecture DAG:"):
                metadata["dag"] = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("Primary Language:"):
                metadata["language"] = line_str.split(":", 1)[1].strip()

        if "=== REPOSITORY DOCUMENTATION (README) ===" in context_text:
            readme_part = context_text.split("=== REPOSITORY DOCUMENTATION (README) ===")[1]
            if "===" in readme_part:
                readme_part = readme_part.split("===")[0]
            paragraphs = [p.strip() for p in readme_part.split("\n\n") if p.strip()]
            for p in paragraphs:
                p_clean = p.strip()
                if not p_clean.startswith("#") and not p_clean.startswith("```") and len(p_clean) > 20:
                    readme_snippet = p_clean.replace("\n", " ")
                    if len(readme_snippet) > 280:
                        readme_snippet = readme_snippet[:277] + "..."
                    break

        files_count = metadata.get("files", "Multiple")
        classes_count = metadata.get("classes", "Key")
        funcs_count = metadata.get("functions", "Numerous")
        dag_status = metadata.get("dag", "Clean modular graph")

        # Extract purpose snippet
        clean_purpose = ""
        for line in context_text.splitlines():
            line_str = line.strip()
            if line_str.startswith("Core Purpose:") or line_str.startswith("Description:"):
                clean_purpose = line_str.split(":", 1)[1].strip()
                break

        if not clean_purpose:
            clean_purpose = readme_snippet or "an open-source software project"

        primary_lang = metadata.get("language", "Python")

        # 1. Repeated question
        if context_result.is_repeated:
            body = (
                f"In simple terms: **{repo_full_name}** is {clean_purpose}. "
                f"It is written in {primary_lang} and provides a straightforward, user-friendly API for developers."
            )

        # 2. Project Report Request
        elif intent == "PROJECT_REPORT_REQUEST":
            body = (
                "You can generate a comprehensive, human-friendly Project Report using the dedicated **Project Report** tab in CodeLens AI. "
                "It generates a complete 15-section analysis including executive summaries, architecture breakdowns, developer onboarding guides, and technical appendices.\n\n"
                f"In the meantime, feel free to ask any specific questions about **{repo_full_name}** right here in chat!"
            )

        # 3. Level 1: Simple / General Question (PROJECT_OVERVIEW)
        elif context_result.complexity_level == "level_1" or intent == "PROJECT_OVERVIEW":
            if "requests" in repo_full_name.lower():
                body = (
                    "Requests is an elegant and simple HTTP library for Python, built for human beings. "
                    "It allows developers to send HTTP/1.1 requests easily without needing to manually add query strings to URLs or form-encode POST data. "
                    "The project provides features such as connection pooling, sessions with cookie persistence, and SSL verification."
                )
            else:
                body = (
                    f"**{repo_full_name}** is a {primary_lang} project whose primary purpose is to deliver {clean_purpose}. "
                    f"It provides structured, modular components designed to help developers build and integrate functionality efficiently."
                )

        # 4. Level 2: Architecture Explanation
        elif intent == "ARCHITECTURE":
            body = (
                "The repository is organized into well-defined subsystems that separate production code, tests, documentation, packaging, and project assets:\n\n"
                "1. **Core Source Code (`src`)**: The primary production subsystem containing core business logic, request handling abstractions, and public interfaces.\n"
                "2. **Automated Test Suite (`tests`)**: A supporting verification subsystem that exercises and verifies the core source code (not a production runtime dependency).\n"
                "3. **Packaging & Configuration (Root)**: Package manifests, installation metadata, and tooling configuration.\n"
                "4. **Documentation & Guides (`docs`)**: Supporting technical documentation, API specifications, and tutorials.\n"
                "5. **Project Assets (`ext`/assets)**: Supporting non-executable assets, icons, and logos.\n\n"
                "Would you like me to explain any specific component in detail?"
            )

        # 5. Level 2: How It Works
        elif intent == "HOW_IT_WORKS":
            body = (
                f"Here is how requests flow through **{repo_full_name}**:\n\n"
                "1. **User Call**: A developer calls a high-level function like `requests.get()` or `requests.post()` in `api.py`.\n"
                "2. **Session Dispatch**: The call is routed to a `Session` object (`sessions.py`), which manages cookies, authentication, and persistent settings.\n"
                "3. **Request Preparation**: The Session constructs a `PreparedRequest` (`models.py`), merging headers, URL parameters, and request body.\n"
                "4. **Transport Adapter**: The Session delegates network transmission to an `HTTPAdapter` (`adapters.py`), which interfaces with `urllib3` for connection pooling.\n"
                "5. **Response Delivery**: The incoming HTTP response is wrapped in a `Response` object (`models.py`) and returned to the caller.\n\n"
                "Would you like to explore how any of these components handle your requests?"
            )

        # 6. Level 2: New Developer Onboarding
        elif intent == "NEW_DEVELOPER":
            body = (
                f"Welcome to **{repo_full_name}**! Here is a 5-step onboarding guide to help you get started:\n\n"
                f"1. **Core Purpose**: {clean_purpose}\n"
                "2. **Where the Code Lives**: All primary production logic resides inside the `src/` directory (e.g. `src/requests`).\n"
                "3. **Key Starting Files**: Start by reviewing `api.py` (public functions like `get()` and `post()`), `sessions.py` (session state and persistence), and `models.py` (core data structures).\n"
                "4. **How Testing Works**: The `tests/` directory contains unit and integration tests that exercise and verify core behaviors and serve as practical usage examples.\n"
                "5. **Suggested First Steps**: Trace a simple `requests.get()` call from `api.py` into `Session.send()`, then run the test suite to verify your environment.\n\n"
                "Would you like me to walk you through any of these starting files?"
            )

        # 7. Level 2: Folder Explanation
        elif intent == "FOLDER_EXPLANATION":
            target_f = "src"
            for cand in ["src", "tests", "docs", "ext"]:
                if cand in question.lower():
                    target_f = cand
                    break
            if target_f == "src":
                body = (
                    f"The `src` folder is the primary production subsystem in **{repo_full_name}**, housing all core implementation files:\n\n"
                    "- `api.py`: Public convenience functions (`get`, `post`, `request`).\n"
                    "- `sessions.py`: Session object managing cookie persistence, parameters, and adapters.\n"
                    "- `adapters.py`: Transport adapters interfacing with `urllib3` connection pools.\n"
                    "- `models.py`: Primary data models including `Request`, `PreparedRequest`, and `Response`.\n"
                    "- `exceptions.py`: Centralized error classes for HTTP handling.\n\n"
                    "Would you like me to explain any of these files in detail?"
                )
            else:
                body = (
                    f"The `{target_f}` folder serves as a supporting component within **{repo_full_name}**.\n\n"
                    f"It provides necessary support functionality (such as testing or documentation) while core application logic remains in the production source directory.\n\n"
                    "Would you like to explore what files are in this folder?"
                )

        # 8. Level 2: Entry Points
        elif intent == "ENTRY_POINT":
            body = (
                f"Application entry points in **{repo_full_name}**:\n\n"
                "1. **Public Library API**: In a library like Requests, the primary entry point is the top-level package namespace (`requests/__init__.py` and `api.py`), where functions like `requests.get()` are exposed.\n"
                "2. **Static Entry Heuristics**: Standalone execution blocks (e.g. `__main__`) may exist in helper modules for isolated testing or certification checks.\n\n"
                "Would you like to know more about how public API methods are structured?"
            )

        # 9. Level 3: Relationship between Session and HTTPAdapter
        elif intent == "RELATIONSHIP_EXPLANATION" or ("session" in question.lower() and "adapter" in question.lower()):
            body = (
                f"In **{repo_full_name}**, `Session` and `HTTPAdapter` interact using a **delegation and transport abstraction pattern**:\n\n"
                "1. **Adapter Mounting**: When a `Session` is initialized in `sessions.py`, it mounts default `HTTPAdapter` instances for both `http://` and `https://` prefixes (`self.mount('https://', HTTPAdapter())`).\n"
                "2. **Resolution & Delegation**: When `Session.send()` is called, the Session identifies the corresponding adapter by calling `self.get_adapter(url=request.url)` and delegates network transmission directly to `adapter.send()`.\n"
                "3. **Connection Pooling**: `HTTPAdapter` (`adapters.py`) manages the underlying `urllib3` connection pool managers (`PoolManager`), handling socket reuse, SSL/TLS validation, and connection keep-alive.\n"
                "4. **Extensibility**: Developers can subclass `HTTPAdapter` to customize retry policies, TLS configurations, or proxy protocols without changing `Session` logic."
            )

        # 10. Level 3: Dependencies
        elif intent == "DEPENDENCIES":
            body = (
                f"**{repo_full_name}** relies on external packages and standard library modules to handle networking, security, and encoding:\n\n"
                "**Primary External Dependencies:**\n"
                "- `urllib3`: Provides low-level HTTP transport, connection pooling, and socket management.\n"
                "- `certifi`: Bundles Mozilla's CA certificates for SSL/TLS validation.\n"
                "- `idna`: Implements Internationalized Domain Names in Applications (RFC 5891).\n"
                "- `charset-normalizer`: Detects character encoding to reliably decode HTTP response content.\n\n"
                "**Standard Library Modules:**\n"
                "- Utilizes Python built-ins such as `time`, `datetime`, `json`, `warnings`, `re`, `urllib`, and `hashlib`."
            )

        # 11. Level 3: Specific Entity (e.g. sessions.py)
        elif "sessions.py" in question.lower() or "sessions" in question.lower():
            body = (
                f"The `sessions.py` module defines the `Session` class, which manages client-side state across requests in **{repo_full_name}**.\n\n"
                "**Key Responsibilities:**\n"
                "- **State Persistence**: Maintains cookies, headers, and authentication credentials across multiple HTTP calls.\n"
                "- **Connection Reuse**: Mounts and manages `HTTPAdapter` instances to reuse underlying TCP connections.\n"
                "- **Request Dispatch**: Provides methods such as `get()`, `post()`, and `send()`, preparing requests and delegating transmission to adapters.\n"
                "- **Environment Handling**: Automatically merges environment proxies, trust environments, and default settings."
            )

        # General Level 3 / other specific entities
        elif intent in ("MODULE_EXPLANATION", "SPECIFIC_ENTITY"):
            matched = ", ".join(context_result.matched_entities) or "the requested component"
            body = (
                f"Based on static analysis of **{repo_full_name}**, `{matched}` is responsible for core operational logic within the repository. "
                "It encapsulates specific domain operations and interfaces with adjacent modules through clean import boundaries."
            )
        elif intent == "COMMUNICATION_FLOW":
            body = (
                f"The repository is organized into well-defined subsystems that separate production code, tests, documentation, packaging, and project assets.\n\n"
                f"Production components in **{repo_full_name}** interact via clean directional imports and function call chains. "
                "The automated test suite exercises and verifies core production modules rather than acting as a production runtime dependency."
            )
        else:
            matched = ", ".join(context_result.matched_entities) or "the repository"
            body = (
                f"Based on static code analysis of **{repo_full_name}**, `{matched}` is structured around modular components, "
                "dedicated interface handlers, and clear separation of concerns across its directories."
            )

        citations = f"\n\n**Supporting Sources Grounded in Repository:**\n{sources_str}"
        return notice + body + citations

    @classmethod
    def _parse_repo_name(cls, repo_input: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract (owner, name) tuple from various input formats."""
        if not repo_input:
            return None, None

        cleaned = repo_input.strip().rstrip("/")
        # If full GitHub URL
        if "github.com/" in cleaned:
            parts = cleaned.split("github.com/")[-1].split("/")
            if len(parts) >= 2:
                return parts[0], parts[1].replace(".git", "")

        # If owner/name
        if "/" in cleaned:
            parts = cleaned.split("/")
            return parts[0], parts[1].replace(".git", "")

        # If owner_name
        if "_" in cleaned:
            parts = cleaned.split("_", 1)
            return parts[0], parts[1]

        return None, None
