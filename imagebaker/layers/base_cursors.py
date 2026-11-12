"""Cursor construction and mode-specific pointer updates for BaseLayer."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QPolygonF

from imagebaker.core.configs import CursorDef
from imagebaker.core.defs import MouseMode


class BaseCursorMixin:
    """Mixin supplying mode-specific cursors for layer interaction."""

    def update_cursor(self):
        """
        Update the cursor based on the current mouse mode.
        Every MouseMode is assigned a visually distinct cursor icon.
        """
        if MouseMode.POINT == self.mouse_mode:
            self.setCursor(self._create_mode_cursor(MouseMode.POINT))
        elif MouseMode.RECTANGLE == self.mouse_mode:
            self.setCursor(self._create_mode_cursor(MouseMode.RECTANGLE))
        elif MouseMode.POLYGON == self.mouse_mode:
            self.setCursor(self._create_mode_cursor(MouseMode.POLYGON))
        elif MouseMode.PAN == self.mouse_mode:
            self.setCursor(CursorDef.PAN_CURSOR)
        elif MouseMode.ZOOM_IN == self.mouse_mode:
            self.setCursor(self._create_zoom_cursor(zoom_in=True))
        elif MouseMode.ZOOM_OUT == self.mouse_mode:
            self.setCursor(self._create_zoom_cursor(zoom_in=False))
        elif MouseMode.IDLE == self.mouse_mode:
            self.setCursor(CursorDef.IDLE_CURSOR)
        elif MouseMode.RESIZE == self.mouse_mode:
            self.setCursor(Qt.SizeFDiagCursor)
        elif MouseMode.RESIZE_HEIGHT == self.mouse_mode:
            self.setCursor(CursorDef.TRANSFORM_UPDOWN)
        elif MouseMode.RESIZE_WIDTH == self.mouse_mode:
            self.setCursor(CursorDef.TRANSFORM_LEFTRIGHT)
        elif MouseMode.GRAB == self.mouse_mode:
            self.setCursor(CursorDef.GRAB_CURSOR)
        elif self.mouse_mode == MouseMode.DRAW:
            self.setCursor(self._create_custom_cursor(self.drawing_color, "circle"))
        elif self.mouse_mode == MouseMode.ERASE:
            self.setCursor(self._create_custom_cursor(Qt.white, "square"))
        else:
            self.setCursor(Qt.ArrowCursor)

    def _create_mode_cursor(self, mode: MouseMode) -> QCursor:
        """Create a distinct custom cursor icon for Point, Rectangle, and Polygon modes."""
        size = 28
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.Antialiasing)

        cx, cy = 10, 10
        halo_pen = QPen(QColor(255, 255, 255, 220), 3)
        fg_pen = QPen(QColor(20, 24, 32, 245), 1.5)

        for pen in (halo_pen, fg_pen):
            painter.setPen(pen)
            painter.drawLine(cx - 7, cy, cx - 2, cy)
            painter.drawLine(cx + 2, cy, cx + 7, cy)
            painter.drawLine(cx, cy - 7, cx, cy - 2)
            painter.drawLine(cx, cy + 2, cx, cy + 7)

        if mode == MouseMode.POINT:
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
            painter.setBrush(QColor(0, 210, 255, 240))
            painter.drawEllipse(QPointF(cx, cy), 3.0, 3.0)
            painter.setPen(QPen(QColor(0, 180, 230, 240), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(20, 20), 4.5, 4.5)
        elif mode == MouseMode.RECTANGLE:
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(14, 15, 11, 9)
            painter.setPen(QPen(QColor(59, 130, 246, 250), 1.5))
            painter.setBrush(QColor(59, 130, 246, 70))
            painter.drawRect(14, 15, 11, 9)
        elif mode == MouseMode.POLYGON:
            poly = QPolygonF(
                [
                    QPointF(15, 24),
                    QPointF(14, 17),
                    QPointF(20, 14),
                    QPointF(25, 19),
                    QPointF(23, 25),
                ]
            )
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(poly)
            painter.setPen(QPen(QColor(16, 185, 129, 250), 1.5))
            painter.setBrush(QColor(16, 185, 129, 75))
            painter.drawPolygon(poly)
            painter.setBrush(QColor(16, 185, 129, 255))
            for pt in poly:
                painter.drawEllipse(pt, 1.6, 1.6)

        painter.end()
        return QCursor(pixmap, cx, cy)

    def _create_custom_cursor(self, color: QColor, shape: str) -> QCursor:
        """Create a custom cursor reflecting current brush size and zoom."""
        eff_diam = max(6, min(96, int(round(self.brush_size * max(0.1, float(self.scale))))))
        pad = 6
        size = eff_diam + pad * 2
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.Antialiasing)
        center = pixmap.rect().center()
        rad = max(2, eff_diam // 2)

        painter.setPen(QPen(QColor(255, 255, 255, 220), 2))
        painter.setBrush(Qt.NoBrush)
        if shape == "circle":
            painter.drawEllipse(center, rad, rad)
        else:
            painter.drawRect(center.x() - rad, center.y() - rad, rad * 2, rad * 2)

        painter.setPen(QPen(Qt.black, 1))
        painter.setBrush(color)
        if shape == "circle":
            painter.drawEllipse(center, rad, rad)
        elif shape == "square":
            painter.drawRect(center.x() - rad, center.y() - rad, rad * 2, rad * 2)

        painter.end()
        return QCursor(pixmap, center.x(), center.y())

    def _create_zoom_cursor(self, zoom_in: bool) -> QCursor:
        """Create a magnifier-like cursor with plus/minus marker."""
        size = 24
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.Antialiasing)
        pen = QPen(Qt.black, 2)
        painter.setPen(pen)

        painter.drawEllipse(2, 2, 14, 14)
        painter.drawLine(13, 13, 21, 21)
        painter.drawLine(6, 9, 12, 9)
        if zoom_in:
            painter.drawLine(9, 6, 9, 12)

        painter.end()
        return QCursor(pixmap, 2, 2)
