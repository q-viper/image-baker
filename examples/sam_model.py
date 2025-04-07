import torch
from PIL import Image
import numpy as np
import cv2
from transformers import SamModel, SamProcessor
from loguru import logger
import time
from skimage import measure
from typing import Union, Optional, List


# Import your base classes
from imagebaker.models.base_model import (
    BasePromptModel,
    DefaultModelConfig,
    ModelType,
    PredictionResult,
)
from imagebaker.utils import generate_color_map, mask_to_polygons, annotate_segmentation


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
    return_annotated_image: bool = False

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
            self.config.color_map = generate_color_map()

        logger.info(f"Model running on {self.config.device}")

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
            polygons = mask_to_polygons(mask_np)
            # polygons = np.array(polygons)

            if not polygons:
                continue
            for p, polygon in enumerate(polygons):
                annotated_image = (
                    annotate_segmentation(
                        self._original_image,
                        results,
                        self.config.color_map,
                    )
                    if self.config.return_annotated_image
                    else None
                )

                # Create result
                results.append(
                    PredictionResult(
                        class_name=f"segment_{p}_{i}",
                        class_id=i,
                        score=score_value,
                        mask=np.argwhere(mask_np > 0.5),
                        polygon=np.array(polygon).astype(np.int32),
                        annotation_time=f"{annotation_time:.6f}",
                        annotated_image=annotated_image,
                    )
                )

        return results
