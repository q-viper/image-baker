"""On-the-fly PyTorch Dataset wrapper backed by CacheDatasetGenerator."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from imagebaker.dataset.config import DatasetBakeConfig
from imagebaker.dataset.generator import CacheDatasetGenerator
from imagebaker.utils.annotation_formats import UNDEFINED_LABEL, rle_to_mask

try:
    import torch
    from torch.utils.data import Dataset as _TorchBaseDataset

    TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001 - handle missing or unloadable native torch deps (e.g. OSError)
    TORCH_AVAILABLE = False

    class _TorchBaseDataset:  # type: ignore[no-redef]
        """Fallback when torch is not installed."""


class ImageBakerTorchDataset(_TorchBaseDataset):
    """
    On-the-fly PyTorch Dataset synthesizing training samples dynamically from ImageBaker cache.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        config: DatasetBakeConfig | None = None,
        split: str = "train",
        length: int = 1000,
        transform: Callable | None = None,
        target_transform: Callable | None = None,
    ):
        self.generator = CacheDatasetGenerator(cache_dir=cache_dir, config=config)
        self.split = split
        self.length = int(length)
        self.transform = transform
        self.target_transform = target_transform
        self.backgrounds_map = self.generator._partition_backgrounds()

    def __len__(self) -> int:
        return self.length

    def __getitem__(self, idx: int) -> tuple[Any, Any]:
        """
        Generate sample on the fly.
        Returns:
          - image: torch.Tensor [C, H, W] (float32 [0, 1]) if torch available, or np.ndarray [H, W, 3]
          - target: dict with 'boxes' (xyxy), 'labels' (class_id int), 'polygons', 'area', 'masks', etc.
        """
        sample = self.generator.generate_sample(
            split=self.split,
            sample_index=idx,
            backgrounds_map=self.backgrounds_map,
        )
        img_rgb = sample["image"]
        h, w = sample["height"], sample["width"]
        anns = sample["annotations"]

        boxes = []
        labels = []
        areas = []
        polygons = []
        inst_masks = []

        for ann in anns:
            inst_mask = np.zeros((h, w), dtype=np.uint8)
            rle_data = ann.get("rle")
            msize = ann.get("mask_size")
            if rle_data and msize and len(msize) == 2:
                decoded = rle_to_mask(rle_data, int(msize[0]), int(msize[1]))
                if decoded is not None:
                    inst_mask = (decoded > 0).astype(np.uint8)
            elif ann.get("polygon") and len(ann["polygon"]) >= 3:
                pts_i32 = np.round(np.array(ann["polygon"], dtype=np.float32)).astype(
                    np.int32
                )
                cv2.fillPoly(inst_mask, [pts_i32], 1)
            elif ann.get("rectangle"):
                rx, ry, rw, rh = ann["rectangle"]
                x0, y0 = max(0, int(rx)), max(0, int(ry))
                x1, y1 = min(w, int(rx + rw)), min(h, int(ry + rh))
                if x1 > x0 and y1 > y0:
                    inst_mask[y0:y1, x0:x1] = 1
            inst_masks.append(inst_mask)

            rect = ann.get("rectangle")
            if rect:
                rx, ry, rw, rh = rect
                x1 = float(rx)
                y1 = float(ry)
                x2 = float(rx + rw)
                y2 = float(ry + rh)
                boxes.append([x1, y1, x2, y2])
                areas.append(
                    float(np.count_nonzero(inst_mask))
                    if np.any(inst_mask)
                    else float(rw * rh)
                )
            else:
                boxes.append([0.0, 0.0, 0.0, 0.0])
                areas.append(0.0)

            lbl = ann.get("label", UNDEFINED_LABEL)
            cls_id = (
                self.generator.class_names.index(lbl)
                if lbl in self.generator.class_names
                else 0
            )
            labels.append(cls_id)
            polygons.append(ann.get("polygon") or [])

        target: dict[str, Any] = {
            "image_id": idx,
            "width": w,
            "height": h,
            "class_names": self.generator.class_names,
        }

        if TORCH_AVAILABLE:
            target["boxes"] = (
                torch.as_tensor(boxes, dtype=torch.float32)
                if boxes
                else torch.zeros((0, 4), dtype=torch.float32)
            )
            target["labels"] = (
                torch.as_tensor(labels, dtype=torch.int64)
                if labels
                else torch.zeros((0,), dtype=torch.int64)
            )
            target["area"] = (
                torch.as_tensor(areas, dtype=torch.float32)
                if areas
                else torch.zeros((0,), dtype=torch.float32)
            )
            target["polygons"] = polygons
            target["masks"] = (
                torch.as_tensor(np.stack(inst_masks, axis=0), dtype=torch.uint8)
                if inst_masks
                else torch.zeros((0, h, w), dtype=torch.uint8)
            )
            image_out: Any = (
                torch.from_numpy(img_rgb).permute(2, 0, 1).contiguous().float() / 255.0
            )
        else:
            target["boxes"] = (
                np.array(boxes, dtype=np.float32) if boxes else np.zeros((0, 4))
            )
            target["labels"] = (
                np.array(labels, dtype=np.int64) if labels else np.zeros((0,))
            )
            target["area"] = (
                np.array(areas, dtype=np.float32) if areas else np.zeros((0,))
            )
            target["polygons"] = polygons
            target["masks"] = (
                np.stack(inst_masks, axis=0)
                if inst_masks
                else np.zeros((0, h, w), dtype=np.uint8)
            )
            image_out = img_rgb

        if self.transform is not None:
            image_out = self.transform(image_out)
        if self.target_transform is not None:
            target = self.target_transform(target)

        return image_out, target
