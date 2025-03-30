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
    return_annotated_image: bool = True

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
            self.generate_color_map()

        logger.info(f"Model running on {self.config.device}")

    def generate_color_map(self, num_colors: int = 20):
        """Generate a color map for the segmentation masks"""
        np.random.seed(42)  # For reproducible colors

        colors = {}
        for i in range(num_colors):
            # Generate distinct colors with good visibility
            # Using HSV color space for better distribution
            hue = i / num_colors
            saturation = 0.8 + np.random.random() * 0.2
            value = 0.8 + np.random.random() * 0.2

            # Convert HSV to BGR (OpenCV uses BGR)
            hsv_color = np.array(
                [[[hue * 180, saturation * 255, value * 255]]], dtype=np.uint8
            )
            bgr_color = cv2.cvtColor(hsv_color, cv2.COLOR_HSV2BGR)[0][0]

            # Store as (B, G, R) tuple
            colors[i] = (int(bgr_color[0]), int(bgr_color[1]), int(bgr_color[2]))

        self.config.color_map = colors

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

    def mask_to_polygons(self, mask: np.ndarray) -> List[List[Tuple[int, int]]]:
        """
        Convert a binary mask to a list of polygons.
        Each polygon is a list of (x, y) coordinates.
        """
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        polygons = []
        for contour in contours:
            # Simplify polygon with Douglas-Peucker algorithm
            epsilon = self.config.polygon_epsilon
            approx = cv2.approxPolyDP(contour, epsilon, True)
            approx = approx.squeeze().tolist()
            # float to int
            approx = [(int(x), int(y)) for x, y in approx]

            # Calculate polygon area
            area = cv2.contourArea(np.array(approx))

            # Filter out small polygons
            if area >= self.config.min_polygon_area:
                polygons.append(approx)

        # Limit number of polygons
        polygons = sorted(
            polygons, key=lambda p: cv2.contourArea(np.array(p)), reverse=True
        )
        return polygons[: self.config.max_polygons_per_mask]

    def annotate_image(
        self, image: np.ndarray, results: List[PredictionResult]
    ) -> np.ndarray:
        """
        Draw segmentation masks and contours on the image
        """
        annotated_image = image.copy()
        mask_overlay = np.zeros_like(image)

        for i, result in enumerate(results):
            if (result.polygon is not None) or not result.mask:
                continue

            # Get color for this mask
            color_idx = i % len(self.config.color_map)
            color = self.config.color_map[color_idx]

            # Create mask from polygons
            mask = np.zeros((image.shape[0], image.shape[1]), dtype=np.uint8)
            for poly in result.polygon:
                poly_np = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(mask, [poly_np], 1)

            # Apply color to mask overlay
            color_mask = np.zeros_like(image)
            color_mask[mask == 1] = color
            mask_overlay = cv2.addWeighted(mask_overlay, 1.0, color_mask, 1.0, 0)

            # Draw contours
            for poly in result.polygon:
                poly_np = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(
                    annotated_image,
                    [poly_np],
                    True,
                    color,
                    self.config.contour_thickness,
                )

            # Add label text
            label_position = (
                result.polygon[0][0]
                if result.polygon and result.polygon[0]
                else [10, 10]
            )
            label_text = f"{result.class_id}: {result.score:.2f}"

            # Draw text background
            (text_width, text_height), baseline = cv2.getTextSize(
                label_text,
                self.config.font_face,
                self.config.text_scale,
                self.config.text_thickness,
            )

            cv2.rectangle(
                annotated_image,
                (label_position[0], label_position[1] - text_height - 5),
                (label_position[0] + text_width, label_position[1]),
                color,
                -1,  # Fill the rectangle
            )

            # Draw text
            cv2.putText(
                annotated_image,
                label_text,
                (label_position[0], label_position[1] - 5),
                self.config.font_face,
                self.config.text_scale,
                (255, 255, 255),  # White text
                self.config.text_thickness,
            )

        # Blend mask overlay with original image
        annotated_image = cv2.addWeighted(
            annotated_image,
            1.0,
            mask_overlay,
            self.config.mask_opacity,
            0,
        )

        return annotated_image

    def postprocess(self, outputs) -> List[PredictionResult]:
        """Convert model outputs to PredictionResult objects with polygons"""
        results = []
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
                polygon = self.mask_to_polygons(mask)

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
            annotated_image = self.annotate_image(self._original_image, results)

            # Update all results with the same annotated image
            for result in results:
                result.annotated_image = annotated_image

        return results
