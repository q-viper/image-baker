"""
ImageBaker Web Package

Standalone web application backend and UI for cross-platform ImageBaker usage.
"""

from .engine import WebAppEngine
from .server import run_web_server

__all__ = ["WebAppEngine", "run_web_server"]
