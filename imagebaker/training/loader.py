"""Dynamic loader for user-defined training scripts (`--trainers-file`)."""

from __future__ import annotations

import inspect
import runpy
import sys
from pathlib import Path

from imagebaker import logger
from imagebaker.training.augmentations import BUILTIN_AUGMENTATIONS, BaseAugmentation
from imagebaker.training.base_trainer import BaseTrainer


def load_trainers(
    trainers_file: str | Path | None,
) -> tuple[dict[str, BaseTrainer], dict[str, BaseAugmentation]]:
    """Load `LOADED_TRAINERS` and optional `LOADED_AUGMENTATIONS` from a Python file.

    Mirrors `load_models(models_file)` in `imagebaker.window.app`:
    - If `LOADED_TRAINERS` dict is defined, instantiates any `BaseTrainer` subclasses in it.
    - Otherwise, auto-discovers any concrete `BaseTrainer` subclasses defined in the module.
    - Merges any `LOADED_AUGMENTATIONS` dict with `BUILTIN_AUGMENTATIONS`.
    """
    trainers: dict[str, BaseTrainer] = {}
    augmentations: dict[str, BaseAugmentation] = dict(BUILTIN_AUGMENTATIONS)

    if not trainers_file:
        return trainers, augmentations

    file_path = Path(trainers_file).expanduser().resolve()
    if not file_path.is_file():
        logger.warning(f"Trainers file not found: {file_path}")
        return trainers, augmentations

    parent_dir = str(file_path.parent)
    added_to_path = False
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        added_to_path = True

    try:
        ns = runpy.run_path(str(file_path))
    except Exception as exc:
        logger.exception(f"Failed to load trainers from {file_path}: {exc}")
        return trainers, augmentations
    finally:
        if added_to_path and parent_dir in sys.path:
            try:
                sys.path.remove(parent_dir)
            except ValueError:
                pass

    raw_trainers = ns.get("LOADED_TRAINERS")
    if isinstance(raw_trainers, dict):
        for key, obj in raw_trainers.items():
            inst = _coerce_trainer(obj)
            if inst is not None:
                trainers[str(key)] = inst
    else:
        for obj in ns.values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseTrainer)
                and obj is not BaseTrainer
                and not inspect.isabstract(obj)
            ):
                inst = _coerce_trainer(obj)
                if inst is not None:
                    trainers[inst.name] = inst

    raw_augs = ns.get("LOADED_AUGMENTATIONS")
    if isinstance(raw_augs, dict):
        for key, obj in raw_augs.items():
            if isinstance(obj, BaseAugmentation):
                augmentations[str(key)] = obj
            elif inspect.isclass(obj) and issubclass(obj, BaseAugmentation):
                try:
                    augmentations[str(key)] = obj()
                except Exception as exc:
                    logger.warning(f"Could not instantiate augmentation {key}: {exc}")

    logger.info(f"Loaded trainers from {file_path.name}: {list(trainers.keys())}")
    return trainers, augmentations


def _coerce_trainer(obj) -> BaseTrainer | None:
    if isinstance(obj, BaseTrainer):
        return obj
    if inspect.isclass(obj) and issubclass(obj, BaseTrainer) and not inspect.isabstract(obj):
        try:
            return obj()
        except Exception as exc:
            logger.warning(f"Could not instantiate trainer {obj.__name__}: {exc}")
    return None
