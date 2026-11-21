"""ImageBaker Training package: user-defined trainers, augmentations, and pipeline runner."""

from imagebaker.training.augmentations import (
    BUILTIN_AUGMENTATIONS,
    BaseAugmentation,
    BaseAugmentationConfig,
)
from imagebaker.training.base_trainer import (
    BaseTrainer,
    BaseTrainingConfig,
    TrainingProgress,
    TrainingRegime,
)
from imagebaker.training.loader import load_trainers
from imagebaker.training.runner import (
    TrainingRunManager,
    default_pipeline_graph,
    validate_and_compile_pipeline,
)

__all__ = [
    "BUILTIN_AUGMENTATIONS",
    "BaseAugmentation",
    "BaseAugmentationConfig",
    "BaseTrainer",
    "BaseTrainingConfig",
    "TrainingProgress",
    "TrainingRegime",
    "TrainingRunManager",
    "default_pipeline_graph",
    "load_trainers",
    "validate_and_compile_pipeline",
]
