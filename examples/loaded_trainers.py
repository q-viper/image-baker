"""Example user-defined trainers script for ImageBaker (`--trainers-file`).

Pass this file when launching ImageBaker Web:
    imagebaker web --models-file examples/loaded_models.py --trainers-file examples/loaded_trainers.py

Define any `BaseTrainer` subclasses and expose them in `LOADED_TRAINERS`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from imagebaker.core.configs import DefaultModelConfig
from imagebaker.core.defs import ModelType, PredictionResult
from imagebaker.models.base_model import BaseDetectionModel
from imagebaker.training import (
    BaseTrainer,
    BaseTrainingConfig,
    TrainingProgress,
    TrainingRegime,
)


class _TrainedDummyModel(BaseDetectionModel):
    """Lightweight inference model returned after DummyTrainer finishes."""

    def __init__(self, checkpoint_path: Path):
        cfg = DefaultModelConfig(
            model_type=ModelType.DETECTION,
            model_name=f"Trained({checkpoint_path.stem})",
        )
        self.checkpoint_path = checkpoint_path
        super().__init__(cfg)

    def predict_boxes(self, image) -> list[PredictionResult]:
        h, w = image.shape[:2]
        return [
            PredictionResult(
                class_name="trained_obj",
                class_id=0,
                score=0.92,
                rectangle=[int(w * 0.2), int(h * 0.2), int(w * 0.4), int(h * 0.4)],
            )
        ]


class DummyTrainerConfig(BaseTrainingConfig):
    step_delay_sec: float = Field(
        default=0.15,
        ge=0.0,
        le=5.0,
        description="Simulated delay per epoch (seconds).",
    )


class DummyTrainer(BaseTrainer):
    """Fast zero-GPU trainer for testing ImageBaker pipelines, regimes, and live metrics."""

    name = "DummyTrainer"
    description = "Simulated trainer supporting finetune, full, and few-shot regimes."
    supported_regimes = [
        TrainingRegime.FINETUNE.value,
        TrainingRegime.FULL.value,
        TrainingRegime.FEW_SHOT.value,
    ]
    config_class = DummyTrainerConfig

    def train(
        self,
        dataset_dir: Path,
        work_dir: Path,
        config: DummyTrainerConfig,
        augmentations: list[dict[str, Any]],
        progress_cb: Callable[[TrainingProgress], None],
        stop_check: Callable[[], bool],
    ) -> dict[str, Any]:
        ckpt_path = work_dir / "best_dummy.json"
        last_epoch = 0
        final_metrics: dict[str, float] = {}

        for epoch in range(1, config.epochs + 1):
            if stop_check():
                return {
                    "last_epoch": last_epoch,
                    "checkpoint_path": str(ckpt_path) if ckpt_path.exists() else None,
                    "metrics": final_metrics,
                    "message": f"Stopped at epoch {last_epoch}.",
                }
            if config.step_delay_sec > 0:
                time.sleep(config.step_delay_sec)

            frac = epoch / max(1, config.epochs)
            loss = round(max(0.05, 1.2 * (1.0 - 0.75 * frac)), 4)
            map50 = round(min(0.98, 0.35 + 0.55 * frac), 4)
            final_metrics = {"loss": loss, "val_loss": round(loss * 1.08, 4), "map50": map50}
            last_epoch = epoch

            progress_cb(
                TrainingProgress(
                    epoch=epoch,
                    total_epochs=config.epochs,
                    step=epoch,
                    status="running",
                    message=(
                        f"[{config.training_mode}] Epoch {epoch}/{config.epochs} "
                        f"loss={loss:.4f} mAP50={map50:.4f}"
                    ),
                    metrics=final_metrics,
                )
            )

        ckpt_payload = {
            "trainer": self.name,
            "training_mode": config.training_mode,
            "epochs": config.epochs,
            "augmentations": augmentations,
            "dataset_dir": str(dataset_dir),
            "metrics": final_metrics,
        }
        ckpt_path.write_text(json.dumps(ckpt_payload, indent=2), encoding="utf-8")
        return {
            "last_epoch": last_epoch,
            "checkpoint_path": str(ckpt_path),
            "metrics": final_metrics,
            "message": f"DummyTrainer ({config.training_mode}) completed.",
        }

    def build_inference_model(self, checkpoint_path: Path):
        return _TrainedDummyModel(checkpoint_path)


class RFDetrDetectionTrainerConfig(BaseTrainingConfig):
    """Hyperparameter schema for RF-DETR Object Detection training."""

    variant: str = Field(
        default="rfdetr-small",
        description="RF-DETR detection variant: rfdetr-nano, rfdetr-small, rfdetr-medium, rfdetr-large, rfdetr-base.",
    )
    export_format: str = Field(default="coco", description="COCO dataset format for RF-DETR.")
    epochs: int = Field(default=30, ge=1, le=500, description="Total training epochs.")
    batch_size: int = Field(default=4, ge=1, le=64, description="Per-device batch size.")
    grad_accum_steps: int = Field(
        default=4, ge=1, le=64, description="Gradient accumulation steps for larger effective batch."
    )
    learning_rate: float = Field(default=1e-4, gt=0.0, description="Decoder / head learning rate.")
    lr_encoder: float = Field(default=1.5e-4, gt=0.0, description="Backbone encoder learning rate.")
    multi_scale: bool = Field(default=False, description="Enable multi-scale training.")
    gradient_checkpointing: bool = Field(
        default=False, description="Enable gradient checkpointing to reduce GPU VRAM usage."
    )


class RFDetrSegmentationTrainerConfig(BaseTrainingConfig):
    """Hyperparameter schema for RF-DETR Instance Segmentation training."""

    variant: str = Field(
        default="rfdetr-seg-small",
        description="RF-DETR seg variant: rfdetr-seg-nano, rfdetr-seg-small, rfdetr-seg-medium, rfdetr-seg-large.",
    )
    export_format: str = Field(default="coco", description="COCO dataset format for RF-DETR.")
    epochs: int = Field(default=30, ge=1, le=500, description="Total training epochs.")
    batch_size: int = Field(default=4, ge=1, le=64, description="Per-device batch size.")
    grad_accum_steps: int = Field(
        default=4, ge=1, le=64, description="Gradient accumulation steps for larger effective batch."
    )
    learning_rate: float = Field(default=1e-4, gt=0.0, description="Decoder / mask-head learning rate.")
    lr_encoder: float = Field(default=1.5e-4, gt=0.0, description="Backbone encoder learning rate.")
    multi_scale: bool = Field(default=False, description="Enable multi-scale training.")
    gradient_checkpointing: bool = Field(
        default=False, description="Enable gradient checkpointing to reduce GPU VRAM usage."
    )


def _instantiate_rfdetr_model(variant: str, pretrained_weights: str = ""):
    """Instantiate an open-source RF-DETR detection or segmentation model class by variant name."""
    import rfdetr

    # Map human-readable variant names from the UI inspector to rfdetr Python classes
    cls_map = {
        "rfdetr-nano": "RFDETRNano",
        "rfdetr-small": "RFDETRSmall",
        "rfdetr-medium": "RFDETRMedium",
        "rfdetr-large": "RFDETRLarge",
        "rfdetr-base": "RFDETRBase",
        "rfdetr-seg-nano": "RFDETRSegNano",
        "rfdetr-seg-small": "RFDETRSegSmall",
        "rfdetr-seg-medium": "RFDETRSegMedium",
        "rfdetr-seg-large": "RFDETRSegLarge",
        "rfdetr-seg-preview": "RFDETRSegPreview",
    }
    cls_name = cls_map.get(variant.lower(), "RFDETRSmall")
    model_cls = getattr(rfdetr, cls_name, None) or getattr(rfdetr, "RFDETRBase", None)
    if model_cls is None:
        raise ImportError(f"RF-DETR class '{cls_name}' not found in installed rfdetr package.")
    kwargs = {"pretrain_weights": pretrained_weights} if pretrained_weights else {}
    return model_cls(**kwargs)


def _run_rfdetr_train(
    dataset_dir: Path,
    work_dir: Path,
    config: RFDetrDetectionTrainerConfig | RFDetrSegmentationTrainerConfig,
    progress_cb: Callable[[TrainingProgress], None],
    label: str,
) -> dict[str, Any]:
    """Shared RF-DETR training runner handling regime-aware LR scaling and checkpoint discovery."""
    model = _instantiate_rfdetr_model(config.variant, config.pretrained_weights)

    # For finetune / few-shot regimes with backbone freezing enabled, damp the encoder LR
    lr_enc = config.lr_encoder
    if config.training_mode in (TrainingRegime.FINETUNE.value, TrainingRegime.FEW_SHOT.value):
        if config.freeze_backbone:
            lr_enc = min(lr_enc, config.learning_rate * 0.25)

    out_dir = work_dir / "rfdetr_run"
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_cb(
        TrainingProgress(
            epoch=0,
            total_epochs=config.epochs,
            status="running",
            message=f"Starting {label} ({config.variant}, {config.training_mode})...",
        )
    )
    train_kwargs: dict[str, Any] = {
        "dataset_dir": str(dataset_dir),
        "epochs": config.epochs,
        "batch_size": config.batch_size,
        "grad_accum_steps": config.grad_accum_steps,
        "lr": config.learning_rate,
        "lr_encoder": lr_enc,
        "weight_decay": config.weight_decay,
        "use_ema": config.use_ema,
        "early_stopping": config.early_stopping_patience > 0,
        "early_stopping_patience": max(1, config.early_stopping_patience),
        "multi_scale": config.multi_scale,
        "gradient_checkpointing": config.gradient_checkpointing,
        "output_dir": str(out_dir),
    }
    if config.resume_from:
        train_kwargs["resume"] = str(config.resume_from)
    if config.device and config.device != "auto":
        train_kwargs["device"] = config.device

    model.train(**train_kwargs)

    # Locate the best exported RF-DETR checkpoint inside the run directory
    ckpts = sorted(out_dir.rglob("checkpoint_best_total.pth"))
    ckpt = ckpts[-1] if ckpts else None
    return {
        "last_epoch": config.epochs,
        "checkpoint_path": str(ckpt) if ckpt else None,
        "metrics": {},
        "message": f"{label} finished.",
    }


class RFDetrDetectionTrainer(BaseTrainer):
    """RF-DETR Object Detection trainer supporting full, finetune, and few-shot regimes."""

    name = "RF-DETR-Detection-Trainer"
    description = "Train RF-DETR object detection models on COCO datasets."
    supported_regimes = [
        TrainingRegime.FINETUNE.value,
        TrainingRegime.FULL.value,
        TrainingRegime.FEW_SHOT.value,
    ]
    config_class = RFDetrDetectionTrainerConfig

    def train(
        self,
        dataset_dir: Path,
        work_dir: Path,
        config: RFDetrDetectionTrainerConfig,
        augmentations: list[dict[str, Any]],
        progress_cb: Callable[[TrainingProgress], None],
        stop_check: Callable[[], bool],
    ) -> dict[str, Any]:
        return _run_rfdetr_train(
            dataset_dir=dataset_dir,
            work_dir=work_dir,
            config=config,
            progress_cb=progress_cb,
            label=self.name,
        )


class RFDetrSegmentationTrainer(BaseTrainer):
    """RF-DETR Instance Segmentation trainer supporting full, finetune, and few-shot regimes."""

    name = "RF-DETR-Segmentation-Trainer"
    description = "Train RF-DETR instance segmentation models on COCO polygon/mask datasets."
    supported_regimes = [
        TrainingRegime.FINETUNE.value,
        TrainingRegime.FULL.value,
        TrainingRegime.FEW_SHOT.value,
    ]
    config_class = RFDetrSegmentationTrainerConfig

    def train(
        self,
        dataset_dir: Path,
        work_dir: Path,
        config: RFDetrSegmentationTrainerConfig,
        augmentations: list[dict[str, Any]],
        progress_cb: Callable[[TrainingProgress], None],
        stop_check: Callable[[], bool],
    ) -> dict[str, Any]:
        return _run_rfdetr_train(
            dataset_dir=dataset_dir,
            work_dir=work_dir,
            config=config,
            progress_cb=progress_cb,
            label=self.name,
        )


LOADED_TRAINERS = {
    "RF-DETR-Detection-Trainer": RFDetrDetectionTrainer(),
    "RF-DETR-Segmentation-Trainer": RFDetrSegmentationTrainer(),
    "DummyTrainer": DummyTrainer(),
}
