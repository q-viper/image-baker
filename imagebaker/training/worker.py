"""Subprocess worker entry point for executing a compiled ImageBaker training run."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from imagebaker.training.base_trainer import TrainingProgress
from imagebaker.training.loader import load_trainers


def _append_metric(metrics_file: Path, event: TrainingProgress) -> None:
    if event.timestamp is None:
        event.timestamp = time.time()
    with metrics_file.open("a", encoding="utf-8") as fh:
        fh.write(event.model_dump_json() + "\n")
        fh.flush()
    if event.message:
        try:
            print(f"[{event.status.upper()}] {event.message}", flush=True)
        except Exception:
            pass


def run_worker(run_dir: Path) -> int:
    """Execute a single compiled training run inside an isolated subprocess.

    Reads `run_spec.json` from `run_dir`, dynamically loads the configured `--trainers-file`,
    streams `TrainingProgress` events into `metrics.jsonl`, and writes `result.json` on exit.
    """
    spec_path = run_dir / "run_spec.json"
    metrics_file = run_dir / "metrics.jsonl"
    result_file = run_dir / "result.json"
    stop_flag = run_dir / "STOP"

    if not spec_path.is_file():
        _append_metric(
            metrics_file,
            TrainingProgress(status="failed", message=f"Missing run_spec.json in {run_dir}"),
        )
        return 1

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    trainers_file = spec.get("trainers_file")
    trainer_name = spec.get("trainer_name")
    dataset_dir = Path(spec["dataset_dir"])
    raw_config = spec.get("trainer_config") or {}
    augmentations = spec.get("augmentations") or []

    trainers, _ = load_trainers(trainers_file)
    trainer = trainers.get(trainer_name)
    if trainer is None:
        msg = f"Trainer '{trainer_name}' not found in {trainers_file}."
        _append_metric(metrics_file, TrainingProgress(status="failed", message=msg))
        result_file.write_text(json.dumps({"ok": False, "message": msg}, indent=2), encoding="utf-8")
        return 1

    def progress_cb(ev: TrainingProgress) -> None:
        _append_metric(metrics_file, ev)

    def stop_check() -> bool:
        return stop_flag.exists()

    try:
        config_obj = trainer.config_class(**raw_config)
        _append_metric(
            metrics_file,
            TrainingProgress(
                epoch=0,
                total_epochs=config_obj.epochs,
                status="running",
                message=f"Starting {trainer_name} ({config_obj.training_mode})...",
            ),
        )
        summary = trainer.train(
            dataset_dir=dataset_dir,
            work_dir=run_dir,
            config=config_obj,
            augmentations=augmentations,
            progress_cb=progress_cb,
            stop_check=stop_check,
        )
        final_status = "stopped" if stop_check() else "completed"
        checkpoint = summary.get("checkpoint_path") if isinstance(summary, dict) else None
        final_metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}

        # Optional post-training visualization on val/test split if Eval & Visualize node is connected
        eval_vis_cfg = spec.get("eval_vis")
        if final_status == "completed" and checkpoint and isinstance(eval_vis_cfg, dict):
            try:
                _generate_eval_visualizations(
                    trainer=trainer,
                    checkpoint_path=Path(checkpoint),
                    dataset_dir=dataset_dir,
                    run_dir=run_dir,
                    eval_cfg=eval_vis_cfg,
                )
            except Exception as eval_exc:
                _append_metric(
                    metrics_file,
                    TrainingProgress(
                        epoch=config_obj.epochs,
                        total_epochs=config_obj.epochs,
                        status="running",
                        message=f"Eval visualization skipped: {eval_exc}",
                    ),
                )
        _append_metric(
            metrics_file,
            TrainingProgress(
                epoch=config_obj.epochs if final_status == "completed" else int(summary.get("last_epoch", 0)),
                total_epochs=config_obj.epochs,
                status=final_status,
                message=summary.get("message", f"Training {final_status}.") if isinstance(summary, dict) else f"Training {final_status}.",
                metrics=final_metrics,
                checkpoint_path=str(checkpoint) if checkpoint else None,
            ),
        )
        result_payload = {
            "ok": final_status == "completed",
            "status": final_status,
            "trainer_name": trainer_name,
            "checkpoint_path": str(checkpoint) if checkpoint else None,
            "metrics": final_metrics,
            "summary": summary if isinstance(summary, dict) else {},
        }
        result_file.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        err_msg = f"Training error: {exc}"
        _append_metric(metrics_file, TrainingProgress(status="failed", message=err_msg))
        result_file.write_text(
            json.dumps({"ok": False, "status": "failed", "message": err_msg}, indent=2),
            encoding="utf-8",
        )
        return 1


def _collect_split_images(dataset_dir: Path, split: str) -> list[Path]:
    """Find image files in a prepared dataset's val/valid/test/train split."""
    valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    split_norm = (split or "val").strip().lower()
    candidates = (
        ["valid", "val", "images/val", "images/valid"]
        if split_norm in ("val", "valid")
        else (["test", "images/test"] if split_norm == "test" else ["train", "images/train"])
    )
    found: list[Path] = []
    for rel in candidates:
        d = dataset_dir / rel
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.is_file() and p.suffix.lower() in valid_exts:
                    found.append(p)
            if found:
                return found
    # Fallback to train if requested split is empty
    for rel in ("train", "images/train"):
        d = dataset_dir / rel
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.is_file() and p.suffix.lower() in valid_exts:
                    found.append(p)
            if found:
                return found
    return found


def _load_gt_boxes_for_image(img_path: Path, dataset_dir: Path, img_w: int, img_h: int) -> list[tuple[int, int, int, int, str]]:
    """Load ground-truth boxes from COCO _annotations.coco.json or YOLO .txt if present."""
    gt: list[tuple[int, int, int, int, str]] = []
    coco_file = img_path.parent / "_annotations.coco.json"
    if coco_file.is_file():
        try:
            coco = json.loads(coco_file.read_text(encoding="utf-8"))
            cat_map = {int(c["id"]): str(c["name"]) for c in coco.get("categories", [])}
            img_id = next(
                (int(im["id"]) for im in coco.get("images", []) if im.get("file_name") == img_path.name),
                None,
            )
            if img_id is not None:
                for ann in coco.get("annotations", []):
                    if int(ann.get("image_id", -1)) == img_id and ann.get("bbox"):
                        x, y, bw, bh = [float(v) for v in ann["bbox"]]
                        gt.append((int(x), int(y), int(x + bw), int(y + bh), cat_map.get(int(ann.get("category_id", 0)), "gt")))
                return gt
        except Exception:
            pass

    # Check YOLO label file in parallel labels/<split>/<stem>.txt
    split_name = img_path.parent.name
    yolo_txt = dataset_dir / "labels" / split_name / f"{img_path.stem}.txt"
    if yolo_txt.is_file():
        for line in yolo_txt.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) == 5:
                cid, xc, yc, bw, bh = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                x1 = int((xc - bw / 2.0) * img_w)
                y1 = int((yc - bh / 2.0) * img_h)
                x2 = int((xc + bw / 2.0) * img_w)
                y2 = int((yc + bh / 2.0) * img_h)
                gt.append((x1, y1, x2, y2, f"cls_{cid}"))
    return gt


def _generate_eval_visualizations(
    trainer,
    checkpoint_path: Path,
    dataset_dir: Path,
    run_dir: Path,
    eval_cfg: dict,
) -> list[dict]:
    """Run trained checkpoint on val/test images and save annotated visualization PNGs."""
    import cv2
    import numpy as np

    model = trainer.build_inference_model(checkpoint_path)
    if model is None:
        return []

    split = str(eval_cfg.get("split", "val"))
    max_samples = max(1, min(24, int(eval_cfg.get("max_samples", 6))))
    conf_thr = float(eval_cfg.get("conf_threshold", 0.35))
    draw_gt = bool(eval_cfg.get("draw_ground_truth", True))

    imgs = _collect_split_images(dataset_dir, split)[:max_samples]
    out_dir = run_dir / "eval_vis"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    for idx, img_path in enumerate(imgs):
        bgr = cv2.imread(str(img_path))
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        vis = bgr.copy()

        gt_boxes = _load_gt_boxes_for_image(img_path, dataset_dir, w, h) if draw_gt else []
        for x1, y1, x2, y2, lbl in gt_boxes:
            cv2.rectangle(vis, (x1, y1), (x2, y2), (74, 222, 128), 2)
            cv2.putText(vis, f"GT:{lbl[:12]}", (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (74, 222, 128), 1, cv2.LINE_AA)

        preds = model.predict(rgb) or []
        n_pred = 0
        for p in preds:
            score = float(p.score) if p.score is not None else 1.0
            if score < conf_thr:
                continue
            n_pred += 1
            if p.polygon is not None and len(p.polygon) >= 3:
                pts = np.round(np.asarray(p.polygon, dtype=np.float32)).astype(np.int32)
                cv2.polylines(vis, [pts], isClosed=True, color=(56, 189, 248), thickness=2)
            if p.rectangle and len(p.rectangle) == 4:
                rx, ry, rw, rh = [int(v) for v in p.rectangle]
                cv2.rectangle(vis, (rx, ry), (rx + rw, ry + rh), (249, 115, 22), 2)
                cv2.putText(
                    vis,
                    f"{p.class_name or 'pred'} {score:.2f}",
                    (rx, min(h - 6, ry + rh + 14)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (249, 115, 22),
                    1,
                    cv2.LINE_AA,
                )

        out_name = f"eval_{split}_{idx:02d}_{img_path.stem[:20]}.png"
        cv2.imwrite(str(out_dir / out_name), vis)
        manifest.append(
            {
                "name": out_name,
                "source_image": img_path.name,
                "split": split,
                "num_gt": len(gt_boxes),
                "num_preds": n_pred,
                "url": f"/api/train/eval-image?run_id={run_dir.name}&name={out_name}",
            }
        )

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="ImageBaker training subprocess worker")
    parser.add_argument("--run-dir", required=True, help="Path to the run directory")
    args = parser.parse_args()
    sys.exit(run_worker(Path(args.run_dir).resolve()))


if __name__ == "__main__":
    main()
