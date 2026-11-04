import os
import sys
from pathlib import Path

import cv2
import numpy as np

# Ensure project root is at the front of sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imagebaker import logger
from imagebaker.core.defs import PredictionResult
from imagebaker.models.base_model import (
    BaseClassificationModel,
    BaseDetectionModel,
    BasePromptModel,
    BaseSegmentationModel,
    DefaultModelConfig,
    ModelType,
    get_dummy_prediction_result,
    normalize_boxes,
    normalize_points,
)


class ClassificationModel(BaseClassificationModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    def predict_class(self, image: np.ndarray):
        return [get_dummy_prediction_result(self.config.model_type)]


class DetectionModel(BaseDetectionModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    def predict_boxes(self, image: np.ndarray):
        h, w = image.shape[:2]
        # Detect non-background contour bounding boxes or fallback to a central box
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        edges = cv2.Canny(gray, 40, 120)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        results: list[PredictionResult] = []
        for idx, cnt in enumerate(sorted(contours, key=cv2.contourArea, reverse=True)[:3]):
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw >= max(8, w // 12) and bh >= max(8, h // 12):
                results.append(
                    PredictionResult(
                        class_name="detected_object",
                        class_id=idx,
                        score=round(0.95 - idx * 0.05, 2),
                        rectangle=[int(x), int(y), int(bw), int(bh)],
                    )
                )
        if not results:
            results.append(
                PredictionResult(
                    class_name="detected_object",
                    class_id=0,
                    score=0.92,
                    rectangle=[int(w * 0.2), int(h * 0.2), int(w * 0.6), int(h * 0.6)],
                )
            )
        return results


class DummySegmentationModel(BaseSegmentationModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    def predict_mask(self, image: np.ndarray):
        h, w = image.shape[:2]
        cx, cy = w / 2.0, h / 2.0
        rx, ry = max(8.0, w * 0.3), max(8.0, h * 0.3)
        angles = np.linspace(0, 2 * np.pi, 12, endpoint=False)
        poly = np.array(
            [[float(cx + rx * np.cos(a)), float(cy + ry * np.sin(a))] for a in angles],
            dtype=np.float32,
        )
        return [
            PredictionResult(
                class_name="segmented_region",
                class_id=0,
                score=0.94,
                polygon=poly,
            )
        ]


class DummyPromptModel(BasePromptModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    def predict_prompt(
        self,
        image: np.ndarray,
        points=None,
        rectangles=None,
        label_hints=None,
        **kwargs,
    ):
        h, w = image.shape[:2]
        results: list[PredictionResult] = []
        boxes = normalize_boxes(rectangles)
        pts = normalize_points(points)

        if boxes:
            for idx, box in enumerate(boxes):
                x1, y1, x2, y2 = box
                bx1, by1 = max(0, int(min(x1, x2))), max(0, int(min(y1, y2)))
                bx2, by2 = min(w, int(max(x1, x2))), min(h, int(max(y1, y2)))
                bw, bh = max(1, bx2 - bx1), max(1, by2 - by1)
                mx, my = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
                rx, ry = max(4.0, bw * 0.45), max(4.0, bh * 0.45)
                poly = np.array(
                    [
                        [mx - rx, my - ry * 0.5],
                        [mx, my - ry],
                        [mx + rx, my - ry * 0.5],
                        [mx + rx, my + ry * 0.5],
                        [mx, my + ry],
                        [mx - rx, my + ry * 0.5],
                    ],
                    dtype=np.float32,
                )
                mask = np.zeros((h, w), dtype=np.uint8)
                cv2.fillPoly(mask, [poly.astype(np.int32)], 1)

                rgba = np.zeros((bh, bw, 4), dtype=np.uint8)
                patch = image[by1:by2, bx1:bx2]
                if patch.ndim == 3 and patch.shape[2] >= 3:
                    rgba[..., :3] = patch[..., :3]
                rgba[..., 3] = mask[by1:by2, bx1:bx2] * 255

                results.append(
                    PredictionResult(
                        class_name="prompt_segment",
                        prompt="box_prompt",
                        class_id=idx,
                        score=0.96,
                        rectangle=[bx1, by1, bw, bh],
                        polygon=poly,
                        mask=mask,
                        annotated_image=rgba,
                    )
                )
        elif pts:
            for idx, pt in enumerate(pts):
                px, py = pt[0], pt[1]
                r = max(10.0, min(w, h) * 0.18)
                angles = np.linspace(0, 2 * np.pi, 8, endpoint=False)
                poly = np.array(
                    [
                        [
                            float(np.clip(px + r * np.cos(a), 0, w)),
                            float(np.clip(py + r * np.sin(a), 0, h)),
                        ]
                        for a in angles
                    ],
                    dtype=np.float32,
                )
                bx1, by1 = max(0, int(px - r)), max(0, int(py - r))
                bx2, by2 = min(w, int(px + r)), min(h, int(py + r))
                bw, bh = max(1, bx2 - bx1), max(1, by2 - by1)
                mask = np.zeros((h, w), dtype=np.uint8)
                cv2.fillPoly(mask, [poly.astype(np.int32)], 1)

                rgba = np.zeros((bh, bw, 4), dtype=np.uint8)
                patch = image[by1:by2, bx1:bx2]
                if patch.ndim == 3 and patch.shape[2] >= 3:
                    rgba[..., :3] = patch[..., :3]
                rgba[..., 3] = mask[by1:by2, bx1:bx2] * 255

                results.append(
                    PredictionResult(
                        class_name="prompt_segment",
                        prompt="point_prompt",
                        class_id=idx,
                        score=0.93,
                        rectangle=[bx1, by1, bw, bh],
                        polygon=poly,
                        mask=mask,
                        annotated_image=rgba,
                    )
                )
        else:
            results.append(get_dummy_prediction_result(ModelType.PROMPT))
        return results


return_annotated_image = True

classification = ClassificationModel(
    DefaultModelConfig(
        model_type=ModelType.CLASSIFICATION,
        return_annotated_image=return_annotated_image,
    )
)
dummy_detector = DetectionModel(
    DefaultModelConfig(
        model_type=ModelType.DETECTION,
        return_annotated_image=return_annotated_image,
    )
)
dummy_segmenter = DummySegmentationModel(
    DefaultModelConfig(
        model_type=ModelType.SEGMENTATION,
        return_annotated_image=return_annotated_image,
    )
)
dummy_prompt = DummyPromptModel(
    DefaultModelConfig(
        model_type=ModelType.PROMPT,
        return_annotated_image=return_annotated_image,
    )
)

LOADED_MODELS = {
    "DummyDetectionModel": dummy_detector,
    "DummySegmentationModel": dummy_segmenter,
    "DummyPromptModel": dummy_prompt,
    "ClassificationModel": classification,
}

# Add YOLO, RF-DETR, and SAM 2 models
try:
    from examples.models_yolo_rfdetr_sam2 import (
        RFDetrDetectionModel,
        RFDetrSegmentationModel,
        SAM2PromptModel,
        YoloDetectionModel,
        YoloSegmentationModel,
    )

    LOADED_MODELS["YOLO-Detection"] = YoloDetectionModel()
    LOADED_MODELS["YOLO-Segmentation"] = YoloSegmentationModel()
    LOADED_MODELS["RF-DETR-Detection"] = RFDetrDetectionModel()
    LOADED_MODELS["RF-DETR-Segmentation"] = RFDetrSegmentationModel()
    LOADED_MODELS["SAM2-Prompt"] = SAM2PromptModel()
except Exception as exc:
    logger.debug(f"Could not load YOLO/RF-DETR/SAM2 models into LOADED_MODELS: {exc}")

# Optionally load heavy deep learning models (RTDetrV2, SAM, YOLO) when
# IMAGEBAKER_LOAD_HEAVY_MODELS=1 is set and dependencies/weights are available.
if os.environ.get("IMAGEBAKER_LOAD_HEAVY_MODELS", "0") == "1":
    try:
        from examples.rtdetr_v2 import RTDetrDetectionModel, RTDetrModelConfig

        LOADED_MODELS["RTDetrV2"] = RTDetrDetectionModel(
            RTDetrModelConfig(return_annotated_image=return_annotated_image)
        )
    except Exception as exc:
        logger.debug(f"Optional RTDetrV2 model not loaded: {exc}")

    try:
        from examples.sam_model import SAMModelConfig, SegmentAnythingModel

        LOADED_MODELS["PromptModel"] = SegmentAnythingModel(
            SAMModelConfig(return_annotated_image=return_annotated_image)
        )
    except Exception as exc:
        logger.debug(f"Optional SAM PromptModel not loaded: {exc}")

    try:
        from examples.segmentation import YoloSegmentationModel, YoloSegmentationModelConfig

        LOADED_MODELS["SegmentationModel"] = YoloSegmentationModel(
            YoloSegmentationModelConfig(return_annotated_image=return_annotated_image)
        )
    except Exception as exc:
        logger.debug(f"Optional YOLO SegmentationModel not loaded: {exc}")

logger.info(f"Loaded models: {list(LOADED_MODELS.keys())}")
