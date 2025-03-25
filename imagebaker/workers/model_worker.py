from imagebaker import logger
from imagebaker.models.base_model import DefaultModel
from PySide6.QtCore import QObject, Signal
import numpy as np
import traceback


class ModelPredictionWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        model: DefaultModel,
        image: np.ndarray,
        points: list[int],
        polygons: list[list[int]],
        rectangles: list[list[int]],
        label_hints: list[int],
    ):
        super().__init__()
        self.model = model
        self.image = image
        self.points = points
        self.polygons = polygons
        self.rectangles = rectangles
        self.label_hints = label_hints

    def process(self):
        try:
            result = self.model.predict(
                self.image,
                self.points,
                self.rectangles,
                self.polygons,
                self.label_hints,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()
            logger.error(f"Model error: {e}")
            return
