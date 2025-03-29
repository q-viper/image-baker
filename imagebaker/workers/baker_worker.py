from PySide6.QtGui import QImage, QPainter, QTransform, QPolygonF
from PySide6.QtCore import (
    Qt,
    QPoint,
    QPointF,
    Signal,
    QRectF,
    QObject,
)
import sys
from pathlib import Path

from imagebaker.core.defs.defs import BakingResult, Annotation
from imagebaker.utils.transform_mask import mask_to_polygons, mask_to_rectangles
from imagebaker import logger
from imagebaker.utils.image import qpixmap_to_numpy


class BakerWorker(QObject):
    finished = Signal(list)  # Emit a list of BakingResult objects
    error = Signal(str)

    def __init__(
        self,
        states: dict[int, list["LayerState"]],
        layers: list["Layer"],
        filename: Path,
    ):
        super().__init__()
        self.states = states  # Dictionary of step -> list of states
        self.layers = layers
        self.filename = filename

    def process(self):
        results = []
        try:
            for step, states in sorted(self.states.items()):
                logger.info(f"Processing step {step}")

                # Calculate bounding box for all layers in this step
                top_left = QPointF(sys.maxsize, sys.maxsize)
                bottom_right = QPointF(-sys.maxsize, -sys.maxsize)

                for state in states:
                    layer = self._get_layer(state.layer_id)
                    if layer and layer.visible and not layer.image.isNull():
                        layer.layer_state = state
                        layer.update()

                        transform = QTransform()
                        transform.translate(layer.position.x(), layer.position.y())
                        transform.rotate(layer.rotation)
                        transform.scale(layer.scale_x, layer.scale_y)

                        original_rect = QRectF(QPointF(0, 0), layer.image.size())
                        transformed_rect = transform.mapRect(original_rect)

                        top_left.setX(min(top_left.x(), transformed_rect.left()))
                        top_left.setY(min(top_left.y(), transformed_rect.top()))
                        bottom_right.setX(
                            max(bottom_right.x(), transformed_rect.right())
                        )
                        bottom_right.setY(
                            max(bottom_right.y(), transformed_rect.bottom())
                        )

                # Create the output image for this step
                width = int(bottom_right.x() - top_left.x())
                height = int(bottom_right.y() - top_left.y())
                if width <= 0 or height <= 0:
                    continue

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
                    for state in states:
                        layer = self._get_layer(state.layer_id)

                        if layer and layer.visible and not layer.image.isNull():
                            painter.save()
                            painter.translate(layer.position - top_left)
                            painter.rotate(layer.rotation)
                            painter.scale(layer.scale_x, layer.scale_y)
                            painter.setOpacity(layer.opacity)
                            painter.drawPixmap(QPoint(0, 0), layer.image)
                            painter.restore()

                            if layer.allow_annotation_export:
                                # Create layer mask
                                layer_mask = QImage(width, height, QImage.Format_ARGB32)
                                layer_mask.fill(Qt.transparent)
                                mask_painter = QPainter(layer_mask)
                                mask_painter.setRenderHints(
                                    QPainter.Antialiasing
                                    | QPainter.SmoothPixmapTransform
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
                                ].copy()  # Extract alpha

                                # Binarize the mask (0 or 255)
                                alpha_channel[alpha_channel > 0] = 255

                                masks.append(alpha_channel)
                                mask_names.append(layer.layer_name)

                                # Generate annotations
                                ann: Annotation = layer.annotations[0]
                                new_annotation = self._generate_annotation(
                                    ann, alpha_channel
                                )

                                new_annotations.append(new_annotation)
                finally:
                    painter.end()

                # Save the image
                filename = self.filename.parent / f"{self.filename.stem}_{step}.png"
                image.save(str(filename))
                logger.info(f"Saved baked image for step {step} to {filename}")

                # Append the result
                results.append(
                    BakingResult(filename, image, masks, mask_names, new_annotations)
                )

            # Emit all results
            self.finished.emit(results)

        except Exception as e:
            logger.error(f"Error in BakerWorker: {e}")
            self.error.emit(str(e))
            import traceback

            traceback.print_exc()

    def _get_layer(self, layer_id):
        for layer in self.layers:
            if layer.layer_id == layer_id:
                return layer
        return None

    def _generate_annotation(self, ann: Annotation, alpha_channel):
        """Generate an annotation based on the alpha channel."""
        new_annotation = Annotation(
            label=ann.label,
            color=ann.color,
            annotation_id=ann.annotation_id,
            is_complete=True,
            visible=True,
        )

        if ann.points:
            new_annotation.points = ann.points
        elif ann.rectangle:
            xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
            new_annotation.rectangle = QRectF(
                xywhs[0][0], xywhs[0][1], xywhs[0][2], xywhs[0][3]
            )
        elif ann.polygon:
            polygon = mask_to_polygons(alpha_channel, merge_polygons=True)
            poly = QPolygonF([QPointF(p[0], p[1]) for p in polygon[0]])
            new_annotation.polygon = poly
        else:
            logger.info("No annotation found")
        return new_annotation
