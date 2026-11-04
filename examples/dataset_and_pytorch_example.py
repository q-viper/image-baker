"""
Dataset extraction and on-the-fly PyTorch Dataset synthesis example for ImageBaker.

This example demonstrates:
1. Configuring DatasetBakeConfig with:
   - train / val / test split ratios
   - Zero background data leakage across splits (`prevent_background_leakage=True`)
   - Aspect-ratio preserving background resizing and optional cropping
   - Layer min/max size constraints
   - Unlabeled noise layers (distractors baked visually but excluded from annotations)
   - Reproducibility via random seed
2. Extracting offline datasets in YOLO, COCO, and Default ImageBaker formats.
3. Using ImageBakerTorchDataset for on-the-fly sample synthesis directly inside
   PyTorch DataLoader pipelines.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imagebaker import (  # noqa: E402
    CacheDatasetGenerator,
    DatasetBakeConfig,
    ImageBakerTorchDataset,
    logger,
)


def create_demo_cache(cache_dir: Path) -> None:
    """Creates synthetic cache assets for foregrounds, backgrounds, and noise layers."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    layers_dir = cache_dir / "baker_layers"
    layers_dir.mkdir(parents=True, exist_ok=True)

    # 1. Background images (3 unique backgrounds)
    for bg_idx, color in enumerate([(60, 80, 100), (90, 70, 60), (45, 95, 65)]):
        bg = np.zeros((720, 1280, 4), dtype=np.uint8)
        bg[:, :, :3] = color
        bg[:, :, 3] = 255
        # Add visual texture
        cv2.circle(bg, (200 * (bg_idx + 1), 300), 120, (color[0] + 30, color[1] + 30, color[2] + 30, 255), -1)
        cv2.imwrite(str(layers_dir / f"bg_{bg_idx + 1}.png"), bg)

    # 2. Foreground labeled objects
    # Object 1: "widget" (blue circle)
    fg1 = np.zeros((120, 120, 4), dtype=np.uint8)
    cv2.circle(fg1, (60, 60), 50, (230, 120, 40, 255), -1)
    cv2.imwrite(str(layers_dir / "obj_widget.png"), fg1)

    # Object 2: "gear" (yellow rectangle)
    fg2 = np.zeros((100, 100, 4), dtype=np.uint8)
    cv2.rectangle(fg2, (15, 15), (85, 85), (50, 200, 240, 255), -1)
    cv2.imwrite(str(layers_dir / "obj_gear.png"), fg2)

    # 3. Noise distractor layer: "noise" (baked visually, but should have no label)
    noise = np.zeros((90, 90, 4), dtype=np.uint8)
    cv2.rectangle(noise, (10, 30), (80, 60), (120, 120, 120, 180), -1)
    cv2.imwrite(str(layers_dir / "distractor_noise.png"), noise)

    # 4. Save metadata into baker_cache.json
    cache_payload = {
        "version": 1,
        "saved_at": 1700000000.0,
        "canvases": [
            {
                "canvas_id": "canvas_1",
                "width": 1280,
                "height": 720,
                "layers": [
                    {
                        "layer_id": "bg_1",
                        "name": "background_1",
                        "label": "background",
                        "image_file": "baker_layers/bg_1.png",
                        "is_background": True,
                        "position": [0, 0],
                        "scale": [1.0, 1.0],
                        "rotation": 0.0,
                        "opacity": 1.0,
                    },
                    {
                        "layer_id": "bg_2",
                        "name": "background_2",
                        "label": "background",
                        "image_file": "baker_layers/bg_2.png",
                        "is_background": True,
                        "position": [0, 0],
                        "scale": [1.0, 1.0],
                        "rotation": 0.0,
                        "opacity": 1.0,
                    },
                    {
                        "layer_id": "bg_3",
                        "name": "background_3",
                        "label": "background",
                        "image_file": "baker_layers/bg_3.png",
                        "is_background": True,
                        "position": [0, 0],
                        "scale": [1.0, 1.0],
                        "rotation": 0.0,
                        "opacity": 1.0,
                    },
                    {
                        "layer_id": "fg_1",
                        "name": "widget",
                        "label": "widget",
                        "image_file": "baker_layers/obj_widget.png",
                        "is_background": False,
                        "position": [100, 100],
                        "scale": [1.0, 1.0],
                        "rotation": 0.0,
                        "opacity": 1.0,
                    },
                    {
                        "layer_id": "fg_2",
                        "name": "gear",
                        "label": "gear",
                        "image_file": "baker_layers/obj_gear.png",
                        "is_background": False,
                        "position": [300, 200],
                        "scale": [1.0, 1.0],
                        "rotation": 0.0,
                        "opacity": 1.0,
                    },
                    {
                        "layer_id": "noise_1",
                        "name": "distractor",
                        "label": "noise",
                        "image_file": "baker_layers/distractor_noise.png",
                        "is_background": False,
                        "position": [200, 400],
                        "scale": [1.0, 1.0],
                        "rotation": 0.0,
                        "opacity": 0.7,
                    },
                ],
            }
        ],
    }

    import json
    (cache_dir / "baker_cache.json").write_text(json.dumps(cache_payload, indent=2), encoding="utf-8")


def run_offline_dataset_extraction(cache_dir: Path, out_dir: Path) -> None:
    """Demonstrates offline dataset export to disk in YOLO and COCO formats."""
    logger.info("=== 1. Offline Dataset Extraction Example ===")

    # Define configuration
    config = DatasetBakeConfig(
        seed=42,  # Fully reproducible sampling
        split_ratios={"train": 0.7, "val": 0.2, "test": 0.1},
        prevent_background_leakage=True,  # Backgrounds never leak across splits
        background_size=(640, 640),  # Target size
        preserve_aspect_ratio=True,  # Resizes preserving aspect ratio and pads
        crop_large_background=True,  # Crops if larger than background size
        layer_min_size=(30, 30),  # Minimum layer bounding dimensions
        layer_max_size=(240, 240),  # Maximum layer bounding dimensions
        rotation_range=(-30.0, 30.0),  # Random rotation per placed layer
        scale_range=(0.6, 1.4),  # Random scale per placed layer
        opacity_range=(180.0, 255.0),  # Random layer opacity
        layers_per_image=(2, 4),  # 2 to 4 layers per baked sample
        unlabeled_labels=["noise", "distractor"],  # Baked into image, but not in annotations
        export_format="yolo",
    )

    # Initialize generator from cache
    generator = CacheDatasetGenerator(cache_dir=cache_dir, config=config)
    logger.info(f"Loaded class names: {generator.class_names}")
    logger.info(f"Loaded {len(generator.background_assets)} backgrounds, {len(generator.foreground_assets)} foregrounds")

    # Export YOLO dataset
    yolo_dir = out_dir / "dataset_yolo"
    yolo_meta = generator.extract_dataset(output_dir=yolo_dir, num_samples=10, format="yolo")
    logger.info(f"Exported YOLO dataset: {yolo_meta['splits']} to {yolo_dir}")
    if (yolo_dir / "data.yaml").exists():
        logger.info(f"Generated YAML:\n{(yolo_dir / 'data.yaml').read_text()[:300]}...")

    # Export COCO dataset
    coco_dir = out_dir / "dataset_coco"
    coco_meta = generator.extract_dataset(output_dir=coco_dir, num_samples=10, format="coco")
    logger.info(f"Exported COCO dataset: {coco_meta['splits']} to {coco_dir}")


def run_pytorch_dataset_example(cache_dir: Path) -> None:
    """Demonstrates using ImageBakerTorchDataset for on-the-fly synthesis."""
    logger.info("=== 2. On-the-fly PyTorch Dataset Synthesis Example ===")

    config = DatasetBakeConfig(
        seed=123,
        split_ratios={"train": 0.8, "val": 0.2},
        prevent_background_leakage=True,
        background_size=(640, 640),
        preserve_aspect_ratio=True,
        rotation_range=(-45.0, 45.0),
        scale_range=(0.5, 1.3),
        unlabeled_labels=["noise"],
        export_format="coco",
    )

    # Create on-the-fly training dataset
    train_dataset = ImageBakerTorchDataset(
        cache_dir=cache_dir,
        config=config,
        split="train",
        length=25,
    )

    logger.info(f"Train dataset length: {len(train_dataset)}")
    sample_image, sample_target = train_dataset[0]

    logger.info(f"Sample 0 image shape/type: {type(sample_image)} - {getattr(sample_image, 'shape', None)}")
    logger.info(f"Sample 0 target keys: {list(sample_target.keys())}")
    logger.info(f"Sample 0 boxes count: {len(sample_target['boxes'])}")
    logger.info(f"Sample 0 labels: {sample_target['labels']}")

    try:
        import torch
        from torch.utils.data import DataLoader

        def custom_collate_fn(batch):
            images = [item[0] for item in batch]
            targets = [item[1] for item in batch]
            return torch.stack(images, dim=0), targets

        loader = DataLoader(train_dataset, batch_size=4, shuffle=True, collate_fn=custom_collate_fn)
        for batch_idx, (batch_images, batch_targets) in enumerate(loader):
            logger.info(f"DataLoader Batch {batch_idx}: images tensor {batch_images.shape}, {len(batch_targets)} targets")
            if batch_idx >= 1:
                break
    except ImportError:
        logger.info("PyTorch is not installed in current environment; demonstrated standalone tensor conversion.")


def main() -> None:
    work_dir = Path(tempfile.mkdtemp(prefix="imagebaker_example_"))
    try:
        cache_dir = work_dir / "cache"
        output_dir = work_dir / "exports"

        create_demo_cache(cache_dir)
        run_offline_dataset_extraction(cache_dir, output_dir)
        run_pytorch_dataset_example(cache_dir)

        logger.info("Dataset and PyTorch example completed successfully!")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
