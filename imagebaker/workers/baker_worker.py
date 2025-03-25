from PySide6.QtGui import QImage, QPainter, QTransform, QPolygonF
from PySide6.QtCore import (
    Qt,
    QPoint,
    QPointF,
    Signal,
    QRectF,
    QObject,
)
import cv2
import sys
from pathlib import Path

from imagebaker.core.defs.defs import BakingResult, Annotation
from imagebaker.utils.transform_mask import mask_to_polygons, mask_to_rectangles
from imagebaker import logger
from imagebaker.utils.image import qpixmap_to_numpy


class BakerWorker(QObject):
    finished = Signal(BakingResult)
    error = Signal(str)

    def __init__(
        self,
        layers: list["Layer"],
        top_left: QPointF,
        bottom_right: QPointF,
        filename: Path,
    ):
        super().__init__()
        self.layers = layers

        self.top_left = top_left
        self.bottom_right = bottom_right
        self.filename = filename

    def process(self):
        top_left = QPointF(sys.maxsize, sys.maxsize)
        bottom_right = QPointF(-sys.maxsize, -sys.maxsize)
        try:
            # Compute the bounding box using transformations
            for layer in self.layers:
                if layer.visible and not layer.image.isNull():
                    transform = QTransform()
                    transform.translate(layer.position.x(), layer.position.y())
                    transform.rotate(layer.rotation)
                    transform.scale(layer.scale_x, layer.scale_y)

                    original_rect = QRectF(QPointF(0, 0), layer.image.size())
                    transformed_rect = transform.mapRect(original_rect)

                    top_left.setX(min(top_left.x(), transformed_rect.left()))
                    top_left.setY(min(top_left.y(), transformed_rect.top()))
                    bottom_right.setX(max(bottom_right.x(), transformed_rect.right()))
                    bottom_right.setY(max(bottom_right.y(), transformed_rect.bottom()))

            # 2. Create the output image
            width = int(bottom_right.x() - top_left.x())
            height = int(bottom_right.y() - top_left.y())
            if width <= 0 or height <= 0:
                return
            image = QImage(width, height, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            masks = []
            mask_names = []
            new_annotations = []

            painter = QPainter(image)
            try:
                painter.setRenderHints(
                    QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                )
                for layer in self.layers:
                    if (
                        layer.visible
                        and not layer.image.isNull()
                        and layer.opacity > 0
                        and layer.allow_annotation_export
                    ):
                        # Draw layer to main image
                        painter.save()
                        painter.translate(layer.position - top_left)
                        painter.rotate(layer.rotation)
                        painter.scale(layer.scale_x, layer.scale_y)
                        painter.setOpacity(layer.opacity)
                        painter.drawPixmap(QPoint(0, 0), layer.image)
                        painter.restore()

                        # Create layer mask
                        layer_mask = QImage(width, height, QImage.Format_ARGB32)
                        layer_mask.fill(Qt.transparent)
                        mask_painter = QPainter(layer_mask)
                        mask_painter.setRenderHints(
                            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                        )
                        mask_painter.translate(layer.position - top_left)
                        mask_painter.rotate(layer.rotation)
                        mask_painter.scale(layer.scale_x, layer.scale_y)
                        mask_painter.drawPixmap(QPoint(0, 0), layer.image)
                        mask_painter.end()

                        # Convert mask to 8-bit
                        mask_arr = qpixmap_to_numpy(layer_mask)
                        alpha_channel = mask_arr[
                            :, :, 3
                        ].copy()  # Extract the alpha channel (0th index)

                        # Binarize the mask (0 or 255)
                        alpha_channel[alpha_channel > 0] = 255

                        # Save the 8-bit mask
                        # cv2.imwrite(f"{layer.name}_annotated.png", alpha_channel)
                        # logger.info(f"Saved 8-bit mask for {layer.name}")
                        masks.append(alpha_channel)
                        mask_names.append(layer.name)
                        ann: Annotation = layer.annotations[0]
                        mask_arr = cv2.cvtColor(alpha_channel, cv2.COLOR_GRAY2BGR)
                        new_annotation = Annotation(
                            label=ann.label,
                            color=ann.color,
                            annotation_id=ann.annotation_id,
                        )

                        if ann.points:
                            new_annotation.points = ann.points
                        elif ann.rectangle:
                            xywhs = mask_to_rectangles(
                                alpha_channel, merge_rectangles=True
                            )
                            new_annotation.rectangle = QRectF(
                                xywhs[0][0],
                                xywhs[0][1],
                                xywhs[0][2],
                                xywhs[0][3],
                            )
                        elif ann.polygon:
                            polygon = mask_to_polygons(
                                alpha_channel, merge_polygons=True
                            )
                            poly = QPolygonF([QPointF(p[0], p[1]) for p in polygon[0]])
                            new_annotation.polygon = poly
                        else:
                            logger.info("No annotation found")
                        new_annotations.append(new_annotation)

            finally:
                painter.end()
            # image.save(filename)
            self.finished.emit(
                BakingResult(self.filename, image, masks, mask_names, new_annotations)
            )

        except Exception as e:
            logger.info(e)
            self.error.emit(str(e))
