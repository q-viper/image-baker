"""Edge feathering, thumbnails, grid overlay, and paint hooks for BaseLayer."""

import math

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap

from imagebaker import logger
from imagebaker.core.defs import Annotation


class BaseRenderMixin:
    """Mixin handling rendering helpers, thumbnails, and grid overlays."""

    def widget_to_image_pos(self, pos: QPointF) -> QPointF:
        """Convert a widget position to an image position."""
        return QPointF(
            (pos.x() - self.offset.x()) / self.scale,
            (pos.y() - self.offset.y()) / self.scale,
        )

    def _apply_edge_opacity(self):
        """
        Apply edge opacity to the image. This function modifies the edges of the image
        to have reduced opacity based on the configuration.
        """
        logger.debug("Applying edge opacity to the image.")
        edge_width = self.edge_width
        edge_opacity = self.edge_opacity

        image = self._original_image.toImage()
        image = image.convertToFormat(QImage.Format_ARGB32)

        width = image.width()
        height = image.height()
        annotation = self.annotations[0] if self.annotations else None
        if annotation is None:
            return

        if annotation.rectangle:
            for x in range(width):
                for y in range(height):
                    color = image.pixelColor(x, y)
                    if color.alpha() != 0:
                        horizontal_distance = min(x, width - x - 1)
                        vertical_distance = min(y, height - y - 1)
                        if (
                            horizontal_distance < edge_width
                            or vertical_distance < edge_width
                        ):
                            distance_to_edge = min(
                                horizontal_distance, vertical_distance
                            )
                            factor = (edge_width - distance_to_edge) / edge_width
                            new_alpha = int(
                                color.alpha()
                                * ((1 - factor) + (factor * (edge_opacity / 255.0)))
                            )
                            color.setAlpha(new_alpha)
                            image.setPixelColor(x, y, color)

        elif annotation.polygon or (annotation.mask is not None and np.any(annotation.mask)):
            if edge_width > 0 and edge_opacity < 255:
                alpha_image = image.convertToFormat(QImage.Format_Alpha8)
                bytes_per_line = alpha_image.bytesPerLine()
                alpha_data = alpha_image.bits().tobytes()
                alpha_array = np.frombuffer(alpha_data, dtype=np.uint8).reshape(
                    (alpha_image.height(), bytes_per_line)
                )[:, : alpha_image.width()]

                bin_mask = (alpha_array > 0).astype(np.uint8)
                if np.any(bin_mask):
                    dist = cv2.distanceTransform(bin_mask, cv2.DIST_L2, 3)
                    edge_region = (bin_mask > 0) & (dist < float(edge_width))
                    if np.any(edge_region):
                        rgba_img = image.convertToFormat(QImage.Format_RGBA8888)
                        bpl = rgba_img.bytesPerLine()
                        buf = (
                            np.frombuffer(rgba_img.bits().tobytes(), dtype=np.uint8)
                            .reshape((height, bpl))[:, : width * 4]
                            .reshape((height, width, 4))
                            .copy()
                        )
                        factor = (float(edge_width) - dist[edge_region]) / float(
                            edge_width
                        )
                        scale = (1.0 - factor) + (factor * (float(edge_opacity) / 255.0))
                        new_alpha = np.clip(
                            buf[:, :, 3][edge_region].astype(np.float32) * scale, 0, 255
                        ).astype(np.uint8)
                        buf[:, :, 3][edge_region] = new_alpha
                        buf = np.ascontiguousarray(buf)
                        out_qimg = QImage(
                            buf.data, width, height, width * 4, QImage.Format_RGBA8888
                        )
                        image = out_qimg.copy()

        self.image = QPixmap.fromImage(image)

    def get_thumbnail(self, annotation: Annotation = None):
        """Generate a thumbnail for the layer or a specific annotation."""
        image = QPixmap(*self.config.normal_draw_config.thumbnail_size)
        image.fill(Qt.transparent)

        if annotation:
            if annotation.rectangle:
                image = self.image.copy(annotation.rectangle.toRect())
            elif annotation.polygon:
                image = self.image.copy(annotation.polygon.boundingRect().toRect())
            elif annotation.mask is not None and np.any(annotation.mask):
                ys, xs = np.nonzero(annotation.mask)
                x0, y0 = int(xs.min()), int(ys.min())
                bw = int(xs.max() - x0 + 1)
                bh = int(ys.max() - y0 + 1)
                image = self.image.copy(x0, y0, bw, bh)
            elif annotation.points:
                thumbnail_size = 100
                thumbnail = QPixmap(thumbnail_size, thumbnail_size)
                thumbnail.fill(Qt.transparent)
                painter = QPainter(thumbnail)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setBrush(annotation.color)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(thumbnail.rect().center() + QPoint(-5, -5), 10, 10)
                painter.end()
                image = thumbnail
        else:
            if self.image:
                image = self.image.copy(
                    0, 0, *self.config.normal_draw_config.thumbnail_size
                )
            elif len(self.layers) > 0:
                image = self.layers[0].get_thumbnail()
            else:
                image = QPixmap(*self.config.normal_draw_config.thumbnail_size)
                image.fill(Qt.transparent)

        return image.scaled(*self.config.normal_draw_config.thumbnail_size)

    def _grid_view_transform(self) -> tuple[QPointF, float]:
        """Return widget-space anchor offset and zoom used by the grid."""
        anchor = self.offset if isinstance(self.offset, QPointF) else QPointF(0, 0)
        zoom = float(self.scale) if self.scale else 1.0
        return anchor, max(0.01, zoom)

    def _draw_grid_overlay(self, painter: QPainter):
        """Draw a multi-depth grid overlay relative to image dimensions."""
        if not getattr(self.config, "show_gridlines", False):
            return

        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        grid_color = getattr(self.config, "grid_color", QColor(120, 120, 120, 80))
        anchor, zoom = self._grid_view_transform()
        zoom = max(0.001, float(zoom))
        anchor_x = float(anchor.x())
        anchor_y = float(anchor.y())

        img_w = (
            float(self.image.width())
            if hasattr(self, "image") and self.image and not self.image.isNull()
            else float(width)
        )
        img_h = (
            float(self.image.height())
            if hasattr(self, "image") and self.image and not self.image.isNull()
            else float(height)
        )

        candidate_steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000]
        fine_step = candidate_steps[-1]
        for s in candidate_steps:
            if s * zoom >= 5.0:
                fine_step = s
                break

        mid_step = fine_step * 5
        if fine_step == 2:
            mid_step = 10
        elif fine_step in (20, 25):
            mid_step = 100
        elif fine_step in (200, 250):
            mid_step = 1000

        major_step = mid_step * 5
        if mid_step == 10:
            major_step = 50
        elif mid_step == 100:
            major_step = 500

        min_img_x = int(math.floor((-anchor_x) / (fine_step * zoom))) * fine_step
        max_img_x = int(math.ceil((width - anchor_x) / (fine_step * zoom))) * fine_step
        min_img_y = int(math.floor((-anchor_y) / (fine_step * zoom))) * fine_step
        max_img_y = int(math.ceil((height - anchor_y) / (fine_step * zoom))) * fine_step

        painter.save()
        painter.resetTransform()
        painter.setOpacity(1.0)
        painter.setRenderHint(QPainter.Antialiasing, False)

        fine_color = QColor(grid_color)
        fine_color.setAlpha(max(20, min(80, int(fine_color.alpha() * 0.45))))
        pen_fine = QPen(fine_color, 1)
        pen_fine.setCosmetic(True)
        painter.setPen(pen_fine)

        for ix in range(min_img_x, max_img_x + 1, fine_step):
            if ix % mid_step == 0:
                continue
            sx = int(round(anchor_x + ix * zoom))
            if 0 <= sx <= width:
                painter.drawLine(sx, 0, sx, height)

        for iy in range(min_img_y, max_img_y + 1, fine_step):
            if iy % mid_step == 0:
                continue
            sy = int(round(anchor_y + iy * zoom))
            if 0 <= sy <= height:
                painter.drawLine(0, sy, width, sy)

        mid_color = QColor(grid_color)
        mid_color.setAlpha(max(40, min(140, int(mid_color.alpha() * 0.85))))
        pen_mid = QPen(mid_color, 1)
        pen_mid.setCosmetic(True)
        painter.setPen(pen_mid)

        for ix in range(min_img_x, max_img_x + 1, fine_step):
            if ix % mid_step != 0 or ix % major_step == 0:
                continue
            sx = int(round(anchor_x + ix * zoom))
            if 0 <= sx <= width:
                painter.drawLine(sx, 0, sx, height)

        for iy in range(min_img_y, max_img_y + 1, fine_step):
            if iy % mid_step != 0 or iy % major_step == 0:
                continue
            sy = int(round(anchor_y + iy * zoom))
            if 0 <= sy <= height:
                painter.drawLine(0, sy, width, sy)

        major_color = QColor(grid_color).lighter(150)
        major_color.setAlpha(max(70, min(200, int(major_color.alpha() * 1.3))))
        pen_major = QPen(major_color, 1)
        pen_major.setCosmetic(True)
        painter.setPen(pen_major)

        for ix in range(min_img_x, max_img_x + 1, fine_step):
            if ix % major_step != 0:
                continue
            sx = int(round(anchor_x + ix * zoom))
            if 0 <= sx <= width:
                painter.drawLine(sx, 0, sx, height)

        for iy in range(min_img_y, max_img_y + 1, fine_step):
            if iy % major_step != 0:
                continue
            sy = int(round(anchor_y + iy * zoom))
            if 0 <= sy <= height:
                painter.drawLine(0, sy, width, sy)

        frame_color = QColor(56, 189, 248, 200)
        pen_frame = QPen(frame_color, 2)
        pen_frame.setCosmetic(True)
        painter.setPen(pen_frame)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(
            QRectF(
                anchor_x,
                anchor_y,
                img_w * zoom,
                img_h * zoom,
            )
        )

        hover_pos = self._mouse_widget_pos
        if hover_pos is not None:
            hover_x = float(hover_pos.x())
            hover_y = float(hover_pos.y())
            if 0 <= hover_x < width and 0 <= hover_y < height:
                cur_img_x = (hover_x - anchor_x) / zoom
                cur_img_y = (hover_y - anchor_y) / zoom
                snap_img_x = int(round(cur_img_x / fine_step) * fine_step)
                snap_img_y = int(round(cur_img_y / fine_step) * fine_step)
                snap_x = int(round(anchor_x + snap_img_x * zoom))
                snap_y = int(round(anchor_y + snap_img_y * zoom))

                highlight_color = QColor(56, 189, 248, 220)
                snap_pen = QPen(highlight_color, 1)
                snap_pen.setCosmetic(True)
                painter.setPen(snap_pen)
                painter.drawLine(snap_x, 0, snap_x, height)
                painter.drawLine(0, snap_y, width, snap_y)

                painter.setBrush(highlight_color)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(snap_x, snap_y), 3.5, 3.5)

        painter.restore()

    def paintEvent(self, event):
        self.paint_event()

    def paint_event(self):
        painter = QPainter(self)
        try:
            painter.setRenderHints(
                QPainter.Antialiasing | QPainter.SmoothPixmapTransform
            )

            painter.fillRect(
                self.rect(),
                QColor(
                    self.config.normal_draw_config.background_color.red(),
                    self.config.normal_draw_config.background_color.green(),
                    self.config.normal_draw_config.background_color.blue(),
                ),
            )
            self.paint_layer(painter)
            self._draw_grid_overlay(painter)
        finally:
            painter.end()

    def paint_layer(self, painter: QPainter):
        raise NotImplementedError
