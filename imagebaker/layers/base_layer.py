from imagebaker.core.configs import LayerConfig, CanvasConfig, CursorDef
from imagebaker.core.defs import Annotation, MouseMode, LayerState, DrawingState
from imagebaker.utils.state_utils import calculate_intermediate_states
from imagebaker import logger

from PySide6.QtCore import QPointF, QPoint, Qt, Signal, QSizeF, QSize
from PySide6.QtGui import (
    QColor,
    QPixmap,
    QPainter,
    QMouseEvent,
    QKeyEvent,
    QImage,
    QPen,
    QCursor,
)
from PySide6.QtWidgets import QWidget

from typing import Optional
from pathlib import Path


class BaseLayer(QWidget):
    messageSignal = Signal(str)
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
        self.image = QPixmap()
        self.annotations: list[Annotation] = []
        self.current_annotation: Optional[Annotation] = None
        self.copied_annotation: Optional[Annotation] = None
        self.selected_annotation: Optional[Annotation] = None

        self.layers: list[BaseLayer] = []
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
        self.offset = QPointF(0, 0)
        self.copied_layer: BaseLayer = None
        self.selected_layer: BaseLayer = None
        self.mouse_mode = MouseMode.IDLE
        self.prev_mouse_mode = MouseMode.IDLE
        self.states: dict[str, list[LayerState]] = dict()

        self.states: dict[int, list[LayerState]] = dict()
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

                logger.info(f"Saving state {step} for layer {layer.layer_id}")
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
        """
        if MouseMode.POINT == self.mouse_mode:
            self.setCursor(CursorDef.POINT_CURSOR)
        elif MouseMode.RECTANGLE == self.mouse_mode:
            self.setCursor(CursorDef.RECTANGLE_CURSOR)
        elif MouseMode.POLYGON == self.mouse_mode:
            self.setCursor(CursorDef.POLYGON_CURSOR)
        elif MouseMode.PAN == self.mouse_mode:
            self.setCursor(CursorDef.PAN_CURSOR)
        elif MouseMode.IDLE == self.mouse_mode:
            self.setCursor(CursorDef.IDLE_CURSOR)
        elif MouseMode.RESIZE == self.mouse_mode:
            self.setCursor(CursorDef.RECTANGLE_CURSOR)
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

        self.original_size = QSizeF(self.image.size())  # Store original size

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
        layer = self.__class__(self.parent_obj, self.config)
        layer.set_image(self.image)
        layer.annotations = [ann.copy() for ann in self.annotations]
        layer.layers = [layer.copy() for layer in self.layers]
        layer.layer_name = self.layer_name
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
        logger.debug(f"Layer {self.layer_id}: Mode set to {mode}")
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # return super().mouseDoubleClickEvent(event)
        pos = event.pos()
        self.handle_mouse_double_click(event, pos)
        self.update()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        self.handle_mouse_press(event)

        self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):

        self.handle_mouse_move(event)
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):

        self.handle_mouse_release(event)
        self.update()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.handle_wheel(event)
        self.update()
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        self.handle_key_press(event)
        self.update()
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

    def paintEvent(self, event):
        self.paint_event()

    def paint_event(self):
        painter = QPainter(self)

        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        painter.fillRect(
            self.rect(),
            QColor(
                self.config.normal_draw_config.background_color.red(),
                self.config.normal_draw_config.background_color.green(),
                self.config.normal_draw_config.background_color.blue(),
            ),
        )
        self.paint_layer(painter)

    def paint_layer(self, painter: QPainter):
        raise NotImplementedError

    def __del__(self):
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
