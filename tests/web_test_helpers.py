"""Shared helpers for ImageBaker web, desktop, and brush-occlusion tests."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np


def create_sample_image(path: Path, width: int = 120, height: int = 90) -> Path:
    """Write a synthetic BGR sample PNG/BMP/TIFF image to ``path``."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (40, 120, 200)
    cv2.rectangle(img, (15, 15), (min(width - 5, 80), min(height - 5, 65)), (20, 220, 80), -1)
    cv2.imwrite(str(path), img)
    return path


def create_dummy_models_file(path: Path) -> Path:
    """Write a lightweight mock detector module exporting ``LOADED_MODELS``."""
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


def rgba_array_to_qpixmap(arr: np.ndarray):
    """Convert an RGBA uint8 numpy array to a detached QPixmap."""
    from PySide6.QtGui import QImage, QPixmap

    contiguous = np.ascontiguousarray(arr)
    return QPixmap.fromImage(
        QImage(
            contiguous.data,
            contiguous.shape[1],
            contiguous.shape[0],
            contiguous.shape[1] * 4,
            QImage.Format_RGBA8888,
        ).copy()
    )
