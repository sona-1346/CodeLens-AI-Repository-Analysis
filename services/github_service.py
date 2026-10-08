"""
GitHub Service for CodeLens AI (Phase 3).
Handles repository URL input processing, single and batch validation,
staging repositories, and keyword-based repository discovery via GitHub API.
"""

import json
import os
import socket
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request
from utils.validators import validate_github_url, validate_repository_batch


class GitHubService:
    """Service handling GitHub repository intake, validation, and search discovery."""

    MAX_REPOSITORIES = 10
    MIN_REPOSITORIES = 1
    GITHUB_API_SEARCH_URL = "https://api.github.com/search/repositories"
    DEFAULT_TIMEOUT_SECONDS = 10
    _search_cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def validate_url(cls, url: Any) -> Dict[str, Any]:
        """
        Validate a single repository URL.

        Returns a structured dictionary:
        {
            "valid": bool,
            "repository": {"url": ..., "owner": ..., "name": ...} or None,
            "error": str or None
        }
        """
        is_valid, repo_data, error_msg = validate_github_url(url)
        return {
            "valid": is_valid,
            "repository": repo_data,
            "error": error_msg,
        }

    @classmethod
    def validate_batch(cls, urls: List[Any]) -> Dict[str, Any]:
        """
        Validate a batch of repository URLs (1 to 10 URLs).

        Returns a structured dictionary:
        {
            "valid": bool,
            "count": int,
            "repositories": [ {"url": ..., "owner": ..., "name": ...} ],
            "errors": [ ... ]
        }
        """
        if not isinstance(urls, list):
            return {
                "valid": False,
                "count": 0,
                "repositories": [],
                "errors": ["Input must be a list of repository URLs."],
            }

        # Filter and extract string URLs
        raw_urls = [str(item).strip() if item is not None else "" for item in urls]

        is_valid, valid_repos, errors = validate_repository_batch(
            raw_urls, min_limit=cls.MIN_REPOSITORIES, max_limit=cls.MAX_REPOSITORIES
        )

        return {
            "valid": is_valid,
            "count": len(valid_repos),
            "repositories": valid_repos,
            "errors": errors,
        }

    @classmethod
    def stage_repositories_for_analysis(cls, urls: List[Any]) -> Dict[str, Any]:
        """
        Validates and stages the repository list for subsequent stages.
        Per Phase 2/3 specification: Clicking Analyze should validate
        and pass the repository list without deep analysis or ranking.
        """
        batch_result = cls.validate_batch(urls)

        if not batch_result["valid"]:
            primary_error = (
                batch_result["errors"][0]
                if batch_result["errors"]
                else "Validation failed."
            )
            return {
                "success": False,
                "stage": "validation_failed",
                "error": primary_error,
                "errors": batch_result["errors"],
                "repositories": [],
                "count": 0,
            }

        repositories = batch_result["repositories"]
        count = len(repositories)

        return {
            "success": True,
            "stage": "staged_for_analysis",
            "count": count,
            "repositories": repositories,
            "message": f"Successfully validated and staged {count} repository{'ies' if count > 1 else ''} for analysis.",
        }

    @classmethod
    def search_repositories(
        cls,
        query: Any,
        per_page: int = 10,
        token: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Search public GitHub repositories by keyword using GitHub's REST API.

        Requirements enforced:
        - Uses GITHUB_TOKEN from parameter or .env if configured (never hard-coded).
        - Handles unauthenticated requests and rate limits gracefully.
        - Returns only data actually supplied by GitHub (no fake scores or ranking).
        - Robust error handling for empty query, 401 bad credentials, 403 rate limits,
          422 query syntax, and network failures.

        Returns structured dict:
        {
            "success": bool,
            "keyword": str,
            "total_count": int,
            "count": int,
            "repositories": List[dict],
            "message": str,
            "error": Optional[str],
            "status_code": int
        }
        """
        # 1. Validate keyword input
        if query is None or not isinstance(query, str):
            return {
                "success": False,
                "keyword": "",
                "total_count": 0,
                "count": 0,
                "repositories": [],
                "error": "Search keyword cannot be empty or non-string.",
                "message": "Search keyword cannot be empty.",
                "status_code": 400,
            }

        clean_query = query.strip()
        if not clean_query:
            return {
                "success": False,
                "keyword": "",
                "total_count": 0,
                "count": 0,
                "repositories": [],
                "error": "Search keyword cannot be empty or whitespace.",
                "message": "Please enter a valid search keyword.",
                "status_code": 400,
            }

        # 2. Resolve authentication token (env variable or parameter, never hard-coded)
        auth_token = token if token is not None else os.getenv("GITHUB_TOKEN", None)
        if auth_token:
            auth_token = auth_token.strip()

        # 3. Build API request URL and headers
        limit = max(1, min(int(per_page), 30))
        cache_key = f"{clean_query.lower()}:{limit}"
        if cache_key in cls._search_cache:
            return cls._search_cache[cache_key]

        encoded_query = urllib.parse.quote_plus(clean_query)
        api_url = f"{cls.GITHUB_API_SEARCH_URL}?q={encoded_query}&per_page={limit}"

        headers = {
            "User-Agent": "CodeLens-AI-System/1.0",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        req = urllib.request.Request(api_url, headers=headers, method="GET")
        req_timeout = timeout if timeout is not None else cls.DEFAULT_TIMEOUT_SECONDS

        # 4. Execute request with comprehensive error handling
        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as response:
                status_code = response.status
                body_bytes = response.read()
                raw_data = json.loads(body_bytes.decode("utf-8"))

                total_count = raw_data.get("total_count", 0)
                raw_items = raw_data.get("items", [])

                # Extract only factual information returned by GitHub
                repositories = []
                for item in raw_items:
                    owner_login = item.get("owner", {}).get("login", "") if item.get("owner") else ""
                    repo_name = item.get("name", "")
                    html_url = item.get("html_url", "")
                    description = item.get("description") or "No description provided."
                    language = item.get("language") or "Not specified"
                    stars = item.get("stargazers_count", 0)
                    topics = item.get("topics") or []
                    is_fork = bool(item.get("fork", False))

                    repositories.append({
                        "name": repo_name,
                        "owner": owner_login,
                        "full_name": f"{owner_login}/{repo_name}" if owner_login else repo_name,
                        "url": html_url,
                        "description": description,
                        "language": language,
                        "stars": stars,
                        "topics": topics,
                        "is_fork": is_fork,
                        "fork_status": "Fork" if is_fork else "Source",
                    })

                msg = (
                    f"Found {len(repositories)} candidate repositories matching '{clean_query}'."
                    if repositories
                    else f"No public repositories found matching keyword '{clean_query}'."
                )

                search_result = {
                    "success": True,
                    "keyword": clean_query,
                    "total_count": total_count,
                    "count": len(repositories),
                    "repositories": repositories,
                    "message": msg,
                    "error": None,
                    "status_code": status_code,
                }
                cls._search_cache[cache_key] = search_result
                return search_result

        except urllib.error.HTTPError as http_err:
            status_code = http_err.code
            err_body = ""
            err_message = None

            try:
                err_body = http_err.read().decode("utf-8", errors="ignore")
                err_json = json.loads(err_body)
                err_message = err_json.get("message")
            except Exception:
                pass

            if status_code == 401:
                friendly_error = (
                    "GitHub API Error: Invalid or expired GitHub token (Bad credentials). "
                    "Please verify your GITHUB_TOKEN in .env or leave it blank to search unauthenticated."
                )
            elif status_code == 403:
                friendly_error = (
                    "GitHub API rate limit exceeded. If you do not have a GITHUB_TOKEN configured in .env, "
                    "GitHub limits unauthenticated search requests to 10 per minute. "
                    "Please wait a minute or set a personal GITHUB_TOKEN in your .env file."
                )
            elif status_code == 422:
                friendly_error = (
                    f"GitHub API Error (422): Validation failed for query '{clean_query}'. "
                    f"{err_message or 'Please simplify your keyword search.'}"
                )
            else:
                friendly_error = (
                    f"GitHub API Error ({status_code}): {err_message or 'The GitHub API was unable to process the request.'}"
                )

            return {
                "success": False,
                "keyword": clean_query,
                "total_count": 0,
                "count": 0,
                "repositories": [],
                "error": friendly_error,
                "message": friendly_error,
                "status_code": status_code,
            }

        except (urllib.error.URLError, socket.gaierror, ConnectionError) as net_err:
            reason = getattr(net_err, "reason", str(net_err))
            friendly_error = (
                f"Network error: Unable to connect to GitHub API ({reason}). "
                "Please verify your internet connection."
            )
            return {
                "success": False,
                "keyword": clean_query,
                "total_count": 0,
                "count": 0,
                "repositories": [],
                "error": friendly_error,
                "message": friendly_error,
                "status_code": 503,
            }

        except (socket.timeout, TimeoutError):
            friendly_error = (
                "Network timeout: The request to the GitHub API timed out after "
                f"{req_timeout} seconds. Please try again."
            )
            return {
                "success": False,
                "keyword": clean_query,
                "total_count": 0,
                "count": 0,
                "repositories": [],
                "error": friendly_error,
                "message": friendly_error,
                "status_code": 504,
            }

        except Exception as ex:
            friendly_error = f"Unexpected error while communicating with GitHub API: {str(ex)}"
            return {
                "success": False,
                "keyword": clean_query,
                "total_count": 0,
                "count": 0,
                "repositories": [],
                "error": friendly_error,
                "message": friendly_error,
                "status_code": 500,
            }
