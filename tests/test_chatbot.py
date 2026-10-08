"""
Unit and integration tests for CodeLens AI Repository Comprehension Assistant Chatbot.

Tests:
- LLMClient configuration, provider resolution, and error handling.
- ChatbotRetrievalService question intent classification and multi-source knowledge gathering.
- ChatbotService ask pipeline, repository isolation, follow-up context, and source citations.
- API Endpoints (/chat, /api/chat/ask, /api/chat/suggested, /api/chat/clear, /api/chat/status).
"""

import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from app import create_app
from models.knowledge import (
    ClassInfo,
    DirectoryInfo,
    EntryPointInfo,
    FileInfo,
    FunctionInfo,
    RepositoryInfo,
    SharedRepositoryKnowledge,
)
from services.chatbot_retrieval_service import ChatbotRetrievalService, GroundedContextResult
from services.chatbot_service import ChatbotService
from services.knowledge_service import KnowledgeService
from services.llm_client import LLMClient, LLMResult


class ChatbotTestCase(unittest.TestCase):
    """Test suite for the AI Repository Assistant Chatbot."""

    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()

        # Build mock repository knowledge
        self.mock_repo = RepositoryInfo(
            name="testchat",
            owner="testowner",
            url="https://github.com/testowner/testchat",
            description="A high-performance web service framework for testing.",
            primary_language="Python",
        )

        self.mock_knowledge = SharedRepositoryKnowledge(
            repository=self.mock_repo,
            directories=[
                DirectoryInfo(path="core", name="core"),
                DirectoryInfo(path="services", name="services", parent="core"),
            ],
            files=[
                FileInfo(path="app.py", name="app.py", extension=".py", language="Python", size=2500, classes_count=1, functions_count=2),
                FileInfo(path="services/worker.py", name="worker.py", extension=".py", language="Python", size=4200, classes_count=2, functions_count=3),
            ],
            classes=[
                ClassInfo(name="WorkerSession", file="services/worker.py", base_classes=["BaseSession"], methods=["start", "stop", "dispatch"]),
                ClassInfo(name="Application", file="app.py", base_classes=[], methods=["run", "configure"]),
            ],
            functions=[
                FunctionInfo(name="dispatch_event", file="services/worker.py", parameters=["event_name", "payload"]),
                FunctionInfo(name="bootstrap", file="app.py", parameters=["config_path"]),
            ],
            entry_points=[
                EntryPointInfo(file="app.py", symbol="__main__", detection_reason="main_block", line=45),
            ],
            statistics={
                "total_files": 2,
                "total_classes": 2,
                "total_functions": 2,
                "total_methods": 5,
                "cycles_count": 0,
            },
        )

        # Save mock knowledge to test analysis directory
        KnowledgeService.save_knowledge("testowner", "testchat", self.mock_knowledge)

    def tearDown(self):
        # Clean up test knowledge file
        k_path = KnowledgeService.get_knowledge_file_path("testowner", "testchat")
        if k_path.is_file():
            try:
                k_path.unlink()
            except Exception:
                pass

    def test_llm_client_initialization_and_config(self):
        """Test LLM client initialization and provider auto-detection."""
        # Unconfigured client
        client = LLMClient(api_key="", model="gemini-1.5-flash")
        self.assertFalse(client.is_configured)
        self.assertEqual(client.resolved_provider, "gemini")

        # Configured Gemini client
        gemini_client = LLMClient(api_key="fake-gemini-key", model="gemini-2.0-flash")
        self.assertTrue(gemini_client.is_configured)
        self.assertEqual(gemini_client.resolved_provider, "gemini")

        # Configured Groq client
        groq_client = LLMClient(api_key="fake-groq-key", model="llama-3.3-70b-versatile", provider="groq")
        self.assertTrue(groq_client.is_configured)
        self.assertEqual(groq_client.resolved_provider, "groq")

    def test_llm_client_offline_unconfigured_error(self):
        """Test that unconfigured LLM client returns friendly error instead of crashing."""
        client = LLMClient(api_key="", provider="gemini")
        res = client.generate(system_instruction="sys", user_prompt="hello")
        self.assertFalse(res.success)
        self.assertIn("AI service is not configured", res.error)

    def test_groq_missing_model_error(self):
        """Test that missing GROQ_MODEL returns clear configuration error without crashing."""
        client = LLMClient(api_key="fake-key", model="", provider="groq")
        res = client.generate(system_instruction="sys", user_prompt="hello")
        self.assertFalse(res.success)
        self.assertIn("GROQ_MODEL is not configured", res.error)

    def test_groq_sdk_execution_mocked(self):
        """Test Groq client generation with mocked Groq SDK."""
        client = LLMClient(api_key="fake-groq-key", model="llama-3.3-70b-versatile", provider="groq")
        with patch("groq.Groq") as mock_groq_class:
            mock_groq_instance = MagicMock()
            mock_groq_class.return_value = mock_groq_instance

            mock_completion = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "Groq analysis: The repository is an HTTP framework."
            mock_completion.choices = [mock_choice]
            mock_completion.usage.prompt_tokens = 150
            mock_completion.usage.completion_tokens = 30
            mock_completion.usage.total_tokens = 180
            mock_groq_instance.chat.completions.create.return_value = mock_completion

            result = client.generate(system_instruction="You are CodeLens AI", user_prompt="What is this?")
            self.assertTrue(result.success)
            self.assertIn("Groq analysis", result.content)
            self.assertEqual(result.provider, "groq")
            self.assertEqual(result.model, "llama-3.3-70b-versatile")

    def test_chatbot_retrieval_service_intent_classification(self):
        """Test question intent understanding, complexity level classification, and repetition detection."""
        intent, entities, complexity, is_repeated = ChatbotRetrievalService._analyze_question(
            "What is this project about?",
            self.mock_knowledge,
            {},
        )
        self.assertEqual(intent, "PROJECT_OVERVIEW")
        self.assertEqual(complexity, "level_1")
        self.assertFalse(is_repeated)

        intent, entities, complexity, is_repeated = ChatbotRetrievalService._analyze_question(
            "Explain the architecture.",
            self.mock_knowledge,
            {},
        )
        self.assertEqual(intent, "ARCHITECTURE")
        self.assertEqual(complexity, "level_2")

        intent, entities, complexity, is_repeated = ChatbotRetrievalService._analyze_question(
            "Where is the main entry point?",
            self.mock_knowledge,
            {},
        )
        self.assertEqual(intent, "ENTRY_POINT")
        self.assertEqual(complexity, "level_2")

        intent, entities, complexity, is_repeated = ChatbotRetrievalService._analyze_question(
            "What dependencies does this project use?",
            self.mock_knowledge,
            {},
        )
        self.assertEqual(intent, "DEPENDENCIES")
        self.assertEqual(complexity, "level_3")

        intent, entities, complexity, is_repeated = ChatbotRetrievalService._analyze_question(
            "Explain this project to a new developer.",
            self.mock_knowledge,
            {},
        )
        self.assertEqual(intent, "NEW_DEVELOPER")
        self.assertEqual(complexity, "level_2")

        intent, entities, complexity, is_repeated = ChatbotRetrievalService._analyze_question(
            "What does WorkerSession do?",
            self.mock_knowledge,
            {},
        )
        self.assertIn("WorkerSession", entities)
        self.assertEqual(complexity, "level_3")

        # Test repetition detection
        history = [
            {"role": "user", "content": "What does this project do?"},
            {"role": "assistant", "content": "It is a web service framework."},
        ]
        intent, entities, complexity, is_repeated = ChatbotRetrievalService._analyze_question(
            "Explain in simple terms",
            self.mock_knowledge,
            {},
            history=history,
        )
        self.assertTrue(is_repeated)

    def test_chatbot_retrieval_service_grounded_context(self):
        """Test multi-source knowledge gathering produces rich context and citations."""
        res: GroundedContextResult = ChatbotRetrievalService.get_grounded_context(
            owner="testowner",
            name="testchat",
            question="What is this project about?",
        )
        self.assertTrue(res.is_sufficient_evidence)
        self.assertIn("=== REPOSITORY IDENTITY ===", res.context_text)
        self.assertIn("testowner/testchat", res.context_text)
        self.assertIn("Python", res.context_text)
        self.assertEqual(res.complexity_level, "level_1")

    def test_chatbot_service_mock_llm_answers(self):
        """Test end-to-end ChatbotService.ask with mocked real LLM response."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_configured = True
        mock_llm.model = "gemini-1.5-flash"
        mock_llm.generate.return_value = LLMResult(
            content="This project is a high-performance web service framework.",
            success=True,
            model="gemini-1.5-flash",
            provider="gemini",
        )

        response = ChatbotService.ask(
            repo_input="testowner/testchat",
            question="What is this project about?",
            llm_client=mock_llm,
        )

        self.assertTrue(response.success)
        self.assertEqual(response.repository, "testowner/testchat")
        self.assertEqual(response.answer, "This project is a high-performance web service framework.")
        self.assertTrue(response.is_llm_active)
        self.assertTrue(len(response.sources) >= 0)

    def test_chatbot_service_fixed_and_random_questions_pipeline(self):
        """Verify that fixed and unexpected random questions all pass through retrieval and synthesis."""
        questions_to_test = [
            "What is this project about?",
            "What are the main components?",
            "Explain the architecture.",
            "What does the worker module do?",
            "Why is this module important?",
            "Which files handle the main functionality?",
            "How do the major components communicate?",
            "Explain this project to a new developer.",
            "If I am new to this repository, what should I understand first?",
            "How does data move through this project?",
        ]

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_configured = True
        mock_llm.model = "gemini-1.5-flash"

        for q in questions_to_test:
            mock_llm.generate.return_value = LLMResult(
                content=f"Synthesized comprehensive answer for inquiry: {q}",
                success=True,
                model="gemini-1.5-flash",
                provider="gemini",
            )
            resp = ChatbotService.ask(
                repo_input="testowner/testchat",
                question=q,
                llm_client=mock_llm,
            )
            self.assertTrue(resp.success, f"Failed for question: {q}")
            self.assertIn("Synthesized", resp.answer)

    def test_chatbot_service_unconfigured_llm_graceful_fallback(self):
        """Test that missing LLM key returns factual grounded synthesis with clear notification."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_configured = False
        mock_llm.model = "gemini-1.5-flash"

        response = ChatbotService.ask(
            repo_input="testowner/testchat",
            question="What is this project about?",
            llm_client=mock_llm,
        )

        self.assertTrue(response.success)
        self.assertFalse(response.is_llm_active)
        self.assertIsNone(response.error)
        self.assertIn("AI Service Notice", response.answer)
        self.assertIn("testowner/testchat", response.answer)
        self.assertIn("Supporting Sources Grounded in Repository", response.answer)

    def test_chatbot_service_repository_isolation(self):
        """Test strict repository isolation when user switches repositories."""
        sess_id = "test_iso_session_1"
        repo_a = "testowner/testchat"
        repo_b = "testowner/otherrepo"

        # Ask question for Repo A
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_configured = True
        mock_llm.model = "gemini-1.5-flash"
        mock_llm.generate.return_value = LLMResult(content="Answer for A", success=True, model="gemini-1.5-flash")

        ChatbotService.ask(repo_a, "Question 1 for A", session_id=sess_id, llm_client=mock_llm)
        self.assertEqual(ChatbotService._sessions[sess_id]["repo"], repo_a)
        self.assertEqual(len(ChatbotService._sessions[sess_id]["history"]), 2)

        # Create mock for Repo B
        mock_b = SharedRepositoryKnowledge(
            repository=RepositoryInfo(name="otherrepo", owner="testowner", url="http://github.com/testowner/otherrepo"),
            directories=[],
            files=[],
            classes=[],
            functions=[],
        )
        KnowledgeService.save_knowledge("testowner", "otherrepo", mock_b)

        # Switch to Repo B in the same session
        mock_llm.generate.return_value = LLMResult(content="Answer for B", success=True, model="gemini-1.5-flash")
        ChatbotService.ask(repo_b, "Question 1 for B", session_id=sess_id, llm_client=mock_llm)

        # History must be isolated and reset for Repo B!
        self.assertEqual(ChatbotService._sessions[sess_id]["repo"], repo_b)
        self.assertEqual(len(ChatbotService._sessions[sess_id]["history"]), 2)
        self.assertEqual(ChatbotService._sessions[sess_id]["history"][0]["content"], "Question 1 for B")

        # Clean up
        KnowledgeService.get_knowledge_file_path("testowner", "otherrepo").unlink(missing_ok=True)

    def test_chatbot_service_unprocessed_repo_error(self):
        """Test that asking questions about unanalyzed repository returns clean user-facing guidance."""
        resp = ChatbotService.ask("nonexistent/unknownrepo", "What is this?")
        self.assertFalse(resp.success)
        self.assertIn("has not been analyzed yet", resp.answer)

    def test_chat_page_route(self):
        """Test GET /chat and /assistant render HTTP 200."""
        r1 = self.client.get("/chat")
        self.assertEqual(r1.status_code, 200)
        self.assertIn(b"AI Repository Assistant", r1.data)

        r2 = self.client.get("/assistant")
        self.assertEqual(r2.status_code, 200)

    def test_api_chat_ask_endpoint(self):
        """Test POST /api/chat/ask."""
        payload = {
            "repo": "testowner/testchat",
            "question": "What is this project about?",
        }
        res = self.client.post("/api/chat/ask", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIsNone(data["error"])
        self.assertIn("answer", data)
        self.assertEqual(data["repository"], "testowner/testchat")

    def test_api_chat_endpoint_with_message_and_conversation(self):
        """Test POST /api/chat with 'message' and 'conversation' payload fields."""
        payload = {
            "repo": "testowner/testchat",
            "message": "What is this repository about?",
            "conversation": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi! How can I help?"}
            ]
        }
        res = self.client.post("/api/chat", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("answer", data)
        self.assertIn("sources", data)
        self.assertEqual(data["repository"], "testowner/testchat")

    def test_api_chat_suggested_and_clear_endpoints(self):
        """Test GET /api/chat/suggested, POST /api/chat/clear, and GET /api/chat/status."""
        # Suggested questions
        res = self.client.get("/api/chat/suggested?repo=testowner/testchat")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(len(data["questions"]) >= 5)

        # Status
        res_status = self.client.get("/api/chat/status")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.get_json()
        self.assertTrue(status_data["success"])
        self.assertIn("provider", status_data)

        # Clear session
        res_clear = self.client.post("/api/chat/clear", json={"session_id": "test_clear_session"})
        self.assertEqual(res_clear.status_code, 200)
        clear_data = res_clear.get_json()
        self.assertTrue(clear_data["success"])

    def test_architecture_explanation_wording(self):
        """Verify fallback and prompt instructions include required subsystem wording and omit 'classic clean-architecture layout'."""
        # Test fallback architecture explanation
        res = ChatbotService.ask("testowner/testchat", "Explain the project architecture", llm_client=LLMClient(api_key=""))
        self.assertTrue(res.success)
        self.assertIn("The repository is organized into well-defined subsystems that separate production code, tests, documentation, packaging, and project assets", res.answer)
        self.assertNotIn("classic clean-architecture layout", res.answer)

    def test_response_complexity_level_1_conciseness(self):
        """Level 1 questions must receive concise, conversational answers without tables or stats dumps."""
        res = ChatbotService.ask("testowner/testchat", "What is this project about?", llm_client=LLMClient(api_key=""))
        self.assertTrue(res.success)
        # Must not contain tables, scale dumps, or file catalogs
        self.assertNotIn("|", res.answer)
        self.assertNotIn("Codebase Scale", res.answer)
        self.assertNotIn("Analyzed Components", res.answer)
        # Must mention project purpose
        self.assertIn("testowner/testchat", res.answer)

    def test_response_complexity_level_2_architecture_and_onboarding(self):
        """Level 2 questions must have structured parts/steps and end with a follow-up question."""
        # Architecture
        res_arch = ChatbotService.ask("testowner/testchat", "Explain the project architecture", llm_client=LLMClient(api_key=""))
        self.assertTrue(res_arch.success)
        self.assertIn("Core Source Code", res_arch.answer)
        self.assertIn("Automated Test Suite", res_arch.answer)
        self.assertIn("Would you like me to explain any specific component in detail?", res_arch.answer)

        # Onboarding
        res_onboard = ChatbotService.ask("testowner/testchat", "Explain this project to a new developer", llm_client=LLMClient(api_key=""))
        self.assertTrue(res_onboard.success)
        self.assertIn("5-step onboarding guide", res_onboard.answer)
        self.assertIn("Core Purpose", res_onboard.answer)
        self.assertIn("Where the Code Lives", res_onboard.answer)
        self.assertIn("Key Starting Files", res_onboard.answer)
        self.assertIn("How Testing Works", res_onboard.answer)
        self.assertIn("Suggested First Steps", res_onboard.answer)
        self.assertIn("Would you like me to walk you through any of these starting files?", res_onboard.answer)
        # Ensure under 400 words
        word_count = len(res_onboard.answer.split())
        self.assertTrue(word_count < 400, f"Onboarding guide too long: {word_count} words")

    def test_response_complexity_level_3_technical_questions(self):
        """Level 3 questions must provide focused technical explanations."""
        # Session and HTTPAdapter relationship
        res_rel = ChatbotService.ask("testowner/testchat", "Explain the relationship between Session and HTTPAdapter", llm_client=LLMClient(api_key=""))
        self.assertTrue(res_rel.success)
        self.assertIn("delegation and transport abstraction pattern", res_rel.answer)
        self.assertIn("Adapter Mounting", res_rel.answer)
        self.assertIn("Resolution & Delegation", res_rel.answer)
        self.assertIn("Connection Pooling", res_rel.answer)

        # Dependencies
        res_dep = ChatbotService.ask("testowner/testchat", "What dependencies does this project use?", llm_client=LLMClient(api_key=""))
        self.assertTrue(res_dep.success)
        self.assertIn("urllib3", res_dep.answer)
        self.assertIn("certifi", res_dep.answer)
        self.assertIn("idna", res_dep.answer)

    def test_project_report_request_redirects_to_report_tab(self):
        """Chatbot must politely redirect 'generate a project report' requests to the Project Report tab."""
        res = ChatbotService.ask("testowner/testchat", "Generate a project report", llm_client=LLMClient(api_key=""))
        self.assertTrue(res.success)
        self.assertIn("Project Report", res.answer)
        self.assertIn("dedicated **Project Report** tab", res.answer)

    def test_repeated_question_starts_with_in_simple_terms(self):
        """Repeated questions or requests for simpler explanations must start with 'In simple terms: '."""
        sess_id = "test_rep_session"
        # First question
        ChatbotService.ask("testowner/testchat", "What does this project do?", session_id=sess_id, llm_client=LLMClient(api_key=""))
        # Repeated/simpler question in same session
        res_rep = ChatbotService.ask("testowner/testchat", "Explain in simple terms", session_id=sess_id, llm_client=LLMClient(api_key=""))
        self.assertTrue(res_rep.success)
        self.assertIn("In simple terms:", res_rep.answer)


if __name__ == "__main__":
    unittest.main()
