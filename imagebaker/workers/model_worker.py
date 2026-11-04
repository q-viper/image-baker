import traceback

import numpy as np
from PySide6.QtCore import QObject, Signal

from imagebaker import logger
from imagebaker.models.base_model import BaseModel


class ModelPredictionWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        model: BaseModel,
        image: np.ndarray,
        points: list[int],
        polygons: list[list[int]],
        rectangles: list[list[int]],
        label_hints: list[int],
        prompt: str | None = None,
        text_prompt: str | None = None,
    ):
        """
        A worker that runs the model prediction in a separate thread.

        Args:
            model (BaseModel): The model to use for prediction.
            image (np.ndarray): The image to predict on.
            points (list[int]): The points to predict on.
            polygons (list[list[int]]): The polygons to predict on.
            rectangles (list[list[int]]): The rectangles to predict on.
            label_hints (list[int]): The label hints to use.
            prompt (str, optional): Text prompt for open-vocabulary / prompt models.
            text_prompt (str, optional): Alternative alias for prompt.
        """
        super().__init__()
        self.model = model
        self.image = image
        self.points = points
        self.polygons = polygons
        self.rectangles = rectangles
        self.label_hints = label_hints
        self.prompt = text_prompt if text_prompt is not None else prompt

    def process(self):
        try:
            result = self.model.predict(
                self.image,
                self.points,
                self.rectangles,
                self.polygons,
                self.label_hints,
                prompt=self.prompt,
                text_prompt=self.prompt,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()
            logger.error(f"Model error: {e}")
            return
