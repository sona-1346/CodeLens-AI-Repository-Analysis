"""
Unified LLM Client for CodeLens AI Repository Comprehension Assistant.

Provides a unified interface for interacting with real LLM providers:
- Google Gemini (REST API: gemini-1.5-flash, gemini-2.0-flash, etc.)
- OpenAI & OpenAI-compatible endpoints (gpt-4o-mini, Groq, Ollama, OpenRouter, vLLM)

Configurable strictly via environment variables without hardcoded keys.
"""

from dataclasses import dataclass, field
import json
import logging
import os
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    """Represents the response from the LLM provider."""
    content: str
    success: bool
    error: Optional[str] = None
    model: str = ""
    provider: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)


class LLMClient:
    """Configurable client for calling real LLM backends."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_seconds: int = 35,
    ):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = (
                os.getenv("GROQ_API_KEY")
                or os.getenv("LLM_API_KEY")
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("OPENAI_API_KEY")
            )

        if model is not None:
            self.model = model
        else:
            self.model = os.getenv("GROQ_MODEL") or os.getenv("LLM_MODEL") or ""

        self.provider = (provider or os.getenv("LLM_PROVIDER", "auto")).lower()
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.temperature = float(temperature if temperature is not None else os.getenv("LLM_TEMPERATURE", "0.2"))
        self.max_tokens = int(max_tokens if max_tokens is not None else os.getenv("LLM_MAX_TOKENS", "1200"))
        self.timeout_seconds = timeout_seconds

        self.resolved_provider = self._resolve_provider()

        # If model is not explicitly set and provider is not Groq, default to provider standard
        if not self.model:
            if self.resolved_provider == "gemini":
                self.model = "gemini-1.5-flash"
            elif self.resolved_provider == "openai":
                self.model = "gpt-4o-mini"
            elif self.resolved_provider == "ollama":
                self.model = "llama3"

    def _resolve_provider(self) -> str:
        """Resolve LLM provider based on provider setting, model name, and keys."""
        if self.provider in ("groq", "gemini", "openai", "ollama"):
            return self.provider

        # Check explicit Groq API key format
        if (self.api_key or "").startswith("gsk_"):
            return "groq"

        # Auto-detect from model name first if specified
        model_lower = (self.model or "").lower()
        if "gemini" in model_lower:
            return "gemini"
        if any(prefix in model_lower for prefix in ("gpt", "o1", "o3", "claude")):
            return "openai"
        if any(g in model_lower for g in ("llama", "mixtral", "gemma", "whisper", "groq", "qwen", "orpheus")):
            return "groq"
        if "ollama" in model_lower or (self.base_url and "11434" in self.base_url):
            return "ollama"

        # Check other environment variable presence
        if os.getenv("GEMINI_API_KEY") and not os.getenv("OPENAI_API_KEY"):
            return "gemini"
        if os.getenv("OPENAI_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            return "openai"

        # Default fallback provider
        return "groq" if os.getenv("GROQ_API_KEY") else "gemini"

    @property
    def is_configured(self) -> bool:
        """Check whether the client has an active API key or local endpoint."""
        if self.resolved_provider == "ollama":
            return True
        return bool(self.api_key and self.api_key.strip())

    def generate(
        self,
        system_instruction: str,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> LLMResult:
        """
        Execute completion with selected real LLM provider.
        """
        if not self.is_configured:
            logger.warning("[CodeLens AI LLM] No API key configured in environment.")
            key_name = "GROQ_API_KEY" if self.resolved_provider == "groq" else "LLM_API_KEY"
            provider_name = "Groq" if self.resolved_provider == "groq" else "LLM"
            return LLMResult(
                content="",
                success=False,
                error=f"AI service is not configured. Please check the {provider_name} API configuration ({key_name} is not set).",
                model=self.model,
                provider=self.resolved_provider,
            )

        # If Groq is the provider and GROQ_MODEL is missing, return a clear configuration error
        if self.resolved_provider == "groq" and not (self.model and self.model.strip()):
            logger.warning("[CodeLens AI LLM] GROQ_MODEL is not configured in environment.")
            return LLMResult(
                content="",
                success=False,
                error="GROQ_MODEL is not configured in environment. Please set GROQ_MODEL in your .env file.",
                model="",
                provider="groq",
            )

        try:
            if self.resolved_provider == "groq":
                return self._call_groq(system_instruction, user_prompt, history)
            elif self.resolved_provider == "gemini":
                return self._call_gemini(system_instruction, user_prompt, history)
            elif self.resolved_provider == "openai":
                return self._call_openai(system_instruction, user_prompt, history)
            elif self.resolved_provider == "ollama":
                return self._call_ollama(system_instruction, user_prompt, history)
            else:
                return self._call_groq(system_instruction, user_prompt, history)
        except Exception as ex:
            logger.exception(f"[CodeLens AI LLM] Unexpected exception calling LLM: {ex}")
            return LLMResult(
                content="",
                success=False,
                error=f"AI service encountered an unexpected error: {str(ex)}",
                model=self.model,
                provider=self.resolved_provider,
            )

    def _call_gemini(
        self,
        system_instruction: str,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> LLMResult:
        """Call Google Gemini REST API endpoint."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={urllib.parse.quote(self.api_key or '')}"
        )

        contents = []
        for turn in history or []:
            role = "model" if turn.get("role") in ("assistant", "model") else "user"
            text = turn.get("content", "").strip()
            if text:
                contents.append({"role": role, "parts": [{"text": text}]})

        contents.append({"role": "user", "parts": [{"text": user_prompt}]})

        payload = {
            "contents": contents,
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }

        req_data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode("utf-8"))

            candidates = data.get("candidates", [])
            if not candidates:
                return LLMResult(
                    content="",
                    success=False,
                    error="Gemini returned no response candidates.",
                    model=self.model,
                    provider="gemini",
                )

            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [])
            if not parts:
                return LLMResult(
                    content="",
                    success=False,
                    error="Gemini returned empty message parts.",
                    model=self.model,
                    provider="gemini",
                )

            answer = parts[0].get("text", "").strip()
            usage = data.get("usageMetadata", {})

            return LLMResult(
                content=answer,
                success=True,
                model=self.model,
                provider="gemini",
                usage=usage,
            )

        except urllib.error.HTTPError as http_err:
            error_body = ""
            try:
                error_body = http_err.read().decode("utf-8")
                err_json = json.loads(error_body)
                err_msg = err_json.get("error", {}).get("message", error_body)
            except Exception:
                err_msg = f"HTTP Error {http_err.code}: {http_err.reason}"

            if http_err.code in (401, 403):
                clean_err = f"Authentication error: Invalid or expired API key. Details: {err_msg}"
            elif http_err.code == 429:
                clean_err = "AI provider rate limit reached. Please wait a moment and try again."
            elif http_err.code in (500, 503):
                clean_err = "Gemini AI service is temporarily unavailable. Please retry shortly."
            else:
                clean_err = f"Gemini API error ({http_err.code}): {err_msg}"

            logger.error(f"[CodeLens AI LLM] Gemini HTTP error: {clean_err}")
            return LLMResult(
                content="",
                success=False,
                error=clean_err,
                model=self.model,
                provider="gemini",
            )
        except urllib.error.URLError as url_err:
            logger.error(f"[CodeLens AI LLM] Network error reaching Gemini: {url_err}")
            return LLMResult(
                content="",
                success=False,
                error=f"Network error communicating with AI service: {str(url_err.reason)}",
                model=self.model,
                provider="gemini",
            )
        except TimeoutError:
            logger.error("[CodeLens AI LLM] Gemini request timed out.")
            return LLMResult(
                content="",
                success=False,
                error="The AI service request timed out. Please try again.",
                model=self.model,
                provider="gemini",
            )

    def _call_openai(
        self,
        system_instruction: str,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> LLMResult:
        """Call OpenAI or OpenAI-compatible /chat/completions endpoint."""
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"

        messages = [{"role": "system", "content": system_instruction}]
        for turn in history or []:
            role = turn.get("role", "user")
            content = turn.get("content", "").strip()
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        req_data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            choices = data.get("choices", [])
            if not choices:
                return LLMResult(
                    content="",
                    success=False,
                    error="OpenAI returned no completion choices.",
                    model=self.model,
                    provider="openai",
                )

            answer = choices[0].get("message", {}).get("content", "").strip()
            usage = data.get("usage", {})

            return LLMResult(
                content=answer,
                success=True,
                model=self.model,
                provider="openai",
                usage=usage,
            )

        except urllib.error.HTTPError as http_err:
            try:
                body = http_err.read().decode("utf-8")
                err_json = json.loads(body)
                err_msg = err_json.get("error", {}).get("message", body)
            except Exception:
                err_msg = f"HTTP Error {http_err.code}: {http_err.reason}"

            if http_err.code in (401, 403):
                clean_err = f"Authentication error: Invalid or expired API key. Details: {err_msg}"
            elif http_err.code == 429:
                clean_err = "AI provider rate limit reached. Please wait a moment and try again."
            elif http_err.code in (500, 503):
                clean_err = "AI service is temporarily unavailable. Please retry shortly."
            else:
                clean_err = f"OpenAI API error ({http_err.code}): {err_msg}"

            logger.error(f"[CodeLens AI LLM] OpenAI HTTP error: {clean_err}")
            return LLMResult(
                content="",
                success=False,
                error=clean_err,
                model=self.model,
                provider="openai",
            )
        except urllib.error.URLError as url_err:
            return LLMResult(
                content="",
                success=False,
                error=f"Network error communicating with AI service: {str(url_err.reason)}",
                model=self.model,
                provider="openai",
            )
        except TimeoutError:
            return LLMResult(
                content="",
                success=False,
                error="The AI service request timed out. Please try again.",
                model=self.model,
                provider="openai",
            )

    def _call_ollama(
        self,
        system_instruction: str,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> LLMResult:
        """Call local Ollama /api/chat endpoint."""
        base = (self.base_url or "http://localhost:11434").rstrip("/")
        url = f"{base}/api/chat"

        messages = [{"role": "system", "content": system_instruction}]
        for turn in history or []:
            role = turn.get("role", "user")
            content = turn.get("content", "").strip()
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }

        req_data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            answer = data.get("message", {}).get("content", "").strip()
            return LLMResult(
                content=answer,
                success=True,
                model=self.model,
                provider="ollama",
            )
        except Exception as ex:
            return LLMResult(
                content="",
                success=False,
                error=f"Ollama local error: {str(ex)}",
                model=self.model,
                provider="ollama",
            )

    def _call_groq(
        self,
        system_instruction: str,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> LLMResult:
        """
        Call real Groq LLM backend using the official Groq SDK (with OpenAI-compatible REST fallback).
        """
        if not self.model or not self.model.strip():
            return LLMResult(
                content="",
                success=False,
                error="GROQ_MODEL is not configured in environment. Please set GROQ_MODEL in your .env file.",
                model="",
                provider="groq",
            )

        messages = [{"role": "system", "content": system_instruction}]
        for turn in history or []:
            role = turn.get("role", "user")
            if role in ("assistant", "model"):
                role = "assistant"
            else:
                role = "user"
            content = turn.get("content", "").strip()
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_prompt})

        # 1. Execute via official Groq Python SDK
        try:
            from groq import Groq

            client = Groq(api_key=self.api_key)
            completion = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout_seconds,
            )

            choices = completion.choices
            if not choices:
                return LLMResult(
                    content="",
                    success=False,
                    error="Groq returned no completion choices.",
                    model=self.model,
                    provider="groq",
                )

            answer = choices[0].message.content or ""
            usage = {}
            if hasattr(completion, "usage") and completion.usage:
                usage = {
                    "prompt_tokens": getattr(completion.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(completion.usage, "completion_tokens", 0),
                    "total_tokens": getattr(completion.usage, "total_tokens", 0),
                }

            return LLMResult(
                content=answer.strip(),
                success=True,
                model=self.model,
                provider="groq",
                usage=usage,
            )
        except ImportError:
            # Fallback to OpenAI-compatible REST endpoint if groq package is missing
            return self._call_groq_rest(messages)
        except Exception as ex:
            ex_str = str(ex).lower()
            if "authentication" in ex_str or "invalid_api_key" in ex_str or "401" in ex_str or "api key" in ex_str:
                clean_err = "Authentication error: Invalid or expired Groq API key."
            elif "rate_limit" in ex_str or "rate limit" in ex_str or "429" in ex_str:
                clean_err = "Groq provider rate limit reached. Please wait a moment and try again."
            elif "model" in ex_str and ("not found" in ex_str or "does not exist" in ex_str or "decommissioned" in ex_str):
                clean_err = f"Groq model '{self.model}' is not available or has been decommissioned. Please check GROQ_MODEL in your .env file."
            elif "connection" in ex_str or "timeout" in ex_str or "network" in ex_str:
                clean_err = "Unable to contact the AI service. Please check your network connection and try again."
            else:
                clean_err = f"Groq API error: {str(ex)}"

            logger.error(f"[CodeLens AI LLM] Groq error: {clean_err}")
            return LLMResult(
                content="",
                success=False,
                error=clean_err,
                model=self.model,
                provider="groq",
            )

    def _call_groq_rest(self, messages: List[Dict[str, str]]) -> LLMResult:
        """Fallback Groq REST call via OpenAI-compatible endpoint."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        req_data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if not choices:
                return LLMResult(
                    content="",
                    success=False,
                    error="Groq returned no completion choices.",
                    model=self.model,
                    provider="groq",
                )
            answer = choices[0].get("message", {}).get("content", "").strip()
            return LLMResult(
                content=answer,
                success=True,
                model=self.model,
                provider="groq",
                usage=data.get("usage", {}),
            )
        except Exception as ex:
            return LLMResult(
                content="",
                success=False,
                error=f"Groq REST call error: {str(ex)}",
                model=self.model,
                provider="groq",
            )

