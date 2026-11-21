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
        err_msg = f"Training error: {exc}"
        _append_metric(metrics_file, TrainingProgress(status="failed", message=err_msg))
        result_file.write_text(
            json.dumps({"ok": False, "status": "failed", "message": err_msg}, indent=2),
            encoding="utf-8",
        )
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="ImageBaker training subprocess worker")
    parser.add_argument("--run-dir", required=True, help="Path to the run directory")
    args = parser.parse_args()
    sys.exit(run_worker(Path(args.run_dir).resolve()))


if __name__ == "__main__":
    main()
