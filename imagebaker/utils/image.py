import numpy as np
from PySide6.QtGui import QPixmap, QImage
import cv2

from imagebaker.core.defs.defs import Annotation


def qpixmap_to_numpy(pixmap: QPixmap | QImage) -> np.ndarray:
    """
    Convert QPixmap to RGBA numpy array.

    Args:
        pixmap: The QPixmap to convert

    Returns:
        numpy.ndarray: Array with shape (height, width, 4) containing RGBA values
    """

    if isinstance(pixmap, QPixmap):
        # Convert QPixmap to QImage first
        image = pixmap.toImage()
    else:
        image = pixmap
    # Convert to Format_RGBA8888 for consistent channel ordering
    if image.format() != QImage.Format_RGBA8888:
        image = image.convertToFormat(QImage.Format_RGBA8888)

    width = image.width()
    height = image.height()

    # Get the bytes directly from the QImage
    ptr = image.constBits()

    # Convert memoryview to bytes and then to numpy array
    bytes_data = bytes(ptr)
    arr = np.frombuffer(bytes_data, dtype=np.uint8).reshape((height, width, 4))

    return arr


def draw_annotations(image: np.ndarray, annotations: list[Annotation]) -> np.ndarray:
    """
    Draw annotations on an image.

    Args:
        image (np.ndarray): Image to draw on.
        annotations (list[Annotation]): List of annotations to draw.

    Returns:
        np.ndarray: Image with annotations drawn.
    """
    for i, ann in enumerate(annotations):
        if ann.rectangle:
            cv2.rectangle(
                image,
                (int(ann.rectangle.x()), int(ann.rectangle.y())),
                (
                    int(ann.rectangle.x() + ann.rectangle.width()),
                    int(ann.rectangle.y() + ann.rectangle.height()),
                ),
                (0, 255, 0),
                2,
            )
            rect_center = ann.rectangle.center()

            cv2.putText(
                image,
                ann.label,
                (int(rect_center.x()), int(rect_center.y())),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
        elif ann.polygon:
            cv2.polylines(
                image,
                [np.array([[int(p.x()), int(p.y())] for p in ann.polygon])],
                True,
                (0, 255, 0),
                2,
            )
            polygon_center = ann.polygon.boundingRect().center()
            cv2.putText(
                image,
                ann.label,
                (int(polygon_center.x()), int(polygon_center.y())),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
        elif ann.points:
            for p in ann.points:
                cv2.circle(image, (int(p.x()), int(p.y())), 5, (0, 255, 0), -1)
            cv2.putText(
                image,
                ann.label,
                (int(ann.points[0].x()), int(ann.points[0].y())),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
    return image
