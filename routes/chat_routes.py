"""
Chat routes for CodeLens AI Repository Comprehension Assistant.

Endpoints for repository-grounded Q&A, contextual question suggestions,
session clearing, and LLM configuration status.
"""

from flask import Blueprint, jsonify, request
from services.chatbot_service import ChatbotService
from services.llm_client import LLMClient

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")


@chat_bp.route("", methods=["POST"])
@chat_bp.route("/ask", methods=["POST"])
def ask_question():
    """
    Process a natural language question about an analyzed repository.
    Accepts:
    {
        "repo": "owner/repo" or "owner_name",
        "message": "What is this repository about?" (or "question"),
        "conversation": [optional-turn-list] (or "history"),
        "session_id": "optional-uuid"
    }
    """
    data = request.get_json(silent=True) or {}
    repo = data.get("repo") or data.get("repository") or ""
    question = (
        data.get("message")
        or data.get("question")
        or data.get("query")
        or data.get("prompt")
        or ""
    )
    session_id = data.get("session_id")
    history = data.get("conversation") or data.get("history")

    if not repo:
        return jsonify({
            "success": False,
            "error": "Missing repository parameter ('repo').",
            "answer": "Please select a repository to ask questions about.",
            "sources": [],
        }), 400

    if not question or not question.strip():
        return jsonify({
            "success": False,
            "error": "Missing question parameter ('message' or 'question').",
            "answer": "Please enter a question about the repository.",
            "sources": [],
        }), 400

    response = ChatbotService.ask(
        repo_input=repo,
        question=question,
        session_id=session_id,
        custom_history=history,
    )

    resp_dict = response.to_dict()
    status_code = 200 if response.success else (404 if "not analyzed" in (response.error or "") else 400)

    return jsonify({
        "data": resp_dict,
        **resp_dict,
    }), status_code


@chat_bp.route("/suggested", methods=["GET"])
def get_suggested_questions():
    """
    Retrieve contextual suggested questions for a repository.
    Query param: ?repo=owner/repo
    """
    repo = request.args.get("repo") or request.args.get("repository") or ""
    questions = ChatbotService.get_suggested_questions(repo)

    return jsonify({
        "success": True,
        "repository": repo,
        "questions": questions,
    }), 200


@chat_bp.route("/clear", methods=["POST"])
def clear_chat_session():
    """
    Clear conversation history for a given session.
    Expected JSON: {"session_id": "..."}
    """
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id") or ""

    if session_id:
        ChatbotService.clear_session(session_id)

    return jsonify({
        "success": True,
        "message": "Chat conversation context reset successfully.",
    }), 200


@chat_bp.route("/status", methods=["GET"])
def get_llm_status():
    """
    Return active LLM provider and configuration status.
    """
    client = LLMClient()
    return jsonify({
        "success": True,
        "is_configured": client.is_configured,
        "provider": client.resolved_provider,
        "model": client.model,
    }), 200
