import numpy as np
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPolygonF

from imagebaker.core.defs import Annotation, ModelType, PredictionResult
from imagebaker.models.base_model import (
    BasePromptModel,
    BaseSegmentationModel,
    DefaultModelConfig,
    normalize_boxes,
    normalize_points,
)
from examples.models_yolo_rfdetr_sam2 import (
    RFDetrSegmentationModel,
    SAM2PromptModel,
)
from examples.loaded_models import DummyPromptModel
from imagebaker.web.engine import WebAppEngine


def test_normalize_boxes():
    # 1D single box
    b1 = normalize_boxes([10, 20, 110, 120])
    assert b1 == [[10.0, 20.0, 110.0, 120.0]]

    # 2D list of boxes
    b2 = normalize_boxes([[10, 20, 110, 120], [30, 40, 130, 140]])
    assert b2 == [[10.0, 20.0, 110.0, 120.0], [30.0, 40.0, 130.0, 140.0]]

    # 3D batched list of boxes
    b3 = normalize_boxes([[[10, 20, 110, 120], [30, 40, 130, 140]]])
    assert b3 == [[10.0, 20.0, 110.0, 120.0], [30.0, 40.0, 130.0, 140.0]]

    # NumPy array
    b4 = normalize_boxes(np.array([[10, 20, 110, 120]]))
    assert b4 == [[10.0, 20.0, 110.0, 120.0]]

    # Empty and None
    assert normalize_boxes(None) == []
    assert normalize_boxes([]) == []


def test_normalize_points():
    # 1D single point
    p1 = normalize_points([50, 60])
    assert p1 == [[50.0, 60.0]]

    # 2D list of points
    p2 = normalize_points([[50, 60], [70, 80]])
    assert p2 == [[50.0, 60.0], [70.0, 80.0]]

    # 3D nested points
    p3 = normalize_points([[[50, 60]], [[70, 80]]])
    assert p3 == [[50.0, 60.0], [70.0, 80.0]]

    assert normalize_points(None) == []
    assert normalize_points([]) == []


def test_sam2_prompt_model_with_rectangle_prompt():
    model = SAM2PromptModel()
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    img[40:160, 50:180] = 200

    # 2D box prompt
    rect_prompt_2d = [[50, 40, 180, 160]]
    results = model.predict(img, rectangles=rect_prompt_2d)
    assert len(results) > 0
    res = results[0]
    assert res.prompt == "box_prompt"
    assert res.polygon is not None
    assert len(res.polygon) >= 3
    assert res.mask is not None
    assert res.mask.shape == (300, 400)
    assert res.rectangle is not None
    assert res.annotated_image is not None
    assert res.annotated_image.shape[2] == 4  # RGBA cropped patch

    # 3D batched box prompt (as passed from canvas annotations)
    rect_prompt_3d = [[[50, 40, 180, 160]]]
    results_3d = model.predict(img, rectangles=rect_prompt_3d)
    assert len(results_3d) > 0
    assert results_3d[0].prompt == "box_prompt"


def test_rfdetr_segmentation_with_rectangle_annotation_crop():
    model = RFDetrSegmentationModel()
    img = np.zeros((400, 500, 3), dtype=np.uint8)
    # Put a bright object at [100:250, 120:300]
    img[100:250, 120:300] = 220

    # Pass rectangle annotation crop prompt
    crop_rect = [[120, 100, 300, 250]]
    results = model.predict(img, rectangles=crop_rect)
    assert len(results) > 0

    res = results[0]
    assert res.prompt == "box_crop"
    assert res.mask is not None
    assert res.mask.shape == (400, 500)
    # The mask should be concentrated inside the crop region [100:250, 120:300]
    assert np.any(res.mask[100:250, 120:300] > 0)
    # Pixels outside crop should be 0
    assert np.all(res.mask[:90, :] == 0)
    assert np.all(res.mask[260:, :] == 0)

    # Polygon coordinates should be mapped to the original image
    assert res.polygon is not None
    assert len(res.polygon) >= 3
    xs = [p[0] for p in res.polygon]
    ys = [p[1] for p in res.polygon]
    assert min(xs) >= 115
    assert min(ys) >= 95

    # Cropped masked RGBA patch
    assert res.annotated_image is not None
    assert res.annotated_image.ndim == 3
    assert res.annotated_image.shape[2] == 4


def test_rfdetr_segmentation_full_image():
    model = RFDetrSegmentationModel()
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    img[50:180, 60:220] = 210

    results = model.predict(img)
    assert len(results) > 0
    res = results[0]
    assert res.mask is not None
    assert res.polygon is not None
    assert res.rectangle is not None
    assert res.annotated_image is not None
    assert res.annotated_image.shape[2] == 4


def test_web_engine_prompt_prediction_and_polygon_precedence(tmp_path):
    import cv2
    img_path = tmp_path / "test_sample.png"
    img = np.full((200, 300, 3), 100, dtype=np.uint8)
    cv2.circle(img, (150, 100), 40, (255, 255, 255), -1)
    cv2.imwrite(str(img_path), img)

    engine = WebAppEngine("examples/loaded_models.py")
    ok, msg = engine.select_folder(str(tmp_path))
    assert ok, f"select_folder failed: {msg}"
    assert len(engine.image_entries) > 0

    # Create a user rectangle prompt annotation on canvas
    engine.current_annotations = [
        Annotation(
            annotation_id=0,
            label="prompt_box",
            rectangle=QRectF(100, 50, 100, 100),  # x=100, y=50, w=100, h=100 -> [100, 50, 200, 150]
            selected=True,
            visible=True,
            is_model_generated=False,
        )
    ]

    # Select RF-DETR segmentation model
    engine.current_model_name = "RF-DETR-Segmentation"
    engine.current_label = "target"
    ok, msg = engine.run_prediction()
    assert ok, f"Prediction failed: {msg}"

    # Verify that prediction generated a polygon/mask annotation (NOT just a rectangle)
    gen_anns = [a for a in engine.current_annotations if a.is_model_generated]
    assert len(gen_anns) > 0
    ann = gen_anns[0]
    assert ann.polygon is not None
    assert len(ann.polygon) >= 3
    assert ann.mask is not None
