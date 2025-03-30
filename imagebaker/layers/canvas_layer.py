from imagebaker.core.configs import CanvasConfig
from imagebaker.core.defs import Annotation, MouseMode, BakingResult, DrawingState
from imagebaker.layers import BaseLayer
from imagebaker.core.configs import CursorDef
from imagebaker import logger
from imagebaker.workers import BakerWorker
from imagebaker.utils.image import qpixmap_to_numpy, draw_annotations


from PySide6.QtCore import (
    QPointF,
    QPoint,
    Qt,
    Signal,
    QRectF,
    QLineF,
    QThread,
    QSizeF,
)
from PySide6.QtGui import (
    QColor,
    QPixmap,
    QPainter,
    QBrush,
    QPen,
    QWheelEvent,
    QMouseEvent,
    QKeyEvent,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QMessageBox,
    QProgressDialog,
)

import math
import cv2
from datetime import datetime


class CanvasLayer(BaseLayer):
    layersChanged = Signal()
    layerSelected = Signal(BaseLayer)
    annotationAdded = Signal(Annotation)
    annotationUpdated = Signal(Annotation)
    bakingResult = Signal(BakingResult)
    thumbnailsAvailable = Signal(int)

    def __init__(self, parent=None, config=CanvasConfig()):
        """
        Initialize the CanvasLayer with a parent widget and configuration.

        Args:
            parent (QWidget, optional): The parent widget for this layer. Defaults to None.
            config (CanvasConfig): Configuration settings for the canvas layer.
        """
        super().__init__(parent, config)
        self.image = QPixmap()
        self.is_annotable = False
        self.last_pan_point = None
        self.state_thumbnail = dict()

        self._last_draw_point = None  # Track the last point for smooth drawing

    def init_ui(self):
        """
        Initialize the user interface for the canvas layer, including size policies
        and storing the original size of the layer.
        """
        logger.info(f"Initializing Layer UI of {self.layer_name}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.original_size = QSizeF(self.image.size())  # Store original size

    def handle_key_release(self, event: QKeyEvent):
        """
        Handle key release events, such as resetting the mouse mode when the Control key is released.

        Args:
            event (QKeyEvent): The key release event.
        """
        if event.key() == Qt.Key_Control:
            if self.mouse_mode not in [MouseMode.DRAW, MouseMode.ERASE]:
                self.mouse_mode = MouseMode.IDLE

    def _update_back_buffer(self):
        """
        Update the back buffer for the canvas layer by rendering all visible layers
        with their transformations and opacity settings.
        """
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
        finally:
            painter.end()

        self.image = self._back_buffer

    ## Helper functions ##
    def handle_key_press(self, event: QKeyEvent):

        # Handle Delete key
        if event.key() == Qt.Key_Delete:
            self._delete_layer()
            return  # Important: return after handling

        # Handle Ctrl key
        if event.key() == Qt.Key_Control:
            if self.mouse_mode not in [MouseMode.DRAW, MouseMode.ERASE]:
                self.mouse_mode = MouseMode.PAN

            return  # Important: return after handling

        # Handle Ctrl+C
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self._copy_layer()
            return  # Important: return after handling

        # Handle Ctrl+V
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self._paste_layer()
            return  # Important: return after handling

    def paint_layer(self, painter: QPainter):
        """
        Paint the canvas layer, including all visible layers, their transformations,
        and any drawing states or selection indicators.

        Args:
            painter (QPainter): The painter object used for rendering.
        """
        painter.translate(self.pan_offset)
        painter.scale(self.scale, self.scale)
        for layer in self.layers:
            if layer.visible and not layer.image.isNull():
                painter.save()
                painter.translate(layer.position)
                painter.rotate(layer.rotation)
                painter.scale(layer.scale_x, layer.scale_y)

                # painter.drawPixmap(0, 0, layer.image)
                # painter.setOpacity(layer.opacity / 255)
                # Create a new pixmap with adjusted opacity
                pixmap_with_alpha = QPixmap(layer.image.size())
                pixmap_with_alpha.fill(Qt.transparent)  # Ensure transparency

                # Use QPainter to apply opacity to the pixmap
                temp_painter = QPainter(pixmap_with_alpha)
                opacity = layer.opacity / 255.0
                temp_painter.setOpacity(opacity)  # Scale opacity to 0.0-1.0
                temp_painter.drawPixmap(0, 0, layer.image)
                temp_painter.end()

                # Draw the modified pixmap
                painter.drawPixmap(0, 0, pixmap_with_alpha)

                if layer.selected:
                    painter.setPen(
                        QPen(
                            self.config.selected_draw_config.color,
                            self.config.selected_draw_config.line_width,
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
                    painter.drawRect(QRectF(QPointF(0, 0), layer.original_size))
                painter.restore()

                if layer.selected:
                    self._draw_transform_handles(painter, layer)
                if layer.layer_state.drawing_states:
                    painter.save()
                    painter.translate(layer.position)
                    painter.rotate(layer.rotation)
                    painter.scale(layer.scale_x, layer.scale_y)

                    for state in layer.layer_state.drawing_states:
                        painter.setRenderHints(QPainter.Antialiasing)
                        painter.setPen(
                            QPen(
                                state.color,
                                state.size,
                                Qt.SolidLine,
                                Qt.RoundCap,
                                Qt.RoundJoin,
                            )
                        )
                        # Draw the point after applying transformations
                        painter.drawPoint(state.position)

                    painter.restore()
        if self.layer_state.drawing_states:
            painter.save()
            painter.translate(self.position)
            painter.rotate(self.rotation)
            painter.scale(self.scale_x, self.scale_y)

            for state in self.layer_state.drawing_states:
                painter.setRenderHints(QPainter.Antialiasing)
                painter.setPen(
                    QPen(
                        state.color,
                        state.size,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.RoundJoin,
                    )
                )
                painter.drawPoint(state.position)

            painter.restore()
        painter.end()

    def _draw_transform_handles(self, painter, layer):
        """
        Draw rotation and scaling handles for the selected layer.

        Args:
            painter (QPainter): The painter object used for rendering.
            layer (BaseLayer): The layer for which the handles are drawn.
        """
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

        # Draw rotation handle at the center and fill it
        painter.setPen(
            QPen(
                self.config.selected_draw_config.handle_color,
                self.config.selected_draw_config.handle_width,
            )
        )
        painter.setBrush(self.config.selected_draw_config.handle_color)
        painter.drawEllipse(
            rotation_pos,
            self.config.selected_draw_config.handle_point_size * 2,
            self.config.selected_draw_config.handle_point_size * 2,
        )
        # now draw rotation symbol
        painter.setPen(
            QPen(
                self.config.selected_draw_config.handle_color,
                self.config.selected_draw_config.handle_width,
            )
        )
        painter.drawLine(
            rotation_pos,
            rotation_pos + QPointF(0, -handle_size),
        )
        painter.drawLine(
            rotation_pos,
            rotation_pos + QPointF(0, handle_size),
        )
        painter.drawLine(
            rotation_pos,
            rotation_pos + QPointF(-handle_size, 0),
        )
        painter.drawLine(
            rotation_pos,
            rotation_pos + QPointF(handle_size, 0),
        )

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

    def _add_drawing_state(self, pos: QPointF):
        """
        Add a new drawing state to the selected layer or the canvas layer itself,
        based on the current mouse mode (DRAW or ERASE).

        Args:
            pos (QPointF): The position where the drawing state is added.
        """
        """Add a new drawing state."""
        self.selected_layer = self._get_selected_layer()
        layer = self.selected_layer if self.selected_layer else self

        # Convert the position to be relative to the layer
        relative_pos = pos - layer.position

        if self.mouse_mode == MouseMode.ERASE:
            # Remove drawing states within the eraser's area
            layer.layer_state.drawing_states = [
                state
                for state in layer.layer_state.drawing_states
                if (state.position - relative_pos).manhattanLength() > self.brush_size
            ]
        elif self.mouse_mode == MouseMode.DRAW:
            # Add a new drawing state only if the position has changed
            # if self._last_draw_point is None or self._last_draw_point != relative_pos:
            drawing_state = DrawingState(
                position=relative_pos,  # Store relative position
                color=self.drawing_color,
                size=self.brush_size,
            )
            layer.layer_state.drawing_states.append(drawing_state)
            self._last_draw_point = relative_pos  # Update the last draw point
            # logger.debug(f"Added drawing state at position: {relative_pos}")

        self.update()  # Refresh the canvas to show the new drawing

    def handle_wheel(self, event: QWheelEvent):
        if self.mouse_mode == MouseMode.DRAW or self.mouse_mode == MouseMode.ERASE:
            # Adjust the brush size using the mouse wheel
            delta = event.angleDelta().y() / 120  # Each step is 120 units
            self.brush_size = max(
                1, self.brush_size + int(delta)
            )  # Ensure size is >= 1
            self.messageSignal.emit(f"Brush size: {self.brush_size}")
            self.update()  # Refresh the canvas to show the updated brush cursor
            return
        if event.modifiers() & Qt.ControlModifier:
            # Get mouse position in widget coordinates
            mouse_pos = event.position()

            # Calculate zoom factor
            zoom_factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            old_scale = self.scale
            new_scale = max(0.1, min(old_scale * zoom_factor, 10.0))

            # Calculate the image point under the cursor before zooming
            before_zoom_img_pos = (mouse_pos - self.pan_offset) / old_scale

            # Update scale
            self.scale = new_scale

            # Calculate the new position of the same image point after zooming
            after_zoom_widget_pos = before_zoom_img_pos * new_scale + self.pan_offset

            # Adjust pan offset to keep the image point under the cursor fixed
            self.pan_offset += mouse_pos - after_zoom_widget_pos

            # Update mouse mode based on zoom direction
            self.mouse_mode = (
                MouseMode.ZOOM_IN if event.angleDelta().y() > 0 else MouseMode.ZOOM_OUT
            )

            self.zoomChanged.emit(self.scale)
            self.update()

    def handle_mouse_release(self, event: QMouseEvent):

        if event.button() == Qt.LeftButton:
            self._active_handle = None
            self._dragging_layer = None

            # Reset drawing state
            if self.mouse_mode in [MouseMode.DRAW, MouseMode.ERASE]:
                self._last_draw_point = None
                self.update()  # Refresh the canvas to show the updated brush cursor

    def handle_mouse_move(self, event: QMouseEvent):
        pos = (event.position() - self.pan_offset) / self.scale
        # logger.info(f"Drawing states: {self.layer_state.drawing_states}")

        # Update cursor position for the brush
        self._cursor_position = event.position()

        if event.buttons() & Qt.LeftButton:
            # Handle drawing or erasing
            if self.mouse_mode in [MouseMode.DRAW, MouseMode.ERASE]:
                self._add_drawing_state(pos)
                # self._last_draw_point = pos
                return

        if self.mouse_mode == MouseMode.PAN:
            if (
                event.modifiers() & Qt.ControlModifier
                and event.buttons() & Qt.LeftButton
            ):
                if self.last_pan_point:
                    delta = event.position() - self.last_pan_point
                    self.pan_offset += delta
                    self.last_pan_point = event.position()
                    self.update()
                    return
            else:
                self.last_pan_point = None
                self.mouse_mode = MouseMode.IDLE

        if self._active_handle:
            handle_type, layer = self._active_handle
            start = self._drag_start
            if "rotate" in handle_type:
                start = self._drag_start
                center = start["center"]

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
                    f"Rotating layer {layer.layer_name} around center to {layer.rotation:.2f} degrees"
                )
                self.messageSignal.emit(
                    f"Rotating layer {layer.layer_name} to {layer.rotation:.2f} degrees"
                )
                layer.selected = True
                self.layersChanged.emit()

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
                    self.mouse_mode = MouseMode.RESIZE
                elif handle_index in [2]:  # Bottom-left
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    pos_offset = QPointF(delta.x(), 0)
                    self.mouse_mode = MouseMode.RESIZE
                elif handle_index in [3]:  # Bottom-right
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    self.mouse_mode = MouseMode.RESIZE
                elif handle_index in [4]:  # Top-center
                    new_scale_y = start["scale_y"] - delta.y() / original_size.height()
                    pos_offset = QPointF(0, delta.y())
                    self.mouse_mode = MouseMode.RESIZE_HEIGHT
                elif handle_index in [5]:  # Bottom-center
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    self.mouse_mode = MouseMode.RESIZE_HEIGHT
                elif handle_index in [6]:  # Left-center
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    self.mouse_mode = MouseMode.RESIZE_WIDTH
                    pos_offset = QPointF(delta.x(), 0)
                elif handle_index in [7]:  # Right-center
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    self.mouse_mode = MouseMode.RESIZE_WIDTH

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
                    f"Scaling layer {layer.layer_name} to {layer.scale_x:.2f}, {layer.scale_y:.2f}"
                )
                self.messageSignal.emit(
                    f"Scaling layer {layer.layer_name} to {layer.scale_x:.2f}, {layer.scale_y:.2f}"
                )

                self.layersChanged.emit()
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

    def handle_mouse_press(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pos = (event.position() - self.pan_offset) / self.scale
            if self.mouse_mode in [MouseMode.DRAW, MouseMode.ERASE]:
                logger.info(f"Drawing mode: {self.mouse_mode} at position: {pos}")
                # Add a drawing state immediately on mouse press
                self._last_draw_point = pos
                self._add_drawing_state(pos)  # Add the drawing state here
                return
            if event.modifiers() & Qt.ControlModifier:
                self.mouse_mode = MouseMode.PAN
                self.last_pan_point = event.position()
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
                        layer.selected = True
                        # then set all other layers to not selected
                        for other_layer in self.layers:
                            if other_layer != layer:
                                other_layer.selected = False
                        layer.update()
                        self.layersChanged.emit()

                        break
        # if right click, deselect all layers
        elif event.button() == Qt.RightButton:
            for layer in self.layers:
                layer.selected = False
            self.mouse_mode = MouseMode.IDLE
            self.layersChanged.emit()
            self.update()

    def handle_mouse_double_click(self, event: QMouseEvent, pos: QPoint):
        # was just trying to select/deselect layers with double click
        # if left double click
        # if event.button() == Qt.LeftButton:
        #     # did we click on a layer?
        #     pos = (event.position() - self.pan_offset) / self.scale
        #     selected_layer = None
        #     # Find clicked layer
        #     for layer in reversed(self.layers):
        #         if layer.visible:
        #             # Create transform including scale
        #             transform = QTransform()
        #             transform.translate(layer.position.x(), layer.position.y())
        #             transform.rotate(layer.rotation)
        #             transform.scale(layer.scale_x, layer.scale_y)
        #             rect = transform.mapRect(QRectF(QPointF(0, 0), layer.original_size))
        #             if rect.contains(pos):
        #                 selected_layer = layer
        #                 break

        #     if selected_layer:
        #         # toggle selection
        #         selected_layer.selected = not selected_layer.selected
        #         # make all other layers unselected
        #         for layer in self.layers:
        #             if layer != selected_layer:
        #                 layer.selected = False
        #     else:
        #         # we clicked on the background
        #         # make all layers unselected
        #         for layer in self.layers:
        #             layer.selected = False
        self.update()

    def _get_selected_layer(self):
        for layer in self.layers:
            if layer.selected:
                return layer
        return None

    def add_layer(self, layer: BaseLayer, index=-1):
        """
        This function adds a new layer to the canvas layer.

        Args:
            layer (BaseLayer): The layer to add.
            index (int, optional): The index at which to add the layer. Defaults to -1.

        Raises:
            ValueError: If the layer is not a BaseLayer instance
        """
        layer.layer_name = f"{len(self.layers) + 1}_" + layer.layer_name
        if index >= 0:
            self.layers.append(layer)
        else:
            self.layers.insert(0, layer)

        self._update_back_buffer()
        self.update()
        self.messageSignal.emit(f"Added layer {layer.layer_name}")

    def clear_layers(self):
        """
        Clear all layers from the canvas layer.
        """
        self.layers.clear()
        self._update_back_buffer()
        self.update()
        self.messageSignal.emit("Cleared all layers")

    def _copy_layer(self):
        """
        Copy the selected layer to the clipboard.
        """
        self.selected_layer = self._get_selected_layer()
        if self.selected_layer:
            self.copied_layer = self.selected_layer.copy()
            self.messageSignal.emit(f"Copied layer {self.selected_layer.layer_name}.")
        else:
            self.messageSignal.emit("No layer selected to copy.")

    def _paste_layer(self):
        """
        Paste the copied layer to the canvas layer.
        """
        if self.copied_layer:
            new_layer = self.copied_layer.copy()
            new_layer.position += QPointF(10, 10)
            self.add_layer(new_layer, index=0)
            self.update()
            self.layerSelected.emit(new_layer)
            self.messageSignal.emit(f"Pasted layer {new_layer.layer_name}.")
        else:
            self.messageSignal.emit("No layer copied to paste.")

    def _delete_layer(self):
        self.selected_layer = self._get_selected_layer()
        # now handled from bakertab
        # if self.selected_layer:
        #     remaining_layers = []
        #     removed = False
        #     for layer in self.layers:
        #         if layer.selected:
        #             removed = True
        #             self.messageSignal.emit(f"Deleted {layer.layer_name} layer.")
        #         else:
        #             remaining_layers.append(layer)

        #     if removed:
        #         self.layers = remaining_layers
        #         self._update_back_buffer()
        #         self.layerRemoved.emit(self.selected_layer)
        #         self.update()

    def export_current_state(self, export_to_annotation_tab=False):
        """
        Export the current state of the canvas layer to an image file or annotation tab.

        Args:
            export_to_annotation_tab (bool, optional): Whether to export the image to the annotation tab. Defaults to False.

        Raises:
            ValueError: If the layer is not a BaseLayer instance
        """
        if not self.layers:
            QMessageBox.warning(
                self,
                "Operation Not Possible",
                "No layers are available to export. Please add layers before exporting.",
                QMessageBox.Ok,
            )
            return
        filename = self.config.filename_format.format(
            project_name=self.config.project_name,
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        filename = self.config.export_folder / f"{filename}.png"
        logger.info(f"Exporting baked image to {filename}")
        self.states = {0: [layer.layer_state for layer in self.layers]}

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
            states=self.states,
            filename=filename,
        )
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(
            lambda results, export_to_annotation_tab=export_to_annotation_tab: self.handle_baker_results(
                results, export_to_annotation_tab=export_to_annotation_tab
            )
        )
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.handle_baker_error)

        # Cleanup connections
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.loading_dialog.close)

        # Start processing
        self.worker_thread.start()

    def handle_baker_error(self, error_msg):
        """
        To handle any errors that occur during the baking process.
        """
        self.loading_dialog.close()
        QMessageBox.critical(
            self.parentWidget(), "Error", f"Processing failed: {error_msg}"
        )

    def predict_state(self):
        """
        To send the current state to the prediction tab.
        """
        self.export_current_state(export_to_annotation_tab=True)

    def play_states(self):
        """Play all the states stored in self.states."""
        if len(self.states) == 0:
            logger.warning("No states to play")
            self.messageSignal.emit("No states to play")
            return

        for step, states in sorted(
            self.states.items()
        ):  # Ensure states are played in order
            self.messageSignal.emit(f"Playing step {step}")
            logger.info(f"Playing step {step}")

            # Update the slider position
            self.parentWidget().timeline_slider.setValue(step)
            # Clear the current drawing states

            for state in states:
                # Get the layer corresponding to the state
                layer = self.get_layer(state.layer_id)
                if layer:
                    # Update the layer's state
                    layer.layer_state = state
                    layer.update()

            # Update the UI to reflect the changes
            self.update()  # Update the current widget

            QApplication.processEvents()  # Process pending events to refresh the UI

            # Wait for the next frame
            QThread.msleep(int(1000 / self.config.fps))  # Convert FPS to milliseconds

        logger.info("Finished playing states")
        self.messageSignal.emit("Finished playing states")

    def export_baked_states(self, export_to_annotation_tab=False):
        """Export all the states stored in self.states."""
        if len(self.states) == 0:
            msg = "No states to export. Creating a single image."
            logger.warning(msg)
            self.messageSignal.emit(msg)
            self.states = {0: [layer.layer_state for layer in self.layers]}

        filename = self.config.filename_format.format(
            project_name=self.config.project_name,
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        filename = self.config.export_folder / f"{filename}.png"

        self.loading_dialog = QProgressDialog(
            "Exporting states, please wait...", "Cancel", 0, 0, self.parentWidget()
        )
        self.loading_dialog.setWindowTitle("Please Wait")
        self.loading_dialog.setWindowModality(Qt.WindowModal)
        self.loading_dialog.setCancelButton(None)
        self.loading_dialog.show()

        QApplication.processEvents()

        # Setup worker thread
        self.worker_thread = QThread()
        self.worker = BakerWorker(
            states=self.states, layers=self.layers, filename=filename
        )
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(
            lambda results, export_to_annotation_tab=export_to_annotation_tab: self.handle_baker_results(
                results, export_to_annotation_tab
            )
        )  # Handle multiple results
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.handle_baker_error)

        # Cleanup connections
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.loading_dialog.close)

        # Start processing
        self.worker_thread.start()

    def handle_baker_results(
        self,
        baking_results: list[BakingResult],
        export_to_annotation_tab=False,
    ):
        logger.info("Baking completed.")
        for baking_result in baking_results:

            filename, image = baking_result.filename, baking_result.image
            masks = baking_result.masks
            mask_names = baking_result.mask_names
            annotations = baking_result.annotations

            if not export_to_annotation_tab:
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

                Annotation.save_as_json(
                    annotations, f"{filename.parent/filename.stem}.json"
                )
                logger.info(f"Saved annotations to {filename}.json")
            else:
                self.bakingResult.emit(baking_result)

    def export_states_to_predict(self):
        self.export_baked_states(export_to_annotation_tab=True)
