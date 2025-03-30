from abc import ABC, abstractmethod
from loguru import logger
import numpy as np
import time
import cv2

from imagebaker.core.defs.defs import ModelType, PredictionResult
from imagebaker.core.configs import DefaultModelConfig


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
    def postprocess(self, output) -> PredictionResult:
        return output

    def predict(
        self,
        image: np.ndarray,
        points: list[int] | None = None,
        rectangles: list[list[int]] | None = None,
        polygons: list[list[int]] | None = None,
        label_hints: list[int] | None = None,
    ) -> list[PredictionResult]:
        t0 = time.time()
        self.image_shape = image.shape[:2]
        if image.shape[2] == 4:
            logger.info("Converting image from RGBA to RGB")
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
        preprocessed_image = self.preprocess(image)
        t1 = time.time()
        logger.info(f"Preprocessing time: {t1-t0:.4f} seconds")

        if self.config.model_type == ModelType.DETECTION:
            output = self.predict_boxes(preprocessed_image)

        elif self.config.model_type == ModelType.SEGMENTATION:
            output = self.predict_mask(preprocessed_image)

        elif self.config.model_type == ModelType.CLASSIFICATION:
            output = self.predict_class(preprocessed_image)

        elif self.config.model_type == ModelType.PROMPT:

            output = self.predict_prompt(
                preprocessed_image, points, rectangles, label_hints
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
            mask=[[0, 0], [0, 100], [100, 100], [100, 0]],
        )

    elif result_type == ModelType.CLASSIFICATION:
        return PredictionResult(class_name="dummy", class_id=0, score=0.99)

    elif result_type == ModelType.PROMPT:
        return PredictionResult(
            prompt="dummy",
            class_id=0,
            score=0.99,
            mask=[[0, 0], [0, 100], [100, 100], [100, 0]],
        )
