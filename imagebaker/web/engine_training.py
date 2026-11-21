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
                "presets": list(self.train_presets.keys()),
                "cache_file": str(self.train_cache_file),
            }

    def _prepare_training_dataset(
        self,
        compiled_spec: dict[str, Any],
        dataset_dir: Path,
    ) -> Path:
        """Prepare a training dataset snapshot from one or more Layerify/Baker data sources."""
        dataset_dir.mkdir(parents=True, exist_ok=True)
        sources_list = compiled_spec.get("data_sources") or [compiled_spec.get("data_source") or {}]
        split_cfg = compiled_spec.get("split_filter") or {}
        selected_labels = {str(x) for x in (split_cfg.get("selected_labels") or []) if x}
        allowed_types = {str(x).lower() for x in (split_cfg.get("annotation_types") or []) if x}
        export_fmt = str(
            compiled_spec.get("trainer_config", {}).get("export_format")
            or (sources_list[0].get("export_format") if sources_list else None)
            or "yolo"
        ).lower()

        train_r = float(split_cfg.get("train_ratio", 0.7))
        val_r = float(split_cfg.get("val_ratio", 0.2))
        test_r = float(split_cfg.get("test_ratio", 0.1))
        total_r = max(1e-6, train_r + val_r + test_r)
        split_ratios = {
            "train": train_r / total_r,
            "val": val_r / total_r,
            "test": test_r / total_r,
        }

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

        for src_cfg in sources_list:
            source_mode = str(src_cfg.get("source", "hybrid")).lower()

            # 1. Baker synthetic dataset (if baker or hybrid and baker cache exists)
            if source_mode in ("baker", "hybrid") and self.baker_cache_file.is_file():
                try:
                    from imagebaker.dataset import CacheDatasetGenerator, DatasetBakeConfig

                    num_samples = max(2, int(src_cfg.get("num_synthetic_samples", 20)))
                    ds_cfg = DatasetBakeConfig(
                        export_format=export_fmt,
                        split_ratios=split_ratios,
                        labeled_labels=sorted(selected_labels) if selected_labels else None,
                    )
                    gen = CacheDatasetGenerator(
                        cache_dir=self.canvas_config.cache_dir,
                        config=ds_cfg,
                    )
                    if gen.foreground_assets:
                        gen.extract_dataset(
                            output_dir=dataset_dir,
                            num_samples=num_samples,
                            format=export_fmt,
                        )
                except Exception as exc:
                    logger.warning(f"Baker dataset generation skipped: {exc}")

            # 2. Layerify real images & annotations
            if source_mode in ("layerify", "hybrid"):
                images_train = dataset_dir / "images" / "train"
                labels_train = dataset_dir / "labels" / "train"
                images_val = dataset_dir / "images" / "val"
                labels_val = dataset_dir / "labels" / "val"
                for d in (images_train, labels_train, images_val, labels_val):
                    d.mkdir(parents=True, exist_ok=True)

                class_names = [
                    lbl.name
                    for lbl in self.layer_config.predefined_labels
                    if not selected_labels or lbl.name in selected_labels
                ] or [lbl.name for lbl in self.layer_config.predefined_labels]
                n_imgs = len(self.image_entries)
                for idx, entry in enumerate(self.image_entries):
                    if not entry.file_path.is_file():
                        continue
                    is_val = n_imgs >= 2 and idx >= max(1, int(n_imgs * split_ratios["train"]))
                    img_dest = (images_val if is_val else images_train) / entry.file_path.name
                    if not img_dest.exists():
                        shutil.copy2(entry.file_path, img_dest)
                    anns = (
                        self.current_annotations
                        if idx == self.curr_image_idx
                        else self.load_image_annotations(entry.file_path)
                    )
                    filtered_anns = [a for a in anns if _ann_matches(a)]
                    if filtered_anns:
                        ext = ".txt" if export_fmt == "yolo" else ".json"
                        lbl_dest = (labels_val if is_val else labels_train) / f"{entry.file_path.stem}{ext}"
                        save_annotations_to_path(
                            annotations=filtered_anns,
                            output_path=lbl_dest,
                            fmt=export_fmt,
                            image_name=entry.file_path.name,
                            image_width=entry.width,
                            image_height=entry.height,
                            class_names=class_names,
                        )

                data_yaml = dataset_dir / "data.yaml"
                if not data_yaml.is_file():
                    names_yaml = "\n".join(f"  {i}: {name}" for i, name in enumerate(class_names))
                    data_yaml.write_text(
                        f"path: {dataset_dir.resolve().as_posix()}\n"
                        f"train: images/train\n"
                        f"val: images/val\n"
                        f"names:\n{names_yaml}\n",
                        encoding="utf-8",
                    )

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

            # 1. Obtain a sample image + annotation overlays
            img_rgb = None
            boxes: list[tuple[int, int, int, int, str]] = []
            source_desc = src_mode

            if src_mode in ("baker", "hybrid") and self.baker_cache_file.is_file():
                try:
                    from imagebaker.dataset import CacheDatasetGenerator, DatasetBakeConfig

                    gen = CacheDatasetGenerator(
                        cache_dir=self.canvas_config.cache_dir,
                        config=DatasetBakeConfig(background_size=(320, 240)),
                    )
                    if gen.foreground_assets:
                        sample = gen.generate_sample(split="train", sample_index=0)
                        img_rgb = sample["image"].copy()
                        source_desc = "Baker Synthetic"
                        for a in sample.get("annotations") or []:
                            lbl = str(a.get("label", "Undefined"))
                            if selected_labels and lbl not in selected_labels:
                                continue
                            r = a.get("rectangle")
                            if r and len(r) == 4:
                                boxes.append((int(r[0]), int(r[1]), int(r[0] + r[2]), int(r[1] + r[3]), lbl))
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

    def start_training(self, pipeline: dict[str, Any] | None = None) -> tuple[bool, str, str | None]:
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
            self._prepare_training_dataset(compiled, dataset_dir)
            ok, msg, run_id = self.training_manager.start_run(
                compiled_spec=compiled,
                dataset_dir=dataset_dir,
                pipeline_snapshot=self.train_pipeline,
            )
            self.last_message = msg
            return ok, msg, run_id

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
