"""
Dataset extraction and on-the-fly PyTorch Dataset synthesis from ImageBaker cache.

Features:
  - CacheDatasetGenerator: Reads ImageBaker cache, composes baked dataset splits,
    and exports in 'default', 'coco', or 'yolo' formats.
  - Reproducible generation with fixed or custom seeds.
  - Configurable train / val / test splits with strict isolation of original images
    across splits to prevent background data leakage.
  - Flexible state variables (position, scale, rotation, opacity, edge feathering).
  - Selective annotation filtering (e.g. noise/distractors baked visually without labels).
  - Background resizing (preserving aspect ratio by default) and optional cropping.
  - Layer min / max size constraints.
  - ImageBakerTorchDataset: On-the-fly PyTorch Dataset subclass synthesizing samples dynamically.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from PIL import Image

from imagebaker import logger
from imagebaker.utils.annotation_formats import (
    UNDEFINED_LABEL,
    export_annotations_data,
    save_annotations_to_path,
)

try:
    import torch
    from torch.utils.data import Dataset as _TorchBaseDataset

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

    class _TorchBaseDataset:  # type: ignore[no-redef]
        """Fallback when torch is not installed."""

        pass


__all__ = [
    "DatasetBakeConfig",
    "CachedLayerAsset",
    "CacheDatasetGenerator",
    "ImageBakerTorchDataset",
]


@dataclass
class DatasetBakeConfig:
    """
    Configuration for dataset generation from ImageBaker cache.
    All properties are reproducible when `seed` is provided.
    """

    seed: int | None = 42

    # Output formatting and splits
    export_format: Literal["default", "coco", "yolo"] = "default"
    split_ratios: dict[str, float] = field(
        default_factory=lambda: {"train": 0.7, "val": 0.2, "test": 0.1}
    )
    prevent_background_leakage: bool = True  # Keep each original image in only one split

    # Background sizing & cropping
    background_size: tuple[int, int] = (640, 640)  # (width, height)
    preserve_aspect_ratio: bool = True
    crop_large_background: bool = True  # Optionally crop background if larger than target size
    crop_mode: Literal["random", "center"] = "random"
    pad_color: tuple[int, int, int] = (114, 114, 114)

    # Foreground layers selection
    layers_per_image: tuple[int, int] = (1, 4)
    background_labels: list[str] = field(
        default_factory=lambda: ["background", "bg", "backdrop"]
    )

    # Layer dimensions constraints
    layer_min_size: tuple[int, int] | int | None = 20  # (min_w, min_h) or min_side
    layer_max_size: tuple[int, int] | int | None = 480  # (max_w, max_h) or max_side

    # Annotation labeling controls (e.g. noise baked into composite without labels)
    labeled_labels: list[str] | None = None  # None means label all foregrounds
    unlabeled_labels: list[str] = field(
        default_factory=lambda: ["noise", "distractor", "background", "bg"]
    )

    # State variable ranges
    scale_range: tuple[float, float] = (0.6, 1.4)
    scale_x_range: tuple[float, float] | None = None
    scale_y_range: tuple[float, float] | None = None
    rotation_range: tuple[float, float] = (0.0, 360.0)
    opacity_range: tuple[float, float] = (200.0, 255.0)
    edge_opacity_range: tuple[int, int] = (255, 255)
    edge_width_range: tuple[int, int] = (1, 1)

    position_mode: Literal["random", "center"] = "random"
    allow_partial_overflow: bool = False  # If False, keep layer within background bounds

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetBakeConfig:
        clean = dict(data)
        if "background_size" in clean and isinstance(clean["background_size"], list):
            clean["background_size"] = tuple(clean["background_size"])
        if "layers_per_image" in clean and isinstance(clean["layers_per_image"], list):
            clean["layers_per_image"] = tuple(clean["layers_per_image"])
        if "scale_range" in clean and isinstance(clean["scale_range"], list):
            clean["scale_range"] = tuple(clean["scale_range"])
        if "rotation_range" in clean and isinstance(clean["rotation_range"], list):
            clean["rotation_range"] = tuple(clean["rotation_range"])
        if "opacity_range" in clean and isinstance(clean["opacity_range"], list):
            clean["opacity_range"] = tuple(clean["opacity_range"])
        return cls(**clean)

    def to_json(self, path: str | Path | None = None) -> str:
        s = json.dumps(self.to_dict(), indent=2)
        if path:
            Path(path).write_text(s, encoding="utf-8")
        return s

    @classmethod
    def from_json(cls, path_or_json: str | Path) -> DatasetBakeConfig:
        p = Path(path_or_json)
        if p.exists() and p.is_file():
            content = p.read_text(encoding="utf-8")
        else:
            content = str(path_or_json)
        return cls.from_dict(json.loads(content))


@dataclass
class CachedLayerAsset:
    """A layer asset loaded from cache."""

    name: str
    label: str
    image: np.ndarray  # RGBA uint8
    polygon: list[list[float]] | None = None
    rectangle: list[float] | None = None  # [x, y, w, h]
    mask: np.ndarray | None = None
    is_background: bool = False
    source_file: str = ""


class CacheDatasetGenerator:
    """
    Reads an ImageBaker project cache and generates synthetic baked datasets.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        config: DatasetBakeConfig | None = None,
    ):
        self.cache_dir = Path(cache_dir).resolve()
        self.config = config or DatasetBakeConfig()
        self.rng = np.random.RandomState(self.config.seed)

        self.background_assets: list[CachedLayerAsset] = []
        self.foreground_assets: list[CachedLayerAsset] = []
        self.noise_assets: list[CachedLayerAsset] = []
        self.class_names: list[str] = []

        self._load_cache()

    def _load_cache(self):
        """Discover and load layers and backgrounds from the cache directory."""
        if not self.cache_dir.exists():
            logger.warning(f"Cache directory does not exist: {self.cache_dir}")
            return

        # 1. Check for labels.json
        labels_json = self.cache_dir / "labels.json"
        if labels_json.exists():
            try:
                data = json.loads(labels_json.read_text(encoding="utf-8"))
                for item in data:
                    name = item.get("name")
                    if name and name not in self.class_names:
                        self.class_names.append(name)
            except Exception as e:
                logger.debug(f"Failed to load labels.json: {e}")

        # 2. Check baker_cache.json
        baker_cache = self.cache_dir / "baker_cache.json"
        if baker_cache.exists():
            self._load_from_baker_cache(baker_cache)

        # 3. Check for standalone images in cache/baker_layers or project assets
        loaded_sources = {a.source_file for a in self.foreground_assets} | {
            a.source_file for a in self.background_assets
        }
        baker_layers_dir = self.cache_dir / "baker_layers"
        if baker_layers_dir.exists():
            for img_file in baker_layers_dir.glob("*.png"):
                if str(img_file) not in loaded_sources and img_file.name not in loaded_sources:
                    self._load_standalone_layer_image(img_file)

        # 4. If no background assets loaded from cache, check parent project assets/exports
        if not self.background_assets:
            self._discover_fallback_backgrounds()

        # Update class names
        for asset in self.foreground_assets:
            if (
                asset.label
                and asset.label not in self.class_names
                and asset.label not in self.config.unlabeled_labels
            ):
                self.class_names.append(asset.label)

        if not self.class_names:
            self.class_names = [UNDEFINED_LABEL]

    def _load_from_baker_cache(self, path: Path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            canvases = payload.get("canvases", [])
            for c in canvases:
                for ldata in c.get("layers", []):
                    rel_img = ldata.get("image_file", "")
                    img_path = self.cache_dir / rel_img
                    if not img_path.exists():
                        continue

                    img_bgr = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
                    if img_bgr is None:
                        continue
                    if img_bgr.ndim == 2:
                        img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2RGBA)
                    elif img_bgr.shape[2] == 3:
                        img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
                    else:
                        img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2RGBA)

                    label = str(ldata.get("label") or UNDEFINED_LABEL)
                    name = str(ldata.get("name") or label)
                    is_bg = label.lower() in [
                        b.lower() for b in self.config.background_labels
                    ]

                    ann_dict = ldata.get("annotation") or {}
                    poly = ann_dict.get("polygon")
                    rect = ann_dict.get("rectangle")

                    asset = CachedLayerAsset(
                        name=name,
                        label=label,
                        image=img_rgba,
                        polygon=poly,
                        rectangle=rect,
                        is_background=is_bg,
                        source_file=str(img_path),
                    )

                    if is_bg:
                        self.background_assets.append(asset)
                    elif label.lower() in [
                        u.lower() for u in self.config.unlabeled_labels
                    ]:
                        self.noise_assets.append(asset)
                    else:
                        self.foreground_assets.append(asset)
        except Exception as e:
            logger.warning(f"Error parsing {path}: {e}")

    def _load_standalone_layer_image(self, img_path: Path):
        img_bgr = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
        if img_bgr is None:
            return
        if img_bgr.ndim == 2:
            img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2RGBA)
        elif img_bgr.shape[2] == 3:
            img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
        else:
            img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2RGBA)

        stem = img_path.stem
        is_bg = any(
            b.lower() in stem.lower() for b in self.config.background_labels
        )
        label = "background" if is_bg else UNDEFINED_LABEL
        h, w = img_rgba.shape[:2]

        asset = CachedLayerAsset(
            name=stem,
            label=label,
            image=img_rgba,
            rectangle=[0, 0, w, h],
            is_background=is_bg,
            source_file=str(img_path),
        )
        if is_bg:
            self.background_assets.append(asset)
        else:
            self.foreground_assets.append(asset)

    def _discover_fallback_backgrounds(self):
        """Find or create synthetic fallback background images if none were found in cache."""
        project_dir = self.cache_dir.parent.parent
        search_dirs = [
            project_dir / "assets",
            project_dir / "assets" / "exports",
            self.cache_dir.parent / "bake",
        ]
        for d in search_dirs:
            if not d.exists():
                continue
            for img_file in d.glob("*.*"):
                if img_file.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    img_bgr = cv2.imread(str(img_file))
                    if img_bgr is not None:
                        img_rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
                        h, w = img_rgba.shape[:2]
                        self.background_assets.append(
                            CachedLayerAsset(
                                name=img_file.stem,
                                label="background",
                                image=img_rgba,
                                rectangle=[0, 0, w, h],
                                is_background=True,
                                source_file=str(img_file),
                            )
                        )
                        if len(self.background_assets) >= 20:
                            break
            if self.background_assets:
                break

        # If still no backgrounds, synthesize clean blank canvas backgrounds
        if not self.background_assets:
            target_w, target_h = self.config.background_size
            for bg_id in range(3):
                # Light solid background with slight texture
                val = 220 + bg_id * 10
                synth = np.full((target_h, target_w, 4), [val, val, val, 255], dtype=np.uint8)
                self.background_assets.append(
                    CachedLayerAsset(
                        name=f"synth_background_{bg_id + 1}",
                        label="background",
                        image=synth,
                        rectangle=[0, 0, target_w, target_h],
                        is_background=True,
                        source_file=f"synthetic_bg_{bg_id + 1}",
                    )
                )

    def _partition_backgrounds(self) -> dict[str, list[CachedLayerAsset]]:
        """
        Split backgrounds across train/val/test without leakage (or shared if configured).
        """
        bgs = list(self.background_assets)
        if not bgs:
            return {"train": [], "val": [], "test": []}

        # Deterministically shuffle backgrounds using seed
        shuffled = list(bgs)
        perm = self.rng.permutation(len(shuffled))
        shuffled = [shuffled[i] for i in perm]

        if not self.config.prevent_background_leakage or len(shuffled) < 3:
            # Allow all backgrounds in all splits
            return {s: list(shuffled) for s in self.config.split_ratios}

        # Partition backgrounds proportionally
        ratios = self.config.split_ratios
        total_ratio = sum(ratios.values())
        norm_ratios = {k: v / total_ratio for k, v in ratios.items()}

        splits: dict[str, list[CachedLayerAsset]] = {}
        start_idx = 0
        n_total = len(shuffled)
        keys = list(norm_ratios.keys())

        for idx, k in enumerate(keys):
            if idx == len(keys) - 1:
                splits[k] = shuffled[start_idx:]
            else:
                count = max(1, int(round(n_total * norm_ratios[k])))
                end_idx = min(n_total, start_idx + count)
                splits[k] = shuffled[start_idx:end_idx]
                start_idx = end_idx

        # Ensure no split is empty if backgrounds are available
        for k in keys:
            if not splits[k] and shuffled:
                splits[k] = [shuffled[0]]

        return splits

    def prepare_background(
        self, bg_asset: CachedLayerAsset, sample_rng: np.random.RandomState
    ) -> np.ndarray:
        """
        Resize and/or crop the background according to config.
        Preserves aspect ratio by default.
        """
        target_w, target_h = self.config.background_size
        img = bg_asset.image
        src_h, src_w = img.shape[:2]

        if self.config.crop_large_background and (src_w > target_w or src_h > target_h):
            # Optional crop if larger than target size
            crop_w = min(src_w, target_w)
            crop_h = min(src_h, target_h)
            if self.config.crop_mode == "center":
                x0 = (src_w - crop_w) // 2
                y0 = (src_h - crop_h) // 2
            else:
                max_x = max(0, src_w - crop_w)
                max_y = max(0, src_h - crop_h)
                x0 = sample_rng.randint(0, max_x + 1) if max_x > 0 else 0
                y0 = sample_rng.randint(0, max_y + 1) if max_y > 0 else 0
            img = img[y0 : y0 + crop_h, x0 : x0 + crop_w]
            src_h, src_w = img.shape[:2]

        if not self.config.preserve_aspect_ratio:
            return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

        # Aspect-ratio preserving resize with padding
        scale = min(target_w / float(src_w), target_h / float(src_h))
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Pad onto target canvas
        pad_r, pad_g, pad_b = self.config.pad_color
        canvas = np.full((target_h, target_w, 4), [pad_r, pad_g, pad_b, 255], dtype=np.uint8)
        x_off = (target_w - new_w) // 2
        y_off = (target_h - new_h) // 2
        canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
        return canvas

    def _clamp_layer_size(
        self, cur_w: int, cur_h: int, target_scale: float
    ) -> tuple[float, float]:
        """Apply min/max size constraints to layer scale."""
        w = max(1, cur_w * target_scale)
        h = max(1, cur_h * target_scale)

        min_w, min_h = 4, 4
        if self.config.layer_min_size is not None:
            if isinstance(self.config.layer_min_size, (tuple, list)):
                min_w, min_h = self.config.layer_min_size
            else:
                min_w = min_h = int(self.config.layer_min_size)

        max_w, max_h = 10000, 10000
        if self.config.layer_max_size is not None:
            if isinstance(self.config.layer_max_size, (tuple, list)):
                max_w, max_h = self.config.layer_max_size
            else:
                max_w = max_h = int(self.config.layer_max_size)

        w = max(min_w, min(max_w, w))
        h = max(min_h, min(max_h, h))
        return float(w / max(1, cur_w)), float(h / max(1, cur_h))

    def generate_sample(
        self,
        split: str = "train",
        sample_index: int = 0,
        backgrounds_map: dict[str, list[CachedLayerAsset]] | None = None,
    ) -> dict[str, Any]:
        """
        Synthesize a single baked sample (image + ground-truth annotations) on the fly.
        """
        # Create a deterministic child RNG for this sample index
        sample_seed = (
            (self.config.seed or 1337) + (sample_index * 1009) + hash(split)
        ) & 0xFFFFFFFF
        s_rng = np.random.RandomState(sample_seed)

        # 1. Select background from this split's allocated backgrounds
        bg_pool = (backgrounds_map or {}).get(split) or self.background_assets
        if not bg_pool:
            self._discover_fallback_backgrounds()
            bg_pool = self.background_assets

        bg_asset = bg_pool[s_rng.randint(0, len(bg_pool))]
        canvas = self.prepare_background(bg_asset, s_rng)
        canvas_h, canvas_w = canvas.shape[:2]

        # 2. Pick foreground layers and optional noise layers
        num_layers = s_rng.randint(
            self.config.layers_per_image[0], self.config.layers_per_image[1] + 1
        )
        selected_assets: list[tuple[CachedLayerAsset, bool]] = []

        pool = list(self.foreground_assets)
        if not pool:
            # Synthetic fallback rectangle foreground
            box_img = np.zeros((80, 80, 4), dtype=np.uint8)
            cv2.circle(box_img, (40, 40), 38, (0, 180, 255, 255), -1)
            synth_asset = CachedLayerAsset(
                name="synth_circle",
                label="object",
                image=box_img,
                rectangle=[0, 0, 80, 80],
                is_background=False,
            )
            pool = [synth_asset]

        for _ in range(num_layers):
            asset = pool[s_rng.randint(0, len(pool))]
            selected_assets.append((asset, True))

        # Add optional noise layers (baked visually, but omitted from annotations)
        if self.noise_assets and s_rng.rand() < 0.5:
            noise_asset = self.noise_assets[s_rng.randint(0, len(self.noise_assets))]
            selected_assets.append((noise_asset, False))

        # Randomize layer stacking order
        perm = s_rng.permutation(len(selected_assets))
        selected_assets = [selected_assets[i] for i in perm]

        annotations = []
        ann_id = 1

        # 3. Paste each layer onto the background canvas
        for asset, should_label in selected_assets:
            src_img = asset.image
            src_h, src_w = src_img.shape[:2]

            # Scale
            if self.config.scale_x_range and self.config.scale_y_range:
                base_sx = s_rng.uniform(*self.config.scale_x_range)
                base_sy = s_rng.uniform(*self.config.scale_y_range)
            else:
                scale_val = s_rng.uniform(*self.config.scale_range)
                base_sx = base_sy = scale_val

            sx, sy = self._clamp_layer_size(src_w, src_h, (base_sx + base_sy) / 2.0)
            target_layer_w = max(1, int(round(src_w * sx)))
            target_layer_h = max(1, int(round(src_h * sy)))

            scaled_img = cv2.resize(
                src_img, (target_layer_w, target_layer_h), interpolation=cv2.INTER_LINEAR
            )

            # Rotation
            rot_deg = float(s_rng.uniform(*self.config.rotation_range))
            if abs(rot_deg) > 0.5:
                # Rotate image
                center = (target_layer_w / 2.0, target_layer_h / 2.0)
                M = cv2.getRotationMatrix2D(center, rot_deg, 1.0)
                cos = abs(M[0, 0])
                sin = abs(M[0, 1])
                new_rw = int((target_layer_h * sin) + (target_layer_w * cos))
                new_rh = int((target_layer_h * cos) + (target_layer_w * sin))
                M[0, 2] += (new_rw / 2.0) - center[0]
                M[1, 2] += (new_rh / 2.0) - center[1]
                rotated_img = cv2.warpAffine(
                    scaled_img,
                    M,
                    (new_rw, new_rh),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(0, 0, 0, 0),
                )
            else:
                rotated_img = scaled_img
                new_rw, new_rh = target_layer_w, target_layer_h

            # Position
            if self.config.position_mode == "center":
                x = (canvas_w - new_rw) // 2
                y = (canvas_h - new_rh) // 2
            else:
                if self.config.allow_partial_overflow:
                    min_x = -new_rw // 3
                    max_x = canvas_w - (new_rw * 2) // 3
                    min_y = -new_rh // 3
                    max_y = canvas_h - (new_rh * 2) // 3
                else:
                    min_x = 0
                    max_x = max(0, canvas_w - new_rw)
                    min_y = 0
                    max_y = max(0, canvas_h - new_rh)

                x = s_rng.randint(min_x, max_x + 1) if max_x > min_x else 0
                y = s_rng.randint(min_y, max_y + 1) if max_y > min_y else 0

            # Opacity
            opacity_val = s_rng.uniform(*self.config.opacity_range)
            alpha_factor = opacity_val / 255.0

            # Alpha blend onto canvas
            x1_src = max(0, -x)
            y1_src = max(0, -y)
            x2_src = min(new_rw, canvas_w - x)
            y2_src = min(new_rh, canvas_h - y)

            x1_dst = max(0, x)
            y1_dst = max(0, y)
            x2_dst = min(canvas_w, x + new_rw)
            y2_dst = min(canvas_h, y + new_rh)

            if x2_src > x1_src and y2_src > y1_src:
                sub_layer = rotated_img[y1_src:y2_src, x1_src:x2_src].astype(np.float32)
                sub_bg = canvas[y1_dst:y2_dst, x1_dst:x2_dst].astype(np.float32)

                fg_alpha = (sub_layer[:, :, 3] / 255.0) * alpha_factor
                fg_alpha = fg_alpha[:, :, None]

                blended = (sub_layer[:, :, :3] * fg_alpha) + (sub_bg[:, :, :3] * (1.0 - fg_alpha))
                canvas[y1_dst:y2_dst, x1_dst:x2_dst, :3] = np.clip(blended, 0, 255).astype(np.uint8)

                # Check if this layer should produce a labeled annotation
                label = asset.label
                is_unlabeled = (
                    not should_label
                    or (label.lower() in [u.lower() for u in self.config.unlabeled_labels])
                    or (
                        self.config.labeled_labels is not None
                        and label not in self.config.labeled_labels
                    )
                )

                if not is_unlabeled:
                    # Compute tight bounding box & polygon for visible foreground
                    mask_bin = (sub_layer[:, :, 3] > 20).astype(np.uint8) * 255
                    contours, _ = cv2.findContours(
                        mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )
                    if contours:
                        largest = max(contours, key=cv2.contourArea)
                        bx, by, bw, bh = cv2.boundingRect(largest)
                        if bw >= 4 and bh >= 4:
                            bbox = [int(x1_dst + bx), int(y1_dst + by), int(bw), int(bh)]
                            poly_pts = []
                            if len(largest) >= 3:
                                poly_pts = [
                                    [float(pt[0][0] + x1_dst), float(pt[0][1] + y1_dst)]
                                    for pt in largest
                                ]
                            annotations.append(
                                {
                                    "annotation_id": ann_id,
                                    "label": label,
                                    "rectangle": bbox,
                                    "polygon": poly_pts,
                                    "visible": True,
                                    "allow_export": True,
                                }
                            )
                            ann_id += 1

        # Convert canvas to RGB
        rgb_image = cv2.cvtColor(canvas, cv2.COLOR_RGBA2RGB)
        return {
            "image": rgb_image,
            "annotations": annotations,
            "width": canvas_w,
            "height": canvas_h,
            "split": split,
            "index": sample_index,
        }

    def extract_dataset(
        self,
        output_dir: str | Path,
        num_samples: int = 100,
        format: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract synthesized dataset into disk with train/val/test splits in specified format.
        """
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        fmt = (format or self.config.export_format).strip().lower()

        bgs_map = self._partition_backgrounds()
        ratios = self.config.split_ratios
        tot = sum(ratios.values())

        # Determine sample count per split
        split_counts: dict[str, int] = {}
        assigned = 0
        keys = list(ratios.keys())
        for idx, k in enumerate(keys):
            if idx == len(keys) - 1:
                split_counts[k] = max(1, num_samples - assigned)
            else:
                c = max(1, int(round(num_samples * (ratios[k] / tot))))
                split_counts[k] = c
                assigned += c

        generated_counts: dict[str, int] = {}
        coco_split_data: dict[str, dict] = {}

        for split_name, count in split_counts.items():
            if fmt == "yolo":
                img_dir = out_path / "images" / split_name
                lbl_dir = out_path / "labels" / split_name
            elif fmt == "coco":
                img_dir = out_path / split_name / "images"
                lbl_dir = out_path / "annotations"
            else:  # default
                img_dir = out_path / split_name / "images"
                lbl_dir = out_path / split_name / "annotations"

            img_dir.mkdir(parents=True, exist_ok=True)
            lbl_dir.mkdir(parents=True, exist_ok=True)

            coco_images = []
            coco_anns = []
            coco_ann_id = 1

            for i in range(count):
                sample = self.generate_sample(
                    split=split_name,
                    sample_index=i,
                    backgrounds_map=bgs_map,
                )
                img_rgb = sample["image"]
                anns = sample["annotations"]
                stem = f"sample_{split_name}_{i:05d}"
                img_filename = f"{stem}.png"
                img_dest = img_dir / img_filename

                # Save Image
                Image.fromarray(img_rgb).save(img_dest)

                # Save Annotations
                if fmt == "yolo":
                    txt_dest = lbl_dir / f"{stem}.txt"
                    save_annotations_to_path(
                        annotations=anns,
                        output_path=txt_dest,
                        fmt="yolo",
                        image_name=img_filename,
                        image_width=sample["width"],
                        image_height=sample["height"],
                        class_names=self.class_names,
                    )
                elif fmt == "coco":
                    exp = export_annotations_data(
                        annotations=anns,
                        fmt="coco",
                        image_name=img_filename,
                        image_width=sample["width"],
                        image_height=sample["height"],
                        class_names=self.class_names,
                        image_id=i + 1,
                    )
                    c_data = exp["data"]
                    coco_images.extend(c_data.get("images", []))
                    for ca in c_data.get("annotations", []):
                        ca["id"] = coco_ann_id
                        coco_ann_id += 1
                        coco_anns.append(ca)
                else:  # default
                    json_dest = lbl_dir / f"{stem}.json"
                    save_annotations_to_path(
                        annotations=anns,
                        output_path=json_dest,
                        fmt="default",
                        image_name=img_filename,
                        image_width=sample["width"],
                        image_height=sample["height"],
                        class_names=self.class_names,
                    )

            if fmt == "coco":
                cat_list = [
                    {"id": idx + 1, "name": c, "supercategory": "object"}
                    for idx, c in enumerate(self.class_names)
                ]
                coco_payload = {
                    "info": {"description": f"ImageBaker COCO {split_name}"},
                    "images": coco_images,
                    "annotations": coco_anns,
                    "categories": cat_list,
                }
                ann_file = lbl_dir / f"instances_{split_name}.json"
                ann_file.write_text(json.dumps(coco_payload, indent=2), encoding="utf-8")
                coco_split_data[split_name] = coco_payload

            generated_counts[split_name] = count

        # Write dataset metadata configs
        self.config.to_json(out_path / "dataset_config.json")
        classes_txt = out_path / "classes.txt"
        classes_txt.write_text("\n".join(self.class_names), encoding="utf-8")

        if fmt == "yolo":
            # Write standard YOLO data.yaml
            data_yaml = [
                f"path: {out_path}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                f"nc: {len(self.class_names)}",
                f"names: {self.class_names}",
            ]
            (out_path / "data.yaml").write_text("\n".join(data_yaml) + "\n", encoding="utf-8")

        return {
            "output_dir": str(out_path),
            "format": fmt,
            "classes": self.class_names,
            "splits": generated_counts,
            "total_samples": sum(generated_counts.values()),
        }


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
          - target: dict with 'boxes' (xyxy), 'labels' (class_id int), 'polygons', 'area', etc.
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

        for ann in anns:
            rect = ann.get("rectangle")
            if rect:
                rx, ry, rw, rh = rect
                x1 = float(rx)
                y1 = float(ry)
                x2 = float(rx + rw)
                y2 = float(ry + rh)
                boxes.append([x1, y1, x2, y2])
                areas.append(float(rw * rh))
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
            boxes_tensor = (
                torch.as_tensor(boxes, dtype=torch.float32)
                if boxes
                else torch.zeros((0, 4), dtype=torch.float32)
            )
            labels_tensor = (
                torch.as_tensor(labels, dtype=torch.int64)
                if labels
                else torch.zeros((0,), dtype=torch.int64)
            )
            areas_tensor = (
                torch.as_tensor(areas, dtype=torch.float32)
                if areas
                else torch.zeros((0,), dtype=torch.float32)
            )

            target["boxes"] = boxes_tensor
            target["labels"] = labels_tensor
            target["area"] = areas_tensor
            target["polygons"] = polygons

            # Image as [C, H, W] float32 in [0, 1]
            img_tensor = torch.from_numpy(img_rgb).permute(2, 0, 1).contiguous().float() / 255.0
            image_out: Any = img_tensor
        else:
            target["boxes"] = np.array(boxes, dtype=np.float32) if boxes else np.zeros((0, 4))
            target["labels"] = np.array(labels, dtype=np.int64) if labels else np.zeros((0,))
            target["area"] = np.array(areas, dtype=np.float32) if areas else np.zeros((0,))
            target["polygons"] = polygons
            image_out = img_rgb

        if self.transform is not None:
            image_out = self.transform(image_out)
        if self.target_transform is not None:
            target = self.target_transform(target)

        return image_out, target
