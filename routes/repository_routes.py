"""
Repository routes for CodeLens AI (Phase 4).
Handles API requests for GitHub repository URL validation, batch checks,
keyword-based repository discovery, and multi-repository suitability ranking.
"""

from flask import Blueprint, jsonify, request, send_file
from services.github_service import GitHubService
from services.ranking_service import RankingService
from services.analysis_service import RepositoryAnalysisService
from services.ast_service import DeepCodeAnalysisService
from services.knowledge_service import KnowledgeService
from services.graph_service import SemanticCodeGraphService
from services.architecture_service import ArchitectureService
from services.report_service import ReportService
from services.chatbot_service import ChatbotService

repository_bp = Blueprint("repository", __name__, url_prefix="/api/repositories")


@repository_bp.route("/validate", methods=["POST"])
def validate_single():
    """
    Validate a single GitHub repository URL.
    Expected JSON: {"url": "https://github.com/owner/repo"}
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url")

    result = GitHubService.validate_url(url)

    if result["valid"]:
        return jsonify({
            "success": True,
            "valid": True,
            "repository": result["repository"]
        }), 200
    else:
        return jsonify({
            "success": False,
            "valid": False,
            "error": result["error"]
        }), 400


@repository_bp.route("/validate-batch", methods=["POST"])
def validate_batch():
    """
    Validate a list of GitHub repository URLs (1 to 10).
    Expected JSON: {"urls": ["https://github.com/owner/repo1", ...]}
    """
    data = request.get_json(silent=True) or {}
    urls = data.get("urls")

    if urls is None:
        return jsonify({
            "success": False,
            "valid": False,
            "errors": ["Request must include a 'urls' list."],
            "error": "Request must include a 'urls' list."
        }), 400

    result = GitHubService.validate_batch(urls)

    if result["valid"]:
        return jsonify({
            "success": True,
            "valid": True,
            "count": result["count"],
            "repositories": result["repositories"]
        }), 200
    else:
        primary_error = result["errors"][0] if result["errors"] else "Batch validation failed."
        return jsonify({
            "success": False,
            "valid": False,
            "count": result["count"],
            "errors": result["errors"],
            "error": primary_error
        }), 400


@repository_bp.route("/analyze", methods=["POST"])
def analyze_repositories():
    """
    Evaluate, rank, and stage candidate repositories (Phase 4).
    Validates input repositories, fetches live GitHub metadata,
    calculates suitability percentages, and identifies the recommended repository.
    Expected JSON:
    {
        "repositories": [{"url": "...", "owner": "...", "name": "..."}],
        "keyword": "optional search keyword",
        "weights": {"keyword_relevance": 0.25, ...}
    }
    """
    data = request.get_json(silent=True) or {}
    keyword = data.get("keyword")
    custom_weights = data.get("weights")

    # Extract URLs from either 'urls' or 'repositories'
    if "urls" in data and isinstance(data["urls"], list):
        urls = data["urls"]
    elif "repositories" in data and isinstance(data["repositories"], list):
        urls = [
            item.get("url") if isinstance(item, dict) else item
            for item in data["repositories"]
        ]
    else:
        urls = []

    # 1. Validate repository collection
    stage_result = GitHubService.stage_repositories_for_analysis(urls)
    if not stage_result["success"]:
        return jsonify(stage_result), 400

    # 2. Evaluate and rank the validated repositories
    ranking_result = RankingService.rank_repositories(
        repositories=stage_result["repositories"],
        keyword=keyword,
        custom_weights=custom_weights,
    )

    if not ranking_result["success"]:
        return jsonify(ranking_result), 400

    # Return unified response containing both staged items and ranking output
    response_payload = {
        "success": True,
        "stage": "staged_for_analysis",
        "ranking_status": "ranked_and_staged",
        "count": ranking_result["total_evaluated"],
        "repositories": stage_result["repositories"],
        "recommended_repository": ranking_result["recommended_repository"],
        "ranking": ranking_result["ranking"],
        "weights_applied": ranking_result["weights_applied"],
        "keyword": keyword,
        "message": ranking_result["message"],
    }
    return jsonify(response_payload), 200


@repository_bp.route("/rank", methods=["POST"])
def rank_repositories_direct():
    """
    Direct ranking endpoint for candidate repositories.
    Expected JSON: {"repositories": [...], "keyword": "...", "weights": {...}}
    """
    return analyze_repositories()


@repository_bp.route("/search", methods=["GET", "POST"])
def search_repositories():
    """
    Search GitHub repositories by keyword (Phase 3).
    Accepts GET query parameter `q` or POST JSON payload `{"q": "keyword", "per_page": 10}`.
    """
    query = None
    per_page = 10

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        query = data.get("q") or data.get("keyword") or data.get("query")
        per_page = data.get("per_page", 10)
    else:
        query = request.args.get("q") or request.args.get("keyword") or request.args.get("query")
        per_page = request.args.get("per_page", 10)

    try:
        per_page = int(per_page)
    except (ValueError, TypeError):
        per_page = 10

    result = GitHubService.search_repositories(query=query, per_page=per_page)

    status_code = result.get("status_code", 200 if result.get("success") else 400)
    return jsonify(result), status_code


# ============================================================================
# Phase 5: Repository Acquisition & Basic Analysis Endpoints
# ============================================================================

@repository_bp.route("/acquire-and-analyze", methods=["POST"])
def acquire_and_analyze():
    """
    Acquire (shallow clone / cache) and perform basic static analysis on a repository.
    Expected JSON:
      {"repo": "owner/name"} OR {"url": "https://github.com/owner/name"}
      Optional: {"force_refresh": false}
    """
    data = request.get_json(silent=True) or {}
    repo_input = data.get("repo") or data.get("url") or data.get("full_name") or ""
    force_refresh = bool(data.get("force_refresh", False))

    owner = data.get("owner")
    name = data.get("name")

    if not owner or not name:
        # Extract owner and name from URL or "owner/name" string
        cleaned = repo_input.strip()
        if "github.com/" in cleaned:
            cleaned = cleaned.split("github.com/")[-1]
        cleaned = cleaned.rstrip("/").removesuffix(".git")
        parts = [p for p in cleaned.split("/") if p]
        if len(parts) >= 2:
            owner, name = parts[0], parts[1]
        else:
            return jsonify({
                "success": False,
                "error": "A valid repository 'owner/name' or GitHub URL is required.",
            }), 400

    result = RepositoryAnalysisService.analyze_repository(
        owner=owner,
        name=name,
        force_refresh=force_refresh,
    )

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@repository_bp.route("/analysis/<owner>/<name>", methods=["GET"])
def get_repository_analysis(owner: str, name: str):
    """
    Retrieve stored analysis result for a previously analyzed repository.
    """
    cached = RepositoryAnalysisService.load_cached_analysis(owner, name)
    if cached:
        return jsonify({
            "success": True,
            "is_cached": True,
            **cached,
        }), 200

    return jsonify({
        "success": False,
        "error": f"No analysis found for repository {owner}/{name}. Run acquisition first.",
    }), 404


@repository_bp.route("/analysis/cached", methods=["GET"])
def list_cached_analyses():
    """
    List all previously analyzed repositories stored in local cache.
    """
    analyses = RepositoryAnalysisService.get_cached_analyses()
    return jsonify({
        "success": True,
        "count": len(analyses),
        "repositories": analyses,
    }), 200


# ============================================================================
# Phase 6: Deep Static Code Analysis (AST) Endpoints
# ============================================================================

@repository_bp.route("/ast-analysis", methods=["POST"])
def perform_ast_analysis():
    """
    Perform deep static AST analysis on an acquired repository.
    Expected JSON: {"repo": "owner/name"} OR {"owner": "...", "name": "..."}
    Optional: {"force_refresh": false}
    """
    data = request.get_json(silent=True) or {}
    repo_input = data.get("repo") or data.get("full_name") or data.get("url") or ""
    force_refresh = bool(data.get("force_refresh", False))

    owner = data.get("owner")
    name = data.get("name")

    if not owner or not name:
        cleaned = repo_input.strip()
        if "github.com/" in cleaned:
            cleaned = cleaned.split("github.com/")[-1]
        cleaned = cleaned.rstrip("/").removesuffix(".git")
        parts = [p for p in cleaned.split("/") if p]
        if len(parts) >= 2:
            owner, name = parts[0], parts[1]
        else:
            return jsonify({
                "success": False,
                "error": "A valid repository 'owner/name' or GitHub URL is required.",
            }), 400

    result = DeepCodeAnalysisService.analyze_codebase(
        owner=owner,
        name=name,
        force_refresh=force_refresh,
    )

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@repository_bp.route("/ast-analysis/<owner>/<name>", methods=["GET"])
def get_ast_analysis(owner: str, name: str):
    """
    Retrieve stored Phase 6 AST knowledge object for a repository.
    """
    cached = DeepCodeAnalysisService.load_cached_knowledge(owner, name)
    if cached:
        return jsonify({
            "success": True,
            "is_cached": True,
            **cached,
        }), 200

    return jsonify({
        "success": False,
        "error": f"No AST knowledge found for repository {owner}/{name}. Run deep analysis first.",
    }), 404


# ============================================================================
# Phase 7: Shared Repository Knowledge & Semantic Code Graph Endpoints
# ============================================================================

@repository_bp.route("/knowledge/<owner>/<name>", methods=["GET"])
def get_shared_knowledge_endpoint(owner: str, name: str):
    """
    Retrieve the centralized Shared Repository Knowledge object for downstream tasks.
    """
    try:
        knowledge = KnowledgeService.get_shared_knowledge(owner=owner, name=name)
        return jsonify({
            "success": True,
            "knowledge": knowledge.to_dict(),
        }), 200
    except Exception as ex:
        return jsonify({
            "success": False,
            "error": f"Failed to retrieve shared knowledge for {owner}/{name}: {str(ex)}",
        }), 500


@repository_bp.route("/graph", methods=["POST"])
def generate_or_get_graph():
    """
    Generate or retrieve the Semantic Code Graph for an acquired repository.
    Expected JSON: {"owner": "...", "name": "..."} OR {"repo": "owner/name"}
    Optional: {"force_refresh": false}
    """
    data = request.get_json(silent=True) or {}
    repo_input = data.get("repo") or data.get("full_name") or data.get("url") or ""
    force_refresh = bool(data.get("force_refresh", False))

    owner = data.get("owner")
    name = data.get("name")

    if not owner or not name:
        cleaned = repo_input.strip()
        if "github.com/" in cleaned:
            cleaned = cleaned.split("github.com/")[-1]
        cleaned = cleaned.rstrip("/").removesuffix(".git")
        parts = [p for p in cleaned.split("/") if p]
        if len(parts) >= 2:
            owner, name = parts[0], parts[1]
        else:
            return jsonify({
                "success": False,
                "error": "A valid repository 'owner/name' or GitHub URL is required.",
            }), 400

    result = SemanticCodeGraphService.get_or_create_graph(
        owner=owner,
        name=name,
        force_refresh=force_refresh,
    )

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@repository_bp.route("/graph/<owner>/<name>", methods=["GET"])
def get_graph_endpoint(owner: str, name: str):
    """
    Retrieve stored Phase 7 Semantic Code Graph JSON for a repository.
    """
    cached = SemanticCodeGraphService.load_cached_graph(owner, name)
    if cached:
        return jsonify({
            "success": True,
            "is_cached": True,
            "graph": cached,
        }), 200

    return jsonify({
        "success": False,
        "error": f"No Semantic Code Graph found for repository {owner}/{name}. Generate it first.",
    }), 404


# ============================================================================
# Phase 8: Whole Repository Architecture Explorer Endpoints
# ============================================================================

@repository_bp.route("/architecture", methods=["POST"])
def get_or_generate_architecture():
    """
    Generate or retrieve the Whole Repository Architecture model.
    Expected JSON: {"owner": "...", "name": "..."} OR {"repo": "owner/name"}
    Optional: {"force_refresh": false}
    """
    data = request.get_json(silent=True) or {}
    repo_input = data.get("repo") or data.get("full_name") or data.get("url") or ""
    force_refresh = bool(data.get("force_refresh", False))

    owner = data.get("owner")
    name = data.get("name")

    if not owner or not name:
        cleaned = repo_input.strip()
        if "github.com/" in cleaned:
            cleaned = cleaned.split("github.com/")[-1]
        cleaned = cleaned.rstrip("/").removesuffix(".git")
        parts = [p for p in cleaned.split("/") if p]
        if len(parts) >= 2:
            owner, name = parts[0], parts[1]
        else:
            return jsonify({
                "success": False,
                "error": "A valid repository 'owner/name' or GitHub URL is required.",
            }), 400

    result = ArchitectureService.get_architecture_data(
        owner=owner,
        name=name,
        force_refresh=force_refresh,
    )

    status_code = 200 if result.get("success") else 400
    payload = {
        "data": result,
        **result,
    }
    return jsonify(payload), status_code


@repository_bp.route("/architecture/<owner>/<name>", methods=["GET"])
def get_architecture_endpoint(owner: str, name: str):
    """
    Retrieve stored Phase 8 Architecture model JSON for a repository.
    """
    cached = ArchitectureService.load_cached_architecture(owner, name)
    if cached:
        return jsonify({
            "success": True,
            "is_cached": True,
            "data": cached,
            **cached,
        }), 200

    # If not cached yet, try building it automatically from shared knowledge
    result = ArchitectureService.get_architecture_data(owner=owner, name=name)
    if result.get("success"):
        return jsonify({
            "data": result,
            **result,
        }), 200

    return jsonify({
        "success": False,
        "error": f"No architecture model found for repository {owner}/{name}. Run analysis first.",
    }), 404


@repository_bp.route("/architecture/<owner>/<name>/cycles", methods=["GET"])
def get_architecture_cycles(owner: str, name: str):
    """
    Retrieve dependency cycle detection results specifically.
    """
    arch = ArchitectureService.get_architecture_data(owner=owner, name=name)
    if arch.get("success"):
        return jsonify({
            "success": True,
            "repository": f"{owner}/{name}",
            "cycles_detected": arch.get("cycles_detected", False),
            "cycles_count": len(arch.get("cycles", [])),
            "cycles": arch.get("cycles", []),
        }), 200

    return jsonify({
        "success": False,
        "error": f"Could not analyze cycles for {owner}/{name}.",
    }), 404


# ============================================================================
# Phase 1 Final Review: AI Project Report Generator Endpoints
# ============================================================================

@repository_bp.route("/report", methods=["POST"])
def generate_or_get_report():
    """
    Generate or retrieve the deterministic 22-section AI Project Report for a repository.
    Expected JSON: {"repo": "owner/name"} OR {"owner": "...", "name": "..."}
    Optional: {"force_refresh": false}
    """
    data = request.get_json(silent=True) or {}
    repo_input = data.get("repo") or data.get("full_name") or data.get("url") or ""
    force_refresh = bool(data.get("force_refresh", False))

    owner = data.get("owner")
    name = data.get("name")

    if not owner or not name:
        cleaned = repo_input.strip()
        if "github.com/" in cleaned:
            cleaned = cleaned.split("github.com/")[-1]
        cleaned = cleaned.rstrip("/").removesuffix(".git")
        parts = [p for p in cleaned.split("/") if p]
        if len(parts) >= 2:
            owner, name = parts[0], parts[1]
        else:
            return jsonify({
                "success": False,
                "error": "A valid repository 'owner/name' or GitHub URL is required to generate report.",
            }), 400

    try:
        result = ReportService.generate_report(
            owner=owner,
            name=name,
            force_refresh=force_refresh,
        )
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as ex:
        return jsonify({
            "success": False,
            "error": f"Could not generate project report for {owner}/{name}: {str(ex)}",
        }), 500


@repository_bp.route("/report/<owner>/<name>", methods=["GET"])
def get_report_endpoint(owner: str, name: str):
    """
    Retrieve stored or newly generated report JSON for a repository.
    """
    try:
        result = ReportService.generate_report(owner=owner, name=name, force_refresh=False)
        if result.get("success"):
            return jsonify(result), 200
        return jsonify(result), 400
    except Exception as ex:
        return jsonify({
            "success": False,
            "error": f"Could not retrieve report for {owner}/{name}: {str(ex)}",
        }), 500


@repository_bp.route("/report/<owner>/<name>/download", methods=["GET"])
def download_report_endpoint(owner: str, name: str):
    """
    Download the generated report in markdown (.md), html (.html), or json (.json) format.
    Query param: `format` = 'md' | 'html' | 'json' (default: 'html')
    """
    fmt = (request.args.get("format") or "html").lower().strip()
    if fmt not in {"md", "html", "json"}:
        fmt = "html"

    # Ensure report artifacts exist
    try:
        ReportService.generate_report(owner=owner, name=name, force_refresh=False)
        file_path = ReportService.get_report_file_path(owner, name, fmt)

        if not file_path.is_file():
            return jsonify({
                "success": False,
                "error": f"Report file in format '{fmt}' not found for {owner}/{name}.",
            }), 404

        mime_types = {
            "html": "text/html",
            "md": "text/markdown",
            "json": "application/json",
        }

        download_name = f"{owner}_{name}_CodeLens_AI_Report.{fmt}"
        return send_file(
            file_path,
            mimetype=mime_types.get(fmt, "text/plain"),
            as_attachment=True,
            download_name=download_name,
        )
    except Exception as ex:
        return jsonify({
            "success": False,
            "error": f"Failed to download report for {owner}/{name}: {str(ex)}",
        }), 500


@repository_bp.route("/report/cached", methods=["GET"])
def list_cached_reports():
    """
    List all repositories with stored reports in data/reports/.
    """
    reports = []
    reports_dir = ReportService.REPORTS_DIR
    if reports_dir.is_dir():
        for json_file in reports_dir.glob("*_report.json"):
            stem = json_file.stem.removesuffix("_report")
            parts = stem.split("_", 1)
            if len(parts) == 2:
                owner, name = parts[0], parts[1]
                reports.append({
                    "owner": owner,
                    "name": name,
                    "full_name": f"{owner}/{name}",
                    "path": str(json_file),
                })

    return jsonify({
        "success": True,
        "count": len(reports),
        "reports": reports,
    }), 200


# ============================================================================
# AI Repository Comprehension Assistant Chatbot Endpoints
# ============================================================================

@repository_bp.route("/chat/ask", methods=["POST"])
def repository_chat_ask():
    """
    Process a natural language question about an analyzed repository.
    Expected JSON: {"repo": "owner/repo", "question": "..."}
    """
    data = request.get_json(silent=True) or {}
    repo = data.get("repo") or data.get("repository") or ""
    question = data.get("message") or data.get("question") or data.get("query") or ""
    session_id = data.get("session_id")
    history = data.get("conversation") or data.get("history")

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


@repository_bp.route("/chat/suggested", methods=["GET"])
def repository_chat_suggested():
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


@repository_bp.route("/chat/clear", methods=["POST"])
def repository_chat_clear():
    """Clear chat conversation context for a session."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id") or ""
    if session_id:
        ChatbotService.clear_session(session_id)
    return jsonify({
        "success": True,
        "message": "Chat conversation context reset successfully.",
    }), 200





