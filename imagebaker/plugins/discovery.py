from __future__ import annotations

import importlib
import importlib.util
import inspect
from pathlib import Path

from imagebaker import logger
from imagebaker.plugins.base_plugin import BasePlugin


def _discover_from_module(module, discovered: dict[str, type[BasePlugin]]):
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, BasePlugin) or obj is BasePlugin:
            continue
        plugin_name = getattr(obj, "plugin_name", obj.__name__)
        if plugin_name in discovered:
            logger.warning(
                f"Duplicate plugin name '{plugin_name}' found; keeping first definition."
            )
            continue
        discovered[plugin_name] = obj


def _load_module_from_path(py_file: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(py_file))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_plugin_classes(project_root: Path | None = None) -> dict[str, type[BasePlugin]]:
    """
    Discover plugin classes from built-ins and project-root plugin files.
    """
    discovered: dict[str, type[BasePlugin]] = {}
    root = Path(project_root or Path.cwd())

    # Built-in package plugins.
    try:
        builtins_pkg = importlib.import_module("imagebaker.plugins")
        _discover_from_module(builtins_pkg, discovered)
    except Exception as error:
        logger.error(f"Failed to load built-in plugins: {error}")

    candidate_dirs = [root / "plugins"]
    excluded_dirs = {".git", "__pycache__", ".imagebaker", ".venv", "venv"}

    for plugin_dir in candidate_dirs:
        if not plugin_dir.exists() or not plugin_dir.is_dir():
            continue
        for py_file in plugin_dir.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            if py_file.stem in {"base_plugin", "discovery", "runtime"}:
                continue
            if any(part in excluded_dirs for part in py_file.parts):
                continue

            module_name = f"user_plugin_{abs(hash(str(py_file.resolve())))}"
            try:
                module = _load_module_from_path(py_file, module_name)
                if module is not None:
                    _discover_from_module(module, discovered)
            except Exception as error:
                logger.error(f"Failed to load plugin from {py_file}: {error}")

    # Also discover root-level plugin-like files.
    for py_file in root.glob("*plugin*.py"):
        if py_file.stem in {"base_plugin", "discovery", "runtime"}:
            continue
        module_name = f"user_plugin_{abs(hash(str(py_file.resolve())))}"
        try:
            module = _load_module_from_path(py_file, module_name)
            if module is not None:
                _discover_from_module(module, discovered)
        except Exception as error:
            logger.error(f"Failed to load plugin from {py_file}: {error}")

    return discovered
