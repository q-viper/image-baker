"""Pipeline DAG validator, dataset preparer, and subprocess TrainingRunManager."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from imagebaker import logger
from imagebaker.training.base_trainer import BaseTrainer


def default_pipeline_graph(default_trainer: str | None = None) -> dict[str, Any]:
    """Return a ready-to-run default ReactFlow-style training pipeline DAG."""
    return {
        "nodes": [
            {
                "id": "node_data",
                "type": "data_source",
                "label": "Data Source",
                "x": 60,
                "y": 140,
                "config": {
                    "source": "layerify",  # layerify | baker | hybrid
                    "export_format": "coco",
                },
            },
            {
                "id": "node_split",
                "type": "split_filter",
                "label": "Split & Filter",
                "x": 320,
                "y": 140,
                "config": {
                    "train_ratio": 0.7,
                    "val_ratio": 0.2,
                    "test_ratio": 0.1,
                    "real_only_val": True,
                    "selected_labels": [],
                    "annotation_types": ["rectangle", "polygon", "brush", "point"],
                },
            },
            {
                "id": "node_aug",
                "type": "augmentation",
                "label": "HorizontalFlip",
                "x": 580,
                "y": 140,
                "config": {
                    "augmentation_name": "HorizontalFlip",
                    "enabled": True,
                    "probability": 0.5,
                },
            },
            {
                "id": "node_trainer",
                "type": "trainer",
                "label": "Model Trainer",
                "x": 850,
                "y": 140,
                "config": {
                    "trainer_name": default_trainer or "",
                    "training_mode": "finetune",
                    "epochs": 5,
                    "batch_size": 4,
                    "img_size": 640,
                    "learning_rate": 0.001,
                    "device": "auto",
                    "freeze_backbone": True,
                    "shots_per_class": 5,
                },
            },
            {
                "id": "node_output",
                "type": "output",
                "label": "Checkpoint & Layerify",
                "x": 1120,
                "y": 90,
                "config": {
                    "auto_load_layerify": True,
                },
            },
            {
                "id": "node_eval_vis",
                "type": "eval_vis",
                "label": "Eval & Visualize",
                "x": 1120,
                "y": 215,
                "config": {
                    "split": "val",
                    "max_samples": 6,
                    "conf_threshold": 0.35,
                    "draw_ground_truth": True,
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "node_data", "target": "node_split"},
            {"id": "e2", "source": "node_split", "target": "node_aug"},
            {"id": "e3", "source": "node_aug", "target": "node_trainer"},
            {"id": "e4", "source": "node_trainer", "target": "node_output"},
            {"id": "e5", "source": "node_trainer", "target": "node_eval_vis"},
        ],
    }


def validate_and_compile_pipeline(
    pipeline: dict[str, Any],
    available_trainers: dict[str, BaseTrainer],
) -> tuple[bool, str, dict[str, Any] | None]:
    """Validate a pipeline DAG (no cycles, has data_source -> trainer) and compile execution spec."""
    nodes = pipeline.get("nodes") or []
    edges = pipeline.get("edges") or []
    if not nodes:
        return False, "Pipeline has no nodes.", None

    node_map = {str(n["id"]): n for n in nodes if "id" in n}
    adj: dict[str, list[str]] = {nid: [] for nid in node_map}
    indeg: dict[str, int] = dict.fromkeys(node_map, 0)

    for edge in edges:
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src in node_map and tgt in node_map and src != tgt:
            adj[src].append(tgt)
            indeg[tgt] += 1

    # Kahn's topological sort for cycle detection
    q = deque([nid for nid, d in indeg.items() if d == 0])
    topo: list[str] = []
    while q:
        curr = q.popleft()
        topo.append(curr)
        for nxt in adj[curr]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    if len(topo) != len(node_map):
        return False, "Pipeline contains a cycle. Remove circular connections before training.", None

    ordered_nodes = [node_map[nid] for nid in topo]
    data_nodes = [n for n in ordered_nodes if n.get("type") == "data_source"]
    trainer_nodes = [n for n in ordered_nodes if n.get("type") == "trainer"]

    if not data_nodes:
        return False, "Pipeline requires a Data Source node.", None
    if not trainer_nodes:
        return False, "Pipeline requires a Trainer node.", None

    trainer_node = trainer_nodes[0]

    # Collect all data_source nodes that can reach trainer_node (supports multi-source pipelines!)
    connected_data_nodes = []
    visited: set[str] = set()
    for dn in data_nodes:
        sub_vis: set[str] = set()
        bfs = deque([str(dn["id"])])
        while bfs:
            u = bfs.popleft()
            if u in sub_vis:
                continue
            sub_vis.add(u)
            for v in adj.get(u, []):
                bfs.append(v)
        if str(trainer_node["id"]) in sub_vis:
            connected_data_nodes.append(dn)
            visited.update(sub_vis)

    if not connected_data_nodes:
        return False, "At least one Data Source node must be connected to the Trainer node.", None
    data_node = connected_data_nodes[0]

    t_cfg = dict(trainer_node.get("config") or {})
    trainer_name = str(t_cfg.pop("trainer_name", "") or "").strip()
    if not trainer_name and available_trainers:
        trainer_name = next(iter(available_trainers.keys()))
    if trainer_name not in available_trainers:
        return (
            False,
            f"Trainer '{trainer_name or 'None'}' is not loaded. Pass --trainers-file with LOADED_TRAINERS.",
            None,
        )

    split_nodes = [n for n in ordered_nodes if n.get("type") == "split_filter" and str(n["id"]) in visited]
    aug_nodes = [n for n in ordered_nodes if n.get("type") == "augmentation" and str(n["id"]) in visited]
    out_nodes = [n for n in ordered_nodes if n.get("type") == "output"]
    eval_nodes = [n for n in ordered_nodes if n.get("type") == "eval_vis"]

    augmentations = []
    for an in aug_nodes:
        ac = dict(an.get("config") or {})
        if ac.get("enabled", True):
            augmentations.append(
                {
                    "name": ac.get("augmentation_name") or an.get("label") or "Augmentation",
                    "params": ac,
                }
            )

    compiled = {
        "data_source": dict(data_node.get("config") or {}),
        "data_sources": [dict(dn.get("config") or {}) for dn in connected_data_nodes],
        "split_filter": dict(split_nodes[0].get("config") or {}) if split_nodes else {},
        "augmentations": augmentations,
        "trainer_name": trainer_name,
        "trainer_config": t_cfg,
        "output": dict(out_nodes[0].get("config") or {}) if out_nodes else {},
        "eval_vis": dict(eval_nodes[0].get("config") or {}) if eval_nodes else None,
    }
    return True, "Pipeline is valid.", compiled


class TrainingRunManager:
    """Manages training run directories, subprocess execution, and live metrics."""

    def __init__(
        self,
        project_dir: Path,
        trainers_file: Path | None = None,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.trainers_file = Path(trainers_file).resolve() if trainers_file else None
        self.runs_dir = self.project_dir / ".imagebaker" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._active_run_id: str | None = None

    def start_run(
        self,
        compiled_spec: dict[str, Any],
        dataset_dir: Path,
        pipeline_snapshot: dict[str, Any] | None = None,
        run_name: str | None = None,
    ) -> tuple[bool, str, str | None]:
        """Create a run directory (using optional custom `run_name`), persist `run_spec.json`, and spawn the worker subprocess.

        Returns `(ok, message, run_id)`. Only one active training subprocess runs per project
        at a time so GPU VRAM is not contended.
        """
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False, f"Run '{self._active_run_id}' is already running.", self._active_run_id

            cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(run_name or "").strip()).strip("_.-")[:64]
            base_id = cleaned if cleaned else time.strftime("run_%Y%m%d_%H%M%S")
            run_id = base_id
            run_dir = self.runs_dir / run_id
            suffix = 1
            while run_dir.exists():
                run_id = f"{base_id}_{suffix}"
                run_dir = self.runs_dir / run_id
                suffix += 1
            run_dir.mkdir(parents=True, exist_ok=True)

            spec = {
                "run_id": run_id,
                "run_name": str(run_name or "").strip() or run_id,
                "trainers_file": str(self.trainers_file) if self.trainers_file else None,
                "trainer_name": compiled_spec["trainer_name"],
                "trainer_config": compiled_spec["trainer_config"],
                "augmentations": compiled_spec["augmentations"],
                "data_source": compiled_spec["data_source"],
                "data_sources": compiled_spec.get("data_sources") or [compiled_spec["data_source"]],
                "split_filter": compiled_spec["split_filter"],
                "output": compiled_spec["output"],
                "eval_vis": compiled_spec.get("eval_vis"),
                "dataset_dir": str(dataset_dir.resolve()),
                "created_at": time.time(),
            }
            (run_dir / "run_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
            if pipeline_snapshot is not None:
                (run_dir / "pipeline.json").write_text(
                    json.dumps(pipeline_snapshot, indent=2), encoding="utf-8"
                )

            log_path = run_dir / "train.log"
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            env.setdefault("NO_COLOR", "1")
            repo_root = str(Path(__file__).resolve().parent.parent.parent)
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pp}" if existing_pp else repo_root

            cmd = [sys.executable, "-u", "-m", "imagebaker.training.worker", "--run-dir", str(run_dir)]
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )

            # Tee worker stdout/stderr to both train.log and the backend console
            proc_ref = self._proc

            def _tee_worker_output() -> None:
                try:
                    with log_path.open("w", encoding="utf-8", errors="replace") as log_fh:
                        if proc_ref.stdout is None:
                            return
                        for line in proc_ref.stdout:
                            log_fh.write(line)
                            log_fh.flush()
                            try:
                                sys.stdout.write(f"[train:{run_id}] {line}")
                                sys.stdout.flush()
                            except Exception:
                                pass
                except Exception as exc:
                    logger.warning(f"Training log tee stopped for {run_id}: {exc}")

            threading.Thread(
                target=_tee_worker_output,
                name=f"train-log-tee-{run_id}",
                daemon=True,
            ).start()

            self._active_run_id = run_id
            logger.info(f"Started training run {run_id} (PID {self._proc.pid})")
            return True, f"Started training run {run_id}", run_id

    def stop_run(self) -> tuple[bool, str]:
        """Request graceful stop via a `STOP` sentinel file, escalating to terminate/kill if needed."""
        with self._lock:
            if not self._active_run_id:
                return False, "No active training run."
            run_dir = self.runs_dir / self._active_run_id
            if run_dir.exists():
                (run_dir / "STOP").write_text("stop", encoding="utf-8")
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
            return True, f"Stopped training run {self._active_run_id}"

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def get_run_status(self, run_id: str | None = None) -> dict[str, Any]:
        """Return live status, parsed `metrics.jsonl` history, log tail, and recent run summaries."""
        with self._lock:
            target_id = run_id or self._active_run_id
            running = self.is_running()
            if not target_id:
                runs = self.list_runs()
                target_id = runs[0]["run_id"] if runs else None

            if not target_id:
                return {
                    "active_run_id": None,
                    "is_running": False,
                    "status": "idle",
                    "metrics_history": [],
                    "latest": None,
                    "logs": "",
                    "runs": [],
                }

            run_dir = self.runs_dir / target_id
            metrics_history: list[dict[str, Any]] = []
            metrics_file = run_dir / "metrics.jsonl"
            if metrics_file.is_file():
                for line in metrics_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        metrics_history.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

            latest = metrics_history[-1] if metrics_history else None
            status = latest.get("status", "running") if latest else ("running" if running else "idle")
            if not running and status == "running":
                status = "completed" if (run_dir / "result.json").is_file() else "stopped"

            logs = ""
            log_file = run_dir / "train.log"
            if log_file.is_file():
                logs = log_file.read_text(encoding="utf-8", errors="replace")[-8000:]

            eval_images: list[dict[str, Any]] = []
            eval_manifest = run_dir / "eval_vis" / "manifest.json"
            if eval_manifest.is_file():
                try:
                    eval_images = json.loads(eval_manifest.read_text(encoding="utf-8"))
                except Exception:
                    eval_images = []

            return {
                "active_run_id": target_id,
                "is_running": running,
                "status": status,
                "metrics_history": metrics_history[-200:],
                "latest": latest,
                "logs": logs,
                "eval_images": eval_images,
                "runs": self.list_runs(),
            }

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if not self.runs_dir.exists():
            return runs
        for run_dir in sorted(self.runs_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            spec_file = run_dir / "run_spec.json"
            if not spec_file.is_file():
                continue
            try:
                spec = json.loads(spec_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            result_file = run_dir / "result.json"
            res = {}
            if result_file.is_file():
                try:
                    res = json.loads(result_file.read_text(encoding="utf-8"))
                except Exception:
                    res = {}
            is_active = self._active_run_id == run_dir.name and self.is_running()
            runs.append(
                {
                    "run_id": run_dir.name,
                    "run_name": spec.get("run_name") or run_dir.name,
                    "trainer_name": spec.get("trainer_name", ""),
                    "training_mode": (spec.get("trainer_config") or {}).get("training_mode", ""),
                    "status": "running" if is_active else res.get("status", "unknown"),
                    "checkpoint_path": res.get("checkpoint_path"),
                    "has_eval": (run_dir / "eval_vis" / "manifest.json").is_file(),
                    "has_pipeline": (run_dir / "pipeline.json").is_file(),
                    "metrics": res.get("metrics") or {},
                    "created_at": spec.get("created_at"),
                }
            )
        return runs[:30]

    def delete_run(self, run_id: str) -> tuple[bool, str]:
        """Delete a completed/stopped/failed training run directory from `.imagebaker/runs/`."""
        with self._lock:
            safe_id = Path(str(run_id or "")).name
            if not safe_id or safe_id.startswith("_"):
                return False, "Invalid run ID."
            if self._active_run_id == safe_id and self.is_running():
                return False, f"Cannot delete active running job '{safe_id}'. Stop it first."
            target = (self.runs_dir / safe_id).resolve()
            runs_root = self.runs_dir.resolve()
            if not str(target).startswith(str(runs_root)) or not target.is_dir():
                return False, f"Run '{safe_id}' not found."
            shutil.rmtree(target, ignore_errors=False)
            if self._active_run_id == safe_id:
                self._active_run_id = None
            return True, f"Deleted training run '{safe_id}'."

    def get_run_pipeline(self, run_id: str) -> dict[str, Any] | None:
        """Load the saved `pipeline.json` snapshot for a past training run, if available."""
        with self._lock:
            safe_id = Path(str(run_id or "")).name
            if not safe_id:
                return None
            pfile = (self.runs_dir / safe_id / "pipeline.json").resolve()
            if not str(pfile).startswith(str(self.runs_dir.resolve())) or not pfile.is_file():
                return None
            try:
                return json.loads(pfile.read_text(encoding="utf-8"))
            except Exception:
                return None

    def cleanup_dataset_copy(self, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
