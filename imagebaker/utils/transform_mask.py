import cv2
import numpy as np
from typing import List, Tuple


def mask_to_polygons(
    mask: np.ndarray,
    min_polygon_area: float = 10,
    merge_polygons: bool = False,
    merge_distance: int = 5,  # Max distance between polygons to merge
) -> List[List[Tuple[int, int]]]:
    """
    Convert a binary mask to a list of polygons.
    Each polygon is a list of (x, y) coordinates.

    Args:
        mask (np.ndarray): Binary mask (0 or 255).
        min_polygon_area (float): Minimum area for a polygon to be included.
        merge_polygons (bool): If True, merges nearby/overlapping polygons.
        merge_distance (int): Max distance between polygons to merge (if merge_polygons=True).

    Returns:
        List[List[Tuple[int, int]]]: List of polygons, each represented as a list of (x, y) points.
    """
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    polygons = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area >= min_polygon_area:
            polygons.append(contour)

    # Sort polygons by area (descending)
    polygons = sorted(
        polygons, key=lambda p: cv2.contourArea(np.array(p)), reverse=True
    )

    # Merge polygons if requested
    if merge_polygons and len(polygons) > 1:
        # Use morphological dilation to merge nearby regions
        kernel = np.ones((merge_distance, merge_distance), np.uint8)
        merged_mask = cv2.dilate(mask, kernel, iterations=1)

        # Re-extract contours after merging
        merged_contours, _ = cv2.findContours(
            merged_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Filter again by area
        merged_polygons = []
        for contour in merged_contours:
            area = cv2.contourArea(contour)
            if area >= min_polygon_area:
                merged_polygons.append(contour)

        polygons = merged_polygons

    # Convert contours to list of points
    result = []
    for poly in polygons:
        points = poly.squeeze().tolist()  # Remove extra dimensions
        if len(points) >= 3:  # Ensure it's a valid polygon
            result.append([(int(x), int(y)) for x, y in points])

    return result


def mask_to_rectangles(
    mask: np.ndarray,
    merge_rectangles: bool = False,
    merge_threshold: int = 1,
    merge_epsilon: float = 0.5,
) -> List[Tuple[int, int, int, int]]:
    """
    Convert a binary mask to a list of rectangles.
    Each rectangle is a tuple of (x, y, w, h).

    Args:
        mask (np.ndarray): Binary mask (0 or 255).
        merge_rectangles (bool): If True, merges overlapping or nearby rectangles.
        merge_threshold (int): Min number of rectangles to merge into one.
        merge_epsilon (float): Controls how close rectangles must be to merge (0.0 to 1.0).

    Returns:
        List[Tuple[int, int, int, int]]: List of rectangles, each as (x, y, w, h).
    """
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    rectangles = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        rectangles.append((x, y, w, h))

    if merge_rectangles and len(rectangles) > 1:
        # Convert rectangles to the format expected by groupRectangles
        rects = np.array(rectangles)
        # groupRectangles requires [x, y, w, h] format
        grouped_rects, _ = cv2.groupRectangles(
            rects.tolist(), merge_threshold, merge_epsilon
        )
        rectangles = [tuple(map(int, rect)) for rect in grouped_rects]

    return rectangles
