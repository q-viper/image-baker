from pathlib import Path

from PySide6.QtCore import QPointF, QSize, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QWidget

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig, LayerConfig
from imagebaker.core.defs import Annotation, DrawingState, LayerState, MouseMode
from imagebaker.layers.base_cursors import BaseCursorMixin
from imagebaker.layers.base_properties import BasePropertiesMixin
from imagebaker.layers.base_rendering import BaseRenderMixin
from imagebaker.utils.state_utils import calculate_intermediate_states


class BaseLayer(
    BaseCursorMixin,
    BaseRenderMixin,
    BasePropertiesMixin,
    QWidget,
):
    """Base Qt widget layer handling shared state, events, cursors, and grid rendering."""

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
        self.pan_offset: QPointF = QPointF(0, 0)
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
        self.last_pan_point = None
        self._dragging_layer = None
        self._drag_offset = QPointF(0, 0)
        self._current_hover = None
        self._active_handle = None
        self._transform_start = None
        self._is_panning = False
        self._mouse_widget_pos: QPointF | None = None
        self.copied_layer: BaseLayer = None
        self.selected_layer: BaseLayer = None
        self.prev_mouse_mode = MouseMode.IDLE

        self.states: dict[int, list[LayerState]] = {}
        self.previous_state = None
        self.current_step = 0
        self.drawing_color = QColor(Qt.red)
        self.brush_size = 5

        if isinstance(config, LayerConfig):
            self.current_label = self.config.predefined_labels[0].name
            self.current_color = self.config.predefined_labels[0].color

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def get_layer(self, id: str) -> "BaseLayer":
        """Get a child layer by its ID."""
        for layer in self.layers:
            if layer.layer_id == id:
                return layer
        return None

    def save_current_state(self, steps: int = 1):
        """
        Save the current state of the layer, including intermediate states
        calculated between the previous and current states.
        """
        curr_states = {}
        mode = self.mouse_mode

        for layer in self.layers:
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
                state.drawing_states = [
                    DrawingState(
                        position=d.position,
                        color=d.color,
                        size=d.size,
                    )
                    for d in layer.layer_state.drawing_states
                ]
                curr_states[step].append(state)

            layer.previous_state = layer.layer_state.copy()
            layer.selected = is_selected

        for step, states in curr_states.items():
            self.states[step] = states
            self.current_step = step

        self.previous_state = self.layer_state.copy()
        self.layer_state.drawing_states = [
            DrawingState(
                position=d.position,
                color=d.color,
                size=d.size,
            )
            for d in self.layer_state.drawing_states
        ]

        self.messageSignal.emit(f"Saved state {self.current_step}")
        self.mouse_mode = mode
        self.update()

    def minimumSizeHint(self):
        """Return the minimum size hint for the widget."""
        return QSize(100, 100)

    def set_image(self, image_path: Path | QPixmap | QImage):
        """Set the image for the layer from a file path, QPixmap, or QImage."""
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

        self._original_image = self.image.copy()
        self.original_size = QSizeF(self.image.size())

    @property
    def image(self):
        """Get the current image of the canvas layer."""
        return self._image

    @image.setter
    def image(self, value: QPixmap):
        """Set the image of the canvas layer."""
        self._image = value

    def copy(self):
        """Create a copy of the layer, including its properties and annotations."""
        if hasattr(self, "canvas_config"):
            layer = self.__class__(self.parent_obj, self.config, self.canvas_config)
        else:
            layer = self.__class__(self.parent_obj, self.config)
        layer.set_image(self.image)
        layer.layer_state = self.layer_state.copy()
        layer.annotations = [ann.copy() for ann in self.annotations]
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
        """Set the mouse interaction mode for the layer."""
        if mode == self.mouse_mode:
            return
        if mode not in [MouseMode.POLYGON, MouseMode.RECTANGLE, MouseMode.POINT]:
            self.current_annotation = None
        self.mouse_mode = mode
        self.modeChanged.emit(mode)
        logger.debug(f"Layer {self.layer_id}: Mode set to {mode}")
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
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

    def __del__(self):
        if hasattr(self, "layer_state"):
            logger.debug(f"Layer {self.layer_id}: {self.layer_name} deleted.")

    def update(self):
        self._last_state = self.layer_state
        self.update_cursor()
        super().update()

    def undo(self):
        if self._last_state is not None:
            self.layer_state = self._last_state
            self.update()
