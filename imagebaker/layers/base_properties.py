"""LayerState-backed properties for BaseLayer."""

from PySide6.QtCore import QPointF

from imagebaker.core.defs import DrawingState


class BasePropertiesMixin:
    """Mixin delegating layer metadata and transform properties to layer_state."""

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

    @property
    def layer_name(self) -> str:
        return self.layer_state.layer_name

    @layer_name.setter
    def layer_name(self, value: str):
        self.layer_state.layer_name = value

    @property
    def position(self) -> QPointF:
        return self.layer_state.position

    @position.setter
    def position(self, value: QPointF):
        self.layer_state.position = value

    @property
    def rotation(self) -> float:
        return self.layer_state.rotation

    @rotation.setter
    def rotation(self, value: float):
        self.layer_state.rotation = value

    @property
    def scale(self) -> float:
        return self.layer_state.scale

    @scale.setter
    def scale(self, value: float):
        self.layer_state.scale = value

    @property
    def scale_x(self) -> float:
        return self.layer_state.scale_x

    @scale_x.setter
    def scale_x(self, value: float):
        self.layer_state.scale_x = value

    @property
    def scale_y(self) -> float:
        return self.layer_state.scale_y

    @scale_y.setter
    def scale_y(self, value: float):
        self.layer_state.scale_y = value

    @property
    def transform_origin(self) -> QPointF:
        return self.layer_state.transform_origin

    @transform_origin.setter
    def transform_origin(self, value: QPointF):
        self.layer_state.transform_origin = value

    @property
    def order(self) -> int:
        return self.layer_state.order

    @order.setter
    def order(self, value: int):
        self.layer_state.order = value

    @property
    def visible(self) -> bool:
        return self.layer_state.visible

    @visible.setter
    def visible(self, value: bool):
        self.layer_state.visible = value

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
