import math
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig, CursorDef, LayerConfig
from imagebaker.core.defs import Annotation, DrawingState, LayerState, MouseMode
from imagebaker.utils.state_utils import calculate_intermediate_states


class BaseLayer(QWidget):
    annotation_clipboard: list[Annotation] = []
    messageSignal = Signal(str)
    modeChanged = Signal(object)
    zoomChanged = Signal(float)
    mouseMoved = Signal(QPointF)
    annotationCleared = Signal()
    layerRemoved = Signal(int)
    layersChanged = Signal()
    layerSignal = Signal(object)

    def __init__(self, parent: QWidget, config: LayerConfig | CanvasConfig):
        """
        BaseLayer is an abstract class that represents a single layer in the canvas.
        It provides functionality for managing layer properties, handling user interactions,
        and rendering the layer's content. This class is designed to be extended by
        subclasses that implement specific layer behaviors.

        Attributes:
            id (int): Unique identifier for the layer.
            layer_state (LayerState): The current state of the layer, including properties
                like position, scale, rotation, and visibility.
            previous_state (LayerState): The previous state of the layer, used for undo operations.
            layers (list[BaseLayer]): A list of child layers associated with this layer.
            annotations (list[Annotation]): A list of annotations associated with the layer.
            selected_annotation (Optional[Annotation]): The currently selected annotation.
            current_annotation (Optional[Annotation]): The annotation currently being created or edited.
            copied_annotation (Optional[Annotation]): A copied annotation for pasting.
            image (QPixmap): The image associated with the layer.
            scale (float): The current scale of the layer.
            pan_offset (QPointF): The current pan offset of the layer.
            mouse_mode (MouseMode): The current mouse interaction mode (e.g., DRAW, PAN, IDLE).
            states (dict[int, list[LayerState]]): A dictionary of saved states for the layer,
                indexed by step.
            current_step (int): The current step in the layer's state history.
            drawing_color (QColor): The color used for drawing operations.
            brush_size (int): The size of the brush used for drawing operations.
            config (LayerConfig | CanvasConfig): Configuration settings for the layer.
            file_path (Path): The file path associated with the layer's image.
            visible (bool): Whether the layer is visible.
            selected (bool): Whether the layer is selected.
            opacity (float): The opacity of the layer (0.0 to 1.0).
            transform_origin (QPointF): The origin point for transformations (e.g., rotation, scaling).
            playing (bool): Whether the layer is currently in a "playing" state (e.g., animation).
            allow_annotation_export (bool): Whether annotations can be exported for this layer.

        Signals:
            messageSignal (str): Emitted when a message needs to be displayed.
            zoomChanged (float): Emitted when the zoom level changes.
            mouseMoved (QPointF): Emitted when the mouse moves over the layer.
            annotationCleared (): Emitted when annotations are cleared.
            layerRemoved (int): Emitted when a layer is removed.
            layersChanged (): Emitted when the layer list changes.
            layerSignal (object): Emitted with a layer-related signal.

        Methods:
            save_current_state(steps: int = 1):
                Save the current state of the layer, including intermediate states
                calculated between the previous and current states.

            set_image(image_path: Path | QPixmap | QImage):
                Set the image for the layer from a file path, QPixmap, or QImage.

            get_layer(id: str) -> "BaseLayer":
                Retrieve a child layer by its ID.

            reset_view():
                Reset the view of the layer, including scale and offset.

            clear_annotations():
                Clear all annotations associated with the layer.

            update_cursor():
                Update the cursor based on the current mouse mode.

            undo():
                Undo the last change to the layer's state.

            set_mode(mode: MouseMode):
                Set the mouse interaction mode for the layer.

            widget_to_image_pos(pos: QPointF) -> QPointF:
                Convert a widget position to an image position.

            get_thumbnail(annotation: Annotation = None) -> QPixmap:
                Generate a thumbnail for the layer or a specific annotation.

            copy() -> "BaseLayer":
                Create a copy of the layer, including its properties and annotations.

            paintEvent(event):
                Handle the paint event for the layer.

            paint_layer(painter: QPainter):
                Abstract method to paint the layer's content. Must be implemented by subclasses.

            handle_mouse_press(event: QMouseEvent):
                Abstract method to handle mouse press events. Must be implemented by subclasses.

            handle_mouse_move(event: QMouseEvent):
                Abstract method to handle mouse move events. Must be implemented by subclasses.

            handle_mouse_release(event: QMouseEvent):
                Abstract method to handle mouse release events. Must be implemented by subclasses.

            handle_wheel(event: QWheelEvent):
                Abstract method to handle wheel events. Must be implemented by subclasses.

            handle_key_press(event: QKeyEvent):
                Abstract method to handle key press events. Must be implemented by subclasses.

            handle_key_release(event: QKeyEvent):
                Abstract method to handle key release events. Must be implemented by subclasses.

        Notes:
            - This class is designed to be extended by subclasses that implement specific
            layer behaviors (e.g., drawing, annotation, image manipulation).
            - The `paint_layer` method must be implemented by subclasses to define how
            the layer's content is rendered.

        """
        super().__init__(parent)
        self.id = id(self)
        self.layer_state = LayerState(layer_id=self.id)
        self._previous_state = None
        self.thumbnails = {}
        self.label_rects = []
        self._last_state = None
        self.config = config
        self.parent_obj = parent
        self.mouse_mode = MouseMode.IDLE
        self.file_path: Path = Path("Runtime")
        self.layersChanged.connect(self.update)

        self.drag_start: QPointF = None
        self.drag_offset: QPointF = None
        self.offset: QPointF = QPointF(0, 0)
        self.pan_start: QPointF = None
        self.pan_offset: QPointF = None
        self._image = QPixmap()
        self._original_image = QPixmap()
        self.annotations: list[Annotation] = []
        self.current_annotation: Annotation | None = None
        self.copied_annotation: Annotation | None = None
        self.selected_annotation: Annotation | None = None

        self.layers: list[BaseLayer] = []
        self.plugins = []
        self.layer_masks = []
        self._back_buffer = QPixmap()
        self.current_label: str = None
        self.current_color: QColor = QColor(255, 255, 255)

        self.scale = 1.0
        self.pan_offset = QPointF(0, 0)
        self.last_pan_point = None
        self._dragging_layer = None
        self._drag_offset = QPointF(0, 0)
        self._current_hover = None
        self._active_handle = None
        self._transform_start = None
        self._is_panning = False
        self._mouse_widget_pos: QPointF | None = None
        self.offset = QPointF(0, 0)
        self.copied_layer: BaseLayer = None
        self.selected_layer: BaseLayer = None
        self.mouse_mode = MouseMode.IDLE
        self.prev_mouse_mode = MouseMode.IDLE
        self.states: dict[str, list[LayerState]] = {}

        self.states: dict[int, list[LayerState]] = {}
        self.previous_state = None
        self.current_step = 0
        self.drawing_color = QColor(Qt.red)  # Default drawing color
        self.brush_size = 5  # Default brush size

        if isinstance(config, LayerConfig):
            self.current_label = self.config.predefined_labels[0].name
            self.current_color = self.config.predefined_labels[0].color

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def get_layer(self, id: str) -> "BaseLayer":
        """
        Get a child layer by its ID.

        Args:
            id (str): The ID of the layer to retrieve.

        Returns:
            Child of BaseLayer: The child layer with the specified ID, or None if not found
        """
        for layer in self.layers:
            if layer.layer_id == id:
                return layer
        return None

    def save_current_state(self, steps: int = 1):
        """
        Save the current state of the layer, including intermediate states
        calculated between the previous and current states.

        Args:
            steps (int): The number of intermediate steps to calculate between

        Returns:
            None
        """
        curr_states = {}
        mode = self.mouse_mode

        for layer in self.layers:
            # Calculate intermediate states between previous_state and current_state
            intermediate_states = calculate_intermediate_states(
                layer.previous_state, layer.layer_state.copy(), steps
            )
            is_selected = layer.selected

            for step, state in enumerate(intermediate_states):
                step += self.current_step

                logger.info(f"Saving state {step} for layer {layer.layer_id}: {state}")
                state.selected = False
                if step not in curr_states:
                    curr_states[step] = []

                # Deep copy the drawing states to avoid unintended modifications
                state.drawing_states = [
                    DrawingState(
                        position=d.position,
                        color=d.color,
                        size=d.size,
                    )
                    for d in layer.layer_state.drawing_states
                ]
                curr_states[step].append(state)

            # Update the layer's previous_state to the current state
            layer.previous_state = layer.layer_state.copy()
            layer.selected = is_selected

        # Save the calculated states in self.states
        for step, states in curr_states.items():
            self.states[step] = states
            self.current_step = step

        # Save the current layer's state
        self.previous_state = self.layer_state.copy()
        self.layer_state.drawing_states = [
            DrawingState(
                position=d.position,
                color=d.color,
                size=d.size,
            )
            for d in self.layer_state.drawing_states
        ]

        # Emit a message signal indicating the state has been saved
        self.messageSignal.emit(f"Saved state {self.current_step}")
        self.mouse_mode = mode

        self.update()

    def minimumSizeHint(self):
        """Return the minimum size hint for the widget."""
        return QSize(100, 100)

    def widget_to_image_pos(self, pos: QPointF) -> QPointF:
        """
        Convert a widget position to an image position.
        """
        return QPointF(
            (pos.x() - self.offset.x()) / self.scale,
            (pos.y() - self.offset.y()) / self.scale,
        )

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
            # Create a custom cursor for drawing (circle representing brush size)
            self.setCursor(self._create_custom_cursor(self.drawing_color, "circle"))
        elif self.mouse_mode == MouseMode.ERASE:
            # Create a custom cursor for erasing (square representing eraser size)
            self.setCursor(self._create_custom_cursor(Qt.white, "square"))
        else:
            # Reset to default cursor
            self.setCursor(Qt.ArrowCursor)

    def _create_mode_cursor(self, mode: MouseMode) -> QCursor:
        """Create a distinct custom cursor icon for Point, Rectangle, and Polygon modes."""
        size = 28
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.Antialiasing)

        # Crosshair at (10, 10) with high-contrast halo
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
            # Distinct target dot + outer ring badge
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
            painter.setBrush(QColor(0, 210, 255, 240))
            painter.drawEllipse(QPointF(cx, cy), 3.0, 3.0)
            painter.setPen(QPen(QColor(0, 180, 230, 240), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(20, 20), 4.5, 4.5)
        elif mode == MouseMode.RECTANGLE:
            # Distinct rectangle badge at bottom-right
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(14, 15, 11, 9)
            painter.setPen(QPen(QColor(59, 130, 246, 250), 1.5))
            painter.setBrush(QColor(59, 130, 246, 70))
            painter.drawRect(14, 15, 11, 9)
        elif mode == MouseMode.POLYGON:
            # Distinct polygon badge with vertex nodes at bottom-right
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
        """Create a custom cursor with the given color and shape."""
        pixmap = QPixmap(self.brush_size * 2, self.brush_size * 2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.black, 1))  # Border color for the cursor
        painter.setBrush(color)

        if shape == "circle":
            painter.drawEllipse(
                pixmap.rect().center(), self.brush_size, self.brush_size
            )
        elif shape == "square":
            painter.drawRect(pixmap.rect().adjusted(1, 1, -1, -1))

        painter.end()
        return QCursor(pixmap)

    def _create_zoom_cursor(self, zoom_in: bool) -> QCursor:
        """Create a magnifier-like cursor with plus/minus marker."""
        size = 24
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.Antialiasing)
        pen = QPen(Qt.black, 2)
        painter.setPen(pen)

        # Lens
        painter.drawEllipse(2, 2, 14, 14)
        # Handle
        painter.drawLine(13, 13, 21, 21)
        # Center marker
        painter.drawLine(6, 9, 12, 9)
        if zoom_in:
            painter.drawLine(9, 6, 9, 12)

        painter.end()
        return QCursor(pixmap, 2, 2)

    def set_image(self, image_path: Path | QPixmap | QImage):
        """
        Set the image for the layer from a file path, QPixmap, or QImage.
        """
        if isinstance(image_path, Path):
            self.file_path = image_path

            if image_path.exists():
                self.image.load(str(image_path))
                self.reset_view()
                self.update()
        elif isinstance(image_path, QPixmap):
            self.image = image_path
            self.reset_view()
            self.update()
        elif isinstance(image_path, QImage):
            self.image = QPixmap.fromImage(image_path)
            self.reset_view()
            self.update()

        self._original_image = self.image.copy()  # Store a copy of the original image
        self.original_size = QSizeF(self.image.size())  # Store original size

    @property
    def image(self):
        """
        Get the current image of the canvas layer.

        Returns:
            QPixmap: The current image of the canvas layer.
        """
        return self._image

    @image.setter
    def image(self, value: QPixmap):
        """
        Set the image of the canvas layer.

        Args:
            value (QPixmap): The new image for the canvas layer.
        """
        self._image = value

    def _apply_edge_opacity(self):
        """
        Apply edge opacity to the image. This function modifies the edges of the image
        to have reduced opacity based on the configuration.
        """
        logger.debug("Applying edge opacity to the image.")
        edge_width = self.edge_width
        edge_opacity = self.edge_opacity

        # Convert QPixmap to QImage for pixel manipulation
        image = self._original_image.toImage()
        image = image.convertToFormat(
            QImage.Format_ARGB32
        )  # Ensure format supports alpha

        width = image.width()
        height = image.height()
        annotation = self.annotations[0] if self.annotations else None
        if annotation is None:
            return

        if annotation.rectangle:
            for x in range(width):
                for y in range(height):
                    color = image.pixelColor(x, y)
                    if color.alpha() != 0:  # If the pixel is not fully transparent
                        # Calculate horizontal and vertical distances to the edges
                        horizontal_distance = min(x, width - x - 1)
                        vertical_distance = min(y, height - y - 1)

                        # If the pixel is within the edge region
                        if (
                            horizontal_distance < edge_width
                            or vertical_distance < edge_width
                        ):
                            distance_to_edge = min(
                                horizontal_distance, vertical_distance
                            )
                            # Calculate the new alpha based on the distance to the edge
                            factor = (edge_width - distance_to_edge) / edge_width
                            new_alpha = int(
                                color.alpha()
                                * ((1 - factor) + (factor * (edge_opacity / 255.0)))
                            )
                            color.setAlpha(new_alpha)
                            image.setPixelColor(x, y, color)

        elif annotation.polygon:
            # Extract alpha channel and find contours
            alpha_image = image.convertToFormat(QImage.Format_Alpha8)
            bytes_per_line = (
                alpha_image.bytesPerLine()
            )  # Get the stride (bytes per line)
            alpha_data = alpha_image.bits().tobytes()

            # Extract only the valid data (remove padding)
            alpha_array = np.frombuffer(alpha_data, dtype=np.uint8).reshape(
                (alpha_image.height(), bytes_per_line)
            )[
                :, : alpha_image.width()
            ]  # Remove padding to match the actual width

            # Use OpenCV to find contours
            contours, _ = cv2.findContours(
                alpha_array, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            # Iterate over each pixel and apply edge opacity
            for x in range(width):
                for y in range(height):
                    color = image.pixelColor(x, y)
                    if color.alpha() != 0:  # If the pixel is not fully transparent
                        # Calculate distance to the nearest contour
                        distance_to_edge = cv2.pointPolygonTest(
                            contours[0], (x, y), True
                        )  # True for distance calculation

                        # If the pixel is within the edge region
                        if 0 <= distance_to_edge < edge_width:
                            # Calculate the new alpha based on the distance to the edge
                            factor = (edge_width - distance_to_edge) / edge_width
                            new_alpha = int(
                                color.alpha()
                                * ((1 - factor) + (factor * (edge_opacity / 255.0)))
                            )
                            color.setAlpha(new_alpha)
                            image.setPixelColor(x, y, color)

        # Convert the modified QImage back to QPixmap
        self.image = QPixmap.fromImage(image)

    def get_thumbnail(self, annotation: Annotation = None):
        """
        Generate a thumbnail for the layer or a specific annotation.
        """
        image = QPixmap(*self.config.normal_draw_config.thumbnail_size)
        image.fill(Qt.transparent)

        if annotation:
            if annotation.rectangle:
                image = self.image.copy(annotation.rectangle.toRect())
            elif annotation.polygon:
                image = self.image.copy(annotation.polygon.boundingRect().toRect())
            elif annotation.points:
                # Create a small thumbnail around the point
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

    def copy(self):
        """
        Create a copy of the layer, including its properties and annotations.
        Should be overridden by subclasses to copy additional properties.
        """
        if hasattr(self, "canvas_config"):
            layer = self.__class__(self.parent_obj, self.config, self.canvas_config)
        else:
            layer = self.__class__(self.parent_obj, self.config)
        layer.set_image(self.image)
        layer.layer_state = self.layer_state.copy()
        layer.annotations = [ann.copy() for ann in self.annotations]
        # Copy child layers from the source layer (not from the new layer itself).
        layer.layers = [child.copy() for child in self.layers]
        layer.plugins = [
            plugin.copy() if hasattr(plugin, "copy") else plugin
            for plugin in self.plugins
        ]
        layer.layer_name = self.layer_name
        layer.file_path = Path(self.file_path)
        layer.position = self.position
        layer.rotation = self.rotation
        layer.scale = self.scale
        layer.scale_x = self.scale_x
        layer.scale_y = self.scale_y
        layer.opacity = self.opacity
        layer.visible = self.visible
        layer.selected = False
        layer.is_annotable = self.is_annotable
        return layer

    def set_mode(self, mode: MouseMode):
        """
        Set the mouse interaction mode for the layer.
        """
        # Preserve current annotation when changing modes
        if mode == self.mouse_mode:
            return

        # Only reset if switching to a different annotation mode
        if mode not in [MouseMode.POLYGON, MouseMode.RECTANGLE, MouseMode.POINT]:
            self.current_annotation = None

        self.mouse_mode = mode
        self.modeChanged.emit(mode)
        logger.debug(f"Layer {self.layer_id}: Mode set to {mode}")
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # return super().mouseDoubleClickEvent(event)
        pos = event.pos()
        self.handle_mouse_double_click(event, pos)
        self.update()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()
        self._mouse_widget_pos = (
            event.position() if hasattr(event, "position") else QPointF(event.pos())
        )
        self.handle_mouse_press(event)

        self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        self._mouse_widget_pos = (
            event.position() if hasattr(event, "position") else QPointF(event.pos())
        )
        self.handle_mouse_move(event)
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):

        self.handle_mouse_release(event)
        self.update()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._mouse_widget_pos = None
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        self.handle_wheel(event)
        self.update()
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        self.handle_key_press(event)
        self.update()
        if event.isAccepted():
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if self.is_annotable:
            self.handle_key_release(event)
        else:
            self.handle_key_release(event)
        self.update()

    def handle_mouse_double_click(self, event, pos):
        raise NotImplementedError

    def handle_mouse_press(self, event):
        """
        Handle mouse press events for selecting layers, initiating transformations,
        or starting drawing/erasing operations.

        Args:
            event (QMouseEvent): The mouse press event.
        """
        raise NotImplementedError

    def handle_mouse_move(self, event):
        """
        Handle mouse move events for panning, drawing, erasing, or transforming layers.

        Args:
            event (QMouseEvent): The mouse move event.
        """
        raise NotImplementedError

    def handle_mouse_release(self, event):
        """
        Handle mouse release events, such as resetting the active handle or stopping
        drawing/erasing operations.

        Args:
            event (QMouseEvent): The mouse release event.
        """
        raise NotImplementedError

    def handle_wheel(self, event):
        """
        Handle mouse wheel events for adjusting the brush size or zooming the canvas.

        Args:
            event (QWheelEvent): The wheel event.
        """
        raise NotImplementedError

    def handle_key_press(self, event):
        raise NotImplementedError

    def handle_key_release(self, event):
        raise NotImplementedError

    def reset_view(self):
        self.scale = 1.0
        self.offset = QPointF(0, 0)

    def clear_annotations(self):
        self.annotations.clear()
        self.selected_annotation = None
        self.current_annotation = None
        self.annotationCleared.emit()
        self.update()

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

        # 1. Deep Fine Grid Lines
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

        # 2. Medium Grid Lines
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

        # 3. Major Grid Lines
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

        # 4. Image Boundary Frame
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

        # 5. Interactive Snapping Crosshair and Coordinate Indicator
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
            # Keep the grid in front of layer content.
            self._draw_grid_overlay(painter)
        finally:
            painter.end()

    def paint_layer(self, painter: QPainter):
        raise NotImplementedError

    def __del__(self):
        if hasattr(self, "layer_state"):
            logger.debug(f"Layer {self.layer_id}: {self.layer_name} deleted.")

    # override update to store last state
    def update(self):
        self._last_state = self.layer_state
        self.update_cursor()
        super().update()

    def undo(self):
        if self._last_state is not None:
            self.layer_state = self._last_state
            self.update()

    # Layer ID Property
    @property
    def layer_id(self) -> int:
        return self.layer_state.layer_id

    @layer_id.setter
    def layer_id(self, value: int):
        self.layer_state.layer_id = value

    @property
    def is_annotable(self) -> bool:
        return self.layer_state.is_annotable

    @is_annotable.setter
    def is_annotable(self, value: bool):
        self.layer_state.is_annotable = value

    # Layer Name Property
    @property
    def layer_name(self) -> str:
        return self.layer_state.layer_name

    @layer_name.setter
    def layer_name(self, value: str):
        self.layer_state.layer_name = value

    # Position Property
    @property
    def position(self) -> QPointF:
        return self.layer_state.position

    @position.setter
    def position(self, value: QPointF):
        self.layer_state.position = value

    # Rotation Property
    @property
    def rotation(self) -> float:
        return self.layer_state.rotation

    @rotation.setter
    def rotation(self, value: float):
        self.layer_state.rotation = value

    # Scale Property
    @property
    def scale(self) -> float:
        return self.layer_state.scale

    @scale.setter
    def scale(self, value: float):
        self.layer_state.scale = value

    # Scale X Property
    @property
    def scale_x(self) -> float:
        return self.layer_state.scale_x

    @scale_x.setter
    def scale_x(self, value: float):
        self.layer_state.scale_x = value

    # Scale Y Property
    @property
    def scale_y(self) -> float:
        return self.layer_state.scale_y

    @scale_y.setter
    def scale_y(self, value: float):
        self.layer_state.scale_y = value

    # Transform Origin Property
    @property
    def transform_origin(self) -> QPointF:
        return self.layer_state.transform_origin

    @transform_origin.setter
    def transform_origin(self, value: QPointF):
        self.layer_state.transform_origin = value

    # Order Property
    @property
    def order(self) -> int:
        return self.layer_state.order

    @order.setter
    def order(self, value: int):
        self.layer_state.order = value

    # Visibility Property
    @property
    def visible(self) -> bool:
        return self.layer_state.visible

    @visible.setter
    def visible(self, value: bool):
        self.layer_state.visible = value

    # Annotation Export Property
    @property
    def allow_annotation_export(self) -> bool:
        return self.layer_state.allow_annotation_export

    @allow_annotation_export.setter
    def allow_annotation_export(self, value: bool):
        self.layer_state.allow_annotation_export = value

    @property
    def playing(self) -> bool:
        return self.layer_state.playing

    @playing.setter
    def playing(self, value: bool):
        self.layer_state.playing = value

    @property
    def selected(self) -> bool:
        return self.layer_state.selected

    @selected.setter
    def selected(self, value: bool):
        self.layer_state.selected = value

    @property
    def opacity(self) -> float:
        return self.layer_state.opacity

    @opacity.setter
    def opacity(self, value: float):
        self.layer_state.opacity = value

    @property
    def status(self) -> str:
        return self.layer_state.status

    @status.setter
    def status(self, value: str):
        self.layer_state.status = value

    @property
    def drawing_states(self) -> list[DrawingState]:
        return self.layer_state.drawing_states

    @drawing_states.setter
    def drawing_states(self, value: list[DrawingState]):
        self.layer_state.drawing_states = value

    @property
    def edge_opacity(self) -> int:
        return self.layer_state.edge_opacity

    @edge_opacity.setter
    def edge_opacity(self, value: int):
        self.layer_state.edge_opacity = value

    @property
    def edge_width(self) -> int:
        return self.layer_state.edge_width

    @edge_width.setter
    def edge_width(self, value: int):
        self.layer_state.edge_width = value

    @property
    def caption(self) -> str:
        return self.layer_state.caption

    @caption.setter
    def caption(self, value: str):
        self.layer_state.caption = value
