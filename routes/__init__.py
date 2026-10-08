"""
Routes Module for CodeLens AI.
"""

from .main_routes import main_bp
from .repository_routes import repository_bp
from .chat_routes import chat_bp

__all__ = ["main_bp", "repository_bp", "chat_bp"]
