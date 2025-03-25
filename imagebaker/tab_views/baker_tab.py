from PySide6.QtWidgets import QWidget, QSizePolicy, QProgressDialog
from PySide6.QtGui import (
    QPainter,
    QPixmap,
    QPaintEvent,
    QMouseEvent,
    QPen,
    QColor,
    QWheelEvent,
    QTransform,
)
from PySide6.QtCore import (
    Qt,
    QPoint,
    QSize,
    QPointF,
    Signal,
    QEvent,
    QRectF,
    QLineF,
    QThread,
)
import sys
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
)
import math
import cv2
from datetime import datetime

from imagebaker.core.defs import Annotation, BakingResult, LayerState
from .layerify_tab import Layer
from imagebaker.workers import BakerWorker
from imagebaker.core.configs import CanvasConfig, CursorDef
from imagebaker import logger
from imagebaker.utils.image import qpixmap_to_numpy, draw_annotations


class Canvas(QWidget):
    mouseMoved = Signal(QPointF)
    layersChanged = Signal()
    layerRemoved = Signal()
    layerSelected = Signal(object)
    messageSignal = Signal(str)

    def __init__(self, parent, config: CanvasConfig = CanvasConfig()):
        super().__init__(parent=parent)
        self.config = config
        self.layers = []
        self.layer_masks = {}
        self._back_buffer = QPixmap()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.layersChanged.connect(self.update)

        # Transformation state
        self.scale = 1.0
        self._pan_offset = QPointF(0, 0)
        self._last_pan_point = None
        self._dragging_layer = None
        self._drag_offset = QPointF(0, 0)
        self._current_hover = None
        self._active_handle = None
        self._transform_start = None
        self._is_panning = False
        self.offset = QPointF(0, 0)
        self.copied_layer: Layer = None
        self.selected_layer: Layer = None

    def set_layers(self, layers: list[Layer]):
        self.layers = layers
        self._update_back_buffer(draw_masks=False)
        self.layersChanged.emit()

    def _get_selected_layer(self):
        for layer in self.layers:
            if layer.selected:
                return layer
        return None

    def _update_back_buffer(self, draw_masks=False):
        # Initialize the back buffer
        self._back_buffer = QPixmap(self.size())
        self._back_buffer.fill(Qt.GlobalColor.transparent)

        # Initialize the layer masks dictionary if it doesn't exist
        if not hasattr(self, "layer_masks"):
            self.layer_masks = {}

        painter = QPainter(self._back_buffer)
        try:
            painter.setRenderHints(
                QPainter.RenderHint.Antialiasing
                | QPainter.RenderHint.SmoothPixmapTransform
            )

            for layer in self.layers:
                if layer.visible and not layer.image.isNull():
                    # Save the painter state
                    painter.save()

                    # Apply layer transformations
                    painter.translate(layer.position)
                    painter.rotate(layer.rotation)
                    painter.scale(layer.scale, layer.scale)

                    # Draw the layer onto the back buffer
                    painter.setOpacity(layer.opacity)
                    painter.drawPixmap(QPoint(0, 0), layer.image)

                    # Restore the painter state
                    painter.restore()
                    if draw_masks:
                        self._create_layer_mask(layer)
        finally:
            painter.end()

    def _create_layer_mask(self, layer: Layer):
        self.messageSignal.emit(f"Creating mask for {layer.name}")
        # Create a mask for the layer with the same transformations and opacity
        mask_pixmap = QPixmap(self.size())
        mask_pixmap.fill(Qt.GlobalColor.transparent)
        mask_painter = QPainter(mask_pixmap)
        mask_painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        mask_painter.translate(layer.position)
        mask_painter.rotate(layer.rotation)
        mask_painter.scale(layer.scale, layer.scale)
        mask_painter.setOpacity(layer.opacity)
        mask_painter.drawPixmap(QPoint(0, 0), layer.image)
        mask_painter.end()
        self.layer_masks[layer.name] = mask_pixmap

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        try:
            # Draw background
            painter.fillRect(self.rect(), QColor(35, 35, 35))

            # Apply view transformations
            painter.translate(self._pan_offset)
            painter.scale(self.scale, self.scale)

            # Draw layers
            for layer in self.layers:
                if layer.visible and not layer.image.isNull():
                    painter.save()
                    try:
                        # Apply layer transformations
                        painter.translate(layer.position)
                        painter.rotate(layer.rotation)
                        painter.scale(layer.scale_x, layer.scale_y)
                        painter.setOpacity(layer.opacity)

                        # Draw layer image
                        painter.drawPixmap(QPoint(0, 0), layer.image)
                        # Draw selection overlay
                        if layer.selected:
                            painter.setPen(QPen(Qt.NoPen))
                            painter.setBrush(
                                QColor(
                                    self.config.selected_draw_config.color.red(),
                                    self.config.selected_draw_config.color.green(),
                                    self.config.selected_draw_config.color.blue(),
                                    50,
                                )
                            )
                            painter.drawRect(QRectF(QPointF(0, 0), layer.original_size))
                    finally:
                        painter.restore()

                    # Draw transform handles
                    if layer.selected:
                        self._draw_transform_handles(painter, layer)

        finally:
            painter.end()

    def _draw_selection(self, painter, layer: Layer):
        try:
            # Draw transformed overlay
            painter.save()
            transform = QTransform()
            transform.translate(layer.position.x(), layer.position.y())
            transform.rotate(layer.rotation)
            transform.scale(layer.scale, layer.scale)
            painter.setTransform(transform)

            # Semi-transparent overlay
            painter.setBrush(QColor(0, 0, 0, 100))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(QPointF(0, 0), layer.original_size))
            painter.restore()

            # Draw handles
            rect = transform.mapRect(QRectF(QPointF(0, 0), layer.original_size))
            handle_size = 8 / self.scale

            # Draw border
            pen = QPen(
                self.config.selected_draw_config.color,
                self.config.selected_draw_config.handle_edge_size,
                Qt.PenStyle.DashLine,
            )
            painter.setPen(pen)
            painter.drawRect(rect)

            # Draw handles
            painter.setBrush(self.config.selected_draw_config.handle_color)
            handles = [
                rect.topLeft(),
                rect.topRight(),
                rect.bottomLeft(),
                rect.bottomRight(),
                QPointF(rect.center().x(), rect.top()),
                QPointF(rect.center().x(), rect.bottom()),
                QPointF(rect.left(), rect.center().y()),
                QPointF(rect.right(), rect.center().y()),
            ]

            for handle in handles:
                painter.drawRect(
                    QRectF(
                        handle.x() - handle_size / 2,
                        handle.y() - handle_size / 2,
                        handle_size,
                        handle_size,
                    )
                )

            # Rotation handle
            rotation_pos = QPointF(rect.center().x(), rect.top() - 20 / self.scale)
            painter.drawEllipse(rotation_pos, handle_size / 2, handle_size / 2)
        except Exception as e:
            logger.info(f"Error drawing selection: {e}")

    def _get_layer_handles(self, layer):
        transform = QTransform()
        transform.translate(layer.position.x(), layer.position.y())
        transform.rotate(layer.rotation)
        transform.scale(layer.scale, layer.scale)
        rect = transform.mapRect(QRectF(QPointF(0, 0), layer.original_size))

        handles = {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_left": rect.bottomLeft(),
            "bottom_right": rect.bottomRight(),
            "top_center": QPointF(rect.center().x(), rect.top()),
            "bottom_center": QPointF(rect.center().x(), rect.bottom()),
            "left_center": QPointF(rect.left(), rect.center().y()),
            "right_center": QPointF(rect.right(), rect.center().y()),
            "rotate": QPointF(rect.center().x(), rect.top() - 20 / self.scale),
        }
        return handles

    def resizeEvent(self, event):
        self._update_back_buffer()
        super().resizeEvent(event)

    def _draw_transform_handles(self, painter, layer):
        """Draw rotation and scaling handles"""
        # Create transform including both scales
        transform = QTransform()
        transform.translate(layer.position.x(), layer.position.y())
        transform.rotate(layer.rotation)
        transform.scale(layer.scale_x, layer.scale_y)

        # Get transformed rect
        rect = transform.mapRect(QRectF(QPointF(0, 0), layer.original_size))

        # Adjust handle positions to stay on edges
        handle_size = 10 / self.scale
        rotation_pos = rect.center()

        # Scale handles (directly on corners/edges)
        corners = [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
        ]
        edges = [
            QPointF(rect.center().x(), rect.top()),
            QPointF(rect.center().x(), rect.bottom()),
            QPointF(rect.left(), rect.center().y()),
            QPointF(rect.right(), rect.center().y()),
        ]

        # Draw rotation handle
        painter.setPen(QPen(self.config.selected_draw_config.handle_color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rotation_pos, handle_size, handle_size)

        # Draw scale handles
        handle_color = self.config.selected_draw_config.handle_color
        painter.setPen(
            QPen(handle_color, self.config.selected_draw_config.handle_width)
        )
        painter.setBrush(self.config.selected_draw_config.handle_color)
        for corner in corners:
            painter.drawEllipse(
                corner,
                self.config.selected_draw_config.handle_point_size,
                self.config.selected_draw_config.handle_point_size,
            )
        for edge in edges:
            # draw small circles on the edges
            painter.drawEllipse(
                edge,
                self.config.selected_draw_config.handle_edge_size,
                self.config.selected_draw_config.handle_edge_size,
            )
            # draw sides
            painter.drawLine(
                edge + QPointF(-handle_size, 0),
                edge + QPointF(handle_size, 0),
            )
            painter.drawLine(
                edge + QPointF(0, -handle_size),
                edge + QPointF(0, handle_size),
            )

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pos = (event.position() - self._pan_offset) / self.scale

            # Check for panning (Ctrl + Left Click)
            if event.modifiers() & Qt.ControlModifier:
                self._is_panning = True
                self._last_pan_point = event.position()
                return

            # Check handles first
            for layer in reversed(self.layers):
                if layer.selected and layer.visible:
                    # Compute visual center (ignoring rotation for the pivot)
                    handle_size = 10 / self.scale
                    transform = QTransform()
                    transform.translate(layer.position.x(), layer.position.y())
                    transform.rotate(layer.rotation)  # now includes rotation!
                    transform.scale(layer.scale_x, layer.scale_y)
                    visual_rect = transform.mapRect(
                        QRectF(QPointF(0, 0), layer.original_size)
                    )
                    visual_center = visual_rect.center()

                    handle_size = 10 / self.scale
                    if QLineF(pos, visual_center).length() < handle_size:
                        vec = pos - visual_center
                        initial_angle = math.atan2(vec.y(), vec.x())
                        self._active_handle = ("rotate", layer)
                        self._drag_start = {
                            "pos": pos,
                            "rotation": layer.rotation,
                            "center": visual_center,
                            "initial_angle": initial_angle,
                            "position": layer.position,  # Store the initial position
                        }
                        return

                    # Check scale handles (using fully transformed rect)
                    full_transform = QTransform()
                    full_transform.translate(layer.position.x(), layer.position.y())
                    full_transform.rotate(layer.rotation)
                    full_transform.scale(layer.scale_x, layer.scale_y)
                    full_rect = full_transform.mapRect(
                        QRectF(QPointF(0, 0), layer.original_size)
                    )
                    full_center = full_rect.center()

                    scale_handles = [
                        full_rect.topLeft(),
                        full_rect.topRight(),
                        full_rect.bottomLeft(),
                        full_rect.bottomRight(),
                        QPointF(full_center.x(), full_rect.top()),
                        QPointF(full_center.x(), full_rect.bottom()),
                        QPointF(full_rect.left(), full_center.y()),
                        QPointF(full_rect.right(), full_center.y()),
                    ]
                    for i, handle_pos in enumerate(scale_handles):
                        if QLineF(pos, handle_pos).length() < handle_size:
                            self._active_handle = (f"scale_{i}", layer)
                            self._drag_start = {
                                "pos": pos,
                                "scale_x": layer.scale_x,
                                "scale_y": layer.scale_y,
                                "position": layer.position,
                            }
                            return

            # Check layer selection
            for layer in reversed(self.layers):
                if layer.visible:
                    transform = QTransform()
                    transform.translate(layer.position.x(), layer.position.y())
                    transform.rotate(layer.rotation)
                    transform.scale(layer.scale_x, layer.scale_y)
                    rect = transform.mapRect(QRectF(QPointF(0, 0), layer.original_size))

                    if rect.contains(pos):
                        self._dragging_layer = layer
                        self._drag_offset = pos - layer.position
                        break

        super().mousePressEvent(event)

    def widget_to_image_pos(self, pos: QPointF) -> QPointF:
        return QPointF(
            (pos.x() - self.offset.x()) / self.scale,
            (pos.y() - self.offset.y()) / self.scale,
        )

    # Modified mouseDoubleClickEvent
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pos = (event.position() - self._pan_offset) / self.scale
            selected_layer = None

            # Find clicked layer
            for layer in reversed(self.layers):
                if layer.visible:
                    # Create transform including scale
                    transform = QTransform()
                    transform.translate(layer.position.x(), layer.position.y())
                    transform.rotate(layer.rotation)
                    transform.scale(layer.scale_x, layer.scale_y)
                    rect = transform.mapRect(QRectF(QPointF(0, 0), layer.original_size))
                    if rect.contains(pos):
                        selected_layer = layer
                        break

            # Toggle selection
            if selected_layer:
                # Deselect all other layers
                selected_layer.selected = not selected_layer.selected
                for layer in self.layers:
                    if layer != selected_layer:
                        layer.selected = False

                # self.layerSelected.emit(layer)
                # Toggle clicked layer's selection

            else:
                # Deselect all if clicking empty space
                for layer in self.layers:
                    layer.selected = False

            for layer in self.layers:
                self.layerSelected.emit(layer)
            self.update()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = (event.position() - self._pan_offset) / self.scale

        if self._is_panning:
            delta = event.position() - self._last_pan_point
            self._pan_offset += delta
            self._last_pan_point = event.position()
            self.update()
            return

        if self._active_handle:
            handle_type, layer = self._active_handle
            start = self._drag_start

            if "rotate" in handle_type:
                start = self._drag_start
                center = start["center"]  # The fixed pivot captured at rotation start

                # Calculate rotation delta from the initial angle
                current_vector = pos - center
                current_angle = math.atan2(current_vector.y(), current_vector.x())
                angle_delta = math.degrees(current_angle - start["initial_angle"])

                new_transform = QTransform()
                new_transform.translate(center.x(), center.y())
                new_transform.rotate(angle_delta)
                new_transform.translate(-center.x(), -center.y())

                new_position = new_transform.map(start["position"])

                # Update the layer using the original reference data
                layer.rotation = (start["rotation"] + angle_delta) % 360
                layer.position = new_position

                logger.info(
                    f"Rotating layer {layer.name} around center to {layer.rotation:.2f} degrees"
                )
                self.messageSignal.emit(
                    f"Rotating layer {layer.name} to {layer.rotation:.2f} degrees"
                )
                layer.selected = True
                self.layersChanged.emit()

                self.update()
                return

            elif "scale" in handle_type:
                # Improved scaling logic
                handle_index = int(handle_type.split("_")[-1])
                original_size = layer.original_size
                delta = pos - start["pos"]

                # Calculate new scale factors
                new_scale_x = layer.scale_x
                new_scale_y = layer.scale_y

                # Calculate position offset (for handles that move the layer)
                pos_offset = QPointF(0, 0)

                # Handle all 8 scale handles
                if handle_index in [0]:  # Top-left
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] - delta.y() / original_size.height()
                    pos_offset = delta
                    self.setCursor(CursorDef.TRANSFORM_ALL)

                elif handle_index in [1]:  # Top-right
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] - delta.y() / original_size.height()
                    pos_offset = QPointF(0, delta.y())
                    self.setCursor(CursorDef.TRANSFORM_ALL)
                elif handle_index in [2]:  # Bottom-left
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    pos_offset = QPointF(delta.x(), 0)
                    self.setCursor(CursorDef.TRANSFORM_ALL)
                elif handle_index in [3]:  # Bottom-right
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    self.setCursor(CursorDef.TRANSFORM_ALL)
                elif handle_index in [4]:  # Top-center
                    new_scale_y = start["scale_y"] - delta.y() / original_size.height()
                    pos_offset = QPointF(0, delta.y())
                    self.setCursor(CursorDef.TRANSFORM_UPDOWN)
                elif handle_index in [5]:  # Bottom-center
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    self.setCursor(CursorDef.TRANSFORM_UPDOWN)
                elif handle_index in [6]:  # Left-center
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    self.setCursor(CursorDef.TRANSFORM_LEFTRIGHT)
                    pos_offset = QPointF(delta.x(), 0)
                elif handle_index in [7]:  # Right-center
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    self.setCursor(CursorDef.TRANSFORM_LEFTRIGHT)

                # Apply scale limits
                new_scale_x = max(0.1, min(new_scale_x, 5.0))
                new_scale_y = max(0.1, min(new_scale_y, 5.0))

                # Update layer properties
                layer.scale_x = new_scale_x
                layer.scale_y = new_scale_y

                # Adjust position for handles that move the layer
                if handle_index in [0, 1, 2, 4, 6]:
                    layer.position = start["position"] + pos_offset

                logger.info(
                    f"Scaling layer {layer.name} to {layer.scale_x:.2f}, {layer.scale_y:.2f}"
                )
                self.messageSignal.emit(
                    f"Scaling layer {layer.name} to {layer.scale_x:.2f}, {layer.scale_y:.2f}"
                )

                self.layersChanged.emit()
            # layer.update()
            self.update()

        elif self._dragging_layer:
            self._dragging_layer.position = pos - self._drag_offset
            self._dragging_layer.selected = True
            self._dragging_layer.update()
            # set all other layers to not selected
            for layer in self.layers:
                if layer != self._dragging_layer:
                    layer.selected = False

            self.layersChanged.emit()
            self.update()

        super().mouseMoveEvent(event)

    def _get_resize_cursor(self, handle_name):
        cursors = {
            "top_left": Qt.SizeFDiagCursor,
            "top_right": Qt.SizeBDiagCursor,
            "bottom_left": Qt.SizeBDiagCursor,
            "bottom_right": Qt.SizeFDiagCursor,
            "top_center": Qt.SizeVerCursor,
            "bottom_center": Qt.SizeVerCursor,
            "left_center": Qt.SizeHorCursor,
            "right_center": Qt.SizeHorCursor,
        }
        return cursors.get(handle_name, Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_panning = False
            self._active_handle = None
            self._dragging_layer = None
            self.setCursor(CursorDef.IDLE_CURSOR)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            # Get mouse position before zoom
            old_pos = self.widget_to_image_pos(event.position())

            # Calculate zoom factor
            zoom_factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            new_scale = max(0.1, min(self.scale * zoom_factor, 10.0))

            # Calculate position shift to keep cursor over same image point
            self.offset += old_pos * self.scale - old_pos * new_scale
            self.scale = new_scale

            self.update()

            # Zoom canvas
            # delta = event.angleDelta().y()
            # zoom_factor = 1.1 if delta > 0 else 0.9
            # self.scale *= zoom_factor
            # self.scale = max(0.1, min(self.scale, 10.0))
            # self.update()
        else:
            # Scale selected layer (if any)
            for layer in self.layers:
                if layer.selected:
                    delta = event.angleDelta().y()
                    layer.scale_x *= 1.1 if delta > 0 else 0.9
                    layer.scale_y *= 1.1 if delta > 0 else 0.9
                    self.update()
                    break

    def sizeHint(self):
        if not self.layers:
            return QSize(800, 600)
        buffer_width = 0
        buffer_height = 0
        for layer in self.layers:
            if not layer.image.isNull():
                pos = (
                    layer.position
                    if isinstance(layer.position, QPoint)
                    else layer.position.toPoint()
                )
                layer_right = pos.x() + layer.image.width()
                layer_bottom = pos.y() + layer.image.height()
                buffer_width = max(buffer_width, layer_right)
                buffer_height = max(buffer_height, layer_bottom)
        return (
            QSize(buffer_width, buffer_height)
            if buffer_width and buffer_height
            else QSize(800, 600)
        )

    def minimumSizeHint(self):
        return QSize(100, 100)

    def add_layer(self, layer, index=-1):
        layer.name = f"{len(self.layers) + 1}_" + layer.name
        if index >= 0:
            self.layers.append(layer)
        else:
            self.layers.insert(0, layer)

        self._update_back_buffer()
        self.update()
        self.messageSignal.emit(f"Added layer {layer.name}")

    def clear_layers(self):
        self.layers.clear()
        self._update_back_buffer()
        self.update()
        self.layerRemoved.emit()
        self.messageSignal.emit("Cleared all layers")

    def event(self, event):
        result = super().event(event)
        # Only handle mouse events here, not key events
        if event.type() in {
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Wheel,
        }:
            self.update()
        return result

    def keyPressEvent(self, event):
        # Handle Delete key
        if event.key() == Qt.Key_Delete:
            self.delete_layer()
            return  # Important: return after handling

        # Handle Ctrl key
        if event.key() == Qt.Key_Control:
            self.setCursor(Qt.OpenHandCursor)
            return  # Important: return after handling

        # Handle Ctrl+C
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self.copy_layer()
            return  # Important: return after handling

        # Handle Ctrl+V
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self.paste_layer()
            return  # Important: return after handling

        # Let parent handle other keys
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Control:
            self.setCursor(Qt.ArrowCursor)
        super().keyReleaseEvent(event)

    def export_current_state(self):
        filename = self.config.filename_format.format(
            project_name=self.config.project_name,
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        filename = self.config.export_folder / f"{filename}.png"
        logger.info(f"Exporting baked image to {filename}")
        # 1. Calculate bounding box of all visible layers
        top_left = QPointF(sys.maxsize, sys.maxsize)
        bottom_right = QPointF(-sys.maxsize, -sys.maxsize)

        self.loading_dialog = QProgressDialog(
            "Baking Please wait...", "Cancel", 0, 0, self.parentWidget()
        )

        self.loading_dialog.setWindowTitle("Please Wait")
        self.loading_dialog.setWindowModality(Qt.WindowModal)
        self.loading_dialog.setCancelButton(None)  # Remove cancel button if not needed
        self.loading_dialog.show()

        # Force UI update
        QApplication.processEvents()

        # Setup worker thread
        self.worker_thread = QThread()
        self.worker = BakerWorker(
            layers=self.layers,
            top_left=top_left,
            bottom_right=bottom_right,
            filename=filename,
        )
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(self.handle_baker_result)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.handle_baker_error)

        # Cleanup connections
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.loading_dialog.close)

        # Start processing
        self.worker_thread.start()

    def handle_baker_result(
        self,
        baking_result: BakingResult,
    ):
        logger.info("Baking completed.")

        filename, image = baking_result.filename, baking_result.image
        masks = baking_result.masks
        mask_names = baking_result.mask_names
        annotations = baking_result.annotations
        image.save(str(filename))
        logger.info(f"Saved annotated image to annotated_{filename}")

        if self.config.is_debug:
            if self.config.write_masks:
                for i, mask in enumerate(masks):
                    mask_name = mask_names[i]
                    write_to = filename.parent / f"{mask_name}_{filename.name}"

                    cv2.imwrite(write_to, mask)

                    logger.info(f"Saved mask for {mask_name}")
            logger.info(f"Saved baked image to {filename}")
            if self.config.write_annotations:
                image = qpixmap_to_numpy(image.copy())
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
                drawn = draw_annotations(image, annotations)
                write_to = filename.parent / f"annotated_{filename.name}"

                cv2.imwrite(str(write_to), drawn)

                logger.info(f"Saved annotated image to annotated_{filename}")

        Annotation.save_as_json(annotations, f"{filename.parent/filename.stem}.json")
        logger.info(f"Saved annotations to {filename}.json")

    def handle_baker_error(self, error_msg):
        self.loading_dialog.close()
        QMessageBox.critical(
            self.parentWidget(), "Error", f"Processing failed: {error_msg}"
        )

    def bake_settings(self, bake_settings: LayerState):
        pass

    def copy_layer(self):
        self.selected_layer = self._get_selected_layer()
        if self.selected_layer:
            self.copied_layer = self.selected_layer.copy()
            self.messageSignal.emit(f"Copied layer {self.selected_layer.name}.")
        else:
            self.messageSignal.emit("No layer selected to copy.")

    def paste_layer(self):
        if self.copied_layer:
            new_layer = self.copied_layer.copy()
            new_layer.position += QPointF(10, 10)
            self.add_layer(new_layer, index=0)
            self.update()
            self.layerSelected.emit(new_layer)
            self.messageSignal.emit(f"Pasted layer {new_layer.name}.")
        else:
            self.messageSignal.emit("No layer copied to paste.")

    def delete_layer(self):
        self.selected_layer = self._get_selected_layer()
        if self.selected_layer:
            remaining_layers = []
            removed = False
            for layer in self.layers:
                if layer.selected:
                    removed = True
                    self.messageSignal.emit(f"Deleted {layer.name} layer.")
                else:
                    remaining_layers.append(layer)

            if removed:
                self.layers = remaining_layers
                self._update_back_buffer()
                self.layerRemoved.emit()
                self.update()
