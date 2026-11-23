"""Training pipeline, catalog, and run-management mixin for WebAppEngine."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from imagebaker import logger
from imagebaker.training import (
    TrainingRunManager,
    default_pipeline_graph,
    load_trainers,
    validate_and_compile_pipeline,
)
from imagebaker.utils.annotation_formats import save_annotations_to_path


class WebEngineTrainingMixin:
    """Manages user-defined trainers, visual pipeline DAGs, and training runs."""

    def _init_training_subsystem(self, trainers_file: str | None = None) -> None:
        resolved_file: Path | None = None
        if trainers_file:
            cand = Path(trainers_file)
            if not cand.is_absolute():
                rel = self.project_dir / cand
                if rel.is_file():
                    cand = rel
            if cand.is_file():
                resolved_file = cand.resolve()
        elif (self.project_dir / "loaded_trainers.py").is_file():
            resolved_file = (self.project_dir / "loaded_trainers.py").resolve()

        self.trainers_file: Path | None = resolved_file
        self.loaded_trainers, self.loaded_augmentations = load_trainers(resolved_file)
        self.training_manager = TrainingRunManager(
            project_dir=self.project_dir,
            trainers_file=resolved_file,
        )
        self.train_pipeline_file = self.layer_config.cache_dir / "train_pipeline.json"
        self.train_cache_file = self.layer_config.cache_dir / "train_cache.json"
        self.train_presets: dict[str, dict[str, Any]] = {}
        self.train_loaded_checkpoints: list[dict[str, str]] = []
        self.train_pipeline: dict[str, Any] = self.load_train_cache()

    def load_train_cache(self) -> dict[str, Any]:
        """Restore Training pipeline, presets, and previously loaded checkpoints from `.imagebaker/cache/train_cache.json`."""
        default_trainer = next(iter(self.loaded_trainers.keys()), "")
        pipeline: dict[str, Any] | None = None

        if self.train_cache_file.is_file():
            try:
                raw = json.loads(self.train_cache_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    if isinstance(raw.get("pipeline"), dict) and isinstance(raw["pipeline"].get("nodes"), list):
                        pipeline = raw["pipeline"]
                    if isinstance(raw.get("presets"), dict):
                        self.train_presets = raw["presets"]
                    if isinstance(raw.get("loaded_checkpoints"), list):
                        self.train_loaded_checkpoints = raw["loaded_checkpoints"]
                        for item in self.train_loaded_checkpoints:
                            if not isinstance(item, dict):
                                continue
                            t_name = item.get("trainer_name", "")
                            r_id = item.get("run_id", "")
                            ckpt = item.get("checkpoint_path", "")
                            tr = self.loaded_trainers.get(t_name)
                            if tr and ckpt and Path(ckpt).exists():
                                try:
                                    m_obj = tr.build_inference_model(Path(ckpt))
                                    if m_obj is not None:
                                        self.loaded_models[f"{t_name}:{r_id}"] = m_obj
                                except Exception as exc:
                                    logger.warning(f"Failed to restore cached trained model {t_name}:{r_id}: {exc}")
            except Exception as exc:
                logger.warning(f"Failed to read train cache {self.train_cache_file}: {exc}")

        if pipeline is None and self.train_pipeline_file.is_file():
            try:
                data = json.loads(self.train_pipeline_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("nodes"), list):
                    pipeline = data
            except Exception as exc:
                logger.warning(f"Failed to read saved train pipeline: {exc}")

        if pipeline is None:
            pipeline = default_pipeline_graph(default_trainer=default_trainer)
        return pipeline

    def save_train_cache(self) -> Path:
        """Persist full Train tab state (pipeline, presets, loaded checkpoints) to `.imagebaker/cache/train_cache.json`."""
        with self.lock:
            self.train_cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "trainers_file": str(self.trainers_file) if self.trainers_file else None,
                "pipeline": self.train_pipeline,
                "presets": self.train_presets,
                "loaded_checkpoints": self.train_loaded_checkpoints,
            }
            try:
                self.train_cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                self.train_pipeline_file.write_text(
                    json.dumps(self.train_pipeline, indent=2), encoding="utf-8"
                )
            except Exception as exc:
                logger.warning(f"Failed to write train cache {self.train_cache_file}: {exc}")
            return self.train_cache_file

    def save_train_pipeline(
        self,
        pipeline: dict[str, Any],
        preset_name: str | None = None,
    ) -> tuple[bool, str]:
        with self.lock:
            if not isinstance(pipeline, dict) or not isinstance(pipeline.get("nodes"), list):
                return False, "Invalid pipeline payload."
            self.train_pipeline = pipeline
            if preset_name and str(preset_name).strip():
                self.train_presets[str(preset_name).strip()] = pipeline
            self.save_train_cache()
            self.last_message = (
                f"Saved training preset '{preset_name}'" if preset_name else "Training pipeline cached"
            )
            return True, self.last_message

    def reset_train_pipeline(self) -> tuple[bool, str]:
        with self.lock:
            default_trainer = next(iter(self.loaded_trainers.keys()), "")
            self.train_pipeline = default_pipeline_graph(default_trainer=default_trainer)
            self.save_train_cache()
            self.last_message = "Reset training pipeline to default"
            return True, self.last_message

    def get_training_catalog(self) -> dict[str, Any]:
        with self.lock:
            device_info = "cpu"
            try:
                import torch

                if torch.cuda.is_available():
                    device_info = f"cuda:0 ({torch.cuda.get_device_name(0)})"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device_info = "mps"
            except Exception:
                pass

            baker_states = (
                self.count_saved_baker_states()
                if hasattr(self, "count_saved_baker_states")
                else 0
            )
            layerify_total = len(self.image_entries)
            layerify_annotated = 0
            for idx, entry in enumerate(self.image_entries):
                anns = (
                    self.current_annotations
                    if idx == self.curr_image_idx
                    else self.load_image_annotations(entry.file_path)
                )
                if anns:
                    layerify_annotated += 1

            return {
                "trainers_file": str(self.trainers_file) if self.trainers_file else None,
                "trainers": {
                    name: tr.get_schema() for name, tr in self.loaded_trainers.items()
                },
                "augmentations": {
                    name: aug.get_schema() for name, aug in self.loaded_augmentations.items()
                },
                "device_info": device_info,
                "labels": [lbl.name for lbl in self.layer_config.predefined_labels],
                "data_counts": {
                    "baker_states": baker_states,
                    "layerify_images": layerify_total,
                    "layerify_annotated": layerify_annotated,
                },
                "presets": list(self.train_presets.keys()),
                "cache_file": str(self.train_cache_file),
            }

    def _prepare_training_dataset(
        self,
        compiled_spec: dict[str, Any],
        dataset_dir: Path,
    ) -> Path:
        """Prepare a clean, faithful training dataset snapshot from Layerify images and/or saved Baker states.

        When `source == "baker"`, uses ONLY the user's saved Baker timeline states rendered via
        the exact Baker compositor (`bake_saved_states_in_memory`) — never random synthetic noise.
        Supports COCO (`train/`, `valid/`, `test/` with `_annotations.coco.json`), YOLO (`data.yaml`),
        and Default JSON formats.
        """
        import numpy as np

        from imagebaker.utils.annotation_formats import export_annotations_data

        dataset_dir.mkdir(parents=True, exist_ok=True)
        sources_list = compiled_spec.get("data_sources") or [compiled_spec.get("data_source") or {}]
        split_cfg = compiled_spec.get("split_filter") or {}
        selected_labels = {str(x) for x in (split_cfg.get("selected_labels") or []) if x}
        allowed_types = {str(x).lower() for x in (split_cfg.get("annotation_types") or []) if x}
        real_only_val = bool(split_cfg.get("real_only_val", True))
        export_fmt = str(
            compiled_spec.get("trainer_config", {}).get("export_format")
            or (sources_list[0].get("export_format") if sources_list else None)
            or "coco"
        ).lower()

        train_r = float(split_cfg.get("train_ratio", 0.7))
        val_r = float(split_cfg.get("val_ratio", 0.2))
        test_r = float(split_cfg.get("test_ratio", 0.1))
        total_r = max(1e-6, train_r + val_r + test_r)
        train_frac = train_r / total_r
        val_frac = val_r / total_r

        def _ann_matches(ann) -> bool:
            if selected_labels and ann.label not in selected_labels:
                return False
            if allowed_types:
                has_mask = ann.mask is not None and bool(getattr(ann.mask, "any", lambda: False)())
                if has_mask and not ann.polygon and not ann.rectangle:
                    atype = "brush"
                elif ann.polygon and len(ann.polygon) >= 3:
                    atype = "polygon"
                elif ann.rectangle:
                    atype = "rectangle"
                else:
                    atype = "point"
                if atype not in allowed_types:
                    return False
            return True

        class_names = [
            lbl.name
            for lbl in self.layer_config.predefined_labels
            if not selected_labels or lbl.name in selected_labels
        ] or [lbl.name for lbl in self.layer_config.predefined_labels]

        # Optional ROI cropping by label names (default empty = no ROI cropping)
        roi_labels: set[str] = set()
        roi_padding = 0
        for src_cfg in sources_list:
            for rlbl in src_cfg.get("roi_labels") or []:
                if rlbl:
                    roi_labels.add(str(rlbl))
            if src_cfg.get("roi_padding") is not None:
                roi_padding = max(roi_padding, int(src_cfg.get("roi_padding") or 0))

        def _ann_bbox_xyxy(ann, img_w: int, img_h: int) -> tuple[int, int, int, int] | None:
            if ann.rectangle is not None:
                r = ann.rectangle
                x1, y1 = int(round(r.x())), int(round(r.y()))
                x2, y2 = int(round(r.x() + r.width())), int(round(r.y() + r.height()))
            elif ann.polygon is not None and len(ann.polygon) >= 3:
                xs = [p.x() for p in ann.polygon]
                ys = [p.y() for p in ann.polygon]
                x1, y1, x2, y2 = int(round(min(xs))), int(round(min(ys))), int(round(max(xs))), int(round(max(ys)))
            elif ann.mask is not None and bool(getattr(ann.mask, "any", lambda: False)()):
                ys, xs = np.nonzero(ann.mask)
                x1, y1, x2, y2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
            else:
                return None
            x1 = max(0, min(img_w - 1, x1))
            y1 = max(0, min(img_h - 1, y1))
            x2 = max(x1 + 1, min(img_w, x2))
            y2 = max(y1 + 1, min(img_h, y2))
            return (x1, y1, x2, y2)

        def _crop_ann_to_roi(ann, cx1: int, cy1: int, cw: int, ch: int):
            from PySide6.QtCore import QPointF, QRectF
            from PySide6.QtGui import QPolygonF

            ac = ann.copy()
            if ac.rectangle is not None:
                r = ac.rectangle
                nx1 = max(0.0, min(float(cw), r.x() - cx1))
                ny1 = max(0.0, min(float(ch), r.y() - cy1))
                nx2 = max(0.0, min(float(cw), r.x() + r.width() - cx1))
                ny2 = max(0.0, min(float(ch), r.y() + r.height() - cy1))
                if nx2 - nx1 < 2.0 or ny2 - ny1 < 2.0:
                    return None
                ac.rectangle = QRectF(nx1, ny1, nx2 - nx1, ny2 - ny1)
            if ac.polygon is not None and len(ac.polygon) >= 3:
                pts = [
                    QPointF(max(0.0, min(float(cw), p.x() - cx1)), max(0.0, min(float(ch), p.y() - cy1)))
                    for p in ac.polygon
                ]
                xs = [p.x() for p in pts]
                ys = [p.y() for p in pts]
                if max(xs) - min(xs) < 2.0 or max(ys) - min(ys) < 2.0:
                    return None
                ac.polygon = QPolygonF(pts)
            if ac.mask is not None and getattr(ac.mask, "ndim", 0) == 2:
                sub = ac.mask[cy1 : cy1 + ch, cx1 : cx1 + cw]
                if sub.size == 0 or not np.any(sub):
                    return None
                ac.mask = sub.copy()
            if ac.points:
                kept_pts = [
                    QPointF(p.x() - cx1, p.y() - cy1)
                    for p in ac.points
                    if cx1 <= p.x() <= cx1 + cw and cy1 <= p.y() <= cy1 + ch
                ]
                if not kept_pts and ac.rectangle is None and ac.polygon is None and ac.mask is None:
                    return None
                ac.points = kept_pts
            return ac

        def _expand_with_roi(sample: dict[str, Any], raw_anns: list[Any]) -> list[dict[str, Any]]:
            if not roi_labels:
                return [sample]
            from PySide6.QtGui import QImage

            qimg = sample["qimage"]
            if qimg is None and sample["src_path"] is not None:
                qimg = QImage(str(sample["src_path"]))
            if qimg is None or qimg.isNull():
                return []
            iw, ih = qimg.width(), qimg.height()
            roi_anns = [a for a in raw_anns if a.label in roi_labels]
            if not roi_anns:
                return []
            out_crops: list[dict[str, Any]] = []
            stem = Path(sample["name"]).stem
            for r_idx, r_ann in enumerate(roi_anns):
                box = _ann_bbox_xyxy(r_ann, iw, ih)
                if box is None:
                    continue
                bx1, by1, bx2, by2 = box
                cx1 = max(0, bx1 - roi_padding)
                cy1 = max(0, by1 - roi_padding)
                cx2 = min(iw, bx2 + roi_padding)
                cy2 = min(ih, by2 + roi_padding)
                cw, ch = cx2 - cx1, cy2 - cy1
                if cw < 4 or ch < 4:
                    continue
                crop_img = qimg.copy(cx1, cy1, cw, ch)
                crop_anns = []
                for a in sample["annotations"]:
                    if a is r_ann and (not selected_labels or a.label not in selected_labels):
                        continue
                    ca = _crop_ann_to_roi(a, cx1, cy1, cw, ch)
                    if ca is not None:
                        crop_anns.append(ca)
                out_crops.append(
                    {
                        "name": f"{stem}_roi{r_idx:02d}.png",
                        "width": cw,
                        "height": ch,
                        "annotations": crop_anns,
                        "origin": sample["origin"],
                        "qimage": crop_img,
                        "src_path": None,
                    }
                )
            return out_crops

        # Collect concrete sample records: {"name", "width", "height", "annotations", "origin", "qimage", "src_path"}
        baker_samples: list[dict[str, Any]] = []
        layerify_samples: list[dict[str, Any]] = []
        wants_baker = any(str(s.get("source", "")).lower() in ("baker", "hybrid") for s in sources_list)
        wants_layerify = any(str(s.get("source", "")).lower() in ("layerify", "hybrid") for s in sources_list)

        if wants_baker:
            baked_states = self.bake_saved_states_in_memory()
            for idx, res in enumerate(baked_states):
                filtered = [a for a in res.annotations if _ann_matches(a)]
                fname = f"baker_{idx:04d}_{res.filename.name}"
                base_sample = {
                    "name": fname,
                    "width": res.image.width(),
                    "height": res.image.height(),
                    "annotations": filtered,
                    "origin": "baker",
                    "qimage": res.image,
                    "src_path": None,
                }
                baker_samples.extend(_expand_with_roi(base_sample, res.annotations))

        if wants_layerify:
            for idx, entry in enumerate(self.image_entries):
                if not entry.file_path.is_file():
                    continue
                anns = (
                    self.current_annotations
                    if idx == self.curr_image_idx
                    else self.load_image_annotations(entry.file_path)
                )
                filtered = [a for a in anns if _ann_matches(a)]
                base_sample = {
                    "name": f"lyr_{idx:04d}_{entry.file_path.name}",
                    "width": entry.width,
                    "height": entry.height,
                    "annotations": filtered,
                    "origin": "layerify",
                    "qimage": None,
                    "src_path": entry.file_path,
                }
                layerify_samples.extend(_expand_with_roi(base_sample, anns))

        if not baker_samples and not layerify_samples:
            if roi_labels:
                raise ValueError(
                    f"No ROI crops found matching label(s): {', '.join(sorted(roi_labels))}."
                )
            if wants_baker and not wants_layerify:
                raise ValueError(
                    "No saved Baker states available. Save states in the Baker tab before training."
                )
            raise ValueError(
                "No training images available from the selected data source(s)."
            )

        # Assign splits cleanly (respecting real_only_val when mixing Layerify + Baker)
        splits: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}

        def _partition(items: list[dict[str, Any]]) -> None:
            n = len(items)
            if n == 0:
                return
            if n == 1:
                splits["train"].append(items[0])
                return
            n_train = max(1, int(round(n * train_frac)))
            n_val = max(1, int(round(n * val_frac))) if (n - n_train) >= 1 else 0
            if n_train + n_val > n:
                n_train = max(1, n - n_val)
            splits["train"].extend(items[:n_train])
            splits["val"].extend(items[n_train : n_train + n_val])
            splits["test"].extend(items[n_train + n_val :])

        if layerify_samples and baker_samples and real_only_val:
            splits["train"].extend(baker_samples)
            _partition(layerify_samples)
        else:
            _partition(baker_samples + layerify_samples)

        if not splits["val"] and len(splits["train"]) >= 2:
            splits["val"].append(splits["train"].pop())

        # Write dataset files in the requested format
        if export_fmt == "coco":
            coco_dir_names = {"train": "train", "val": "valid", "test": "test"}
            for split_key, items in splits.items():
                if not items and split_key == "test":
                    continue
                sdir = dataset_dir / coco_dir_names[split_key]
                sdir.mkdir(parents=True, exist_ok=True)
                coco_images = []
                coco_anns = []
                coco_cats = [
                    {"id": i, "name": cname, "supercategory": "object"}
                    for i, cname in enumerate(class_names, start=1)
                ]
                valid_cat_ids = {c["id"] for c in coco_cats}
                cat_name_to_id = {c["name"]: c["id"] for c in coco_cats}
                ann_uid = 1
                for img_uid, item in enumerate(items, start=1):
                    img_out = sdir / item["name"]
                    if item["qimage"] is not None:
                        item["qimage"].save(str(img_out), "PNG")
                    elif item["src_path"] is not None:
                        shutil.copy2(item["src_path"], img_out)
                    coco_images.append(
                        {
                            "id": img_uid,
                            "file_name": item["name"],
                            "width": int(item["width"]),
                            "height": int(item["height"]),
                        }
                    )
                    if item["annotations"]:
                        exp = export_annotations_data(
                            annotations=item["annotations"],
                            fmt="coco",
                            image_name=item["name"],
                            image_width=int(item["width"]),
                            image_height=int(item["height"]),
                            class_names=class_names,
                        )
                        exp_cat_id_to_name = {
                            int(c["id"]): str(c["name"])
                            for c in (exp.get("data") or {}).get("categories") or []
                        }
                        for ca in (exp.get("data") or {}).get("annotations") or []:
                            ca_copy = dict(ca)
                            ca_copy["id"] = ann_uid
                            ca_copy["image_id"] = img_uid
                            cid = int(ca_copy.get("category_id", 1))
                            if cid not in valid_cat_ids:
                                cname = exp_cat_id_to_name.get(cid)
                                if cname and cname in cat_name_to_id:
                                    cid = cat_name_to_id[cname]
                                elif cname:
                                    cid = len(coco_cats) + 1
                                    coco_cats.append({"id": cid, "name": cname, "supercategory": "object"})
                                    valid_cat_ids.add(cid)
                                    cat_name_to_id[cname] = cid
                                else:
                                    cid = coco_cats[0]["id"] if coco_cats else 1
                            ca_copy["category_id"] = cid
                            coco_anns.append(ca_copy)
                            ann_uid += 1
                (sdir / "_annotations.coco.json").write_text(
                    json.dumps(
                        {"images": coco_images, "annotations": coco_anns, "categories": coco_cats},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        else:
            for split_key, items in splits.items():
                img_dir = dataset_dir / "images" / split_key
                lbl_dir = dataset_dir / "labels" / split_key
                img_dir.mkdir(parents=True, exist_ok=True)
                lbl_dir.mkdir(parents=True, exist_ok=True)
                ext = ".txt" if export_fmt == "yolo" else ".json"
                for item in items:
                    img_out = img_dir / item["name"]
                    if item["qimage"] is not None:
                        item["qimage"].save(str(img_out), "PNG")
                    elif item["src_path"] is not None:
                        shutil.copy2(item["src_path"], img_out)
                    if item["annotations"]:
                        lbl_out = lbl_dir / f"{Path(item['name']).stem}{ext}"
                        save_annotations_to_path(
                            annotations=item["annotations"],
                            output_path=lbl_out,
                            fmt=export_fmt,
                            image_name=item["name"],
                            image_width=int(item["width"]),
                            image_height=int(item["height"]),
                            class_names=class_names,
                        )
            names_yaml = "\n".join(f"  {i}: {name}" for i, name in enumerate(class_names))
            (dataset_dir / "data.yaml").write_text(
                f"path: {dataset_dir.resolve().as_posix()}\n"
                f"train: images/train\n"
                f"val: images/val\n"
                f"test: images/test\n"
                f"names:\n{names_yaml}\n",
                encoding="utf-8",
            )
            (dataset_dir / "classes.txt").write_text("\n".join(class_names) + "\n", encoding="utf-8")

        manifest = {
            "export_format": export_fmt,
            "baker_states_used": len(baker_samples),
            "layerify_images_used": len(layerify_samples),
            "roi_labels": sorted(roi_labels),
            "roi_padding": roi_padding,
            "counts": {k: len(v) for k, v in splits.items()},
            "class_names": class_names,
        }
        (dataset_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return dataset_dir

    def preview_pipeline_node(
        self,
        pipeline: dict[str, Any] | None,
        node_id: str,
    ) -> dict[str, Any]:
        """Generate a live simulated image preview for hovering over a pipeline node."""
        import base64
        import io
        from collections import deque

        import cv2
        import numpy as np
        from PIL import Image

        with self.lock:
            pipe = pipeline if isinstance(pipeline, dict) else self.train_pipeline
            nodes = pipe.get("nodes") or []
            edges = pipe.get("edges") or []
            node_map = {str(n["id"]): n for n in nodes if "id" in n}
            if node_id not in node_map:
                return {"ok": False, "message": "Node not found."}

            # Reverse BFS to find upstream nodes feeding into node_id
            rev_adj: dict[str, list[str]] = {nid: [] for nid in node_map}
            for e in edges:
                s, t = str(e.get("source", "")), str(e.get("target", ""))
                if s in node_map and t in node_map:
                    rev_adj[t].append(s)
            upstream_ids: list[str] = []
            seen: set[str] = set()
            q = deque([node_id])
            while q:
                u = q.popleft()
                if u in seen:
                    continue
                seen.add(u)
                upstream_ids.append(u)
                for p in rev_adj.get(u, []):
                    q.append(p)
            upstream_nodes = [node_map[nid] for nid in reversed(upstream_ids)]

            data_nodes = [n for n in upstream_nodes if n.get("type") == "data_source"]
            split_nodes = [n for n in upstream_nodes if n.get("type") == "split_filter"]
            aug_nodes = [n for n in upstream_nodes if n.get("type") == "augmentation"]

            src_mode = str((data_nodes[0].get("config") or {}).get("source", "hybrid")) if data_nodes else "hybrid"
            split_cfg = (split_nodes[0].get("config") or {}) if split_nodes else {}
            selected_labels = {str(x) for x in (split_cfg.get("selected_labels") or []) if x}
            allowed_types = {str(x).lower() for x in (split_cfg.get("annotation_types") or []) if x}

            # 0. If hovering over an Eval & Visualize node, show the latest post-training val/test image if available
            if node_map[node_id].get("type") == "eval_vis":
                st = self.get_training_status()
                eval_imgs = st.get("eval_images") or []
                if eval_imgs:
                    first_ev = eval_imgs[0]
                    ev_path = self.training_manager.runs_dir / str(st.get("active_run_id", "")) / "eval_vis" / first_ev["name"]
                    if ev_path.is_file():
                        b64_ev = base64.b64encode(ev_path.read_bytes()).decode("ascii")
                        return {
                            "ok": True,
                            "node_id": node_id,
                            "node_label": node_map[node_id].get("label", "Eval & Visualize"),
                            "source": f"Eval ({first_ev.get('split', 'val')}: {first_ev.get('source_image', '')})",
                            "num_annotations": int(first_ev.get("num_preds", 0)),
                            "applied_augmentations": [f"GT: {first_ev.get('num_gt', 0)}", f"Preds: {first_ev.get('num_preds', 0)}"],
                            "image_b64": f"data:image/png;base64,{b64_ev}",
                        }

            # 1. Obtain a sample image + annotation overlays
            img_rgb = None
            boxes: list[tuple[int, int, int, int, str]] = []
            source_desc = src_mode

            if src_mode in ("baker", "hybrid"):
                try:
                    baked_list = self.bake_saved_states_in_memory(max_states=1)
                    if baked_list:
                        from imagebaker.utils.image import qpixmap_to_numpy

                        baked_res = baked_list[0]
                        rgba_np = qpixmap_to_numpy(baked_res.image.copy())
                        img_rgb = rgba_np[:, :, :3].copy()
                        total_states = self.count_saved_baker_states()
                        source_desc = f"Baker Saved State (1/{total_states})"
                        for ann in baked_res.annotations:
                            if selected_labels and ann.label not in selected_labels:
                                continue
                            has_mask = ann.mask is not None and bool(getattr(ann.mask, "any", lambda: False)())
                            atype = (
                                "brush" if (has_mask and not ann.polygon and not ann.rectangle)
                                else ("polygon" if ann.polygon else ("rectangle" if ann.rectangle else "point"))
                            )
                            if allowed_types and atype not in allowed_types:
                                continue
                            if ann.rectangle:
                                r = ann.rectangle
                                boxes.append((int(r.x()), int(r.y()), int(r.x() + r.width()), int(r.y() + r.height()), ann.label))
                            elif ann.polygon and len(ann.polygon) >= 3:
                                br = ann.polygon.boundingRect()
                                boxes.append((int(br.x()), int(br.y()), int(br.x() + br.width()), int(br.y() + br.height()), ann.label))
                except Exception:
                    pass

            if img_rgb is None and self.image_entries:
                entry = self.image_entries[min(self.curr_image_idx, len(self.image_entries) - 1)]
                if entry.file_path.is_file():
                    bgr = cv2.imread(str(entry.file_path))
                    if bgr is not None:
                        img_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                        source_desc = f"Layerify ({entry.name})"
                        anns = self.current_annotations or self.load_image_annotations(entry.file_path)
                        for ann in anns:
                            if selected_labels and ann.label not in selected_labels:
                                continue
                            has_mask = ann.mask is not None and bool(getattr(ann.mask, "any", lambda: False)())
                            atype = (
                                "brush" if (has_mask and not ann.polygon and not ann.rectangle)
                                else ("polygon" if ann.polygon else ("rectangle" if ann.rectangle else "point"))
                            )
                            if allowed_types and atype not in allowed_types:
                                continue
                            if ann.rectangle:
                                r = ann.rectangle
                                boxes.append((int(r.x()), int(r.y()), int(r.x() + r.width()), int(r.y() + r.height()), ann.label))
                            elif ann.polygon and len(ann.polygon) >= 3:
                                br = ann.polygon.boundingRect()
                                boxes.append((int(br.x()), int(br.y()), int(br.x() + br.width()), int(br.y() + br.height()), ann.label))

            if img_rgb is None:
                # Fallback clean synthetic preview canvas so hover preview always works
                img_rgb = np.full((200, 280, 3), (30, 41, 59), dtype=np.uint8)
                cv2.rectangle(img_rgb, (40, 45), (150, 145), (59, 130, 246), -1)
                cv2.circle(img_rgb, (210, 110), 34, (16, 185, 129), -1)
                boxes = [(40, 45, 150, 145, "sample_box"), (176, 76, 244, 144, "sample_obj")]
                source_desc = "Simulated Preview"

            # Draw boxes before spatial transforms so user sees augmentations applied to both image & labels
            vis = img_rgb.copy()
            h, w = vis.shape[:2]
            for x1, y1, x2, y2, lbl in boxes[:25]:
                cv2.rectangle(vis, (x1, y1), (x2, y2), (56, 189, 248), max(2, min(w, h) // 160))
                cv2.putText(vis, lbl[:14], (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

            applied_augs: list[str] = []
            for an in aug_nodes:
                ac = an.get("config") or {}
                if ac.get("enabled", True) is False:
                    continue
                aname = str(ac.get("augmentation_name") or an.get("label") or "")
                applied_augs.append(aname)
                if aname == "HorizontalFlip":
                    vis = cv2.flip(vis, 1)
                elif aname == "VerticalFlip":
                    vis = cv2.flip(vis, 0)
                elif aname == "RandomRotate":
                    angle = float(ac.get("max_angle", 20.0)) * 0.6
                    mat = cv2.getRotationMatrix2D((vis.shape[1] / 2.0, vis.shape[0] / 2.0), angle, 1.0)
                    vis = cv2.warpAffine(vis, mat, (vis.shape[1], vis.shape[0]))
                elif aname == "GaussianBlur":
                    k = max(3, int(ac.get("kernel_size", 5)) | 1)
                    vis = cv2.GaussianBlur(vis, (k, k), 0)
                elif aname == "ColorJitter":
                    b = float(ac.get("brightness", 0.2))
                    vis = np.clip(vis.astype(np.float32) * (1.0 + b * 0.6), 0, 255).astype(np.uint8)
                elif aname == "RandomCrop":
                    sc = max(0.3, min(0.95, float(ac.get("min_scale", 0.75))))
                    ch, cw = int(vis.shape[0] * sc), int(vis.shape[1] * sc)
                    y0, x0 = (vis.shape[0] - ch) // 2, (vis.shape[1] - cw) // 2
                    vis = cv2.resize(vis[y0 : y0 + ch, x0 : x0 + cw], (vis.shape[1], vis.shape[0]))
                elif aname == "Mosaic":
                    half = cv2.resize(vis, (max(2, vis.shape[1] // 2), max(2, vis.shape[0] // 2)))
                    top = np.hstack([half, cv2.flip(half, 1)])
                    bot = np.hstack([cv2.flip(half, 0), cv2.flip(half, -1)])
                    vis = np.vstack([top, bot])

            # Resize thumbnail for crisp fast hover popover
            max_w = 280
            if vis.shape[1] > max_w:
                scale = max_w / float(vis.shape[1])
                vis = cv2.resize(vis, (max_w, max(1, int(vis.shape[0] * scale))))

            buf = io.BytesIO()
            Image.fromarray(vis).save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return {
                "ok": True,
                "node_id": node_id,
                "node_label": node_map[node_id].get("label", node_id),
                "source": source_desc,
                "num_annotations": len(boxes),
                "applied_augmentations": applied_augs,
                "image_b64": f"data:image/png;base64,{b64}",
            }

    def validate_train_pipeline(self, pipeline: dict[str, Any] | None = None) -> tuple[bool, str, dict[str, Any] | None]:
        with self.lock:
            target = pipeline if pipeline is not None else self.train_pipeline
            return validate_and_compile_pipeline(target, self.loaded_trainers)

    def start_training(
        self,
        pipeline: dict[str, Any] | None = None,
        run_name: str | None = None,
    ) -> tuple[bool, str, str | None]:
        with self.lock:
            if pipeline is not None:
                self.save_train_pipeline(pipeline)
            ok, msg, compiled = self.validate_train_pipeline(self.train_pipeline)
            if not ok or compiled is None:
                self.last_message = msg
                return False, msg, None

            dataset_dir = self.training_manager.runs_dir / "_staging_dataset"
            if dataset_dir.exists():
                shutil.rmtree(dataset_dir, ignore_errors=True)
            try:
                self._prepare_training_dataset(compiled, dataset_dir)
            except Exception as exc:
                self.last_message = str(exc)
                return False, str(exc), None
            ok, msg, run_id = self.training_manager.start_run(
                compiled_spec=compiled,
                dataset_dir=dataset_dir,
                pipeline_snapshot=self.train_pipeline,
                run_name=run_name,
            )
            self.last_message = msg
            return ok, msg, run_id

    def delete_training_run(self, run_id: str) -> tuple[bool, str]:
        with self.lock:
            ok, msg = self.training_manager.delete_run(run_id)
            self.last_message = msg
            return ok, msg

    def get_training_run_pipeline(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self.training_manager.get_run_pipeline(run_id)

    def run_eval_visualization(
        self,
        run_id: str | None = None,
        split: str = "val",
        max_samples: int = 6,
        conf_threshold: float = 0.35,
        draw_ground_truth: bool = True,
    ) -> dict[str, Any]:
        """Run or re-run post-training visualization on a completed run's val/test split."""
        from imagebaker.training.worker import _generate_eval_visualizations

        with self.lock:
            st = self.get_training_status(run_id)
            target_id = run_id or st.get("active_run_id")
            if not target_id:
                return {"ok": False, "message": "No training run available to visualize."}
            run_dir = self.training_manager.runs_dir / target_id
            spec_file = run_dir / "run_spec.json"
            result_file = run_dir / "result.json"
            if not spec_file.is_file() or not result_file.is_file():
                return {"ok": False, "message": f"Run '{target_id}' is not completed yet."}
            spec = json.loads(spec_file.read_text(encoding="utf-8"))
            res = json.loads(result_file.read_text(encoding="utf-8"))
            ckpt = res.get("checkpoint_path")
            trainer = self.loaded_trainers.get(spec.get("trainer_name"))
            if not ckpt or not Path(ckpt).exists() or trainer is None:
                return {"ok": False, "message": "Trained checkpoint or trainer not available."}
            eval_images = _generate_eval_visualizations(
                trainer=trainer,
                checkpoint_path=Path(ckpt),
                dataset_dir=Path(spec["dataset_dir"]),
                run_dir=run_dir,
                eval_cfg={
                    "split": split,
                    "max_samples": max_samples,
                    "conf_threshold": conf_threshold,
                    "draw_ground_truth": draw_ground_truth,
                },
            )
            return {
                "ok": True,
                "message": f"Generated {len(eval_images)} {split} visualization(s).",
                "eval_images": eval_images,
                "training": self.get_training_status(target_id),
            }

    def stop_training(self) -> tuple[bool, str]:
        with self.lock:
            ok, msg = self.training_manager.stop_run()
            self.last_message = msg
            return ok, msg

    def get_training_status(self, run_id: str | None = None) -> dict[str, Any]:
        return self.training_manager.get_run_status(run_id=run_id)

    def load_trained_model_into_layerify(self, run_id: str) -> tuple[bool, str]:
        with self.lock:
            run_dir = self.training_manager.runs_dir / run_id
            result_file = run_dir / "result.json"
            if not result_file.is_file():
                return False, f"Run '{run_id}' has no completed result.json."
            res = json.loads(result_file.read_text(encoding="utf-8"))
            trainer_name = res.get("trainer_name")
            ckpt_str = res.get("checkpoint_path")
            if not ckpt_str or not Path(ckpt_str).exists():
                return False, f"Checkpoint not found for run '{run_id}'."
            trainer = self.loaded_trainers.get(trainer_name)
            if trainer is None:
                return False, f"Trainer '{trainer_name}' is not loaded."
            model_obj = trainer.build_inference_model(Path(ckpt_str))
            if model_obj is None:
                return False, f"Trainer '{trainer_name}' does not implement build_inference_model()."
            model_key = f"{trainer_name}:{run_id}"
            self.loaded_models[model_key] = model_obj
            self.current_model_name = model_key
            entry = {
                "run_id": run_id,
                "trainer_name": str(trainer_name),
                "checkpoint_path": str(ckpt_str),
            }
            if not any(c.get("run_id") == run_id for c in self.train_loaded_checkpoints):
                self.train_loaded_checkpoints.append(entry)
                self.save_train_cache()
            self.last_message = f"Loaded trained model '{model_key}' into Layerify"
            return True, self.last_message
