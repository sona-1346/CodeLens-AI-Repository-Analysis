"""
Validation utilities for CodeLens AI.
Validates GitHub repository URLs and batch inputs according to Phase 2 requirements.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# GitHub username/org: alphanumeric and single hyphens, 1-39 chars, cannot start/end with hyphen
GITHUB_OWNER_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")

# GitHub repository name: alphanumeric, hyphen, underscore, dot, 1-100 chars
GITHUB_REPO_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")

# Reserved GitHub paths that cannot be user or organization accounts
RESERVED_GITHUB_NAMES = {
    "about",
    "collections",
    "contact",
    "customer-stories",
    "enterprise",
    "events",
    "explore",
    "features",
    "issues",
    "join",
    "login",
    "marketplace",
    "notifications",
    "organizations",
    "pricing",
    "pulls",
    "search",
    "security",
    "settings",
    "sponsors",
    "topics",
    "trending",
}


def validate_github_url(url: Any) -> Tuple[bool, Optional[Dict[str, str]], Optional[str]]:
    """
    Validate a single GitHub repository URL.

    Checks:
    - Non-empty string
    - Valid URL structure with http/https
    - GitHub host (github.com or www.github.com)
    - Valid owner (exists and adheres to GitHub naming rules)
    - Valid repository name (exists and adheres to repository naming rules)
    - Rejects subpaths (e.g. /tree/main, /issues, /pull/1)

    Returns:
        (is_valid, repository_dict, error_message)
        If valid: (True, {"url": canonical_url, "owner": owner, "name": name}, None)
        If invalid: (False, None, error_message)
    """
    if url is None:
        return False, None, "Repository URL cannot be empty."

    if not isinstance(url, str):
        return False, None, "Repository URL must be a valid string."

    clean_url = url.strip()
    if not clean_url:
        return False, None, "Repository URL cannot be empty or blank."

    # Parse URL
    try:
        parsed = urlparse(clean_url)
    except Exception:
        return False, None, f"Malformed URL: '{clean_url}'."

    # Verify scheme
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return (
            False,
            None,
            f"Invalid URL protocol '{parsed.scheme}'. Must be 'https://' or 'http://'.",
        )

    # Verify hostname
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("github.com", "www.github.com"):
        return (
            False,
            None,
            f"'{clean_url}' is not a GitHub URL. Host must be 'github.com'.",
        )

    # Clean path segments (split by '/', filter out empty strings)
    path_segments = [seg for seg in parsed.path.strip("/").split("/") if seg]

    if len(path_segments) == 0:
        return (
            False,
            None,
            "GitHub URL is missing repository path. Expected format: https://github.com/owner/repository",
        )

    if len(path_segments) == 1:
        return (
            False,
            None,
            f"GitHub URL is missing repository name. Owner '{path_segments[0]}' found, but no repository specified.",
        )

    if len(path_segments) > 2:
        return (
            False,
            None,
            "URL points to a sub-page (e.g., branch, issue, or commit). Please provide the root repository URL.",
        )

    owner, repo_name = path_segments[0], path_segments[1]

    # Strip .git suffix if present
    if repo_name.lower().endswith(".git"):
        repo_name = repo_name[:-4]

    if not repo_name:
        return False, None, "Repository name in URL cannot be empty."

    # Check reserved words for owner
    if owner.lower() in RESERVED_GITHUB_NAMES:
        return (
            False,
            None,
            f"'{owner}' is a reserved GitHub system endpoint, not a valid repository owner.",
        )

    # Validate owner format
    if not GITHUB_OWNER_REGEX.match(owner):
        return (
            False,
            None,
            f"Invalid owner format '{owner}'. GitHub usernames/orgs may only contain alphanumeric characters and hyphens.",
        )

    # Validate repository name format
    if not GITHUB_REPO_REGEX.match(repo_name):
        return (
            False,
            None,
            f"Invalid repository name format '{repo_name}'.",
        )

    canonical_url = f"https://github.com/{owner}/{repo_name}"

    return True, {
        "url": canonical_url,
        "owner": owner,
        "name": repo_name,
    }, None


def validate_repository_batch(
    urls: List[str], min_limit: int = 1, max_limit: int = 10
) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    """
    Validate a collection of GitHub repository URLs (1 to 10 URLs).

    Checks:
    - List bounds (1 <= len <= 10)
    - Validates each URL individually
    - Detects and rejects duplicates (case-insensitive comparison)

    Returns:
        (is_valid, list_of_repositories, list_of_errors)
    """
    errors: List[str] = []
    valid_repos: List[Dict[str, str]] = []
    seen_identifiers: set = set()

    if not urls or len(urls) < min_limit:
        return False, [], [f"At least {min_limit} repository URL must be provided."]

    if len(urls) > max_limit:
        return (
            False,
            [],
            [f"A maximum of {max_limit} repository URLs is allowed. You provided {len(urls)}."],
        )

    for idx, item in enumerate(urls, start=1):
        is_valid, repo_data, err_msg = validate_github_url(item)
        if not is_valid:
            errors.append(f"Repository {idx}: {err_msg}")
            continue

        assert repo_data is not None
        identifier = f"{repo_data['owner'].lower()}/{repo_data['name'].lower()}"
        if identifier in seen_identifiers:
            errors.append(
                f"Repository {idx}: Duplicate entry detected for '{repo_data['owner']}/{repo_data['name']}'."
            )
            continue

        seen_identifiers.add(identifier)
        valid_repos.append(repo_data)

    if errors:
        return False, valid_repos, errors

    return True, valid_repos, []
