"""Tests for ImageBaker model training subsystem, user-defined trainers, and Train tab API."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from imagebaker.training import (
    default_pipeline_graph,
    load_trainers,
    validate_and_compile_pipeline,
)
from imagebaker.web.engine import WebAppEngine
from imagebaker.web.server import STATIC_DIR, create_http_server
from tests.web_test_helpers import create_sample_image


def test_load_trainers_and_pipeline_validation():
    trainers_file = Path(__file__).resolve().parent.parent / "examples" / "loaded_trainers.py"
    trainers, augs = load_trainers(trainers_file)
    assert "DummyTrainer" in trainers
    assert "RF-DETR-Detection-Trainer" in trainers
    assert "RF-DETR-Segmentation-Trainer" in trainers
    assert "HorizontalFlip" in augs

    # Valid default pipeline
    pipe = default_pipeline_graph(default_trainer="DummyTrainer")
    ok, msg, compiled = validate_and_compile_pipeline(pipe, trainers)
    assert ok is True, msg
    assert compiled is not None
    assert compiled["trainer_name"] == "DummyTrainer"
    assert len(compiled["augmentations"]) == 1

    # Cycle detection
    cyclic = {
        "nodes": pipe["nodes"],
        "edges": pipe["edges"] + [{"id": "e_cycle", "source": "node_trainer", "target": "node_data"}],
    }
    ok_c, msg_c, _ = validate_and_compile_pipeline(cyclic, trainers)
    assert ok_c is False
    assert "cycle" in msg_c.lower()


def test_training_subprocess_end_to_end_and_load_into_layerify(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    create_sample_image(assets / "img1.png", 120, 100)
    create_sample_image(assets / "img2.png", 120, 100)

    trainers_file = Path(__file__).resolve().parent.parent / "examples" / "loaded_trainers.py"
    engine = WebAppEngine(
        models_file=None,
        project_dir=str(tmp_path),
        trainers_file=str(trainers_file),
    )

    cat = engine.get_training_catalog()
    assert "DummyTrainer" in cat["trainers"]
    assert "finetune" in cat["trainers"]["DummyTrainer"]["supported_regimes"]
    assert "full" in cat["trainers"]["DummyTrainer"]["supported_regimes"]
    assert "few_shot" in cat["trainers"]["DummyTrainer"]["supported_regimes"]

    pipe = default_pipeline_graph(default_trainer="DummyTrainer")
    for n in pipe["nodes"]:
        if n["type"] == "trainer":
            n["config"]["training_mode"] = "few_shot"
            n["config"]["epochs"] = 3
            n["config"]["step_delay_sec"] = 0.02

    ok, msg, run_id = engine.start_training(pipe)
    assert ok is True, msg
    assert run_id is not None

    # Wait for DummyTrainer subprocess to finish
    deadline = time.time() + 15.0
    status = {}
    while time.time() < deadline:
        status = engine.get_training_status(run_id)
        if not status["is_running"] and status["status"] in ("completed", "failed", "stopped"):
            break
        time.sleep(0.1)

    assert status["status"] == "completed", f"Unexpected status: {status}"
    assert len(status["metrics_history"]) >= 3
    assert status["latest"]["checkpoint_path"] is not None

    # Hot-load trained checkpoint into Layerify
    ok_load, msg_load = engine.load_trained_model_into_layerify(run_id)
    assert ok_load is True, msg_load
    assert engine.current_model_name == f"DummyTrainer:{run_id}"

    # Verify prediction works with the newly loaded trained model
    ok_pred, msg_pred = engine.run_prediction()
    assert ok_pred is True, msg_pred

    # Verify train_cache.json persisted the pipeline and loaded checkpoint, and restores on new engine start
    assert engine.train_cache_file.is_file()
    engine_reloaded = WebAppEngine(
        models_file=None,
        project_dir=str(tmp_path),
        trainers_file=str(trainers_file),
    )
    assert f"DummyTrainer:{run_id}" in engine_reloaded.loaded_models
    ok_reset, _ = engine_reloaded.reset_train_pipeline()
    assert ok_reset is True


def test_train_http_endpoints_and_ui_contract(tmp_path: Path):
    trainers_file = Path(__file__).resolve().parent.parent / "examples" / "loaded_trainers.py"
    engine = WebAppEngine(
        models_file=None,
        project_dir=str(tmp_path),
        trainers_file=str(trainers_file),
    )
    server, port = create_http_server(engine, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(f"{base}/api/train/catalog") as resp:
            cat = json.loads(resp.read().decode("utf-8"))
        assert cat["ok"] is True
        assert "DummyTrainer" in cat["catalog"]["trainers"]

        with urllib.request.urlopen(f"{base}/api/train/pipeline") as resp:
            pipe_res = json.loads(resp.read().decode("utf-8"))
        assert pipe_res["ok"] is True
        assert len(pipe_res["pipeline"]["nodes"]) >= 4
    finally:
        server.shutdown()
        server.server_close()

    # Verify Train tab & ReactFlow-like canvas elements exist in static assets
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="tab-btn-train"' in index_html
    assert 'id="view-train"' in index_html
    assert 'id="train-flow-viewport"' in index_html
    assert 'id="flow-hover-preview"' in index_html
    assert 'id="btn-add-node-baker-data"' in index_html
    assert (STATIC_DIR / "js" / "train_flow.js").is_file()
    assert (STATIC_DIR / "js" / "ui_train.js").is_file()
    assert (STATIC_DIR / "css" / "train.css").is_file()

    # Verify hover simulation preview endpoint works on augmentation node
    pipe = default_pipeline_graph(default_trainer="DummyTrainer")
    preview = engine.preview_pipeline_node(pipe, "node_aug")
    assert preview["ok"] is True
    assert preview["image_b64"].startswith("data:image/png;base64,")
    assert "HorizontalFlip" in preview["applied_augmentations"]
