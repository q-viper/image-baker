"""
ImageBaker API Module

This module provides programmatic access to ImageBaker's core functionality
for use as a Python library.
"""

from .annotation import AnnotationType, create_annotation
from .baker import ImageBaker
from .layer import Layer
from .models import load_model

__all__ = [
    "ImageBaker",
    "Layer",
    "create_annotation",
    "AnnotationType",
    "load_model",
]
