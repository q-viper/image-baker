"""Annotation painting and geometry rendering helpers for AnnotableLayer."""

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPolygonF

from imagebaker.core.defs import Annotation


class AnnotableRenderMixin:
    """Mixin handling rendering of annotations, brush masks, handles, and labels."""

    def paint_layer(self, painter: QPainter):
        painter.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        self.label_rects.clear()

        if not self.image.isNull():
            painter.save()
            painter.translate(self.offset)
            painter.scale(self.scale, self.scale)
            painter.drawPixmap(0, 0, self.image)

            target_brush = getattr(self, "_target_brush_annotation", None)
            for annotation in self.annotations:
                if target_brush is annotation and self._brush_mask is not None:
                    self.draw_annotation(
                        painter, annotation, override_mask=self._brush_mask
                    )
                else:
                    self.draw_annotation(painter, annotation)

            if (
                target_brush is None
                and self._brush_mask is not None
                and np.any(self._brush_mask)
            ):
                live_label = self.current_label or self.config.default_label.name
                live_color = self.current_color or self.config.get_label_color(
                    live_label
                )
                live_ann = Annotation(
                    annotation_id=-1,
                    label=live_label,
                    color=live_color,
                    mask=self._brush_mask,
                    is_complete=False,
                    selected=True,
                )
                self.draw_annotation(painter, live_ann, is_temp=True)

            if self.current_annotation:
                self.draw_annotation(painter, self.current_annotation, is_temp=True)

            painter.restore()

    def draw_annotation(
        self, painter, annotation: Annotation, is_temp=False, override_mask=None
    ):
        """Draw annotation on the image."""
        if not annotation.visible:
            return
        painter.save()
        base_color = annotation.color
        pen_color = QColor(
            base_color.red(),
            base_color.green(),
            base_color.blue(),
            self.config.normal_draw_config.pen_alpha,
        )
        brush_color = QColor(
            base_color.red(),
            base_color.green(),
            base_color.blue(),
            self.config.normal_draw_config.brush_alpha,
        )

        pen = QPen(pen_color, self.config.normal_draw_config.line_width / self.scale)
        brush = QBrush(brush_color, Qt.DiagCrossPattern)

        is_hovered = getattr(self, "hovered_annotation", None) is annotation
        mask_src = override_mask if override_mask is not None else annotation.mask

        if mask_src is not None:
            raw_m = np.asarray(mask_src)
            if raw_m.ndim == 3:
                raw_m = raw_m[:, :, -1] if raw_m.shape[2] == 4 else raw_m[:, :, 0]
            bin_mask = raw_m > 0
            h, w = bin_mask.shape[:2]
            if h > 0 and w > 0 and np.any(bin_mask):
                color = annotation.color
                alpha_val = (
                    self.config.selected_draw_config.brush_alpha
                    if annotation.selected
                    else self.config.normal_draw_config.brush_alpha
                )
                rgba = np.zeros((h, w, 4), dtype=np.uint8)
                rgba[bin_mask] = [color.red(), color.green(), color.blue(), alpha_val]
                rgba = np.ascontiguousarray(rgba)
                qimg = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
                painter.drawImage(0, 0, qimg)

                mask_u8 = bin_mask.astype(np.uint8) * 255
                contours, _ = cv2.findContours(
                    mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                outline_color = (
                    self.config.selected_draw_config.color
                    if annotation.selected
                    else pen_color
                )
                outline_w = (
                    (self.config.selected_draw_config.line_width + 0.8)
                    if annotation.selected
                    else self.config.normal_draw_config.line_width
                ) / max(0.1, float(self.scale))
                painter.save()
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(outline_color, outline_w))
                for cnt in contours:
                    if len(cnt) >= 3:
                        qpoly = QPolygonF(
                            [QPointF(float(p[0][0]), float(p[0][1])) for p in cnt]
                        )
                        painter.drawPolygon(qpoly)
                if annotation.selected or is_hovered:
                    bx, by, bw, bh = cv2.boundingRect(mask_u8)
                    if bw > 0 and bh > 0:
                        box_pen = QPen(
                            outline_color,
                            max(1.0, 1.5 / max(0.1, float(self.scale))),
                            Qt.DashLine,
                        )
                        painter.setPen(box_pen)
                        painter.drawRect(QRectF(bx, by, bw, bh))
                painter.restore()

        if annotation.selected and mask_src is None:
            painter.setPen(
                QPen(
                    self.config.selected_draw_config.color,
                    self.config.selected_draw_config.line_width / self.scale,
                )
            )
            painter.setBrush(
                QBrush(
                    QColor(
                        self.config.selected_draw_config.color.red(),
                        self.config.selected_draw_config.color.green(),
                        self.config.selected_draw_config.color.blue(),
                        self.config.selected_draw_config.brush_alpha,
                    )
                )
            )
            if annotation.polygon:
                painter.drawPolygon(annotation.polygon)
            elif annotation.rectangle:
                painter.drawRect(annotation.rectangle)
            elif annotation.points:
                painter.drawEllipse(
                    annotation.points[0],
                    self.config.selected_draw_config.ellipse_size / self.scale,
                    self.config.selected_draw_config.ellipse_size / self.scale,
                )

        if is_temp:
            pen.setStyle(Qt.DashLine)
            brush.setStyle(Qt.Dense4Pattern)

        painter.setPen(pen)
        painter.setBrush(brush)

        if mask_src is None:
            if annotation.points and not annotation.polygon and not annotation.rectangle:
                for point in annotation.points:
                    painter.drawEllipse(
                        point,
                        self.config.normal_draw_config.point_size / self.scale,
                        self.config.normal_draw_config.point_size / self.scale,
                    )
            elif annotation.polygon:
                if len(annotation.polygon) > 1:
                    if annotation.is_complete:
                        painter.drawPolygon(annotation.polygon)
                    else:
                        painter.drawPolyline(annotation.polygon)
            elif annotation.rectangle:
                painter.drawRect(annotation.rectangle)

        show_points = (
            is_temp or not annotation.is_complete or annotation.selected or is_hovered
        )

        if show_points and not annotation.polygon and annotation.rectangle:
            rect = annotation.rectangle
            corners = [
                rect.topLeft(),
                rect.topRight(),
                rect.bottomLeft(),
                rect.bottomRight(),
            ]
            painter.save()
            painter.setPen(
                QPen(
                    Qt.black,
                    self.config.normal_draw_config.control_point_size / self.scale,
                )
            )
            painter.setBrush(QBrush(Qt.white))
            for corner in corners:
                painter.drawEllipse(
                    corner,
                    self.config.normal_draw_config.point_size / self.scale,
                    self.config.normal_draw_config.point_size / self.scale,
                )
            painter.restore()

        if show_points and annotation.polygon and len(annotation.polygon) > 0:
            painter.save()
            painter.setPen(
                QPen(
                    Qt.white,
                    self.config.normal_draw_config.control_point_size / self.scale,
                )
            )
            painter.setBrush(QBrush(Qt.darkGray))
            for point in annotation.polygon:
                painter.drawEllipse(
                    point,
                    self.config.normal_draw_config.point_size / self.scale,
                    self.config.normal_draw_config.point_size / self.scale,
                )
            painter.restore()

        is_active_annotation = annotation is self.current_annotation or (
            annotation is self.selected_annotation
            and hasattr(self, "active_handle")
            and self.active_handle is not None
        )

        if (
            annotation.is_complete
            and annotation.label
            and not is_temp
            and not is_active_annotation
        ):
            label_pos = self.get_label_position(annotation)
            text = annotation.label

            widget_pos = QPointF(
                label_pos.x() * self.scale + self.offset.x(),
                label_pos.y() * self.scale + self.offset.y(),
            )

            if annotation.points:
                widget_pos += QPointF(10, 10)

            zoom = max(0.1, float(self.scale))
            label_px = int(
                round(self.config.normal_draw_config.label_font_size * zoom)
            )
            label_px = max(9, min(48, label_px))

            painter.resetTransform()

            label_font = painter.font()
            label_font.setPixelSize(label_px)
            label_font.setItalic(False)
            label_font.setWeight(QFont.DemiBold)
            painter.setFont(label_font)

            label_metrics = painter.fontMetrics()
            label_width = label_metrics.horizontalAdvance(text)
            label_height = label_metrics.height()

            bg_rect = QRectF(
                widget_pos.x() - label_width / 2 - 4,
                widget_pos.y() - label_height / 2 - 3,
                label_width + 8,
                label_height + 6,
            )
            self.label_rects.append((bg_rect, annotation))

            painter.setPen(Qt.NoPen)
            painter.setBrush(self.config.normal_draw_config.label_font_background_color)
            painter.drawRoundedRect(bg_rect, 3, 3)

            painter.setPen(Qt.white)
            painter.drawText(bg_rect, Qt.AlignCenter, text)

            if annotation.caption:
                caption_text = annotation.caption
                caption_px = int(
                    round(self.config.selected_draw_config.label_font_size * zoom)
                )
                caption_px = max(8, min(40, caption_px))

                caption_font = painter.font()
                caption_font.setItalic(True)
                caption_font.setPixelSize(caption_px)
                caption_font.setWeight(QFont.Light)
                painter.setFont(caption_font)

                caption_metrics = painter.fontMetrics()
                caption_width = caption_metrics.horizontalAdvance(caption_text)
                caption_height = caption_metrics.height()
                caption_rect = QRectF(
                    widget_pos.x() - caption_width / 2 - 4,
                    bg_rect.bottom() + 2,
                    caption_width + 8,
                    caption_height + 4,
                )

                painter.setPen(Qt.NoPen)
                painter.setBrush(
                    self.config.normal_draw_config.label_font_background_color
                )
                painter.drawRoundedRect(caption_rect, 3, 3)

                painter.setPen(Qt.white)
                painter.drawText(caption_rect, Qt.AlignCenter, caption_text)

        painter.restore()

        if (annotation.selected or is_hovered) and annotation.is_complete:
            painter.save()
            handle_color = self.config.selected_draw_config.handle_color
            painter.setPen(
                QPen(
                    handle_color,
                    self.config.selected_draw_config.handle_width / self.scale,
                )
            )
            painter.setBrush(QBrush(handle_color))

            if not annotation.polygon and annotation.rectangle:
                rect = annotation.rectangle
                for corner in [
                    rect.topLeft(),
                    rect.topRight(),
                    rect.bottomLeft(),
                    rect.bottomRight(),
                ]:
                    painter.drawEllipse(
                        corner,
                        self.config.selected_draw_config.handle_point_size / self.scale,
                        self.config.selected_draw_config.handle_point_size / self.scale,
                    )
                for edge in [
                    QPointF(rect.center().x(), rect.top()),
                    QPointF(rect.center().x(), rect.bottom()),
                    QPointF(rect.left(), rect.center().y()),
                    QPointF(rect.right(), rect.center().y()),
                ]:
                    painter.drawEllipse(
                        edge,
                        self.config.selected_draw_config.handle_edge_size / self.scale,
                        self.config.selected_draw_config.handle_edge_size / self.scale,
                    )

            elif annotation.polygon:
                for point in annotation.polygon:
                    painter.drawEllipse(
                        point,
                        self.config.selected_draw_config.handle_point_size / self.scale,
                        self.config.selected_draw_config.handle_point_size / self.scale,
                    )

            elif annotation.points:
                for point in annotation.points:
                    painter.drawEllipse(
                        point,
                        self.config.selected_draw_config.handle_point_size / self.scale,
                        self.config.selected_draw_config.handle_point_size / self.scale,
                    )

            painter.restore()

    def get_label_position(self, annotation: Annotation):
        if annotation.points:
            return annotation.points[0]
        if annotation.rectangle:
            return annotation.rectangle.center()
        if annotation.polygon:
            return annotation.polygon.boundingRect().center()
        if annotation.mask is not None and np.any(annotation.mask):
            return self.get_annotation_position(annotation)
        return QPointF()
