"""
ImageBaker Web Package

Standalone web application backend and UI for cross-platform ImageBaker usage.
"""

from .engine import WebAppEngine
from .models import (
    ImageUndoHistory,
    WebCanvasItem,
    WebImageEntry,
    WebLayerItem,
)
from .server import run_web_server

__all__ = [
    "ImageUndoHistory",
    "WebAppEngine",
    "WebCanvasItem",
    "WebImageEntry",
    "WebLayerItem",
    "run_web_server",
]
