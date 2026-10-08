import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory: root of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / ".env")


class Config:
    """Base configuration class for CodeLens AI."""

    # Core Flask Configuration
    SECRET_KEY = os.getenv("SECRET_KEY", "codelens-ai-insecure-dev-secret-key-change-in-production")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "t", "yes")

    # Server Configuration
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", 5000))

    # Project Directories
    BASE_DIR = BASE_DIR
    DATA_DIR = BASE_DIR / "data"
    REPOSITORIES_DIR = DATA_DIR / "repositories"
    ANALYSIS_DIR = DATA_DIR / "analysis"
    GRAPHS_DIR = DATA_DIR / "graphs"
    REPORTS_DIR = DATA_DIR / "reports"

    # Integrations
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", None)

    # AI Chatbot & LLM Configuration (Repository Comprehension Assistant)
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL")
    LLM_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    LLM_MODEL = os.getenv("GROQ_MODEL") or os.getenv("LLM_MODEL")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq" if os.getenv("GROQ_API_KEY") else "auto")  # 'groq', 'auto', 'gemini', 'openai', 'ollama'
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", None)
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1200"))

    # Phase 4: Configurable Repository Suitability Ranking Weights
    # Total conceptual sum = 1.0 (normalized in calculation)
    SUITABILITY_WEIGHTS = {
        "keyword_relevance": float(os.getenv("WEIGHT_KEYWORD_RELEVANCE", "0.25")),
        "code_architecture": float(os.getenv("WEIGHT_CODE_ARCHITECTURE", "0.30")),
        "documentation": float(os.getenv("WEIGHT_DOCUMENTATION", "0.25")),
        "completeness_activity": float(os.getenv("WEIGHT_COMPLETENESS_ACTIVITY", "0.20")),
    }


class DevelopmentConfig(Config):
    """Development environment configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production environment configuration."""
    DEBUG = False


class TestingConfig(Config):
    """Testing environment configuration."""
    TESTING = True
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
