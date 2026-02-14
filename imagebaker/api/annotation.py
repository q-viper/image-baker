"""
Annotation API

Provides simplified annotation creation and manipulation.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPolygonF

from imagebaker import logger
from imagebaker.core.defs import Annotation as CoreAnnotation


class AnnotationType(Enum):
    """Annotation types supported by ImageBaker."""
    POINT = "point"
    RECTANGLE = "rectangle"
    POLYGON = "polygon"
    MASK = "mask"


def create_annotation(
    label: str,
    annotation_type: AnnotationType,
    coordinates: List[Tuple[float, float]],
    color: Optional[Tuple[int, int, int]] = None,
    annotation_id: Optional[int] = None,
    score: Optional[float] = None,
    caption: str = ""
) -> CoreAnnotation:
    """
    Create an annotation.
    
    Args:
        label: Annotation label/class name
        annotation_type: Type of annotation (POINT, RECTANGLE, POLYGON, MASK)
        coordinates: List of (x, y) coordinates
            - For POINT: [(x, y), ...]
            - For RECTANGLE: [(x1, y1), (x2, y2)] (top-left and bottom-right)
            - For POLYGON: [(x1, y1), (x2, y2), ...] (vertices)
        color: Optional RGB color tuple (defaults to white)
        annotation_id: Optional annotation ID (auto-generated if None)
        score: Optional confidence score
        caption: Optional text caption
        
    Returns:
        CoreAnnotation instance
        
    Example:
        >>> # Create a rectangle annotation
        >>> ann = create_annotation(
        ...     label="person",
        ...     annotation_type=AnnotationType.RECTANGLE,
        ...     coordinates=[(100, 100), (200, 200)],
        ...     color=(255, 0, 0)
        ... )
        
        >>> # Create a polygon annotation
        >>> ann = create_annotation(
        ...     label="object",
        ...     annotation_type=AnnotationType.POLYGON,
        ...     coordinates=[(10, 10), (50, 10), (50, 50), (10, 50)],
        ... )
    """
    if color is None:
        color = (255, 255, 255)
    
    if annotation_id is None:
        annotation_id = hash(datetime.now())
    
    q_color = QColor(*color)
    
    # Create base annotation
    annotation = CoreAnnotation(
        annotation_id=annotation_id,
        label=label,
        color=q_color,
        score=score,
        caption=caption,
        is_complete=True,
        annotation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    
    # Set coordinates based on type
    if annotation_type == AnnotationType.POINT:
        annotation.points = [QPointF(x, y) for x, y in coordinates]
        logger.debug(f"Created POINT annotation with {len(coordinates)} points")
        
    elif annotation_type == AnnotationType.RECTANGLE:
        if len(coordinates) != 2:
            raise ValueError("RECTANGLE requires exactly 2 coordinates (top-left, bottom-right)")
        x1, y1 = coordinates[0]
        x2, y2 = coordinates[1]
        annotation.rectangle = QRectF(
            min(x1, x2), min(y1, y2),
            abs(x2 - x1), abs(y2 - y1)
        )
        logger.debug(f"Created RECTANGLE annotation at ({x1}, {y1}) to ({x2}, {y2})")
        
    elif annotation_type == AnnotationType.POLYGON:
        if len(coordinates) < 3:
            raise ValueError("POLYGON requires at least 3 coordinates")
        annotation.polygon = QPolygonF([QPointF(x, y) for x, y in coordinates])
        logger.debug(f"Created POLYGON annotation with {len(coordinates)} vertices")
        
    elif annotation_type == AnnotationType.MASK:
        # For mask, coordinates should be polygon points
        annotation.polygon = QPolygonF([QPointF(x, y) for x, y in coordinates])
        logger.debug(f"Created MASK annotation with {len(coordinates)} points")
    
    else:
        raise ValueError(f"Unsupported annotation type: {annotation_type}")
    
    return annotation


def rectangle_annotation(
    label: str,
    x1: float, y1: float,
    x2: float, y2: float,
    color: Optional[Tuple[int, int, int]] = None,
    score: Optional[float] = None
) -> CoreAnnotation:
    """
    Convenience function to create a rectangle annotation.
    
    Args:
        label: Annotation label
        x1, y1: Top-left corner
        x2, y2: Bottom-right corner
        color: Optional RGB color
        score: Optional confidence score
        
    Returns:
        CoreAnnotation instance
    """
    return create_annotation(
        label=label,
        annotation_type=AnnotationType.RECTANGLE,
        coordinates=[(x1, y1), (x2, y2)],
        color=color,
        score=score
    )


def polygon_annotation(
    label: str,
    points: List[Tuple[float, float]],
    color: Optional[Tuple[int, int, int]] = None,
    score: Optional[float] = None
) -> CoreAnnotation:
    """
    Convenience function to create a polygon annotation.
    
    Args:
        label: Annotation label
        points: List of (x, y) vertices
        color: Optional RGB color
        score: Optional confidence score
        
    Returns:
        CoreAnnotation instance
    """
    return create_annotation(
        label=label,
        annotation_type=AnnotationType.POLYGON,
        coordinates=points,
        color=color,
        score=score
    )


def point_annotation(
    label: str,
    points: List[Tuple[float, float]],
    color: Optional[Tuple[int, int, int]] = None,
    score: Optional[float] = None
) -> CoreAnnotation:
    """
    Convenience function to create a point annotation.
    
    Args:
        label: Annotation label
        points: List of (x, y) points
        color: Optional RGB color
        score: Optional confidence score
        
    Returns:
        CoreAnnotation instance
    """
    return create_annotation(
        label=label,
        annotation_type=AnnotationType.POINT,
        coordinates=points,
        color=color,
        score=score
    )
