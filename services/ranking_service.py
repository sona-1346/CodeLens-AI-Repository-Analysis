"""
Repository Ranking & Suitability Evaluation Service for CodeLens AI (Phase 4).
Evaluates GitHub repositories based on measurable, factual factors
to determine their suitability for software comprehension and architectural analysis.

Calculates:
- Keyword & domain relevance
- Code architecture & source code availability
- Documentation & comprehension quality
- Repository completeness, maintenance, and community validation

Produces a normalized (0-100%) "Repository Analysis Suitability" percentage,
ranks alternatives, identifies the Recommended Repository, and provides a factual reason.
"""

from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request
from config.config import Config


class RankingService:
    """Service evaluating and ranking candidate repositories for analysis suitability."""

    # Default configurable factor weights
    DEFAULT_WEIGHTS = {
        "keyword_relevance": 0.25,
        "code_architecture": 0.30,
        "documentation": 0.25,
        "completeness_activity": 0.20,
    }

    # In-memory session cache for repository metadata to preserve API quotas
    _metadata_cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_configured_weights(cls, custom_weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Retrieve active scoring weights, merging defaults with Config and custom overrides.
        """
        weights = dict(cls.DEFAULT_WEIGHTS)
        if hasattr(Config, "SUITABILITY_WEIGHTS") and isinstance(Config.SUITABILITY_WEIGHTS, dict):
            weights.update(Config.SUITABILITY_WEIGHTS)
        if custom_weights and isinstance(custom_weights, dict):
            for k, v in custom_weights.items():
                if k in weights and isinstance(v, (int, float)) and v >= 0:
                    weights[k] = float(v)

        total = sum(weights.values())
        if total <= 0:
            return dict(cls.DEFAULT_WEIGHTS)

        # Normalize weights so they sum to 1.0
        return {k: round(v / total, 4) for k, v in weights.items()}

    @classmethod
    def fetch_repository_metadata(
        cls,
        owner: str,
        name: str,
        token: Optional[str] = None,
        fallback_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch live repository metadata and README details from GitHub REST API.
        Uses in-memory cache and falls back gracefully to fallback_data if rate-limited or offline.
        """
        cache_key = f"{owner.lower()}/{name.lower()}"
        if cache_key in cls._metadata_cache:
            return cls._metadata_cache[cache_key]

        auth_token = token if token is not None else os.getenv("GITHUB_TOKEN", None)
        headers = {
            "User-Agent": "CodeLens-AI-Ranking/1.0",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token.strip()}"

        metadata: Dict[str, Any] = {
            "owner": owner,
            "name": name,
            "full_name": f"{owner}/{name}",
            "url": f"https://github.com/{owner}/{name}",
            "description": None,
            "language": None,
            "size": 0,
            "stars": 0,
            "forks": 0,
            "open_issues": 0,
            "topics": [],
            "license": None,
            "archived": False,
            "is_fork": False,
            "pushed_at": None,
            "has_readme": False,
            "readme_size": 0,
            "readme_name": None,
            "data_source": "api_live",
        }

        # Populate initial values from fallback if provided
        if fallback_data:
            metadata["description"] = fallback_data.get("description")
            metadata["language"] = fallback_data.get("language")
            metadata["stars"] = fallback_data.get("stars", fallback_data.get("stargazers_count", 0))
            metadata["forks"] = fallback_data.get("forks", fallback_data.get("forks_count", 0))
            metadata["open_issues"] = fallback_data.get("open_issues", fallback_data.get("open_issues_count", 0))
            metadata["size"] = fallback_data.get("size", 0)
            metadata["topics"] = fallback_data.get("topics", [])
            metadata["is_fork"] = fallback_data.get("is_fork", fallback_data.get("fork", False))
            metadata["archived"] = fallback_data.get("archived", False)
            metadata["license"] = fallback_data.get("license") or fallback_data.get("license_name")
            metadata["pushed_at"] = fallback_data.get("pushed_at") or fallback_data.get("updated_at")
            metadata["has_readme"] = fallback_data.get("has_readme", False)
            metadata["readme_size"] = fallback_data.get("readme_size", fallback_data.get("readme_bytes", 0))

        # 1. Fetch Repository Details
        api_repo_url = f"https://api.github.com/repos/{owner}/{name}"
        try:
            req = urllib.request.Request(api_repo_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                repo_json = json.loads(resp.read().decode("utf-8"))
                metadata["description"] = repo_json.get("description") or metadata["description"]
                metadata["language"] = repo_json.get("language") or metadata["language"]
                metadata["size"] = repo_json.get("size", 0)
                metadata["stars"] = repo_json.get("stargazers_count", metadata["stars"])
                metadata["forks"] = repo_json.get("forks_count", 0)
                metadata["open_issues"] = repo_json.get("open_issues_count", 0)
                metadata["topics"] = repo_json.get("topics") or metadata["topics"]
                metadata["archived"] = repo_json.get("archived", False)
                metadata["is_fork"] = repo_json.get("fork", metadata["is_fork"])
                metadata["pushed_at"] = repo_json.get("pushed_at")
                if repo_json.get("license"):
                    metadata["license"] = repo_json["license"].get("spdx_id") or repo_json["license"].get("name")
        except urllib.error.HTTPError as http_err:
            metadata["data_source"] = f"api_http_{http_err.code}"
        except Exception as ex:
            metadata["data_source"] = f"api_error_{type(ex).__name__}"

        # 2. Fetch README Metadata (does not clone or download full codebase)
        readme_url = f"https://api.github.com/repos/{owner}/{name}/readme"
        try:
            req_readme = urllib.request.Request(readme_url, headers=headers)
            with urllib.request.urlopen(req_readme, timeout=6) as resp_readme:
                readme_json = json.loads(resp_readme.read().decode("utf-8"))
                metadata["has_readme"] = True
                metadata["readme_size"] = readme_json.get("size", 0)
                metadata["readme_name"] = readme_json.get("name", "README.md")
        except urllib.error.HTTPError as http_err:
            if http_err.code == 404:
                metadata["has_readme"] = False
                metadata["readme_size"] = 0
        except Exception:
            pass

        cls._metadata_cache[cache_key] = metadata
        return metadata

    @classmethod
    def calculate_suitability(
        cls,
        metadata: Dict[str, Any],
        keyword: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate Repository Analysis Suitability (0-100%) from actual metadata.

        Factors:
        1. Keyword Relevance (0-100)
        2. Code Architecture & Source Code Availability (0-100)
        3. Documentation Quality (0-100)
        4. Completeness & Maintenance Activity (0-100)
        """
        active_weights = cls.get_configured_weights(weights)

        # ----------------------------------------------------------------------
        # Factor 1: Keyword Relevance
        # ----------------------------------------------------------------------
        keyword_score = 0.0
        kw_reasons = []

        if keyword and keyword.strip():
            clean_kw = keyword.strip().lower()
            tokens = [t for t in re.split(r"[\s_,-]+", clean_kw) if len(t) > 1]
            if not tokens:
                tokens = [clean_kw]

            repo_name_lower = (metadata.get("name") or "").lower()
            desc_lower = (metadata.get("description") or "").lower()
            topics_lower = [str(t).lower() for t in (metadata.get("topics") or [])]
            lang_lower = (metadata.get("language") or "").lower()

            name_matches = sum(1 for t in tokens if t in repo_name_lower)
            desc_matches = sum(1 for t in tokens if t in desc_lower)
            topic_matches = sum(1 for t in tokens if any(t in top for top in topics_lower))
            lang_match = any(t in lang_lower for t in tokens)

            # Name matching: up to 40 pts
            if clean_kw in repo_name_lower:
                keyword_score += 40.0
                kw_reasons.append("exact keyword in repository name")
            elif name_matches > 0:
                keyword_score += min(35.0, name_matches * 20.0)
                kw_reasons.append("keyword tokens in repository name")

            # Description matching: up to 30 pts
            if clean_kw in desc_lower:
                keyword_score += 30.0
                kw_reasons.append("keyword in description")
            elif desc_matches > 0:
                keyword_score += min(25.0, desc_matches * 15.0)

            # Topic matching: up to 20 pts
            if topic_matches > 0:
                keyword_score += min(20.0, topic_matches * 10.0)
                kw_reasons.append("relevant topic tags")

            # Language match: 10 pts
            if lang_match:
                keyword_score += 10.0
                kw_reasons.append(f"primary language matches {metadata.get('language')}")

            keyword_score = min(100.0, keyword_score)
        else:
            # Baseline relevance when user provided direct URLs without a search keyword
            base = 65.0
            if metadata.get("description"):
                base += 15.0
            if metadata.get("topics"):
                base += 10.0
            keyword_score = min(90.0, base)
            kw_reasons.append("direct repository input")

        # ----------------------------------------------------------------------
        # Factor 2: Code Architecture & Source Code Availability
        # ----------------------------------------------------------------------
        arch_score = 0.0
        arch_reasons = []

        # 1. Identified primary language (essential for AST parser)
        language = metadata.get("language")
        if language and language != "Not specified":
            arch_score += 35.0
            arch_reasons.append(f"identified {language} codebase")
        else:
            arch_reasons.append("unspecified primary language")

        # 2. Codebase volume / size (size in KB from GitHub)
        size_kb = metadata.get("size", 0)
        if size_kb == 0:
            arch_score += 0.0
            arch_reasons.append("empty codebase (0 KB)")
        elif size_kb < 30:
            arch_score += 15.0
            arch_reasons.append("minimal size (<30 KB)")
        elif size_kb < 300:
            arch_score += 25.0
            arch_reasons.append("lightweight modular codebase")
        elif size_kb <= 80000:
            arch_score += 35.0
            arch_reasons.append("substantial multi-module source code")
        else:
            # Huge repositories are still valid but may require extensive parsing
            arch_score += 30.0
            arch_reasons.append("very large monolithic repository")

        # 3. Source repository vs fork
        if not metadata.get("is_fork"):
            arch_score += 15.0
        else:
            arch_score += 5.0
            arch_reasons.append("fork repository")

        # 4. Multi-module readiness (has topics, license, or size > 100KB)
        if size_kb > 100:
            arch_score += 15.0

        arch_score = min(100.0, arch_score)

        # ----------------------------------------------------------------------
        # Factor 3: Documentation Quality
        # ----------------------------------------------------------------------
        doc_score = 0.0
        doc_reasons = []

        # Description presence
        desc = metadata.get("description")
        if desc and len(desc.strip()) >= 30:
            doc_score += 30.0
            doc_reasons.append("detailed project description")
        elif desc and len(desc.strip()) >= 5:
            doc_score += 15.0
        else:
            doc_reasons.append("missing description")

        # README presence & depth
        if metadata.get("has_readme"):
            readme_size = metadata.get("readme_size", 0)
            if readme_size > 2000:
                doc_score += 40.0
                doc_reasons.append("comprehensive README documentation")
            elif readme_size >= 300:
                doc_score += 30.0
                doc_reasons.append("standard README file")
            else:
                doc_score += 15.0
                doc_reasons.append("minimal README stub")
        else:
            doc_reasons.append("missing README")

        # Topics configured (helps multi-agent contextualization)
        topics = metadata.get("topics") or []
        if len(topics) >= 3:
            doc_score += 15.0
        elif len(topics) >= 1:
            doc_score += 8.0

        # Open-source license (essential for academic & enterprise comprehension)
        if metadata.get("license"):
            doc_score += 15.0
            doc_reasons.append(f"{metadata['license']} license")

        doc_score = min(100.0, doc_score)

        # ----------------------------------------------------------------------
        # Factor 4: Repository Completeness, Maintenance & Activity
        # ----------------------------------------------------------------------
        activity_score = 0.0
        act_reasons = []

        # Archived check
        if metadata.get("archived"):
            activity_score += 0.0
            act_reasons.append("archived/read-only repository")
        else:
            activity_score += 30.0

        # Maintenance recency (pushed_at ISO timestamp)
        pushed_at_str = metadata.get("pushed_at")
        if pushed_at_str:
            try:
                # Parse ISO timestamp (e.g. 2026-09-08T16:40:53Z)
                clean_time = pushed_at_str.replace("Z", "+00:00")
                pushed_dt = datetime.fromisoformat(clean_time)
                now_dt = datetime.now(timezone.utc)
                days_since_push = (now_dt - pushed_dt).days

                if days_since_push <= 180:
                    activity_score += 30.0
                    act_reasons.append("actively maintained (pushed recently)")
                elif days_since_push <= 365:
                    activity_score += 20.0
                    act_reasons.append("maintained within past year")
                elif days_since_push <= 730:
                    activity_score += 10.0
                    act_reasons.append("moderate maintenance history")
                else:
                    activity_score += 5.0
                    act_reasons.append("infrequent recent commits")
            except Exception:
                activity_score += 15.0
        else:
            activity_score += 10.0

        # Community adoption & stability (indicates real-world production project)
        stars = metadata.get("stars", 0)
        forks = metadata.get("forks", 0)

        if stars >= 500:
            activity_score += 25.0
        elif stars >= 50:
            activity_score += 18.0
        elif stars >= 5:
            activity_score += 10.0
        else:
            activity_score += 3.0

        if forks >= 20:
            activity_score += 15.0
        elif forks >= 1:
            activity_score += 8.0

        activity_score = min(100.0, activity_score)

        # ----------------------------------------------------------------------
        # Weighted Overall Suitability Score (0-100%)
        # ----------------------------------------------------------------------
        raw_suitability = (
            keyword_score * active_weights["keyword_relevance"]
            + arch_score * active_weights["code_architecture"]
            + doc_score * active_weights["documentation"]
            + activity_score * active_weights["completeness_activity"]
        )

        final_percentage = int(round(max(0.0, min(100.0, raw_suitability))))

        # ----------------------------------------------------------------------
        # Generate Factual Reason Summary
        # ----------------------------------------------------------------------
        reason = cls._generate_reason(
            final_percentage=final_percentage,
            keyword_score=keyword_score,
            arch_score=arch_score,
            doc_score=doc_score,
            activity_score=activity_score,
            metadata=metadata,
        )

        return {
            "suitability_percentage": final_percentage,
            "factors": {
                "keyword_relevance": round(keyword_score, 1),
                "code_architecture": round(arch_score, 1),
                "documentation": round(doc_score, 1),
                "completeness_activity": round(activity_score, 1),
            },
            "weights": active_weights,
            "reason": reason,
            "metadata": metadata,
        }

    @classmethod
    def _generate_reason(
        cls,
        final_percentage: int,
        keyword_score: float,
        arch_score: float,
        doc_score: float,
        activity_score: float,
        metadata: Dict[str, Any],
    ) -> str:
        """Construct a factual, descriptive explanation for the calculated percentage."""
        positives = []
        cautions = []

        lang = metadata.get("language")
        size_kb = metadata.get("size", 0)

        if keyword_score >= 70:
            positives.append("high keyword relevance")
        elif keyword_score < 40:
            cautions.append("lower keyword relevance")

        if arch_score >= 75 and lang:
            positives.append(f"well-structured {lang} codebase ({size_kb} KB)")
        elif not lang:
            cautions.append("unspecified primary programming language")
        elif size_kb < 20:
            cautions.append("minimal codebase volume")

        if doc_score >= 75:
            positives.append("comprehensive documentation and README")
        elif not metadata.get("has_readme"):
            cautions.append("missing README")
        elif not metadata.get("description"):
            cautions.append("lacks repository description")

        if activity_score >= 75:
            positives.append("active maintenance and established community")
        elif metadata.get("archived"):
            cautions.append("archived repository status")

        if final_percentage >= 80:
            base = "Highly suitable for deep software comprehension. "
        elif final_percentage >= 60:
            base = "Suitable for architectural analysis. "
        elif final_percentage >= 40:
            base = "Moderate suitability for analysis. "
        else:
            base = "Low analysis suitability. "

        parts = []
        if positives:
            parts.append("Featuring " + ", ".join(positives))
        if cautions:
            parts.append("Noted with " + ", ".join(cautions))

        if parts:
            return base + "; ".join(parts) + "."
        return base + f"Demonstrates balanced metrics across architecture and documentation ({final_percentage}%)."

    @classmethod
    def rank_repositories(
        cls,
        repositories: List[Dict[str, Any]],
        keyword: Optional[str] = None,
        custom_weights: Optional[Dict[str, float]] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate and rank multiple repositories.

        Returns structured ranking with Rank 1 identified as Recommended Repository.
        """
        if not repositories or not isinstance(repositories, list):
            return {
                "success": False,
                "error": "At least one repository must be provided for evaluation.",
                "total_evaluated": 0,
                "recommended_repository": None,
                "ranking": [],
                "weights_applied": cls.get_configured_weights(custom_weights),
            }

        evaluated_list = []

        for repo in repositories:
            if isinstance(repo, str):
                repo = {"url": repo}
            elif not isinstance(repo, dict):
                continue

            owner = repo.get("owner")
            name = repo.get("name")
            if not owner or not name:
                # Attempt to extract owner and name from url
                url = repo.get("url", "")
                cleaned = url.replace("https://github.com/", "").replace("http://github.com/", "").strip("/")
                if cleaned.endswith(".git"):
                    cleaned = cleaned[:-4]
                segments = [s for s in cleaned.split("/") if s]
                if len(segments) >= 2:
                    owner, name = segments[0], segments[1]
                else:
                    continue

            # Fetch metadata (live with graceful fallbacks)
            meta = cls.fetch_repository_metadata(
                owner=owner,
                name=name,
                token=token,
                fallback_data=repo,
            )

            # Calculate actual suitability score
            eval_result = cls.calculate_suitability(
                metadata=meta,
                keyword=keyword,
                weights=custom_weights,
            )

            evaluated_list.append({
                "owner": owner,
                "name": name,
                "full_name": f"{owner}/{name}",
                "url": repo.get("url") or f"https://github.com/{owner}/{name}",
                "suitability_percentage": eval_result["suitability_percentage"],
                "factors": eval_result["factors"],
                "reason": eval_result["reason"],
                "language": meta.get("language") or "Not specified",
                "stars": meta.get("stars", 0),
                "forks": meta.get("forks", 0),
                "size_kb": meta.get("size", 0),
                "has_readme": meta.get("has_readme", False),
                "is_fork": meta.get("is_fork", False),
                "archived": meta.get("archived", False),
                "license": meta.get("license"),
            })

        if not evaluated_list:
            return {
                "success": False,
                "error": "No valid repositories could be evaluated.",
                "total_evaluated": 0,
                "recommended_repository": None,
                "ranking": [],
                "weights_applied": cls.get_configured_weights(custom_weights),
            }

        # Sort in descending order of suitability percentage (Rank 1 has highest score)
        # Secondary sort key by stars to break ties deterministically
        evaluated_list.sort(
            key=lambda r: (r["suitability_percentage"], r["stars"]),
            reverse=True,
        )

        # Assign ranks and mark Recommended Repository
        for index, item in enumerate(evaluated_list, start=1):
            item["rank"] = index
            item["is_recommended"] = (index == 1)

        recommended = evaluated_list[0] if evaluated_list else None

        return {
            "success": True,
            "keyword": keyword,
            "total_evaluated": len(evaluated_list),
            "recommended_repository": recommended,
            "ranking": evaluated_list,
            "weights_applied": cls.get_configured_weights(custom_weights),
            "message": (
                f"Successfully evaluated and ranked {len(evaluated_list)} repositories. "
                f"'{recommended['full_name']}' is recommended with {recommended['suitability_percentage']}% suitability."
            ),
        }
