"""Tests for Brush RLE encoding, multi-part instance segmentation, and z-order occlusion."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from imagebaker.web.engine import WebAppEngine
from tests.web_test_helpers import create_sample_image, rgba_array_to_qpixmap


def test_brush_label_rle_layerify_and_baking(tmp_path: Path):
    """Verify Label Studio-compatible RLE brush annotation, moving, erasing, layerifying, and baking."""
    from PySide6.QtGui import QColor
    from imagebaker.core.defs import Annotation
    from imagebaker.utils.annotation_formats import (
        dict_to_annotation,
        export_annotations_data,
        mask_to_rle,
        rle_to_mask,
    )
    from imagebaker.utils.image import qpixmap_to_numpy
    from imagebaker.web.annotation_ops import (
        deserialize_annotation,
        serialize_annotation,
    )

    # 1. RLE lossless encoding & decoding
    h, w = 120, 160
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, (60, 50), 25, 1, -1)
    mask[80:110, 100:140] = 1

    rle = mask_to_rle(mask)
    assert isinstance(rle, list)
    assert len(rle) > 2
    assert sum(rle) == h * w

    decoded = rle_to_mask(rle, h, w)
    assert decoded is not None
    assert np.array_equal(decoded, mask)

    # 2. Label Studio dictionary format compatibility
    ls_payload = {
        "annotation_id": 42,
        "type": "brushlabels",
        "format": "rle",
        "value": {
            "brushlabels": ["CustomBrush"],
            "format": "rle",
            "rle": rle,
            "mask_size": [h, w],
        },
    }
    ann = dict_to_annotation(ls_payload)
    assert ann.label == "CustomBrush"
    assert ann.annotation_id == 42
    assert ann.mask is not None
    assert ann.mask.shape == (h, w)
    assert np.array_equal(ann.mask, mask)

    # 3. JSON Save/Load roundtrip with RLE
    json_path = tmp_path / "brush_annotations.json"
    Annotation.save_as_json([ann], str(json_path))
    loaded_raw = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(loaded_raw) == 1
    assert loaded_raw[0]["type"] == "brushlabels"
    assert loaded_raw[0]["format"] == "rle"
    assert loaded_raw[0]["rle"] == rle
    assert loaded_raw[0]["mask_size"] == [h, w]

    loaded_anns = Annotation.load_from_json(str(json_path))
    assert len(loaded_anns) == 1
    assert loaded_anns[0].label == "CustomBrush"
    assert loaded_anns[0].mask is not None
    assert np.array_equal(loaded_anns[0].mask, mask)

    # 4. Serialize Annotation for Web Client
    serialized = serialize_annotation(ann)
    assert serialized["type"] == "brush"
    assert serialized["has_mask"] is True
    assert serialized["rle"] == rle
    assert serialized["mask_size"] == [h, w]
    assert serialized["mask_png_b64"] is not None
    assert serialized["brush_bbox"] is not None
    # Verify points and polygon are empty for brush
    assert serialized["points"] == []
    assert serialized["polygon"] == []

    # 5. Moving whole brush mask by delta (mask_offset_x, mask_offset_y)
    serialized["mask_offset_x"] = 12
    serialized["mask_offset_y"] = 8
    shifted_ann = deserialize_annotation(serialized, 42, tmp_path / "dummy.png")
    assert shifted_ann.mask is not None
    assert shifted_ann.mask.shape == (h, w)
    assert mask[50, 40] == 1
    assert shifted_ann.mask[50, 40] == 0
    assert shifted_ann.mask[58, 72] == 1

    # 6. Erasing / modifying brush mask with brush_strokes
    erase_data = {
        "annotation_id": 42,
        "type": "brush",
        "rle": rle,
        "mask_size": [h, w],
        "label": "CustomBrush",
        "brush_strokes": [
            {
                "points": [[60, 50]],
                "size": 30,
                "erase": True,
            }
        ],
    }
    erased_ann = deserialize_annotation(erase_data, 42, tmp_path / "dummy.png")
    assert erased_ann.mask is not None
    assert erased_ann.mask[50, 60] == 0

    # 7. Layerifying brush annotation in WebAppEngine
    img_dir = tmp_path / "brush_img_dir"
    img_dir.mkdir()
    sample_img_path = img_dir / "canvas_photo.png"
    photo_np = np.full((120, 160, 3), 180, dtype=np.uint8)
    photo_np[20:70, 30:90] = [255, 100, 50]
    photo_np[70:115, 80:150] = [50, 200, 100]
    cv2.imwrite(str(sample_img_path), photo_np)

    engine = WebAppEngine(models_file=None, project_dir=str(tmp_path), configs_file=None)
    ok, msg = engine.select_folder(str(img_dir))
    assert ok is True

    engine.current_annotations = [
        Annotation(
            annotation_id=1,
            label="BrushPatch",
            color=QColor(220, 50, 50),
            mask=mask.copy(),
            visible=True,
            selected=True,
            is_complete=True,
            file_path=sample_img_path,
        )
    ]

    ok, msg = engine.layerify_annotations()
    assert ok is True, f"Layerify failed: {msg}"
    assert len(engine.current_canvas.layers) >= 1

    brush_layer = engine.current_canvas.layers[-1]
    assert brush_layer.annotations
    assert brush_layer.annotations[0].mask is not None

    layer_arr = qpixmap_to_numpy(brush_layer.image)
    assert layer_arr.shape[2] == 4
    assert np.any(layer_arr[:, :, 3] == 0)
    assert np.any(layer_arr[:, :, 3] > 0)

    # 8. Baker State Baking & Export
    engine.manage_states({"action": "save", "steps": 1})
    bake_res = engine.bake_and_export(mode="current_local")
    assert bake_res["ok"] is True
    assert len(bake_res["exported_files"]) >= 1

    exp_ann_file = Path(bake_res["exported_files"][0]).with_suffix(".json")
    assert exp_ann_file.exists()
    baked_anns_json = json.loads(exp_ann_file.read_text(encoding="utf-8"))
    assert len(baked_anns_json) >= 1
    first_baked = baked_anns_json[0]
    assert first_baked["type"] == "brushlabels" or first_baked.get("rle") is not None

    exp_coco = export_annotations_data(
        annotations=engine.current_canvas.layers[-1].annotations,
        fmt="coco",
        image_name="test.png",
        image_width=160,
        image_height=120,
    )
    assert exp_coco["format"] == "coco"
    assert len(exp_coco["data"]["annotations"]) >= 1
    assert exp_coco["data"]["annotations"][0]["bbox"][2] > 0
    assert exp_coco["data"]["annotations"][0]["bbox"][3] > 0

    exp_yolo = export_annotations_data(
        annotations=engine.current_canvas.layers[-1].annotations,
        fmt="yolo",
        image_name="test.png",
        image_width=160,
        image_height=120,
    )
    assert exp_yolo["format"] == "yolo"
    assert len(exp_yolo["data"]["txt"].strip().splitlines()) >= 1

    # 9. Test Baking directly to Layerify tab (predict_state / Annotate States)
    bake_to_lyr = engine.bake_and_export(mode="predict_state")
    assert bake_to_lyr["ok"] is True
    assert bake_to_lyr["switched_to_layerify"] is True
    assert engine.active_tab == "Layerify"
    assert engine.image_entries[-1].is_baked_result is True


def test_occluded_brush_formats_roundtrip_and_layerify_worker():
    """Verify multi-part occluded Brush RLE/COCO/YOLO roundtrip and LayerifyWorker extraction."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QPixmap, QPolygonF
    from PySide6.QtWidgets import QApplication

    from imagebaker.core.configs import DrawConfig
    from imagebaker.core.defs import Annotation
    from imagebaker.utils.annotation_formats import (
        export_annotations_data,
        load_annotation_dicts_from_data,
        mask_to_rle,
        rle_to_mask,
    )
    from imagebaker.utils.image import qpixmap_to_numpy
    from imagebaker.workers.layerify_worker import LayerifyWorker

    _app = QApplication.instance() or QApplication([])

    two_island_mask = np.zeros((100, 160), dtype=np.uint8)
    two_island_mask[20:70, 15:55] = 1
    two_island_mask[20:70, 95:135] = 1
    expected_area = int(two_island_mask.sum())
    rle = mask_to_rle(two_island_mask)

    src_ann = Annotation(
        annotation_id=1,
        label="occluded_car",
        color=QColor(59, 130, 246),
        mask=two_island_mask,
        selected=True,
        is_complete=True,
    )

    # 1. Default RLE export + reload preserves 2 connected islands
    exp_def = export_annotations_data(
        annotations=[src_ann],
        fmt="default",
        image_name="occ.png",
        image_width=160,
        image_height=100,
    )
    reloaded_def = load_annotation_dicts_from_data(
        exp_def["data"], fmt="default", image_width=160, image_height=100
    )
    assert len(reloaded_def) == 1
    assert reloaded_def[0]["type"] == "brushlabels"
    assert reloaded_def[0]["rle"] == rle
    rec_def = rle_to_mask(reloaded_def[0]["rle"], height=100, width=160)
    n_def, _ = cv2.connectedComponents((rec_def > 0).astype(np.uint8))
    assert n_def - 1 == 2
    assert not np.any(rec_def[20:70, 60:90])

    # 2. COCO multi-polygon export + reload merges islands back into ONE brushlabels RLE annotation
    exp_coco = export_annotations_data(
        annotations=[src_ann],
        fmt="coco",
        image_name="occ.png",
        image_width=160,
        image_height=100,
    )
    coco_anns = exp_coco["data"]["annotations"]
    assert len(coco_anns) == 1
    assert len(coco_anns[0]["segmentation"]) == 2
    assert coco_anns[0]["bbox"][2] >= 118
    assert abs(float(coco_anns[0]["area"]) - float(expected_area)) <= 1.0

    reloaded_coco = load_annotation_dicts_from_data(
        exp_coco["data"], fmt="coco", image_width=160, image_height=100
    )
    assert len(reloaded_coco) == 1
    assert reloaded_coco[0]["type"] == "brushlabels"
    rec_coco = rle_to_mask(reloaded_coco[0]["rle"], height=100, width=160)
    n_coco, _ = cv2.connectedComponents((rec_coco > 0).astype(np.uint8))
    assert n_coco - 1 == 2

    # 3. YOLO bridged export emits 1 line containing coordinates from both left & right islands
    exp_yolo = export_annotations_data(
        annotations=[src_ann],
        fmt="yolo",
        image_name="occ.png",
        image_width=160,
        image_height=100,
    )
    yolo_lines = [ln for ln in exp_yolo["data"]["txt"].splitlines() if ln.strip()]
    assert len(yolo_lines) == 1
    coords = [float(v) for v in yolo_lines[0].split()[1:]]
    xs = coords[0::2]
    assert any(x < 0.35 for x in xs) and any(x > 0.60 for x in xs)

    # 4. LayerifyWorker crops local_ann.mask cleanly & keeps transparent gap + handles polygon & rectangle
    img_arr = np.full((100, 160, 4), (40, 160, 220, 255), dtype=np.uint8)
    pixmap = rgba_array_to_qpixmap(img_arr)

    poly_ann = Annotation(
        annotation_id=2,
        label="sign",
        color=QColor(16, 185, 129),
        polygon=QPolygonF([QPointF(10, 10), QPointF(50, 10), QPointF(50, 40), QPointF(10, 40)]),
    )
    rect_ann = Annotation(
        annotation_id=3,
        label="box",
        color=QColor(239, 68, 68),
        rectangle=QRectF(90, 55, 45, 35),
    )

    captured: list[tuple[Annotation, QPixmap]] = []
    worker = LayerifyWorker(pixmap, [src_ann, poly_ann, rect_ann], DrawConfig())
    worker.finished.connect(lambda ann, pix: captured.append((ann, pix)))
    worker.process()

    assert len(captured) == 3
    loc_brush, brush_pix = captured[0]
    assert loc_brush.mask is not None
    assert loc_brush.rectangle is None
    assert loc_brush.polygon is None
    n_loc, _ = cv2.connectedComponents((loc_brush.mask > 0).astype(np.uint8))
    assert n_loc - 1 == 2
    pix_rgba = qpixmap_to_numpy(brush_pix)
    assert not np.any(pix_rgba[:, 42:78, 3])
    assert np.any(pix_rgba[:, 5:35, 3] > 0)
    assert np.any(pix_rgba[:, 85:115, 3] > 0)

    loc_poly, _ = captured[1]
    assert loc_poly.polygon is not None and len(loc_poly.polygon) == 4
    loc_rect, _ = captured[2]
    assert loc_rect.rectangle is not None and loc_rect.rectangle.x() == 0 and loc_rect.rectangle.y() == 0


def test_desktop_annotable_layer_brush_shortcuts_and_extract(tmp_path: Path):
    """Verify Desktop B/V shortcuts, multi-island brush continuation, Alt+Drag erase, +New, and Extract."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication, QMainWindow

    from imagebaker.core.configs import CanvasConfig, LayerConfig
    from imagebaker.core.defs import MouseMode
    from imagebaker.layers.base_layer import BaseLayer
    from imagebaker.tabs.layerify_tab import LayerifyTab
    from imagebaker.utils.image import qpixmap_to_numpy

    _app = QApplication.instance() or QApplication([])
    img_path = create_sample_image(tmp_path / "scene.png", 160, 100)

    mw = QMainWindow()
    try:
        tab = LayerifyTab(mw, LayerConfig(project_dir=tmp_path), CanvasConfig(project_dir=tmp_path), {})
        tab.layer.set_image(img_path)
        tab.layer.resize(160, 100)
        tab.layer.scale = 1.0
        tab.layer.offset = QPointF(0.0, 0.0)
        tab.layer.brush_size = 14

        ev_b = QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.NoModifier)
        tab.keyPressEvent(ev_b)
        assert tab.layer.mouse_mode == MouseMode.DRAW

        def _stroke(points: list[tuple[float, float]], modifiers=Qt.NoModifier):
            p0 = QPointF(points[0][0] * tab.layer.scale + tab.layer.offset.x(), points[0][1] * tab.layer.scale + tab.layer.offset.y())
            tab.layer.handle_mouse_press(
                QMouseEvent(QEvent.MouseButtonPress, p0, p0, Qt.LeftButton, Qt.LeftButton, modifiers)
            )
            for px, py in points[1:]:
                pm = QPointF(px * tab.layer.scale + tab.layer.offset.x(), py * tab.layer.scale + tab.layer.offset.y())
                tab.layer.handle_mouse_move(
                    QMouseEvent(QEvent.MouseMove, pm, pm, Qt.NoButton, Qt.LeftButton, modifiers)
                )
            pe = QPointF(points[-1][0] * tab.layer.scale + tab.layer.offset.x(), points[-1][1] * tab.layer.scale + tab.layer.offset.y())
            tab.layer.handle_mouse_release(
                QMouseEvent(QEvent.MouseButtonRelease, pe, pe, Qt.LeftButton, Qt.NoButton, modifiers)
            )

        _stroke([(25, 30), (35, 30)])
        assert len(tab.layer.annotations) == 1
        assert tab.layer.annotations[0].selected is True
        assert tab.layer.annotations[0].mask is not None

        _stroke([(115, 30), (125, 30)])
        assert len(tab.layer.annotations) == 1
        merged_mask = tab.layer.annotations[0].mask
        n_comp, _ = cv2.connectedComponents((merged_mask > 0).astype(np.uint8))
        assert n_comp - 1 == 2

        assert tab.layer.find_annotation_at(QPointF(30, 30)) is tab.layer.annotations[0]
        assert tab.layer.find_annotation_at(QPointF(120, 30)) is tab.layer.annotations[0]
        assert tab.layer.find_annotation_at(QPointF(75, 30)) is None
        lbl_pos = tab.layer.get_label_position(tab.layer.annotations[0])
        assert lbl_pos is not None

        before_sum = int(tab.layer.annotations[0].mask.sum())
        _stroke([(28, 30), (32, 30)], modifiers=Qt.AltModifier)
        after_sum = int(tab.layer.annotations[0].mask.sum())
        assert after_sum < before_sum
        assert np.any(tab.layer.annotations[0].mask[:, 110:130])

        tab.start_new_brush_annotation()
        assert tab.layer.annotations[0].selected is False
        _stroke([(30, 75), (45, 75)])
        assert len(tab.layer.annotations) == 2
        assert tab.layer.annotations[1].selected is True

        extracted_payloads = []
        orig_layerify = tab.layer.layerify_annotation
        try:
            tab.layer.layerify_annotation = lambda anns: extracted_payloads.append(list(anns))
            tab.annotation_list.layerify_selected_btn.click()
        finally:
            tab.layer.layerify_annotation = orig_layerify
        assert len(extracted_payloads) == 1
        assert len(extracted_payloads[0]) == 1
        assert extracted_payloads[0][0].annotation_id == tab.layer.annotations[1].annotation_id

        edge_layer = BaseLayer(None, config=CanvasConfig(project_dir=tmp_path))
        rgba = np.full((100, 160, 4), (40, 160, 220, 255), dtype=np.uint8)
        edge_layer.set_image(rgba_array_to_qpixmap(rgba))
        edge_layer.annotations = [tab.layer.annotations[0]]
        edge_layer.edge_width = 2
        edge_layer.edge_opacity = 0
        edge_layer._apply_edge_opacity()
        feathered = qpixmap_to_numpy(edge_layer.image)
        assert np.any(feathered[:, :, 3] > 0)

        ev_v = QKeyEvent(QEvent.KeyPress, Qt.Key_V, Qt.NoModifier)
        tab.keyPressEvent(ev_v)
        assert tab.layer.mouse_mode == MouseMode.IDLE
    finally:
        mw.close()


def test_zorder_occlusion_split_across_web_desktop_baker_api_and_conversion(tmp_path: Path):
    """Verify upper occluding layer splits lower object into single-instance Brush RLE across Web, Desktop, and Python API."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QPolygonF
    from PySide6.QtWidgets import QApplication, QMainWindow

    from imagebaker.api import ImageBaker, brush_annotation
    from imagebaker.core.configs import CanvasConfig
    from imagebaker.core.defs import Annotation, BakingResult
    from imagebaker.layers.base_layer import BaseLayer
    from imagebaker.tabs.baker_tab import BakerTab
    from imagebaker.utils.annotation_formats import rle_to_mask
    from imagebaker.web.models import WebLayerItem
    from imagebaker.workers.baker_worker import BakerWorker

    _app = QApplication.instance() or QApplication([])

    bg_arr = np.full((160, 220, 4), (40, 50, 60, 255), dtype=np.uint8)
    car_arr = np.full((60, 180, 4), (30, 130, 240, 255), dtype=np.uint8)
    pole_arr = np.full((140, 30, 4), (235, 235, 235, 255), dtype=np.uint8)

    img_dir = tmp_path / "web_scene"
    img_dir.mkdir()
    create_sample_image(img_dir / "bg.png", 220, 160)
    eng = WebAppEngine(models_file=None, project_dir=str(tmp_path), configs_file=None)
    ok, _ = eng.select_folder(str(img_dir))
    assert ok is True

    def _make_web_layer(
        lid: int,
        name: str,
        arr: np.ndarray,
        pos: QPointF,
        allow_export: bool,
        anns: list[Annotation] | None = None,
    ) -> WebLayerItem:
        lyr = WebLayerItem(eng.canvas_config)
        lyr.layer_id = lid
        lyr.layer_name = name
        lyr.set_image(rgba_array_to_qpixmap(arr))
        lyr.position = pos
        lyr.allow_annotation_export = allow_export
        lyr.annotations = list(anns or [])
        return lyr

    car_poly = QPolygonF([QPointF(0, 0), QPointF(180, 0), QPointF(180, 60), QPointF(0, 60)])
    eng.current_canvas.layers = [
        _make_web_layer(1, "bg", bg_arr, QPointF(0, 0), False),
        _make_web_layer(
            2,
            "car_layer",
            car_arr,
            QPointF(20, 50),
            True,
            [
                Annotation(
                    annotation_id=1,
                    label="car",
                    color=QColor(30, 130, 240),
                    polygon=car_poly,
                    selected=False,
                )
            ],
        ),
        _make_web_layer(3, "pole", pole_arr, QPointF(95, 10), False),
    ]
    eng.manage_states({"action": "save", "steps": 1})

    exp_coco = eng.bake_and_export(mode="current_local", annotation_format="coco")
    assert exp_coco["ok"] is True
    coco_payload = json.loads(exp_coco["annotation_exports"][0]["content"])
    assert len(coco_payload["annotations"]) == 1
    assert len(coco_payload["annotations"][0]["segmentation"]) == 2

    exp_def = eng.bake_and_export(mode="current_local", annotation_format="default")
    assert exp_def["ok"] is True
    def_anns = json.loads(exp_def["annotation_exports"][0]["content"])
    assert len(def_anns) == 1
    assert def_anns[0]["type"] == "brushlabels"
    rec = rle_to_mask(def_anns[0]["rle"], height=int(def_anns[0]["mask_size"][0]), width=int(def_anns[0]["mask_size"][1]))
    assert not np.any(rec[:, 97:123])
    n_web, _ = cv2.connectedComponents((rec > 0).astype(np.uint8))
    assert n_web - 1 == 2

    two_mask = np.zeros((60, 180), dtype=np.uint8)
    two_mask[10:50, 10:60] = 1
    two_mask[10:50, 120:170] = 1
    eng.current_canvas.layers[1].selected = True
    eng.current_canvas.layers[1].annotations = [
        Annotation(annotation_id=9, label="car", color=QColor(30, 130, 240), mask=two_mask)
    ]
    ok_conv, _ = eng._convert_selected_annotation_type()
    assert ok_conv is True
    conv_ann = eng.current_canvas.layers[1].annotations[0]
    assert conv_ann.polygon is not None or conv_ann.rectangle is not None

    mw = QMainWindow()
    try:
        btab = BakerTab(mw, CanvasConfig(project_dir=tmp_path))
        l_bg = BaseLayer(None, config=btab.config)
        l_bg.layer_id = 1
        l_bg.layer_name = "bg"
        l_bg.set_image(rgba_array_to_qpixmap(bg_arr))
        l_bg.position = QPointF(0, 0)
        l_bg.allow_annotation_export = False

        l_car = BaseLayer(None, config=btab.config)
        l_car.layer_id = 2
        l_car.layer_name = "car"
        l_car.set_image(rgba_array_to_qpixmap(car_arr))
        l_car.position = QPointF(20, 50)
        l_car.allow_annotation_export = True
        l_car.annotations = [
            Annotation(annotation_id=1, label="car", color=QColor(30, 130, 240), polygon=car_poly)
        ]

        l_pole = BaseLayer(None, config=btab.config)
        l_pole.layer_id = 3
        l_pole.layer_name = "pole"
        l_pole.set_image(rgba_array_to_qpixmap(pole_arr))
        l_pole.position = QPointF(95, 10)
        l_pole.allow_annotation_export = False

        worker_results: list[BakingResult] = []
        l_bg.layer_state.order = 0
        l_car.layer_state.order = 1
        l_pole.layer_state.order = 2
        states_map = {
            0: [l_bg.layer_state.copy(), l_car.layer_state.copy(), l_pole.layer_state.copy()]
        }
        b_worker = BakerWorker(
            states=states_map,
            layers=[l_bg, l_car, l_pole],
            filename=tmp_path / "desk_bake.png",
            timeline_total_steps=1,
        )
        b_worker.finished.connect(worker_results.extend)
        b_worker.process()

        assert len(worker_results) == 1
        d_anns = worker_results[0].annotations
        assert len(d_anns) == 1
        assert d_anns[0].mask is not None
        assert not np.any(d_anns[0].mask[:, 97:123])
        n_desk, _ = cv2.connectedComponents((d_anns[0].mask > 0).astype(np.uint8))
        assert n_desk - 1 == 2

        l_car.selected = True
        l_car.annotations = [
            Annotation(annotation_id=5, label="car", color=QColor(30, 130, 240), mask=two_mask)
        ]
        btab.current_canvas.layers = [l_car]
        btab.convert_selected_annotation_type()
        assert l_car.annotations[0].polygon is not None or l_car.annotations[0].rectangle is not None
    finally:
        mw.close()

    api_baker = ImageBaker(output_dir=str(tmp_path / "api_out"))
    api_baker.add_layer_from_array(bg_arr, layer_name="bg")
    car_full_mask = np.zeros((160, 220), dtype=np.uint8)
    car_full_mask[50:110, 20:200] = 1
    car_full_rgba = np.zeros((160, 220, 4), dtype=np.uint8)
    car_full_rgba[50:110, 20:200] = (30, 130, 240, 255)
    c_id = api_baker.add_layer_from_array(car_full_rgba, layer_name="car")
    api_baker.add_annotation(c_id, brush_annotation(label="car", mask=car_full_mask))
    pole_full_rgba = np.zeros((160, 220, 4), dtype=np.uint8)
    pole_full_rgba[10:150, 95:125] = (235, 235, 235, 255)
    api_baker.add_layer_from_array(pole_full_rgba, layer_name="pole")
    api_res = api_baker.bake()
    assert len(api_res.annotations) == 1
    assert api_res.annotations[0].mask is not None
    assert not np.any(api_res.annotations[0].mask[:, 97:123])
    n_api, _ = cv2.connectedComponents((api_res.annotations[0].mask > 0).astype(np.uint8))
    assert n_api - 1 == 2
