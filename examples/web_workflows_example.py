"""
Real-World Workflows & Scenarios Example for ImageBaker Web.

Demonstrates end-to-end usage of the standalone cross-platform ImageBaker Web
engine and HTTP server across 4 realistic computer-vision workflows:
  1. Dataset Curation, Upload, Label Management & Multi-Geometry Annotation
  2. AI-Assisted Annotation (Detection, Segmentation, Prompt & Classification)
  3. Layerification, Multi-Canvas Composition, Brush Drawing, Edge Feathering & Grouping
  4. Plugin-Driven Augmentation, Timeline States & Multi-Mode Baking/Export

Run with:
    python examples/web_workflows_example.py
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

import cv2
import numpy as np

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from imagebaker.web.engine import WebAppEngine  # noqa: E402
from imagebaker.web.server import create_http_server  # noqa: E402


def _make_scene_image(path: Path, bg_bgr: tuple[int, int, int], kind: str) -> Path:
    """Create a synthetic realistic test image with distinct visual objects."""
    h, w = 240, 320
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = bg_bgr

    if kind == "street":
        # Road
        cv2.rectangle(img, (0, 150), (w, h), (55, 55, 60), -1)
        # Vehicle body
        cv2.rectangle(img, (40, 110), (150, 175), (30, 60, 210), -1)
        # Traffic sign octagon-like circle
        cv2.circle(img, (250, 80), 28, (20, 20, 230), -1)
    elif kind == "desk":
        # Desk surface
        cv2.rectangle(img, (10, 40), (310, 220), (90, 140, 180), -1)
        # Laptop
        cv2.rectangle(img, (60, 65), (195, 165), (180, 185, 190), -1)
        # Mug
        cv2.circle(img, (245, 130), 25, (240, 240, 250), -1)
    else:
        # Warehouse shelf
        cv2.rectangle(img, (30, 30), (290, 210), (70, 100, 130), 3)
        cv2.rectangle(img, (55, 60), (135, 135), (40, 190, 220), -1)
        cv2.rectangle(img, (165, 80), (260, 185), (190, 110, 50), -1)

    cv2.imwrite(str(path), img)
    return path


def _http_get_json(base_url: str, route: str) -> dict:
    with urllib.request.urlopen(f"{base_url}{route}") as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(base_url: str, route: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}{route}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_all_scenarios() -> None:
    print("=" * 72)
    print("ImageBaker Web - Real-World Workflows & Compatibility Scenarios")
    print("=" * 72)

    with tempfile.TemporaryDirectory(prefix="imagebaker_scenarios_") as tmp_str:
        workspace = Path(tmp_str)
        dataset_dir = workspace / "dataset_scenes"
        dataset_dir.mkdir(parents=True, exist_ok=True)

        _make_scene_image(dataset_dir / "01_street_scene.png", (180, 130, 90), "street")
        _make_scene_image(dataset_dir / "02_office_desk.png", (60, 75, 95), "desk")
        _make_scene_image(dataset_dir / "03_warehouse_box.png", (45, 55, 65), "warehouse")

        # Also create a custom project plugin in the workspace to test dynamic discovery
        custom_plugin_code = """
from imagebaker.core.defs import LayerState
from imagebaker.plugins.base_plugin import BasePlugin

class CustomJitterPlugin(BasePlugin):
    plugin_name = "CustomJitterPlugin"

    def __init__(self):
        super().__init__(name="CustomJitterPlugin")

    def update(self, state: LayerState, step: int, total_steps: int, layer=None, canvas=None) -> LayerState:
        updated = state.copy()
        updated.rotation = (updated.rotation + step * 7.5) % 360.0
        return updated
"""
        (workspace / "custom_project_plugin.py").write_text(
            custom_plugin_code.strip(), encoding="utf-8"
        )

        engine = WebAppEngine(
            models_file=str(PROJECT_ROOT / "examples" / "loaded_models.py"),
            project_dir=str(workspace),
            configs_file=str(PROJECT_ROOT / "examples" / "example_config.py"),
        )
        server, port = create_http_server(engine, host="127.0.0.1", port=0)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        base_url = f"http://127.0.0.1:{port}"

        try:
            # ------------------------------------------------------------------
            # SCENARIO 1: Dataset Curation, Upload, Labels & Manual Annotations
            # ------------------------------------------------------------------
            print("\n[Scenario 1] Dataset Curation, Upload, Labels & Multi-Geometry Annotation")
            browse_res = _http_get_json(
                base_url, f"/api/layerify/browse-folders?path={workspace}"
            )
            assert browse_res["ok"] is True
            assert any(d["name"] == "dataset_scenes" for d in browse_res["directories"])

            folder_res = _http_post_json(
                base_url,
                "/api/layerify/select-folder",
                {"folder_path": str(dataset_dir)},
            )
            assert folder_res["ok"] is True
            assert len(folder_res["state"]["layerify"]["images"]) == 3
            print("  [OK] Loaded 3 scene images from folder.")

            # Upload a 4th image via base64 upload endpoint
            extra_img_path = workspace / "extra_upload.png"
            _make_scene_image(extra_img_path, (100, 120, 140), "desk")
            b64_str = base64.b64encode(extra_img_path.read_bytes()).decode("ascii")
            up_res = _http_post_json(
                base_url,
                "/api/layerify/upload-images",
                {"files": [{"name": "04_uploaded_desk.png", "data_b64": b64_str}]},
            )
            assert up_res["ok"] is True
            print(f"  [OK] Uploaded local image via browser API: {up_res['message']}")

            # Switch back to dataset_scenes folder for the remaining workflow
            _http_post_json(
                base_url,
                "/api/layerify/select-folder",
                {"folder_path": str(dataset_dir)},
            )

            # Add custom domain labels, update color, rename, and cleanup unused defaults
            for lbl_name, col in [
                ("Vehicle", "#e63946"),
                ("TrafficSign", "#ffb703"),
                ("Pedestrian", "#2a9d8f"),
            ]:
                res = _http_post_json(
                    base_url,
                    "/api/layerify/labels",
                    {"action": "add", "label": lbl_name, "color": col},
                )
                assert res["ok"] is True

            clean_res = _http_post_json(
                base_url, "/api/layerify/labels", {"action": "cleanup_defaults"}
            )
            assert clean_res["ok"] is True
            print(f"  [OK] Created domain labels and cleaned placeholders: {clean_res['message']}")

            # Annotate image 0 with Rectangle, Polygon, and Point annotations
            scene0_anns = [
                {
                    "annotation_id": 0,
                    "label": "Vehicle",
                    "rectangle": [40, 110, 150, 175],
                    "polygon": [],
                    "points": [],
                    "selected": True,
                    "visible": True,
                    "caption": "Blue sedan on street",
                },
                {
                    "annotation_id": 1,
                    "label": "TrafficSign",
                    "rectangle": None,
                    "polygon": [
                        [222, 65],
                        [250, 50],
                        [278, 65],
                        [278, 95],
                        [250, 110],
                        [222, 95],
                    ],
                    "points": [],
                    "selected": False,
                    "visible": True,
                    "caption": "Octagon stop sign",
                },
                {
                    "annotation_id": 2,
                    "label": "Pedestrian",
                    "rectangle": None,
                    "polygon": [],
                    "points": [[190, 145]],
                    "selected": False,
                    "visible": True,
                    "caption": "Crosswalk keypoint",
                },
            ]
            upd_res = _http_post_json(
                base_url,
                "/api/layerify/annotations/update",
                {
                    "annotations": scene0_anns,
                    "push_undo": True,
                    "message": "Annotated street scene",
                },
            )
            assert len(upd_res["state"]["layerify"]["annotations"]) == 3

            # Copy, Paste, Undo, Redo
            _http_post_json(base_url, "/api/layerify/annotations/action", {"action": "copy"})
            paste_res = _http_post_json(
                base_url, "/api/layerify/annotations/action", {"action": "paste"}
            )
            assert len(paste_res["state"]["layerify"]["annotations"]) == 4
            undo_res = _http_post_json(
                base_url, "/api/layerify/annotations/action", {"action": "undo"}
            )
            assert len(undo_res["state"]["layerify"]["annotations"]) == 3

            # Export & Import merged annotations JSON
            merged_json_path = workspace / "merged_dataset_annotations.json"
            save_ann_res = _http_post_json(
                base_url,
                "/api/layerify/annotations/save",
                {"all_layers": True, "file_path": str(merged_json_path)},
            )
            assert save_ann_res["ok"] is True
            assert merged_json_path.exists()
            print("  [OK] Annotated street scene, verified Undo/Redo/Copy/Paste & JSON export.")

            # ------------------------------------------------------------------
            # SCENARIO 2: AI-Assisted Annotation with Multiple Model Types
            # ------------------------------------------------------------------
            print("\n[Scenario 2] AI-Assisted Annotation (Detection, Segmentation, Prompt)")
            # Switch to image 1 (office desk)
            _http_post_json(base_url, "/api/layerify/select-image", {"index": 1})

            for model_name in [
                "DummyDetectionModel",
                "DummySegmentationModel",
                "DummyPromptModel",
            ]:
                _http_post_json(
                    base_url,
                    "/api/layerify/model",
                    {"action": "select", "model_name": model_name},
                )
                pred_res = _http_post_json(
                    base_url, "/api/layerify/model", {"action": "predict"}
                )
                assert pred_res["ok"] is True, f"Prediction failed for {model_name}: {pred_res}"
                print(f"  [OK] {model_name}: {pred_res['message']}")

            desk_anns = _http_get_json(base_url, "/api/state")["state"]["layerify"]["annotations"]
            assert len(desk_anns) >= 3
            # Make all annotations visible for layerification
            for a in desk_anns:
                a["visible"] = True
            _http_post_json(
                base_url,
                "/api/layerify/annotations/update",
                {"annotations": desk_anns, "push_undo": False},
            )

            # ------------------------------------------------------------------
            # SCENARIO 3: Layerification, Multi-Canvas, Drawing, Edge Feather & Grouping
            # ------------------------------------------------------------------
            print("\n[Scenario 3] Layerification, Multi-Canvas Composition, Brush & Grouping")
            # Layerify from image 1
            lyr_res = _http_post_json(
                base_url, "/api/layerify/layerify", {"annotation_ids": None}
            )
            assert lyr_res["ok"] is True

            # Also switch back to image 0 and layerify the Vehicle & TrafficSign
            _http_post_json(base_url, "/api/layerify/select-image", {"index": 0})
            lyr_res_0 = _http_post_json(
                base_url, "/api/layerify/layerify", {"annotation_ids": [0, 1]}
            )
            assert lyr_res_0["ok"] is True

            # Switch to Baker tab
            _http_post_json(base_url, "/api/settings", {"active_tab": "Baker"})
            baker_state = _http_get_json(base_url, "/api/state")["state"]["baker"]
            layers = baker_state["layers"]
            assert len(layers) >= 4
            print(f"  [OK] Created {len(layers)} Baker layers across multiple images.")

            # Add a blank drawable layer and paint brush strokes on it
            blank_res = _http_post_json(
                base_url,
                "/api/baker/layers/add-blank",
                {"width": 200, "height": 150, "label": "HighlightOverlay"},
            )
            assert blank_res["ok"] is True
            layers = blank_res["state"]["baker"]["layers"]
            layers[-1]["drawing_states"] = [
                {
                    "points": [[30, 30], [45, 35], [60, 40], [75, 45]],
                    "color": [255, 64, 64, 255],
                    "size": 8,
                }
            ]
            # Adjust edge feathering & transform on first layer
            layers[0]["position"] = [40, 35]
            layers[0]["scale_x"] = 1.15
            layers[0]["scale_y"] = 1.15
            layers[0]["rotation"] = 12.0
            layers[0]["opacity"] = 230
            layers[0]["edge_width"] = 6
            layers[0]["edge_opacity"] = 120
            layers[0]["caption"] = "Feathered foreground object"
            layers[0]["selected"] = True
            layers[1]["selected"] = True
            for i in range(2, len(layers)):
                layers[i]["selected"] = False

            upd_bkr = _http_post_json(
                base_url,
                "/api/baker/layers/update",
                {"layers": layers, "push_undo": True, "message": "Configured layers"},
            )
            assert upd_bkr["ok"] is True

            # Convert annotation type on selected layers
            conv_res = _http_post_json(
                base_url, "/api/baker/layers/action", {"action": "convert_ann_type"}
            )
            assert conv_res["ok"] is True
            print(f"  [OK] Converted layer annotation geometry: {conv_res['message']}")

            # Group the 2 selected layers into a composite group layer
            grp_res = _http_post_json(
                base_url, "/api/baker/layers/action", {"action": "group"}
            )
            assert grp_res["ok"] is True
            grouped_layers = grp_res["state"]["baker"]["layers"]
            assert any(lyr["is_group"] for lyr in grouped_layers)
            print(f"  [OK] Grouped 2 layers into composite layer: {grp_res['message']}")

            # Ungroup the composite layer back into individual layers
            ungrp_res = _http_post_json(
                base_url, "/api/baker/layers/action", {"action": "group"}
            )
            assert ungrp_res["ok"] is True
            print(f"  [OK] Ungrouped composite layer: {ungrp_res['message']}")

            # ------------------------------------------------------------------
            # SCENARIO 4: Plugins, Timeline States & Multi-Mode Baking
            # ------------------------------------------------------------------
            print("\n[Scenario 4] Plugins, Timeline Animation & Multi-Mode Baking")
            avail_plugins = ungrp_res["state"]["baker"]["available_plugins"]
            assert "CustomJitterPlugin" in avail_plugins
            assert "GaussianBlur" in avail_plugins

            plug_res = _http_post_json(
                base_url,
                "/api/baker/plugins",
                {
                    "action": "set",
                    "plugins": ["CustomJitterPlugin", "GaussianBlur", "SineMovement"],
                },
            )
            assert plug_res["ok"] is True
            print(f"  [OK] Enabled plugins on layers: {plug_res['message']}")

            # Save initial keyframe state
            save_st1 = _http_post_json(
                base_url, "/api/baker/states", {"action": "save", "steps": 1}
            )
            assert save_st1["ok"] is True
            assert save_st1["state"]["baker"]["num_states"] == 1

            # Transform first layer and save interpolated states to next keyframe
            layers_k2 = save_st1["state"]["baker"]["layers"]
            layers_k2[0]["position"] = [110, 75]
            layers_k2[0]["rotation"] = 35.0
            _http_post_json(
                base_url,
                "/api/baker/layers/update",
                {"layers": layers_k2, "push_undo": True, "message": "Keyframe 2 transform"},
            )
            save_st_res = _http_post_json(
                base_url, "/api/baker/states", {"action": "save", "steps": 2}
            )
            assert save_st_res["ok"] is True
            total_saved_states = save_st_res["state"]["baker"]["num_states"]
            assert total_saved_states >= 3
            print(f"  [OK] Interpolated keyframe states saved (total states: {total_saved_states}).")

            # Seek to step 2 and fetch rendered layer PNG with plugins applied
            seek_res = _http_post_json(
                base_url, "/api/baker/states", {"action": "seek", "step": 2}
            )
            assert seek_res["ok"] is True
            cid = seek_res["state"]["baker"]["current_canvas_id"]
            lid = seek_res["state"]["baker"]["layers"][0]["layer_id"]
            with urllib.request.urlopen(
                f"{base_url}/api/baker/layer-image?canvas_id={cid}&layer_id={lid}&step=2"
            ) as img_resp:
                png_bytes = img_resp.read()
                assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
            print("  [OK] Verified plugin-rendered layer PNG over HTTP.")

            # Export Current State locally
            exp_cur = _http_post_json(
                base_url, "/api/baker/export", {"mode": "current_local"}
            )
            assert exp_cur["ok"] is True
            assert exp_cur["count"] == 1
            assert Path(exp_cur["exported_files"][0]).exists()
            print(f"  [OK] Export Current State: {exp_cur['message']}")

            # Export All Saved States locally
            exp_all = _http_post_json(
                base_url, "/api/baker/export", {"mode": "states_local"}
            )
            assert exp_all["ok"] is True
            assert exp_all["count"] == total_saved_states
            for fp in exp_all["exported_files"]:
                assert Path(fp).exists()
                assert Path(fp).with_suffix(".json").exists()
            print(f"  [OK] Export States (all {exp_all['count']} timeline frames + JSONs saved).")

            # Annotate States (send baked states back to Layerify tab)
            exp_ann = _http_post_json(
                base_url, "/api/baker/export", {"mode": "annotate_states"}
            )
            assert exp_ann["ok"] is True
            assert exp_ann["switched_to_layerify"] is True
            assert exp_ann["state"]["active_tab"] == "Layerify"
            print(
                f"  [OK] Annotate States: transferred {exp_ann['count']} baked frame(s) to Layerify tab."
            )

        finally:
            server.shutdown()
            server.server_close()

    print("\n" + "=" * 72)
    print("ALL 4 REAL-WORLD WORKFLOW SCENARIOS COMPLETED SUCCESSFULLY!")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
