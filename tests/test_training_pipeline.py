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
    # Post-training Eval & Visualize should have generated val/test prediction images
    assert isinstance(status.get("eval_images"), list)
    assert len(status["eval_images"]) >= 1
    first_eval = status["eval_images"][0]
    assert first_eval["url"].startswith("/api/train/eval-image?")

    # Hot-load trained checkpoint into Layerify
    ok_load, msg_load = engine.load_trained_model_into_layerify(run_id)
    assert ok_load is True, msg_load
    assert engine.current_model_name == f"DummyTrainer:{run_id}"

    # Verify on-demand eval visualization also succeeds
    eval_res = engine.run_eval_visualization(run_id=run_id, split="val", max_samples=2)
    assert eval_res["ok"] is True
    assert len(eval_res["eval_images"]) >= 1

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
    assert 'id="btn-add-node-eval"' in index_html
    assert 'id="train-eval-gallery"' in index_html
    assert 'id="eval-lightbox-modal"' in index_html
    assert 'id="btn-train-clear-logs"' in index_html
    assert 'id="select-train-log-lines"' in index_html
    assert 'id="tab-btn-compare"' in index_html
    assert 'id="view-compare"' in index_html
    assert (STATIC_DIR / "js" / "ui_compare.js").is_file()
    assert (STATIC_DIR / "css" / "compare.css").is_file()


def test_baker_exact_saved_states_and_data_counts(tmp_path: Path):
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
    assert cat["data_counts"]["layerify_images"] == 2
    assert cat["data_counts"]["baker_states"] == 0

    # Selecting Baker source with 0 saved states must fail cleanly with a clear error message
    baker_pipe = default_pipeline_graph(default_trainer="DummyTrainer")
    for n in baker_pipe["nodes"]:
        if n["type"] == "data_source":
            n["config"]["source"] = "baker"
            n["config"]["export_format"] = "coco"
        elif n["type"] == "trainer":
            n["config"]["epochs"] = 1
            n["config"]["step_delay_sec"] = 0.01

    ok0, msg0, _ = engine.start_training(baker_pipe)
    assert ok0 is False
    assert "baker" in msg0.lower()

    # Now create a canvas, add a blank layer, and save 2 timeline states
    engine.manage_canvas({"action": "create", "name": "BakeCanvas", "width": 128, "height": 128})
    engine.add_blank_layer(width=64, height=64, label="Sprite")
    engine.manage_states({"action": "save", "steps": 1})
    engine.manage_states({"action": "save", "steps": 1})

    cat2 = engine.get_training_catalog()
    assert cat2["data_counts"]["baker_states"] == 2

    # Baker-only training now succeeds using ONLY those 2 exact saved states with custom run_name
    ok1, msg1, run_id = engine.start_training(baker_pipe, run_name="baker_dummy_ep1")
    assert ok1 is True, msg1
    assert run_id == "baker_dummy_ep1"

    manifest_file = engine.project_dir / ".imagebaker" / "runs" / "_staging_dataset" / "dataset_manifest.json"
    assert manifest_file.is_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["baker_states_used"] == 2
    assert manifest["layerify_images_used"] == 0
    assert sum(manifest["counts"].values()) == 2

    # Verify COCO category IDs match annotation category_id values (1-based, RF-DETR compatible)
    train_coco = json.loads(
        (engine.project_dir / ".imagebaker" / "runs" / "_staging_dataset" / "train" / "_annotations.coco.json").read_text(
            encoding="utf-8"
        )
    )
    cat_ids = {c["id"] for c in train_coco["categories"]}
    assert all(cid >= 1 for cid in cat_ids)
    for ann in train_coco["annotations"]:
        assert ann["category_id"] in cat_ids

    # Wait for completion
    deadline = time.time() + 10.0
    while time.time() < deadline:
        st = engine.get_training_status(run_id)
        if not st["is_running"] and st["status"] in ("completed", "failed", "stopped"):
            break
        time.sleep(0.1)
    assert st["status"] == "completed"

    # Verify saved run pipeline can be restored and run can be deleted
    saved_pipe = engine.get_training_run_pipeline(run_id)
    assert saved_pipe is not None and len(saved_pipe.get("nodes", [])) >= 4
    ok_del, msg_del = engine.delete_training_run(run_id)
    assert ok_del is True, msg_del
    assert all(r["run_id"] != run_id for r in engine.get_training_status()["runs"])


def test_training_roi_cropping_and_baker_predict_popup(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    create_sample_image(assets / "scene.png", 200, 160)

    trainers_file = Path(__file__).resolve().parent.parent / "examples" / "loaded_trainers.py"
    engine = WebAppEngine(
        models_file=None,
        project_dir=str(tmp_path),
        trainers_file=str(trainers_file),
    )

    # Add ROI label box [x1, y1, x2, y2] = [40, 30, 140, 110] (100x80) + Insect box [60, 50, 80, 70] (20x20)
    engine.manage_labels({"action": "add", "label": "TrapROI", "color": [0, 255, 0]})
    engine.manage_labels({"action": "add", "label": "Insect", "color": [255, 0, 0]})
    engine.update_annotations(
        [
            {"annotation_id": 1, "label": "TrapROI", "rectangle": [40, 30, 140, 110], "visible": True},
            {"annotation_id": 2, "label": "Insect", "rectangle": [60, 50, 80, 70], "visible": True},
        ],
        push_undo=False,
    )

    pipe = default_pipeline_graph(default_trainer="DummyTrainer")
    for n in pipe["nodes"]:
        if n["type"] == "data_source":
            n["config"]["source"] = "layerify"
            n["config"]["export_format"] = "coco"
            n["config"]["roi_labels"] = ["TrapROI"]
            n["config"]["roi_padding"] = 0
        elif n["type"] == "split_filter":
            n["config"]["selected_labels"] = ["Insect"]
        elif n["type"] == "trainer":
            n["config"]["epochs"] = 1
            n["config"]["step_delay_sec"] = 0.01

    ok, msg, compiled = engine.validate_train_pipeline(pipe)
    assert ok is True, msg
    ds_dir = tmp_path / "roi_staged"
    engine._prepare_training_dataset(compiled, ds_dir)
    manifest = json.loads((ds_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["roi_labels"] == ["TrapROI"]

    train_coco = json.loads((ds_dir / "train" / "_annotations.coco.json").read_text(encoding="utf-8"))
    assert len(train_coco["images"]) == 1
    assert train_coco["images"][0]["width"] == 100
    assert train_coco["images"][0]["height"] == 80
    assert len(train_coco["annotations"]) == 1
    # Insect box (60, 50, 20, 20) shifted by ROI origin (40, 30) -> (20, 20, 20, 20)
    assert [int(round(v)) for v in train_coco["annotations"][0]["bbox"]] == [20, 20, 20, 20]

    # Baker interactive Predict State popup workflow (prepare -> discard -> prepare -> commit)
    engine.manage_canvas({"action": "create", "name": "PredCanvas", "width": 120, "height": 100})
    engine.add_blank_layer(width=64, height=64, label="Obj")

    prep = engine.prepare_baker_predict_state()
    assert prep["ok"] is True
    assert prep["image_b64"].startswith("data:image/png;base64,")

    ok_disc, _ = engine.discard_baker_predict_state()
    assert ok_disc is True
    assert len(engine.image_entries) == 1  # untouched on discard

    prep2 = engine.prepare_baker_predict_state()
    assert prep2["ok"] is True
    ok_com, _ = engine.commit_baker_predict_state(include_predictions=True)
    assert ok_com is True
    assert len(engine.image_entries) == 2  # moved to Layerify
    assert engine.active_tab == "Layerify"
