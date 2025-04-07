import torch
from PIL import Image
import numpy as np
from typing import List
import cv2
from transformers import RTDetrV2ForObjectDetection, RTDetrImageProcessor

from loguru import logger
import time
from imagebaker.utils.vis import annotate_detection
from imagebaker.utils import generate_color_map

# Import your base classes
from imagebaker.models.base_model import (
    BaseDetectionModel,
    DefaultModelConfig,
    ModelType,
    PredictionResult,
)
from imagebaker.utils import generate_color_map


class RTDetrModelConfig(DefaultModelConfig):
    model_type: ModelType = ModelType.DETECTION
    model_name: str = "RTDetr-V2"
    model_description: str = (
        "Real-time Detection Transformer V2 model for object detection"
    )
    model_version: str = "r18vd"
    model_author: str = "PekingU"
    model_license: str = "Apache-2.0"
    pretrained_model_name: str = "PekingU/rtdetr_v2_r18vd"
    confidence_threshold: float = 0.5
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    return_annotated_image: bool = True

    # Annotation parameters
    box_thickness: int = 2
    text_thickness: int = 1
    text_scale: float = 0.5
    font_face: int = cv2.FONT_HERSHEY_SIMPLEX
    color_map: dict = {}


class RTDetrDetectionModel(BaseDetectionModel):
    def __init__(self, config: RTDetrModelConfig = RTDetrModelConfig()):
        super().__init__(config)

    def setup(self):
        """Initialize the model and processor"""
        logger.info(f"Loading RTDetr model from {self.config.pretrained_model_name}")

        # Load the image processor and model
        self.processor = RTDetrImageProcessor.from_pretrained(
            self.config.pretrained_model_name
        )
        self.model = RTDetrV2ForObjectDetection.from_pretrained(
            self.config.pretrained_model_name, device_map=self.config.device
        )

        # Update class names from the model
        if hasattr(self.model.config, "id2label"):
            self.config.class_names = list(self.model.config.id2label.values())

        # Generate color map for annotations if not provided
        if not self.config.color_map:
            color_map = generate_color_map(len(self.config.class_names))
            self.config.color_map = {
                class_name: color_map[i]
                for i, class_name in enumerate(self.config.class_names)
            }

        logger.info(f"Loaded model with {len(self.config.class_names)} classes")
        logger.info(f"Model running on {self.config.device}")

    def preprocess(self, image: np.ndarray):
        """Convert numpy array to PIL Image for the RTDetr processor"""
        self._original_image = (
            image.copy() if isinstance(image, np.ndarray) else np.array(image)
        )

        if isinstance(image, np.ndarray):
            # Convert numpy array to PIL Image
            pil_image = Image.fromarray(image.astype("uint8"))
            return pil_image
        return image

    def predict_boxes(self, image):
        """Run object detection on the input image"""
        # Prepare inputs
        inputs = self.processor(images=image, return_tensors="pt")

        # Move inputs to the same device as the model
        inputs = {k: v.to(self.config.device) for k, v in inputs.items()}

        # Run inference
        with torch.no_grad():
            outputs = self.model(**inputs)

        # Get original image dimensions for post-processing
        if isinstance(image, Image.Image):
            image_size = torch.tensor([(image.height, image.width)])
        else:
            # Assuming numpy array with shape (height, width, channels)
            image_size = torch.tensor([(image.shape[0], image.shape[1])])

        # Post-process the outputs
        results = self.processor.post_process_object_detection(
            outputs,
            target_sizes=torch.tensor(self.image_shape)
            .unsqueeze(0)
            .to(self.config.device),
            threshold=self.config.confidence_threshold,
        )

        return results[0]  # Return the first (and only) result

    def postprocess(self, output) -> List[PredictionResult]:
        """Convert model output to PredictionResult objects"""
        results = []

        # Extract outputs
        scores = output["scores"].cpu().numpy()
        labels = output["labels"].cpu().numpy()
        boxes = output["boxes"].cpu().numpy()

        annotation_time = time.time()

        for score, label_id, box in zip(scores, labels, boxes):
            # Get the class name
            class_name = self.model.config.id2label[label_id.item()]

            # Convert box coordinates to integers of x, y, w, h
            x = int(box[0])
            y = int(box[1])
            w = int(box[2] - box[0])
            h = int(box[3] - box[1])

            # Create a PredictionResult
            result = PredictionResult(
                class_name=class_name,
                class_id=int(label_id),
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
