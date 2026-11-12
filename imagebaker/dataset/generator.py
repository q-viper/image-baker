"""Cache discovery and synthetic dataset composition generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from imagebaker import logger
from imagebaker.core.defs.defs import AnnotationFormat
from imagebaker.dataset.config import CachedLayerAsset, DatasetBakeConfig
from imagebaker.utils.annotation_formats import (
    UNDEFINED_LABEL,
    export_annotations_data,
    mask_to_rle,
    rle_to_mask,
    save_annotations_to_path,
)


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

        baker_cache = self.cache_dir / "baker_cache.json"
        if baker_cache.exists():
            self._load_from_baker_cache(baker_cache)

        loaded_sources = {a.source_file for a in self.foreground_assets} | {
            a.source_file for a in self.background_assets
        }
        baker_layers_dir = self.cache_dir / "baker_layers"
        if baker_layers_dir.exists():
            for img_file in baker_layers_dir.glob("*.png"):
                if str(img_file) not in loaded_sources and img_file.name not in loaded_sources:
                    self._load_standalone_layer_image(img_file)

        if not self.background_assets:
            self._discover_fallback_backgrounds()

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
                    mask_arr = None
                    rle_data = ann_dict.get("rle")
                    mask_size = ann_dict.get("mask_size")
                    if rle_data and mask_size and len(mask_size) == 2:
                        mask_arr = rle_to_mask(
                            rle_data, int(mask_size[0]), int(mask_size[1])
                        )

                    asset = CachedLayerAsset(
                        name=name,
                        label=label,
                        image=img_rgba,
                        polygon=poly,
                        rectangle=rect,
                        mask=mask_arr,
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

        if not self.background_assets:
            target_w, target_h = self.config.background_size
            for bg_id in range(3):
                val = 220 + bg_id * 10
                synth = np.full(
                    (target_h, target_w, 4), [val, val, val, 255], dtype=np.uint8
                )
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

        shuffled = list(bgs)
        perm = self.rng.permutation(len(shuffled))
        shuffled = [shuffled[i] for i in perm]

        if not self.config.prevent_background_leakage or len(shuffled) < 3:
            return {s: list(shuffled) for s in self.config.split_ratios}

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

        scale = min(target_w / float(src_w), target_h / float(src_h))
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        pad_r, pad_g, pad_b = self.config.pad_color
        canvas = np.full(
            (target_h, target_w, 4), [pad_r, pad_g, pad_b, 255], dtype=np.uint8
        )
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
        sample_seed = (
            (self.config.seed or 1337) + (sample_index * 1009) + hash(split)
        ) & 0xFFFFFFFF
        s_rng = np.random.RandomState(sample_seed)

        bg_pool = (backgrounds_map or {}).get(split) or self.background_assets
        if not bg_pool:
            self._discover_fallback_backgrounds()
            bg_pool = self.background_assets

        bg_asset = bg_pool[s_rng.randint(0, len(bg_pool))]
        canvas = self.prepare_background(bg_asset, s_rng)
        canvas_h, canvas_w = canvas.shape[:2]

        num_layers = s_rng.randint(
            self.config.layers_per_image[0], self.config.layers_per_image[1] + 1
        )
        selected_assets: list[tuple[CachedLayerAsset, bool]] = []

        pool = list(self.foreground_assets)
        if not pool:
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

        if self.noise_assets and s_rng.rand() < 0.5:
            noise_asset = self.noise_assets[s_rng.randint(0, len(self.noise_assets))]
            selected_assets.append((noise_asset, False))

        perm = s_rng.permutation(len(selected_assets))
        selected_assets = [selected_assets[i] for i in perm]

        annotations = []
        ann_id = 1
        owner_map = np.zeros((canvas_h, canvas_w), dtype=np.int32)
        layer_records: list[dict[str, Any]] = []

        for slot_idx, (asset, should_label) in enumerate(selected_assets, start=1):
            src_img = asset.image
            src_h, src_w = src_img.shape[:2]

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

            rot_deg = float(s_rng.uniform(*self.config.rotation_range))
            if abs(rot_deg) > 0.5:
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

            opacity_val = s_rng.uniform(*self.config.opacity_range)
            alpha_factor = opacity_val / 255.0

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

                blended = (sub_layer[:, :, :3] * fg_alpha) + (
                    sub_bg[:, :, :3] * (1.0 - fg_alpha)
                )
                canvas[y1_dst:y2_dst, x1_dst:x2_dst, :3] = np.clip(blended, 0, 255).astype(
                    np.uint8
                )

                occ_patch = (sub_layer[:, :, 3] * alpha_factor) >= 20.0
                owner_map[y1_dst:y2_dst, x1_dst:x2_dst][occ_patch] = slot_idx

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
                    layer_records.append(
                        {
                            "slot": slot_idx,
                            "label": label,
                            "is_brush": asset.mask is not None,
                        }
                    )

        for rec in layer_records:
            vis_bin = (owner_map == rec["slot"]).astype(np.uint8) * 255
            if not np.any(vis_bin):
                continue
            bx, by, bw, bh = cv2.boundingRect(vis_bin)
            if bw < 4 or bh < 4:
                continue

            contours, _ = cv2.findContours(
                vis_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            valid_contours = [
                c for c in contours if cv2.contourArea(c) >= 4.0 and len(c) >= 3
            ]
            bbox = [int(bx), int(by), int(bw), int(bh)]

            if rec["is_brush"] or len(valid_contours) > 1:
                annotations.append(
                    {
                        "annotation_id": ann_id,
                        "label": rec["label"],
                        "type": "brushlabels",
                        "format": "rle",
                        "brushlabels": [rec["label"]],
                        "rle": mask_to_rle(vis_bin),
                        "mask_size": [int(canvas_h), int(canvas_w)],
                        "rectangle": bbox,
                        "polygon": [],
                        "visible": True,
                        "allow_export": True,
                    }
                )
            else:
                target_contour = (
                    valid_contours[0]
                    if valid_contours
                    else (max(contours, key=cv2.contourArea) if contours else None)
                )
                poly_pts = (
                    [[float(pt[0][0]), float(pt[0][1])] for pt in target_contour]
                    if target_contour is not None and len(target_contour) >= 3
                    else []
                )
                annotations.append(
                    {
                        "annotation_id": ann_id,
                        "label": rec["label"],
                        "rectangle": bbox,
                        "polygon": poly_pts,
                        "visible": True,
                        "allow_export": True,
                    }
                )
            ann_id += 1

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
        format: AnnotationFormat | str | None = None,
    ) -> dict[str, Any]:
        """
        Extract synthesized dataset into disk with train/val/test splits in specified format.
        """
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        fmt_enum = AnnotationFormat.from_value(format or self.config.export_format)
        fmt = fmt_enum.value

        bgs_map = self._partition_backgrounds()
        ratios = self.config.split_ratios
        tot = sum(ratios.values())

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

        for split_name, count in split_counts.items():
            if fmt == "yolo":
                img_dir = out_path / "images" / split_name
                lbl_dir = out_path / "labels" / split_name
            elif fmt == "coco":
                img_dir = out_path / split_name / "images"
                lbl_dir = out_path / "annotations"
            else:
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

                Image.fromarray(img_rgb).save(img_dest)

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
                else:
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

            generated_counts[split_name] = count

        self.config.to_json(out_path / "dataset_config.json")
        classes_txt = out_path / "classes.txt"
        classes_txt.write_text("\n".join(self.class_names), encoding="utf-8")

        if fmt == "yolo":
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
