from flask import Blueprint, jsonify, render_template

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@main_bp.route("/repositories")
def index():
    """Render the CodeLens AI landing page and ranking dashboard."""
    return render_template("index.html")


@main_bp.route("/analysis")
def analysis():
    """Render the CodeLens AI Repository Analysis & Semantic Code Graph page."""
    return render_template("analysis.html")


@main_bp.route("/architecture")
def architecture():
    """Render the CodeLens AI Whole Repository Architecture Explorer page."""
    return render_template("architecture.html")


@main_bp.route("/graph")
def graph():
    """Render the detailed Phase 7 Semantic Code Graph page (technical relationship layer)."""
    return render_template("graph.html")


@main_bp.route("/report")
def report():
    """Render the CodeLens AI Project Report Generator page (Phase 1 Final Review)."""
    return render_template("report.html")


@main_bp.route("/chat")
@main_bp.route("/assistant")
@main_bp.route("/ai-chat")
def chat():
    """Render the CodeLens AI Repository Comprehension Assistant Chatbot page."""
    return render_template("chat.html")


@main_bp.route("/health")
def health():
    """Health check endpoint to verify Flask application status."""
    return jsonify({
        "status": "online",
        "project": "CodeLens AI",
        "phase": "Phase 8 - Whole Repository Architecture Explorer",
        "ready": True
    }), 200
