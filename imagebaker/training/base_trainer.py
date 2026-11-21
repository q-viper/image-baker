"""Base trainer abstractions, training regimes, and structured progress events."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrainingRegime(str, Enum):
    """Supported high-level model training regimes."""

    FINETUNE = "finetune"
    FULL = "full"
    FEW_SHOT = "few_shot"
    CUSTOM = "custom"


class BaseTrainingConfig(BaseModel):
    """Base Pydantic configuration schema for all ImageBaker trainers.

    Subclasses can add framework-specific hyperparameters; the Web UI
    auto-generates node inspector controls from `model_json_schema()`.
    """

    model_config = ConfigDict(extra="allow")

    training_mode: str = Field(
        default=TrainingRegime.FINETUNE.value,
        description="Training regime: finetune, full, few_shot, or custom.",
    )
    epochs: int = Field(default=10, ge=1, le=10000, description="Number of training epochs.")
    batch_size: int = Field(default=8, ge=1, le=512, description="Mini-batch size.")
    img_size: int = Field(default=640, ge=32, le=4096, description="Input image size (px).")
    learning_rate: float = Field(default=1e-3, gt=0.0, description="Initial head/base learning rate.")
    backbone_lr: float = Field(
        default=1e-4,
        ge=0.0,
        description="Differential learning rate for backbone layers (0 = same as learning_rate).",
    )
    optimizer: str = Field(
        default="adamw",
        description="Optimizer: adamw, adam, or sgd.",
    )
    scheduler: str = Field(
        default="cosine",
        description="LR scheduler: cosine, onecycle, step, or none.",
    )
    weight_decay: float = Field(default=1e-4, ge=0.0, description="Weight decay.")
    device: str = Field(default="auto", description="Device: auto, cpu, cuda:0, mps.")
    pretrained_weights: str = Field(
        default="",
        description="Optional path or hub identifier for pretrained weights.",
    )
    resume_from: str = Field(
        default="",
        description="Optional checkpoint path to resume training from.",
    )
    freeze_backbone: bool = Field(
        default=True,
        description="Freeze backbone layers during finetuning / few-shot training.",
    )
    unfreeze_epoch: int = Field(
        default=0,
        ge=0,
        le=1000,
        description="Epoch at which to unfreeze backbone for staged training (0 = keep setting).",
    )
    use_ema: bool = Field(default=True, description="Enable Exponential Moving Average (ModelEMA).")
    weighted_loss: bool = Field(
        default=False,
        description="Use inverse-frequency class weights for imbalanced datasets.",
    )
    mixed_precision: bool = Field(default=True, description="Enable AMP mixed precision on GPU.")
    early_stopping_patience: int = Field(
        default=10,
        ge=0,
        le=500,
        description="Stop after N epochs without val improvement (0 = disabled).",
    )
    shots_per_class: int = Field(
        default=5,
        ge=1,
        le=1000,
        description="Max examples per class when training_mode == 'few_shot'.",
    )
    export_format: str = Field(
        default="yolo",
        description="Prepared dataset format: yolo, coco, or default.",
    )
    seed: int = Field(default=42, description="Random seed for reproducibility.")


class TrainingProgress(BaseModel):
    """Structured progress event emitted during a training run."""

    epoch: int = 0
    total_epochs: int = 0
    step: int = 0
    status: str = "running"  # queued | preparing | running | completed | failed | stopped
    message: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    checkpoint_path: str | None = None
    timestamp: float | None = None


class BaseTrainer(ABC):
    """Abstract base class for user-defined or built-in model trainers.

    Users can subclass `BaseTrainer` in a `--trainers-file` (e.g. `loaded_trainers.py`)
    and expose instances or classes in `LOADED_TRAINERS = {"MyTrainer": MyTrainer()}`.
    """

    name: str = "BaseTrainer"
    description: str = "Custom model trainer"
    supported_regimes: list[str] = [
        TrainingRegime.FINETUNE.value,
        TrainingRegime.FULL.value,
        TrainingRegime.FEW_SHOT.value,
    ]
    config_class: type[BaseTrainingConfig] = BaseTrainingConfig

    def get_schema(self) -> dict[str, Any]:
        """Return JSON schema & metadata for the Web Train tab inspector."""
        schema = self.config_class.model_json_schema()
        defaults = self.config_class().model_dump()
        return {
            "name": self.name,
            "description": self.description,
            "supported_regimes": list(self.supported_regimes),
            "defaults": defaults,
            "schema": schema,
        }

    @abstractmethod
    def train(
        self,
        dataset_dir: Path,
        work_dir: Path,
        config: BaseTrainingConfig,
        augmentations: list[dict[str, Any]],
        progress_cb: Callable[[TrainingProgress], None],
        stop_check: Callable[[], bool],
    ) -> dict[str, Any]:
        """Execute training and return a result summary dict (e.g. checkpoint_path, metrics)."""

    def build_inference_model(self, checkpoint_path: Path):
        """Optionally return a `BaseModel` instance from a trained checkpoint for Layerify."""
        return None
