
import cv2
import numpy as np


def mask_to_polygons(
    mask: np.ndarray,
    min_polygon_area: float = 10,
    merge_polygons: bool = False,
    merge_distance: int = 5,  # Max distance between polygons to merge
) -> list[list[tuple[int, int]]]:
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
) -> list[tuple[int, int, int, int]]:
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
        x0 = min(r[0] for r in rectangles)
        y0 = min(r[1] for r in rectangles)
        x1 = max(r[0] + r[2] for r in rectangles)
        y1 = max(r[1] + r[3] for r in rectangles)
        rectangles = [(int(x0), int(y0), int(x1 - x0), int(y1 - y0))]

    return rectangles


def merge_contours_with_bridge(
    contours: list[np.ndarray] | list[list[list[float]]],
) -> np.ndarray:
    """Merge disconnected closed contours into a single closed polygon.

    Uses zero-width closest-vertex bridges (same convention as Ultralytics YOLO
    segment merging) so a multi-part occluded object remains one instance.
    """
    pts_list: list[np.ndarray] = []
    for contour in contours or []:
        arr = np.asarray(contour, dtype=np.float64)
        if arr.ndim == 3 and arr.shape[1] == 1 and arr.shape[2] == 2:
            arr = arr[:, 0, :]
        if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 3:
            continue
        # Normalize orientation via signed shoelace area so island areas add up.
        x = arr[:, 0]
        y = arr[:, 1]
        signed_area = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
        if signed_area < 0:
            arr = arr[::-1].copy()
        pts_list.append(arr)

    if not pts_list:
        return np.empty((0, 2), dtype=np.float64)
    if len(pts_list) == 1:
        return pts_list[0]

    def _poly_area(p: np.ndarray) -> float:
        return abs(
            0.5
            * float(
                np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])
            )
        )

    pts_list.sort(key=_poly_area, reverse=True)
    merged = pts_list[0]
    remaining = pts_list[1:]

    while remaining:
        best_dist2 = float("inf")
        best_r_idx = 0
        best_i = 0
        best_j = 0
        for r_idx, cand in enumerate(remaining):
            diff = merged[:, None, :] - cand[None, :, :]
            dist2 = np.sum(diff * diff, axis=2)
            flat_idx = int(np.argmin(dist2))
            i, j = divmod(flat_idx, dist2.shape[1])
            d2 = float(dist2[i, j])
            if d2 < best_dist2:
                best_dist2 = d2
                best_r_idx = r_idx
                best_i = i
                best_j = j

        cand = remaining.pop(best_r_idx)
        c_rot = np.roll(cand, -best_j, axis=0)
        merged = np.vstack(
            [
                merged[: best_i + 1],
                c_rot,
                c_rot[0:1],
                merged[best_i : best_i + 1],
                merged[best_i + 1 :],
            ]
        )

    return merged
