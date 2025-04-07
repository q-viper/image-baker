from imagebaker.core.defs import PredictionResult

import cv2
import numpy as np
from typing import List


def annotate_detection(
    image: np.ndarray,
    results: List[PredictionResult],
    color_map: dict[str, tuple[int, int, int]],
    box_thickness: int = 2,
    font_face: int = cv2.FONT_HERSHEY_SIMPLEX,
    text_scale: float = 0.5,
    text_thickness: int = 1,
) -> np.ndarray:
    """
    Draw bounding boxes and labels on the image

    Args:
        image: The original image as a numpy array
        results: List of PredictionResult objects

    Returns:
        Annotated image as a numpy array
    """
    annotated_image = image.copy()

    for result in results:
        # Extract data from result
        box = result.rectangle  # [x1, y1, x2, y2]
        score = result.score
        class_name = result.class_name

        if not box:
            continue

        # Get color for this class
        color = color_map.get(
            result.class_name, (0, 255, 0)
        )  # Default to green if not found

        # Draw bounding box
        cv2.rectangle(
            annotated_image,
            (box[0], box[1]),
            (box[2], box[3]),
            color,
            box_thickness,
        )

        # Prepare label text with class name and score
        label_text = f"{class_name}: {score:.2f}"

        # Calculate text size to create background rectangle
        (text_width, text_height), baseline = cv2.getTextSize(
            label_text,
            font_face,
            text_scale,
            text_thickness,
        )

        # Draw text background
        cv2.rectangle(
            annotated_image,
            (box[0], box[1] - text_height - 5),
            (box[0] + text_width, box[1]),
            color,
            -1,  # Fill the rectangle
        )

        # Draw text
        cv2.putText(
            annotated_image,
            label_text,
            (box[0], box[1] - 5),
            font_face,
            text_scale,
            (255, 255, 255),  # White text
            text_thickness,
        )

    return annotated_image


def annotate_segmentation(
    image: np.ndarray,
    results: List[PredictionResult],
    color_map: dict[int, tuple[int, int, int]],
    contour_thickness: int = 2,
    mask_opacity: float = 0.5,
    font_face: int = cv2.FONT_HERSHEY_SIMPLEX,
    text_scale: float = 0.5,
    text_thickness: int = 1,
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
        color_idx = i % len(color_map)
        color = color_map[color_idx]

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
                contour_thickness,
            )

        # Add label text
        label_position = (
            result.polygon[0][0] if result.polygon and result.polygon[0] else [10, 10]
        )
        label_text = f"{result.class_id}: {result.score:.2f}"

        # Draw text background
        (text_width, text_height), baseline = cv2.getTextSize(
            label_text,
            font_face,
            text_scale,
            text_thickness,
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
            font_face,
            text_scale,
            (255, 255, 255),  # White text
            text_thickness,
        )

    # Blend mask overlay with original image
    annotated_image = cv2.addWeighted(
        annotated_image,
        1.0,
        mask_overlay,
        mask_opacity,
        0,
    )

    return annotated_image
