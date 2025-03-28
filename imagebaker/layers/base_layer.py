from imagebaker.core.configs import LayerConfig, CanvasConfig, CursorDef
from imagebaker.core.defs import Annotation, MouseMode, LayerState
from imagebaker import logger
from imagebaker.utils.state_utils import calculate_intermediate_states

from PySide6.QtCore import QPointF, QPoint, Qt, Signal, QSizeF, QSize
from PySide6.QtGui import QColor, QPixmap, QPainter, QMouseEvent, QKeyEvent, QImage
from PySide6.QtWidgets import (
    QWidget,
)

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

        if isinstance(config, LayerConfig):
            self.current_label = self.config.predefined_labels[0].name
            self.current_color = self.config.predefined_labels[0].color

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def get_layer(self, id: str) -> "BaseLayer":
        for layer in self.layers:
            if layer.layer_id == id:
                return layer
        return None

    def save_current_state(self, steps: int = 1):
        """
        Save the current state of all layers, including intermediate states
        calculated between the previous state and the current state.
        """
        curr_states = {}

        for layer in self.layers:
            # Calculate intermediate states between previous_state and current_state
            intermediate_states = calculate_intermediate_states(
                layer.previous_state, layer.layer_state.copy(), steps
            )

            for step, state in enumerate(intermediate_states):
                if step not in curr_states:
                    curr_states[step] = []
                curr_states[step].append(state)
            # Update the layer's previous_state to the current state
            layer.previous_state = layer.layer_state.copy()

        # Save the calculated states in self.states
        for step, states in curr_states.items():
            self.states[step] = states
            self.current_step = step
        self.previous_state = self.layer_state.copy()

        # Emit a message signal indicating the state has been saved
        self.messageSignal.emit(f"Saved state {self.current_step}")

    def minimumSizeHint(self):
        return QSize(100, 100)

    def widget_to_image_pos(self, pos: QPointF) -> QPointF:
        return QPointF(
            (pos.x() - self.offset.x()) / self.scale,
            (pos.y() - self.offset.y()) / self.scale,
        )

    def update_cursor(self):
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

    def set_image(self, image_path: Path | QPixmap | QImage):
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

    # def apply_opacity(self):
    #     """Apply opacity to the QPixmap image."""
    #     if self.image and self.opacity < 1:
    #         # Create a new transparent pixmap with the same size
    #         transparent_pixmap = QPixmap(self.image.size())
    #         transparent_pixmap.fill(Qt.transparent)

    #         # Create a painter to draw on the new pixmap
    #         painter = QPainter(transparent_pixmap)
    #         try:
    #             # Set the opacity
    #             painter.setOpacity(self.opacity)

    #             # Draw the original image onto the new pixmap
    #             painter.drawPixmap(0, 0, self.image)
    #         finally:
    #             # Ensure the painter is properly ended
    #             painter.end()

    #         # Replace the original image with the transparent version
    #         self.image = transparent_pixmap

    def copy(self):
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
        raise NotImplementedError

    def handle_mouse_move(self, event):
        raise NotImplementedError

    def handle_mouse_release(self, event):
        raise NotImplementedError

    def handle_wheel(self, event):
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
                10,
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
