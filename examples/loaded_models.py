import sys
from pathlib import Path

# Add the project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from imagebaker.models.base_model import (
    DefaultModelConfig,
    BaseClassificationModel,
    get_dummy_prediction_result,
    ModelType,
)
from imagebaker.models.base_model import BaseDetectionModel
from imagebaker import logger

# Import models from the examples folder
# from examples.rtdetr_v2 import RTDetrModelConfig, RTDetrDetectionModel
# from examples.segmentation import (
#     YoloSegmentationModel,
#     YoloSegmentationModelConfig,
# )

# from examples.sam_model import SegmentAnythingModel, SAMModelConfig


class ClassificationModel(BaseClassificationModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    def predict_class(self, image):
        return [get_dummy_prediction_result(self.config.model_type)]


class DetectionModel(BaseDetectionModel):
    def __init__(self, config: DefaultModelConfig):
        super().__init__(config)

    def predict_boxes(self, image):
        return [get_dummy_prediction_result(self.config.model_type)]


return_annotated_image = True
# detector = RTDetrDetectionModel(
#     RTDetrModelConfig(return_annotated_image=return_annotated_image)
# )

# classification = ClassificationModel(
#     DefaultModelConfig(
#         model_type=ModelType.CLASSIFICATION,
#         return_annotated_image=return_annotated_image,
#     )
# )
# segmentation = YoloSegmentationModel(
#     YoloSegmentationModelConfig(return_annotated_image=return_annotated_image)
# )
# prompt = SegmentAnythingModel(
#     SAMModelConfig(return_annotated_image=return_annotated_image)
# )
dummy_detector = DetectionModel(
    DefaultModelConfig(
        model_type=ModelType.DETECTION, return_annotated_image=return_annotated_image
    )
)


LOADED_MODELS = {
    "DummyDetectionModel": dummy_detector,
    # "PromptModel": prompt,
    # "SegmentationModel": segmentation,
    # "RTDetrV2": detector,
    # "ClassificationModel": classification,
}

logger.info(f"Loaded models: {LOADED_MODELS}")
