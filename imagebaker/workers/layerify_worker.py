from PySide6.QtCore import (
    QObject,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPixmap,
)

from imagebaker import logger
from imagebaker.core.defs import Annotation


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
            import numpy as np

            from imagebaker.utils.image import qpixmap_to_numpy

            for annotation in self.annotations:
                logger.info(f"Layerifying annotation {annotation}")
                if annotation.mask is not None and np.any(annotation.mask):
                    raw_mask = np.asarray(annotation.mask)
                    if raw_mask.ndim == 3:
                        raw_mask = (
                            raw_mask[:, :, -1]
                            if raw_mask.shape[2] == 4
                            else raw_mask[:, :, 0]
                        )
                    img_h, img_w = self.image.height(), self.image.width()
                    mask_u8 = np.zeros((img_h, img_w), dtype=np.uint8)
                    mh = min(img_h, raw_mask.shape[0])
                    mw = min(img_w, raw_mask.shape[1])
                    mask_u8[:mh, :mw] = (raw_mask[:mh, :mw] > 0).astype(np.uint8) * 255
                    ys, xs = np.nonzero(mask_u8)
                    if len(xs) == 0 or len(ys) == 0:
                        continue
                    x0, x1 = max(0, int(xs.min())), min(img_w, int(xs.max()) + 1)
                    y0, y1 = max(0, int(ys.min())), min(img_h, int(ys.max()) + 1)
                    raw_arr = qpixmap_to_numpy(self.image)[y0:y1, x0:x1].copy()
                    src_alpha = raw_arr[:, :, 3].astype(np.uint16)
                    msk_alpha = mask_u8[y0:y1, x0:x1].astype(np.uint16)
                    raw_arr[:, :, 3] = ((src_alpha * msk_alpha) // 255).astype(np.uint8)
                    raw_arr = np.ascontiguousarray(raw_arr)
                    qimg = QImage(
                        raw_arr.data,
                        raw_arr.shape[1],
                        raw_arr.shape[0],
                        raw_arr.shape[1] * 4,
                        QImage.Format_RGBA8888,
                    )
                    cropped_image = QPixmap.fromImage(qimg.copy())
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
                elif annotation.rectangle:
                    cropped_image = self.image.copy(annotation.rectangle.toRect())
                else:
                    cropped_image = self.image

                self.finished.emit(annotation, cropped_image)

        except Exception as e:
            print(e)
            import traceback

            traceback.print_exc()
            self.error.emit(str(e))
