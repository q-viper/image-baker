from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
import logging

try:
    from loguru import logger  # type: ignore[import-not-found]
except ImportError:
    logger = logging.getLogger("imagebaker")

try:
    __version__ = version("imagebaker")
except PackageNotFoundError:
    __version__ = "0.0.0"

_LAZY_EXPORTS = {
    "AnnotationType": ("imagebaker.api", "AnnotationType"),
    "ImageBaker": ("imagebaker.api", "ImageBaker"),
    "Layer": ("imagebaker.api", "Layer"),
    "create_annotation": ("imagebaker.api", "create_annotation"),
    "load_model": ("imagebaker.api", "load_model"),
}

__all__ = ["logger", "__version__", *_LAZY_EXPORTS]


def __getattr__(name):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'imagebaker' has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
