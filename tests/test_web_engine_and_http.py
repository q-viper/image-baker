"""Tests for ImageBaker web CLI, WebAppEngine lifecycle, HTTP endpoints, and formats."""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typer.testing import CliRunner

from imagebaker.cli import app
from imagebaker.web.engine import WebAppEngine
from imagebaker.web.server import create_http_server
from tests.web_test_helpers import create_dummy_models_file, create_sample_image


def test_cli_web_help():
    runner = CliRunner()
    result = runner.invoke(app, ["web", "--help"])
    assert result.exit_code == 0
    assert "Launch the standalone cross-platform ImageBaker web application" in result.output
    assert "--host" in result.output
    assert "--port" in result.output


def test_web_engine_end_to_end(tmp_path: Path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    create_sample_image(img_dir / "sample1.png", 120, 90)
    create_sample_image(img_dir / "sample2.png", 100, 80)
    models_file = create_dummy_models_file(tmp_path / "dummy_models.py")

    engine = WebAppEngine(
        models_file=str(models_file),
        project_dir=str(tmp_path),
        configs_file=None,
    )
    initial_labels = [item["name"] for item in engine.get_state()["layerify"]["labels"]]
    assert initial_labels == ["Undefined"]
    labels_cache_path = tmp_path / ".imagebaker" / "cache" / "labels.json"
    assert labels_cache_path.exists()

    # 1. Select folder & check loaded images
    ok, _msg = engine.select_folder(str(img_dir))
    assert ok is True
    state = engine.get_state()
    assert len(state["layerify"]["images"]) == 2
    assert state["layerify"]["current_image_index"] == 0

    # 2. Add annotations, undo/redo, copy/paste
    anns = [
        {
            "annotation_id": 1,
            "label": "BoxObj",
            "rectangle": [10, 10, 60, 50],
            "polygon": [],
            "points": [],
            "selected": True,
            "visible": True,
            "color": [255, 0, 0],
            "caption": "first box",
        },
        {
            "annotation_id": 2,
            "label": "PolyObj",
            "rectangle": None,
            "polygon": [[20, 20], [70, 20], [70, 60], [20, 60]],
            "points": [],
            "selected": False,
            "visible": True,
            "color": [0, 255, 0],
            "caption": "",
        },
    ]
    engine.update_annotations(anns, push_undo=True, message="Added 2 annotations")
    assert len(engine.get_state()["layerify"]["annotations"]) == 2

    ok, _ = engine.copy_annotations()
    assert ok is True
    ok, _ = engine.paste_annotations()
    assert ok is True
    assert len(engine.get_state()["layerify"]["annotations"]) == 3

    ok, _ = engine.undo_annotation()
    assert ok is True
    assert len(engine.get_state()["layerify"]["annotations"]) == 2
    ok, _ = engine.redo_annotation()
    assert ok is True
    assert len(engine.get_state()["layerify"]["annotations"]) == 3

    # 3. Save & Load annotations
    save_file = tmp_path / "saved_anns.json"
    save_res = engine.export_annotations_json(all_layers=True, file_path=str(save_file))
    assert save_res["ok"] is True
    assert save_file.exists()

    ok, _ = engine.clear_all_annotations_and_layers()
    assert ok is True
    assert len(engine.get_state()["layerify"]["annotations"]) == 0

    ok, _ = engine.import_annotations_json(all_layers=True, file_path=str(save_file))
    assert ok is True
    assert len(engine.get_state()["layerify"]["annotations"]) == 3

    # 4. Label management & labels.json cache persistence
    ok, _ = engine.manage_labels({"action": "add", "label": "CustomLabel", "color": [12, 34, 56]})
    assert ok is True
    cached_labels = json.loads(labels_cache_path.read_text(encoding="utf-8"))
    assert any(item["name"] == "CustomLabel" for item in cached_labels)

    ok, _ = engine.manage_labels(
        {"action": "rename", "old_label": "CustomLabel", "new_label": "RenamedLabel"}
    )
    assert ok is True
    labels = {item["name"] for item in engine.get_state()["layerify"]["labels"]}
    assert "RenamedLabel" in labels
    cached_labels = json.loads(labels_cache_path.read_text(encoding="utf-8"))
    assert any(item["name"] == "RenamedLabel" for item in cached_labels)

    # 5. Model prediction assigns currently selected label (or Undefined if none selected)
    engine.current_model_name = "DummyDetectionModel"
    engine.manage_labels({"action": "select", "label": "RenamedLabel"})
    ok, _ = engine.run_prediction()
    assert ok is True
    cur_anns = engine.get_state()["layerify"]["annotations"]
    assert len(cur_anns) >= 4
    assert cur_anns[-1]["label"] == "RenamedLabel"

    # Deselect label -> defaults to Undefined on prediction
    engine.manage_labels({"action": "select", "label": ""})
    assert engine.get_state()["layerify"]["selected_label"] == "Undefined"
    ok, _ = engine.run_prediction()
    assert ok is True
    cur_anns = engine.get_state()["layerify"]["annotations"]
    assert cur_anns[-1]["label"] == "Undefined"

    ok, _ = engine.manage_labels({"action": "delete", "label": "RenamedLabel"})
    assert ok is True
    for a in cur_anns:
        a["visible"] = True
    engine.update_annotations(cur_anns, push_undo=False)

    # 6. Layerify annotations into Baker canvas
    ok, _ = engine.layerify_annotations()
    assert ok is True
    bkr_layers = engine.get_state()["baker"]["layers"]
    assert len(bkr_layers) >= 2

    # 7. Baker layer operations: select, reorder, convert annotation type, group
    bkr_layers[0]["selected"] = True
    engine.update_baker_layers(bkr_layers, push_undo=False)
    ok, _ = engine.reorder_baker_layers({"direction": "up"})
    assert ok is True
    ok, _ = engine.baker_layer_action({"action": "convert_ann_type"})
    assert ok is True

    # Select first two layers and group them
    updated_layers = engine.get_state()["baker"]["layers"]
    for i, lyr in enumerate(updated_layers):
        lyr["selected"] = i < 2
    engine.update_baker_layers(updated_layers, push_undo=True)
    ok, _ = engine.baker_layer_action({"action": "group"})
    assert ok is True

    # 8. States & Plugins & Baking Export
    ok, _ = engine.manage_states({"action": "save", "steps": 1})
    assert ok is True
    ok, _ = engine.manage_states({"action": "randomize", "steps": 2})
    assert ok is True
    assert engine.get_state()["baker"]["num_states"] == 2

    ok, _ = engine.manage_states({"action": "seek", "step": 1})
    assert ok is True

    exp_cur = engine.bake_and_export(mode="current_local")
    assert exp_cur["ok"] is True
    assert len(exp_cur["exported_files"]) == 1
    assert Path(exp_cur["exported_files"][0]).exists()

    exp_states = engine.bake_and_export(mode="states_local")
    assert exp_states["ok"] is True
    assert len(exp_states["exported_files"]) == 2


def test_http_server_endpoints(tmp_path: Path):
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    create_sample_image(img_dir / "test.png", 80, 60)

    engine = WebAppEngine(
        models_file=None,
        project_dir=str(tmp_path),
        configs_file=None,
    )
    engine.select_folder(str(img_dir))

    server, port = create_http_server(engine, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    try:
        # GET /
        with urllib.request.urlopen(f"{base_url}/") as resp:
            html = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "ImageBaker" in html
            assert "btn-top-theme" in html
            assert "ls-label-bar" in html
            assert "strip-mode-rectangle" in html
            assert "btn-layerify-all" in html
            assert "layerify-loading-overlay" in html
            assert 'id="dock-layerify-tools"' not in html
            assert 'id="strip-btn-layerify"' not in html
            assert 'id="btn-insp-bake"' not in html

        # GET /api/layerify/browse-folders (verify images list & quick_paths)
        with urllib.request.urlopen(
            f"{base_url}/api/layerify/browse-folders?path={quote(str(img_dir))}"
        ) as resp:
            browse_data = json.loads(resp.read().decode("utf-8"))
            assert browse_data["ok"] is True
            assert browse_data["image_count"] == 1
            assert len(browse_data["images"]) == 1
            assert browse_data["images"][0]["name"] == "test.png"
            assert isinstance(browse_data["quick_paths"], list)
            assert len(browse_data["quick_paths"]) >= 1
            for qp in browse_data["quick_paths"]:
                assert qp.get("name") and qp["name"] != "undefined"
                assert qp.get("label") == qp.get("name")
                assert qp.get("path")

        # GET all modularized CSS & JS static assets referenced from index.html
        static_paths = [
            "/static/styles.css",
            "/static/css/workspace.css",
            "/static/css/panels.css",
            "/static/css/modals_and_help.css",
            "/static/js/canvas_layerify_masks.js",
            "/static/js/canvas_layerify_render.js",
            "/static/js/canvas_layerify.js",
            "/static/js/ui_layerify_modals.js",
            "/static/js/ui_layerify.js",
            "/static/app.js",
        ]
        for asset_path in static_paths:
            with urllib.request.urlopen(f"{base_url}{asset_path}") as resp:
                body = resp.read().decode("utf-8")
                assert resp.status == 200
                assert len(body.strip()) > 0

        # GET /api/state
        with urllib.request.urlopen(f"{base_url}/api/state") as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            assert payload["ok"] is True
            assert len(payload["state"]["layerify"]["images"]) == 1

        # GET /api/layerify/image?index=0
        with urllib.request.urlopen(f"{base_url}/api/layerify/image?index=0") as resp:
            img_bytes = resp.read()
            assert resp.status == 200
            assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"

        # POST /api/baker/layers/add-blank
        req = urllib.request.Request(
            f"{base_url}/api/baker/layers/add-blank",
            data=json.dumps({"width": 64, "height": 64, "label": "BlankTest"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            assert payload["ok"] is True
            assert len(payload["state"]["baker"]["layers"]) == 1

        # GET /api/baker/layer-image
        cid = payload["state"]["baker"]["current_canvas_id"]
        lid = payload["state"]["baker"]["layers"][0]["layer_id"]
        with urllib.request.urlopen(
            f"{base_url}/api/baker/layer-image?canvas_id={cid}&layer_id={lid}"
        ) as resp:
            layer_png = resp.read()
            assert resp.status == 200
            assert layer_png[:8] == b"\x89PNG\r\n\x1a\n"

        # POST /api/layerify/annotations/update with multiple annotations (one selected)
        anns_update = [
            {"label": "A1", "rectangle": [5, 5, 20, 20], "annotation_id": 1, "selected": True, "visible": True},
            {"label": "A2", "rectangle": [30, 30, 20, 20], "annotation_id": 2, "selected": False, "visible": True},
        ]
        req = urllib.request.Request(
            f"{base_url}/api/layerify/annotations/update",
            data=json.dumps({"annotations": anns_update}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            assert payload["ok"] is True
            assert len(payload["state"]["layerify"]["annotations"]) == 2

        # POST /api/layerify/layerify with all=True (Layerify All button behavior)
        # It must layerify ALL visible annotations into Baker layers, not just the selected one
        prev_layers_count = len(payload["state"]["baker"]["layers"])
        req = urllib.request.Request(
            f"{base_url}/api/layerify/layerify",
            data=json.dumps({"all": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            assert payload["ok"] is True
            assert len(payload["state"]["baker"]["layers"]) == prev_layers_count + 2
    finally:
        server.shutdown()
        server.server_close()


def test_edge_cases_and_formats(tmp_path: Path):
    """Test multi-format images (TIFF/BMP), brush mask baking, predict_state, and all built-in plugins."""
    img_dir = tmp_path / "multi_format"
    img_dir.mkdir()
    create_sample_image(img_dir / "scene.tiff", 100, 80)
    create_sample_image(img_dir / "scene.bmp", 100, 80)

    # Create models file with binary mask segmentation + classification + detection
    models_code = """
import numpy as np
from imagebaker.core.defs import PredictionResult
from imagebaker.models.base_model import (
    BaseClassificationModel,
    BaseDetectionModel,
    BaseSegmentationModel,
    DefaultModelConfig,
    ModelType,
)

class BinaryMaskSegModel(BaseSegmentationModel):
    def predict_mask(self, image):
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[10:min(h - 5, 50), 10:min(w - 5, 60)] = 255
        return [PredictionResult(class_name="bin_mask_obj", class_id=0, score=0.91, mask=mask)]

class SimpleClassModel(BaseClassificationModel):
    def predict_class(self, image):
        return [PredictionResult(class_name="scene_class", class_id=1, score=0.88)]

class SimpleDetModel(BaseDetectionModel):
    def predict_boxes(self, image):
        return [PredictionResult(class_name="baked_det", class_id=0, score=0.95, rectangle=[10, 10, 40, 30])]

LOADED_MODELS = {
    "BinaryMaskSegModel": BinaryMaskSegModel(DefaultModelConfig(model_type=ModelType.SEGMENTATION)),
    "SimpleClassModel": SimpleClassModel(DefaultModelConfig(model_type=ModelType.CLASSIFICATION)),
    "SimpleDetModel": SimpleDetModel(DefaultModelConfig(model_type=ModelType.DETECTION)),
}
"""
    models_file = tmp_path / "edge_models.py"
    models_file.write_text(models_code.strip(), encoding="utf-8")

    engine = WebAppEngine(
        models_file=str(models_file),
        project_dir=str(tmp_path),
        configs_file=None,
    )
    ok, _ = engine.select_folder(str(img_dir))
    assert ok is True
    assert len(engine.get_state()["layerify"]["images"]) == 2

    # Verify BMP and TIFF images are served properly (TIFF converted to PNG)
    bmp_res = engine.get_layerify_image_bytes(0)
    assert bmp_res is not None and bmp_res[1] == "image/bmp" and len(bmp_res[0]) > 0
    tiff_res = engine.get_layerify_image_bytes(1)
    assert (
        tiff_res is not None
        and tiff_res[1] == "image/png"
        and tiff_res[0][:8] == b"\x89PNG\r\n\x1a\n"
    )

    # Run BinaryMaskSegModel and SimpleClassModel
    engine.current_model_name = "BinaryMaskSegModel"
    ok, _ = engine.run_prediction()
    assert ok is True

    engine.current_model_name = "SimpleClassModel"
    ok, _ = engine.run_prediction()
    assert ok is True

    anns = engine.get_state()["layerify"]["annotations"]
    assert len(anns) >= 2
    for a in anns:
        a["visible"] = True
    engine.update_annotations(anns, push_undo=False)

    # Single-layer JSON save/load
    single_json = tmp_path / "single_layer.json"
    res_single = engine.export_annotations_json(all_layers=False, file_path=str(single_json))
    assert res_single["ok"] is True
    assert single_json.exists()

    # Layerify and add brush drawing states to layer (separate layers so upper full-image class layer doesn't bury layer 0)
    ok, _ = engine.layerify_annotations()
    assert ok is True
    layers = engine.get_state()["baker"]["layers"]
    assert len(layers) >= 1
    layers[0]["selected"] = True
    layers[0]["position"] = [380, 300]
    layers[0]["drawing_states"] = [
        {"position": [12, 12], "color": "#ff0000", "size": 6},
        {"position": [18, 18], "color": "#00ff00", "size": 6},
    ]
    if len(layers) >= 2:
        layers[1]["position"] = [560, 300]
    engine.update_baker_layers(layers, push_undo=True)

    # Enable all built-in plugins (GaussianBlur, PerspectiveTransform, SineMovement, SmokeSim)
    ok, _ = engine.manage_plugins(
        {
            "action": "set",
            "plugins": ["GaussianBlur", "PerspectiveTransform", "SineMovement", "SmokeSim"],
        }
    )
    assert ok is True

    # Save states and verify brush annotation is exported
    engine.manage_states({"action": "save", "steps": 1})
    exp = engine.bake_and_export(mode="current_local")
    assert exp["ok"] is True
    exported_json = Path(exp["exported_files"][0]).with_suffix(".json")
    assert exported_json.exists()
    saved_baked_anns = json.loads(exported_json.read_text(encoding="utf-8"))
    assert any(a["label"].endswith("_brush") for a in saved_baked_anns)

    # Test predict_state mode (bakes current state & sends it to Layerify tab)
    engine.current_model_name = "SimpleDetModel"
    pred_state_res = engine.bake_and_export(mode="predict_state")
    assert pred_state_res["ok"] is True
    assert pred_state_res["switched_to_layerify"] is True
    assert engine.get_state()["layerify"]["current_image"]["is_baked_result"] is True
    ok, _ = engine.run_prediction()
    assert ok is True
    assert any(a["label"] == "Undefined" for a in engine.get_state()["layerify"]["annotations"])


def test_web_remove_image_skip_download_and_logs(tmp_path):
    """Verify Layerify image list removal endpoint and Web skip-download & log UI contracts."""
    from imagebaker.web.server import STATIC_DIR

    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    create_sample_image(assets / "img_one.png", 64, 64)
    create_sample_image(assets / "img_two.png", 64, 64)
    models_file = create_dummy_models_file(tmp_path / "dummy_models.py")

    engine = WebAppEngine(models_file=str(models_file), project_dir=str(tmp_path))
    assert len(engine.image_entries) == 2

    # Remove first image via engine
    ok, msg = engine.remove_image(0)
    assert ok is True
    assert "img_one.png" in msg
    assert len(engine.image_entries) == 1
    assert engine.image_entries[0].file_path.name == "img_two.png"
    assert (assets / "img_one.png").exists()  # File on disk is untouched

    # Remove remaining image via HTTP POST
    server, port = create_http_server(engine, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/layerify/remove-image",
            data=json.dumps({"index": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["ok"] is True
        assert payload["state"]["layerify"]["images"] == []
    finally:
        server.shutdown()
        server.server_close()

    # Verify skip-download handler, web log drawer, and image remove button exist in static files
    ui_baker_js = (STATIC_DIR / "js" / "ui_baker.js").read_text(encoding="utf-8")
    assert "btn-baker-export-skip" in ui_baker_js
    assert "runExport(true)" in ui_baker_js

    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="web-log-drawer"' in index_html
    assert 'id="btn-toggle-logs"' in index_html

    state_js = (STATIC_DIR / "js" / "state.js").read_text(encoding="utf-8")
    assert "appendLog" in state_js
    assert "console.info" in state_js

    ui_layerify_js = (STATIC_DIR / "js" / "ui_layerify.js").read_text(encoding="utf-8")
    assert "api.removeImage" in ui_layerify_js


def test_native_shrinkable_panels_image_removal_and_plugins(tmp_path):
    """Verify native AnnotationList shrinkability, Layerify image removal, and BakerTab plugins."""
    from PySide6.QtWidgets import QApplication, QCheckBox, QMainWindow

    from imagebaker.core.configs import CanvasConfig, LayerConfig
    from imagebaker.tabs.baker_tab import BakerTab
    from imagebaker.tabs.layerify_tab import LayerifyTab

    _app = QApplication.instance() or QApplication([])
    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    create_sample_image(assets / "native_a.png", 80, 60)
    create_sample_image(assets / "native_b.png", 80, 60)

    win = QMainWindow()
    lcfg = LayerConfig(assets_dir=assets, cache_dir=tmp_path / "cache", bake_dir=tmp_path / "bake")
    ccfg = CanvasConfig(export_folder=tmp_path / "exports", cache_dir=tmp_path / "baker_cache")

    layerify = LayerifyTab(win, lcfg, ccfg, [])
    # Rightmost AnnotationList panel must be able to shrink well below 260px
    assert layerify.annotation_list.minimumWidth() <= 160
    assert layerify.annotation_list.minimumSizeHint().width() <= 240

    initial_count = len(layerify.image_entries)
    assert initial_count >= 2
    first_entry = layerify.image_entries[0]
    layerify.remove_image_entry(first_entry)
    assert len(layerify.image_entries) == initial_count - 1
    assert first_entry not in layerify.image_entries

    baker = BakerTab(win, ccfg)
    assert baker.layer_settings.minimumWidth() <= 180
    assert len(baker.plugin_actions) >= 1
    assert all(isinstance(w, QCheckBox) for w in baker.plugin_actions.values())

    initial_layers = len(baker.current_canvas.layers)
    baker.add_blank_layer()
    assert len(baker.current_canvas.layers) == initial_layers + 1
    for lyr in baker.current_canvas.layers[:-1]:
        lyr.selected = False
    target_layer = baker.current_canvas.layers[-1]
    target_layer.selected = True

    first_plugin_name = sorted(baker.plugin_actions)[0]
    baker.plugin_actions[first_plugin_name].setChecked(True)
    assert len(target_layer.plugins) == 1
    assert "(1)" in baker.plugin_dropdown_btn.text()

    baker.sync_plugin_menu_with_selection([])
    assert baker.plugin_actions[first_plugin_name].isChecked() is False

    baker.sync_plugin_menu_with_selection([target_layer])
    assert baker.plugin_actions[first_plugin_name].isChecked() is True

    baker.clear_plugin_selection()
    assert target_layer.plugins == []

