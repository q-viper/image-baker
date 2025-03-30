from PySide6.QtCore import (
    Qt,
    Signal,
    QObject,
)
from PySide6.QtGui import (
    QColor,
    QPixmap,
    QPainter,
    QImage,
)


from imagebaker.core.defs import Annotation
from imagebaker import logger


class LayerifyWorker(QObject):
    finished = Signal(Annotation, QPixmap)
    error = Signal(str)

    def __init__(self, image, annotations, config):
        """
        Worker to layerify an image based on annotations.

        Args:
            image (QPixmap): Image to layerify.
            annotations (List[Annotation]): List of annotations to layerify.
            config (Config): Config object containing settings.
        """
        super().__init__()
        self.image = image.copy()
        self.annotations = annotations
        self.config = config

    def process(self):
        try:
            for annotation in self.annotations:
                logger.info(f"Layerifying annotation {annotation}")
                if annotation.rectangle:
                    cropped_image = self.image.copy(annotation.rectangle.toRect())
                elif annotation.polygon:
                    # Get bounding box and crop
                    bounding_rect = annotation.polygon.boundingRect().toRect()
                    cropped_pixmap = self.image.copy(bounding_rect)

                    # Convert to ARGB32 format to ensure alpha channel support
                    cropped_image = cropped_pixmap.toImage().convertToFormat(
                        QImage.Format_ARGB32
                    )

                    # Create mask with sharp edges
                    mask = QImage(cropped_image.size(), QImage.Format_ARGB32)
                    mask.fill(Qt.transparent)

                    # Translate polygon coordinates
                    translated_poly = annotation.polygon.translated(
                        -bounding_rect.topLeft()
                    )

                    # Draw mask without anti-aliasing
                    painter = QPainter(mask)
                    painter.setRenderHint(QPainter.Antialiasing, False)
                    painter.setBrush(QColor(255, 255, 255, 255))  # Opaque white
                    painter.setPen(Qt.NoPen)
                    painter.drawPolygon(translated_poly)
                    painter.end()

                    # Apply mask to image
                    for y in range(cropped_image.height()):
                        for x in range(cropped_image.width()):
                            mask_alpha = mask.pixelColor(x, y).alpha()
                            color = cropped_image.pixelColor(x, y)

                            # Set alpha to 0 outside polygon, 255 inside
                            color.setAlpha(255 if mask_alpha > 0 else 0)
                            cropped_image.setPixelColor(x, y, color)

                    # Convert back to pixmap with proper alpha
                    cropped_image = QPixmap.fromImage(cropped_image)
                else:
                    cropped_image = self.image

                self.finished.emit(annotation, cropped_image)

        except Exception as e:
            print(e)
            import traceback

            traceback.print_exc()
            self.error.emit(str(e))
