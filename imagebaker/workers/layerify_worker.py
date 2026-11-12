from PySide6.QtCore import (
    QObject,
    QRectF,
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
                local_ann = annotation.copy()
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
                    if x1 <= x0 or y1 <= y0:
                        continue
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
                    local_ann.mask = (mask_u8[y0:y1, x0:x1] > 0).astype(np.uint8)
                    local_ann.rectangle = None
                    local_ann.polygon = None
                elif annotation.polygon and len(annotation.polygon) >= 3:
                    bounding_rect = (
                        annotation.polygon.boundingRect()
                        .toRect()
                        .intersected(self.image.rect())
                    )
                    if bounding_rect.width() <= 0 or bounding_rect.height() <= 0:
                        continue
                    cropped_raw = (
                        self.image.copy(bounding_rect)
                        .toImage()
                        .convertToFormat(QImage.Format_ARGB32)
                    )
                    mask_img = QImage(cropped_raw.size(), QImage.Format_ARGB32)
                    mask_img.fill(Qt.transparent)
                    translated_poly = annotation.polygon.translated(
                        -bounding_rect.topLeft()
                    )

                    painter = QPainter(mask_img)
                    painter.setRenderHint(QPainter.Antialiasing, False)
                    painter.setBrush(QColor(255, 255, 255, 255))
                    painter.setPen(Qt.NoPen)
                    painter.drawPolygon(translated_poly)
                    painter.end()

                    raw_arr = qpixmap_to_numpy(cropped_raw).copy()
                    mask_arr = qpixmap_to_numpy(mask_img)
                    raw_arr[:, :, 3] = np.where(
                        mask_arr[:, :, 3] > 0, raw_arr[:, :, 3], 0
                    ).astype(np.uint8)
                    raw_arr = np.ascontiguousarray(raw_arr)
                    qimg = QImage(
                        raw_arr.data,
                        raw_arr.shape[1],
                        raw_arr.shape[0],
                        raw_arr.shape[1] * 4,
                        QImage.Format_RGBA8888,
                    )
                    cropped_image = QPixmap.fromImage(qimg.copy())
                    local_ann.polygon = translated_poly
                    local_ann.rectangle = None
                    local_ann.mask = None
                elif annotation.rectangle:
                    rect = annotation.rectangle.toRect().intersected(self.image.rect())
                    if rect.width() <= 0 or rect.height() <= 0:
                        continue
                    cropped_image = self.image.copy(rect)
                    local_ann.rectangle = QRectF(0, 0, rect.width(), rect.height())
                    local_ann.polygon = None
                    local_ann.mask = None
                else:
                    cropped_image = self.image

                self.finished.emit(local_ann, cropped_image)

        except Exception as e:
            print(e)
            import traceback

            traceback.print_exc()
            self.error.emit(str(e))
