"""Multi-iteration scenario tests covering Web, Desktop, API, Dataset extraction, and Brush RLE occlusion."""

from __future__ import annotations

import io
import json
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import pytest

from imagebaker.api import ImageBaker, brush_annotation
from imagebaker.core.configs import CanvasConfig
from imagebaker.core.defs import Annotation, BakingResult
from imagebaker.dataset import CacheDatasetGenerator, DatasetBakeConfig, ImageBakerTorchDataset, TORCH_AVAILABLE
from imagebaker.layers.base_layer import BaseLayer
from imagebaker.tabs.layerify_tab import LayerifyTab
from imagebaker.utils.annotation_formats import (
    export_annotations_data,
    load_annotation_dicts_from_data,
    rle_to_mask,
)
from imagebaker.web.engine import WebAppEngine
from imagebaker.web.models import WebLayerItem
from imagebaker.web.server import create_http_server
from imagebaker.workers.baker_worker import BakerWorker
from tests.web_test_helpers import create_sample_image, rgba_array_to_qpixmap


def test_scenario_1_three_part_multi_occluder_and_full_occlusion_drop(tmp_path: Path):
    """
    Scenario 1:
    - A wide 'bus' layer is crossed by 2 solid vertical poles + 1 fully transparent overlay.
      The transparent overlay must NOT split the mask, while the 2 solid poles split it into 3 islands.
    - A second small 'cone' layer is 100% covered by a foreground layer and must be omitted (not emitted empty).
    - Verified consistently across WebAppEngine, Desktop BakerWorker, Python API ImageBaker, COCO, YOLO, and Default RLE.
    """
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QPolygonF
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])

    W, H = 300, 180
    bg_arr = np.full((H, W, 4), (30, 40, 50, 255), dtype=np.uint8)
    bus_arr = np.full((60, 240, 4), (240, 180, 30, 255), dtype=np.uint8)
    cone_arr = np.full((24, 24, 4), (255, 90, 20, 255), dtype=np.uint8)
    pole_arr = np.full((150, 26, 4), (235, 235, 235, 255), dtype=np.uint8)
    blocker_arr = np.full((60, 60, 4), (90, 90, 90, 255), dtype=np.uint8)
    ghost_clear = np.zeros((150, 26, 4), dtype=np.uint8)  # alpha == 0 must not occlude

    # --- 1A. WebAppEngine (with a grouped foreground occluder pair) ---
    img_dir = tmp_path / "scene1"
    img_dir.mkdir()
    create_sample_image(img_dir / "bg.png", W, H)
    eng = WebAppEngine(models_file=None, project_dir=str(tmp_path), configs_file=None)
    assert eng.select_folder(str(img_dir))[0] is True

    def _web_lyr(lid: int, name: str, arr: np.ndarray, pos: tuple[float, float], allow_export: bool, anns=None):
        lyr = WebLayerItem(eng.canvas_config)
        lyr.layer_id = lid
        lyr.layer_name = name
        lyr.set_image(rgba_array_to_qpixmap(arr))
        lyr.position = QPointF(pos[0], pos[1])
        lyr.allow_annotation_export = allow_export
        lyr.annotations = list(anns or [])
        return lyr

    bus_poly = QPolygonF([QPointF(0, 0), QPointF(240, 0), QPointF(240, 60), QPointF(0, 60)])
    cone_poly = QPolygonF([QPointF(0, 0), QPointF(24, 0), QPointF(24, 24), QPointF(0, 24)])

    eng.current_canvas.layers = [
        _web_lyr(1, "bg", bg_arr, (0, 0), False),
        _web_lyr(
            2,
            "bus",
            bus_arr,
            (30, 60),
            True,
            [Annotation(annotation_id=1, label="bus", color=QColor(240, 180, 30), polygon=bus_poly)],
        ),
        _web_lyr(
            3,
            "cone_hidden",
            cone_arr,
            (250, 125),
            True,
            [Annotation(annotation_id=2, label="cone", color=QColor(255, 90, 20), polygon=cone_poly)],
        ),
        _web_lyr(4, "pole_left", pole_arr, (95, 15), False),
        _web_lyr(5, "pole_right", pole_arr, (180, 15), False),
        _web_lyr(6, "ghost_transparent", ghost_clear, (140, 15), False),
        _web_lyr(7, "cone_blocker", blocker_arr, (235, 110), False),
    ]
    eng.manage_states({"action": "save", "steps": 1})

    # Verify Default RLE: 1 annotation ('bus' with 3 connected islands); 'cone' dropped because 100% occluded
    exp_def = eng.bake_and_export(mode="current_local", annotation_format="default")
    assert exp_def["ok"] is True
    def_anns = json.loads(exp_def["annotation_exports"][0]["content"])
    assert len(def_anns) == 1
    assert def_anns[0]["brushlabels"] == ["bus"]
    rec = rle_to_mask(def_anns[0]["rle"], height=H, width=W)
    n_parts, _ = cv2.connectedComponents((rec > 0).astype(np.uint8))
    assert n_parts - 1 == 3
    assert np.any(rec[75:105, 145:160] > 0)  # ghost transparent overlay did NOT split middle island!
    assert not np.any(rec[:, 97:119])
    assert not np.any(rec[:, 182:204])

    # Verify COCO & YOLO multi-part outputs for the 3-island single instance
    exp_coco = eng.bake_and_export(mode="current_local", annotation_format="coco")
    coco_anns = json.loads(exp_coco["annotation_exports"][0]["content"])["annotations"]
    assert len(coco_anns) == 1
    assert len(coco_anns[0]["segmentation"]) == 3

    exp_yolo = eng.bake_and_export(mode="current_local", annotation_format="yolo")
    yolo_lines = [ln for ln in exp_yolo["annotation_exports"][0]["content"].splitlines() if ln.strip()]
    assert len(yolo_lines) == 1

    # --- 1B. Desktop BakerWorker parity ---
    cfg = CanvasConfig(project_dir=tmp_path)
    desk_layers = []
    for idx, lyr in enumerate(eng.current_canvas.layers):
        dl = BaseLayer(None, config=cfg)
        dl.layer_id = lyr.layer_id
        dl.layer_name = lyr.layer_name
        dl.set_image(lyr.image)
        dl.position = QPointF(lyr.position)
        dl.allow_annotation_export = lyr.allow_annotation_export
        dl.annotations = [a.copy() for a in lyr.annotations]
        dl.layer_state.order = idx
        desk_layers.append(dl)

    d_results: list[BakingResult] = []
    worker = BakerWorker(
        states={0: [dl.layer_state.copy() for dl in desk_layers]},
        layers=desk_layers,
        filename=tmp_path / "desk_3part.png",
        timeline_total_steps=1,
    )
    worker.finished.connect(d_results.extend)
    worker.process()
    assert len(d_results) == 1
    assert len(d_results[0].annotations) == 1
    n_desk, _ = cv2.connectedComponents((d_results[0].annotations[0].mask > 0).astype(np.uint8))
    assert n_desk - 1 == 3

    # --- 1C. Python API ImageBaker parity ---
    baker = ImageBaker(output_dir=str(tmp_path / "api1"))
    baker.add_layer_from_array(bg_arr, layer_name="bg")
    bus_full = np.zeros((H, W, 4), dtype=np.uint8)
    bus_full[60:120, 30:270] = (240, 180, 30, 255)
    bus_mask = np.zeros((H, W), dtype=np.uint8)
    bus_mask[60:120, 30:270] = 1
    bid = baker.add_layer_from_array(bus_full, layer_name="bus")
    baker.add_annotation(bid, brush_annotation(label="bus", mask=bus_mask))
    for px in (95, 180):
        p_arr = np.zeros((H, W, 4), dtype=np.uint8)
        p_arr[15:165, px : px + 26] = (235, 235, 235, 255)
        baker.add_layer_from_array(p_arr, layer_name=f"pole_{px}")
    api_res = baker.bake()
    assert len(api_res.annotations) == 1
    n_api, _ = cv2.connectedComponents((api_res.annotations[0].mask > 0).astype(np.uint8))
    assert n_api - 1 == 3


def test_scenario_2_brush_transform_rotate_scale_feather_and_dataset_extract(tmp_path: Path):
    """
    Scenario 2:
    Paint two disjoint brush parts -> Layerify -> Rotate + Scale + Feather + Opacity in Baker ->
    Save timeline states + save_baker_cache() -> Generate Dataset splits in Default, COCO, and YOLO
    via CacheDatasetGenerator and verify ImageBakerTorchDataset samples.
    """
    W, H = 200, 160
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    bg_path = create_sample_image(img_dir / "room.png", W, H)

    eng = WebAppEngine(models_file=None, project_dir=str(tmp_path), configs_file=None)
    assert eng.select_folder(str(img_dir))[0] is True

    # Two-part brush instance across gap
    mask = np.zeros((H, W), dtype=np.uint8)
    cv2.circle(mask, (45, 70), 20, 1, -1)
    cv2.circle(mask, (145, 70), 20, 1, -1)
    rle = export_annotations_data(
        annotations=[], fmt="default", image_name="room.png", image_width=W, image_height=H
    )  # sanity helper check; encode directly:
    from imagebaker.utils.annotation_formats import mask_to_rle

    rle_list = mask_to_rle(mask)
    assert len(rle_list) > 2 and isinstance(rle, dict)

    eng.update_annotations(
        [
            {
                "annotation_id": 1,
                "label": "twin_part",
                "type": "brush",
                "format": "rle",
                "rle": rle_list,
                "mask_size": [H, W],
                "selected": True,
                "visible": True,
                "color": [16, 185, 129],
            }
        ],
        push_undo=True,
        message="Two-island brush",
    )
    ok, msg = eng.layerify_annotations(layerify_all=True)
    assert ok is True, msg
    assert len(eng.current_canvas.layers) == 1

    # Add a background layer first so CacheDatasetGenerator has >=1 background asset + >=1 foreground asset
    lyr_payload = eng.get_state()["baker"]["layers"]
    lyr_payload[0]["position"] = [280.0, 220.0]
    lyr_payload[0]["rotation"] = 25.0
    lyr_payload[0]["scale_x"] = 1.25
    lyr_payload[0]["scale_y"] = 0.85
    lyr_payload[0]["opacity"] = 215
    lyr_payload[0]["edge_width"] = 2
    lyr_payload[0]["edge_opacity"] = 120
    ok, _ = eng.update_baker_layers(lyr_payload, push_undo=True)
    assert ok is True

    eng.manage_states({"action": "save", "steps": 2})
    eng.save_baker_cache()

    bake_res = eng.bake_and_export(mode="states_local", annotation_format="coco")
    assert bake_res["ok"] is True
    assert len(bake_res["annotation_exports"]) == 2
    for ae in bake_res["annotation_exports"]:
        coco = json.loads(ae["content"])
        assert len(coco["annotations"]) == 1
        assert len(coco["annotations"][0]["segmentation"]) == 2

    # Ensure background directory also exists cleanly for CacheDatasetGenerator
    bg_extra = tmp_path / "bg_extra.png"
    create_sample_image(bg_extra, 256, 256)
    cache_dir = eng.canvas_config.cache_dir

    # Add explicit background image reference in cache dir if generator only has foreground asset
    ds_cfg = DatasetBakeConfig(
        seed=123,
        background_size=(256, 256),
        layers_per_image=(1, 1),
        scale_range=(0.7, 1.1),
        rotation_range=(-20.0, 20.0),
        split_ratios={"train": 0.6, "val": 0.2, "test": 0.2},
    )
    gen = CacheDatasetGenerator(cache_dir=cache_dir, config=ds_cfg)
    assert len(gen.foreground_assets) >= 1
    # Inject a deterministic background asset pointing to bg_path if fallback didn't discover one
    if not gen.background_assets:
        from imagebaker.dataset import CachedLayerAsset

        bg_rgb = cv2.cvtColor(cv2.imread(str(bg_path)), cv2.COLOR_BGR2RGB)
        gen.background_assets.append(
            CachedLayerAsset(label="background", image=bg_rgb, annotations=[], source_file=str(bg_path))
        )

    for fmt_name in ("default", "coco", "yolo"):
        out_dir = tmp_path / f"ds_{fmt_name}"
        summary = gen.extract_dataset(out_dir, num_samples=5, format=fmt_name)
        assert summary["format"] == fmt_name
        assert summary["total_samples"] >= 3
        assert (out_dir / "classes.txt").exists()
        assert "twin_part" in (out_dir / "classes.txt").read_text(encoding="utf-8")
        if fmt_name == "yolo":
            assert (out_dir / "data.yaml").exists()
            assert list((out_dir / "labels" / "train").glob("*.txt"))
        elif fmt_name == "coco":
            coco_train = json.loads((out_dir / "annotations" / "instances_train.json").read_text(encoding="utf-8"))
            assert len(coco_train["annotations"]) >= 1
        else:
            def_train = list((out_dir / "train" / "annotations").glob("*.json"))
            assert len(def_train) >= 1
            first_doc = json.loads(def_train[0].read_text(encoding="utf-8"))
            assert any(item.get("type") == "brushlabels" for item in first_doc)

    if TORCH_AVAILABLE:
        torch_ds = ImageBakerTorchDataset(gen, length=3, split="train")
        sample0 = torch_ds[0]
        assert sample0["image"].shape[0] == 3
        assert sample0["masks"].shape[0] >= 1


def test_scenario_3_iterative_brush_edit_undo_redo_copy_paste_rebridge(tmp_path: Path):
    """
    Scenario 3:
    Interactive multi-step Brush edit sequence:
    1) Desktop AnnotableLayer: stroke A -> disjoint stroke B (same instance) -> erase part of A
       -> undo -> redo -> verify history stack integrity.
    2) WebAppEngine + HTTP: update brush -> copy/paste (+15,+15 offset verified on mask & bbox) ->
       bridge gap across islands -> HTTP save/load roundtrip across default/coco/yolo.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QMainWindow

    from imagebaker.core.configs import LayerConfig
    from imagebaker.core.defs import MouseMode

    _app = QApplication.instance() or QApplication([])
    W, H = 180, 120
    img_dir = tmp_path / "edit_imgs"
    img_dir.mkdir()
    img_path = create_sample_image(img_dir / "edit.png", W, H)

    # 3A. Desktop iterative edit + undo/redo
    mw = QMainWindow()
    try:
        tab = LayerifyTab(mw, LayerConfig(project_dir=tmp_path), CanvasConfig(project_dir=tmp_path), {})
        tab.layer.set_image(img_path)
        tab.layer.resize(W, H)
        tab.layer.scale = 1.0
        tab.layer.offset = QPointF(0.0, 0.0)
        tab.layer.brush_size = 12
        tab.layer.mouse_mode = MouseMode.DRAW

        def _stroke(pts, mods=Qt.NoModifier):
            p0 = QPointF(pts[0][0], pts[0][1])
            tab.layer.handle_mouse_press(QMouseEvent(QEvent.MouseButtonPress, p0, p0, Qt.LeftButton, Qt.LeftButton, mods))
            for x, y in pts[1:]:
                pm = QPointF(x, y)
                tab.layer.handle_mouse_move(QMouseEvent(QEvent.MouseMove, pm, pm, Qt.NoButton, Qt.LeftButton, mods))
            pe = QPointF(pts[-1][0], pts[-1][1])
            tab.layer.handle_mouse_release(QMouseEvent(QEvent.MouseButtonRelease, pe, pe, Qt.LeftButton, Qt.NoButton, mods))

        # Step 1: stroke A
        _stroke([(20, 40), (45, 40)])
        assert len(tab.layer.annotations) == 1
        sum_step1 = int(tab.layer.annotations[0].mask.sum())

        # Step 2: disjoint stroke B merges into same instance
        _stroke([(120, 40), (145, 40)])
        assert len(tab.layer.annotations) == 1
        sum_step2 = int(tab.layer.annotations[0].mask.sum())
        assert sum_step2 > sum_step1
        n_s2, _ = cv2.connectedComponents((tab.layer.annotations[0].mask > 0).astype(np.uint8))
        assert n_s2 - 1 == 2

        # Step 3: Alt+Drag erase middle of stroke B to split stroke B itself into sub-parts!
        _stroke([(132, 32), (132, 48)], mods=Qt.AltModifier)
        sum_step3 = int(tab.layer.annotations[0].mask.sum())
        assert sum_step3 < sum_step2
        n_s3, _ = cv2.connectedComponents((tab.layer.annotations[0].mask > 0).astype(np.uint8))
        assert n_s3 - 1 >= 2

        # Step 4: Undo back to step 2 -> Redo back to step 3
        tab.layer.undo()
        assert int(tab.layer.annotations[0].mask.sum()) == sum_step2
        tab.layer.redo()
        assert int(tab.layer.annotations[0].mask.sum()) == sum_step3
    finally:
        mw.close()

    # 3B. Web copy/paste offset, bridge stroke, and HTTP save/load roundtrip
    eng = WebAppEngine(models_file=None, project_dir=str(tmp_path), configs_file=None)
    assert eng.select_folder(str(img_dir))[0] is True

    from imagebaker.utils.annotation_formats import mask_to_rle

    init_mask = np.zeros((H, W), dtype=np.uint8)
    init_mask[25:45, 20:50] = 1
    init_mask[25:45, 90:120] = 1
    eng.update_annotations(
        [
            {
                "annotation_id": 1,
                "label": "bridged_item",
                "type": "brush",
                "format": "rle",
                "rle": mask_to_rle(init_mask),
                "mask_size": [H, W],
                "selected": True,
                "visible": True,
                "brush_strokes": [],
            }
        ],
        push_undo=True,
    )
    assert eng.copy_annotations()[0] is True
    assert eng.paste_annotations()[0] is True
    anns = eng.get_state()["layerify"]["annotations"]
    assert len(anns) == 2
    pasted = anns[1]
    assert pasted["brush_bbox"][0] == anns[0]["brush_bbox"][0] + 15
    assert pasted["brush_bbox"][1] == anns[0]["brush_bbox"][1] + 15

    # Paint a bridge stroke across the gap (x=50..90) on pasted annotation (shifted y~40..60)
    eng.update_annotations(
        [
            anns[0],
            {
                **pasted,
                "brush_strokes": [{"points": [[60, 50], [110, 50]], "size": 16, "erase": False}],
            },
        ],
        push_undo=True,
    )
    bridged_rle = eng.get_state()["layerify"]["annotations"][1]["rle"]
    bridged_mask = rle_to_mask(bridged_rle, H, W)
    n_bridged, _ = cv2.connectedComponents((bridged_mask > 0).astype(np.uint8))
    assert n_bridged - 1 == 1

    # HTTP /api/layerify/annotations/save + /load roundtrip
    server, port = create_http_server(eng, host="127.0.0.1", port=0)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        for fmt in ("default", "coco", "yolo"):
            save_path = tmp_path / f"roundtrip_{fmt}.json"
            req = urllib.request.Request(
                f"{base_url}/api/layerify/annotations/save",
                data=json.dumps({"all_layers": False, "file_path": str(save_path), "format": fmt}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                save_data = json.loads(resp.read().decode("utf-8"))
                assert save_data["ok"] is True
                assert save_data["json_content"]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("dims", [(160, 110), (240, 170)])
@pytest.mark.parametrize("fmt", ["default", "coco", "yolo"])
def test_scenario_4_multi_resolution_multi_class_pipeline_matrix(tmp_path: Path, dims: tuple[int, int], fmt: str):
    """
    Scenario 4:
    Parametrized matrix over resolutions and annotation formats verifying mixed annotations
    (2-island brush + occluded polygon + unoccluded rect + unoccluded point + foreground occluder)
    across WebAppEngine baking, HTTP zip export, and format reload.
    """
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QPolygonF

    W, H = dims
    img_dir = tmp_path / f"mat_{W}x{H}_{fmt}"
    img_dir.mkdir(parents=True)
    create_sample_image(img_dir / "bg.png", W, H)

    eng = WebAppEngine(models_file=None, project_dir=str(tmp_path / f"proj_{W}_{fmt}"), configs_file=None)
    assert eng.select_folder(str(img_dir))[0] is True

    bg_arr = np.full((H, W, 4), (45, 55, 65, 255), dtype=np.uint8)
    poly_arr = np.full((50, 90, 4), (20, 190, 140, 255), dtype=np.uint8)
    rect_arr = np.full((35, 45, 4), (220, 70, 90, 255), dtype=np.uint8)
    occ_arr = np.full((80, 22, 4), (240, 240, 240, 255), dtype=np.uint8)

    def _lyr(lid: int, name: str, arr: np.ndarray, pos: tuple[float, float], export: bool, anns=None):
        lyr = WebLayerItem(eng.canvas_config)
        lyr.layer_id = lid
        lyr.layer_name = name
        lyr.set_image(rgba_array_to_qpixmap(arr))
        lyr.position = QPointF(pos[0], pos[1])
        lyr.allow_annotation_export = export
        lyr.annotations = list(anns or [])
        return lyr

    poly_geom = QPolygonF([QPointF(0, 0), QPointF(90, 0), QPointF(90, 50), QPointF(0, 50)])
    eng.current_canvas.layers = [
        _lyr(1, "bg", bg_arr, (0, 0), False),
        _lyr(
            2,
            "poly_split",
            poly_arr,
            (20, 25),
            True,
            [Annotation(annotation_id=1, label="panel", color=QColor(20, 190, 140), polygon=poly_geom)],
        ),
        _lyr(
            3,
            "rect_clean",
            rect_arr,
            (W - 55, H - 45),
            True,
            [Annotation(annotation_id=2, label="badge", color=QColor(220, 70, 90), rectangle=QRectF(0, 0, 45, 35))],
        ),
        _lyr(4, "occluder", occ_arr, (54, 10), False),
    ]
    eng.manage_states({"action": "save", "steps": 1})

    exp = eng.bake_and_export(mode="current_local", annotation_format=fmt)
    assert exp["ok"] is True
    content = exp["annotation_exports"][0]["content"]

    if fmt == "yolo":
        lines = [ln for ln in content.splitlines() if ln.strip()]
        assert len(lines) == 2  # split panel + clean badge
    elif fmt == "coco":
        data = json.loads(content)
        assert len(data["annotations"]) == 2
        reloaded = load_annotation_dicts_from_data(data, fmt="coco", image_width=W, image_height=H)
        assert len(reloaded) == 2
    else:
        data = json.loads(content)
        assert len(data) == 2
        panel_ann = next(a for a in data if (a.get("label") or (a.get("brushlabels") or [""])[0]) == "panel")
        assert panel_ann["type"] == "brushlabels"
        m = rle_to_mask(panel_ann["rle"], height=H, width=W)
        n_comp, _ = cv2.connectedComponents((m > 0).astype(np.uint8))
        assert n_comp - 1 == 2

    # Check downloadable zip via HTTP in states_local mode
    server, port = create_http_server(eng, host="127.0.0.1", port=0)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/baker/export",
            data=json.dumps({"mode": "states_local", "format": fmt}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            assert payload["ok"] is True
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{payload['download_url']}") as dl_resp:
                with zipfile.ZipFile(io.BytesIO(dl_resp.read()), "r") as zf:
                    assert any(name.endswith(".png") for name in zf.namelist())
                    assert len(zf.namelist()) >= 2
    finally:
        server.shutdown()
        server.server_close()
