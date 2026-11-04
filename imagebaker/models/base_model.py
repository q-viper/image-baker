import inspect
import time
from abc import ABC, abstractmethod
from typing import Any

import cv2
import numpy as np
from loguru import logger

from imagebaker.core.configs import DefaultModelConfig
from imagebaker.core.defs.defs import ModelType, PredictionResult


def normalize_boxes(rectangles: Any) -> list[list[float]]:
    """
    Normalizes bounding boxes/rectangles into a standard 2D list of [x1, y1, x2, y2] floats.
    Handles:
      - None / empty -> []
      - 1D: [x1, y1, x2, y2] -> [[x1, y1, x2, y2]]
      - 2D: [[x1, y1, x2, y2], ...] -> [[x1, y1, x2, y2], ...]
      - 3D: [[[x1, y1, x2, y2], ...]] -> [[x1, y1, x2, y2], ...]
      - NumPy arrays of matching shapes
    """
    if rectangles is None:
        return []
    if isinstance(rectangles, np.ndarray):
        rectangles = rectangles.tolist()
    if not isinstance(rectangles, (list, tuple)) or len(rectangles) == 0:
        return []

    # 1D single box: [x1, y1, x2, y2]
    if len(rectangles) == 4 and all(isinstance(v, (int, float, np.number)) for v in rectangles):
        return [[float(v) for v in rectangles]]

    boxes: list[list[float]] = []
    for item in rectangles:
        if item is None:
            continue
        if isinstance(item, np.ndarray):
            item = item.tolist()
        if not isinstance(item, (list, tuple)) or len(item) == 0:
            continue
        if len(item) == 4 and all(isinstance(v, (int, float, np.number)) for v in item):
            boxes.append([float(v) for v in item])
        elif isinstance(item[0], (list, tuple, np.ndarray)):
            for sub in item:
                if isinstance(sub, np.ndarray):
                    sub = sub.tolist()
                if (
                    isinstance(sub, (list, tuple))
                    and len(sub) == 4
                    and all(isinstance(v, (int, float, np.number)) for v in sub)
                ):
                    boxes.append([float(v) for v in sub])

    return boxes


def normalize_points(points: Any) -> list[list[float]]:
    """
    Normalizes points into a list of [x, y] coordinates.
    Handles [x, y], [[x, y], ...], [[[x, y], ...]].
    """
    if points is None:
        return []
    if isinstance(points, np.ndarray):
        points = points.tolist()
    if not isinstance(points, (list, tuple)) or len(points) == 0:
        return []

    # 1D single point [x, y]
    if len(points) == 2 and all(isinstance(v, (int, float, np.number)) for v in points):
        return [[float(points[0]), float(points[1])]]

    pts: list[list[float]] = []
    for item in points:
        if item is None:
            continue
        if isinstance(item, np.ndarray):
            item = item.tolist()
        if not isinstance(item, (list, tuple)) or len(item) == 0:
            continue
        if len(item) == 2 and all(isinstance(v, (int, float, np.number)) for v in item):
            pts.append([float(item[0]), float(item[1])])
        elif isinstance(item[0], (list, tuple, np.ndarray)):
            for sub in item:
                if isinstance(sub, np.ndarray):
                    sub = sub.tolist()
                if (
                    isinstance(sub, (list, tuple))
                    and len(sub) == 2
                    and all(isinstance(v, (int, float, np.number)) for v in sub)
                ):
                    pts.append([float(sub[0]), float(sub[1])])
    return pts


class BaseModel(ABC):
    def __init__(self, config: DefaultModelConfig):
        """
        A base class for all models.

        Args:
            config (DefaultModelConfig): Model configuration.
        """
        self.config = config
        self.model = None
        self.image_shape: tuple = None

        self.setup()

    @property
    def name(self):
        # class name
        return self.__class__.__name__

    def __repr__(self):
        return f"{self.config.model_name} v{self.config.model_version}"

    # @abstractmethod
    def setup(self):
        pass

    # @abstractmethod
    def preprocess(self, image: np.ndarray):
        return image

    # @abstractmethod
    def postprocess(self, output) -> list[PredictionResult]:
        return output

    def predict(
        self,
        image: np.ndarray,
        points: list[int] | None = None,
        rectangles: list[list[int]] | None = None,
        polygons: list[list[int]] | None = None,
        label_hints: list[int] | None = None,
        prompt: str | None = None,
        text_prompt: str | None = None,
        **kwargs,
    ) -> list[PredictionResult]:
        t0 = time.time()
        self.image_shape = image.shape[:2]
        effective_prompt = text_prompt if text_prompt is not None else prompt
        self.current_prompt = effective_prompt

        if image.shape[2] == 4:
            logger.info("Converting image from RGBA to RGB")
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
        preprocessed_image = self.preprocess(image)
        t1 = time.time()
        logger.info(f"Preprocessing time: {t1-t0:.4f} seconds")

        output = []
        if self.config.model_type == ModelType.DETECTION:
            sig = inspect.signature(self.predict_boxes)
            params = sig.parameters
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            kwargs_to_pass = {}
            if "rectangles" in params or (has_var_kw and rectangles is not None):
                kwargs_to_pass["rectangles"] = rectangles
            if "prompt" in params:
                kwargs_to_pass["prompt"] = effective_prompt
            if "text_prompt" in params or has_var_kw:
                kwargs_to_pass["text_prompt"] = effective_prompt

            called = False
            if kwargs_to_pass:
                try:
                    output = self.predict_boxes(preprocessed_image, **kwargs_to_pass)
                    called = True
                except TypeError:
                    called = False
            if not called:
                try:
                    output = self.predict_boxes(preprocessed_image, text_prompt=effective_prompt)
                except TypeError:
                    output = self.predict_boxes(preprocessed_image)

        elif self.config.model_type == ModelType.SEGMENTATION:
            sig = inspect.signature(self.predict_mask)
            params = sig.parameters
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            kwargs_to_pass = {}
            if "rectangles" in params or has_var_kw:
                kwargs_to_pass["rectangles"] = rectangles
            if "boxes" in params:
                kwargs_to_pass["boxes"] = rectangles
            if "points" in params or (has_var_kw and points is not None):
                kwargs_to_pass["points"] = points
            if "polygons" in params or (has_var_kw and polygons is not None):
                kwargs_to_pass["polygons"] = polygons
            if "label_hints" in params or (has_var_kw and label_hints is not None):
                kwargs_to_pass["label_hints"] = label_hints
            if "prompt" in params:
                kwargs_to_pass["prompt"] = effective_prompt
            if "text_prompt" in params or has_var_kw:
                kwargs_to_pass["text_prompt"] = effective_prompt

            called = False
            if kwargs_to_pass:
                try:
                    output = self.predict_mask(preprocessed_image, **kwargs_to_pass)
                    called = True
                except TypeError as err:
                    logger.debug(f"predict_mask with kwargs failed ({err}), falling back.")
                    called = False
            if not called:
                try:
                    output = self.predict_mask(preprocessed_image, text_prompt=effective_prompt)
                except TypeError:
                    output = self.predict_mask(preprocessed_image)

        elif self.config.model_type == ModelType.CLASSIFICATION:
            try:
                output = self.predict_class(preprocessed_image, text_prompt=effective_prompt)
            except TypeError:
                output = self.predict_class(preprocessed_image)

        elif self.config.model_type == ModelType.PROMPT:
            sig = inspect.signature(self.predict_prompt)
            params = sig.parameters
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

            norm_boxes = normalize_boxes(rectangles)
            norm_points = normalize_points(points)

            call_kwargs = {}
            # Map rectangles / boxes prompt
            if "rectangles" in params:
                call_kwargs["rectangles"] = rectangles if rectangles is not None else (norm_boxes if norm_boxes else None)
            elif "input_boxes" in params:
                call_kwargs["input_boxes"] = [norm_boxes] if norm_boxes else rectangles
            elif "boxes" in params:
                call_kwargs["boxes"] = norm_boxes if norm_boxes else rectangles
            elif has_var_kw:
                call_kwargs["rectangles"] = rectangles

            # Map points prompt
            if "points" in params:
                call_kwargs["points"] = points
            elif "input_points" in params:
                call_kwargs["input_points"] = norm_points if norm_points else points
            elif has_var_kw and points is not None:
                call_kwargs["points"] = points

            # Map polygons
            if "polygons" in params:
                call_kwargs["polygons"] = polygons
            elif has_var_kw and polygons is not None:
                call_kwargs["polygons"] = polygons

            # Map label hints
            if "label_hints" in params:
                call_kwargs["label_hints"] = label_hints
            elif "input_labels" in params:
                call_kwargs["input_labels"] = label_hints
            elif has_var_kw and label_hints is not None:
                call_kwargs["label_hints"] = label_hints

            # Map prompt text
            if "prompt" in params:
                call_kwargs["prompt"] = effective_prompt
            elif "text_prompt" in params:
                call_kwargs["text_prompt"] = effective_prompt
            elif has_var_kw and effective_prompt is not None:
                call_kwargs["prompt"] = effective_prompt

            called = False
            if call_kwargs:
                try:
                    output = self.predict_prompt(preprocessed_image, **call_kwargs)
                    called = True
                except TypeError as err:
                    logger.debug(f"Calling predict_prompt with kwargs failed: {err}. Falling back to positional call.")
                    called = False

            if not called:
                try:
                    output = self.predict_prompt(
                        preprocessed_image, points, rectangles, label_hints, prompt=effective_prompt
                    )
                except TypeError:
                    try:
                        output = self.predict_prompt(
                            preprocessed_image, points, rectangles, label_hints
                        )
                    except TypeError:
                        output = self.predict_prompt(
                            preprocessed_image, points, rectangles, polygons
                        )

        t2 = time.time()
        logger.info(f"Prediction time: {t2-t1:.4f} seconds")

        result = self.postprocess(output)
        t3 = time.time()
        logger.info(f"Postprocessing time: {t3-t2:.4f} seconds")

        return result


class BaseSegmentationModel(BaseModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    @abstractmethod
    def predict_mask(self, image):
        pass


class BaseDetectionModel(BaseModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    @abstractmethod
    def predict_boxes(self, image):
        pass


class BaseClassificationModel(BaseModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    @abstractmethod
    def predict_class(self, image):
        pass


class BasePromptModel(BaseModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    @abstractmethod
    def predict_prompt(self, image, points, rectangles, polygons):
        pass


def get_dummy_prediction_result(result_type: ModelType) -> PredictionResult:
    if result_type == ModelType.DETECTION:
        # retrun random rectangle

        x1, y1 = np.random.randint(0, 1000, 2)
        x2, y2 = np.random.randint(200, 500, 2)
        return PredictionResult(
            class_name="dummy", class_id=0, score=0.99, rectangle=[x1, y1, x2, y2]
        )

    elif result_type == ModelType.SEGMENTATION:
        return PredictionResult(
            class_name="dummy",
            class_id=0,
            score=0.99,
            mask=np.array([[0, 0], [0, 100], [100, 100], [100, 0]]),
        )

    elif result_type == ModelType.CLASSIFICATION:
        return PredictionResult(class_name="dummy", class_id=0, score=0.99)

    elif result_type == ModelType.PROMPT:
        return PredictionResult(
            prompt="dummy",
            class_id=0,
            score=0.99,
            mask=np.array([[0, 0], [0, 100], [100, 100], [100, 0]]),
        )
