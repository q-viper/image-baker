from importlib.metadata import PackageNotFoundError, version

from loguru import logger  # noqa

logger.info("imagebaker package loaded with loguru logger.")

try:
    __version__ = version("imagebaker")
except PackageNotFoundError:
    __version__ = "0.0.0"

# Export API for programmatic use
from imagebaker.api import (AnnotationType, ImageBaker, Layer,
                            create_annotation, load_model)

__all__ = [
    "logger",
    "__version__",
    "ImageBaker",
    "Layer",
    "create_annotation",
    "AnnotationType",
    "load_model",
]
