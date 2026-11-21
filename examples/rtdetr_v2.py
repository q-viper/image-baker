"""RF-DETR Object Detection example using the native `rfdetr` package directly (no transformers)."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import torch
from loguru import logger
from PIL import Image

from imagebaker.models.base_model import (
    BaseDetectionModel,
    DefaultModelConfig,
    ModelType,
    PredictionResult,
)
from imagebaker.utils import generate_color_map
from imagebaker.utils.vis import annotate_detection


class RTDetrModelConfig(DefaultModelConfig):
    """Configuration for RF-DETR object detection loaded directly via `rfdetr`."""

    model_type: ModelType = ModelType.DETECTION
    model_name: str = "RF-DETR"
    model_description: str = "Real-Time Detection Transformer loaded directly via `rfdetr`."
    model_version: str = "small"
    model_license: str = "Apache-2.0"
    pretrained_model_name: str = "rfdetr-small"
    confidence_threshold: float = 0.45
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    return_annotated_image: bool = True

    # Visualization parameters
    box_thickness: int = 2
    text_thickness: int = 1
    text_scale: float = 0.5
    font_face: int = cv2.FONT_HERSHEY_SIMPLEX
    color_map: dict = {}


class RTDetrDetectionModel(BaseDetectionModel):
    """Object detection wrapper backed directly by the open-source `rfdetr` package."""

    def __init__(self, config: RTDetrModelConfig = RTDetrModelConfig()):
        super().__init__(config)

    def setup(self):
        """Initialize the native `rfdetr` detector model."""
        import rfdetr

        cls_map = {
            "rfdetr-nano": "RFDETRNano",
            "rfdetr-small": "RFDETRSmall",
            "rfdetr-medium": "RFDETRMedium",
            "rfdetr-large": "RFDETRLarge",
            "rfdetr-base": "RFDETRBase",
        }
        raw = str(self.config.pretrained_model_name or "rfdetr-small").strip()
        cls_name = cls_map.get(raw.lower(), "RFDETRSmall")
        model_cls = getattr(rfdetr, cls_name, None) or getattr(rfdetr, "RFDETRBase", None)

        logger.info(f"Loading RF-DETR detector ({cls_name}) via `rfdetr`...")
        if raw and Path(raw).is_file():
            self.model = model_cls(pretrain_weights=raw)
        else:
            self.model = model_cls()

        if hasattr(self.model, "class_names") and self.model.class_names:
            self.config.class_names = list(self.model.class_names.values())
        if self.config.class_names and not self.config.color_map:
            color_map = generate_color_map(len(self.config.class_names))
            self.config.color_map = {
                cls_name: color_map[i] for i, cls_name in enumerate(self.config.class_names)
            }

    def preprocess(self, image: np.ndarray) -> Image.Image:
        """Convert numpy RGB array to PIL Image for `rfdetr.predict()`."""
        self._original_image = (
            image.copy() if isinstance(image, np.ndarray) else np.array(image)
        )
        if isinstance(image, np.ndarray):
            return Image.fromarray(image.astype("uint8"))
        return image

    def predict_boxes(self, image: Image.Image):
        """Run object detection directly with `rfdetr`."""
        return self.model.predict(image, threshold=self.config.confidence_threshold)

    def postprocess(self, output) -> list[PredictionResult]:
        """Convert `rfdetr` `supervision.Detections` output into ImageBaker `PredictionResult`s."""
        results: list[PredictionResult] = []
        if output is None or not hasattr(output, "xyxy"):
            return results

        xyxy_arr = np.asarray(output.xyxy)
        scores = (
            np.asarray(output.confidence)
            if output.confidence is not None
            else np.ones(len(xyxy_arr))
        )
        labels = (
            np.asarray(output.class_id)
            if output.class_id is not None
            else np.zeros(len(xyxy_arr), dtype=int)
        )
        annotation_time = time.time()

        for score, label_id, box in zip(scores, labels, xyxy_arr, strict=False):
            cid = int(label_id)
            class_name = (
                self.config.class_names[cid]
                if 0 <= cid < len(self.config.class_names)
                else f"class_{cid}"
            )
            x = int(box[0])
            y = int(box[1])
            w = int(box[2] - box[0])
            h = int(box[3] - box[1])

            result = PredictionResult(
                class_name=class_name,
                class_id=cid,
                score=float(score),
                rectangle=[x, y, w, h],
                annotation_time=f"{annotation_time:.6f}",
            )
            if self.config.return_annotated_image:
                result.annotated_image = annotate_detection(
                    self._original_image,
                    [result],
                    box_thickness=self.config.box_thickness,
                    text_thickness=self.config.text_thickness,
                    text_scale=self.config.text_scale,
                    font_face=self.config.font_face,
                    color_map=self.config.color_map,
                )
            results.append(result)

        return results
