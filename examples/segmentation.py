# based on https://docs.ultralytics.com/tasks/segment/#how-do-i-load-and-validate-a-pretrained-yolo-segmentation-model

from typing import List, Tuple
import numpy as np
import cv2
from loguru import logger
import time
from ultralytics import YOLO
import torch


from imagebaker.models.base_model import (
    BaseSegmentationModel,
    DefaultModelConfig,
    ModelType,
    PredictionResult,
)
from imagebaker.utils import mask_to_polygons, annotate_segmentation, generate_color_map


class YoloSegmentationModelConfig(DefaultModelConfig):
    model_type: ModelType = ModelType.SEGMENTATION
    model_name: str = "YOLOv8-Segmentation"
    model_description: str = "YOLOv8 model for instance segmentation"
    model_version: str = "yolov8n-seg"
    model_author: str = "Ultralytics"
    model_license: str = "AGPL-3.0"
    pretrained_model_name: str = "yolo11n-seg.pt"
    confidence_threshold: float = 0.5
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    return_annotated_image: bool = False

    # Segmentation specific settings
    polygon_epsilon: float = 1.0  # Douglas-Peucker algorithm epsilon
    min_polygon_area: int = 100  # Minimum area for a polygon to be considered
    max_polygons_per_mask: int = 5  # Maximum number of polygons per mask

    # Annotation parameters
    mask_opacity: float = 0.5  # Opacity of mask overlay
    contour_thickness: int = 2  # Thickness of contour lines
    text_thickness: int = 1  # Thickness of text
    text_scale: float = 0.5  # Text scale
    font_face: int = cv2.FONT_HERSHEY_SIMPLEX
    color_map: dict = {}  # Will be auto-generated


class YoloSegmentationModel(BaseSegmentationModel):
    def __init__(
        self, config: YoloSegmentationModelConfig = YoloSegmentationModelConfig()
    ):
        super().__init__(config)

    def setup(self):
        """Initialize the YOLO model"""
        logger.info(f"Loading YOLO model from {self.config.pretrained_model_name}")

        # Load the YOLO model
        self.model = YOLO(self.config.pretrained_model_name)

        # Generate color map for annotations if not provided
        if not self.config.color_map:
            self.config.color_map = generate_color_map()

        logger.info(f"Model running on {self.config.device}")

    def preprocess(self, image: np.ndarray):
        """Preprocess the image for the model"""
        self._original_image = (
            image.copy() if isinstance(image, np.ndarray) else np.array(image)
        )
        return image

    def predict_mask(self, image):
        """Run segmentation on the input image using YOLO"""
        # Run inference
        results = self.model(image)

        # Extract masks, polygons, and scores
        masks = []
        polygons = []
        scores = []
        class_ids = []
        for result in results:
            if result.masks is not None:
                for mask in result.masks.data:
                    masks.append(mask.cpu().numpy())
                for polygon in result.masks.xy:
                    polygons.append(polygon.tolist())
                scores.extend(result.boxes.conf.cpu().numpy().tolist())

                class_ids.extend(result.boxes.cls.cpu().numpy().tolist())

        return {
            "masks": masks,
            "polygons": polygons,
            "scores": scores,
            "class_ids": class_ids,
        }

    def postprocess(self, outputs) -> List[PredictionResult]:
        """Convert model outputs to PredictionResult objects with polygons"""
        results: list[PredictionResult] = []
        masks = outputs["masks"]
        polygons = outputs["polygons"]
        scores = outputs["scores"]
        class_ids = outputs["class_ids"]

        annotation_time = time.time()

        for i, (mask, polygon, score) in enumerate(zip(masks, polygons, scores)):
            # Skip masks with low scores
            if score < self.config.confidence_threshold:
                continue

            # Convert mask to polygons (if not already provided)
            if not polygon:
                polygon = mask_to_polygons(mask)

            if not polygon:  # Skip if no valid polygons found
                continue

            # Create a flattened mask for the result
            mask_coords = np.argwhere(mask > 0.5)
            mask_coords = mask_coords.tolist() if len(mask_coords) > 0 else None
            polygon = np.array(polygon).astype(np.int32)

            # Create a PredictionResult
            result = PredictionResult(
                class_name=self.model.names[class_ids[i]],
                class_id=i,
                score=float(score),
                polygon=polygon,
                annotation_time=f"{annotation_time:.6f}",
            )

            results.append(result)

        # If needed, add annotated image
        if (
            self.config.return_annotated_image
            and len(results) > 0
            and hasattr(self, "_original_image")
        ):
            annotated_image = annotate_segmentation(
                self._original_image, results, self.config.color_map
            )

            # Update all results with the same annotated image
            for result in results:
                result.annotated_image = annotated_image

        return results
