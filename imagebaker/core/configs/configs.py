from pathlib import Path
from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from pydantic import BaseModel, Field

from imagebaker.core.defs import Label, ModelType
from imagebaker import logger


class DrawConfig(BaseModel):
    color: QColor = Field(default_factory=lambda: QColor(255, 255, 255))
    point_size: int = 5
    line_width: int = 5
    control_point_size: int = 1.5
    ellipse_size: int = 8
    pen_alpha: int = 150
    brush_alpha: int = 50
    brush_fill_pattern: Qt.BrushStyle = Qt.BrushStyle.DiagCrossPattern
    thumbnail_size: Tuple[int, int] = Field(default_factory=lambda: (50, 50))
    background_color: QColor = Field(default_factory=lambda: QColor(0, 0, 0, 255))
    label_font_size: int = 12
    label_font_background_color: QColor = Field(
        default_factory=lambda: QColor(0, 0, 0, 150)
    )
    handle_color: QColor = Field(default_factory=lambda: QColor(0, 255, 255, 150))
    handle_width: int = 5
    handle_point_size: int = 8
    handle_edge_size: int = 5

    button_width: int = 30

    class Config:
        arbitrary_types_allowed = True


class BaseConfig(BaseModel):
    project_name: str = "ImageBaker"
    version: str = "0.1.0"
    project_dir: Path = Path(".")

    is_debug: bool = True
    deque_maxlen: int = 10

    # drawing configs #
    # ON SELECTION
    selected_draw_config: DrawConfig = DrawConfig(
        color=QColor(255, 0, 0),
        point_size=5,
        line_width=5,
        ellipse_size=8,
        pen_alpha=150,
        brush_alpha=50,
        thumbnail_size=(50, 50),
        brush_fill_pattern=Qt.BrushStyle.CrossPattern,
    )
    normal_draw_config: DrawConfig = DrawConfig()
    zoom_in_factor: float = 1.1
    zoom_out_factor: float = 0.9

    @property
    def assets_folder(self):
        asset_dir = self.project_dir / "assets"
        if not asset_dir.exists():
            asset_dir.mkdir(parents=True)
            logger.info(f"Created assets folder at {asset_dir}")
        return asset_dir

    class Config:
        arbitrary_types_allowed = True


class LayerConfig(BaseConfig):
    show_labels: bool = True
    show_annotations: bool = True

    default_label: Label = Field(
        default_factory=lambda: Label("Unlabeled", QColor(255, 255, 255))
    )
    predefined_labels: List[Label] = Field(
        default_factory=lambda: [
            Label("Unlabeled", QColor(255, 255, 255)),
            Label("Label 1", QColor(255, 0, 0)),
            Label("Label 2", QColor(0, 255, 0)),
            Label("Label 3", QColor(0, 0, 255)),
            Label("Custom", QColor(128, 128, 128)),
        ]
    )

    def get_label_color(self, label):
        for lbl in self.predefined_labels:
            if lbl.name == label:
                return lbl.color
        return self.default_label.color


class CanvasConfig(BaseConfig):
    save_on_bake: bool = True
    bake_timeout: float = -1.0
    filename_format: str = "{project_name}_{timestamp}"
    export_format: str = "png"
    max_xpos: int = 1000
    max_ypos: int = 1000
    max_scale: int = 1000
    # whether to allow the use of sliders to change layer properties
    allow_slider_usage: bool = True

    write_annotations: bool = True
    write_labels: bool = True
    write_masks: bool = True
    fps: int = 5

    @property
    def export_folder(self):
        folder = self.project_dir / "assets" / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        return folder


class CursorDef:
    POINT_CURSOR: Qt.CursorShape = Qt.CrossCursor
    POLYGON_CURSOR: Qt.CursorShape = Qt.CrossCursor
    RECTANGLE_CURSOR: Qt.CursorShape = Qt.CrossCursor
    IDLE_CURSOR: Qt.CursorShape = Qt.ArrowCursor
    PAN_CURSOR: Qt.CursorShape = Qt.OpenHandCursor
    ZOOM_IN_CURSOR: Qt.CursorShape = Qt.SizeFDiagCursor
    ZOOM_OUT_CURSOR: Qt.CursorShape = Qt.SizeBDiagCursor
    TRANSFORM_UPDOWN: Qt.CursorShape = Qt.SizeVerCursor
    TRANSFORM_LEFTRIGHT: Qt.CursorShape = Qt.SizeHorCursor
    TRANSFORM_ALL: Qt.CursorShape = Qt.SizeAllCursor
    GRAB_CURSOR: Qt.CursorShape = Qt.OpenHandCursor
    GRABBING_CURSOR: Qt.CursorShape = Qt.ClosedHandCursor
    DRAW_CURSOR: Qt.CursorShape = Qt.CrossCursor
    ERASE_CURSOR: Qt.CursorShape = Qt.CrossCursor


class DefaultModelConfig(BaseModel):
    model_type: ModelType = ModelType.DETECTION
    model_name: str = "Dummy Model"
    model_description: str = "This is a dummy model"
    model_version: str = "1.0"
    model_author: str = "Anonymous"
    model_license: str = "MIT"
    input_size: Tuple[int, int] = (224, 224)
    input_channels: int = 3
    class_names: List[str] = ["class1", "class2", "class3"]
    device: str = "cpu"
    return_annotated_image: bool = False

    @property
    def num_classes(self):
        return len(self.class_names)

    class Config:
        arbitrary_types_allowed = True
