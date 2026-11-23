# Visual Model Training, Evaluation & Comparison Guide

ImageBaker's Web Studio (`imagebaker web`) closes the full computer-vision active-learning loop inside one cross-platform interface:

> **Annotate (`Layerify`) → Synthesize & Preview (`Baker`) → Train & Evaluate (`Train`) → Compare Models (`Compare`) → Load Checkpoint back into `Layerify` (`M` + `P`)**

---

## 1. Launching with Custom Models & Trainers

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
        # Optional: return a BaseModel instance to enable one-click "Load" & post-training Eval & Visualize
        return None


LOADED_TRAINERS = {
    "My-RF-DETR-Trainer": MyCustomTrainer(),
}
```

### Built-in `BaseTrainingConfig` Hyperparameters
Every trainer inherits optimization and regularization controls out of the box:
- **Regime**: `training_mode` (`finetune`, `full`, `few_shot`, `custom`) + `shots_per_class`
- **Optimizer & Scheduler**: `optimizer` (`adamw`, `adam`, `sgd`), `scheduler` (`cosine`, `onecycle`, `step`, `none`), `learning_rate`, `backbone_lr` (differential backbone LR), `weight_decay`
- **Staged Training & Regularization**: `freeze_backbone`, `unfreeze_epoch`, `use_ema` (ModelEMA), `weighted_loss`, `mixed_precision` (AMP), `early_stopping_patience`
- **Checkpointing**: `pretrained_weights`, `resume_from`, `device`, `seed`, `export_format` (`coco`, `yolo`, `default`)

---

## 3. Visual Pipeline Editor (Train Tab)

The **Train** tab provides a pan/zoom dot-grid node graph with directional arrows where you wire your training pipeline visually:

1. **Data Source Nodes (`Layerify Data` & `Baker States`)**:
   - **🖼️ Layerify Data Source**: Uses real annotated images from the Layerify tab and displays exact live counts (`<M> imgs (<K> ann)`).
   - **🧁 Baker States Source**: Uses **only your actual saved Baker timeline states** rendered through the exact Baker compositor and z-order occlusion (never synthetic noise), displaying exact live counts (`<N> available`).
   - **Optional ROI Cropping by Label Names**: Configure **ROI Crop Labels** (empty by default = full image) and **ROI Crop Padding (px)** on any Data Source node. When set, ImageBaker crops each matching ROI region (rectangle, polygon, or mask) and translates/clips all target annotations into the cropped ROI coordinates before staging the dataset.
   - **Export Format**: `COCO` (`train/`, `valid/`, `test/` with 1-based `_annotations.coco.json`), `YOLO` (`data.yaml`), or `Default` JSON.
2. **Split & Filter Node**:
   - Configure `train / val / test` ratios, **Keep Validation Real-Only**, **Selected Labels** (multi-select chips), and **Annotation Types** (`rectangle`, `polygon`, `brush`, `point`).
3. **Augmentation Nodes**:
   - Chain built-in augmentations (`HorizontalFlip`, `VerticalFlip`, `RandomRotate`, `ColorJitter`, `GaussianBlur`, `Mosaic`, `RandomCrop`) or custom `BaseAugmentation` classes from `LOADED_AUGMENTATIONS`.
4. **Trainer Node**:
   - Choose your backend trainer, training regime (`FINETUNE`, `FULL`, `FEW_SHOT`), and tune hyperparameters in the right-hand **Node Inspector**.
5. **Checkpoint & Layerify Node**:
   - Runs execute in an isolated unbuffered subprocess under `.imagebaker/runs/<run_name>/` with logs teed live to both `train.log` and the backend console.
6. **Eval & Visualize Node (`📊 Eval & Visualize`)**:
   - Automatically runs the trained checkpoint on the configured `val` / `test` split after training completes, overlaying ground-truth boxes (green) and predicted boxes/polygons/scores (orange/cyan).
   - Click any eval thumbnail in the bottom gallery to open the **in-app popup lightbox** (click outside or press `Esc` to close, `←` / `→` to step, or **⚖️ Compare** to jump to the Compare tab).
   - You can also trigger evaluation on demand anytime via **📊 Visualize Val/Test**.

### Header-Hover Simulation Preview
Hovering over the **header** of any image-outputting block (`Data Source`, `Augmentation`, or `Eval & Visualize`) opens a live floating preview card showing a real/baked sample with active filters and upstream augmentations applied—or the latest post-training eval visualization.

### Run Naming, Live Charts, Scrollable Logs & Interactive Run History
- **Auto-Generated Run Name**: Above the progress bar and charts, the **Run Name** field automatically updates from your selected data source, model/variant, regime, epochs, and labels (e.g., `baker_rfdetr-small_finetune_ep5_insect`), and can be edited manually or regenerated via **↻ Auto**.
- **Live Metric Charts & Auto-Trimmed Logs**: Plots `Loss` (orange) and `mAP50` (emerald) in real time during training; the scrollable log viewer preserves your scroll position, supports **Max lines** auto-trimming (`150`–`1000`), and includes a **🧹 Clear Logs** button (without deleting `train.log` on disk).
- **Interactive Training Runs Pane**: Click any run card to inspect its metrics, logs, and eval gallery, or use its quick actions:
  - **📥 Pipeline**: Restore that run's saved `pipeline.json` back onto the canvas.
  - **⚖️ Compare**: Open that run's eval outputs in the **Compare** tab.
  - **🔮 Load**: Hot-load the run's checkpoint into Layerify.
  - **🗑️**: Delete finished/stopped/failed runs from disk.

### Persistent Training Cache (`train_cache.json`)
Just like Layerify and Baker, the **Train** tab automatically persists its pipeline and loaded checkpoints in `.imagebaker/cache/train_cache.json`, and also supports **⬇ Export JSON**, **📂 Load JSON**, and **↺ Reset**.

---

## 4. Model & Image Comparison (`Compare` Tab)

Adapted from [@Crazz-Zaac](https://github.com/Crazz-Zaac)'s original image comparison tool, the **Compare** tab lets you inspect differences between two or more trained models' predictions, raw Layerify images, or locally uploaded images:

- **1–4 Independent Panes**: Pick a different training run, Layerify set, or local upload in each pane, or drag-and-drop images directly onto any pane. Use **Match names across panes** to step through validation images across models simultaneously.
- **Relative Synchronized Zoom & Pan**: Zoom (`Wheel`) and pan (`Drag` or `Ctrl + Drag` in any mode, including Swipe) operate in normalized image coordinates so images of different resolutions stay aligned.
- **Comparison Modes**: `Side by side`, `Swipe 1 | 2` (draggable curtain), `Blend 1 + 2`, `Blink 1 / 2`, `Difference` (amplified), and `Difference map` (magenta pixel-difference highlight with threshold slider and `% pixels differ` stat).
- **Synchronized Annotations & Pixel Inspector**: Draw `Box`, `Ellipse`, `Arrow`, `Freehand`, `Text`, `Marker`, or `Erase` with live mirrored preview across all panes (**On all panes**), `Ctrl+Z` undo, synchronized RGB/ΔRGB **Crosshair**, **Save Annotated (PNG)**, and **Export View (PNG)**.

---

## 5. Baker Playback & Interactive `Predict State` Popup

In the **Baker** tab:
- **Smooth Single-Pass Playback**: Set **Add Steps** (automatically resets to `1` after saving) to interpolate smooth transforms (including shortest-path rotation) from the last saved state. Clicking **▶ Play States** plays smoothly at 60 FPS with a clean layers-only view (hiding boxes, handles, gridlines, and text overlays) and automatically pauses after one full pass.
- **Interactive `Predict State` Popup**: Clicking **Predict State** opens a modal showing the baked current state on the left and a selector for all loaded models on the right. Run **🔮 Predict** to render live interactive predictions with Layerify-style **hover glow**, remove any unwanted prediction with **`🗑️`**, and choose **➡️ Move to Annotation Page** (committing only your kept predictions to Layerify) or **🗑️ Remove / Ignore**.
