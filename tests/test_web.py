"""Tests for the standalone cross-platform ImageBaker web application."""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from typer.testing import CliRunner

from imagebaker.cli import app
from imagebaker.web.engine import WebAppEngine
from imagebaker.web.server import create_http_server


def _create_sample_image(path: Path, width: int = 120, height: int = 90) -> Path:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (40, 120, 200)
    cv2.rectangle(img, (15, 15), (80, 65), (20, 220, 80), -1)
    cv2.imwrite(str(path), img)
    return path


def _create_dummy_models_file(path: Path) -> Path:
    code = """
from imagebaker.core.defs import PredictionResult
from imagebaker.models.base_model import (
    BaseDetectionModel,
    DefaultModelConfig,
    ModelType,
)

class DummyDetector(BaseDetectionModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    def predict_boxes(self, image):
        return [
            PredictionResult(
                class_name="detected_obj",
                class_id=0,
                score=0.95,
                rectangle=[15, 15, 50, 40],
            )
        ]

LOADED_MODELS = {
    "DummyDetectionModel": DummyDetector(
        DefaultModelConfig(model_type=ModelType.DETECTION, return_annotated_image=False)
    ),
}
"""
    path.write_text(code.strip(), encoding="utf-8")
    return path


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
    _create_sample_image(img_dir / "sample1.png", 120, 90)
    _create_sample_image(img_dir / "sample2.png", 100, 80)
    models_file = _create_dummy_models_file(tmp_path / "dummy_models.py")

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
    _create_sample_image(img_dir / "test.png", 80, 60)

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
        from urllib.parse import quote

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

        # GET /static/app.js
        with urllib.request.urlopen(f"{base_url}/static/app.js") as resp:
            js = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "applyServerState" in js

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
    _create_sample_image(img_dir / "scene.tiff", 100, 80)
    _create_sample_image(img_dir / "scene.bmp", 100, 80)

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

    # Layerify and add brush drawing states to layer
    ok, _ = engine.layerify_annotations()
    assert ok is True
    layers = engine.get_state()["baker"]["layers"]
    assert len(layers) >= 1
    layers[0]["selected"] = True
    layers[0]["drawing_states"] = [
        {"position": [12, 12], "color": "#ff0000", "size": 6},
        {"position": [18, 18], "color": "#00ff00", "size": 6},
    ]
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


def test_desktop_parity_and_undo_redo(tmp_path: Path):
    """Verify Desktop LayerConfig labels.json cache, BaseLayer.copy(), and AnnotableLayer undo/redo."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from imagebaker.core.configs import CanvasConfig, LayerConfig
    from imagebaker.core.defs import Annotation, Label
    from imagebaker.layers.annotable_layer import AnnotableLayer

    _app = QApplication.instance() or QApplication([])

    cfg = LayerConfig(project_dir=tmp_path)
    canvas_cfg = CanvasConfig(project_dir=tmp_path)
    cfg.load_labels_from_cache()
    assert [lbl.name for lbl in cfg.predefined_labels] == ["Undefined"]
    assert cfg.labels_cache_file.exists()

    cfg.predefined_labels.append(Label("Car", QColor(255, 0, 0)))
    cfg.save_labels_to_cache()

    cfg2 = LayerConfig(project_dir=tmp_path)
    cfg2.load_labels_from_cache()
    assert [lbl.name for lbl in cfg2.predefined_labels] == ["Undefined", "Car"]

    layer = AnnotableLayer(None, cfg, canvas_cfg)
    img = QImage(100, 100, QImage.Format_RGBA8888)
    img.fill(QColor(50, 100, 150))
    layer.set_image(img)
    layer.file_path = tmp_path / "img1.png"

    # Default label when none selected is Undefined
    layer.selected_label = ""
    layer.current_annotation = Annotation(
        annotation_id=1, label="", rectangle=QRectF(10, 10, 30, 30)
    )
    layer.finalize_annotation()
    assert len(layer.annotations) == 1
    assert layer.annotations[0].label == "Undefined"

    # Undo and Redo on img1
    layer.undo()
    assert len(layer.annotations) == 0
    layer.redo()
    assert len(layer.annotations) == 1
    assert layer.annotations[0].label == "Undefined"

    # Switching file_path isolates undo/redo stacks per image
    layer.file_path = tmp_path / "img2.png"
    layer.annotations = []
    layer.undo()
    assert len(layer.annotations) == 0

    # BaseLayer.copy() preserves layer_state
    layer.caption = "test_caption"
    layer.edge_width = 7
    copied_layer = layer.copy()
    assert copied_layer.caption == "test_caption"
    assert copied_layer.edge_width == 7


def test_real_world_workflows_example():
    """Run the 4 real-world end-to-end scenarios from examples/web_workflows_example.py."""
    from examples.web_workflows_example import run_all_scenarios

    run_all_scenarios()


def test_web_layerify_icons_and_layer_deletion(tmp_path: Path):
    """Test thumbnail icons, layer deletion via action and update_baker_layers sync."""
    from PIL import Image as PILImage
    from PySide6.QtCore import QPointF, QRectF
    from imagebaker.core.defs import Annotation
    from imagebaker.web.engine import WebAppEngine

    img_path = tmp_path / "sample.png"
    PILImage.new("RGB", (400, 300), color=(100, 150, 200)).save(str(img_path))

    engine = WebAppEngine(project_dir=tmp_path)
    engine.select_folder(str(tmp_path))

    ann1 = Annotation(
        label="Car",
        rectangle=QRectF(10, 10, 80, 80),
        annotation_id=1,
    )
    ann2 = Annotation(
        label="Person",
        rectangle=QRectF(100, 100, 50, 100),
        annotation_id=2,
    )
    engine.current_annotations = [ann1, ann2]

    # Layerify all annotations
    ok, msg = engine.layerify_annotations()
    assert ok is True
    state = engine.get_state()
    layers = state["baker"]["layers"]
    assert len(layers) == 2

    # Check icons: thumb_url, thumbnail, and image_url must be present
    for lyr in layers:
        assert "thumb_url" in lyr and lyr["thumb_url"]
        assert "thumbnail" in lyr and lyr["thumbnail"]
        assert "image_url" in lyr and lyr["image_url"]
        assert lyr["thumb_url"].startswith("/api/baker/layer-image?")

        # Check rendering png bytes
        cid = state["baker"]["current_canvas_id"]
        png_bytes = engine.get_baker_layer_png_bytes(cid, lyr["layer_id"])
        assert png_bytes is not None
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    # Test get_layer with both int and str
    first_id = layers[0]["layer_id"]
    second_id = layers[1]["layer_id"]
    canvas = engine.current_canvas
    assert canvas.get_layer(first_id) is not None
    assert canvas.get_layer(str(first_id)) is not None
    assert canvas.get_layer(99999) is None

    # Test layer sorting/reordering via order array with string IDs
    ok, msg = engine.reorder_baker_layers({"order": [str(second_id), str(first_id)]})
    assert ok is True
    reordered = engine.get_state()["baker"]["layers"]
    assert reordered[0]["layer_id"] == second_id
    assert reordered[1]["layer_id"] == first_id

    # Test layer sorting/reordering via direction with specific layer_id
    ok, msg = engine.reorder_baker_layers({"direction": "up", "layer_id": str(first_id)})
    assert ok is True
    reordered2 = engine.get_state()["baker"]["layers"]
    assert reordered2[0]["layer_id"] == first_id
    assert reordered2[1]["layer_id"] == second_id

    # Test gizmo transform updates (position, scale_x, scale_y, rotation)
    transform_payload = [
        {
            "layer_id": first_id,
            "position": [150.0, 220.0],
            "scale_x": 1.75,
            "scale_y": 2.25,
            "rotation": 45.0,
        },
        {
            "layer_id": second_id,
        },
    ]
    ok, msg = engine.update_baker_layers(transform_payload, push_undo=True, message="Gizmo transform")
    assert ok is True
    lyr1_state = next(l for l in engine.get_state()["baker"]["layers"] if l["layer_id"] == first_id)
    assert lyr1_state["position"] == [150.0, 220.0]
    assert lyr1_state["scale_x"] == 1.75
    assert lyr1_state["scale_y"] == 2.25
    assert lyr1_state["rotation"] == 45.0

    # Test delete via baker_layer_action with string ID
    ok, msg = engine.baker_layer_action({"action": "delete", "layer_id": str(first_id)})
    assert ok is True
    state = engine.get_state()
    remaining = state["baker"]["layers"]
    assert len(remaining) == 1
    assert remaining[0]["layer_id"] == layers[1]["layer_id"]

    # Test delete via update_baker_layers synchronization (omitted layers are removed)
    ok, msg = engine.update_baker_layers([], push_undo=True, message="Deleted all")
    assert ok is True
    state = engine.get_state()
    assert len(state["baker"]["layers"]) == 0
    assert len(engine.current_canvas.layers) == 0


def test_web_copy_paste_annotations_and_layers(tmp_path: Path):
    """Test copy and paste of annotations (Layerify) and layers (Baker) with offsets and selection."""
    from PIL import Image as PILImage
    from PySide6.QtCore import QPointF, QRectF
    from imagebaker.core.defs import Annotation
    from imagebaker.web.engine import WebAppEngine

    img_path = tmp_path / "copy_paste_test.png"
    PILImage.new("RGB", (500, 400), color=(80, 120, 160)).save(str(img_path))

    engine = WebAppEngine(project_dir=tmp_path)
    engine.select_folder(str(tmp_path))

    # --- 1. Annotation Copy / Paste ---
    ann1 = Annotation(
        label="Box1",
        rectangle=QRectF(20.0, 30.0, 100.0, 60.0),
        selected=True,
        annotation_id=1,
    )
    ann2 = Annotation(
        label="Box2",
        rectangle=QRectF(150.0, 80.0, 70.0, 50.0),
        selected=False,
        annotation_id=2,
    )
    engine.current_annotations = [ann1, ann2]

    # Copy selected annotations
    ok, msg = engine.copy_annotations()
    assert ok is True
    assert len(engine.annotation_clipboard) == 1
    assert engine.annotation_clipboard[0].label == "Box1"

    # Paste copied annotations
    ok, msg = engine.paste_annotations()
    assert ok is True
    assert len(engine.current_annotations) == 3

    # Cloned annotation should be selected; original ones should be deselected
    orig1 = engine.current_annotations[0]
    orig2 = engine.current_annotations[1]
    pasted = engine.current_annotations[2]
    assert orig1.selected is False
    assert orig2.selected is False
    assert pasted.selected is True
    assert pasted.label == "Box1"
    # Position must be offset by +15px
    assert pasted.rectangle.x() == 35.0
    assert pasted.rectangle.y() == 45.0
    assert pasted.rectangle.width() == 100.0
    assert pasted.rectangle.height() == 60.0

    # --- 2. Baker Layer Copy / Paste ---
    # Deselect annotations so layerify_annotations processes all annotations
    for ann in engine.current_annotations:
        ann.selected = False
    ok, msg = engine.layerify_annotations()
    assert ok is True
    canvas = engine.current_canvas
    assert len(canvas.layers) == 3

    # Deselect all and select only layer 0
    for lyr in canvas.layers:
        lyr.selected = False
    canvas.layers[0].selected = True
    orig_pos = QPointF(canvas.layers[0].position.x(), canvas.layers[0].position.y())

    # Copy single selected layer
    ok, msg = engine.baker_layer_action({"action": "copy"})
    assert ok is True
    assert len(canvas.copied_layers) == 1

    # Paste layer
    ok, msg = engine.baker_layer_action({"action": "paste"})
    assert ok is True
    assert len(canvas.layers) == 4

    pasted_lyr = canvas.layers[-1]
    assert pasted_lyr.selected is True
    assert canvas.layers[0].selected is False
    assert pasted_lyr.position.x() == orig_pos.x() + 15.0
    assert pasted_lyr.position.y() == orig_pos.y() + 15.0

    # Multi-layer copy & paste
    canvas.layers[0].selected = True
    canvas.layers[1].selected = True
    canvas.layers[2].selected = False
    canvas.layers[3].selected = False

    pos0 = QPointF(canvas.layers[0].position.x(), canvas.layers[0].position.y())
    pos1 = QPointF(canvas.layers[1].position.x(), canvas.layers[1].position.y())

    ok, msg = engine.baker_layer_action({"action": "copy"})
    assert ok is True
    assert len(canvas.copied_layers) == 2

    ok, msg = engine.baker_layer_action({"action": "paste"})
    assert ok is True
    assert len(canvas.layers) == 6

    # Both newly pasted layers should be selected and offset by +15px
    assert canvas.layers[4].selected is True
    assert canvas.layers[5].selected is True
    assert canvas.layers[0].selected is False
    assert canvas.layers[1].selected is False
    assert canvas.layers[4].position.x() == pos0.x() + 15.0
    assert canvas.layers[4].position.y() == pos0.y() + 15.0
    assert canvas.layers[5].position.x() == pos1.x() + 15.0
    assert canvas.layers[5].position.y() == pos1.y() + 15.0

    # --- 3. Two-layer Grouping and Ungrouping with Individual Annotations & States ---
    # Attempting to group 3 layers must fail (grouping only pairs 2 layers together)
    canvas.layers[0].selected = True
    canvas.layers[1].selected = True
    canvas.layers[2].selected = True
    ok, msg = engine.baker_layer_action({"action": "group"})
    assert ok is False
    assert "Select exactly 2 layers" in msg

    # Select exactly 2 layers to group
    canvas.layers[0].selected = True
    canvas.layers[1].selected = True
    canvas.layers[2].selected = False
    canvas.layers[3].selected = False
    canvas.layers[4].selected = False
    canvas.layers[5].selected = False

    group_lids = [canvas.layers[0].layer_id, canvas.layers[1].layer_id]
    ok, msg = engine.baker_layer_action({"action": "group", "layer_ids": group_lids})
    assert ok is True
    # 6 layers originally - 2 grouped + 1 group = 5 layers
    assert len(canvas.layers) == 5
    grouped_layer = next(lyr for lyr in canvas.layers if len(lyr.layers) >= 2)
    assert len(grouped_layer.layers) == 2
    assert grouped_layer.selected is True

    # Child layers maintain individual annotations, layer_states, and captions
    child0, child1 = grouped_layer.layers[0], grouped_layer.layers[1]
    assert child0.layer_state is not None
    assert child1.layer_state is not None
    assert len(child0.annotations) > 0
    assert len(child1.annotations) > 0

    # Ungroup via explicit "ungroup" action
    ok, msg = engine.baker_layer_action({"action": "ungroup", "layer_id": str(grouped_layer.layer_id)})
    assert ok is True
    # Back to 6 layers
    assert len(canvas.layers) == 6

    # --- 4. Multi-layer Deletion via layer_ids ---
    del_ids = [canvas.layers[0].layer_id, canvas.layers[1].layer_id]
    ok, msg = engine.baker_layer_action({"action": "delete", "layer_ids": del_ids})
    assert ok is True
    assert len(canvas.layers) == 4

    # --- 5. Annotation Multi-Deletion via delete_annotations ---
    assert len(engine.current_annotations) == 3
    ok, msg = engine.delete_annotations(annotation_ids=[engine.current_annotations[0].annotation_id, engine.current_annotations[1].annotation_id])
    assert ok is True
    assert len(engine.current_annotations) == 1


def test_layerify_all_button_with_selected_annotation(tmp_path: Path):
    """
    Ensure 'Layerify All' creates layers from ALL visible annotations
    even if one or more annotations are currently selected.
    """
    from PySide6.QtCore import QRectF
    from imagebaker.core.defs import Annotation

    img_path = _create_sample_image(tmp_path / "sample.png", width=300, height=300)

    engine = WebAppEngine(project_dir=tmp_path)
    engine.select_folder(str(tmp_path))

    ann1 = Annotation(label="Obj1", rectangle=QRectF(10, 10, 50, 50), annotation_id=101, selected=True)
    ann2 = Annotation(label="Obj2", rectangle=QRectF(80, 80, 50, 50), annotation_id=102, selected=False)
    ann3 = Annotation(label="Obj3", rectangle=QRectF(150, 150, 50, 50), annotation_id=103, selected=False)
    engine.current_annotations = [ann1, ann2, ann3]

    # Calling layerify_annotations with default (layerify_all=True) must layerify ALL 3 annotations
    ok, msg = engine.layerify_annotations()
    assert ok is True
    assert len(engine.current_canvas.layers) == 3

    # Reset canvas layers
    engine.current_canvas.layers.clear()

    # Calling with explicit layerify_all=True while ann1 is selected must still layerify all 3
    ok, msg = engine.layerify_annotations(layerify_all=True)
    assert ok is True
    assert len(engine.current_canvas.layers) == 3

    # Reset canvas layers
    engine.current_canvas.layers.clear()

    # Calling with layerify_all=False while ann1 is selected must layerify only the selected annotation (1 layer)
    ok, msg = engine.layerify_annotations(layerify_all=False)
    assert ok is True
    assert len(engine.current_canvas.layers) == 1
    assert "Obj1" in engine.current_canvas.layers[0].layer_name

    # Reset canvas layers
    engine.current_canvas.layers.clear()

    # Calling with explicit annotation_ids must layerify only the specified annotation
    ok, msg = engine.layerify_annotations(annotation_ids=[102])
    assert ok is True
    assert len(engine.current_canvas.layers) == 1
    assert "Obj2" in engine.current_canvas.layers[0].layer_name


if __name__ == "__main__":
    import tempfile

    print("Running ImageBaker Web test suite...")
    test_cli_web_help()
    print("  [PASS] test_cli_web_help")
    with tempfile.TemporaryDirectory() as d1:
        test_web_engine_end_to_end(Path(d1))
    print("  [PASS] test_web_engine_end_to_end")
    with tempfile.TemporaryDirectory() as d2:
        test_http_server_endpoints(Path(d2))
    print("  [PASS] test_http_server_endpoints")
    with tempfile.TemporaryDirectory() as d3:
        test_edge_cases_and_formats(Path(d3))
    print("  [PASS] test_edge_cases_and_formats")
    with tempfile.TemporaryDirectory() as d4:
        test_desktop_parity_and_undo_redo(Path(d4))
    print("  [PASS] test_desktop_parity_and_undo_redo")
    test_real_world_workflows_example()
    print("  [PASS] test_real_world_workflows_example")
    with tempfile.TemporaryDirectory() as d5:
        test_web_layerify_icons_and_layer_deletion(Path(d5))
    print("  [PASS] test_web_layerify_icons_and_layer_deletion")
    with tempfile.TemporaryDirectory() as d6:
        test_web_copy_paste_annotations_and_layers(Path(d6))
    print("  [PASS] test_web_copy_paste_annotations_and_layers")
    with tempfile.TemporaryDirectory() as d7:
        test_layerify_all_button_with_selected_annotation(Path(d7))
    print("  [PASS] test_layerify_all_button_with_selected_annotation")
    print("All tests passed!")
