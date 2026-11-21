# Visual Model Training & Pipeline Guide

ImageBaker includes an integrated **Train** tab in the Web studio (`imagebaker web`) that closes the active-learning loop:

> **Annotate (`Layerify`) → Synthesize (`Baker`) → Train (`Train`) → Load Checkpoint back into `Layerify` (`M` + `P`)**

---

## 1. Launching with Custom Trainers (`--trainers-file`)

Just like `--models-file` loads `LOADED_MODELS` for inference, `--trainers-file` loads your own Python training backends (`LOADED_TRAINERS`) and optional custom augmentations (`LOADED_AUGMENTATIONS`):

```bash
imagebaker web \
  --models-file examples/loaded_models.py \
  --trainers-file examples/loaded_trainers.py \
  --project-dir .
```

If a `loaded_trainers.py` file exists in `--project-dir`, ImageBaker loads it automatically even without passing `--trainers-file`.

---

## 2. Writing a Custom Backend Trainer

Subclass `BaseTrainer` and define a Pydantic `BaseTrainingConfig` for your hyperparameters. The **Node Inspector** in the Web UI automatically generates form controls from your config's JSON schema.

```python
from pathlib import Path
from typing import Any
from pydantic import Field

from imagebaker.training import (
    BaseTrainer,
    BaseTrainingConfig,
    TrainingProgress,
    TrainingRegime,
)


class MyTrainerConfig(BaseTrainingConfig):
    variant: str = Field(default="rfdetr-small", description="Model backbone/variant.")
    grad_accum_steps: int = Field(default=4, ge=1, le=64)


class MyCustomTrainer(BaseTrainer):
    name = "My-RF-DETR-Trainer"
    description = "Trains my custom detector with finetune, full, or few-shot regimes."
    supported_regimes = [
        TrainingRegime.FINETUNE.value,
        TrainingRegime.FULL.value,
        TrainingRegime.FEW_SHOT.value,
    ]
    config_class = MyTrainerConfig

    def train(self, dataset_dir, work_dir, config, augmentations, progress_cb, stop_check):
        for epoch in range(1, config.epochs + 1):
            if stop_check():
                break
            # ... run your training loop ...
            progress_cb(
                TrainingProgress(
                    epoch=epoch,
                    total_epochs=config.epochs,
                    status="running",
                    message=f"Epoch {epoch}/{config.epochs}",
                    metrics={"loss": 0.42, "map50": 0.81},
                )
            )
        ckpt = work_dir / "best.pth"
        return {"last_epoch": config.epochs, "checkpoint_path": str(ckpt), "metrics": {"map50": 0.81}}

    def build_inference_model(self, checkpoint_path: Path):
        # Optional: return a BaseModel instance to enable one-click "Load in Layerify"
        return None


LOADED_TRAINERS = {
    "My-RF-DETR-Trainer": MyCustomTrainer(),
}
```

### Built-in `BaseTrainingConfig` Hyperparameters
Every trainer inherits rich optimization and regularization controls out of the box:
- **Regime**: `training_mode` (`finetune`, `full`, `few_shot`, `custom`) + `shots_per_class`
- **Optimizer & Scheduler**: `optimizer` (`adamw`, `adam`, `sgd`), `scheduler` (`cosine`, `onecycle`, `step`, `none`), `learning_rate`, `backbone_lr` (differential backbone LR), `weight_decay`
- **Staged Training & Regularization**: `freeze_backbone`, `unfreeze_epoch`, `use_ema` (ModelEMA), `weighted_loss`, `mixed_precision` (AMP), `early_stopping_patience`
- **Checkpointing**: `pretrained_weights`, `resume_from`, `device`, `seed`, `export_format` (`coco`, `yolo`, `default`)

---

## 3. Visual Pipeline Editor (ReactFlow-Style Canvas)

The **Train** tab provides a pan/zoom dot-grid node graph where you wire your training pipeline visually:

1. **Multiple Data Source Nodes**:
   - Add **🖼️ Layerify Local Source** (real annotated images) and/or **🧁 Baker Synthetic Source** (synthesized via `CacheDatasetGenerator`), and connect both into **Split & Filter**.
2. **Split & Filter Node**:
   - Configure `train / val / test` ratios, **Keep Validation Real-Only**, **Selected Labels** (multi-select chips), and **Annotation Types** (`rectangle`, `polygon`, `brush`, `point`).
3. **Augmentation Nodes**:
   - Chain built-in augmentations (`HorizontalFlip`, `VerticalFlip`, `RandomRotate`, `ColorJitter`, `GaussianBlur`, `Mosaic`, `RandomCrop`) or custom `BaseAugmentation` classes from `LOADED_AUGMENTATIONS`.
4. **Trainer Node**:
   - Choose your backend trainer, training regime (`FINETUNE`, `FULL`, `FEW_SHOT`), and tune hyperparameters in the right-hand **Node Inspector**.
5. **Checkpoint & Layerify Node**:
   - Runs execute in an isolated subprocess under `.imagebaker/runs/<run_id>/` with live progress bar, loss/mAP50 chart, and logs. Click **🔮 Load in Layerify** on any completed run to immediately register its checkpoint into Layerify's model dropdown.

### Live Hover Simulation Preview
Hovering over any **Data Source**, **Split & Filter**, **Augmentation**, or **Trainer** block opens a live floating preview card showing a simulated image with the active label/type filters and all upstream augmentations applied—before you start training.

### Persistent Training Cache (`train_cache.json`)
Just like Layerify (`labels.json` + per-image annotation cache) and Baker (`baker_cache.json`), the **Train** tab automatically persists its state in `.imagebaker/cache/train_cache.json`:
- Every node edit, edge connection, or hyperparameter change is auto-cached and restored on startup.
- Any trained checkpoint you load via **🔮 Load in Layerify** is recorded in `train_cache.json` and automatically re-registered into Layerify's model dropdown when ImageBaker restarts.
- You can also export or load pipeline configs directly as JSON files (**⬇ Export JSON** / **📂 Load JSON**) or reset to the default graph (**↺ Reset**).

