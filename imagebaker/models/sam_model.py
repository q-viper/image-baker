import torch
import requests
from PIL import Image
import numpy as np
import cv2
from transformers import SamModel, SamProcessor
from loguru import logger
import time
import matplotlib.pyplot as plt
from skimage import measure
from typing import Union, Optional, List


# Import your base classes
from imagebaker.models.base_model import (
    BasePromptModel,
    DefaultModelConfig,
    ModelType,
    PredictionResult,
)


class SAMModelConfig(DefaultModelConfig):
    model_type: ModelType = ModelType.PROMPT
    model_name: str = "SAM-HF"
    model_description: str = "Segment Anything Model for instance segmentation"
    model_version: str = "vit_h"
    model_author: str = "Meta/Facebook"
    model_license: str = "Apache-2.0"
    pretrained_model_name: str = (
        "facebook/sam-vit-base"  # Can be replaced with smaller variants
    )
    confidence_threshold: float = 0.5
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    return_annotated_image: bool = True

    # Segmentation specific settings
    points_per_side: int = 32  # Grid size for automatic point generation
    points_per_batch: int = 64  # Number of points to process at once
    pred_iou_thresh: float = 0.88  # Minimum predicted IoU for keeping a mask
    stability_score_thresh: float = 0.95  # Minimum stability score
    box_nms_thresh: float = 0.7  # Box NMS threshold
    crop_n_layers: int = 0  # Number of layers for cropping
    crop_nms_thresh: float = 0.7  # Crop NMS threshold
    crop_overlap_ratio: float = 512 / 1500  # Crop overlap ratio
    crop_n_points_downscale_factor: int = 1  # Downscale factor for crop points
    point_grids: List = None  # Custom point grids
    min_mask_region_area: int = 0  # Minimum number of pixels for a mask
    output_mode: str = (
        "binary_mask"  # Can be 'binary_mask', 'uncompressed_rle', 'coco_rle'
    )

    # Polygon simplification parameters
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


class SegmentAnythingModel(BasePromptModel):
    def __init__(self, config: SAMModelConfig):
        super().__init__(config)

    def setup(self):
        """Initialize the SAM model and processor"""
        logger.info(f"Loading SAM model from {self.config.pretrained_model_name}")

        # Load the processor and model
        self.processor = SamProcessor.from_pretrained(self.config.pretrained_model_name)
        self.model = SamModel.from_pretrained(
            self.config.pretrained_model_name, device_map=self.config.device
        )

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
        """Preprocess the image for SAM model"""
        self._original_image = (
            image.copy() if isinstance(image, np.ndarray) else np.array(image)
        )

        if isinstance(image, np.ndarray):
            # Convert numpy array to PIL Image
            pil_image = Image.fromarray(image.astype("uint8"))
            return pil_image
        return image

    def predict_prompt(
        self,
        image: Union[np.ndarray, Image.Image],
        input_points: Optional[List[List[float]]] = None,
        input_boxes: Optional[List[List[float]]] = None,
        label_hints: Optional[list[int]] = None,
        multimask_output: bool = False,
    ):
        """Run segmentation with optional prompts

        Args:
            image: Input image (PIL or numpy array)
            input_points: List of [x,y] coordinates for point prompts
            input_boxes: List of [x1,y1,x2,y2] coordinates for box prompts
            input_labels: List of labels (1 for foreground, 0 for background)
            multimask_output: Whether to return multiple masks per prompt
        """
        # Preprocess image
        image = self.preprocess(image)

        # Prepare inputs
        inputs = self.processor(
            image,
            input_points=input_points,
            input_boxes=input_boxes,
            input_labels=label_hints,
            return_tensors="pt",
        ).to(self.config.device)

        # Run inference
        with torch.no_grad():
            outputs = self.model(**inputs)

        # Process masks
        masks = self.processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(),
            inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu(),
        )

        # Get scores (handle both single and multi-mask cases)
        if multimask_output:
            scores = outputs.iou_scores  # Shape: (batch_size, num_masks)
        else:
            scores = outputs.iou_scores.squeeze(-1)  # Shape: (batch_size,)

        return {
            "masks": masks,
            "scores": scores,
        }

    def mask_to_polygons(self, mask: np.ndarray) -> List[List[List[int]]]:
        """
        Convert a binary mask to a list of polygons.
        Each polygon is a list of [x, y] coordinates.

        Args:
            mask: Binary mask as numpy array

        Returns:
            List of polygons, where each polygon is a list of [x, y] coordinates
        """
        # Find contours in the mask
        contours = measure.find_contours(mask, 0.5)

        # Convert to polygon format and simplify
        polygons = []
        for contour in contours:
            # Skimage find_contours returns points in (row, col) format, convert to (x, y)
            contour = np.fliplr(contour)

            # Convert to integer coordinates
            contour = contour.astype(np.int32)

            # Simplify polygon with Douglas-Peucker algorithm
            epsilon = self.config.polygon_epsilon
            approx = cv2.approxPolyDP(contour.reshape(-1, 1, 2), epsilon, True)
            approx = approx.reshape(-1, 2)

            # Calculate polygon area
            area = cv2.contourArea(approx.reshape(-1, 1, 2))

            # Filter out small polygons
            if area >= self.config.min_polygon_area:
                # Convert to list format
                poly = approx.tolist()
                polygons.append(poly)

        # Limit number of polygons
        polygons = sorted(
            polygons,
            key=lambda p: cv2.contourArea(np.array(p).reshape(-1, 1, 2)),
            reverse=True,
        )
        return polygons[: self.config.max_polygons_per_mask]

    def annotate_image(
        self, image: np.ndarray, results: List[PredictionResult]
    ) -> np.ndarray:
        """
        Draw segmentation masks and contours on the image

        Args:
            image: The original image as a numpy array
            results: List of PredictionResult objects

        Returns:
            Annotated image as a numpy array
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
                # Convert polygon to numpy array
                poly_np = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                # Fill polygon
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

            # Draw text background
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
            annotated_image, 1.0, mask_overlay, self.config.mask_opacity, 0
        )

        return annotated_image

    def postprocess(self, outputs) -> List[PredictionResult]:
        """Convert model outputs to PredictionResult objects"""
        results = []
        masks = outputs["masks"][0]  # Get first batch item
        scores = outputs["scores"][0]

        annotation_time = time.time()

        for i, (mask, score) in enumerate(zip(masks, scores)):
            # Handle multi-mask case by taking best score
            if isinstance(score, torch.Tensor) and len(score) > 1:
                best_idx = score.argmax()
                mask = mask[best_idx]
                score = score[best_idx]

            score_value = (
                score.item() if isinstance(score, torch.Tensor) else float(score)
            )

            if score_value < self.config.confidence_threshold:
                continue

            # Convert mask to polygons
            mask_np = mask.cpu().numpy()
            polygons = self.mask_to_polygons(mask_np)
            # polygons = np.array(polygons)

            if not polygons:
                continue
            for p, polygon in enumerate(polygons):

                # Create result
                results.append(
                    PredictionResult(
                        class_name=f"segment_{p}_{i}",
                        class_id=i,
                        score=score_value,
                        mask=np.argwhere(mask_np > 0.5),
                        polygon=np.array(polygon).astype(np.int32),
                        annotation_time=f"{annotation_time:.6f}",
                    )
                )

        # Add annotated image if requested
        if (
            self.config.return_annotated_image
            and results
            and hasattr(self, "_original_image")
        ):
            annotated = self.annotate_image(self._original_image, results)
            for r in results:
                r.annotated_image = annotated

        return results


# Example usage
if __name__ == "__main__":
    import time
    import matplotlib.pyplot as plt

    # Create configuration
    config = SAMModelConfig()

    # Create model
    model = SegmentAnythingModel(config)

    # Test with an image from URL
    url = "http://images.cocodataset.org/val2017/000000039769.jpg"
    response = requests.get(url, stream=True)
    image = Image.open(response.raw)

    # Convert to numpy array for compatibility with your pipeline
    image_np = np.array(image)

    # Run prediction
    t0 = time.time()
    prediction_results = model.predict(image_np)
    t1 = time.time()

    print(f"Total prediction time: {t1-t0:.4f} seconds")
    print(f"Found {len(prediction_results)} segments:")

    for result in prediction_results:
        print(
            f"Segment {result.class_id}: score={result.score:.2f}, polygons={len(result.polygon)}"
        )

    # Display the annotated image if available
    if prediction_results and prediction_results[0].annotated_image is not None:
        plt.figure(figsize=(12, 8))
        plt.imshow(
            cv2.cvtColor(prediction_results[0].annotated_image, cv2.COLOR_BGR2RGB)
        )
        plt.axis("off")
        plt.title(f"Segmentation Results: {len(prediction_results)} segments")
        plt.show()
