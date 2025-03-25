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
    QPolygonF,
    QWheelEvent,
    QMouseEvent,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QInputDialog,
    QSizePolicy,
    QMessageBox,
    QProgressDialog,
)

from typing import Optional
from pathlib import Path

from imagebaker.core.configs import LayerConfig, CursorDef
from imagebaker.core.defs import Annotation, MouseMode, LayerState
from imagebaker.workers import LayerifyWorker
from imagebaker import logger


class BaseLayer(QWidget):
    def __init__(
        self, parent: Optional[QWidget] = None, config: LayerConfig = LayerConfig()
    ):
        super().__init__(parent)
        self.layer_state = LayerState()
        self.layer_state.layer_id = id(self)
        self.thumbnails = {}
        self.label_rects = []
        self._last_state = None

    # override update to store last state
    def update(self):
        self._last_state = self.layer_state
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
    def opacity(self) -> int:
        return self.layer_state.opacity

    @opacity.setter
    def opacity(self, value: int):
        self.layer_state.opacity = value
